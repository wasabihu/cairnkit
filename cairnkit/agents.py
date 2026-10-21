"""Agent definitions loaded from a directory.

    agents/
      note_structurer/
        agent.toml    # name, description, tools, skills, limits
        SOUL.md       # persona and rules (stable prompt tier)

Loading a directory is all a project needs to declare its agents; code only
supplies the tools and the model.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from cairnkit.guardrails import GuardrailConfig
from cairnkit.security import first_threat_message


class AgentConfigError(ValueError):
    pass


@dataclass(frozen=True)
class AgentSpec:
    name: str
    description: str
    persona: str
    model: str = "default"  # key the host maps to a ChatModel
    tools: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    max_iterations: int = 6
    temperature: float | None = None
    max_tokens: int | None = None
    guardrails: GuardrailConfig = field(default_factory=GuardrailConfig)


_ALLOWED_KEYS = {
    "name",
    "description",
    "model",
    "tools",
    "skills",
    "max_iterations",
    "temperature",
    "max_tokens",
    "guardrails",
}


MAX_PERSONA_CHARS = 12_000


def validate_persona(persona: str) -> str:
    """Rules for a persona edited outside the repository (for example in an admin page)."""
    persona = persona.strip()
    if not persona:
        raise AgentConfigError("the persona is empty")
    if len(persona) > MAX_PERSONA_CHARS:
        raise AgentConfigError(f"the persona may hold at most {MAX_PERSONA_CHARS} characters")
    if threat := first_threat_message(persona, scope="all"):
        raise AgentConfigError(threat)
    return persona


def load_agent(directory: str | Path) -> AgentSpec:
    directory = Path(directory)
    config_path = directory / "agent.toml"
    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise AgentConfigError(f"{config_path}: {exc}") from exc
    unknown = set(data) - _ALLOWED_KEYS
    if unknown:
        raise AgentConfigError(f"{config_path}: unknown keys {sorted(unknown)}")
    name = data.get("name", directory.name)
    if name != directory.name:
        raise AgentConfigError(f"{config_path}: name {name!r} must match its directory")
    soul = directory / "SOUL.md"
    persona = soul.read_text(encoding="utf-8").strip() if soul.is_file() else ""
    if not persona:
        raise AgentConfigError(f"{directory}: SOUL.md is missing or empty")
    if threat := first_threat_message(persona, scope="all"):
        raise AgentConfigError(f"{soul}: {threat}")
    max_iterations = int(data.get("max_iterations", 6))
    if not 1 <= max_iterations <= 50:
        raise AgentConfigError(f"{config_path}: max_iterations must be 1-50")
    return AgentSpec(
        name=name,
        description=str(data.get("description", "")),
        persona=persona,
        model=str(data.get("model", "default")),
        tools=list(data.get("tools", [])),
        skills=list(data.get("skills", [])),
        max_iterations=max_iterations,
        temperature=data.get("temperature"),
        max_tokens=data.get("max_tokens"),
        guardrails=GuardrailConfig(**data.get("guardrails", {})),
    )


def load_agents(root: str | Path) -> dict[str, AgentSpec]:
    root = Path(root)
    if not root.is_dir():
        raise AgentConfigError(f"agents directory not found: {root}")
    return {
        spec.name: spec
        for spec in (load_agent(d) for d in sorted(root.iterdir()) if (d / "agent.toml").is_file())
    }
