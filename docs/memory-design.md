# Design: bounded memory, archive projection and consolidation

Status: **implemented across v0.1–v0.7.0** (`memory.py`, `memory_ops.py`, `memory_layers.py`,
`memory_archive.py`, `memory_consolidation.py`, `memory_selection.py`). Storage, provenance,
access control and atomic commits stay with the host application; every module here runs in
process with zero framework or database dependencies.

See [examples/zero_call_memory.py](../examples/zero_call_memory.py) for an end-to-end offline
walkthrough and [examples/memory.py](../examples/memory.py) for background review across turns.

## 1. Hybrid pipeline: zero model calls on the hot path

Running a second LLM call after every chat turn is expensive and noisy. Hosts using `cairnkit`
can keep the steady-state path deterministic (zero model calls) and reserve `consolidate_memory`
only for genuine character-limit overflow:

1. **Deterministic intake & write screening (0 model calls).** Extract structured host events or
   explicit user updates in application code, screen each text with `screen_memory_write`, and
   build atomic edits with `plan_operations`.
2. **Ordinal ranking & lossless prepass (0 model calls when fitting).** Rank original facts by
   host source order with `layer_facts` (`recent_count`, `middle_count`) and supply
   `compact_entries` (normalization and lossless same-fact grouping) to `consolidate_memory`. A
   host-validated result under the hard `limit` returns immediately with `precompacted=True` and
   `attempts=0`.
3. **Pure working-set projection over canonical storage (0 model calls, zero data loss).** When
   hosts keep all canonical facts in their own database for scoped search, `project_archive`
   projects older facts into typed summaries while retaining recent, protected and unknown-origin
   entries in full detail.
4. **Bounded model consolidation on true overflow (1–3 calls max).** Only if distinct entries still
   exceed `limit` (and `minimum_chars` does not already prove `capacity_unreachable`) does
   `consolidate_memory` ask the model for compact `groups` and `remove_ranges`, validated by the
   host and committed atomically against an unchanged snapshot check.
5. **Frozen prompt snapshots.** At the start of the next conversation, `render_snapshot` formats
   allowed items under a fixed character ceiling so mid-conversation writes never invalidate the
   provider's prompt cache.

## 2. Memory consolidation and retrieval

```python
from cairnkit.memory_consolidation import consolidate_memory

result = await consolidate_memory(model, entries, pending_operations, limit=12000, target_chars=8000,
                                  validate=validate_grounding)
if result.plan is not None:
    # Host must atomically compare the original snapshot, then commit and audit.
    commit_if_unchanged(entries, result.plan)
```

A fitting batch makes no model request. Overflow permits up to three JSON
proposals with validation feedback. No proposal writes storage; failure or
cancellation leaves the original entries untouched. The host defines factual
support, which new corrections must survive, permissions and persistence.

`target_chars` is a soft consolidation goal. Only exceeding `limit` can invoke the
model. Up to three proposals try to reach the target; otherwise the smallest
host-validated plan under the hard limit is returned with `target_met=False`.
Indexed removals reduce output size for large sets of short entries.


For hosts with a verifiable fact vocabulary, pass `render_group: Callable[[list[str]], str]`.
The model then selects `{"groups":[[0,1]],"remove_ranges":[[2,4]]}` against a numbered,
pending-applied snapshot. Ranges are inclusive; unselected rows stay unchanged. IDs are
immutable across attempts. New/changed entries cannot be removed by a range; grouping
must retain their meaning, checked by the host's `validate` callback. The pure renderer
must preserve meaning or raise `ValueError` (e.g. when dates cannot be grouped).
The generic package supplies no domain vocabulary or permission decisions.

