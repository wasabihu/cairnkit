# Guidelines for contributors and AI coding assistants

Read this before changing the repository.

- **Stay independent.** Only general runtime capabilities belong here: no business code,
  databases or web frameworks. The core depends only on the standard library and `httpx`.
  Features that need more go in optional modules (for example `documents`, installed with
  `cairnkit[documents]`); core modules must not import them. Storage, permissions, price
  tables and wording come from the host through parameters, callbacks or configuration.
- **Identity and permissions come from the host** through `ToolContext`; the model never
  decides who is acting. Prefer `access="propose"` for writes.
- **Keep Hermes' design where it fits.** Ported files name their Hermes version, commit and
  source file in the header, and [NOTICE.md](NOTICE.md) keeps the MIT notice. Record
  differences and their reasons in [docs/hermes-porting.md](docs/hermes-porting.md).
  Follow [docs/upgrading-hermes.md](docs/upgrading-hermes.md) for new Hermes releases.
- A conversation's system prompt does not change, except through context compression.
- **Tests never use the network.** Use `ScriptedModel`. Real-model checks need a stated
  purpose and the maintainer's agreement.
- Never commit keys, runtime data, logs or virtual environments.
- Adding or upgrading dependencies needs the maintainer's agreement.
- **Public API changes need a release**: bump the version as described in the
  [README](README.md#versioning), update [CHANGELOG.md](CHANGELOG.md), tag the commit.
- Before committing: `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
- Keep other people's uncommitted work; stage files one by one.
