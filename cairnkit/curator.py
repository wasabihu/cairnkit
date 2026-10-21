# Adapted from hermes-agent v0.22.2 (d923a5e): agent/curator.py
# Copyright (c) 2025 Nous Research. MIT License.
"""Curator: background maintenance of skills a host lets people (or agents) add.

Kept from Hermes:
* **Idle-triggered, no scheduler.** :func:`should_run` says yes only when the last run is
  older than ``interval_hours`` and nobody has used the agents for ``min_idle_hours``. Hosts
  call it from whatever quiet moment they have (a page load, the end of a request).
* **Lifecycle from activity.** A skill unused for ``stale_after_days`` becomes *stale*; one
  unused for ``archive_after_days`` is *archived*; using a stale skill makes it *active*
  again. A never-used skill younger than the stale window is left alone (no evidence is not
  staleness), and its clock starts at creation.
* **Never delete, only archive.** Archiving is reversible. **Pinned** skills and skills the
  host marks as built-in are never touched.
* **Optional consolidation** by a model (off by default) that may only *propose* archiving
  or rewriting skills, as a report; nothing it says is applied automatically.

Changed: transitions are returned as a plan instead of written to files, so a host can
apply them, or turn the archive steps into proposals someone approves first.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

from cairnkit.llm.base import ChatModel

SkillState = Literal["active", "stale", "archived"]


@dataclass
class CuratorPolicy:
    enabled: bool = False  # hosts decide; this project ships it switched off
    interval_hours: float = 24 * 7
    min_idle_hours: float = 2
    stale_after_days: int = 14
    archive_after_days: int = 30
    consolidate: bool = False  # ask a model for merge / rewrite / archive suggestions

    def __post_init__(self) -> None:
        self.interval_hours = max(1.0, float(self.interval_hours))
        self.min_idle_hours = max(0.0, float(self.min_idle_hours))
        self.stale_after_days = max(1, int(self.stale_after_days))
        self.archive_after_days = max(self.stale_after_days + 1, int(self.archive_after_days))


@dataclass(frozen=True)
class SkillActivity:
    name: str
    state: SkillState = "active"
    pinned: bool = False
    built_in: bool = False  # shipped with the code: never curated
    use_count: int = 0
    last_used_at: datetime | None = None
    created_at: datetime | None = None
    description: str = ""


@dataclass(frozen=True)
class Transition:
    name: str
    from_state: SkillState
    to_state: SkillState
    reason: str


@dataclass(frozen=True)
class Suggestion:
    """A model's consolidation idea. Never applied without a person."""

    action: Literal["archive", "rewrite"]
    skills: list[str]
    reason: str
    new_description: str | None = None
    new_body: str | None = None


@dataclass
class CuratorReport:
    checked: int = 0
    transitions: list[Transition] = field(default_factory=list)
    suggestions: list[Suggestion] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # pinned / built-in
    error: str | None = None


def should_run(
    policy: CuratorPolicy,
    *,
    last_run_at: datetime | None,
    last_activity_at: datetime | None,
    now: datetime | None = None,
) -> bool:
    if not policy.enabled:
        return False
    now = now or datetime.now(UTC)
    if last_run_at and now - _aware(last_run_at) < timedelta(hours=policy.interval_hours):
        return False
    return not (
        last_activity_at and now - _aware(last_activity_at) < timedelta(hours=policy.min_idle_hours)
    )


def plan_transitions(
    skills: list[SkillActivity], policy: CuratorPolicy, now: datetime | None = None
) -> CuratorReport:
    """Hermes ``apply_automatic_transitions`` as a pure function."""
    now = now or datetime.now(UTC)
    stale_cutoff = now - timedelta(days=policy.stale_after_days)
    archive_cutoff = now - timedelta(days=policy.archive_after_days)
    report = CuratorReport()
    for skill in skills:
        report.checked += 1
        if skill.pinned or skill.built_in:
            report.skipped.append(skill.name)
            continue
        if skill.state == "archived":
            continue
        anchor = _aware(skill.last_used_at or skill.created_at or now)
        if skill.use_count == 0 and anchor > stale_cutoff:
            if skill.state == "stale":
                report.transitions.append(
                    Transition(skill.name, "stale", "active", "too new to judge")
                )
            continue
        idle = (now - anchor).days
        if anchor <= archive_cutoff:
            report.transitions.append(
                Transition(skill.name, skill.state, "archived", f"unused for {idle} days")
            )
        elif anchor <= stale_cutoff and skill.state == "active":
            report.transitions.append(
                Transition(skill.name, "active", "stale", f"unused for {idle} days")
            )
        elif anchor > stale_cutoff and skill.state == "stale":
            report.transitions.append(Transition(skill.name, "stale", "active", "used again"))
    return report


CONSOLIDATION_PROMPT = """You maintain a library of skills (instructions an AI assistant reads
on demand). Review the list below and suggest consolidation: skills that overlap and should
be merged into one rewrite, and skills that are obsolete and should be archived. Archiving is
reversible; nothing you suggest is applied until a person approves it. Be conservative: no
suggestion is a fine answer. Never suggest touching a skill marked pinned.

Answer with JSON only:
{{"suggestions": [{{"action": "archive" | "rewrite", "skills": ["name", ...], "reason": "...",
"new_description": "<= 60 chars, rewrite only", "new_body": "full text, rewrite only"}}]}}

Skills:
{skills}"""


async def suggest_consolidation(
    model: ChatModel,
    skills: list[SkillActivity],
    bodies: dict[str, str],
    *,
    max_chars: int = 60_000,
) -> list[Suggestion]:
    """Ask a model for consolidation ideas (Hermes' optional LLM pass, report-only)."""
    rows, used = [], 0
    for s in skills:
        if s.state == "archived" or s.built_in:
            continue
        row = (
            f"### {s.name}{' (pinned)' if s.pinned else ''}\n{s.description}\n"
            f"uses: {s.use_count}\n{bodies.get(s.name, '')[:4_000]}"
        )
        if used + len(row) > max_chars:
            break
        rows.append(row)
        used += len(row)
    if len(rows) < 2:
        return []
    response = await model.complete(
        [{"role": "user", "content": CONSOLIDATION_PROMPT.format(skills="\n\n".join(rows))}],
        max_tokens=4_000,
    )
    return parse_suggestions(response.content or "", {s.name for s in skills if not s.pinned})


def parse_suggestions(text: str, allowed: set[str]) -> list[Suggestion]:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return []
    out: list[Suggestion] = []
    for item in data.get("suggestions", []) if isinstance(data, dict) else []:
        if not isinstance(item, dict) or item.get("action") not in ("archive", "rewrite"):
            continue
        names = [n for n in item.get("skills", []) if isinstance(n, str)]
        if not names or any(n not in allowed for n in names):
            continue  # unknown or pinned skills: drop the whole suggestion
        out.append(
            Suggestion(
                action=item["action"],
                skills=names,
                reason=str(item.get("reason", ""))[:500],
                new_description=(
                    str(item["new_description"])[:60] if item.get("new_description") else None
                ),
                new_body=str(item["new_body"]) if item.get("new_body") else None,
            )
        )
    return out


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)
