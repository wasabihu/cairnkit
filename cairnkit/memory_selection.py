"""Host-rendered memory proposals. IDs refer to one immutable, pending-applied snapshot."""

from collections.abc import Callable

from cairnkit.memory_ops import (
    ENTRY_DELIMITER,
    MemoryPlan,
    MemoryPlanError,
    plan_operations,
    total_chars,
)


def validate_removal_size(plan: MemoryPlan, target: int) -> None:
    """Reject lossy consolidation more than 5% below its configured soft target.

    Call only when facts are discarded, not for proven lossless packing. Hosts
    can use this same guard after comparing meanings in legacy text proposals.
    """
    floor = max(1, target * 95 // 100)
    size = total_chars(plan.entries)
    if size < floor:
        raise MemoryPlanError(
            f"Removal leaves {size} chars; retain at least {floor}. "
            "Remove fewer facts or use lossless grouping instead.",
            "over_removal",
        )


def prepare(entries: list[str], operations: list[dict]) -> tuple[list[str], list[int]]:
    # Planning only: no writes. Bound accommodates all inserted text and delimiters.
    ceiling = total_chars(entries) + sum(
        len(str(op.get("content", op.get("new_text", "")))) + 3 for op in operations
    )
    pending = plan_operations(entries, operations, max(1, ceiling))
    changed = {c.after for c in pending.changes if c.after is not None}
    return pending.entries, [i for i, text in enumerate(pending.entries) if text in changed]


def is_full_singleton_list(payload: object, count: int) -> bool:
    if not isinstance(payload, dict):
        return False
    groups = payload.get("groups")
    return (
        isinstance(groups, list)
        and len(groups) == count
        and all(
            isinstance(group, list) and len(group) == 1 and type(group[0]) is int
            for group in groups
        )
        and {group[0] for group in groups} == set(range(count))
    )


def removal_option(
    working: list[str], protected: list[int], target: int
) -> tuple[dict, list[list[int]]] | None:
    """Offer an ordered removal prefix, skipping protected IDs and retaining one entry."""
    remaining = total_chars(working)
    protected_ids = set(protected)
    ranges: list[list[int]] = []
    removed = []
    for index, entry in enumerate(working):
        if index in protected_ids:
            continue
        if len(removed) == len(working) - 1:
            break
        # Large indivisible rows do not justify nearly emptying memory. Try
        # smaller later rows; if none reach the target safely, offer no option.
        if remaining - len(entry) - len(ENTRY_DELIMITER) < max(1, target * 95 // 100):
            continue
        removed.append(entry)
        remaining -= len(entry) + len(ENTRY_DELIMITER)
        if ranges and ranges[-1][1] == index - 1:
            ranges[-1][1] = index
        else:
            ranges.append([index, index])
        if remaining <= target:
            return {"id": 0, "result_chars": remaining, "entries_to_remove": removed}, ranges
    return None


def select_plan(
    entries: list[str],
    operations: list[dict],
    working: list[str],
    protected: list[int],
    payload: dict,
    limit: int,
    render_group: Callable[[list[str]], str],
) -> MemoryPlan:
    if set(payload) - {"groups", "remove_ranges"}:
        raise ValueError("Selection accepts only groups and remove_ranges; no text edits")
    count = len(working)

    def valid_id(value):
        return type(value) is int and 0 <= value < count

    groups, ranges = payload.get("groups", []), payload.get("remove_ranges", [])
    if not isinstance(groups, list) or not isinstance(ranges, list):
        raise ValueError("groups and remove_ranges must be arrays")
    if (
        len(groups) > 16
        or len(ranges) > 64
        or any(isinstance(group, list) and len(group) > 16 for group in groups)
    ):
        raise ValueError("Use bounded edits: at most 16 groups of 16 IDs and 64 ranges")
    if len(groups) + len(ranges) > count:
        raise ValueError("Too many selections for entry_count")
    removed = set()
    for pair in ranges:
        if (
            not isinstance(pair, list)
            or len(pair) != 2
            or not all(valid_id(i) for i in pair)
            or pair[0] > pair[1]
        ):
            raise ValueError(f"Ranges must be inclusive [start,end] within 0..{count - 1}")
        indices = set(range(pair[0], pair[1] + 1))
        if removed & indices or indices.intersection(protected):
            raise ValueError("Overlapping ranges or removal of protected pending entry")
        removed.update(indices)
    touched = set(removed)
    rendered = []
    for group in groups:
        if (
            not isinstance(group, list)
            or not group
            or not all(valid_id(i) for i in group)
            or len(set(group)) != len(group)
            or touched.intersection(group)
        ):
            raise ValueError("Groups must have distinct valid IDs, disjoint from other selections")
        text = render_group([working[i] for i in group])
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Host renderer must return nonempty text")
        touched.update(group)
        if len(group) == 1 and text == working[group[0]]:
            continue
        rendered.append(text)
        removed.update(group)
    batch = [
        *operations,
        *({"action": "remove", "old_text": working[i]} for i in sorted(removed)),
        *({"action": "add", "content": text} for text in rendered),
    ]
    proposed = plan_operations(entries, batch, limit)
    # Hosts persist this as one transaction. Do not expose temporary pending rows
    # that are subsequently removed by a merge (e.g. ORM delete of a new object).
    final = proposed.entries
    edits = [
        *({"action": "remove", "old_text": text} for text in entries if text not in final),
        *({"action": "add", "content": text} for text in final if text not in entries),
    ]
    return plan_operations(entries, edits, limit) if edits else MemoryPlan(list(entries))
