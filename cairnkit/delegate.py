# Adapted from hermes-agent v0.22.2 (d923a5e): tools/delegate_tool.py
# Copyright (c) 2025 Nous Research. MIT License. Single-level, sequential delegation.
"""Hand a focused task to a child agent.

The child starts a fresh conversation with its own focused system prompt and its own
(narrower) tools. The parent only ever sees the delegation call and the child's final
answer, never the child's intermediate tool calls (Hermes contract). Children cannot
delegate further, and each parent turn may delegate a bounded number of times.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from cairnkit.tools import ToolContext, ToolError, ToolSpec, tool_result

if TYPE_CHECKING:
    from cairnkit.loop import Agent, RunResult

ChildRunHook = Callable[["Agent", "RunResult", ToolContext], None]
"""Called after each finished child run with the child, its result and the parent's context."""

DEPTH_KEY = "_delegation_depth"
COUNT_KEY = "_delegations"


def make_delegate_tool(
    children: dict[str, Agent],
    *,
    name: str = "delegate_task",
    max_per_turn: int = 3,
    roles: set[str] | None = None,
    on_child_run: ChildRunHook | None = None,
) -> ToolSpec:
    """``on_child_run`` sees every finished child run, e.g. to bill its usage (the parent's
    ``RunResult.usage`` covers only the parent's own model calls)."""
    if not children:
        raise ValueError("at least one child agent is required")
    catalog = "; ".join(f"'{n}': {a.spec.description}" for n, a in children.items())

    async def handler(args: dict[str, Any], ctx: ToolContext) -> str:
        if int(ctx.scope.get(DEPTH_KEY, 0)) >= 1:
            raise ToolError("delegated agents cannot delegate again; do the task yourself")
        counter = ctx.scope.get(COUNT_KEY)
        if isinstance(counter, list):
            if len(counter) >= max_per_turn:
                raise ToolError(
                    f"this turn already delegated {len(counter)} times (limit "
                    f"{max_per_turn}); finish with the results you have"
                )
            counter.append(args.get("agent"))
        child = children.get(str(args.get("agent", "")))
        if child is None:
            raise ToolError(f"agent must be one of {', '.join(children)}")
        goal = str(args.get("goal") or "").strip()
        if not goal:
            raise ToolError("goal is required: say exactly what the child should find or produce")
        context = str(args.get("context") or "").strip()
        child_ctx = ToolContext(
            principal=ctx.principal,
            roles=ctx.roles,
            scope={**ctx.scope, DEPTH_KEY: 1, COUNT_KEY: []},
        )
        message = f"Goal: {goal}" + (
            f"\n\nContext from the requester:\n{context}" if context else ""
        )
        result = await child.run(message, child_ctx)
        if on_child_run is not None:
            on_child_run(child, result, ctx)
        return tool_result(
            agent=child.spec.name,
            answer=result.text or "",
            stop_reason=result.stop_reason,
            tool_calls=len(result.tool_records),
        )

    return ToolSpec(
        name=name,
        description=(
            "Give a focused task to a specialist agent and get back only its final answer. "
            f"Use it for self-contained lookups or drafting. Agents: {catalog}."
        ),
        access="read",
        roles=frozenset(roles) if roles else None,
        handler=handler,
        parameters={
            "type": "object",
            "properties": {
                "agent": {"type": "string", "enum": list(children)},
                "goal": {"type": "string", "description": "What the specialist must deliver."},
                "context": {
                    "type": "string",
                    "description": "Facts it needs; it cannot see this chat.",
                },
            },
            "required": ["agent", "goal"],
        },
    )
