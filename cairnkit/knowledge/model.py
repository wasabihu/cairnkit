"""Records the knowledge module stores and returns."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

MetadataValue = str | Sequence[str]


@dataclass(frozen=True)
class Document:
    """A document as the host gives it. ``version`` and ``updated_at`` are the host's: the
    store keeps the current version only and never invents history (empty ``updated_at``
    becomes the time of the upsert)."""

    id: str
    collection: str
    title: str
    text: str = ""
    source: str = ""
    version: int = 1
    updated_at: str = ""  # ISO 8601
    metadata: Mapping[str, MetadataValue] = field(default_factory=dict)


@dataclass(frozen=True)
class Chunk:
    """A searchable piece of a document. ``when`` and ``author`` are optional and used by
    timelines (notes, logs) where each chunk is a dated entry."""

    id: str
    document_id: str
    ordinal: int
    heading_path: str
    text: str
    when: str = ""
    author: str = ""


@dataclass(frozen=True)
class ChunkHit:
    chunk: Chunk
    document: Document  # without its text
    score: float  # higher is better within one result list
    snippet: str
    via: tuple[str, ...] = ()  # "lexical" and/or "vector": which search found it


@dataclass(frozen=True)
class Query:
    """What to search and where. ``collections`` must name at least one collection; nothing
    searches every collection by accident. ``filters`` are AND-ed; a list value means any
    of these values."""

    text: str
    collections: Sequence[str]
    filters: Mapping[str, MetadataValue] = field(default_factory=dict)
    limit: int = 20


def matches(document: Document, collections: Sequence[str], filters: Mapping) -> bool:
    """Does a document fall inside a scope (collections + metadata filters)?"""
    if document.collection not in collections:
        return False
    for key, wanted in filters.items():
        wanted_set = {wanted} if isinstance(wanted, str) else set(wanted)
        have = document.metadata.get(key)
        have_set = set() if have is None else {have} if isinstance(have, str) else set(have)
        if not wanted_set & have_set:
            return False
    return True
