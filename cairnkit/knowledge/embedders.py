"""Embedders turn text into vectors. Any object with this shape works; ``FastEmbed`` runs a
small model on the server's CPU (``pip install "cairnkit[vectors]"``), so text never leaves
the machine."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


class Embedder(Protocol):
    name: str  # stored with every vector; changing it means re-embedding (reindex)

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class FastEmbed:
    """Local embeddings via fastembed (ONNX Runtime, no PyTorch).

    The default model handles English and Chinese (and about 50 more languages), 384
    dimensions, about 220 MB, downloaded once into ``cache_dir``. Loading it takes a few
    hundred MB of memory; it is loaded on first use, not at import.
    """

    def __init__(self, model: str = DEFAULT_MODEL, *, cache_dir: str | None = None) -> None:
        self.name = model
        self._cache_dir = cache_dir
        self._model = None

    def _load(self):
        if self._model is None:
            try:
                from fastembed import TextEmbedding  # type: ignore[import-not-found]
            except ImportError as exc:
                raise ImportError('FastEmbed needs: pip install "cairnkit[vectors]"') from exc
            self._model = TextEmbedding(self.name, cache_dir=self._cache_dir)
        return self._model

    # passage_embed / query_embed add the prefixes models such as e5 expect.
    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [list(map(float, v)) for v in self._load().passage_embed(list(texts))]

    def embed_query(self, text: str) -> list[float]:
        return [float(x) for x in next(iter(self._load().query_embed([text])))]
