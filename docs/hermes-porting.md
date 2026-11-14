# Hermes Agent porting map

> Reference: Hermes Agent **v0.23.0** (commit `2bd378e`, MIT; first port from v0.22.2, `d923a5e`). The source can be checked out
> under `reference/hermes-agent/` for comparison (see [reference/README.md](../reference/README.md)).
> Goal: **keep Hermes' good design**, and adapt it to web applications where many people
> share data, memory lives in a database and a person approves changes.
> "Host" below means the application that uses cairnkit.

## Status

Every ported module names its Hermes source (version, commit, file) in its header.

| #   | Mechanism                                                 | Module                             |
| --- | --------------------------------------------------------- | ---------------------------------- |
| 1   | Three-layer system prompt and prompt caching              | `prompt.py`                        |
| 2   | Agent loop, tool rounds, argument checks, loop protection | `loop.py`, `guardrails.py`         |
| 3   | Tool registry with access levels and roles                | `tools.py`                         |
| 4   | Memory: add / patch / remove, limits, scanning            | `memory_ops.py`, `memory.py`       |
| 5   | History search                                            | `search.py`                        |
| 6   | Skills shown on demand, scanned when loaded               | `skills.py`                        |
| 7   | Automatic titles                                          | `titles.py`                        |
| 8   | Error classification and fallback models                  | `llm/errors.py`, `llm/fallback.py` |
| 9   | Usage and cost                                            | `types.py` (`Usage`), `pricing.py` |
| 10  | Context compression                                       | `compression.py`                   |
| 11  | Background review                                         | `review.py`                        |
| 12  | Skill curation                                            | `curator.py`                       |
| 13  | Delegation to sub-agents                                  | `delegate.py`                      |

## Why port instead of running Hermes

Hermes is built as one person's assistant. Several things do not fit a shared web app:

| Hermes                                                                | A multi-user web application needs                                                |
| --------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| Memory per profile in `MEMORY.md` / `USER.md`, shared by every user   | Memory per record (customer, case…) in a database, with review status and sources |
| The model decides what to remember                                    | People record, the AI drafts, a person approves                                   |
| 40+ tools for terminals, files and browsers                           | A few business tools, allowed by role                                             |
| Configuration and state under `get_hermes_home()` and profile folders | Everything in the application's database and settings                             |
| ~880k lines covering 20+ platforms                                    | One web backend                                                                   |

So cairnkit **keeps the mechanisms and algorithms and replaces three layers: storage,
configuration and permissions.**

## Porting rules

1. **Read first.** Before porting a mechanism, read the `AGENTS.md` of the matching Hermes
   folder and the source files listed below, and understand the constraints they protect.
2. **Name the source.** Ported files start with:
   ```python
   # Ported from hermes-agent v0.23.0 (2bd378e): tools/memory_tool_store.py
   # Copyright (c) 2025 Nous Research. MIT License.
   ```
3. **Keep the algorithm, replace the shell.** Matching, truncation, limits, scanning rules
   and error classes stay as they are; file I/O, `get_hermes_home()`, `config.yaml` and
   profile scopes become host callbacks and settings.
4. **Port the tests too.** Hermes' behaviour tests for a ported mechanism come along as
   regression tests.
5. **Only branches that are used.** Code for providers and platforms cairnkit does not
   support is left out.
6. **Follow upstream with evidence.** On a new Hermes release, compare the files listed
   here and record the decision (see [upgrading-hermes.md](upgrading-hermes.md)).

## Mechanisms

### 1. System prompt layers and prompt caching

