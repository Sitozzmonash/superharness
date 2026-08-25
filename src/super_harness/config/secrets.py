"""Secret wrappers and conservative log redaction helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass

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


def redact_text(value: str) -> str:
    """Redact common API-key, token, and bearer-secret patterns from text."""
    redacted = _BEARER.sub("Bearer ********", value)
    return _SECRET_ASSIGNMENT.sub(r"\1\2********", redacted)
