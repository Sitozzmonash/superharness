"""Validated local and Git skill installation."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from super_harness.exceptions import SkillError

from .models import SkillMetadata, parse_skill


@dataclass(frozen=True, slots=True)
class SkillSource:
    source_type: str
    location: str
    revision: str | None
    installed_at: str


class SkillInstaller:
    def __init__(self, destination: str | Path) -> None:
        self.destination = Path(destination)
        self.destination.mkdir(parents=True, exist_ok=True)

    def install(self, source: str | Path) -> SkillMetadata:
        value = str(source)
        if value.startswith(("https://", "git+https://")):
            return self._install_git(value.removeprefix("git+"))
        path = Path(source).resolve()
        metadata = parse_skill(path, source="local")
        return self._copy(metadata, SkillSource("local", str(path), None, _now()))

    def _install_git(self, source: str) -> SkillMetadata:
        parsed = urlparse(source)
        if parsed.scheme != "https":
            raise SkillError("remote skills require an HTTPS Git URL")
        repo_url = source
        revision: str | None = None
        subdirectory = ""
        if parsed.netloc.casefold() == "github.com" and "/tree/" in parsed.path:
            repo_path, remainder = parsed.path.split("/tree/", 1)
            parts = remainder.split("/", 1)
            revision = parts[0]
            subdirectory = parts[1] if len(parts) == 2 else ""
            repo_url = f"https://github.com{repo_path}.git"
        with tempfile.TemporaryDirectory(prefix="super-harness-skill-") as temporary:
            clone = Path(temporary) / "repo"
            command = ["git", "clone", "--depth", "1", repo_url, str(clone)]
            result = subprocess.run(command, capture_output=True, text=True, check=False)
            if result.returncode != 0:
                raise SkillError("skill Git clone failed", details={"source": source})
            if revision:
                checkout = subprocess.run(
                    ["git", "-C", str(clone), "fetch", "--depth", "1", "origin", revision],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if checkout.returncode == 0:
                    checkout = subprocess.run(
                        ["git", "-C", str(clone), "checkout", "--detach", "FETCH_HEAD"],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                if checkout.returncode != 0:
                    raise SkillError(
                        "skill Git revision checkout failed", details={"source": source}
                    )
            skill_root = (clone / subdirectory).resolve()
            try:
                skill_root.relative_to(clone.resolve())
            except ValueError as exc:
                raise SkillError("Git skill subdirectory escapes repository") from exc
            metadata = parse_skill(skill_root, source="git")
            commit = subprocess.run(
                ["git", "-C", str(clone), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            return self._copy(metadata, SkillSource("git", source, commit, _now()))

    def _copy(self, metadata: SkillMetadata, source: SkillSource) -> SkillMetadata:
        target = (self.destination / metadata.name).resolve()
        try:
            target.relative_to(self.destination.resolve())
        except ValueError as exc:
            raise SkillError("skill name escapes installation root") from exc
        if target.exists():
            raise SkillError(f"skill {metadata.name!r} is already installed")
        if any(path.is_symlink() for path in metadata.path.parent.rglob("*")):
            raise SkillError("skill packages may not contain symbolic links")
        shutil.copytree(metadata.path.parent, target, symlinks=True)
        (target / ".super-harness-source.json").write_text(
            json.dumps(asdict(source), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return parse_skill(target, source=source.source_type)

    def remove(self, name: str) -> None:
        target = (self.destination / name).resolve()
        try:
            target.relative_to(self.destination.resolve())
        except ValueError as exc:
            raise SkillError("skill name escapes installation root") from exc
        if not target.is_dir():
            raise SkillError(f"skill {name!r} is not installed")
        shutil.rmtree(target)


def _now() -> str:
    return datetime.now(UTC).isoformat()
