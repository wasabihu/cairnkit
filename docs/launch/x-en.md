# X launch draft — English (v0.7.0)

Status: draft, not posted. Attach `docs/assets/cairnkit-approval-demo.mp4` to post 1.
The two blocks below are separate posts; the attribution stays in the same thread.

## Post 1

If you're adding an AI agent to a real business app, the model shouldn't decide who the user is or directly mutate production rows.

I open-sourced cairnkit (v0.7.0, MIT, on PyPI): host injects `ToolContext`, tools declare `read`/`propose`/`write`, and writes wait for human review + version checks.

35s offline demo:
https://github.com/wasabihu/cairnkit

## Post 2

Core depends only on stdlib + httpx (no bundled web framework or DB). Offline `ScriptedModel` demos include stdlib ASGI+SQLite+SSE approval with 403/409 locks (`examples/web_approval.py`) and 0-call memory screening + archival projection (`examples/zero_call_memory.py`).

Many loop/compression/memory mechanisms are ported from Hermes Agent v0.23.0 (MIT, Nous Research; porting map inside, not affiliated). `pip install cairnkit`
