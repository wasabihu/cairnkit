# Adapted from hermes-agent v0.23.0 (2bd378e): agent/tool_guardrails.py and
# agent/tool_result_classification.py
# Copyright (c) 2025 Nous Research. MIT License. Condensed to the per-turn loop detectors.
"""Per-turn tool loop detection. Side-effect free: returns decisions, the loop acts on them."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Literal

Action = Literal["allow", "warn", "block", "halt"]


@dataclass(frozen=True)
class GuardrailConfig:
    exact_failure_warn_after: int = 2
    exact_failure_block_after: int = 3
    same_tool_failure_halt_after: int = 5
    identical_result_halt_after: int = 3


@dataclass(frozen=True)
class Decision:
    action: Action = "allow"
    code: str = "allow"
    message: str = ""

    @property
    def allows_execution(self) -> bool:
        return self.action in ("allow", "warn")


_RATE_LIMIT = re.compile(r"rate[\s_-]?limit|too many requests|\b429\b", re.IGNORECASE)
_RETRY_AFTER_KEYS = ("retry_after", "retryAfter", "retry_after_seconds", "retry_after_ms")


def is_rate_limited(result: str) -> bool:
    """True when a FAILED result says the backend throttled the call: a ``retry_after`` field,
    a 429 status, or rate-limit wording in its error. Only meaningful for failed results."""
    try:
        data = json.loads(result.strip())
    except ValueError:
        return bool(_RATE_LIMIT.search(result[:500]))
    if not isinstance(data, dict):
        return False
    if any(data.get(k) for k in _RETRY_AFTER_KEYS) or 429 in (
        data.get("status"),
        data.get("status_code"),
        data.get("code"),
    ):
        return True
    error = data.get("error")
    text = error.get("message") or error.get("code") if isinstance(error, dict) else error
    return isinstance(text, str) and bool(_RATE_LIMIT.search(text))


def signature(tool_name: str, arguments: dict[str, Any]) -> str:
    canonical = json.dumps(
        arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return f"{tool_name}:{hashlib.sha256(canonical.encode()).hexdigest()[:16]}"


class GuardrailController:
    def __init__(self, config: GuardrailConfig | None = None):
        self.config = config or GuardrailConfig()
        self._exact_failures: Counter[str] = Counter()
        self._tool_failures: Counter[str] = Counter()
        self._last: tuple[str, str] | None = None
        self._identical_streak = 0

    def before_call(self, tool_name: str, arguments: dict[str, Any]) -> Decision:
        count = self._exact_failures[signature(tool_name, arguments)]
        if count >= self.config.exact_failure_block_after:
            return Decision(
                "block",
                "repeated_exact_failure_block",
                f"Blocked {tool_name}: the same call failed {count} times with identical "
                "arguments. Stop retrying it unchanged; change strategy or explain the blocker.",
            )
        return Decision()

    def after_call(
        self, tool_name: str, arguments: dict[str, Any], result: str, failed: bool
    ) -> Decision:
        sig = signature(tool_name, arguments)
        if failed:
            # A throttled call retried after its cooldown is the right move, not a replay: keep
            # it out of the identical-arguments streak. It still counts per tool, so a dead
            # endpoint is bounded by the halt below.
            throttled = is_rate_limited(result)
            if not throttled:
                self._exact_failures[sig] += 1
            self._tool_failures[tool_name] += 1
            if self._tool_failures[tool_name] >= self.config.same_tool_failure_halt_after:
                return Decision(
                    "halt",
                    "same_tool_failure_halt",
                    f"Stopped {tool_name}: it failed {self._tool_failures[tool_name]} times this "
                    "turn. Choose a different approach.",
                )
            if not throttled and self._exact_failures[sig] >= self.config.exact_failure_warn_after:
                return Decision(
                    "warn",
                    "repeated_exact_failure_warning",
                    f"{tool_name} has failed {self._exact_failures[sig]} times with identical "
                    "arguments. Inspect the error and change strategy.",
                )
            return Decision()
        current = (sig, hashlib.sha256(result.encode()).hexdigest())
        self._identical_streak = self._identical_streak + 1 if current == self._last else 1
        self._last = current
        if self._identical_streak >= self.config.identical_result_halt_after:
            return Decision(
                "halt",
                "identical_call_streak_halt",
                f"Stopped {tool_name}: the same call returned the same result "
                f"{self._identical_streak} times in a row. Use the result already provided.",
            )
        return Decision()
