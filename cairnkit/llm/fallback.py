# Adapted from hermes-agent v0.22.2 (d923a5e): agent/fallback_cooldown.py and the
# fallback walk in agent/chat_completion_helpers.py. Copyright (c) 2025 Nous Research. MIT License.
"""Try a chain of models; retry transient errors, fall back on model-level failures."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from cairnkit.llm.base import ChatModel, emit_delta
from cairnkit.llm.errors import ClassifiedError, FailoverReason, classify_error
from cairnkit.types import Message, ModelResponse

logger = logging.getLogger(__name__)

Sleep = Callable[[float], Awaitable[None]]


class AllModelsFailed(Exception):
    def __init__(self, errors: list[tuple[str, ClassifiedError]]):
        summary = "; ".join(f"{name}: {err.reason.value}" for name, err in errors)
        super().__init__(f"every model failed ({summary})")
        self.errors = errors


class FallbackModel:
    """Primary model first; on fallback-worthy failures move down the chain.

    A model that hit a rate limit is skipped for ``cooldown_seconds`` so later calls
    go straight to the next model instead of waiting on a throttled one.
    Errors that no other model can fix (auth, malformed request, context overflow)
    are raised immediately.
    """

    def __init__(
        self,
        models: list[ChatModel],
        *,
        retries: int = 2,
        backoff_seconds: float = 1.0,
        cooldown_seconds: float = 60.0,
        sleep: Sleep = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        if not models:
            raise ValueError("at least one model is required")
        self.models = models
        self.name = models[0].name
        self._retries = retries
        self._backoff = backoff_seconds
        self._cooldown = cooldown_seconds
        self._sleep = sleep
        self._clock = clock
        self._cooling_until: dict[str, float] = {}

    async def complete(self, messages: list[Message], **kwargs: Any) -> ModelResponse:
        """Streamed text cannot be taken back, so once a delta went out, errors are raised."""
        errors: list[tuple[str, ClassifiedError]] = []
        user_delta = kwargs.pop("on_delta", None)
        streamed = False

        async def on_delta(text: str) -> None:
            nonlocal streamed
            streamed = True
            await emit_delta(user_delta, text)

        if user_delta is not None:
            kwargs["on_delta"] = on_delta
        now = self._clock()
        candidates = [m for m in self.models if self._cooling_until.get(m.name, 0) <= now]
        for model in candidates or self.models:
            for attempt in range(self._retries + 1):
                try:
                    return await model.complete(messages, **kwargs)
                except Exception as exc:  # noqa: BLE001 - classified below
                    if streamed:
                        raise
                    verdict = classify_error(exc)
                    logger.warning("model %s failed: %s", model.name, verdict.reason.value)
                    if verdict.reason in (
                        FailoverReason.rate_limit,
                        FailoverReason.upstream_rate_limit,
                    ):
                        self._cooling_until[model.name] = self._clock() + self._cooldown
                    if not verdict.retryable and not verdict.should_fallback:
                        raise
                    if (
                        verdict.retryable
                        and attempt < self._retries
                        and verdict.reason not in (FailoverReason.rate_limit,)
                    ):
                        await self._sleep(self._backoff * (2**attempt))
                        continue
                    errors.append((model.name, verdict))
                    break
        raise AllModelsFailed(errors)
