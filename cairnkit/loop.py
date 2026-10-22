# Adapted from hermes-agent v0.22.2 (d923a5e): agent/conversation_loop.py,
# agent/turn_tool_round.py, agent/turn_tool_validation.py. Copyright (c) 2025 Nous Research.
# MIT License. Rewritten as an async loop without the CLI/gateway concerns.
"""The agent loop: call the model, run the tools it asks for, repeat, answer.

Invariants kept from Hermes:
* the system prompt is fixed for the conversation (pass it back on later turns);
* invalid tool calls are answered with tool-role errors, never synthetic user messages;
* the tool-call event fires *before* the tool runs, so hosts can persist it first;
* a per-turn guardrail stops identical retries and runaway failures;
* after the iteration budget, one last call without tools forces a plain answer;
* when the context gets long, the compressor rewrites the middle of the conversation
  (the only sanctioned edit of past context) before the next model call.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from cairnkit.agents import AgentSpec
from cairnkit.compression import CompressionResult, CompressionState, ContextCompressor
from cairnkit.guardrails import GuardrailController
from cairnkit.llm.base import ChatModel
from cairnkit.llm.errors import classify_error
from cairnkit.llm.fallback import AllModelsFailed
from cairnkit.prompt import PromptParts, build_system_prompt
from cairnkit.skills import SkillLibrary
from cairnkit.tools import ToolContext, ToolRegistry, ToolSpec, tool_error
from cairnkit.types import Message, ToolCall, Usage

StopReason = Literal["completed", "max_iterations", "guardrail"]


@dataclass(frozen=True)
class RunEvent:
    kind: Literal["tool_call", "tool_result", "guardrail", "text_delta", "compressed"]
    data: dict[str, Any]


EventHandler = Callable[[RunEvent], Awaitable[None] | None]


@dataclass
class ToolRecord:
    name: str
    arguments: dict[str, Any] | None
    result: str
    failed: bool


@dataclass
class RunResult:
    text: str | None
    system_prompt: str
    messages: list[Message]
    tool_records: list[ToolRecord] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    stop_reason: StopReason = "completed"
    compressed: bool = False
    compression: CompressionResult | None = None  # the last compaction in this run
    compression_state: CompressionState | None = None  # persist it with the conversation
    # Summary-model calls made by compaction in this run (``usage`` is the agent's own).
    compression_usage: Usage = field(default_factory=Usage)


@dataclass
class _RunScope:
    """Per-run settings, so one Agent can serve concurrent conversations."""

    on_event: EventHandler | None
    stream: bool
    state: CompressionState
    tried_compression: bool = False  # one automatic attempt per run; overflow may force more


class Agent:
    def __init__(
        self,
        spec: AgentSpec,
        *,
        model: ChatModel,
        tools: ToolRegistry | None = None,
        skills: SkillLibrary | None = None,
        compressor: ContextCompressor | None = None,
    ):
        self.spec = spec
        self.model = model
        self.compressor = compressor
        self._skills = skills or SkillLibrary()
        self._registry = ToolRegistry()
        host = tools or ToolRegistry()
        for name in spec.tools:
            tool = host.get(name)
            if tool is None:
                raise ValueError(
                    f"agent {spec.name!r} needs tool {name!r}, which is not registered"
                )
            self._registry.register(tool)
        missing = [s for s in spec.skills if self._skills.get(s) is None]
        if missing:
            raise ValueError(f"agent {spec.name!r} needs skills that are not loaded: {missing}")
        if spec.skills:
            self._skills.register_tools(self._registry, spec.skills)

    def system_prompt(
        self, *, context: list[str] | None = None, volatile: list[str] | None = None
    ) -> str:
        return build_system_prompt(
            PromptParts(
                stable=[self.spec.persona],
                context=list(context or []),
                volatile=[self._skills.index_prompt(self.spec.skills), *(volatile or [])],
            )
        )

    async def run(
        self,
        user_message: str,
        ctx: ToolContext,
        *,
        history: list[Message] | None = None,
        system_prompt: str | None = None,
        context: list[str] | None = None,
        volatile: list[str] | None = None,
        on_event: EventHandler | None = None,
        stream: bool = False,
        compression_state: CompressionState | None = None,
    ) -> RunResult:
        """Run one user turn. Pass ``system_prompt`` from the first turn on later turns.

        With ``stream=True`` answer text arrives as ``text_delta`` events while it is
        generated; tool calls still arrive whole. Pass the conversation's
        ``compression_state`` (and store ``result.compression_state`` afterwards) so
        compaction can anchor on real token counts and update its previous summary."""
        system = system_prompt or self.system_prompt(context=context, volatile=volatile)
        messages: list[Message] = [
            {"role": "system", "content": system},
            *(history or []),
            {"role": "user", "content": user_message},
        ]
        tools = self._registry.available(None, ctx)
        by_name = {t.name: t for t in tools}
        schemas = [t.schema() for t in tools] or None
        guard = GuardrailController(self.spec.guardrails)
        state = compression_state or CompressionState()
        result = RunResult(
            text=None, system_prompt=system, messages=messages, compression_state=state
        )
        run = _RunScope(on_event=on_event, stream=stream, state=state)

        for _ in range(self.spec.max_iterations):
            await self._maybe_compress(result, run)
            messages = result.messages
            response = await self._call(messages, schemas, result, run)
            if not response.tool_calls:
                messages.append(response.to_message())
                result.text = response.content
                return result
            messages.append(response.to_message())
            halted = False
            for call in response.tool_calls:
                content, halted = await self._run_tool(call, by_name, ctx, guard, result, on_event)
                messages.append({"role": "tool", "tool_call_id": call.id, "content": content})
            if halted:
                result.stop_reason = "guardrail"
                break
        else:
            result.stop_reason = "max_iterations"

        # Budget spent or loop stopped: one call without tools forces a plain answer.
        await self._maybe_compress(result, run)
        messages = result.messages
        final = await self._call(messages, None, result, run)
        messages.append({"role": "assistant", "content": final.content})
        result.text = final.content
        return result

    async def _maybe_compress(
        self, result: RunResult, run: _RunScope, *, force: bool = False
    ) -> bool:
        if self.compressor is None or (run.tried_compression and not force):
            return False
        if not self.compressor.should_compress(result.messages, run.state, force=force)[0]:
            return False
        run.tried_compression = True
        compressed = await self.compressor.compress(result.messages, run.state, force=force)
        result.compression = compressed
        result.compression_usage.add(compressed.usage)
        if not compressed.changed:
            return False
        result.messages[:] = compressed.messages
        result.compressed = True
        await _emit(
            run.on_event,
            RunEvent(
                "compressed",
                {
                    "pruned_tool_results": compressed.pruned_tool_results,
                    "deduplicated_tool_results": compressed.deduplicated_tool_results,
                    "summarized_messages": compressed.summarized_messages,
                    "fallback": compressed.used_fallback,
                    "tokens_before": compressed.tokens_before,
                    "tokens_after": compressed.tokens_after,
                },
            ),
        )
        return True

    async def _call(
        self,
        messages: list[Message],
        schemas: list[dict] | None,
        result: RunResult,
        run: _RunScope,
    ):
        kwargs: dict = {
            "tools": schemas,
            "temperature": self.spec.temperature,
            "max_tokens": self.spec.max_tokens,
        }
        if run.stream:

            async def on_delta(text: str) -> None:
                await _emit(run.on_event, RunEvent("text_delta", {"text": text}))

            kwargs["on_delta"] = on_delta
        try:
            response = await self.model.complete(messages, **kwargs)
        except Exception as exc:
            # Provider-proven overflow: compact (even below our own threshold) and retry once.
            if not _is_overflow(exc) or not await self._maybe_compress(result, run, force=True):
                raise
            messages = result.messages
            response = await self.model.complete(messages, **kwargs)
        result.usage.add(response.usage)
        if self.compressor is not None:
            self.compressor.record_usage(
                run.state,
                response.usage.prompt_tokens,
                response.usage.completion_tokens,
                len(messages) + 1,  # the reply is covered by completion_tokens
            )
        return response

    async def _run_tool(
        self,
        call: ToolCall,
        by_name: dict[str, ToolSpec],
        ctx: ToolContext,
        guard: GuardrailController,
        result: RunResult,
        on_event: EventHandler | None,
    ) -> tuple[str, bool]:
        spec = by_name.get(call.name)
        if spec is None:
            available = ", ".join(sorted(by_name)) or "none"
            content = tool_error(f"unknown tool {call.name!r}; available tools: {available}")
            result.tool_records.append(ToolRecord(call.name, None, content, True))
            return content, False
        try:
            arguments = json.loads(call.arguments or "{}")
            if not isinstance(arguments, dict):
                raise ValueError
        except ValueError:
            content = tool_error("arguments must be a JSON object matching the tool's parameters")
            result.tool_records.append(ToolRecord(call.name, None, content, True))
            return content, False

        decision = guard.before_call(call.name, arguments)
        if not decision.allows_execution:
            await _emit(on_event, RunEvent("guardrail", {"tool": call.name, "code": decision.code}))
            result.tool_records.append(
                ToolRecord(call.name, arguments, tool_error(decision.message), True)
            )
            return tool_error(decision.message), True

        await _emit(
            on_event,
            RunEvent("tool_call", {"id": call.id, "tool": call.name, "arguments": arguments}),
        )
        outcome = await self._registry.dispatch(spec, arguments, ctx)
        result.tool_records.append(ToolRecord(call.name, arguments, outcome.result, outcome.failed))
        await _emit(
            on_event,
            RunEvent("tool_result", {"id": call.id, "tool": call.name, "failed": outcome.failed}),
        )
        after = guard.after_call(call.name, arguments, outcome.result, outcome.failed)
        if after.action == "halt":
            await _emit(on_event, RunEvent("guardrail", {"tool": call.name, "code": after.code}))
            return outcome.result + f"\n[{after.message}]", True
        if after.action == "warn":
            return outcome.result + f"\n[{after.message}]", False
        return outcome.result, False


async def _emit(handler: EventHandler | None, event: RunEvent) -> None:
    if handler is None:
        return
    value = handler(event)
    if value is not None:
        await value


def _is_overflow(exc: BaseException) -> bool:
    if isinstance(exc, AllModelsFailed):
        return any(err.should_compress for _, err in exc.errors)
    return classify_error(exc).should_compress
