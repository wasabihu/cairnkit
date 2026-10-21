"""List which Hermes source files that cairnkit ports from changed between two releases.

Usage (from the repository root, with reference/hermes-agent checked out):

    python scripts/hermes_changes.py v0.22.2 v0.23.0

It reads the "Adapted from / Ported from hermes-agent ..." header of every module in
cairnkit/, collects the Hermes paths named there, and runs ``git diff --stat`` for them in
reference/hermes-agent. Both tags must be fetched there first (see docs/upgrading-hermes.md).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HERMES = ROOT / "reference" / "hermes-agent"
PATH = re.compile(r"[\w./-]+\.(?:py|md|ts|json|toml|yaml)")


def header(path: Path) -> str:
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("#"):
            break
        lines.append(line.lstrip("# "))
    return " ".join(lines)


def ported_sources() -> dict[str, list[str]]:
    """Hermes path -> cairnkit modules that port it."""
    found: dict[str, list[str]] = {}
    for module in sorted((ROOT / "cairnkit").rglob("*.py")):
        text = header(module)
        if "hermes-agent" not in text:
            continue
        body = text.split("):", 1)[-1].split("Copyright", 1)[0]
        for hermes_path in PATH.findall(body):
            found.setdefault(hermes_path, []).append(str(module.relative_to(ROOT)))
    return found


def main(old: str, new: str) -> int:
    if not (HERMES / ".git").exists():
        print("reference/hermes-agent is missing; see reference/README.md", file=sys.stderr)
        return 1
    sources = ported_sources()
    changed = 0
    for hermes_path, modules in sorted(sources.items()):
        stat = subprocess.run(
            ["git", "diff", "--stat", f"{old}..{new}", "--", hermes_path],
            cwd=HERMES,
            capture_output=True,
            text=True,
            check=False,
        )
        if stat.returncode != 0:
            print(f"! {hermes_path}: {stat.stderr.strip()}")
            continue
        summary = stat.stdout.strip().splitlines()
        if summary:
            changed += 1
            print(f"* {hermes_path}  ({summary[-1].strip()})  -> {', '.join(modules)}")
    print(f"\n{changed} of {len(sources)} ported Hermes files changed between {old} and {new}.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2]))
