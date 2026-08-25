"""Provider-neutral immutable model request and response values."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, TypeAlias

JsonObject: TypeAlias = Mapping[str, Any]


def _freeze(value: Mapping[str, Any] | None = None) -> JsonObject:
    return MappingProxyType(dict(value or {}))


class MessageRole(StrEnum):
    SYSTEM = "system"
    DEVELOPER = "developer"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(frozen=True, slots=True)
class Message:
    role: MessageRole
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    parameters: JsonObject

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("tool name must be non-empty")
        object.__setattr__(self, "parameters", _freeze(self.parameters))


@dataclass(frozen=True, slots=True)
class ToolCall:
    call_id: str
    name: str
    arguments: JsonObject
    raw_arguments: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "arguments", _freeze(self.arguments))


@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True, slots=True)
class ModelCapabilities:
    streaming: bool = True
    tools: bool = True
    structured_output: bool = True
    reasoning: bool = False
    parallel_tool_calls: bool = True
    wire_apis: tuple[str, ...] = ("chat_completions",)


@dataclass(frozen=True, slots=True)
class ModelRequest:
    messages: Sequence[Message]
    tools: Sequence[ToolDefinition] = ()
    output_schema: JsonObject | None = None
    temperature: float | None = None
    parallel_tool_calls: bool = True
    extra: JsonObject = field(default_factory=_freeze)

    def __post_init__(self) -> None:
        object.__setattr__(self, "messages", tuple(self.messages))
        object.__setattr__(self, "tools", tuple(self.tools))
        if self.output_schema is not None:
            object.__setattr__(self, "output_schema", _freeze(self.output_schema))
        object.__setattr__(self, "extra", _freeze(self.extra))


@dataclass(frozen=True, slots=True)
class ModelResponse:
    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    usage: Usage = field(default_factory=Usage)
    response_id: str | None = None
    finish_reason: str | None = None
    output_json: JsonObject | None = None

    def __post_init__(self) -> None:
        if self.output_json is not None:
            object.__setattr__(self, "output_json", _freeze(self.output_json))


class ModelStreamEventType(StrEnum):
    STARTED = "started"
    TEXT_DELTA = "text_delta"
    TOOL_CALL_DELTA = "tool_call_delta"
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class ModelStreamEvent:
    type: ModelStreamEventType
    delta: str = ""
    tool_call_index: int | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    response: ModelResponse | None = None