Selection proposals use a 2048-token output ceiling, explicit entry counts and remaining
space. `finish_reason=length` is rejected even for parseable JSON. Rejected output is not
replayed; each request sees the same snapshot and bounded feedback. A small, valid proposal
that misses the soft target may be included in feedback, explicitly not committed.
Legacy text `operations`/`remove_indices` remain accepted for compatibility and still pass
host validation; legacy callers without a renderer retain the 8192-token ceiling.
Explicit removals cannot leave less than 95% of `target_chars` (rounded down to whole
characters, at least one). This guard is based on the configured target, not a fixed
memory size. Host-rendered lossless groups and the lossless prepass can shrink further.
For legacy text patches, the host must compare meanings; it can call
`cairnkit.memory_selection.validate_removal_size(plan, target)` when facts were lost.
Legacy explicit removals are checked by the helper as well. A safe plan slightly above
the target remains preferable to excessive deletion and may be returned after three tries.
After a failed proposal listing every entry as a singleton group or deleting too much, the next request can
offer a calculated removal option. It takes entries in the supplied order and skips
protected changes and indivisible entries that would undershoot the allowed size.
If no bounded option exists, no option is offered. The model sees the facts the option would remove and can select or
decline it. The same host validator checks an accepted option before it becomes a plan.
Only final changes are returned for atomic persistence; no transient pending row needs to
be inserted and deleted. No provider errors are retried, and there are at most three
proposals. These are offline-tested mechanisms, not a guarantee of real-model quality.

Pass an optional `compact_entries: Callable[[list[str]], list[str]]` to try a lossless
prepass before model proposals. It receives a copy of the pending-applied entries and
must preserve every distinct fact (including new corrections), using only reversible
normalization and equivalent-fact deduplication. It must not drop less important facts.
The helper checks shape, non-growing size and the host's `validate`; only the host can
prove semantic equivalence. A fitting result returns `precompacted=True`, `attempts=0`,
even above `target_chars`. A result still over the hard limit is not partly committed;
model proposals use the original snapshot and IDs. Exceptions fail without writes.

For read-time context, hosts can pass individual facts as `MemoryItem`s in their chosen
priority order to `render_snapshot`. Each fact may carry its own source label. Packing
skips oversized items and repeated IDs; `max_items` counts only included items. Text
deduplication, relevance, source validation and ownership stay with the host. This does
not rewrite stored records or add a model request.

### Ordinal memory layers

`cairnkit.memory_layers.layer_facts` ranks original `LayeredFact` records by a
host-supplied stable source order. `recent_count` and `middle_count` are required
configuration, not day thresholds. The host owns topic keys, durable/pending
protection and reversible rendering. Unknown origins stay detailed and protected;
rebuilding summary rows does not reset source order. `MemoryLayers.compact` groups
older facts within the same topic and layer, with a default maximum of 16 atoms
per group. The host must validate exact semantic preservation.

`consolidate_memory(..., protected_entry=...)` exposes host protection in selection
IDs and bounded removal options. Supply `validate` too, including checks on legacy
text patches. No framework, database, business vocabulary or model prompt assembly
is imported by this module.

### Infeasible memory and bounded proposals

`consolidate_memory(..., minimum_chars=callback)` accepts a host-proven lower bound
on the pending-applied snapshot. A bound above the hard limit returns
`capacity_unreachable` with zero model attempts. Do not pass an estimate or assume
protected entries cannot be merged. Unknown feasibility keeps normal planning.
The host owns any separate correction-only transaction; this helper never writes storage.

Selection replies are limited to 16 groups of 16 IDs and 64 removal ranges, leaving
unselected entries unchanged. A truncated selection switches to an existing safe
removal option with a 128-token vote; if no safe option exists (or the vote truncates),
stop. No partial JSON is applied, no repeated long-output retry, no automatic deletion.

### Working summaries over a searchable archive

`cairnkit.memory_archive.project_archive` is a pure, optional projection. It accepts
`ArchiveFact(key, text, order, topic, keep_detail)` records, explicit character and
rank thresholds, and a host `summarize(facts, level)` callback. The result partitions
all input keys into detailed keys and typed summary groups; it never edits or deletes
canonical records. Archive keys remain available for scoped, bounded host retrieval.

When the full representation exceeds `limit`, older eligible facts are grouped until
`target` fits, trying distant then middle ranks. Recent, durable/explicitly protected,
unknown-origin and ungroupable facts remain detailed. If only an under-limit result
is possible it is returned; otherwise `capacity_unreachable` leaves input untouched.
A rebuilding summary never changes original source order. Character counts include
`ENTRY_DELIMITER`; host metadata and chat context budgets are separate.

Hosts must retain all canonical facts, validate topic/summary semantics and provenance,
apply pending corrections before projecting, enforce owner/agent scope and revocation,
and rebuild/invalidate views after completion, expiry, deletion, merging or retention.
Do not apply the working-view budget as a total disk-store cap or treat the projection
as approval for data loss. No model, database, framework or prompt builder is used here.
This projection extends the original Hermes memory mechanism.
