"""Plug a knowledge base into the ``history_search`` tool (``make_search_tool``).

``doc_id`` is a document id, items are its chunks. The host says, per run, which
collections and metadata the signed-in person may see (``scope``); ``allowed`` is an
optional last check on each document. Nothing outside the scope is returned, counted or
expanded.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from cairnkit.knowledge.base import KnowledgeBase
from cairnkit.knowledge.model import Chunk, ChunkHit, Document, MetadataValue, Query, matches
from cairnkit.search import SearchHit, SearchItem
from cairnkit.tools import ToolContext


@dataclass(frozen=True)
class Scope:
    collections: Sequence[str]
    filters: Mapping[str, MetadataValue] = field(default_factory=dict)


class KnowledgeSearchBackend:
    def __init__(
        self,
        knowledge: KnowledgeBase,
        scope: Callable[[ToolContext], Scope],
        *,
        allowed: Callable[[Document, ToolContext], bool] | None = None,
        timeline: bool = False,
    ) -> None:
        """``timeline=True`` for documents whose chunks are dated entries in order (notes,
        logs): a document's hit is its newest keyword-matching entry, since an older entry
        may have been superseded, and reading a document starts from the newest entries."""
        self.kb = knowledge
        self.scope = scope
        self.allowed = allowed
        self.timeline = timeline

    # -------------------------------------------------------------- SearchBackend

    def search(self, query: str, ctx: ToolContext, limit: int) -> list[SearchHit]:
        scope = self.scope(ctx)
        hits = self.kb.search(Query(query, scope.collections, scope.filters, limit * 4))
        picked: dict[str, ChunkHit] = {}  # insertion order = rank of the document
        for hit in hits:
            if not self._visible(hit.document, scope, ctx):
                continue
            kept = picked.get(hit.document.id)
            if kept is None or (self.timeline and _newer_match(hit, kept)):
                picked[hit.document.id] = hit
        return [
            SearchHit(
                doc_id=hit.document.id,
                title=_title(hit.document),
                snippet=hit.snippet,
                when=hit.chunk.when or hit.document.updated_at,
                item_id=hit.chunk.id,
            )
            for hit in list(picked.values())[:limit]
        ]

    def read(self, doc_id: str, ctx: ToolContext, limit: int) -> list[SearchItem] | None:
        document = self._document(doc_id, ctx)
        if document is None:
            return None
        chunks = self.kb.store.chunks(doc_id)
        if self.timeline:
            chunks = sorted(chunks, key=lambda c: (c.when, c.ordinal), reverse=True)
        return [_item(c, document) for c in chunks[:limit]]

    def around(
        self, doc_id: str, item_id: str, ctx: ToolContext, window: int
    ) -> list[SearchItem] | None:
        document = self._document(doc_id, ctx)
        if document is None:
            return None
        chunks = self.kb.store.chunk_window(doc_id, item_id, window)
        return None if chunks is None else [_item(c, document) for c in chunks]

    def browse(self, ctx: ToolContext, limit: int) -> list[SearchHit]:
        scope = self.scope(ctx)
        documents = self.kb.store.recent(Query("", scope.collections, scope.filters, limit * 4))
        return [
            SearchHit(doc_id=d.id, title=_title(d), snippet="", when=d.updated_at)
            for d in documents
            if self._visible(d, scope, ctx)
        ][:limit]

    # -------------------------------------------------------------- helpers

    def _document(self, doc_id: str, ctx: ToolContext) -> Document | None:
        document = self.kb.store.get(doc_id)
        if document is None or not self._visible(document, self.scope(ctx), ctx):
            return None
        return document

    def _visible(self, document: Document, scope: Scope, ctx: ToolContext) -> bool:
        if not matches(document, scope.collections, scope.filters):
            return False
        return self.allowed is None or self.allowed(document, ctx)


def _newer_match(hit: ChunkHit, kept: ChunkHit) -> bool:
    """On a timeline the newest keyword match wins: the words are really there, and a newer
    entry may supersede an older one. Vector-only hits are near in meaning, not in fact, so
    they never displace a keyword match, and among themselves rank decides."""
    if "lexical" not in hit.via:
        return False
    if "lexical" not in kept.via:
        return True
    return (hit.chunk.when, hit.chunk.ordinal) > (kept.chunk.when, kept.chunk.ordinal)


def _title(document: Document) -> str:
    return document.title if document.version <= 1 else f"{document.title} (v{document.version})"


def _item(chunk: Chunk, document: Document) -> SearchItem:
    text = f"[{chunk.heading_path}] {chunk.text}" if chunk.heading_path else chunk.text
    return SearchItem(
        item_id=chunk.id, text=text, when=chunk.when or document.updated_at, author=chunk.author
    )
