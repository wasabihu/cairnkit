# cairnkit

[![CI](https://github.com/wasabihu/cairnkit/actions/workflows/ci.yml/badge.svg)](https://github.com/wasabihu/cairnkit/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)

**A small agent runtime for business applications.** The application decides who is
acting and what they may do; the model only ever proposes. Built for web apps where an AI
assistant works on shared, real data — customer records, notes, knowledge — and a person
stays in charge of what gets saved.

A cairn is a pile of stones that marks a trail so the next walker can follow it. cairnkit
does the same for agents: approved memory, searchable history and curated skills that the
next conversation builds on.

[中文说明](README.zh-CN.md)

## Why another agent runtime

Most agent frameworks assume one user and a trusted model. Business apps are different:
many people share the same data, roles decide who may do what, and an AI must not quietly
change records. cairnkit is built around that:

- **Identity comes from the host, never from the model.** Tools receive the signed-in
  person, their roles and the record being worked on in a `ToolContext`.
- **Writes become drafts.** Tools declare an access level (`read`, `propose`, `write`) and
  the roles that may use them. Memory edits arrive as reviewable plans, not silent writes.
- **Memory with guard rails.** Add / patch / remove edits located by quoted text, size
  limits, prompt-injection scanning and frozen snapshots, ported from Hermes Agent.
- **Long conversations stay cheap.** A faithful port of Hermes Agent's context compression:
  incremental structured summaries, real token anchors, cooldowns and verbatim user quotes.
- **Small.** The core depends only on the standard library and `httpx`. No web framework,
  no database, no vector store: storage and permissions stay in your application.

## What is inside

| Area                 | Module                       | What it does                                                                                                   |
| -------------------- | ---------------------------- | -------------------------------------------------------------------------------------------------------------- |
| Agent loop           | `loop.py`                    | Model → tools → model, streaming, a forced plain answer when the step budget runs out                          |
| Tools                | `tools.py`                   | Schema, handler, access level, allowed roles; identity is injected, never taken from the model                 |
| Loop protection      | `guardrails.py`              | Warns or stops on repeated failing calls and identical results                                                 |
| System prompt        | `prompt.py`                  | Stable / context / volatile layers, assembled once per conversation for prompt caching                         |
| Memory               | `memory.py`, `memory_ops.py` | Hermes' add / patch / remove rules; your store decides whether changes need approval                           |
| History search       | `search.py`                  | One tool, four modes (search, read, context, browse); no model calls                                           |
| Skills               | `skills.py`                  | `SKILL.md` folders, shown on demand, scanned for injection when loaded                                         |
| Context compression  | `compression.py`             | Four-phase compaction with incremental summaries and per-conversation `CompressionState`                       |
| Background review    | `review.py`                  | After a turn, a forked agent decides whether anything should be remembered                                     |
| Delegation           | `delegate.py`                | Hand a focused task to a specialist agent and get back only its answer (one level deep)                        |
| Skill curation       | `curator.py`                 | Marks unused skills stale, suggests archives and merges; returns a plan, you decide                            |
| Injection scanning   | `security.py`                | Prompt injection, hidden characters and exfiltration patterns                                                  |
| Titles               | `titles.py`                  | Instant title, upgraded by a small model; never overrides a title the user typed                               |
| Models               | `llm/`                       | OpenAI-compatible client (streaming), OpenRouter, error classification, fallback chain, offline scripted model |
| Cost                 | `pricing.py`                 | Uses the provider's reported cost, otherwise a price table                                                     |
| Agent definitions    | `agents.py`                  | One folder per agent: `agent.toml` + `SOUL.md`                                                                 |
| Documents (optional) | `documents.py`               | PDF, Word, Excel and text to Markdown, with size and zip-bomb limits                                           |

## Install

cairnkit is not on PyPI yet. Pin a release tag from GitHub:

```bash
uv add "cairnkit @ git+https://github.com/wasabihu/cairnkit@v0.3.0"
# with document reading (adds pypdf and openpyxl):
uv add "cairnkit[documents] @ git+https://github.com/wasabihu/cairnkit@v0.3.0"
```

or in `pyproject.toml`:

```toml
[project]
dependencies = ["cairnkit"]

[tool.uv.sources]
cairnkit = { git = "https://github.com/wasabihu/cairnkit", tag = "v0.3.0" }
```

Python 3.12 or newer.

## Quick start

An agent is a folder:

```
agents/
  greeter/
    agent.toml
    SOUL.md
```

```toml
# agents/greeter/agent.toml
description = "Answers questions about opening hours."
model = "default"          # a name your application maps to a model
tools = ["opening_hours"]  # the only tools this agent may use
skills = []                # optional: skills from a skills/ folder
max_iterations = 4
temperature = 0.2
```

`SOUL.md` holds the persona and rules; it goes into the stable layer of the system prompt.

```python
from cairnkit import Agent, ToolContext, ToolRegistry, load_agents, openrouter, tool_result

tools = ToolRegistry()

@tools.tool(name="opening_hours", description="Opening hours for a weekday.",
            parameters={"type": "object", "properties": {"day": {"type": "string"}},
                        "required": ["day"]})
def opening_hours(args, ctx):
    return tool_result(day=args["day"], hours="7am-7pm")

specs = load_agents("agents")
agent = Agent(specs["greeter"], model=openrouter("openai/gpt-4.1-mini", api_key="..."),
              tools=tools)
result = await agent.run("When do you open on Sunday?", ToolContext(principal={"id": "u1"}))
print(result.text)
```

Runnable examples, no API key needed:

| Example                                                | Shows                                                      |
| ------------------------------------------------------ | ---------------------------------------------------------- |
| [examples/minimal.py](examples/minimal.py)             | The smallest complete agent with one tool                  |
| [examples/approval.py](examples/approval.py)           | Roles decide which tools are offered; writes become drafts |
| [examples/read_document.py](examples/read_document.py) | Reading a PDF, Word or Excel file into Markdown            |

## Rules worth keeping

- **Identity is not the model's to decide.** Put the user and the record in `ToolContext`.
- **Assemble the system prompt once per conversation.** Pass `RunResult.system_prompt` back
  as `run(system_prompt=...)` on later turns so the provider's prompt cache keeps working.
- **Prefer `access="propose"`** for anything that changes data, and let a person approve.
- **Test offline** with `ScriptedModel`; automated tests should never call a real model.
- **Text from users, files and tools is data.** Keep it out of the system prompt.

## Reading documents (optional)

```python
from cairnkit.documents import DocumentError, Limits, extract_text

try:
    doc = extract_text(data, "price-list.xlsx", limits=Limits(max_chars=40_000))
except DocumentError as exc:
    exc.code  # too_large, empty, unsupported, old_format, image, encrypted, no_text, unreadable, needs_extra
else:
    doc.text, doc.kind, doc.parts, doc.truncated, doc.warnings
```

- **Output** is Markdown. Word keeps headings, lists and tables; Excel becomes one table per
  visible sheet (dates as `2026-11-07`); PDF text is marked `[Page N]`.
- **The format is judged by content**, not only the file name. Old `.doc`/`.xls`, pictures
  and scanned PDFs get their own error codes so your UI can explain what to do.
- **Limits** on file size, PDF pages, Excel rows and unzipped size. Only text is read;
  macros and formulas never run.
- **Replaceable**: `register_extractor("pdf", fn)` swaps in another reader (MarkItDown,
  Docling, an OCR service) without changing callers.

## Relationship to Hermes Agent

Many mechanisms and algorithms are ported from
[Hermes Agent](https://github.com/NousResearch/hermes-agent) v0.22.2 (MIT, Nous Research):
the prompt layers, the tool loop, memory editing rules, history search, skills, context
compression, background review, curation and delegation. Every ported file names its
Hermes source in its header. Hermes is a personal assistant with files, terminals and
dozens of platforms; cairnkit keeps the algorithms and replaces storage, configuration and
permissions so they fit a multi-user web application. See
[docs/hermes-porting.md](docs/hermes-porting.md) for the map and
[docs/upgrading-hermes.md](docs/upgrading-hermes.md) for following new Hermes releases.
cairnkit is not affiliated with or endorsed by Nous Research.

## Versioning

`MAJOR.MINOR.PATCH`. Before 1.0:

- **Patch** (0.3.0 → 0.3.1): fixes, tests and docs; upgrade freely.
- **Minor** (0.3 → 0.4): new features, Hermes updates, or anything that needs changes in
  your code. [CHANGELOG.md](CHANGELOG.md) says what to change.

## Development

```bash
uv sync --all-extras
uv run pytest -q && uv run ruff check . && uv run ruff format --check .
```

See [CONTRIBUTING.md](CONTRIBUTING.md). Security reports: [SECURITY.md](SECURITY.md).

## License

MIT, see [LICENSE](LICENSE). Ported Hermes Agent code keeps its MIT notice in
[NOTICE.md](NOTICE.md).
