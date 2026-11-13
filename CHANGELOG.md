# Changelog

Versioning rules: see [README](README.md#versioning).

## v0.6.1 (2026-11-13)

- **Fix silent streaming success on truncated responses.** `OpenAICompatModel` now requires
  a non-empty string `finish_reason` for choice 0 and a complete SSE `[DONE]` event before
  returning a `ModelResponse`. EOF, `[DONE]` alone, missing `[DONE]`, malformed JSON or
  chunk structure, provider errors, and output or conflicting reasons after the terminal
  frame raise `ModelAPIError` (502 for invalid/incomplete responses). Streams cannot hand
  unfinished tool calls to the agent loop. Transport errors and cancellation still propagate.
- SSE parsing assembles multi-line `data:` events, ignores comments and other SSE fields,
  and rejects events cut off before their blank-line separator. Streaming selects choice 0
  instead of combining alternatives, matching the single-completion return type.
- Normal `stop`, `length`, `tool_calls`, `content_filter` and other non-error string reasons
  pass through for the host to interpret. Empty content is still allowed with valid terminal
  markers. Both OpenAI's empty-choices usage frame and OpenRouter's content-free usage frame
  repeating the same finish reason are supported.
- Compatibility: custom endpoints must send both terminal markers. Previously accepted
  malformed or incomplete streams now raise. Already emitted `on_delta` text is provisional;
  callers must handle failure before treating a turn as complete. The client does not retry;
  `FallbackModel` retains its existing policy before output and never retries/falls back once
  text has been emitted. No continuation or replacement answer is added.

## v0.6.0 (2026-11-12)

New optional module **`cairnkit.knowledge`**: documents an agent can search and quote.
Design and growth path: [docs/knowledge-design.md](docs/knowledge-design.md).

- `SQLiteStore`: documents, chunks and indexes in SQLite (standard library only). Give it a
  path or your own `sqlite3.Connection`; tables share a prefix (`kn_`), so they can live in
  the application's database. Your connection's `row_factory` is left alone.
- Chunking by Markdown headings, then paragraphs and sentences; the heading path is indexed
  and returned, so answers can cite "Travel policy > Meals".
- Keyword search per collection language: English (`porter`; words of 5+ letters also match
  as a prefix) and Chinese / Japanese / Korean (`trigram`; two-character words via LIKE,
  near phrases via any-trigram fallback). All words first, then any word.
- Optional vectors (`pip install "cairnkit[vectors]"`): `FastEmbed` runs a small
  multilingual model on the CPU; vectors are plain float32 blobs, scored by sqlite-vec when
  installed or in Python otherwise. `KnowledgeBase` fuses keyword and vector hits with RRF
  (`rrf()`); vector hits below `min_similarity` (default 0.4) are dropped so absent topics
  find nothing. `reindex()` embeds what was added before the embedder.
- `KnowledgeSearchBackend` plugs into `make_search_tool`: scope (collections + metadata
  filters) and an optional `allowed` check come from the host per run, and apply to search,
  read, context and browse. `timeline=True` for dated entries (notes, logs): the newest
  keyword match wins, vector-only hits never displace it.
- `cairnkit.knowledge.evaluate`: run your own cases through the real search tool and get
  found / seen / full per kind of question; assert floors in your tests.
- `ChunkHit.via` says which search found a hit.

Nothing changes for existing code; the core still imports nothing new.

## v0.5.1 (2026-11-12)

- `make_search_tool`: `discover` now expands the best hit around the item that matched
  (`SearchHit.item_id`, five items on each side, via `SearchBackend.around`) instead of the
  document's 20 most recent items. Before, a match older than those was visible only as its
  snippet. The expansion says which item it is centred on (`top.around_id`). Hits without an
  `item_id`, or whose item `around` cannot find, are expanded as before.

## v0.5.0 (2026-11-09)

Follows Hermes Agent v0.23.0 (`2bd378e`). What was taken, skipped or left for later, and why:
[docs/hermes-porting.md](https://github.com/wasabihu/cairnkit/blob/v0.5.0/docs/hermes-porting.md#v0230-2bd378e-checked-2026-11-09).

- **On PyPI.** Install with `pip install cairnkit` or `uv add cairnkit`; releases are
  published from a tag (`.github/workflows/release.yml`).
- New example `examples/verify_citations.py`: a read tool that checks a draft's DOIs and PMIDs
  with [claimcite](https://github.com/wasabihu/claimcite) before a person reviews it.

New (optional, existing code keeps working):

- `ContextCompressor(fallback_model=...)`: when a separate summary model fails (dead
  endpoint, quota, unknown model, bad key), the summary is retried once on this model,
  usually the agent's main model. `CompressionResult.fallback_model_used` and
  `summary_model_error` say it happened, so the host can warn that the summary model is broken.
- `ClassifiedError.context["timeout_phase"]` (`"connect"` or `"read"`), and timeout messages
  that say whether a connection was made and what to change. `AllModelsFailed` repeats them.

Changed behaviour:

- Compression summaries have a `## Unverified / Working Hypotheses` section and the prompt asks
  for uncertain claims as `UNVERIFIED: <claim> — <basis>` lines, so guesses no longer turn into
  facts. Hosts with their own `summary_sections` get the label rule without the section.
- The lean compression tail never exceeds half the trigger, so a small `threshold_tokens` on a
  large window can get below the trigger again.
- A 400 that names a request-body byte cap (Novita, Z.AI, "content-length ... bytes") is
  `payload_too_large` and triggers compression instead of a format error.
- Streamed tool calls: a new id at an index already in use starts a new call only when it is
  named and the previous call's arguments are complete. Ollama's parallel calls (all at index
  0) are now separate calls; LM Studio, Kimi and MiniMax fragments stay one call.
- Tool results: a JSON result counts as failed when it has a non-empty `error`, a `status` of
  `failed`/`error`, or a `results` list where every item has an error (before, only
  `success: false`). This affects loop protection and `ToolRecord.failed`. A rate-limited
  failure no longer counts toward the identical-arguments warning and block.
- Memory tool: the schema lists only `target` and `operations` (a single change is a one-item
  list). The single-change shape and the `new_text` alias are still accepted. Batches that
  only remove, or a lone duplicate add, are no longer refused when the store is over a lowered
  limit, and a lone add over the limit says how many characters to free.
- `history_search` with no arguments lists 10 documents by default (a search still returns 3).
- `REVIEW_INSTRUCTION` tells the reviewer to save only facts grounded in the conversation, never
  inferred traits or one-off requests as standing preferences.

## v0.4.1 (2026-10-22)

- `documents`: text and Markdown files saved as Simplified Chinese by older Windows tools
  (GBK / GB18030) are now read correctly instead of as Windows-1252 garbage. The result
  carries a warning saying how the text was read. Western legacy text is unchanged.

## v0.4.0 (2026-10-22)

- `make_delegate_tool(..., on_child_run=...)`: a hook that sees every finished child run
  (agent, result, parent context), so child model calls can be billed. The parent's
  `RunResult.usage` still covers only its own calls.
- `generate_title(..., on_usage=...)`: receives the title call's token usage, also when the
  title is rejected.
- `RunResult.compression_usage` and `CompressionResult.usage`: what the summary model used
  when compaction ran, so it can be billed too.

All are additions (optional arguments or new fields); existing code keeps working unchanged.

## v0.3.0 (2026-10-21)

First public release. The project was developed privately as `agentcore`.

- **Renamed to cairnkit.** The package, the import name and the repository are now
  `cairnkit`. To upgrade from `agentcore` 0.2: change the dependency to
  `cairnkit` (or `cairnkit[documents]`), point the source at
  `https://github.com/wasabihu/cairnkit` tag `v0.3.0`, and replace `agentcore` with
  `cairnkit` in imports. Nothing else changed in the API.
- English documentation, contribution and security guides, CI on Python 3.12 and 3.13,
  `py.typed`, and two more examples (`approval.py`, `read_document.py`).

## v0.2.0 (2026-10-21)

- Optional module `documents`: PDF, Word (.docx), Excel (.xlsx) and text to Markdown
  (`extract_text`), with limits on size, pages, rows and unzipped size, stable error codes
  (`DocumentError.code`) and replaceable readers (`register_extractor`).
- Optional dependency group `documents` (pypdf, openpyxl). Core dependencies unchanged.

## v0.1.0 (2026-10-21)

First version as a standalone package, based on Hermes Agent v0.22.2 (`d923a5e`).

- Agent loop (streaming, tool rounds, loop protection, forced final answer)
- Tool registry with access levels and roles; three-layer system prompt; skills shown on
  demand with injection scanning
- Memory editing rules (add / patch / remove), history search, background review,
  delegation to sub-agents
- Context compression following Hermes' full implementation (token anchors, cooldowns,
  anti-thrashing, incremental summaries, forced compaction and retry on overflow)
- Skill curation (returns a plan; the host decides)
- Models: OpenAI-compatible client, OpenRouter, error classification, fallback chain,
  offline scripted model; cost estimates; automatic titles
- `scripts/hermes_changes.py` and the Hermes upgrade guide
