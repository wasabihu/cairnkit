"""Deterministic model for tests, demos and offline development."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from cairnkit.llm.base import DeltaHandler, emit_delta
from cairnkit.types import Message, ModelResponse, Usage

Responder = Callable[[list[Message], list[dict[str, Any]] | None], ModelResponse]


class ScriptedModel:
    """Answers from a list of canned responses, or by calling ``responder``."""

    def __init__(
        self,
        responses: list[ModelResponse] | None = None,
        *,
        responder: Responder | None = None,
        name: str = "scripted",
    ):
        if (responses is None) == (responder is None):
            raise ValueError("pass exactly one of responses or responder")
        self.name = name
        self._responses = list(responses or [])
        self._responder = responder
        self.requests: list[dict[str, Any]] = []

    async def complete(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        on_delta: DeltaHandler | None = None,
    ) -> ModelResponse:
        self.requests.append({"messages": [dict(m) for m in messages], "tools": tools})
        if self._responder is not None:
            response = self._responder(messages, tools)
        else:
            if not self._responses:
                raise RuntimeError("ScriptedModel ran out of responses")
            response = self._responses.pop(0)
        if response.usage.calls == 0:
            response.usage = Usage(calls=1)
        response.model = response.model or self.name
        if on_delta is not None and response.content:
            words = response.content.split(" ")
            for i, word in enumerate(words):
                await emit_delta(on_delta, word if i == len(words) - 1 else word + " ")
        return response
