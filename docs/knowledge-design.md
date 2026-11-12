# Design: a small knowledge module (`cairnkit.knowledge`)

Status: **stages 0 and 1 implemented in v0.6.0** (SQLite keyword search, English and Chinese,
optional local vectors). Stage 2 (Postgres) is planned. Read this before changing the module.

## 1. Goal

Let an agent search a body of documents (policies, manuals, FAQs, notes) and quote what it
found, with as little machinery as possible on day one and a clear path when the data grows.

- **Start small:** SQLite from the standard library, keyword search (FTS5 + BM25), no new
  dependencies, no model calls, no server.
- **Grow without rewrites:** vectors, then another database, arrive as new back ends behind
  the same interface. Application code and agent tools do not change.
- **Stay a cairnkit module:** identity and permissions come from the host (`ToolContext`);
  search returns stored text only and never calls a model (the Hermes rule kept in
  `search.py`); results can be cited back to a document, a version and a heading.

Non-goals for now: re-ranking models, query expansion by a model inside search, graph RAG,
file watching, an admin UI, document conversion (use `cairnkit.documents` for PDF, Word and
spreadsheets).

## 2. Where it sits

`cairnkit.knowledge` is an **optional module**, like `cairnkit.documents`: the core does not
import it. It uses only `sqlite3` from the standard library, so it needs no extra install.
Optional back ends that need packages get their own extras (`cairnkit[vectors]`,
`cairnkit[postgres]`), and the module works without them.

This changes one line of the README's promise ("no database, no vector store"). The new
wording: the core still has none; `knowledge` is a reference store an application may use
or replace, and the store is always the application's (its file, its connection, its
backups).

## 3. Model

```
Document  id, collection, title, source, version, updated_at, metadata (dict), text
Chunk     id, document_id, ordinal, heading_path ("Travel policy > Expenses > Meals"), text
```

- **Collection** is a namespace (one per tenant, project or kind of material). Every query
  names one or more collections; nothing searches across all of them by accident.
- **Metadata** is a flat dict of strings the host filters on (department, audience,
  language, visibility). The store does not interpret it.
- **Versions:** upserting a document with the same id replaces its chunks and bumps its
  version; `updated_at` and `version` travel with every result, so the agent can say how
  current a quote is. Keeping old versions is the host's choice (store them as separate
  documents with a `superseded_by` metadata key).

## 4. Pipeline

1. **Ingest** text or Markdown (other formats through `cairnkit.documents` first).
2. **Chunk by structure:** split on Markdown headings, then on paragraphs to a size limit
   (default 1,500 characters, no overlap). Each chunk keeps its heading path, and the
   heading path is indexed with the text, so a chunk that says "keep receipts over $50"
   is still found by a search for "meal expenses". Lessons from practice: clean chunks and
   heading context matter more than the retrieval model.
3. **Index** each chunk in FTS5 (and later in a vector index).

Whole short documents may stay one chunk; a document under the size limit is never split.

## 5. Interfaces

```python
store = SQLiteStore(path_or_connection, prefix="kn_", vectors="auto")
store.ensure_collection("handbook", language="en")       # "zh" / "ja" / "ko" -> trigram
store.upsert(document, chunks=None)  # replaces the previous version; chunks by headings
store.delete(document_id)
store.get(document_id) / store.chunks(document_id) / store.chunk_window(doc, chunk, n)
store.recent(query)                  # recently updated documents in scope
store.lexical(query)                 # keyword hits, best first
store.vector(query, embedding, model, min_similarity)
store.set_vectors(model, [(chunk_id, vector)]) / store.missing_vectors(model)

kb = KnowledgeBase(store, embedder=None, mode=None, min_similarity=0.4)
kb.add(document, chunks=None)        # upsert + embed when an embedder is set
kb.reindex()                         # embed chunks that have no vector from this model
kb.search(Query(text, collections, filters, limit))   # lexical / vector / hybrid (RRF)

class Embedder(Protocol):            # FastEmbed() is the local default
    name: str
    def embed_documents(self, texts) -> list[list[float]]: ...
    def embed_query(self, text) -> list[float]: ...
```

A second store (Postgres) implements the same `store` calls; `KnowledgeBase` and
everything above it stay unchanged. `rrf(lists, k=60)` is a plain function. Hits are
folded per document by the agent tool (best chunk first), like `search.py` does.

**Permissions** never live in the store. The host turns the signed-in person into
`collections` and `filters` (from `ToolContext`) before every query, and may pass an
`allowed(document, ctx) -> bool` callback as a last check. Tests show that a document
outside the scope is never returned by search, read, context or browse.

## 6. Agent tool

`KnowledgeSearchBackend` implements the existing `SearchBackend`, so `make_search_tool`
works unchanged:

| tool shape | knowledge meaning |
|---|---|
| `query` (discover) | best documents; the best one expanded **around the matching chunk** (v0.5.1 behaviour) |
| `doc_id` + `around_id` | neighbouring chunks: context backfill on demand |
| `doc_id` | the whole document in order |
| no arguments | recently updated documents |

Each item carries `title`, `heading_path`, `version` and `updated_at`, so the agent can cite
"Travel policy v3, Meals (updated 2026-10-02)". Hosts that want a separate tool name
per collection register the tool twice with different backends.

A host with few documents can skip search entirely and keep using skills (`skill_view`
returns a whole document; no chunking loss). The module is for when that stops fitting:
roughly 20+ documents, or documents over the 40,000-character skill limit.

