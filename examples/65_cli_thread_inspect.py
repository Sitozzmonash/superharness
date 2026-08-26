"""Inspect a durable Thread without contacting its model provider."""

import os
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

from super_harness import Agent, SQLiteThreadStore
from super_harness.cli import main
from super_harness.models import (
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
    ModelStreamEventType,
)


class ExampleProvider:
    name = "example"
    capabilities = ModelCapabilities()

    async def complete(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse("saved")

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        yield ModelStreamEvent(ModelStreamEventType.STARTED)
        yield ModelStreamEvent(ModelStreamEventType.COMPLETED, response=ModelResponse("saved"))

    async def aclose(self) -> None:
        return None


with tempfile.TemporaryDirectory(prefix="super-harness-thread-example-") as temporary:
    project = Path(temporary)
    (project / ".git").mkdir()
    database = project / ".super-harness" / "threads.db"
    with SQLiteThreadStore(database) as store:
        thread = Agent(ExampleProvider(), store=store).thread()
        thread.run("persist this turn")
        thread_id = thread.thread_id
    previous = Path.cwd()
    try:
        os.chdir(project)
        assert main(["--json", "thread", "inspect", thread_id]) == 0
    finally:
        os.chdir(previous)
