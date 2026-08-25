"""Async model provider protocol."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from .types import ModelCapabilities, ModelRequest, ModelResponse, ModelStreamEvent


@runtime_checkable
class ModelProvider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def capabilities(self) -> ModelCapabilities: ...

    async def complete(self, request: ModelRequest) -> ModelResponse: ...

    def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]: ...

    async def aclose(self) -> None: ...