## 7. Lexical search details (from practice)

- Build the FTS5 query from words only (quoted, never raw operators), at most 12 words.
- **All words first, then any word** when nothing matches.
- Words of 5+ letters also match as a prefix: the porter stemmer gives "allergy" and
  "allergic" different stems; short words stay exact ("cart" must not match "cartridge").
- BM25 rank, then newest first.
- **Tokenizer per collection:** `porter unicode61` for English (default); `trigram` for
  Chinese, Japanese and mixed text (unicode61 does not segment CJK). Trigram cannot match
  queries shorter than three characters; for those the store falls back to `LIKE` on the
  collection (fine at small scale; documented as a limit).

## 8. Growth path

| stage | when | what changes |
|---|---|---|
| 0. SQLite, keyword | start | `SQLiteStore` (stdlib), FTS5 + BM25 |
| 1. + vectors | real questions miss because of wording (measure with §9 first) | `cairnkit[vectors]`: vectors in SQLite via sqlite-vec, or SQLite's own vec1 once it ships in releases; `Embedder` local (fastembed, small English or multilingual model, data stays on the server) or any HTTP API |
| 2. + Postgres | several app servers, many concurrent writers, or millions of chunks | `cairnkit[postgres]`: `PostgresStore` with tsvector (or a BM25 extension such as ParadeDB) + pgvector, same `KnowledgeStore` interface |

Notes:
- Brute-force vector search in Python is enough for tens of thousands of chunks; an
  index (sqlite-vec / vec1 / pgvector HNSW) is needed beyond that.
- Embeddings are stored with the model name and dimension; changing models re-embeds in
  the background and searches stay keyword-only until it finishes.
- A migration helper copies documents from one store to another (re-chunk and re-embed on
  the way), so moving from SQLite to Postgres is a script, not a rewrite.

## 9. Evaluation

Retrieval quality is measured, not assumed. `cairnkit.knowledge.evaluate`:

- `Case(query, expected_document, expected_item=None, kind="exact")`;
- runs the real `SearchBackend` through the real search tool;
- reports per case and per kind: **found** (right document in hits), **seen** (right chunk
  visible to the model), **full** (right chunk's full text in the expansion);
- hosts keep their own corpus and cases and assert per-kind floors in their tests.

Kinds that proved useful: `exact`, `morph` (word forms), `synonym`, `old` (match outside the
most recent items), `latest` (an older item says otherwise). No model calls; real-model
answer checks are a separate, opt-in step.

## 10. Decisions (2026-11-12)

1. **Storage file:** both. `SQLiteStore` takes a path (own connection, WAL) or the host's
   open `sqlite3.Connection`; all tables share a prefix. A shared connection's
   `row_factory` is never changed: the store uses its own cursors.
2. **Chinese from the start:** collections are created with a language; `zh` / `ja` / `ko`
   use the `trigram` tokenizer (SQLite 3.34+). Terms under three characters use LIKE, which
   scans the collection: fine for thousands of chunks, the first thing to revisit at scale.
3. **Versions belong to the host:** the store keeps the current version only; `version` and
   `updated_at` are stored as given and returned with every hit.
4. **Vectors now, as an option:** sqlite-vec scores (Python fallback), vectors stored as
   float32 blobs so the scorer can change (SQLite's vec1, pgvector) without migrating data.
   Default model `paraphrase-multilingual-MiniLM-L12-v2` (English, Chinese and ~50 more,
   384 dimensions, ~220 MB; loading it takes a few hundred MB of memory).
5. **`min_similarity` = 0.4** for the default model: at 0.3 more paraphrases are found, but
   questions about absent topics start returning unrelated text, which an agent that must
   say "not recorded" cannot afford.
6. **Timelines:** with `timeline=True` a document's hit is its newest *keyword* match;
   vector-only hits never displace one (they did in testing, hiding an exact older match).

## 11. Measurements (fictional data, v0.6.0)

A host's notes corpus (18 cases, 5 kinds), `full` = the right entry's full text reaches the
model:

| mode | exact | word forms | other words | old entry | newer entry wins | all |
|---|---|---|---|---|---|---|
| host's previous FTS5 search | 1.00 | 1.00 | 0.17 | 1.00 | 1.00 | 0.72 |
| knowledge, keyword | 1.00 | 1.00 | 0.17 | 1.00 | 1.00 | 0.72 |
| knowledge, hybrid (0.4) | 1.00 | 1.00 | 0.33 | 1.00 | 1.00 | 0.78 |
| knowledge, hybrid (0.3) | 1.00 | 1.00 | 0.67 | 1.00 | 1.00 | 0.89 |

Absent topics returning anything: keyword 1/10, hybrid 0.4 1/10, hybrid 0.3 3/10.

`examples/knowledge.py` (English and Chinese handbook, 17 cases): keyword 0.71 (all exact,
word-form, two-character Chinese and near-phrase cases pass; 1/6 other-words), hybrid 0.88
(other-words: right document 6/6, right section 4/6); absent topics 0/6 keyword, 1/6 hybrid.

## 12. Next

- Stage 2: `PostgresStore` (tsvector or a BM25 extension, pgvector) behind the same calls,
  plus a copy-between-stores helper.
- A vector index (sqlite-vec `vec0` or vec1) when a collection passes tens of thousands of
  chunks; today vectors are scored by a scan.
- Chinese terms under three characters: an n-gram side index if LIKE scans get slow.
