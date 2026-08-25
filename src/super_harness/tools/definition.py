"""Typed Python tool definitions and decorator."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, cast, get_type_hints, overload

from pydantic import BaseModel, ConfigDict, ValidationError, create_model

from super_harness.exceptions import ToolValidationError
from super_harness.models import ToolDefinition

ToolCallable = Callable[..., object]


def _empty_extra() -> Mapping[str, Any]:
    return {}


@dataclass(frozen=True, slots=True)
class ToolMetadata:
    namespace: str | None = None
    source: str = "runtime"
    risk: str = "low"
    timeout: float = 30.0
    max_output_chars: int = 20_000
    supports_parallel: bool = False
    deferred: bool = False
    extra: Mapping[str, Any] = field(default_factory=_empty_extra)

    def __post_init__(self) -> None:
        if self.timeout <= 0:
            raise ValueError("tool timeout must be positive")
        if self.max_output_chars < 100:
            raise ValueError("tool output limit must be at least 100 characters")
        object.__setattr__(self, "extra", MappingProxyType(dict(self.extra)))


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    description: str
    input_model: type[BaseModel]
    handler: ToolCallable
    metadata: ToolMetadata = field(default_factory=ToolMetadata)

    @property
    def qualified_name(self) -> str:
        if self.metadata.namespace:
            return f"{self.metadata.namespace}.{self.name}"
        return self.name

    def provider_definition(self) -> ToolDefinition:
        return ToolDefinition(
            self.qualified_name,
            self.description,
            self.input_model.model_json_schema(),
        )

    def validate(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        try:
            model = self.input_model.model_validate(dict(arguments))
        except ValidationError as exc:
            raise ToolValidationError(
                f"invalid arguments for tool {self.qualified_name}",
                details={"tool": self.qualified_name, "errors": exc.errors(include_url=False)},
            ) from exc
        return model.model_dump()

    async def invoke(self, arguments: Mapping[str, Any]) -> object:
        values = self.validate(arguments)
        if inspect.iscoroutinefunction(self.handler):
            result = self.handler(**values)
            return await cast(Awaitable[object], result)
        return await asyncio.to_thread(self.handler, **values)


def _argument_model(function: ToolCallable, name: str) -> type[BaseModel]:
    signature = inspect.signature(function)
    hints = get_type_hints(function)
    fields: dict[str, tuple[Any, Any]] = {}
    for parameter_name, parameter in signature.parameters.items():
        if parameter.kind in {parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD}:
            raise TypeError("tool functions cannot use *args or **kwargs")
        annotation = hints.get(parameter_name)
        if annotation is None:
            raise TypeError(f"tool parameter {parameter_name!r} must have a type annotation")
        default = parameter.default
        if default is inspect.Parameter.empty:
            default = ...
        fields[parameter_name] = (annotation, default)
    model_factory = cast(Callable[..., type[BaseModel]], create_model)
    return model_factory(
        f"{name.title().replace('_', '')}Arguments",
        __config__=ConfigDict(extra="forbid"),
        **fields,
    )


def _build_tool(
    function: ToolCallable,
    *,
    name: str | None,
    description: str | None,
    namespace: str | None,
    source: str,
    risk: str,
    timeout: float,
    max_output_chars: int,
    supports_parallel: bool,
    deferred: bool,
) -> Tool:
    tool_name = name or function.__name__
    if not tool_name or not tool_name.strip():
        raise ValueError("tool name must be non-empty")
    tool_description = description or inspect.getdoc(function) or tool_name
    metadata = ToolMetadata(
        namespace=namespace,
        source=source,
        risk=risk,
        timeout=timeout,
        max_output_chars=max_output_chars,
        supports_parallel=supports_parallel,
        deferred=deferred,
    )
    return Tool(
        tool_name,
        tool_description,
        _argument_model(function, tool_name),
        function,
        metadata,
    )


@overload
def tool(
    function: ToolCallable,
    *,
    name: str | None = None,
    description: str | None = None,
    namespace: str | None = None,
    source: str = "runtime",
    risk: str = "low",
    timeout: float = 30.0,
    max_output_chars: int = 20_000,
    supports_parallel: bool = False,
    deferred: bool = False,
) -> Tool: ...


@overload
def tool(
    function: None = None,
    *,
    name: str | None = None,
    description: str | None = None,
    namespace: str | None = None,
    source: str = "runtime",
    risk: str = "low",
    timeout: float = 30.0,
    max_output_chars: int = 20_000,
    supports_parallel: bool = False,
    deferred: bool = False,
) -> Callable[[ToolCallable], Tool]: ...


def tool(
    function: ToolCallable | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
    namespace: str | None = None,
    source: str = "runtime",
    risk: str = "low",
    timeout: float = 30.0,
    max_output_chars: int = 20_000,
    supports_parallel: bool = False,
    deferred: bool = False,
) -> Tool | Callable[[ToolCallable], Tool]:
    """Decorate a typed sync or async callable as a model-visible tool."""

    def decorate(candidate: ToolCallable) -> Tool:
        return _build_tool(
            candidate,
            name=name,
            description=description,
            namespace=namespace,
            source=source,
            risk=risk,
            timeout=timeout,
            max_output_chars=max_output_chars,
            supports_parallel=supports_parallel,
            deferred=deferred,
        )

    if function is None:
        return decorate
    return decorate(function)
