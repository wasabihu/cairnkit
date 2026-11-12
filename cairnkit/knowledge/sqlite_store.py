"""Knowledge storage in SQLite: documents, chunks, full-text indexes and optional vectors.

Uses only ``sqlite3`` from the standard library. Give it a path (it opens its own
connection, in WAL mode) or an open ``sqlite3.Connection`` (it uses yours, so the tables
can live in the application's own database file). Every table name starts with
``prefix`` so the tables sit next to the application's without clashing; tell your
migration tool to ignore them.

Vectors are stored as plain float32 blobs in an ordinary table. Distances are computed by
the sqlite-vec extension when it is installed (``cairnkit[vectors]``), otherwise in
Python: fine for a few thousand chunks. The storage format does not depend on which one
computes, so switching (to sqlite-vec, SQLite's own vec1, or another database) needs no
data migration.
"""

from __future__ import annotations

import json
import math
import sqlite3
import struct
import threading
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from cairnkit.knowledge.chunking import make_chunks
from cairnkit.knowledge.model import Chunk, ChunkHit, Document, Query
from cairnkit.knowledge.query import Pass, plan

LANGUAGES = {"en": "en", "english": "en", "cjk": "cjk", "zh": "cjk", "ja": "cjk", "ko": "cjk"}
_TOKENIZERS = {"en": "porter unicode61", "cjk": "trigram"}
_LIKE = "(c.heading_path || ' ' || c.text) LIKE ? ESCAPE '\\'"


class KnowledgeError(Exception):
    pass


