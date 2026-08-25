"""Typed configuration skeleton and stable defaults."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ProfileName(StrEnum):
    """Built-in configuration composition profiles."""

    CHINA = "china"
    GLOBAL = "global"
    OFFLINE = "offline"
    TEST = "test"


class ModelConfig(BaseModel):
    """Main text-model selection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str = "deepseek"
    model: str = "deepseek-v4-flash"


class SandboxConfig(BaseModel):
    """Sandbox backend and access mode selection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    backend: str = "local"
    mode: str = "workspace_write"


class ApprovalConfig(BaseModel):
    """Approval engine defaults."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: str = "full_access"


class HarnessConfig(BaseModel):
    """Root configuration model used by later resolution layers.

    Runtime arguments, environment variables, project config, user config,
    and defaults are merged by the configuration loader delivered in a later
    phase. This model defines the validated target shape and defaults.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    profile: ProfileName = ProfileName.CHINA
    model: ModelConfig = Field(default_factory=ModelConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    approval: ApprovalConfig = Field(default_factory=ApprovalConfig)
