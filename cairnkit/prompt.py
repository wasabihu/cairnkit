# Adapted from hermes-agent v0.22.2 (d923a5e): agent/system_prompt.py
# Copyright (c) 2025 Nous Research. MIT License.
"""System prompt in three tiers, assembled once per conversation.

The prompt is byte-stable for the life of a conversation so the provider's prefix
cache stays warm. Anything that must arrive mid-conversation rides a user message or
a tool result, never a rebuilt system prompt (Hermes' core caching invariant).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PromptParts:
    stable: list[str] = field(default_factory=list)
    """Identity, behaviour rules, safety rules: changes only when a new version ships."""
    context: list[str] = field(default_factory=list)
    """Facts about this conversation's setting (who is asking, house rules)."""
    volatile: list[str] = field(default_factory=list)
    """Skill index, memory snapshot, current time: frozen at conversation start."""


def build_system_prompt(parts: PromptParts) -> str:
    blocks = [b.strip() for tier in (parts.stable, parts.context, parts.volatile) for b in tier]
    return "\n\n".join(b for b in blocks if b)
