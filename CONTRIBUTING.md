# Contributing

Thanks for helping. cairnkit is small on purpose, so please open an issue to discuss a new
feature before writing it. Bug fixes, tests and documentation improvements are welcome
directly as pull requests.

## Set up

```bash
git clone https://github.com/wasabihu/cairnkit
cd cairnkit
uv sync --all-extras
uv run pytest -q && uv run ruff check . && uv run ruff format --check .
```

## What a good change looks like

- It follows [AGENTS.md](AGENTS.md): the core stays dependency-light, identity comes from
  the host, and tests run offline with `ScriptedModel`.
- It has tests for the behaviour it adds or fixes.
- Public API changes are described in [CHANGELOG.md](CHANGELOG.md) under an "Unreleased"
  heading.
- Code ported from Hermes Agent names its source in the file header.

## Reporting bugs

Include the cairnkit version, Python version, a minimal script that shows the problem
(with `ScriptedModel` if possible) and what you expected. For security problems, see
[SECURITY.md](SECURITY.md) instead of opening a public issue.

By contributing you agree that your contribution is licensed under the MIT License.
