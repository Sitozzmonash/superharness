"""Bounded thread-local working memory."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, field

from super_harness.context import ContextFragment, ContextKind


def _values() -> OrderedDict[str, object]:
    return OrderedDict()


@dataclass(slots=True)
class WorkingMemory:
    max_items: int = 64
    _values: OrderedDict[str, object] = field(default_factory=_values, repr=False)

    def __post_init__(self) -> None:
        if self.max_items < 1:
            raise ValueError("working-memory max_items must be positive")

    def set(self, key: str, value: object) -> None:
        if not key.strip():
            raise ValueError("working-memory key must be non-empty")
        self._values.pop(key, None)
        self._values[key] = value
        while len(self._values) > self.max_items:
            self._values.popitem(last=False)

    def get(self, key: str, default: object = None) -> object:
        if key not in self._values:
            return default
        value = self._values.pop(key)
        self._values[key] = value
        return value

    def delete(self, key: str) -> bool:
        return self._values.pop(key, None) is not None

    def clear(self) -> None:
        self._values.clear()

    def snapshot(self) -> Mapping[str, object]:
        return dict(self._values)

    def context(self, *, source: str = "working-memory") -> ContextFragment | None:
        if not self._values:
            return None
        content = "\n".join(f"{key}: {value}" for key, value in self._values.items())
        return ContextFragment(
            ContextKind.MEMORY, content, source, metadata={"items": len(self._values)}
        )
