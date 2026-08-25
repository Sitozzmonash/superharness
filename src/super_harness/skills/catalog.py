"""Ordered skill discovery with metadata-only progressive loading."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from super_harness.exceptions import SkillError

from .models import ActivatedSkill, SkillMetadata, activate_skill, parse_skill


def _skills() -> dict[str, SkillMetadata]:
    return {}


def _collisions() -> dict[str, list[Path]]:
    return {}


def _errors() -> list[SkillError]:
    return []


@dataclass(slots=True)
class SkillCatalog:
    skills: dict[str, SkillMetadata] = field(default_factory=_skills)
    collisions: dict[str, list[Path]] = field(default_factory=_collisions)
    errors: list[SkillError] = field(default_factory=_errors)

    @classmethod
    def discover(
        cls,
        *,
        cwd: str | Path | None = None,
        explicit: Iterable[str | Path] = (),
        user_root: str | Path | None = None,
        plugin_roots: Iterable[str | Path] = (),
        system_roots: Iterable[str | Path] = (),
    ) -> SkillCatalog:
        catalog = cls()
        roots: list[tuple[str, Path]] = [("explicit", Path(item)) for item in explicit]
        if cwd is not None:
            project = _project_root(Path(cwd).resolve())
            roots.extend(
                [
                    ("project-agents", project / ".agents" / "skills"),
                    ("project-super-harness", project / ".super-harness" / "skills"),
                ]
            )
        roots.append(
            (
                "user",
                Path(user_root)
                if user_root is not None
                else Path.home() / ".super-harness" / "skills",
            )
        )
        roots.extend(("plugin", Path(item)) for item in plugin_roots)
        roots.extend(("system", Path(item)) for item in system_roots)
        for source, root in roots:
            candidates = [root] if (root / "SKILL.md").is_file() else []
            if root.is_dir() and not candidates:
                candidates = sorted(path.parent for path in root.glob("*/SKILL.md"))
            for candidate in candidates:
                try:
                    metadata = parse_skill(candidate, source=source)
                except SkillError as exc:
                    catalog.errors.append(exc)
                    continue
                if metadata.name in catalog.skills:
                    catalog.collisions.setdefault(metadata.name, []).append(metadata.path)
                    continue
                catalog.skills[metadata.name] = metadata
        return catalog

    def list(self) -> tuple[SkillMetadata, ...]:
        return tuple(self.skills.values())

    def get(self, name: str) -> SkillMetadata:
        try:
            return self.skills[name]
        except KeyError as exc:
            raise SkillError(f"unknown skill {name!r}") from exc

    def activate(self, name: str) -> ActivatedSkill:
        return activate_skill(self.get(name))


def _project_root(cwd: Path) -> Path:
    for candidate in (cwd, *cwd.parents):
        if (candidate / ".git").exists():
            return candidate
    return cwd
