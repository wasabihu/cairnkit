"""Pure working-set projection over a host-owned, searchable fact archive.

This is an extension, not Hermes' destructive memory editing policy. Nothing is
written or removed here. Hosts retain canonical records and validate summaries;
keys partition the input exactly so archived sources remain individually usable.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from cairnkit.memory_ops import ENTRY_DELIMITER, MemoryPlanError, total_chars


@dataclass(frozen=True)
class ArchiveFact:
    key: str
    text: str
    order: tuple[float, str] | None
    topic: str
    keep_detail: bool = False


@dataclass(frozen=True)
class ArchiveSummary:
    text: str
    keys: tuple[str, ...]
    level: str


@dataclass(frozen=True)
class WorkingMemory:
    details: tuple[str, ...]
    summaries: tuple[ArchiveSummary, ...]
    chars: int


def project_archive(
    facts: Sequence[ArchiveFact],
    *,
    limit: int,
    target: int,
    recent_count: int,
    middle_count: int,
    summarize: Callable[[Sequence[ArchiveFact], str], str],
) -> WorkingMemory:
    """Archive oldest eligible facts until target; never mutate the source.

    Unknown origins, ungroupable topics, explicit protections and the newest
    ``recent_count`` facts stay detailed. Age uses original source order, not the
    time a summary was rebuilt. If the target cannot fit, an under-limit view is
    acceptable. If mandatory details cannot fit even with summaries, fail closed.
    The host's summary renderer must faithfully describe all supplied facts.
    """
    if not 0 < target <= limit or not 0 <= recent_count <= middle_count:
        raise ValueError("invalid archive budget or rank thresholds")
    keys = [f.key for f in facts]
    if len(set(keys)) != len(keys) or any(not f.key or not f.text.strip() for f in facts):
        raise ValueError("archive facts need unique keys and nonempty text")
    chars = total_chars([f.text for f in facts])
    if chars <= limit:
        return WorkingMemory(tuple(keys), (), chars)
    known = sorted(
        (f for f in facts if f.order is not None), key=lambda f: (f.order, f.key), reverse=True
    )
    ranks = {f.key: i for i, f in enumerate(known)}
    candidates = [
        f for f in reversed(known) if ranks[f.key] >= recent_count and not f.keep_detail and f.topic
    ]
    groups: dict[tuple[str, str], list[ArchiveFact]] = {}
    summaries: dict[tuple[str, str], ArchiveSummary] = {}
    archived: set[str] = set()
    best = None
    delimiter = len(ENTRY_DELIMITER)
    for fact in candidates:
        level = "distant" if ranks[fact.key] >= middle_count else "middle"
        group = (level, fact.topic)
        members = groups.setdefault(group, [])
        members.append(fact)
        text = summarize(tuple(members), level)
        if not isinstance(text, str) or not text.strip():
            raise ValueError("archive summary must be nonempty text")
        old = summaries.get(group)
        # Replacing the first detail by a summary keeps entry count; subsequent
        # members remove one detail and its delimiter, updating the group once.
        chars += len(text) - len(fact.text) - (len(old.text) + delimiter if old else 0)
        summaries[group] = ArchiveSummary(text, tuple(f.key for f in members), level)
        archived.add(fact.key)
        if chars <= limit and (best is None or chars < best.chars):
            best = WorkingMemory(
                tuple(k for k in keys if k not in archived), tuple(summaries.values()), chars
            )
        if chars <= target:
            return best
    if best is not None:
        return best
    raise MemoryPlanError(
        "mandatory details and archive summaries exceed capacity", "capacity_unreachable"
    )
