"""Validated local and HTTPS Git plugin installation lifecycle."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse
from uuid import uuid4

from super_harness.exceptions import PluginError

from .loader import load_plugin
from .models import InstalledPlugin, PluginManifest

_SOURCE_FILE = ".super-harness-source.json"


class PluginInstaller:
    def __init__(self, destination: str | Path) -> None:
        self.destination = Path(destination).resolve()
        self.destination.mkdir(parents=True, exist_ok=True)

    def install(self, source: str | Path) -> InstalledPlugin:
        root, source_data, cleanup = self._stage_source(source)
        try:
            manifest = load_plugin(root)
            target = self._target(manifest.name)
            if target.exists():
                raise PluginError(f"plugin {manifest.name!r} is already installed")
            self._validate_tree(root)
            shutil.copytree(root, target)
            self._write_source(target, source_data)
            return InstalledPlugin(load_plugin(target), False, source_data)
        finally:
            cleanup.cleanup()

    def update(self, name: str) -> InstalledPlugin:
        current = self.info(name)
        source = current.source.get("location")
        if not isinstance(source, str) or not source:
            raise PluginError("plugin source metadata cannot be updated")
        root, source_data, cleanup = self._stage_source(source)
        target = self._target(name)
        staging = self.destination / f".{name}-staging-{uuid4().hex}"
        backup = self.destination / f".{name}-backup-{uuid4().hex}"
        try:
            manifest = load_plugin(root)
            if manifest.name != name:
                raise PluginError("updated plugin name differs from installed plugin")
            self._validate_tree(root)
            shutil.copytree(root, staging)
            self._write_source(staging, source_data)
            target.rename(backup)
            try:
                staging.rename(target)
            except BaseException:
                backup.rename(target)
                raise
            shutil.rmtree(backup)
            return InstalledPlugin(load_plugin(target), False, source_data)
        finally:
            cleanup.cleanup()
            if staging.exists():
                shutil.rmtree(staging)
            if backup.exists() and not target.exists():
                backup.rename(target)

    def remove(self, name: str) -> None:
        target = self._target(name)
        if not target.is_dir():
            raise PluginError(f"plugin {name!r} is not installed")
        shutil.rmtree(target)

    def list(self) -> tuple[PluginManifest, ...]:
        manifests: list[PluginManifest] = []
        for path in sorted(self.destination.iterdir()):
            if path.is_dir() and not path.name.startswith("."):
                manifests.append(load_plugin(path))
        return tuple(manifests)

    def info(self, name: str) -> InstalledPlugin:
        target = self._target(name)
        if not target.is_dir():
            raise PluginError(f"plugin {name!r} is not installed")
        source_path = target / _SOURCE_FILE
        try:
            source: object = json.loads(source_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PluginError("plugin source metadata is missing or invalid") from exc
        if not isinstance(source, dict):
            raise PluginError("plugin source metadata must be an object")
        return InstalledPlugin(load_plugin(target), False, cast(dict[str, Any], source))

    def _stage_source(
        self, source: str | Path
    ) -> tuple[Path, dict[str, str], tempfile.TemporaryDirectory[str]]:
        temporary = tempfile.TemporaryDirectory(prefix="super-harness-plugin-")
        try:
            staging = Path(temporary.name) / "plugin"
            value = str(source)
            if value.startswith(("https://", "git+https://")):
                location = value.removeprefix("git+")
                revision = self._clone(location, staging)
                return staging, _source("git", location, revision), temporary
            local = Path(source).resolve()
            if not local.is_dir():
                raise PluginError("local plugin source must be a directory")
            shutil.copytree(local, staging, symlinks=True)
            return staging, _source("local", str(local), ""), temporary
        except BaseException:
            temporary.cleanup()
            raise

    def _clone(self, source: str, staging: Path) -> str:
        parsed = urlparse(source)
        if parsed.scheme != "https":
            raise PluginError("remote plugins require an HTTPS Git URL")
        repo_url = source
        revision = ""
        subdirectory = ""
        if parsed.netloc.casefold() == "github.com" and "/tree/" in parsed.path:
            repo_path, remainder = parsed.path.split("/tree/", 1)
            parts = remainder.split("/", 1)
            revision = parts[0]
            subdirectory = parts[1] if len(parts) == 2 else ""
            repo_url = f"https://github.com{repo_path}.git"
        clone = staging.parent / "repo"
        result = subprocess.run(
            ["git", "clone", "--depth", "1", repo_url, str(clone)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise PluginError("plugin Git clone failed", details={"source": source})
        if revision:
            result = subprocess.run(
                ["git", "-C", str(clone), "fetch", "--depth", "1", "origin", revision],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                result = subprocess.run(
                    ["git", "-C", str(clone), "checkout", "--detach", "FETCH_HEAD"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
            if result.returncode != 0:
                raise PluginError("plugin Git revision checkout failed", details={"source": source})
        selected = (clone / subdirectory).resolve()
        try:
            selected.relative_to(clone.resolve())
        except ValueError as exc:
            raise PluginError("plugin Git subdirectory escapes repository") from exc
        if not selected.is_dir():
            raise PluginError("plugin Git subdirectory does not exist")
        shutil.copytree(selected, staging, symlinks=True)
        return subprocess.run(
            ["git", "-C", str(clone), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    def _validate_tree(self, root: Path) -> None:
        if any(path.is_symlink() for path in root.rglob("*")):
            raise PluginError("plugin packages may not contain symbolic links")

    def _target(self, name: str) -> Path:
        target = (self.destination / name).resolve()
        try:
            target.relative_to(self.destination)
        except ValueError as exc:
            raise PluginError("plugin name escapes installation root") from exc
        return target

    def _write_source(self, target: Path, source: dict[str, str]) -> None:
        (target / _SOURCE_FILE).write_text(
            json.dumps(source, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def _source(source_type: str, location: str, revision: str) -> dict[str, str]:
    return {
        "source_type": source_type,
        "location": location,
        "revision": revision,
        "installed_at": datetime.now(UTC).isoformat(),
    }
