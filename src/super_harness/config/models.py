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


class VisionConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str = "zhipu"
    model: str = "glm-4v-flash"


class WebSearchConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str = "zhipu"
    count: int = Field(default=10, ge=1, le=50)


class SandboxConfig(BaseModel):
    """Sandbox backend and access mode selection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    backend: str = "local"
    mode: str = "workspace_write"


class ApprovalConfig(BaseModel):
    """Approval engine defaults."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: str = "full_access"


class MultiAgentConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_agents: int = Field(default=6, ge=1, le=64)
    max_depth: int = Field(default=2, ge=0, le=16)


class PersistenceConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    backend: str = "sqlite"
    path: str = ".super-harness/state.db"


class HarnessConfig(BaseModel):
    """Validated target for defaults, files, environment, and runtime overrides."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    profile: ProfileName = ProfileName.CHINA
    model: ModelConfig = Field(default_factory=ModelConfig)
    vision: VisionConfig = Field(default_factory=VisionConfig)
    web_search: WebSearchConfig = Field(default_factory=WebSearchConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    approval: ApprovalConfig = Field(default_factory=ApprovalConfig)
    multi_agent: MultiAgentConfig = Field(default_factory=MultiAgentConfig)
    persistence: PersistenceConfig = Field(default_factory=PersistenceConfig)
