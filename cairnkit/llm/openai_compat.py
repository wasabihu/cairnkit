# Adapted from hermes-agent v0.23.0 (2bd378e): agent/chat_completion_helpers_tool_calls.py
# (streamed tool-call assembly). Copyright (c) 2025 Nous Research. MIT License.
"""Client for any OpenAI-compatible ``/chat/completions`` endpoint."""

from __future__ import annotations

import json
from typing import Any

import httpx

from cairnkit.llm.base import DeltaHandler, emit_delta
from cairnkit.llm.errors import ModelAPIError
from cairnkit.types import Message, ModelResponse, ToolCall, Usage

OPENROUTER_URL = "https://openrouter.ai/api/v1"


class OpenAICompatModel:
    def __init__(
        self,
        model: str,
        *,
        base_url: str,
        api_key: str,
        extra_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        if not api_key:
            raise ValueError("api_key is required")
        self.name = model
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}", **(headers or {})}
        self._extra_body = extra_body or {}
        self._timeout = timeout
        self._transport = transport

    async def complete(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        on_delta: DeltaHandler | None = None,
    ) -> ModelResponse:
        body: dict[str, Any] = {"model": self.name, "messages": messages, **self._extra_body}
        if tools:
            body["tools"] = tools
        if temperature is not None:
            body["temperature"] = temperature
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if on_delta is not None:
            return await self._stream(body, on_delta)
        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            response = await client.post(self._url, json=body, headers=self._headers)
        payload = _json(response)
        if response.status_code >= 400:
            raise ModelAPIError(response.status_code, _error_message(payload, response), payload)
        # Some gateways answer 200 with an error object instead of choices.
        if isinstance(payload, dict) and payload.get("error") and not payload.get("choices"):
            error = payload["error"]
            code = error.get("code") if isinstance(error, dict) else None
            raise ModelAPIError(
                code if isinstance(code, int) else 502, _error_message(payload, response), payload
            )
        return _parse(payload, self.name)

    async def _stream(self, body: dict[str, Any], on_delta: DeltaHandler) -> ModelResponse:
        body = {**body, "stream": True, "stream_options": {"include_usage": True}}
        content: list[str] = []
        calls = _ToolCallAccumulator()
        final: dict[str, Any] = {"model": self.name, "finish_reason": None, "usage": {}}
        async with (
            httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client,
            client.stream("POST", self._url, json=body, headers=self._headers) as response,
        ):
            if response.status_code >= 400:
                await response.aread()
                payload = _json(response)
                raise ModelAPIError(
                    response.status_code, _error_message(payload, response), payload
                )
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue  # SSE comments (": OPENROUTER PROCESSING") and blank lines
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except ValueError:
                    continue
                if isinstance(chunk.get("error"), dict):
                    error = chunk["error"]
                    code = error.get("code") if isinstance(error.get("code"), int) else 502
                    raise ModelAPIError(code, str(error.get("message", "stream error")), chunk)
                final["model"] = chunk.get("model") or final["model"]
                if chunk.get("usage"):
                    final["usage"] = chunk["usage"]
                for choice in chunk.get("choices") or []:
                    delta = choice.get("delta") or {}
                    if text := delta.get("content"):
                        content.append(text)
                        await emit_delta(on_delta, text)
                    for raw in delta.get("tool_calls") or []:
                        calls.feed(raw)
                    final["finish_reason"] = choice.get("finish_reason") or final["finish_reason"]
        message = {
            "content": "".join(content) or None,
            "tool_calls": [
                {
                    "id": c["id"] or f"call_{i}",
                    "function": {"name": c["name"], "arguments": "".join(c["args"])},
                }
                for i, c in sorted(calls.slots.items())
            ],
        }
        return _parse(
            {
                "model": final["model"],
                "usage": final["usage"],
                "choices": [{"message": message, "finish_reason": final["finish_reason"]}],
            },
            self.name,
        )


