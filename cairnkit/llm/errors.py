# Adapted from hermes-agent v0.22.2 (d923a5e): agent/error_classifier.py
# Copyright (c) 2025 Nous Research. MIT License. Condensed to OpenAI-compatible endpoints.
"""Classify model API failures into a recovery decision.

The retry/fallback code consults the hints on :class:`ClassifiedError` instead of
re-matching error strings itself (same contract as Hermes' classifier).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any

import httpx


class FailoverReason(enum.Enum):
    auth = "auth"  # 401/403 credential refused: abort, retrying will not help
    billing = "billing"  # 402 or credit exhausted: fall back, do not retry this model
    rate_limit = "rate_limit"  # 429 from the gateway itself: back off, then fall back
    upstream_rate_limit = "upstream_rate_limit"  # aggregator's upstream 429: key is fine, fall back
    overloaded = "overloaded"  # 503/529: back off and retry
    server_error = "server_error"  # 500/502: retry
    timeout = "timeout"  # connect/read timeout: retry
    context_overflow = "context_overflow"  # prompt too long: compress, do not fail over
    payload_too_large = "payload_too_large"  # 413: compress
    model_not_found = "model_not_found"  # 404 / invalid model id: fall back to another model
    provider_policy_blocked = "provider_policy_blocked"  # data policy excluded every endpoint
    content_policy_blocked = "content_policy_blocked"  # safety filter: same input fails again
    format_error = "format_error"  # 400 malformed request: abort
    unknown = "unknown"


@dataclass(frozen=True)
class ClassifiedError:
    reason: FailoverReason
    status_code: int | None = None
    message: str = ""
    retryable: bool = False
    should_fallback: bool = False
    should_compress: bool = False
    context: dict[str, Any] = field(default_factory=dict)


class ModelAPIError(Exception):
    """Non-2xx answer from a model endpoint. ``body`` is the parsed JSON when available."""

    def __init__(self, status_code: int, message: str, body: Any = None):
        super().__init__(f"HTTP {status_code}: {message}")
        self.status_code = status_code
        self.message = message
        self.body = body


_CONTEXT_PATTERNS = (
    "context length",
    "context_length",
    "maximum context",
    "too many tokens",
    "prompt is too long",
    "reduce the length",
    "context window",
)
_BILLING_PATTERNS = ("insufficient credits", "insufficient_quota", "key limit exceeded", "credit")
_POLICY_PATTERNS = ("data policy", "no endpoints found matching your data policy")
_CONTENT_PATTERNS = ("content policy", "flagged", "moderation", "safety")


def _text(error: ModelAPIError) -> str:
    return f"{error.message} {error.body!r}".lower()


def _upstream_429(body: Any) -> bool:
    """OpenRouter wraps provider errors as ``{"error": {"metadata": {"provider_name": ...}}}``."""
    if not isinstance(body, dict):
        return False
    meta = (
        (body.get("error") or {}).get("metadata") if isinstance(body.get("error"), dict) else None
    )
    return isinstance(meta, dict) and bool(meta.get("provider_name") or meta.get("raw"))


def classify_error(error: BaseException) -> ClassifiedError:
    if isinstance(error, httpx.TimeoutException):
        return ClassifiedError(
            FailoverReason.timeout, message=str(error), retryable=True, should_fallback=True
        )
    if isinstance(error, httpx.TransportError):
        return ClassifiedError(
            FailoverReason.server_error, message=str(error), retryable=True, should_fallback=True
        )
    if not isinstance(error, ModelAPIError):
        return ClassifiedError(FailoverReason.unknown, message=type(error).__name__)

    status, text = error.status_code, _text(error)

    def verdict(reason: FailoverReason, **hints: Any) -> ClassifiedError:
        return ClassifiedError(reason, status_code=status, message=error.message, **hints)

    if any(p in text for p in _CONTEXT_PATTERNS):
        return verdict(FailoverReason.context_overflow, should_compress=True)
    if status == 413:
        return verdict(FailoverReason.payload_too_large, should_compress=True)
    if status == 402 or any(p in text for p in _BILLING_PATTERNS):
        return verdict(FailoverReason.billing, should_fallback=True)
    if status == 401:
        return verdict(FailoverReason.auth)
    if status == 403:
        if any(p in text for p in _POLICY_PATTERNS):
            return verdict(FailoverReason.provider_policy_blocked, should_fallback=True)
        return verdict(FailoverReason.auth)
    if status == 404:
        if any(p in text for p in _POLICY_PATTERNS):
            return verdict(FailoverReason.provider_policy_blocked, should_fallback=True)
        return verdict(FailoverReason.model_not_found, should_fallback=True)
    if status == 429:
        if _upstream_429(error.body):
            return verdict(FailoverReason.upstream_rate_limit, should_fallback=True)
        return verdict(FailoverReason.rate_limit, retryable=True, should_fallback=True)
    if status in (503, 529):
        return verdict(FailoverReason.overloaded, retryable=True, should_fallback=True)
    if 500 <= status < 600:
        return verdict(FailoverReason.server_error, retryable=True, should_fallback=True)
    if status == 400:
        if any(p in text for p in _CONTENT_PATTERNS):
            return verdict(FailoverReason.content_policy_blocked)
        return verdict(FailoverReason.format_error)
    return verdict(FailoverReason.unknown)
