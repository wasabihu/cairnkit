# Adapted from hermes-agent v0.22.2 (d923a5e): tools/registry.py
# Copyright (c) 2025 Nous Research. MIT License. Added per-call identity context and access levels.
"""Tool registry: schema, handler, access level and who may use each tool.

Identity never comes from the model. Handlers receive a :class:`ToolContext` built by
the host application from the signed-in user; arguments the model sends are only
the tool's own parameters.
"""

from __future__ import annotations

import inspect
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

logger = logging.getLogger(__name__)

Access = Literal["read", "propose", "write"]
"""read: no side effects. propose: creates drafts a human must approve. write: changes state."""


@dataclass(frozen=True)
class ToolContext:
    """Who is acting and on what, supplied by the host application per run."""

    principal: Mapping[str, Any] = field(default_factory=dict)
    roles: frozenset[str] = frozenset()
    scope: Mapping[str, Any] = field(default_factory=dict)
    """Host objects the tools may use (database session, the record being worked on, ...)."""


class ToolError(Exception):
    """Raise from a handler for an expected failure; the message is shown to the model."""


Handler = Callable[[dict[str, Any], ToolContext], Any | Awaitable[Any]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Handler
    access: Access = "read"
    roles: frozenset[str] | None = None  # None: any signed-in principal

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass(frozen=True)
class ToolOutcome:
    result: str  # always a JSON string, as Hermes handlers return
    failed: bool


def tool_result(**data: Any) -> str:
    return json.dumps({"success": True, **data}, ensure_ascii=False, default=str)


def tool_error(message: str, **data: Any) -> str:
    return json.dumps({"success": False, "error": message, **data}, ensure_ascii=False, default=str)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> ToolSpec:
        if spec.name in self._tools:
            raise ValueError(f"tool {spec.name!r} is already registered")
        if spec.parameters.get("type") != "object":
            raise ValueError(f"tool {spec.name!r}: parameters must be a JSON object schema")
        self._tools[spec.name] = spec
        return spec

    def tool(
        self,
        *,
        name: str,
        description: str,
        parameters: dict[str, Any] | None = None,
        access: Access = "read",
        roles: set[str] | frozenset[str] | None = None,
    ) -> Callable[[Handler], Handler]:
        def decorator(fn: Handler) -> Handler:
            self.register(
                ToolSpec(
                    name=name,
                    description=description,
                    parameters=parameters or {"type": "object", "properties": {}},
                    handler=fn,
                    access=access,
                    roles=frozenset(roles) if roles is not None else None,
                )
            )
            return fn

        return decorator

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def available(self, allowed: list[str] | None, ctx: ToolContext) -> list[ToolSpec]:
        """Tools in ``allowed`` (all when None) that the principal's roles permit."""
        names = self.names() if allowed is None else allowed
        unknown = [n for n in names if n not in self._tools]
        if unknown:
            raise ValueError(f"unknown tools: {', '.join(unknown)}")
        return [
            spec
            for spec in (self._tools[n] for n in names)
            if spec.roles is None or spec.roles & ctx.roles
        ]

    async def dispatch(
        self, spec: ToolSpec, arguments: dict[str, Any], ctx: ToolContext
    ) -> ToolOutcome:
        if spec.roles is not None and not spec.roles & ctx.roles:
            return ToolOutcome(tool_error(f"{spec.name} is not permitted for this user"), True)
        try:
            value = spec.handler(arguments, ctx)
            if inspect.isawaitable(value):
                value = await value
        except ToolError as exc:
            return ToolOutcome(tool_error(str(exc)), True)
        except Exception:
            # Never leak internals (paths, SQL, secrets) to the model.
            logger.exception("tool %s crashed", spec.name)
            return ToolOutcome(tool_error(f"{spec.name} failed unexpectedly"), True)
        if isinstance(value, str):
            return ToolOutcome(value, _looks_failed(value))
        return ToolOutcome(
            tool_result(**value) if isinstance(value, dict) else tool_result(result=value), False
        )


def _looks_failed(result: str) -> bool:
    try:
        data = json.loads(result)
    except ValueError:
        return False
    return isinstance(data, dict) and data.get("success") is False
