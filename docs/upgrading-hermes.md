# Following Hermes Agent releases

Many of cairnkit's mechanisms are ported from [Hermes Agent](https://github.com/NousResearch/hermes-agent).
When Hermes releases a new version, use these steps to decide what to take. The aim is to
**adopt improvements selectively**, not to mirror Hermes: cairnkit replaces Hermes'
storage, configuration and permission layers (see [hermes-porting.md](hermes-porting.md)).

## 1. Check for a release

Read the latest stable release on [Hermes Releases](https://github.com/NousResearch/hermes-agent/releases)
and note its version. The version currently followed is in
[reference/README.md](../reference/README.md).

## 2. Get both versions of the source

```bash
cd reference/hermes-agent            # get it first as described in reference/README.md
git fetch --depth 50 origin tag v0.22.2 tag <new>
git checkout <new>
```

## 3. List the changes that matter

```bash
python scripts/hermes_changes.py v0.22.2 <new>
```

The script reads the source header (`Adapted from / Ported from hermes-agent ...`) of every
module in `cairnkit/` and lists which of those Hermes files changed, with the matching
cairnkit module. Then read each diff:

```bash
cd reference/hermes-agent && git diff v0.22.2..<new> -- agent/context_compressor.py
```

Also skim the release notes for **new features** worth porting (add a row to
hermes-porting.md if you port one).

## 4. Decide, change by change

Record each decision in the upgrade log at the end of [hermes-porting.md](hermes-porting.md):

| Decision | Examples                                                  | Action                          |
| -------- | --------------------------------------------------------- | ------------------------------- |
| Take     | An algorithm fix, better compression, new injection rules | Port it, with tests             |
| Skip     | Only about the CLI, terminals, file storage or profiles   | Write down why                  |
| Later    | Large or behaviour-changing                               | Write it down and discuss first |

Security changes (the injection rules in `tools/threat_patterns.py`) are taken by default.

## 5. Change the code

- Update the header of each changed file to the new version and commit, for example
  `# Adapted from hermes-agent v0.23.0 (abc1234): ...`.
- Run `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`.
- Automated tests never call real models.

## 6. Release

1. Update `version` in `pyproject.toml`, [CHANGELOG.md](../CHANGELOG.md), the version and
   commit in [reference/README.md](../reference/README.md) and in [NOTICE.md](../NOTICE.md).
2. Commit, tag and push: `git tag -a vX.Y.Z -m "..." && git push origin main --tags`.

Versioning rules: see the [README](../README.md#versioning).