class _ToolCallAccumulator:
    """Assemble streamed tool-call deltas into whole calls (slot -> id, name, argument parts).

    Ollama-compatible endpoints reuse index 0 for every call of a parallel batch, told apart
    only by id, so a new id at a seen index can open a new slot. LM Studio and Kimi send a fresh
    id on every argument fragment without a name, and some MiniMax routes resend the same name
    with each fragment: only a named delta opens a call, and one with the current call's name
    only after that call's arguments have closed.
    """

    def __init__(self) -> None:
        self.slots: dict[int, dict[str, Any]] = {}
        self._slot_by_index: dict[int, int] = {}
        self._last_id: dict[int, str] = {}
        # slot -> (fragments scanned, depth, in_string, escaped, started)
        self._scan: dict[int, tuple[int, int, bool, bool, bool]] = {}

    def feed(self, raw: dict[str, Any]) -> None:
        index = raw.get("index")
        index = index if isinstance(index, int) else 0
        call_id = str(raw.get("id") or "")
        function = raw.get("function") or {}
        slot = self._slot_by_index.setdefault(index, index)
        last = self._last_id.get(index)
        if (
            call_id
            and last is not None
            and call_id != last
            and self._starts_new_call(function, slot)
        ):
            slot = self._slot_by_index[index] = max(self.slots, default=-1) + 1
        if call_id:
            self._last_id[index] = call_id
        entry = self.slots.setdefault(slot, {"id": "", "name": "", "args": []})
        entry["id"] = call_id or entry["id"]
        # Assignment, not +=: some providers resend the full name with every chunk.
        entry["name"] = function.get("name") or entry["name"]
        if function.get("arguments"):
            entry["args"].append(function["arguments"])

    def _starts_new_call(self, function: dict[str, Any], slot: int) -> bool:
        name = function.get("name")
        if not name:
            return False
        if name != self.slots.get(slot, {}).get("name"):
            return True
        return self._arguments_closed(slot)

    def _arguments_closed(self, slot: int) -> bool:
        """Brackets balanced outside strings (not strict JSON, so a repairable call still ends
        its slot). Scans only fragments added since the last check."""
        parts = self.slots.get(slot, {}).get("args", [])
        done, depth, in_string, escaped, started = self._scan.get(slot, (0, 0, False, False, False))
        for ch in "".join(parts[done:]):
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
            elif ch == '"':
                in_string = True
            elif ch in "{[":
                depth, started = depth + 1, True
            elif ch in "}]":
                depth -= 1
        self._scan[slot] = (len(parts), depth, in_string, escaped, started)
        return started and depth == 0 and not in_string


def openrouter(
    model: str,
    *,
    api_key: str,
    deny_data_collection: bool = True,
    sort: str | None = "throughput",
    only_providers: list[str] | None = None,
    app_name: str | None = None,
    timeout: float = 60.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> OpenAICompatModel:
    """OpenRouter with privacy-first routing: providers that store/train on data are excluded."""
    provider: dict[str, Any] = {}
    if deny_data_collection:
        provider["data_collection"] = "deny"
    if sort:
        provider["sort"] = sort
    if only_providers:
        provider["only"] = only_providers
    headers = {"X-Title": app_name} if app_name else None
    return OpenAICompatModel(
        model,
        base_url=OPENROUTER_URL,
        api_key=api_key,
        extra_body={"provider": provider, "usage": {"include": True}} if provider else None,
        headers=headers,
        timeout=timeout,
        transport=transport,
    )


def _json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


def _error_message(payload: Any, response: httpx.Response) -> str:
    if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
        return str(payload["error"].get("message") or response.reason_phrase)
    return response.reason_phrase or "model request failed"


def _parse(payload: Any, fallback_model: str) -> ModelResponse:
    try:
        choice = payload["choices"][0]
        message = choice["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ModelAPIError(502, "malformed completion payload", payload) from exc
    calls = []
    for raw in message.get("tool_calls") or []:
        function = raw.get("function") or {}
        arguments = function.get("arguments")
        if not isinstance(arguments, str):
            arguments = json.dumps(arguments or {})
        calls.append(
            ToolCall(
                id=raw.get("id") or f"call_{len(calls)}",
                name=function.get("name", ""),
                arguments=arguments,
            )
        )
    usage_raw = payload.get("usage") or {}
    details = usage_raw.get("prompt_tokens_details") or {}
    usage = Usage(
        prompt_tokens=int(usage_raw.get("prompt_tokens") or 0),
        completion_tokens=int(usage_raw.get("completion_tokens") or 0),
        cached_tokens=int(details.get("cached_tokens") or 0),
        cost=float(usage_raw["cost"]) if isinstance(usage_raw.get("cost"), int | float) else None,
        calls=1,
    )
    return ModelResponse(
        content=message.get("content"),
        tool_calls=calls,
        usage=usage,
        model=payload.get("model") or fallback_model,
        finish_reason=choice.get("finish_reason"),
    )
