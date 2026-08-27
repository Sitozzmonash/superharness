"""Explicit observable model-provider fallback chains."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from super_harness.exceptions import ModelError

if TYPE_CHECKING:
    from super_harness.runtime.events import EventObserver

from .base import ModelProvider
from .types import (
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
    ModelStreamEventType,
)

RetryPredicate = Callable[[Exception], bool]


def _retryable_error(error: Exception) -> bool:
    return isinstance(error, (ModelError, TimeoutError))


@dataclass(frozen=True, slots=True)
class FallbackPolicy:
    timeout: float = 60.0
    retry_if: RetryPredicate = _retryable_error

    def __post_init__(self) -> None:
        if self.timeout <= 0:
            raise ValueError("fallback timeout must be positive")


class FallbackProvider:
    """Try configured providers in order without silent switching."""

    def __init__(
        self,
        providers: Sequence[ModelProvider],
        *,
        policy: FallbackPolicy | None = None,
        observer: EventObserver | None = None,
    ) -> None:
        if not providers:
            raise ValueError("fallback chain requires at least one provider")
        self.providers = tuple(providers)
        self.policy = policy or FallbackPolicy()
        self.observer = observer

    @property
    def name(self) -> str:
        return "fallback[" + ",".join(item.name for item in self.providers) + "]"

    @property
    def model(self) -> str | None:
        return cast(str | None, getattr(self.providers[0], "model", None))

    @property
    def capabilities(self) -> ModelCapabilities:
        values = [item.capabilities for item in self.providers]
        wire = set(values[0].wire_apis)
        for item in values[1:]:
            wire.intersection_update(item.wire_apis)
        return ModelCapabilities(
            streaming=all(item.streaming for item in values),
            tools=all(item.tools for item in values),
            structured_output=all(item.structured_output for item in values),
            reasoning=all(item.reasoning for item in values),
            parallel_tool_calls=all(item.parallel_tool_calls for item in values),
            wire_apis=tuple(sorted(wire)),
        )

    async def complete(self, request: ModelRequest) -> ModelResponse:
        failures: list[dict[str, str]] = []
        for index, provider in enumerate(self.providers):
            await self._event("provider.attempt.started", provider, index)
            try:
                async with asyncio.timeout(self.policy.timeout):
                    response = await provider.complete(request)
                await self._event("provider.attempt.completed", provider, index)
                return response
            except Exception as exc:
                normalized = self._normalized(exc, provider)
                failures.append({"provider": provider.name, "error": type(normalized).__name__})
                await self._event("provider.attempt.failed", provider, index, normalized)
                if index + 1 >= len(self.providers) or not self.policy.retry_if(exc):
                    raise normalized from exc
                await self._event(
                    "provider.fallback.selected",
                    self.providers[index + 1],
                    index + 1,
                    previous=provider.name,
                )
        raise ModelError("provider fallback exhausted", details={"attempts": failures})

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        yield ModelStreamEvent(ModelStreamEventType.STARTED)
        for index, provider in enumerate(self.providers):
            visible = False
            completed = False
            await self._event("provider.attempt.started", provider, index)
            try:
                async with asyncio.timeout(self.policy.timeout):
                    async for event in provider.stream(request):
                        if event.type is ModelStreamEventType.STARTED:
                            continue
                        if event.type in {
                            ModelStreamEventType.TEXT_DELTA,
                            ModelStreamEventType.TOOL_CALL_DELTA,
                        }:
                            visible = True
                        if event.type is ModelStreamEventType.COMPLETED:
                            completed = True
                            visible = True
                        yield event
                if not completed:
                    raise ModelError(
                        "provider stream ended without a completed event",
                        details={"provider": provider.name},
                    )
                await self._event("provider.attempt.completed", provider, index)
                return
            except Exception as exc:
                normalized = self._normalized(exc, provider)
                await self._event("provider.attempt.failed", provider, index, normalized)
                if visible:
                    raise ModelError(
                        "provider stream failed after visible output; fallback is unsafe",
                        details={"provider": provider.name},
                    ) from exc
                if index + 1 >= len(self.providers) or not self.policy.retry_if(exc):
                    raise normalized from exc
                await self._event(
                    "provider.fallback.selected",
                    self.providers[index + 1],
                    index + 1,
                    previous=provider.name,
                )

    async def aclose(self) -> None:
        results = await asyncio.gather(
            *(provider.aclose() for provider in self.providers),
            return_exceptions=True,
        )
        failure = next((item for item in results if isinstance(item, Exception)), None)
        if failure is not None:
            raise ModelError("provider fallback close failed") from failure

    def _normalized(self, error: Exception, provider: ModelProvider) -> ModelError:
        if isinstance(error, ModelError):
            return error
        if isinstance(error, TimeoutError):
            return ModelError(
                "model provider attempt timed out",
                details={"provider": provider.name, "timeout": self.policy.timeout},
            )
        return ModelError(
            "model provider attempt failed",
            details={"provider": provider.name, "error_class": type(error).__name__},
        )

    async def _event(
        self,
        event_type: str,
        provider: ModelProvider,
        index: int,
        error: Exception | None = None,
        *,
        previous: str | None = None,
    ) -> None:
        if self.observer is None:
            return
        from super_harness.runtime.events import Event

        payload: dict[str, object] = {
            "provider": provider.name,
            "attempt": index + 1,
        }
        if error is not None:
            payload["error_class"] = type(error).__name__
        if previous is not None:
            payload["previous_provider"] = previous
        result = self.observer.observe(Event(event_type, payload=payload))
        if inspect.isawaitable(result):
            await cast(Awaitable[object], result)
