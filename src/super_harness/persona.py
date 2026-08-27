"""Typed Agent identity, persona, and role templates."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from types import MappingProxyType

from super_harness.models import ModelProvider
from super_harness.tools import Tool


def _templates() -> Mapping[str, Persona]:
    return {}


@dataclass(frozen=True, slots=True)
class Persona:
    """Instruction/configuration layer for one Agent identity."""

    name: str
    role: str
    goal: str
    instructions: str = ""
    constraints: tuple[str, ...] = ()
    model_override: str | None = None
    tool_scopes: tuple[str, ...] = ("*",)
    skill_scopes: tuple[str, ...] = ("*",)
    memory_scope: str = "thread"
    subagent_roles: Mapping[str, Persona] = field(default_factory=_templates)

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._ -]{0,63}", self.name):
            raise ValueError("persona name is invalid")
        if not self.role.strip() or not self.goal.strip():
            raise ValueError("persona role and goal are required")
        if self.memory_scope not in {"none", "thread", "long_term", "both"}:
            raise ValueError("persona memory_scope is invalid")
        if any(not value.strip() for value in (*self.tool_scopes, *self.skill_scopes)):
            raise ValueError("persona scopes may not be empty")
        if self.name in self.subagent_roles:
            raise ValueError("persona may not contain itself as a named subagent role")
        object.__setattr__(self, "subagent_roles", MappingProxyType(dict(self.subagent_roles)))

    def compose_instructions(self, additional: str | None = None) -> str:
        sections = [
            f"Identity: {self.name}",
            f"Role: {self.role}",
            f"Goal: {self.goal}",
        ]
        if self.instructions.strip():
            sections.append(f"Instructions:\n{self.instructions.strip()}")
        if self.constraints:
            constraints = "\n".join(f"- {item.strip()}" for item in self.constraints)
            sections.append(f"Constraints:\n{constraints}")
        if additional and additional.strip():
            sections.append(f"Application instructions:\n{additional.strip()}")
        return "\n\n".join(sections)

    def validate_provider(self, provider: ModelProvider) -> None:
        if self.model_override is None:
            return
        actual = getattr(provider, "model", None)
        if actual != self.model_override:
            raise ValueError(
                f"persona requires model {self.model_override!r}; configured provider uses "
                f"{actual!r}"
            )

    def select_tools(self, tools: Iterable[Tool]) -> tuple[Tool, ...]:
        return tuple(
            item
            for item in tools
            if any(fnmatchcase(item.qualified_name, scope) for scope in self.tool_scopes)
        )

    def subagent(self, role: str) -> Persona:
        try:
            return self.subagent_roles[role]
        except KeyError as exc:
            raise KeyError(f"unknown subagent role {role!r}") from exc

    def metadata(self) -> dict[str, object]:
        return {
            "persona": self.name,
            "role": self.role,
            "memory_scope": self.memory_scope,
            "skill_scopes": list(self.skill_scopes),
        }
