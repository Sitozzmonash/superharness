"""Structured exception hierarchy shared by Super Harness subsystems."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any


class SuperHarnessError(Exception):
    """Base class for public framework errors.

    Args:
        message: Human-readable error description without secret values.
        correlation_id: Optional event, trace, or operation identifier.
        details: Redacted diagnostic metadata.
    """

    def __init__(
        self,
        message: str,
        *,
        correlation_id: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.correlation_id = correlation_id
        self.details = MappingProxyType(dict(details or {}))


class ConfigError(SuperHarnessError):
    """Raised when configuration is invalid or cannot be resolved."""


class ProviderError(SuperHarnessError):
    """Base error for normalized provider failures."""


class ModelError(ProviderError):
    """Raised when a model provider operation fails."""


class ToolError(SuperHarnessError):
    """Raised when tool validation or execution fails."""


class ToolValidationError(ToolError):
    """Raised when tool arguments do not satisfy the declared schema."""


class SandboxError(SuperHarnessError):
    """Raised when sandbox preparation or execution fails."""


class ApprovalDenied(SuperHarnessError):
    """Raised when an approval policy denies an operation."""


class MCPError(SuperHarnessError):
    """Raised for normalized Model Context Protocol failures."""


class RAGError(ProviderError):
    """Raised for normalized retrieval service failures."""


class SearchError(ProviderError):
    """Raised for normalized web-search failures."""


class SkillError(SuperHarnessError):
    """Raised when skill discovery, validation, or execution fails."""


class PluginError(SuperHarnessError):
    """Raised when plugin installation, loading, or execution fails."""


class WorkflowError(SuperHarnessError):
    """Raised when workflow validation or execution fails."""


class CancelledError(SuperHarnessError):
    """Normalized cancellation visible at public framework boundaries."""
