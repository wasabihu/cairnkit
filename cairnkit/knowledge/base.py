"""``KnowledgeBase``: add documents and search them, by keywords, vectors, or both."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from cairnkit.knowledge.embedders import Embedder
from cairnkit.knowledge.model import Chunk, ChunkHit, Document, Query
from cairnkit.knowledge.sqlite_store import SQLiteStore

Mode = Literal["lexical", "vector", "hybrid"]
RRF_K = 60


def rrf(lists: Sequence[Sequence[ChunkHit]], k: int = RRF_K) -> list[ChunkHit]:
    """Reciprocal Rank Fusion: merge ranked lists by rank, not by their incomparable scores.
    A chunk's score is the sum of 1 / (k + rank) over the lists it appears in; ties keep the
    order of the earlier lists."""
    scores: dict[str, float] = {}
    first: dict[str, ChunkHit] = {}
    order: dict[str, int] = {}
    via: dict[str, tuple[str, ...]] = {}
    for hits in lists:
        for rank, hit in enumerate(hits, start=1):
            key = hit.chunk.id
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
            via[key] = tuple(dict.fromkeys([*via.get(key, ()), *hit.via]))
            if key not in first:
                first[key] = hit
                order[key] = len(order)
    ranked = sorted(scores, key=lambda key: (-scores[key], order[key]))
    return [
        ChunkHit(first[key].chunk, first[key].document, scores[key], first[key].snippet, via[key])
        for key in ranked
    ]


class KnowledgeBase:
    """Keyword search always; vector search when an ``embedder`` is given.

    ``mode`` "hybrid" (default with an embedder) fuses both lists with RRF; vector hits
    below ``min_similarity`` are dropped, so a query about something absent does not drag
    in whatever happens to be nearest. 0.4 suits the default model: lower finds more
    paraphrases but also more unrelated text. Measure with ``evaluate`` before changing it.
    """

    def __init__(
        self,
        store: SQLiteStore,
        embedder: Embedder | None = None,
        *,
        mode: Mode | None = None,
        min_similarity: float = 0.4,
    ) -> None:
        self.store = store
        self.embedder = embedder
        self.mode: Mode = mode or ("hybrid" if embedder else "lexical")
        if self.mode != "lexical" and embedder is None:
            raise ValueError(f"mode {self.mode!r} needs an embedder")
        self.min_similarity = min_similarity

    def add(self, document: Document, chunks: Sequence[Chunk] | None = None) -> Document:
        stored = self.store.upsert(document, chunks)
        if self.embedder is not None:
            self._embed(self.store.chunks(stored.id))
        return stored

    def remove(self, document_id: str) -> None:
        self.store.delete(document_id)

    def reindex(self, batch: int = 64) -> int:
        """Embed chunks that have no vector from the current model (after adding an embedder
        or changing models). Returns how many were embedded."""
        if self.embedder is None:
            return 0
        total = 0
        while chunks := self.store.missing_vectors(self.embedder.name, limit=batch):
            total += self._embed(chunks)
        return total

    def _embed(self, chunks: Sequence[Chunk]) -> int:
        assert self.embedder is not None
        texts = [" > ".join(x for x in (c.heading_path, c.text) if x) for c in chunks]
        vectors = self.embedder.embed_documents(texts)
        return self.store.set_vectors(
            self.embedder.name, zip([c.id for c in chunks], vectors, strict=True)
        )

    def search(self, query: Query) -> list[ChunkHit]:
        if self.mode == "lexical" or not query.text.strip():
            return self.store.lexical(query)
        assert self.embedder is not None
        vector = self.store.vector(
            query,
            self.embedder.embed_query(query.text),
            self.embedder.name,
            self.min_similarity,
        )
        if self.mode == "vector":
            return vector
        return rrf([self.store.lexical(query), vector])[: query.limit]
