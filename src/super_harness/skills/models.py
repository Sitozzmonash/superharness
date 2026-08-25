"""Open Agent Skills metadata and progressive activation."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

import yaml

from super_harness.exceptions import SkillError


def _extra() -> Mapping[str, Any]:
    return {}


@dataclass(frozen=True, slots=True)
class SkillMetadata:
    name: str
    description: str
    path: Path
    source: str = "runtime"
    extra: Mapping[str, Any] = field(default_factory=_extra)

    def __post_init__(self) -> None:
        object.__setattr__(self, "extra", MappingProxyType(dict(self.extra)))


@dataclass(frozen=True, slots=True)
class ActivatedSkill:
    metadata: SkillMetadata
    instructions: str

    def read_resource(self, relative_path: str) -> bytes:
        root = self.metadata.path.parent.resolve()
        path = (root / relative_path).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise SkillError("skill resource escapes its directory") from exc
        if not path.is_file():
            raise SkillError("skill resource does not exist", details={"path": relative_path})
        return path.read_bytes()


def parse_skill(path: str | Path, *, source: str = "runtime") -> SkillMetadata:
    skill_path = Path(path)
    if skill_path.is_dir():
        skill_path = skill_path / "SKILL.md"
    try:
        text = skill_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SkillError("unable to read SKILL.md", details={"path": str(skill_path)}) from exc
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise SkillError("SKILL.md is missing YAML frontmatter")
    try:
        end = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration as exc:
        raise SkillError("SKILL.md frontmatter is not closed") from exc
    frontmatter = "\n".join(lines[1:end])
    try:
        decoded = yaml.safe_load(frontmatter)
    except yaml.YAMLError:
        try:
            decoded = yaml.safe_load(_repair_colon_scalars(frontmatter))
        except yaml.YAMLError as exc:
            raise SkillError("SKILL.md contains invalid YAML") from exc
    if not isinstance(decoded, dict):
        raise SkillError("SKILL.md frontmatter must be an object")
    values = cast(dict[str, Any], decoded)
    name = str(values.get("name") or skill_path.parent.name).strip()
    description = str(values.get("description") or "").strip()
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
        raise SkillError("skill name must contain lowercase letters, numbers, and hyphens")
    if len(name) > 64:
        raise SkillError("skill name must be no more than 64 characters")
    if not description:
        raise SkillError("skill description is required")
    return SkillMetadata(name, " ".join(description.split()), skill_path.resolve(), source, values)


def _repair_colon_scalars(frontmatter: str) -> str:
    repaired: list[str] = []
    for line in frontmatter.splitlines():
        if ":" not in line:
            repaired.append(line)
            continue
        key, value = line.split(":", 1)
        scalar = value.strip()
        if ": " in scalar and not scalar.startswith(("'", '"', "|", ">")):
            repaired.append(f"{key}: {json.dumps(scalar, ensure_ascii=False)}")
        else:
            repaired.append(line)
    return "\n".join(repaired)


def activate_skill(metadata: SkillMetadata) -> ActivatedSkill:
    text = metadata.path.read_text(encoding="utf-8")
    lines = text.splitlines()
    end = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    instructions = "\n".join(lines[end + 1 :]).strip()
    if not instructions:
        raise SkillError("SKILL.md instructions are empty", details={"name": metadata.name})
    return ActivatedSkill(metadata, instructions)
