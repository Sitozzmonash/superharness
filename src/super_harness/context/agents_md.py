"""Project-root bounded AGENTS.md discovery."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from super_harness.models import MessageRole

from .fragments import ContextFragment, ContextKind


@dataclass(frozen=True, slots=True)
class AgentsMdLoader:
    root_markers: tuple[str, ...] = (".git",)
    max_bytes: int = 32_768
    filenames: tuple[str, ...] = ("AGENTS.override.md", "AGENTS.md")

    def project_root(self, cwd: Path) -> Path:
        directory = cwd.resolve(strict=True)
        if not self.root_markers:
            return directory
        for candidate in (directory, *directory.parents):
            if any((candidate / marker).exists() for marker in self.root_markers):
                return candidate
        return directory

    def discover(self, cwd: str | Path) -> tuple[Path, ...]:
        directory = Path(cwd).resolve(strict=True)
        if not directory.is_dir():
            raise ValueError("AGENTS.md cwd must be a directory")
        root = self.project_root(directory)
        relative = directory.relative_to(root)
        directories = [root]
        current = root
        for part in relative.parts:
            current = current / part
            directories.append(current)
        found: list[Path] = []
        for search_dir in directories:
            for filename in self.filenames:
                candidate = search_dir / filename
                if candidate.is_file():
                    found.append(candidate)
                    break
        return tuple(found)

    def load(self, cwd: str | Path) -> tuple[ContextFragment, ...]:
        remaining = self.max_bytes
        fragments: list[ContextFragment] = []
        for path in self.discover(cwd):
            if remaining <= 0:
                break
            data = path.read_bytes()[:remaining]
            remaining -= len(data)
            content = data.decode("utf-8", errors="replace")
            if content.strip():
                fragments.append(
                    ContextFragment(
                        ContextKind.PROJECT,
                        content,
                        str(path),
                        MessageRole.USER,
                        metadata={"path": str(path)},
                    )
                )
        return tuple(fragments)
