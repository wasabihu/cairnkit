# Show HN draft — v0.7.0 (ready to submit)

Status: draft, not submitted. Be available to answer technical questions after posting.

## Title

Show HN: Cairnkit – Small Python agent runtime where the host owns identity, approval, and storage

## URL

https://github.com/wasabihu/cairnkit

## First comment

I built cairnkit (v0.7.0 on PyPI, MIT) for teams adding an agent loop into an existing multi-user Python backend rather than building a standalone single-user CLI agent.

The question behind it is: when an agent proposes an edit, what actually authorizes the write?

In cairnkit, the core stays small (Python 3.12+ standard library + `httpx`, no bundled web framework or database) and keeps control boundaries with the host:

- Host-injected `ToolContext` (principal, roles, record scope) separated from model tool arguments; the registry filters tools by role and checks the role again on dispatch.
- Explicit `read` / `propose` / `write` tool tiers. Approval queues and database transactions remain application code — marking a tool as `propose` does not itself enforce a workflow.
- Zero-call hot-path memory screening (`screen_memory_write`, `plan_operations`), ordinal layering (`layer_facts`), pure searchable archival projection (`project_archive`, preserving canonical host records), and bounded model consolidation (`consolidate_memory`, max 3 selection proposals with 95% over-removal guards).
- Strict streaming completion validation (requires terminal `finish_reason` + SSE `[DONE]` before returning) and four-phase context compression.

Offline runnable examples (all use `ScriptedModel` and fictional data, no API key required):

    pip install cairnkit
    # or clone and run the offline demos:
    git clone https://github.com/wasabihu/cairnkit.git
    cd cairnkit
    uv run python examples/approval.py          # terminal approve/reject demo
    uv run python examples/web_approval.py      # stdlib ASGI + SQLite + SSE + 403/409 optimistic lock
    uv run python examples/zero_call_memory.py  # 0-call screening, archive projection, overflow merge

Many loop, compression, and memory-safety mechanisms are ported from Hermes Agent v0.23.0 (MIT, Nous Research); file-level attribution and a porting map are in `docs/hermes-porting.md`. This is not affiliated with or endorsed by Nous Research.

I would appreciate feedback on how you split agent loop/memory planning from your application's own auth, review queue, and database transaction layer.
