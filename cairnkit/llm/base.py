from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol, runtime_checkable

from cairnkit.types import Message, ModelResponse

DeltaHandler = Callable[[str], Awaitable[None] | None]
"""Receives visible answer text as it streams. Tool calls are only returned at the end."""


async def emit_delta(handler: DeltaHandler | None, text: str) -> None:
    if handler is None or not text:
        return
    value = handler(text)
    if value is not None:
        await value


@runtime_checkable
class ChatModel(Protocol):
    """Anything that can answer a chat request, optionally with tool calls."""

    name: str

    async def complete(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        on_delta: DeltaHandler | None = None,
    ) -> ModelResponse: ...
