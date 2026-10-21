# Ported from hermes-agent v0.22.2 (d923a5e): tools/memory_tool_store.py and tools/memory_tool.py
# Copyright (c) 2025 Nous Research. MIT License.
# Modified: the file store is replaced by a host-provided MemoryStore; planning is pure.
"""Memory edits as a pure plan over a list of entries.

Keeps Hermes' editing contract:
* one ``operations`` batch is atomic and the character limit is checked on the result,
  so a single call can free room and add in one go;
* ``patch`` / ``remove`` locate the entry by text: a whole-entry exact match wins, then
  a substring, then a typography-folded substring; several distinct matches is an error;
* a ``patch`` span must occur once in its entry and must change something;
* every written text is screened for injection; duplicates are not re-added;
* errors name the fix (closest entries, chars to free) instead of failing silently.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from cairnkit.security import first_threat_message

ENTRY_DELIMITER = "\n§\n"
Action = Literal["add", "patch", "remove"]

_MATCH_FOLD = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "})


@dataclass(frozen=True)
class MemoryChange:
    action: Action
    before: str | None  # the full entry as it was (None for add)
    after: str | None  # the full entry as it will be (None for remove)


@dataclass
class MemoryPlan:
    entries: list[str]
    changes: list[MemoryChange] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)


class MemoryPlanError(Exception):
    def __init__(self, message: str, failure_class: str, **extra: Any):
        super().__init__(message)
        self.message = message
        self.failure_class = failure_class
        self.extra = extra


def total_chars(entries: list[str]) -> int:
    return len(ENTRY_DELIMITER.join(entries))


def _normalize(text: str) -> str:
    return " ".join(str(text).replace("\\n", " ").translate(_MATCH_FOLD).split())


def _substring_matches(entries: list[str], old_text: str) -> list[int]:
    if exact := [i for i, e in enumerate(entries) if old_text in e]:
        return exact
    needle = _normalize(old_text)
    if not any(c.isalnum() for c in needle):
        return []
    return [i for i, e in enumerate(entries) if needle in _normalize(e)]


def _closest(entries: list[str], old_text: str) -> list[str]:
    def words(text: str) -> set[str]:
        return set(re.findall(r"\w+", text.lower()))

    target = words(old_text)
    if not target:
        return []
    scored = sorted(
        ((len(target & words(e)) / len(target), i) for i, e in enumerate(entries)),
        key=lambda p: (-p[0], p[1]),
    )
    return [entries[i] for score, i in scored[:3] if score >= 0.3]


def locate(entries: list[str], old_text: str, verb: str) -> int:
    """Index of the one entry ``old_text`` selects, else :class:`MemoryPlanError`."""
    exact = [i for i, e in enumerate(entries) if e == old_text]
    matches = exact or _substring_matches(entries, old_text)
    if len({entries[i] for i in matches}) > 1:
        raise MemoryPlanError(
            f"Multiple entries matched '{old_text}'. Be more specific.",
            "ambiguous",
            matches=[entries[i][:80] for i in matches],
        )
    if not matches:
        closest = _closest(entries, old_text)
        raise MemoryPlanError(
            f"No entry matched '{old_text}'. Retry the {verb} with old_text copied verbatim from "
            "the intended entry" + (" (closest_entries below)." if closest else "."),
            "no_match",
            **({"closest_entries": closest} if closest else {}),
        )
    return matches[0]


def _span_occurrences(text: str, span: str) -> int:
    return sum(text.startswith(span, i) for i in range(len(text) - len(span) + 1))


def _screen(text: str) -> None:
    if threat := first_threat_message(text, scope="strict"):
        raise MemoryPlanError(threat, "scan_blocked")


def _apply_one(entries: list[str], op: dict[str, Any], plan: MemoryPlan) -> list[str]:
    action = op.get("action")
    if action == "add":
        content = str(op.get("content") or "").strip()
        if not content:
            raise MemoryPlanError("Content cannot be empty.", "missing_content")
        _screen(content)
        if content in entries:
            plan.messages.append("Entry already exists (no duplicate added).")
            return entries
        plan.changes.append(MemoryChange("add", None, content))
        plan.messages.append("Entry added.")
        return [*entries, content]
    if action == "patch":
        old_text = str(op.get("old_text") or "")
        new_text = op.get("content", op.get("new_text"))
        if not old_text.strip():
            raise MemoryPlanError("old_text cannot be empty.", "missing_old_text")
        if new_text is None or not str(new_text).strip():
            raise MemoryPlanError(
                "new text cannot be empty. To drop text inside an entry, patch a longer span "
                "that contains it; 'remove' deletes the whole entry.",
                "missing_content",
            )
        index = locate(entries, old_text, "patch")
        before = entries[index]
        if (count := _span_occurrences(before, old_text)) > 1:
            raise MemoryPlanError(
                f"'{old_text}' appears {count} times in the matched entry, and patch edits one "
                "span. Include more surrounding text so old_text occurs once.",
                "ambiguous",
            )
        after = before.replace(old_text, str(new_text), 1) if old_text in before else str(new_text)
        if after == before:
            raise MemoryPlanError(
                f"Patch is a no-op: '{old_text}' leaves the entry unchanged.", "invalid_args"
            )
        _screen(after)
        plan.changes.append(MemoryChange("patch", before, after))
        plan.messages.append("Entry patched.")
        return [*entries[:index], after, *entries[index + 1 :]]
    if action == "remove":
        old_text = str(op.get("old_text") or "").strip()
        if not old_text:
            raise MemoryPlanError("old_text cannot be empty.", "missing_old_text")
        index = locate(entries, old_text, "remove")
        plan.changes.append(MemoryChange("remove", entries[index], None))
        plan.messages.append("Entry removed.")
        return [*entries[:index], *entries[index + 1 :]]
    raise MemoryPlanError("action must be one of add, patch, remove.", "invalid_args")


def plan_operations(entries: list[str], operations: list[dict[str, Any]], limit: int) -> MemoryPlan:
    """Apply ``operations`` to a copy of ``entries``; all succeed or :class:`MemoryPlanError`."""
    if not operations:
        raise MemoryPlanError("No operations given.", "invalid_args")
    plan = MemoryPlan(entries=list(dict.fromkeys(entries)))
    working = plan.entries
    for op in operations:
        working = _apply_one(working, op, plan)
    new_total = total_chars(working)
    if new_total > limit:
        raise MemoryPlanError(
            f"The result would put memory at {new_total:,}/{limit:,} chars: free at least "
            f"{new_total - limit:,} chars. Retry as ONE operations batch that removes or shortens "
            "stale entries and adds the new one together.",
            "over_limit",
            current_entries=entries,
        )
    plan.entries = working
    return plan
