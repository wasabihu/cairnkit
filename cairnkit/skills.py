# Adapted from hermes-agent v0.22.2 (d923a5e): tools/skills_tool.py, agent/skill_utils.py
# Copyright (c) 2025 Nous Research. MIT License.
"""Skills with progressive disclosure.

A skill is a directory with ``SKILL.md`` (front matter + instructions) and optional
``references/`` and ``templates/``. The system prompt lists only names and one-line
descriptions; the model calls ``skill_view`` to read a skill in full when it needs it.
Skills are scanned for injection at load time and rejected if anything matches.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from cairnkit.security import first_threat_message
from cairnkit.tools import ToolContext, ToolError, ToolRegistry, ToolSpec, tool_result

MAX_DESCRIPTION_CHARS = 60
MAX_SKILL_CHARS = 40_000  # whole skill, body plus files (skill_view returns it in one piece)
SUPPORT_DIRS = ("references", "templates")
SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,47}$")


class SkillError(ValueError):
    pass


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    body: str
    path: Path
    files: dict[str, str] = field(default_factory=dict)  # relative path -> text


def parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    """Minimal ``key: value`` front matter between ``---`` lines (no YAML dependency)."""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end == -1:
        raise SkillError("front matter is not closed with ---")
    meta: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition(":")
        if not sep:
            raise SkillError(f"front matter line is not key: value: {line!r}")
        meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta, text[end + 4 :].lstrip("\n")


def make_skill(
    name: str, description: str, body: str, files: dict[str, str] | None = None
) -> Skill:
    """Build a skill from text (for example one an administrator uploaded), applying the
    same rules as skills on disk: slug name, short description, size limit, threat scan."""
    name, description, body = name.strip(), " ".join(description.split()), body.strip()
    files = dict(files or {})
    if not SKILL_NAME_PATTERN.match(name):
        raise SkillError("name must be 2-48 lowercase letters, digits or hyphens")
    if not description or len(description) > MAX_DESCRIPTION_CHARS:
        raise SkillError(f"description must be 1-{MAX_DESCRIPTION_CHARS} characters")
    if not body:
        raise SkillError("the skill has no content")
    if len(body) + sum(len(t) for t in files.values()) > MAX_SKILL_CHARS:
        raise SkillError(f"a skill may hold at most {MAX_SKILL_CHARS} characters")
    for label in files:
        if not label.startswith(tuple(f"{d}/" for d in SUPPORT_DIRS)) or ".." in label:
            raise SkillError(f"file {label!r} must sit under references/ or templates/")
    for label, text in [("SKILL.md", body), *files.items()]:
        if threat := first_threat_message(text, scope="strict"):
            raise SkillError(f"{name}/{label}: {threat}")
    return Skill(name=name, description=description, body=body, path=Path(name), files=files)


def load_skill(directory: Path) -> Skill:
    skill_md = directory / "SKILL.md"
    meta, body = parse_front_matter(skill_md.read_text(encoding="utf-8"))
    name = meta.get("name") or directory.name
    description = meta.get("description", "")
    if name != directory.name:
        raise SkillError(f"{skill_md}: name {name!r} must match its directory")
    if not description or len(description) > MAX_DESCRIPTION_CHARS:
        raise SkillError(f"{skill_md}: description must be 1-{MAX_DESCRIPTION_CHARS} characters")
    files: dict[str, str] = {}
    for sub in SUPPORT_DIRS:
        for path in sorted((directory / sub).rglob("*")) if (directory / sub).is_dir() else []:
            if path.is_file():
                files[path.relative_to(directory).as_posix()] = path.read_text(encoding="utf-8")
    for label, text in [("SKILL.md", body), *files.items()]:
        if threat := first_threat_message(text, scope="strict"):
            raise SkillError(f"{name}/{label}: {threat}")
    return Skill(name=name, description=description, body=body, path=directory, files=files)


class SkillLibrary:
    def __init__(self, skills: list[Skill] | None = None):
        self._skills = {s.name: s for s in skills or []}

    @classmethod
    def load(cls, root: str | Path) -> SkillLibrary:
        root = Path(root)
        if not root.is_dir():
            return cls()
        return cls([load_skill(d) for d in sorted(root.iterdir()) if (d / "SKILL.md").is_file()])

    def names(self) -> list[str]:
        return sorted(self._skills)

    def with_skills(self, skills: list[Skill]) -> SkillLibrary:
        """A new library with ``skills`` added; a name already present is kept as is."""
        merged = dict(self._skills)
        for skill in skills:
            merged.setdefault(skill.name, skill)
        return SkillLibrary(list(merged.values()))

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def index_prompt(self, allowed: list[str]) -> str:
        """The only skill text that goes into the system prompt."""
        skills = [self._skills[n] for n in allowed if n in self._skills]
        if not skills:
            return ""
        lines = [f"- {s.name}: {s.description}" for s in skills]
        return (
            "Skills available (call skill_view with the name to read one before relying on it):\n"
            + "\n".join(lines)
        )

    def register_tools(self, registry: ToolRegistry, allowed: list[str]) -> None:
        allowed_set = set(allowed)

        def skills_list(_args: dict, _ctx: ToolContext) -> str:
            return tool_result(
                skills=[
                    {"name": s.name, "description": s.description}
                    for s in (self._skills[n] for n in sorted(allowed_set) if n in self._skills)
                ]
            )

        def skill_view(args: dict, _ctx: ToolContext) -> str:
            name = str(args.get("name", ""))
            skill = self._skills.get(name) if name in allowed_set else None
            if skill is None:
                raise ToolError(f"no skill named {name!r}; call skills_list to see what exists")
            file = args.get("file")
            if file:
                if file not in skill.files:
                    raise ToolError(f"{name} has no file {file!r}; files: {sorted(skill.files)}")
                return tool_result(name=name, file=file, content=skill.files[file])
            return tool_result(name=name, content=skill.body, files=sorted(skill.files))

        registry.register(
            ToolSpec(
                name="skills_list",
                description="List the skills you can read, with one-line descriptions.",
                parameters={"type": "object", "properties": {}},
                handler=skills_list,
            )
        )
        registry.register(
            ToolSpec(
                name="skill_view",
                description="Read a skill in full, or one of its reference files.",
                parameters={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Skill name from the list."},
                        "file": {
                            "type": "string",
                            "description": "Optional file, e.g. references/x.md",
                        },
                    },
                    "required": ["name"],
                },
                handler=skill_view,
            )
        )