class SQLiteStore:
    def __init__(
        self,
        db: str | Path | sqlite3.Connection,
        *,
        prefix: str = "kn_",
        vectors: str = "auto",
    ) -> None:
        """``vectors``: "auto" (sqlite-vec if installed, else Python), "sqlite-vec" (must be
        installed) or "python"."""
        if not prefix.replace("_", "").isalnum():
            raise KnowledgeError("prefix may contain only letters, digits and underscores")
        if isinstance(db, sqlite3.Connection):
            self.conn = db
        else:
            self.conn = sqlite3.connect(str(db), check_same_thread=False)
            self._q("PRAGMA journal_mode=WAL")
        self.p = prefix
        self._lock = threading.RLock()
        self._create()
        self.vector_engine = self._load_vectors(vectors)

    # ------------------------------------------------------------------ schema

    def _create(self) -> None:
        p = self.p
        with self._lock, self.conn:
            self.conn.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {p}collections(
                    name TEXT PRIMARY KEY, language TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS {p}documents(
                    id TEXT PRIMARY KEY, collection TEXT NOT NULL, title TEXT NOT NULL,
                    source TEXT NOT NULL, version INTEGER NOT NULL, updated_at TEXT NOT NULL,
                    metadata TEXT NOT NULL, text TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS {p}documents_recent
                    ON {p}documents(collection, updated_at);
                CREATE TABLE IF NOT EXISTS {p}metadata(
                    document_id TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
                    PRIMARY KEY (document_id, key, value));
                CREATE INDEX IF NOT EXISTS {p}metadata_kv ON {p}metadata(key, value);
                CREATE TABLE IF NOT EXISTS {p}chunks(
                    rowid INTEGER PRIMARY KEY, id TEXT NOT NULL UNIQUE,
                    document_id TEXT NOT NULL, ordinal INTEGER NOT NULL,
                    heading_path TEXT NOT NULL, text TEXT NOT NULL,
                    item_when TEXT NOT NULL, author TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS {p}chunks_doc ON {p}chunks(document_id, ordinal);
                CREATE TABLE IF NOT EXISTS {p}vectors(
                    chunk_rowid INTEGER PRIMARY KEY, model TEXT NOT NULL, dim INTEGER NOT NULL,
                    embedding BLOB NOT NULL);
                """
            )
            for language, tokenizer in _TOKENIZERS.items():
                try:
                    self._q(
                        f"CREATE VIRTUAL TABLE IF NOT EXISTS {p}fts_{language} "
                        f"USING fts5(title_path, text, tokenize='{tokenizer}')"
                    )
                except sqlite3.OperationalError as exc:  # trigram needs SQLite 3.34+
                    if language == "en":
                        raise KnowledgeError(f"SQLite FTS5 is not available: {exc}") from exc

    def _load_vectors(self, mode: str) -> str:
        if mode == "python":
            return "python"
        try:
            import sqlite_vec  # type: ignore[import-not-found]

            self.conn.enable_load_extension(True)
            try:
                sqlite_vec.load(self.conn)
            finally:
                self.conn.enable_load_extension(False)
            return "sqlite-vec"
        except (ImportError, AttributeError, sqlite3.OperationalError) as exc:
            if mode == "sqlite-vec":
                raise KnowledgeError(f"sqlite-vec could not be loaded: {exc}") from exc
            return "python"

    # ------------------------------------------------------------------ collections

    def ensure_collection(self, name: str, language: str = "en") -> None:
        lang = LANGUAGES.get(language.lower())
        if lang is None:
            raise KnowledgeError(f"unknown language {language!r}; use one of {sorted(LANGUAGES)}")
        with self._lock, self.conn:
            row = self._q(
                f"SELECT language FROM {self.p}collections WHERE name = ?", (name,)
            ).fetchone()
            if row and row[0] != lang:
                raise KnowledgeError(f"collection {name!r} already uses language {row[0]!r}")
            if lang == "cjk" and not self._has_table(f"{self.p}fts_cjk"):
                raise KnowledgeError("CJK collections need SQLite 3.34+ (trigram tokenizer)")
            self._q(
                f"INSERT OR IGNORE INTO {self.p}collections(name, language) VALUES (?, ?)",
                (name, lang),
            )

    def _has_table(self, name: str) -> bool:
        return bool(self._q("SELECT 1 FROM sqlite_master WHERE name = ?", (name,)).fetchone())

    def _language(self, collection: str) -> str:
        row = self._q(
            f"SELECT language FROM {self.p}collections WHERE name = ?", (collection,)
        ).fetchone()
        if row is None:
            raise KnowledgeError(f"unknown collection {collection!r}; call ensure_collection")
        return row[0]

    # ------------------------------------------------------------------ writing

    def upsert(self, document: Document, chunks: Sequence[Chunk] | None = None) -> Document:
        """Store a document, replacing any previous version and its chunks and vectors.
        Without ``chunks`` the text is chunked by its structure."""
        if not document.id or not document.title:
            raise KnowledgeError("a document needs an id and a title")
        updated = document.updated_at or datetime.now(UTC).isoformat(timespec="seconds")
        stored = Document(
            id=document.id,
            collection=document.collection,
            title=document.title,
            text=document.text,
            source=document.source,
            version=document.version,
            updated_at=updated,
            metadata=dict(document.metadata),
        )
        pieces = list(chunks) if chunks is not None else make_chunks(document.id, document.text)
        if any(c.document_id != document.id for c in pieces):
            raise KnowledgeError("every chunk must belong to the document")
        p = self.p
        with self._lock, self.conn:
            fts = f"{p}fts_{self._language(document.collection)}"
            self._delete(document.id)
            self._q(
                f"INSERT INTO {p}documents VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    stored.id,
                    stored.collection,
                    stored.title,
                    stored.source,
                    stored.version,
                    stored.updated_at,
                    json.dumps(stored.metadata, ensure_ascii=False, sort_keys=True),
                    stored.text,
                ),
            )
            self.conn.executemany(
                f"INSERT INTO {p}metadata VALUES (?, ?, ?)",
                [
                    (stored.id, k, v)
                    for k, values in stored.metadata.items()
                    for v in _values(values)
                ],
            )
            for chunk in pieces:
                cur = self._q(
                    f"INSERT INTO {p}chunks(id, document_id, ordinal, heading_path, text, "
                    "item_when, author) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        chunk.id,
                        chunk.document_id,
                        chunk.ordinal,
                        chunk.heading_path,
                        chunk.text,
                        chunk.when,
                        chunk.author,
                    ),
                )
                title_path = " > ".join(x for x in (stored.title, chunk.heading_path) if x)
                self._q(
                    f"INSERT INTO {fts}(rowid, title_path, text) VALUES (?, ?, ?)",
                    (cur.lastrowid, title_path, chunk.text),
                )
        return stored

    def delete(self, document_id: str) -> None:
        with self._lock, self.conn:
            self._delete(document_id)

    def _delete(self, document_id: str) -> None:
        p = self.p
        rowids = [
            r[0]
            for r in self._q(f"SELECT rowid FROM {p}chunks WHERE document_id = ?", (document_id,))
        ]
        for language in _TOKENIZERS:
            if self._has_table(f"{p}fts_{language}"):
                self.conn.executemany(
                    f"DELETE FROM {p}fts_{language} WHERE rowid = ?", [(r,) for r in rowids]
                )
        self.conn.executemany(
            f"DELETE FROM {p}vectors WHERE chunk_rowid = ?", [(r,) for r in rowids]
        )
        self._q(f"DELETE FROM {p}chunks WHERE document_id = ?", (document_id,))
        self._q(f"DELETE FROM {p}metadata WHERE document_id = ?", (document_id,))
        self._q(f"DELETE FROM {p}documents WHERE id = ?", (document_id,))

    def set_vectors(self, model: str, vectors: Iterable[tuple[str, Sequence[float]]]) -> int:
        """Store embeddings for chunks (by chunk id), normalised to unit length."""
        count = 0
        with self._lock, self.conn:
            for chunk_id, vector in vectors:
                row = self._q(
                    f"SELECT rowid FROM {self.p}chunks WHERE id = ?", (chunk_id,)
                ).fetchone()
                if row is None:
                    continue
                unit = _normalise(vector)
                self._q(
                    f"INSERT OR REPLACE INTO {self.p}vectors VALUES (?, ?, ?, ?)",
                    (row[0], model, len(unit), _pack(unit)),
                )
                count += 1
        return count

    def missing_vectors(self, model: str, limit: int = 256) -> list[Chunk]:
        """Chunks without an embedding from ``model`` (new chunks, or a changed model)."""
        rows = self._q(
            f"SELECT c.* FROM {self.p}chunks c LEFT JOIN {self.p}vectors v "
            "ON v.chunk_rowid = c.rowid AND v.model = ? WHERE v.chunk_rowid IS NULL "
            "ORDER BY c.rowid LIMIT ?",
            (model, limit),
        ).fetchall()
        return [_chunk(r) for r in rows]

    # ------------------------------------------------------------------ reading

    def get(self, document_id: str) -> Document | None:
        row = self._q(f"SELECT * FROM {self.p}documents WHERE id = ?", (document_id,)).fetchone()
        return None if row is None else _document(row, with_text=True)

    def chunks(self, document_id: str) -> list[Chunk]:
        rows = self._q(
            f"SELECT * FROM {self.p}chunks WHERE document_id = ? ORDER BY ordinal",
            (document_id,),
        ).fetchall()
        return [_chunk(r) for r in rows]

    def chunk_window(self, document_id: str, chunk_id: str, window: int) -> list[Chunk] | None:
        found = self._q(
            f"SELECT ordinal FROM {self.p}chunks WHERE id = ? AND document_id = ?",
            (chunk_id, document_id),
        ).fetchone()
        if found is None:
            return None
        rows = self._q(
            f"SELECT * FROM {self.p}chunks WHERE document_id = ? AND ordinal BETWEEN ? AND ? "
            "ORDER BY ordinal",
            (document_id, found[0] - window, found[0] + window),
        ).fetchall()
        return [_chunk(r) for r in rows]

    def recent(self, query: Query) -> list[Document]:
        scope, params = self._scope(query)
        if scope is None:
            return []
        rows = self._q(
            f"SELECT d.* FROM {self.p}documents d WHERE {scope} "
            "ORDER BY d.updated_at DESC, d.id LIMIT ?",
            (*params, query.limit),
        ).fetchall()
        return [_document(r) for r in rows]

    def lexical(self, query: Query) -> list[ChunkHit]:
        """Full-text hits, best first. Collections in different languages are searched in
        their own index and the lists merged by rank."""
        groups: dict[str, list[str]] = {}
        for name in query.collections:
            groups.setdefault(self._language(name), []).append(name)
        lists = [
            self._lexical_one(language, Query(query.text, names, query.filters, query.limit))
            for language, names in groups.items()
        ]
        if len(lists) == 1:
            return lists[0]
        from cairnkit.knowledge.base import rrf

        return rrf(lists)[: query.limit]

    def _lexical_one(self, language: str, query: Query) -> list[ChunkHit]:
        scope, params = self._scope(query)
        if scope is None:
            return []
        for attempt in plan(query.text, language):
            rows = self._run_pass(language, attempt, scope, params, query.limit)
            if rows:
                return [self._hit(row, -float(row["score"] or 0), "lexical") for row in rows]
        return []

    def _run_pass(self, language: str, attempt: Pass, scope: str, params: list, limit: int):
        p = self.p
        like_sql, like_params = _likes(attempt)
        if attempt.match is not None:
            fts = f"{p}fts_{language}"
            sql = (
                f"SELECT c.*, bm25({fts}, 2.0, 1.0) AS score, "
                f"snippet({fts}, 1, '[', ']', '…', 16) AS snip "
                f"FROM {fts} JOIN {p}chunks c ON c.rowid = {fts}.rowid "
                f"JOIN {p}documents d ON d.id = c.document_id "
                f"WHERE {fts} MATCH ? AND {scope}{like_sql} "
                "ORDER BY score, c.item_when DESC, d.updated_at DESC, c.ordinal LIMIT ?"
            )
            args = [attempt.match, *params, *like_params, limit]
        else:
            any_terms = attempt.like_any
            order = " + ".join([_LIKE] * len(any_terms)) if any_terms else "0"
            sql = (
                f"SELECT c.*, -({order}) AS score, NULL AS snip FROM {p}chunks c "
                f"JOIN {p}documents d ON d.id = c.document_id WHERE {scope}{like_sql} "
                "ORDER BY score, c.item_when DESC, d.updated_at DESC, c.ordinal LIMIT ?"
            )
            args = [*(_like(t) for t in any_terms), *params, *like_params, limit]
        with self._lock:
            return self._rows(sql, args)

    def vector(
        self, query: Query, embedding: Sequence[float], model: str, min_similarity: float = 0.0
    ) -> list[ChunkHit]:
        """Nearest chunks by cosine similarity (scores are similarities, 1 = identical)."""
        scope, params = self._scope(query)
        if scope is None:
            return []
        p = self.p
        if not any(embedding):
            return []
        unit = _normalise(embedding)
        base = (
            f"FROM {p}vectors v JOIN {p}chunks c ON c.rowid = v.chunk_rowid "
            f"JOIN {p}documents d ON d.id = c.document_id WHERE v.model = ? AND v.dim = ? "
            f"AND {scope}"
        )
        with self._lock:
            if self.vector_engine == "sqlite-vec":
                rows = self._rows(
                    f"SELECT c.*, 1 - vec_distance_cosine(v.embedding, ?) AS sim {base} "
                    "ORDER BY sim DESC LIMIT ?",
                    (_pack(unit), model, len(unit), *params, query.limit),
                )
                scored = [(float(r["sim"]), r) for r in rows]
            else:
                rows = self._rows(
                    f"SELECT c.*, v.embedding AS emb {base}", (model, len(unit), *params)
                )
                scored = sorted(
                    ((_dot(unit, _unpack(r["emb"])), r) for r in rows),
                    key=lambda pair: -pair[0],
                )[: query.limit]
        return [self._hit(r, sim, "vector") for sim, r in scored if sim >= min_similarity]

    # ------------------------------------------------------------------ helpers

    def _q(self, sql: str, args=()) -> sqlite3.Cursor:
        """Plain tuples whatever row_factory the (possibly shared) connection has."""
        cursor = self.conn.cursor()
        cursor.row_factory = None
        return cursor.execute(sql, args)

    def _rows(self, sql: str, args) -> list[sqlite3.Row]:
        """Named rows without touching the connection's row_factory (it may be the host's)."""
        cursor = self.conn.cursor()
        cursor.row_factory = sqlite3.Row
        return cursor.execute(sql, args).fetchall()

    def _scope(self, query: Query) -> tuple[str | None, list]:
        """SQL condition on ``d`` (documents) for the query's collections and filters."""
        names = list(query.collections)
        if not names:
            return None, []
        parts = [f"d.collection IN ({', '.join('?' * len(names))})"]
        params: list = list(names)
        for key, wanted in query.filters.items():
            values = _values(wanted)
            if not values:
                return None, []
            parts.append(
                f"EXISTS (SELECT 1 FROM {self.p}metadata m WHERE m.document_id = d.id "
                f"AND m.key = ? AND m.value IN ({', '.join('?' * len(values))}))"
            )
            params.extend([key, *values])
        return " AND ".join(parts), params

    def _hit(self, row: sqlite3.Row, score: float, via: str) -> ChunkHit:
        chunk = _chunk(row)
        document = self._document_info(chunk.document_id)
        snip = row["snip"] if "snip" in row.keys() else None  # noqa: SIM118 (Row: keys)
        snippet = snip or chunk.text[:160]
        return ChunkHit(chunk, document, score, snippet, (via,))

    def _document_info(self, document_id: str) -> Document:
        row = self._q(f"SELECT * FROM {self.p}documents WHERE id = ?", (document_id,)).fetchone()
        return _document(row)


def _values(value) -> list[str]:
    return [value] if isinstance(value, str) else [str(v) for v in value]


def _like(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _likes(attempt: Pass) -> tuple[str, list]:
    terms = attempt.like_all
    clause = "".join(f" AND {_LIKE}" for _ in terms)
    params = [_like(t) for t in terms]
    if attempt.like_any and attempt.match is None:
        clause += " AND (" + " OR ".join(_LIKE for _ in attempt.like_any) + ")"
        params += [_like(t) for t in attempt.like_any]
    return clause, params


def _document(row, *, with_text: bool = False) -> Document:
    id_, collection, title, source, version, updated, metadata, text = tuple(row)[:8]
    return Document(
        id=id_,
        collection=collection,
        title=title,
        text=text if with_text else "",
        source=source,
        version=version,
        updated_at=updated,
        metadata=json.loads(metadata),
    )


def _chunk(row) -> Chunk:
    _, id_, document_id, ordinal, heading_path, text, when, author = tuple(row)[:8]
    return Chunk(
        id=id_,
        document_id=document_id,
        ordinal=ordinal,
        heading_path=heading_path,
        text=text,
        when=when,
        author=author,
    )


def _normalise(vector: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector))
    if norm == 0:
        raise KnowledgeError("cannot store a zero vector")
    return [float(x) / norm for x in vector]


def _pack(vector: Sequence[float]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def _unpack(blob: bytes) -> tuple[float, ...]:
    return struct.unpack(f"<{len(blob) // 4}f", blob)


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))
