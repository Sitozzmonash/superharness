"""Typed configuration and secret primitives."""

from super_harness.config.models import (
    ApprovalConfig,
    HarnessConfig,
    ModelConfig,
    MultiAgentConfig,
    PersistenceConfig,
    ProfileName,
    SandboxConfig,
    VisionConfig,
    WebSearchConfig,
)
from super_harness.config.resolution import ConfigResolver, ResolvedConfig
from super_harness.config.secrets import (
    CompositeSecretProvider,
    EnvironmentSecretProvider,
    MappingSecretProvider,
    SecretProvider,
    SecretValue,
    redact_text,
)

__all__ = [
    "ApprovalConfig",
    "CompositeSecretProvider",
    "ConfigResolver",
    "EnvironmentSecretProvider",
    "HarnessConfig",
    "MappingSecretProvider",
    "ModelConfig",
    "MultiAgentConfig",
    "PersistenceConfig",
    "ProfileName",
    "ResolvedConfig",
    "SandboxConfig",
    "SecretProvider",
    "SecretValue",
    "VisionConfig",
    "WebSearchConfig",
    "redact_text",
]
