"""Attach one observer to human console and JSONL outputs."""

import asyncio
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

from super_harness import Agent, Observability, StructuredLogger
from super_harness.models import (
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
    ModelStreamEventType,
)


class DemoProvider:
    name = "demo"
    model = "demo-model"
    capabilities = ModelCapabilities()

    async def complete(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse("unused")

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        yield ModelStreamEvent(ModelStreamEventType.STARTED)
        yield ModelStreamEvent(
            ModelStreamEventType.COMPLETED,
            response=ModelResponse("observable result"),
        )

    async def aclose(self) -> None:
        return None


async def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "events.jsonl"
        observer = Observability(logger=StructuredLogger(jsonl=path))
        await Agent(DemoProvider(), observer=observer).arun("run")
        await observer.aclose()
        print("jsonl records:", len(path.read_text(encoding="utf-8").splitlines()))


if __name__ == "__main__":
    asyncio.run(main())
