"""Ordered, time-bounded hook registration and dispatch."""

from __future__ import annotations

import asyncio
import inspect
import warnings
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import perf_counter
from typing import cast

from super_harness.exceptions import HookError

from .models import HookContext, HookEvent, HookFailurePolicy, HookOutcome, HookResult, HookTrace

HookValue = HookResult | None
HookCallable = Callable[[HookContext], HookValue | Awaitable[HookValue]]
HookTraceSink = Callable[[HookTrace], None]

_DENIABLE_EVENTS = frozenset(
    {HookEvent.USER_PROMPT, HookEvent.BEFORE_MODEL, HookEvent.PRE_TOOL_USE, HookEvent.PRE_COMPACT}
)


@dataclass(frozen=True, slots=True)
class HookRegistration:
    event: HookEvent
    handler: HookCallable
    name: str
    source: str = "runtime"
    priority: int = 100
    timeout: float = 10.0
    failure_policy: HookFailurePolicy = HookFailurePolicy.WARN
    allow_modify: bool = False

    def __post_init__(self) -> None:
        if not self.name.strip() or self.timeout <= 0:
            raise ValueError("hook name must be non-empty and timeout positive")


class HookRegistry:
    def __init__(self, *, trace_sink: HookTraceSink | None = None) -> None:
        self._hooks: dict[HookEvent, list[HookRegistration]] = {}
        self.trace_sink = trace_sink

    def register(
        self,
        event: HookEvent,
        handler: HookCallable,
        *,
        name: str | None = None,
        source: str = "runtime",
        priority: int = 100,
        timeout: float = 10.0,
        failure_policy: HookFailurePolicy = HookFailurePolicy.WARN,
        allow_modify: bool = False,
    ) -> HookRegistration:
        registration = HookRegistration(
            event,
            handler,
            name or getattr(handler, "__name__", "hook"),
            source,
            priority,
            timeout,
            failure_policy,
            allow_modify,
        )
        bucket = self._hooks.setdefault(event, [])
        if any(item.name == registration.name and item.source == source for item in bucket):
            raise HookError(f"hook {source}:{registration.name} is already registered")
        bucket.append(registration)
        bucket.sort(key=lambda item: (item.priority, item.source, item.name))
        return registration

    def unregister(self, event: HookEvent, name: str, *, source: str = "runtime") -> None:
        bucket = self._hooks.get(event, [])
        retained = [item for item in bucket if (item.name, item.source) != (name, source)]
        if len(retained) == len(bucket):
            raise HookError(f"unknown hook {source}:{name}")
        self._hooks[event] = retained

    def list(self, event: HookEvent | None = None) -> tuple[HookRegistration, ...]:
        if event is not None:
            return tuple(self._hooks.get(event, ()))
        return tuple(item for event_name in HookEvent for item in self._hooks.get(event_name, ()))

    async def dispatch(self, context: HookContext) -> HookOutcome:
        data = dict(context.data)
        traces: list[HookTrace] = []
        for item in self._hooks.get(context.event, ()):
            started = perf_counter()
            try:
                raw = item.handler(
                    HookContext(
                        context.event, data, context.thread_id, context.turn_id, item.source
                    )
                )
                result = await asyncio.wait_for(_resolve(raw), item.timeout)
                if result is not None and result.updates:
                    if not item.allow_modify:
                        raise HookError(f"hook {item.name!r} is not allowed to modify this event")
                    data.update(result.updates)
                denied = result is not None and result.deny_reason is not None
                if denied and context.event not in _DENIABLE_EVENTS:
                    raise HookError(f"event {context.event.value!r} cannot be denied")
                trace = HookTrace(
                    context.event,
                    item.name,
                    item.source,
                    True,
                    (perf_counter() - started) * 1_000,
                    denied,
                )
                self._trace(trace)
                traces.append(trace)
                if denied:
                    return HookOutcome(
                        data, tuple(traces), True, cast(HookResult, result).deny_reason
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                warning = f"{type(exc).__name__}: {exc}"
                trace = HookTrace(
                    context.event,
                    item.name,
                    item.source,
                    False,
                    (perf_counter() - started) * 1_000,
                    warning=warning,
                )
                self._trace(trace)
                traces.append(trace)
                if item.failure_policy is HookFailurePolicy.FAIL_CLOSED:
                    raise HookError(
                        f"hook {item.source}:{item.name} failed closed",
                        details={"event": context.event.value, "error_type": type(exc).__name__},
                    ) from exc
                if item.failure_policy is HookFailurePolicy.WARN:
                    warnings.warn(
                        f"hook {item.source}:{item.name} failed: {warning}",
                        RuntimeWarning,
                        stacklevel=2,
                    )
        return HookOutcome(data, tuple(traces))

    def _trace(self, trace: HookTrace) -> None:
        if self.trace_sink is not None:
            self.trace_sink(trace)


async def _resolve(value: HookValue | Awaitable[HookValue]) -> HookValue:
    if inspect.isawaitable(value):
        return await value
    return value
