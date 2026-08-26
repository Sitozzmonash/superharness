"""Provider-neutral immutable model request and response values."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, TypeAlias, cast

JsonObject: TypeAlias = Mapping[str, Any]

_TOOL_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")


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
        if _TOOL_NAME.fullmatch(self.name) is None:
            raise ValueError(
                "tool name must be non-empty and contain 1-128 safe letters, numbers, dot, "
                "dash, or underscore"
            )
        _validate_json(self.parameters, path="parameters")
        object.__setattr__(self, "parameters", _freeze(self.parameters))


@dataclass(frozen=True, slots=True)
class ToolCall:
    call_id: str
    name: str
    arguments: JsonObject
    raw_arguments: str

    def __post_init__(self) -> None:
        invalid_call_id = (
            not self.call_id
            or len(self.call_id) > 256
            or any(ord(char) < 32 for char in self.call_id)
        )
        if invalid_call_id:
            raise ValueError("tool call ID must be 1-256 characters without control characters")
        if _TOOL_NAME.fullmatch(self.name) is None:
            raise ValueError("tool call name contains unsafe characters")
        _validate_json(self.arguments, path="arguments")
        if len(self.raw_arguments) > 1_000_000:
            raise ValueError("raw tool arguments exceed one million characters")
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


def _validate_json(
    value: object,
    *,
    path: str,
    depth: int = 0,
    seen: set[int] | None = None,
) -> None:
    if depth > 32:
        raise ValueError(f"{path} exceeds maximum JSON nesting depth")
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} contains a non-finite number")
        return
    identities: set[int] = seen if seen is not None else set()
    identity = id(value)
    if identity in identities:
        raise ValueError(f"{path} contains a cycle")
    identities.add(identity)
    try:
        if isinstance(value, Mapping):
            mapping = cast(Mapping[object, object], value)
            if len(mapping) > 10_000:
                raise ValueError(f"{path} contains too many object fields")
            for key, item in mapping.items():
                if not isinstance(key, str):
                    raise ValueError(f"{path} object keys must be strings")
                _validate_json(item, path=f"{path}.{key}", depth=depth + 1, seen=identities)
            return
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            sequence = cast(Sequence[object], value)
            if len(sequence) > 10_000:
                raise ValueError(f"{path} contains too many array items")
            for index, item in enumerate(sequence):
                _validate_json(
                    item,
                    path=f"{path}[{index}]",
                    depth=depth + 1,
                    seen=identities,
                )
            return
        raise ValueError(f"{path} contains non-JSON value {type(value).__name__}")
    finally:
        identities.discard(identity)
