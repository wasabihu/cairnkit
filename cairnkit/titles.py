# Adapted from hermes-agent v0.22.2 (d923a5e): agent/title_generator.py
# Copyright (c) 2025 Nous Research. MIT License.
"""Conversation titles in two stages: an instant derived title, then a small-model upgrade.

Provenance ranks ``derived < llm < user``: a later stage only replaces an earlier one
and nothing replaces a title the user typed.
"""

from __future__ import annotations

import json
import re

from cairnkit.llm.base import ChatModel

MAX_DERIVED_TITLE_CHARS = 60
MAX_TITLE_WORDS = 12
_RANK = {"derived": 0, "llm": 1, "user": 2}

_PROMPT = (
    "Write a short title (3-7 words) for a conversation that starts with the message below. "
    'Answer only with JSON like {"title": "Early check-in request"}.\n\nMessage:\n'
)


def derive_title(first_message: str) -> str | None:
    """First meaningful line, trimmed at a word boundary. No model; never fails."""
    line = next((ln.strip() for ln in first_message.splitlines() if ln.strip()), "")
    line = " ".join(line.split())
    if len(line) > MAX_DERIVED_TITLE_CHARS:
        cut = line[:MAX_DERIVED_TITLE_CHARS]
        space = cut.rfind(" ")
        line = (cut[:space] if space > MAX_DERIVED_TITLE_CHARS // 2 else cut).rstrip(" ,.;:-") + "…"
    return line or None


def can_replace(current_source: str | None, new_source: str) -> bool:
    if current_source is None:
        return True
    return _RANK[new_source] > _RANK[current_source]


def _extract(raw: str) -> str | None:
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and isinstance(parsed.get("title"), str):
            return parsed["title"].strip()
    except ValueError:
        pass
    match = re.search(r'"title"\s*:\s*"((?:[^"\\]|\\.)*)"', raw)
    return match.group(1).strip() if match else None


async def generate_title(model: ChatModel, first_message: str) -> str | None:
    """Ask a (cheap) model for a title. Returns None instead of a bad title."""
    response = await model.complete(
        [{"role": "user", "content": _PROMPT + first_message[:2000]}], max_tokens=64
    )
    title = _extract(response.content or "")
    if not title or len(title.split()) > MAX_TITLE_WORDS:
        return None
    return title.strip(" .\"'")
