# Adapted from hermes-agent v0.22.2 (d923a5e): tools/memory_tool.py, tools/memory_tool_store.py
# Copyright (c) 2025 Nous Research. MIT License.
"""Bounded memory snapshots and write screening.

Storage is the host application's job (a database, per user, per record...). This
module keeps Hermes' two rules that make memory safe to put in a prompt:

* the snapshot is bounded in characters (model independent) and frozen when the
  conversation starts, so mid-conversation writes never rebuild the system prompt;
* anything written into memory is screened for injection first.

``make_memory_tool`` gives a model Hermes' add / patch / remove editing over any
host :class:`MemoryStore`; the store decides whether changes apply now or wait for
a person to approve them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from cairnkit.memory_ops import MemoryPlan, MemoryPlanError, plan_operations, total_chars
from cairnkit.security import first_threat_message, scan_for_threats
from cairnkit.tools import ToolContext, ToolError, ToolSpec, tool_error, tool_result

DEFAULT_SNAPSHOT_CHARS = 2200  # Hermes' default MEMORY.md budget


@dataclass(frozen=True)
class MemoryItem:
    id: str
    text: str
    label: str = ""  # e.g. "preference", shown in brackets


def render_snapshot(
    items: list[MemoryItem], *, title: str = "Memory", max_chars: int = DEFAULT_SNAPSHOT_CHARS
) -> tuple[str, list[str]]:
    """Render items in priority order until the budget is used.

    Returns the text and the ids that made it in, so callers can verify citations.
    Items flagged by the context-scope threat scan are left out rather than injected.
    """
    lines: list[str] = []
    included: list[str] = []
    used = len(title) + 2
    for item in items:
        if scan_for_threats(item.text, scope="context"):
            continue
        label = f"[{item.label}] " if item.label else ""
        line = f"- ({item.id}) {label}{item.text}"
        if used + len(line) + 1 > max_chars:
            break
        lines.append(line)
        included.append(item.id)
        used += len(line) + 1
    if not lines:
        return f"{title}:\n- (nothing recorded)", []
    return f"{title}:\n" + "\n".join(lines), included


def screen_memory_write(text: str) -> str | None:
    """None when safe to store, else a message explaining why it was refused."""
    return first_threat_message(text, scope="strict")


# ── Memory tool ─────────────────────────────────────────────────────────────


class MemoryStore(Protocol):
    """Host-side storage. ``save`` decides whether changes apply now or wait for approval."""

    def load(self, target: str, ctx: ToolContext) -> list[str]: ...

    def limit(self, target: str) -> int: ...

    def save(self, target: str, plan: MemoryPlan, ctx: ToolContext) -> str:
        """Persist (or stage) ``plan.changes``; return a short message for the model.
        Raise :class:`cairnkit.tools.ToolError` to refuse."""
        ...


_MEMORY_DESCRIPTION = (
    "Save durable facts to memory. Make ALL your changes to one target in ONE call via an "
    "'operations' array (each item: {action, content?, old_text?}); the batch applies "
    "atomically and the size limit is checked on the final result, so one call can remove or "
    "shorten stale entries AND add new ones. 'patch' replaces the old_text span inside one "
    "entry; 'remove' deletes the whole entry that contains old_text. Copy old_text verbatim "
    "from an existing entry. Only save facts that will matter later; skip trivia."
)


def make_memory_tool(
    store: MemoryStore,
    targets: dict[str, str],
    *,
    name: str = "memory",
    description: str = _MEMORY_DESCRIPTION,
    roles: set[str] | None = None,
) -> ToolSpec:
    """Build the memory tool. ``targets`` maps target name -> what it holds."""
    target_help = "; ".join(f"'{k}' = {v}" for k, v in targets.items())

    def handler(args: dict[str, Any], ctx: ToolContext) -> str:
        target = args.get("target") or (next(iter(targets)) if len(targets) == 1 else None)
        if target not in targets:
            raise ToolError(f"target must be one of {', '.join(targets)}")
        operations = args.get("operations")
        if not operations:
            operations = [{k: args.get(k) for k in ("action", "content", "old_text") if k in args}]
        if not isinstance(operations, list) or not all(isinstance(o, dict) for o in operations):
            raise ToolError("operations must be a list of {action, content?, old_text?} objects")
        entries = store.load(target, ctx)
        limit = store.limit(target)
        try:
            plan = plan_operations(entries, operations, limit)
        except MemoryPlanError as exc:
            return tool_error(exc.message, failure_class=exc.failure_class, **exc.extra)
        if not plan.changes:
            return tool_result(
                message=" ".join(plan.messages), usage=f"{total_chars(entries)}/{limit}"
            )
        message = store.save(target, plan, ctx)
        return tool_result(
            message=message,
            changes=len(plan.changes),
            usage=f"{total_chars(plan.entries):,}/{limit:,}",
        )

    return ToolSpec(
        name=name,
        description=f"{description} Targets: {target_help}.",
        access="propose",
        roles=frozenset(roles) if roles else None,
        handler=handler,
        parameters={
            "type": "object",
            "properties": {
                "target": {"type": "string", "enum": list(targets)},
                "operations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "action": {"type": "string", "enum": ["add", "patch", "remove"]},
                            "content": {"type": "string"},
                            "old_text": {"type": "string"},
                        },
                        "required": ["action"],
                    },
                },
                "action": {
                    "type": "string",
                    "enum": ["add", "patch", "remove"],
                    "description": "Single-change shape; omit when using operations.",
                },
                "content": {"type": "string"},
                "old_text": {"type": "string"},
            },
        },
    )
