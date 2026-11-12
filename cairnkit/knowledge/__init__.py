"""Knowledge: documents an agent can search and quote. Optional module.

Keyword search needs only the standard library (SQLite FTS5). Vector search needs
``pip install "cairnkit[vectors]"`` (sqlite-vec, fastembed). Design and growth path:
docs/knowledge-design.md.

    store = SQLiteStore("knowledge.sqlite3")          # or an open sqlite3.Connection
    store.ensure_collection("handbook", language="en")  # "zh" for Chinese
    kb = KnowledgeBase(store)                           # KnowledgeBase(store, FastEmbed())
    kb.add(Document(id="travel", collection="handbook", title="Travel policy", text=md))
    tool = make_search_tool(
        KnowledgeSearchBackend(kb, lambda ctx: Scope(["handbook"])), name="handbook_search"
    )
"""

from cairnkit.knowledge.backend import KnowledgeSearchBackend, Scope
from cairnkit.knowledge.base import KnowledgeBase, rrf
from cairnkit.knowledge.chunking import chunk_text, make_chunks
from cairnkit.knowledge.embedders import DEFAULT_MODEL, Embedder, FastEmbed
from cairnkit.knowledge.evaluate import Case, evaluate, report, summarise
from cairnkit.knowledge.model import Chunk, ChunkHit, Document, Query
from cairnkit.knowledge.sqlite_store import KnowledgeError, SQLiteStore

__all__ = [
    "DEFAULT_MODEL",
    "Case",
    "Chunk",
    "ChunkHit",
    "Document",
    "Embedder",
    "FastEmbed",
    "KnowledgeBase",
    "KnowledgeError",
    "KnowledgeSearchBackend",
    "Query",
    "SQLiteStore",
    "Scope",
    "chunk_text",
    "evaluate",
    "make_chunks",
    "report",
    "rrf",
    "summarise",
]
