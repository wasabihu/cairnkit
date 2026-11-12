"""Measure retrieval quality with your own cases. No model calls.

    results = evaluate(backend, ctx, cases)
    print(report(results))

Per case: **found** (the right document is among the hits), **seen** (the right chunk is
visible to the model: a hit or the expanded chunks) and **full** (the right chunk's full
text is in the expansion). ``summarise`` gives the share per ``kind``; assert floors on it
in your tests so a change cannot quietly make retrieval worse.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from cairnkit.search import SearchBackend, make_search_tool
from cairnkit.tools import ToolContext

METRICS = ("found", "seen", "full")


@dataclass(frozen=True)
class Case:
    query: str
    document: str
    item: str | None = None  # expected chunk id; without it only "found" is meaningful
    kind: str = "exact"


def evaluate(
    backend: SearchBackend, ctx: ToolContext, cases: list[Case], *, limit: int = 3
) -> list[dict[str, Any]]:
    tool = make_search_tool(backend)
    results = []
    for case in cases:
        out = json.loads(tool.handler({"query": case.query, "limit": limit}, ctx))
        hits = out.get("hits") or []
        expanded = (out.get("top") or {}).get("items") or []
        found = any(h["doc_id"] == case.document for h in hits)
        if case.item is None:
            seen = full = found
        else:
            full = any(i["item_id"] == case.item for i in expanded)
            seen = full or any(h.get("item_id") == case.item for h in hits)
        results.append(
            {"query": case.query, "kind": case.kind, "found": found, "seen": seen, "full": full}
        )
    return results


def summarise(results: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    kinds = list(dict.fromkeys(r["kind"] for r in results))
    out = {}
    for kind in [*kinds, "all"]:
        rows = [r for r in results if kind in ("all", r["kind"])]
        if rows:
            out[kind] = {
                "n": len(rows),
                **{m: round(sum(r[m] for r in rows) / len(rows), 2) for m in METRICS},
            }
    return out


def report(results: list[dict[str, Any]]) -> str:
    lines = [f"{'kind':10} {'n':>3}  found  seen  full"]
    for kind, s in summarise(results).items():
        lines.append(f"{kind:10} {s['n']:>3}   {s['found']:.2f}  {s['seen']:.2f}  {s['full']:.2f}")
    return "\n".join(lines)
