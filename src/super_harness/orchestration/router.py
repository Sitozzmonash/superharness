"""Provider-neutral, observable rule routing."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, Generic, TypeVar, cast

from super_harness.exceptions import WorkflowError
from super_harness.runtime.events import Event, EventObserver

T = TypeVar("T")
RoutePredicate = Callable[[T, Mapping[str, Any]], Any]


def _metadata() -> Mapping[str, Any]:
    return {}


@dataclass(frozen=True, slots=True)
class Route(Generic[T]):
    name: str
    target: str
    predicate: RoutePredicate[T]
    priority: int = 100
    metadata: Mapping[str, Any] = field(default_factory=_metadata)

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.target.strip() or not callable(self.predicate):
            raise ValueError("route name, target, and predicate are required")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class RouteDecision:
    route: str
    target: str
    matched: bool
    reason: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: Mapping[str, Any] = field(default_factory=_metadata)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


class Router(Generic[T]):
    def __init__(
        self,
        routes: Sequence[Route[T]],
        *,
        default: str | None = None,
        observer: EventObserver | None = None,
    ) -> None:
        names = [item.name for item in routes]
        if len(names) != len(set(names)):
            raise ValueError("route names must be unique")
        self.routes = tuple(sorted(routes, key=lambda item: (item.priority, item.name)))
        self.default = default
        self.observer = observer

    async def aroute(
        self,
        value: T,
        *,
        context: Mapping[str, Any] | None = None,
    ) -> RouteDecision:
        safe_context = MappingProxyType(dict(context or {}))
        for route in self.routes:
            result = route.predicate(value, safe_context)
            matched_value: object = await result if inspect.isawaitable(result) else result
            if not isinstance(matched_value, bool):
                raise WorkflowError(f"route predicate {route.name!r} did not return bool")
            if matched_value:
                decision = RouteDecision(
                    route.name,
                    route.target,
                    True,
                    "predicate matched",
                    metadata=route.metadata,
                )
                await self._observe(decision)
                return decision
        if self.default is None:
            raise WorkflowError("router found no matching route and has no default")
        decision = RouteDecision("default", self.default, False, "no predicate matched")
        await self._observe(decision)
        return decision

    def route(
        self,
        value: T,
        *,
        context: Mapping[str, Any] | None = None,
    ) -> RouteDecision:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.aroute(value, context=context))
        raise RuntimeError("Router.route cannot run inside an active event loop; use aroute")

    async def _observe(self, decision: RouteDecision) -> None:
        if self.observer is None:
            return
        result = self.observer.observe(
            Event(
                "route.selected",
                payload={
                    "route": decision.route,
                    "target": decision.target,
                    "matched": decision.matched,
                    "reason": decision.reason,
                    "metadata": dict(decision.metadata),
                },
            )
        )
        if inspect.isawaitable(result):
            await cast(Awaitable[object], result)
