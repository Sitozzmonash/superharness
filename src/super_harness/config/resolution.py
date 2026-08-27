"""Deterministic typed configuration resolution."""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import ValidationError

from super_harness.exceptions import ConfigError

from .models import HarnessConfig, ProfileName


@dataclass(frozen=True, slots=True)
class ResolvedConfig:
    config: HarnessConfig
    sources: tuple[Path, ...]
    environment_keys: tuple[str, ...]
    dotenv: Path | None = None

    def diagnostics(self) -> dict[str, object]:
        return {
            "profile": self.config.profile.value,
            "model_provider": self.config.model.provider,
            "model": self.config.model.model,
            "sandbox_backend": self.config.sandbox.backend,
            "sandbox_mode": self.config.sandbox.mode,
            "sources": [str(item) for item in self.sources],
            "environment_overrides": list(self.environment_keys),
            "dotenv": str(self.dotenv) if self.dotenv else None,
        }


class ConfigResolver:
    """Resolve defaults < user < project < environment < runtime."""

    def __init__(self, *, user_config: str | Path | None = None) -> None:
        self.user_config = (
            Path(user_config).resolve()
            if user_config is not None
            else Path.home() / ".super-harness" / "config.toml"
        )

    def resolve(
        self,
        *,
        cwd: str | Path | None = None,
        runtime: Mapping[str, Any] | None = None,
        environment: Mapping[str, str] | None = None,
        load_dotenv: bool = False,
    ) -> ResolvedConfig:
        project = _project_root(Path(cwd or Path.cwd()).resolve())
        project_config = _project_config(project)
        source_values: list[tuple[Path, dict[str, Any]]] = []
        if self.user_config.is_file():
            source_values.append((self.user_config, _read_config(self.user_config)))
        if project_config is not None:
            source_values.append((project_config, _read_config(project_config)))

        env = dict(os.environ if environment is None else environment)
        dotenv_path = project / ".env"
        used_dotenv: Path | None = None
        if load_dotenv and dotenv_path.is_file():
            for key, value in _read_dotenv(dotenv_path).items():
                env.setdefault(key, value)
            used_dotenv = dotenv_path
        env_values, env_keys = _environment_config(env)
        runtime_values = dict(runtime or {})
        profile_value = _profile_value(
            runtime_values,
            env_values,
            *(values for _, values in reversed(source_values)),
        )
        merged = _profile_defaults(profile_value)
        for _, values in source_values:
            _merge(merged, values)
        _merge(merged, env_values)
        _merge(merged, runtime_values)
        merged["profile"] = profile_value.value
        try:
            config = HarnessConfig.model_validate(merged)
        except ValidationError as exc:
            raise ConfigError(
                "configuration validation failed",
                details={"errors": exc.errors(include_url=False)},
            ) from exc
        return ResolvedConfig(
            config,
            tuple(path for path, _ in source_values),
            tuple(env_keys),
            used_dotenv,
        )


def _profile_value(*values: Mapping[str, Any]) -> ProfileName:
    for value in values:
        if "profile" not in value:
            continue
        raw = str(value["profile"]).strip().casefold().replace("-dev", "")
        try:
            return ProfileName(raw)
        except ValueError as exc:
            raise ConfigError(f"unknown configuration profile {raw!r}") from exc
    return ProfileName.CHINA


def _profile_defaults(profile: ProfileName) -> dict[str, Any]:
    base = HarnessConfig(profile=profile).model_dump(mode="python")
    if profile is ProfileName.GLOBAL:
        base["model"] = {"provider": "openai_compatible", "model": "gpt-5"}
        base["vision"] = {"provider": "openai_compatible", "model": "gpt-5"}
    elif profile is ProfileName.OFFLINE:
        base["model"] = {"provider": "offline", "model": "local"}
        base["vision"] = {"provider": "offline", "model": "local"}
        base["web_search"] = {"provider": "disabled", "count": 10}
        base["sandbox"] = {"backend": "local", "mode": "read_only"}
    elif profile is ProfileName.TEST:
        base["model"] = {"provider": "test", "model": "deterministic"}
        base["vision"] = {"provider": "test", "model": "deterministic"}
        base["web_search"] = {"provider": "test", "count": 3}
        base["persistence"] = {"backend": "sqlite", "path": ":memory:"}
    return base


def _environment_config(environment: Mapping[str, str]) -> tuple[dict[str, Any], list[str]]:
    mapping: dict[str, tuple[str, ...]] = {
        "SUPER_HARNESS_PROFILE": ("profile",),
        "SUPER_HARNESS_MODEL_PROVIDER": ("model", "provider"),
        "SUPER_HARNESS_MODEL": ("model", "model"),
        "SUPER_HARNESS_VISION_PROVIDER": ("vision", "provider"),
        "SUPER_HARNESS_VISION_MODEL": ("vision", "model"),
        "SUPER_HARNESS_SEARCH_PROVIDER": ("web_search", "provider"),
        "SUPER_HARNESS_SANDBOX_BACKEND": ("sandbox", "backend"),
        "SUPER_HARNESS_SANDBOX_MODE": ("sandbox", "mode"),
        "SUPER_HARNESS_APPROVAL_MODE": ("approval", "mode"),
    }
    result: dict[str, Any] = {}
    used: list[str] = []
    for name, path in mapping.items():
        if name not in environment:
            continue
        _set_nested(result, path, environment[name])
        used.append(name)
    return result, used


def _read_config(path: Path) -> dict[str, Any]:
    try:
        if path.suffix.casefold() == ".toml":
            value: object = tomllib.loads(path.read_text(encoding="utf-8"))
        else:
            value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError, yaml.YAMLError) as exc:
        raise ConfigError("unable to read configuration", details={"path": str(path)}) from exc
    if not isinstance(value, dict):
        raise ConfigError("configuration root must be an object", details={"path": str(path)})
    return cast(dict[str, Any], value)


def _read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ConfigError("unable to read .env", details={"path": str(path)}) from exc
    for index, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, separator, raw = stripped.partition("=")
        if not separator or not key.strip().replace("_", "").isalnum():
            raise ConfigError("invalid .env assignment", details={"line": index})
        values[key.strip()] = raw.strip().strip("'\"")
    return values


def _merge(target: dict[str, Any], source: Mapping[str, Any]) -> None:
    for key, value in source.items():
        current = target.get(key)
        if isinstance(current, dict) and isinstance(value, Mapping):
            _merge(cast(dict[str, Any], current), cast(Mapping[str, Any], value))
        else:
            target[key] = value


def _set_nested(target: dict[str, Any], path: tuple[str, ...], value: object) -> None:
    cursor = target
    for segment in path[:-1]:
        child = cursor.setdefault(segment, {})
        if not isinstance(child, dict):
            raise ConfigError(f"configuration key {segment!r} conflicts with an object")
        cursor = cast(dict[str, Any], child)
    cursor[path[-1]] = value


def _project_root(cwd: Path) -> Path:
    for candidate in (cwd, *cwd.parents):
        if (candidate / ".git").exists():
            return candidate
    return cwd


def _project_config(project: Path) -> Path | None:
    root = project / ".super-harness"
    candidates = [root / "config.toml", root / "config.yaml", root / "config.yml"]
    return next((path for path in candidates if path.is_file()), None)
