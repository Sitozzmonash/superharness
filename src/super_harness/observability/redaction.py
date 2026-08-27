"""Bounded recursive secret redaction for logs and telemetry."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any, cast

from super_harness.config import SecretValue

MASK = "********"

_ASSIGNMENT = re.compile(
    r"(?i)(api[_-]?key|access[_-]?token|auth(?:orization)?|password|secret|token)"
    r"(\s*[:=]\s*)([^\s,;&]+)"
)
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_KNOWN_TOKEN = re.compile(r"(?<![A-Za-z0-9])(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{12,})")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")

DEFAULT_SECRET_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "access_token",
        "refresh_token",
        "password",
        "secret",
        "token",
        "cookie",
        "set-cookie",
    }
)

CustomRedactor = Callable[[object], object]


class SecretRedactor:
    """Redact known patterns, configured values, secret keys, and custom values."""

    def __init__(
        self,
        *,
        secrets: Sequence[str] = (),
        secret_keys: Sequence[str] = (),
        custom: Sequence[CustomRedactor] = (),
        max_depth: int = 8,
        max_items: int = 128,
        max_string_chars: int = 20_000,
    ) -> None:
        if max_depth < 1 or max_items < 1 or max_string_chars < 1:
            raise ValueError("redaction bounds must be positive")
        self.secrets = tuple(sorted((value for value in secrets if value), key=len, reverse=True))
        self.secret_keys = DEFAULT_SECRET_KEYS | {
            _normalize_key(value) for value in secret_keys if value
        }
        self.custom = tuple(custom)
        self.max_depth = max_depth
        self.max_items = max_items
        self.max_string_chars = max_string_chars

    def redact(self, value: object) -> Any:
        candidate = value
        for callback in self.custom:
            candidate = callback(candidate)
        return self._redact(candidate, 0, set())

    def text(self, value: str) -> str:
        bounded = value[: self.max_string_chars]
        for secret in self.secrets:
            bounded = bounded.replace(secret, MASK)
        bounded = _BEARER.sub(f"Bearer {MASK}", bounded)
        bounded = _ASSIGNMENT.sub(rf"\1\2{MASK}", bounded)
        bounded = _KNOWN_TOKEN.sub(MASK, bounded)
        return _JWT.sub(MASK, bounded)

    def _redact(self, value: object, depth: int, seen: set[int]) -> Any:
        if depth >= self.max_depth:
            return "<max-depth>"
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, SecretValue):
            return MASK
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, bytes):
            return f"<bytes:{len(value)}>"
        if isinstance(value, Enum):
            return self.text(str(value.value))
        if isinstance(value, BaseException):
            return {"error_class": type(value).__name__, "message": self.text(str(value))}

        identity = id(value)
        if identity in seen:
            return "<cycle>"
        seen.add(identity)
        try:
            if isinstance(value, Mapping):
                mapping = cast(Mapping[object, object], value)
                output: dict[str, Any] = {}
                for index, (key, item) in enumerate(mapping.items()):
                    if index >= self.max_items:
                        output["<truncated>"] = len(mapping) - self.max_items
                        break
                    safe_key = self.text(str(key))
                    if _normalize_key(str(key)) in self.secret_keys:
                        output[safe_key] = MASK
                    else:
                        output[safe_key] = self._redact(item, depth + 1, seen)
                return output
            if isinstance(value, Sequence):
                sequence = cast(Sequence[object], value)
                return [self._redact(item, depth + 1, seen) for item in sequence[: self.max_items]]
            if is_dataclass(value) and not isinstance(value, type):
                return {
                    item.name: self._redact(getattr(value, item.name), depth + 1, seen)
                    for item in fields(value)
                    if not item.name.startswith("_")
                }
            return self.text(str(value))
        finally:
            seen.discard(identity)


def _normalize_key(value: str) -> str:
    return value.strip().lower().replace("-", "_")
