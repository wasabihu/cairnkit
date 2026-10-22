# Approval example

The example follows one fictional invoice-email request through a real cairnkit tool
loop and an example host's review function. All addresses use the reserved `example.com`
domain. Nothing contacts a model provider, sends an email, or writes to a database.

## Run it

From a checkout of **main containing this demo** (the original v0.4.1 tag has the earlier,
shorter example):

```bash
uv run python examples/approval.py
```

The terminal asks the human to act as the fictional reviewer Alex:

- `approve`: the host applies the exact pending change and increments the record version.
- `reject`, an empty response, or EOF: the record remains unchanged.

For a repeatable run without terminal input:

```bash
uv run python examples/approval.py --decision approve
uv run python examples/approval.py --decision reject
```

`--decision` **simulates the human's choice** for automation. Do not describe an automated
run as evidence that a real reviewer approved a real change.

## Replay the recorded states

Regenerate the visual replay from actual example execution:

```bash
uv run python examples/approval.py --decision approve --export examples/approval-demo/trace.js
python3 -m http.server 8768 --bind 127.0.0.1 --directory examples/approval-demo
```

Open <http://127.0.0.1:8768>. Use Play, Next step, or the five numbered stages.
The static page also works by opening `examples/approval-demo/index.html` directly.
Its data comes from `trace.js`; the controls replay snapshots and do not approve records.
The playback lasts 35 seconds (five stages, seven seconds each), with no automatic playback.

The [MP4](assets/cairnkit-approval-demo.mp4) and [GIF](assets/approval-demo.gif) show those
recorded states. They are visual walkthroughs, not a recording of a live LLM session.

## What cairnkit does, and what the host does

| Responsibility | Owner in this example |
| --- | --- |
| Model → tool → model loop | cairnkit `Agent` |
| Deterministic model responses | cairnkit `ScriptedModel` |
| Offer tools by role and recheck the role on dispatch | cairnkit `ToolRegistry` |
| Principal and selected ticket | Host-created `ToolContext` |
| Validate arguments, ticket scope, and create pending draft | Example tool handlers |
| Check reviewer, pending status, and record version | Example host `review()` |
| Apply approved value, record the decision | Example in-memory host store |

There is no save/approve tool in this agent's allowed tools. The host review function is
called separately from the agent loop. `access="propose"` describes a tool's intent;
it does not automatically intercept writes or create an approval queue.

## Limits

- The fixture identities are not authentication. A production host must derive the person,
  roles, and record scope from its own authenticated session.
- The store is in memory and single-process. A production host needs durable drafts, audit
  history, and an atomic version check plus write; this example is not a database adapter.
- Email validation is intentionally basic. Implement your application's validation and
  ownership checks before applying contact changes.
- No model quality, throughput, latency, cost, or security benchmark is implied.
- Run `uv run pytest -q tests/test_approval_example.py` to check the workflow boundaries.

Many runtime mechanisms are ported from [Hermes Agent](https://github.com/NousResearch/hermes-agent)
(MIT, Nous Research). See [NOTICE.md](../NOTICE.md) and [the porting map](hermes-porting.md).
