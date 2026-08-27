"""Secret wrappers and conservative log redaction helpers."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

_SECRET_ASSIGNMENT = re.compile(r"(?i)(api[_-]?key|token|secret)(\s*[:=]\s*)([^\s,;]+)")
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")


@dataclass(frozen=True, slots=True)
class SecretValue:
    """A value whose string and repr forms never reveal the secret."""

    _value: str

    def reveal(self) -> str:
        """Return the raw value for an explicit provider-boundary operation."""
        return self._value

    def __str__(self) -> str:
        return "********"

    def __repr__(self) -> str:
        return "SecretValue('********')"


class SecretProvider(Protocol):
    """Resolve one named secret without exposing it through diagnostics."""

    def get(self, name: str) -> SecretValue | None: ...


@dataclass(frozen=True, slots=True)
class EnvironmentSecretProvider:
    environment: Mapping[str, str] | None = None

    def get(self, name: str) -> SecretValue | None:
        source = os.environ if self.environment is None else self.environment
        value = source.get(name)
        return SecretValue(value) if value else None


@dataclass(frozen=True, slots=True)
class MappingSecretProvider:
    values: Mapping[str, str]

    def get(self, name: str) -> SecretValue | None:
        value = self.values.get(name)
        return SecretValue(value) if value else None


@dataclass(frozen=True, slots=True)
class CompositeSecretProvider:
    providers: Sequence[SecretProvider]

    def get(self, name: str) -> SecretValue | None:
        for provider in self.providers:
            if (value := provider.get(name)) is not None:
                return value
        return None


def redact_text(value: str) -> str:
    """Redact common API-key, token, and bearer-secret patterns from text."""
    redacted = _BEARER.sub("Bearer ********", value)
    return _SECRET_ASSIGNMENT.sub(r"\1\2********", redacted)
