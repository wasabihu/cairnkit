# Changelog

Versioning rules: see [README](README.md#versioning).

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