- **Hermes files:** `agent/system_prompt.py`, `agent/prompt_builder.py`, `agent/AGENTS.md` (message-flow invariants)
- **Kept:** stable / context / volatile layers; the prompt is assembled once per conversation and never changed mid-way; anything added later arrives in user messages or tool results; strict role alternation.
- **Changed:** platform hints, coding-environment hints and reading `AGENTS.md` from the working directory are gone; the context layer carries what the host supplies (for example the user's role and house rules).

### 2. Agent loop and tool rounds

- **Hermes files:** `agent/conversation_loop.py`, `agent/turn_tool_round.py`, `agent/turn_tool_validation.py`, `agent/tool_executor.py`, `agent/tool_guardrails.py`
- **Kept:** an iteration limit plus one closing call; **tool calls are reported before they run** so the host can save them first; invalid tool names or arguments come back as tool results, never as injected user messages; loop protection for repeated identical calls and consecutive failures.
- **Changed:** the loop is `async` so it can stream through web frameworks; interrupts, `/steer`, mixture-of-agents and other unused branches are gone.

### 3. Tool registry

- **Hermes files:** `tools/registry.py`, `toolsets.py`, `model_tools.py`, `tools/AGENTS.md`
- **Kept:** each tool declares a schema, a handler and an availability check; handlers return JSON strings; tool descriptions never mention tools from other toolsets; the core set stays small.
- **Changed:** two new declarations, `access` (read / propose / write) and `roles`; identity is injected through `ToolContext` and never accepted from the model; availability depends on configuration only.

### 4. Memory

- **Hermes files:** `tools/memory_tool.py`, `tools/memory_tool_store.py`, `agent/memory_manager.py`, `agent/memory_provider.py`, `tools/threat_patterns.py`
- **Kept:** capacity limits counted in characters (model independent); a **frozen snapshot** per conversation, so writes do not change the prompt mid-way; one tool with `add` / `patch` / `remove` and batches; `patch` finds the entry by a unique quoted fragment and explains when it matches nothing or several entries; injection scanning before writing; over-limit writes are refused with a hint, never silently truncated.
- **Changed:** storage is a `MemoryStore` the host implements (for example a database table per customer); the store decides whether a plan is applied or queued for approval; file locks are replaced by the host's transactions.

### 5. History search

- **Hermes files:** `tools/session_search_tool.py`, `hermes_state_fts.py`
- **Kept:** **no model calls while searching**; one tool, modes chosen by arguments (search, context around a hit, read in full, browse); duplicate hits folded, only the best one expanded.
- **Changed:** the host implements `SearchBackend` over whatever it stores (notes, records, approved memory), and limits results to what the current person may see.

### 6. Skills

- **Hermes files:** `tools/skills_tool.py`, `agent/skill_utils.py`, `agent/skill_preprocessing.py`, `tools/skills_guard.py`, `skills/AGENTS.md`
- **Kept:** the `SKILL.md` format (front matter, body, `references/` and `templates/`), compatible with agentskills.io; **shown on demand** (the prompt lists names, `skills_list` returns descriptions, `skill_view` the full text); descriptions up to 60 characters; security scanning for skills from outside.
- **Changed:** skills come from the repository or from text the host supplies (`make_skill`, for uploads managed in an admin page); no online hub, no inline shell commands (`!cmd`), no platform filters; each agent lists the skills it may use.

### 7. Automatic titles

- **Hermes file:** `agent/title_generator.py`
- **Kept:** an **instant title** from the first message (no model call, cannot fail), then a better one from a small model in the background; title sources ranked `derived < llm < user`, so a model never overwrites a title the user typed.

### 8. Error classification and fallback

- **Hermes files:** `agent/error_classifier.py`, `agent/fallback_cooldown.py`, `agent/turn_api_error.py`
- **Kept:** errors classified by priority (auth, billing, rate limit, upstream rate limit, overload, server error, timeout, context overflow, unknown model, provider policy, content filter, bad request…), each with a hint: retry, switch to a fallback model, compress, or stop; cooldowns after rate limits.
- **Changed:** only the classes OpenAI-compatible APIs and OpenRouter produce; no credential pools. Timeouts say whether the connect or the read phase failed.
- **Changed (v0.6.1 stream fix):** `llm/openai_compat.py` validates complete SSE events,
  choice 0's terminal `finish_reason`, and `[DONE]`. Malformed or truncated streams raise
  instead of returning a partial success; there is no synthetic answer or continuation.
  Provider finish reasons such as `length` remain available to the host. OpenRouter's
  content-free usage frame can repeat the terminal reason. This is client-side validation,
  independent of Hermes' streamed tool-call accumulator, which stays unchanged.

### 9. Usage and cost

- **Hermes files:** `agent/turn_usage.py`, `agent/usage_pricing.py`
- **Kept:** token usage (including cache hits) summed per call and priced from a table.
- **Changed:** the provider's reported cost wins when present; the host stores and reports usage.

### 10. Context compression

- **Hermes files:** `agent/context_compressor.py`, `agent/usage_anchor.py`, `website/docs/developer-guide/context-compression-and-caching.md`
- **Kept, four phases:** ① prune old tool results without a model call (repeats folded, one line left per pruned result, per-tool hooks; the round the model has not answered is never touched); ② choose boundaries (system prompt and a token-budgeted tail kept; tool calls and results never split; the latest real user message always kept verbatim); ③ a structured summary with fixed sections, **updated** on later compactions instead of re-summarised, sampled evenly when the input is too large, dated, with optional focus topic, uncertain claims kept as labelled `UNVERIFIED:` lines; ④ reassemble and repair call/result pairs.
- **Kept, against losing facts:** an anchor index of dates, times, amounts, IDs and links copied verbatim; the user's own words in the compacted range quoted newest first; an optional "how to recover details" hint from the host.
- **Kept, reliability:** real token counts from the provider as anchors, estimates only for newer messages; the lean tail never exceeds half the trigger; a failing summary model gets one retry on `fallback_model` (usually the main model); summary failures classified (timeouts cool down 60 → 300 → 900 s, auth or billing keeps the original, others fall back to a deterministic summary); refused, truncated or incomplete summaries count as failures; two compactions in a row saving under 10% pause auto-compaction; on a context-overflow error, compress and retry once.
- **Kept, safety:** secrets, passwords and credentials in URLs masked before and after summarising; the prompt says the conversation is data, not instructions.
- **Changed:** state is per conversation (`CompressionState`, saved by the host), so one compressor serves all conversations; CJK text estimated at about one token per character; small regions get a proportionally smaller summary budget; a summary that would not save anything is skipped without a model call.
- **Not ported:** provider-native compaction, background summary preparation (`prepare_ahead`), skill-pruned markers, Anthropic cache markers, gateway session cleanup, the session archive (the host keeps original transcripts), learned per-provider image pricing (images count as 1,500 tokens).

### 11. Background review

- **Hermes file:** `agent/background_review.py`
- **Kept:** after a turn, a snapshot goes to a forked agent with a restricted tool list that asks "is there anything to remember or update?"; it reuses the main system prompt, so it hits the same prompt cache; **the main conversation is not affected**.
- **Changed:** in Hermes the fork writes memory directly; here its edits go through the host's `MemoryStore`, which can turn them into drafts for a person to approve.

### 12. Skill curation

- **Hermes file:** `agent/curator.py`
- **Kept:** runs when idle, not on a timer (`interval_hours` since the last run and `min_idle_hours` of inactivity); skills unused for `stale_after_days` become stale, after `archive_after_days` archived, and active again when used; new, never-used skills are left alone; **archive, never delete**; pinned skills untouched; optional model-assisted consolidation (merge, rewrite, archive suggestions), off by default.
- **Changed:** the result is a **plan** the host executes, so a host can apply labels directly and turn archives and rewrites into proposals a person approves.
- **Not ported:** cron reference checks, report files, the `skill_manage` tool.

### 13. Delegation

- **Hermes files:** `tools/delegate_tool.py` and its helpers
- **Kept:** sub-agents get a fresh conversation, a focused system prompt and a subset of the parent's tools; **the parent sees only the request and the final answer**; a limit on sub-agents per turn.
- **Changed:** one level only (sub-agents cannot delegate further).

## Not ported

| Part                                                | Why                                         |
| --------------------------------------------------- | ------------------------------------------- |
| CLI, TUI, desktop app, 20+ chat platforms           | cairnkit is a library for web applications  |
| Terminal, file, browser and code-execution tools    | Not safe to expose in a shared web app      |
| Cron jobs, kanban                                   | Out of scope                                |
| Credential pools, OAuth, provider-specific adapters | OpenAI-compatible APIs and OpenRouter only  |
| Profiles and `HERMES_HOME`                          | The host's database and settings instead    |
| Skills Hub online install                           | Skills come from the repository or the host |

## Upgrade log

One line per Hermes release checked, including releases not followed (say why). Process:
[upgrading-hermes.md](upgrading-hermes.md).

| Date       | Hermes              | Decision                              | cairnkit |
| ---------- | ------------------- | ------------------------------------- | -------- |
| 2026-10-20 | v0.22.2 (`d923a5e`) | Initial port, all 13 mechanisms above | v0.1.0   |
| 2026-11-09 | v0.23.0 (`2bd378e`) | Took 13 changes, skipped 17, 2 later (below) | v0.5.0   |

### v0.23.0 (`2bd378e`), checked 2026-11-09

`python scripts/hermes_changes.py v0.22.2 v0.23.0`: 17 of the 22 ported Hermes files changed.
`tools/threat_patterns.py` did not change, so there are no new injection rules to take.
Decisions follow [upgrading-hermes.md](upgrading-hermes.md#4-decide-change-by-change).

| Area        | Hermes change                                                                                                   | Decision | Reason                                                                                                                                                                                                                                                                                                                         |
| ----------- | --------------------------------------------------------------------------------------------------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Compression | Uncertain claims kept as `UNVERIFIED: <claim> — <basis>` under `## Unverified / Working Hypotheses`             | Take     | Summaries drop "probably" first, so a guess became a fact the next turn acted on. Added to the default sections and the summary prompt; custom `summary_sections` still get the label rule.                                                                                                                                    |
| Compression | Lean tail budget held to half the trigger (`lean_tail_budget`)                                                  | Take     | A small `threshold_tokens` on a large window kept a tail larger than the trigger, so compaction never got below it.                                                                                                                                                                                                            |
| Compression | One retry on the main model when a separate summary model fails, for any error class                            | Take     | Hermes already did this in v0.22.2 and v0.23.0 extends it to fallbacks inside the aux client; cairnkit had no equivalent. New optional `fallback_model`, with `CompressionResult.fallback_model_used` / `summary_model_error` so the host can warn that its summary model is broken.                                            |
| Compression | `prepare_ahead`: write the next summary in the background near the trigger and splice it in at compaction      | Later    | Needs an agent that lives across turns with in-memory pass state, cancellation and a "same messages" check over message ids. cairnkit keeps compression state per conversation in the host and holds no agent between requests, so this needs a host-side design (where the pending summary lives, who cancels it). Discuss first. |
| Compression | Skill-pruned markers for every `skill_view` size, `## Skill Safety Rule`, `/skill` turns quoted as typed        | Later    | cairnkit never ported the `[SKILL_PRUNED: ...]` mechanism (v0.22.2 used it only for bodies over 5,000 chars). Porting it adds summary sections and a tail rule; worth doing together with skills. Until then hosts can pass a `tool_summarizers["skill_view"]` that says "reload with skill_view".                              |
| Compression | Structural no-op backoff lifted when the transcript grows; progress floor past standalone handoff rows         | Skip     | cairnkit has no structural no-op backoff (only paid, ineffective attempts cool down), and its tail cut already falls back to the recent-row floor, so it cannot plan an empty window.                                                                                                                                          |
| Compression | Image eviction latching, Gemini prompt-block class, memory trim without GC, refactor into mixin files          | Skip     | Send-path image retirement, the native Gemini adapter and process memory trimming are not in cairnkit; the mixin split changes no behaviour.                                                                                                                                                                                  |
| Model calls | Body byte-cap 400s (Novita, Z.AI, `content-length ... bytes`) classified as payload too large                   | Take     | Gateways reporting an oversized body as a 400 fell to `format_error`, so the same oversized request was never compressed. Same subject/overflow/token rules as Hermes.                                                                                                                                                          |
| Model calls | Timeout errors say which phase failed (`agent/timeout_error_summary.py`)                                         | Take     | A bare "timed out" did not say whether a connection was ever made. `classify_error` now names connect or read, with `context["timeout_phase"]`, and `AllModelsFailed` repeats it. The hint points at `timeout=` on the model client instead of Hermes' `config.yaml` key.                                                     |
| Model calls | Streamed tool calls: a fresh id at a reused index opens a new call only when named and the previous call closed | Take     | cairnkit merged everything at one index, so Ollama's parallel calls (all at index 0) became one broken call. Ported Hermes' accumulator with the v0.23.0 guard, so LM Studio / Kimi (new id per fragment) and MiniMax (name resent per fragment) are not split. New header on `llm/openai_compat.py`.                          |
| Model calls | Stream lifetime cap treated as a timeout; abandoned-worker and invisible-delta handling in the streaming monitor | Skip     | cairnkit's stream is a single `httpx` read under the client timeout, with no watchdog thread, stale-stream kill or lifetime cap.                                                                                                                                                                                                 |
| Model calls | Nous usage-window 402, `data_policy_denied`, Gemini prompt block, Anthropic `redacted_thinking`, reasoning level sets | Skip     | Provider-specific to Nous Portal, connectors, the native Gemini adapter, Anthropic thinking replay and reasoning-effort controls; cairnkit sends none of these.                                                                                                                                                                 |
| Model calls | Bedrock, Codex, Copilot, Nous Portal and MoA changes in `chat_completion_helpers.py`                             | Skip     | Provider adapters cairnkit does not have (OpenAI-compatible APIs and OpenRouter only).                                                                                                                                                                                                                                         |
| Model calls | No prompt-cache markers on one-shot calls (summaries, titles): `is_one_shot_request` in `agent/prompt_caching.py` | Skip     | The saving comes from not writing Anthropic `cache_control` markers nothing reads back. cairnkit never writes cache markers or `prompt_cache_key` (listed as not ported), so its summary and title calls already pay no cache-write premium.                                                                                    |
| Memory      | Schema advertises only `operations[]` (a single change is a one-item list); the old shape is still accepted      | Take     | Two shapes in the schema made models mix them. The handler keeps the single-change shape and the `new_text` alias for drifting models and replayed transcripts, and a call with neither now explains the expected shape.                                                                                                       |
| Memory      | Remove-only batches and a lone duplicate add are not refused when a lowered limit is already exceeded             | Take     | Otherwise a store over a newly lowered limit could not be pruned back under it.                                                                                                                                                                                                                                                |
| Memory      | A lone add over the limit gets its own message with the chars to free and the current entries                    | Take     | Same wording as Hermes' `_add_overflow`; the model has not consolidated yet, so it needs the entries to choose from.                                                                                                                                                                                                           |
| Memory      | A one-item remove may empty the store; drift backups (`.bak`) created exclusively; oversized-entry drift checks | Skip     | cairnkit has no "refuse to empty" guard to relax (the host's approval covers deletions), and no memory files to drift or back up.                                                                                                                                                                                              |
| Tools       | A JSON tool result is judged failed by its top-level shape: non-empty `error`, `status` failed/error, or every `results` item erroring | Take     | cairnkit only looked at `success: false`, so a host handler returning `{"error": ...}` or a fully failed batch counted as a success for loop protection and `ToolRecord.failed`. `"error": null` and words inside content never count. Plain-text results stay "not failed" (cairnkit handlers return JSON).  |
| Tools       | A throttled failure (`retry_after`, 429, rate-limit wording) stays out of the identical-arguments streak          | Take     | Retrying after a cooldown is correct, not a replay; it still counts per tool, so `same_tool_failure_halt` bounds a dead endpoint.                                                                                                                                                                                              |
| Tools       | Registry: per-session tool overlays, `move_to_scope`, safe-worker discovery, check_fn verdict windows and epochs, `execution_timeout` | Skip     | Profile/session scoping, plugin discovery and cached availability probes have no counterpart (availability is configuration only, tools are registered by the host). `execution_timeout` only widens MCP tools' timeout; cairnkit has no tool timeout or MCP.                                                           |
| Search      | Browsing (no arguments) defaults to 10 results; a search still defaults to 3                                     | Take     | A browse list of 3 was too short to pick a document from.                                                                                                                                                                                                                                                                      |
| Search      | Cross-profile DB moved into `session_search`, read-only handle for managed workers, shorter description         | Skip     | Profiles, worker processes and FTS5 handles belong to Hermes' storage; cairnkit's `SearchBackend` is the host's.                                                                                                                                                                                                               |
| Review      | Memory review saves only facts grounded in the conversation, never inferred traits or one-off requests           | Take     | Matters even more with approval: every guess becomes a draft a person must reject. Added to `REVIEW_INSTRUCTION`.                                                                                                                                                                                                              |
| Review      | Reviews off for finite turns and the safe worker; locked-skill note; usage attributed per task; secret prompt skipped | Skip     | The host decides when a review runs and bills `RunResult.usage` itself; there are no locked skills, worker modes or secret prompts in cairnkit.                                                                                                                                                                              |
| Delegation  | Pluggable delegation backends: per-task routes (model, reasoning effort, profile), per-task refusal inside a batch, service tiers | Skip     | In cairnkit the host already chooses each child: `make_delegate_tool` takes named `Agent`s, each with its own model and tools, and a call runs one task. Per-task routing and partial refusal only matter for Hermes' parallel batches over one configurable child. Revisit if cairnkit ever runs several tasks per call. |
| Delegation  | Worker-process child stores, one-shot schema without live `action` controls, gateway inline mode                  | Skip     | No worker processes, background children or live steering in cairnkit (children run inline, one level).                                                                                                                                                                                                                        |
| Skills      | Index descriptions clipped at a word boundary (`clip_skill_description`)                                          | Skip     | cairnkit refuses descriptions over 60 characters when a skill is loaded or made, so there is nothing to clip.                                                                                                                                                                                                                  |
| Skills      | Directory-tree catalog signature, config cache bounds and locking, plugin `plugin:` prefixes, secret capture per turn, shorter `skill_view` description | Skip     | Skills come from the repository or the host; there is no catalog cache, `config.yaml`, plugin namespace or secret prompt. cairnkit's `skill_view` description is already short.                                                                                                                                            |
| Curator     | Locked skills skipped by automatic transitions; prompt says the index shows 60 chars                             | Skip     | Locks come from Hermes' skill installs; pinned skills are cairnkit's equivalent and are already untouched. cairnkit's prompt already says 60 characters.                                                                                                                                                                      |
| Prompt      | Plugin discovery for platform hints, memory module rename, no `/steer` note in one-shot sessions                 | Skip     | Platform hints and `/steer` were never ported; the rename has no behaviour.                                                                                                                                                                                                                                                    |
| Agent loop  | Prompt-refresh epochs, held stream transforms, `pre_llm_call` veto, Codex app-server turns, Nous/Copilot credential and billing copy, closing failed turns that end on a tool row, `prepare_ahead` hook in the tool round | Skip     | Gateway, plugin and provider features. The host stores transcripts, so closing a failed turn is its job; `prepare_ahead` is recorded as later above.                                                                                                                                                                   |
| Security    | `tools/threat_patterns.py`                                                                                       | —        | Unchanged in v0.23.0.                                                                                                                                                                                                                                                                                                          |

Modules whose Hermes sources changed but whose port did not (`delegate.py`, `skills.py`, `curator.py`,
`prompt.py`, `loop.py`) keep their v0.22.2 header: they were checked against v0.23.0 and nothing was taken.

### 2026-11-14: bounded consolidation, v0.23.1

`memory_consolidation.py` adapts `tools/memory_tool_store.py` at
`3b421578588243f920886e6fe79a6faa87ea026e`: overflow feedback contains existing
entries and a capacity error, proposals apply atomically, and an initial failed
write gets at most three further consolidation proposals. The model may merge,
shorten or remove entries. Differences: JSON proposals instead of an agent tool
loop; no file storage; host callback validates grounding and permissions; caller
must compare the original snapshot before committing. Provider errors do not
retry. This is a selective port, not a claim that every module follows v0.23.1.

Local consolidation extension: separate soft target and hard limit; no full inventory
repeated in retry feedback; bounded best-valid fallback and an empty-result guard.
Optional original-entry indices make batch removals compact. No fixed target ratio
is attributed to Hermes. Fact evidence and schema migrations remain host-owned.


### Selection protocol in v0.7.0

The host-rendered ID/group/range protocol in `memory_selection.py` is a cairnkit extension,
not copied Hermes behavior. It reduces model text rewriting and unbounded index enumeration.
Selection IDs include pending corrections but are not persisted until host approval and atomic
commit. Original snapshot validation, source grounding and business permissions stay with the
host. Truncated output is rejected; failed proposal text is excluded from retry context.
If an all-singleton proposal fails or deletes too much, cairnkit can calculate a removal option in host
entry order, skipping pending changes, for explicit model selection and host validation.
The local helper also rejects explicit removals below 95% of the soft target, rounded
to whole characters. This is a cairnkit protection, not a claim about Hermes behavior.
Host-rendered lossless groups are exempt; hosts detect semantic loss in free-text patches.
Recovery skips oversized indivisible rows rather than offering a nearly empty result.

The optional lossless prepass and snapshot packing improvements are also local cairnkit
extensions, not claims about Hermes behavior. Hosts provide reversible normalization;
the generic helper supplies validation, bounded plans and the no-model fast path when
the hard limit is met. Snapshot packing can skip oversized facts and limit the number
actually selected. Domain fact parsing, relevance, provenance and storage remain outside
the package. Released in v0.7.0.

## Local extension: ordinal memory layers

`memory_layers.py` is an original host-configurable extension, not a verbatim
Hermes port. It groups by original fact order and host topic, not elapsed days,
while preserving the host's protected facts. Hosts own storage, semantics and
capacity/target defaults. Selection protection supplements (never replaces) host
semantic validation. No Hermes answer-control prompts are copied.

### Local infeasibility and truncation fix

Unlike an open-ended tool retry loop, hosts may prove the pending snapshot cannot
fit and skip model calls. Selection output has structural limits and truncation
uses a short, validated option vote or stops. These are original extensions;
no Hermes hidden prompts or answer recovery behavior are copied. Correction-first
persistence, ownership and audit remain host responsibilities.

### Local working-set/archive projection

`memory_archive.py` is an original, optional pure projection, not copied from Hermes.
It leaves canonical facts in host storage and partitions keys into recent/protected
working details and older host-rendered summaries. Only the working representation
has the supplied character cap; this is explicitly different from capping all stored
memory. Original source order survives rebuilding. Hosts must validate summaries,
scope retrieval and invalidate views on lifecycle changes. No eviction, model calls,
extra answer instructions or filesystem persistence are introduced by this module.
