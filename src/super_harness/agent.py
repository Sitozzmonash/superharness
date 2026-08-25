"""Public Agent API."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable, Iterator, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from super_harness.context import AgentsMdLoader, ContextAssembler, ContextFragment
from super_harness.hooks import HookRegistry
from super_harness.models import ModelProvider, ModelResponse, ToolDefinition
from super_harness.persistence import SQLiteThreadStore
from super_harness.runtime.events import Event
from super_harness.runtime.thread import Thread
from super_harness.runtime.turn import TurnStatus
from super_harness.tools import ApprovalPolicy, Tool, ToolExecutor, ToolRegistry


class Agent:
    """A configured agent that creates independent conversational Threads."""

    def __init__(
        self,
        provider: ModelProvider,
        *,
        instructions: str | None = None,
        tools: Iterable[Tool] = (),
        approval: ApprovalPolicy | None = None,
        hooks: HookRegistry | None = None,
        max_model_steps: int = 8,
        context: Iterable[ContextFragment] = (),
        cwd: str | None = None,
        agents_loader: AgentsMdLoader | None = None,
        store: SQLiteThreadStore | None = None,
        compaction_threshold_chars: int = 100_000,
    ) -> None:
        if max_model_steps < 1:
            raise ValueError("max_model_steps must be positive")
        self.provider = provider
        self.instructions = instructions
        self.tool_registry = ToolRegistry(tools)
        self.hooks = hooks
        self.tool_executor = (
            ToolExecutor(self.tool_registry, approval=approval, hooks=hooks)
            if self.tool_registry.list()
            else None
        )
        self.max_model_steps = max_model_steps
        self.context = ContextAssembler()
        self.context.extend(context)
        if cwd is not None:
            self.context.extend((agents_loader or AgentsMdLoader()).load(cwd))
        self.store = store
        self.compaction_threshold_chars = compaction_threshold_chars

    def thread(self) -> Thread:
        thread = Thread(
            provider=self.provider,
            instructions=self.instructions,
            tool_registry=self.tool_registry,
            tool_executor=self.tool_executor,
            max_model_steps=self.max_model_steps,
            context=ContextAssembler(self.context.max_chars, list(self.context.fragments)),
            store=self.store,
            compaction_threshold_chars=self.compaction_threshold_chars,
            hooks=self.hooks,
        )
        if self.store is not None:
            self.store.save(thread)
        return thread

    def resume(self, thread_id: str) -> Thread:
        if self.store is None:
            raise RuntimeError("Agent.resume requires a SQLiteThreadStore")
        snapshot = self.store.load(thread_id)
        thread = Thread(
            provider=self.provider,
            instructions=snapshot.instructions,
            tool_registry=self.tool_registry,
            tool_executor=self.tool_executor,
            max_model_steps=self.max_model_steps,
            context=ContextAssembler(self.context.max_chars, list(self.context.fragments)),
            store=self.store,
            thread_id=snapshot.thread_id,
            created_at=snapshot.created_at,
            updated_at=snapshot.updated_at,
            archived=snapshot.archived,
            parent_thread_id=snapshot.parent_thread_id,
            metadata=dict(snapshot.metadata),
            messages=list(snapshot.messages),
            turns=list(snapshot.turns),
            summaries=list(snapshot.summaries),
            compaction_threshold_chars=self.compaction_threshold_chars,
            hooks=self.hooks,
        )
        for turn in thread.turns:
            if turn.status.value in {"pending", "running", "waiting_tool"}:
                turn.status = TurnStatus.INTERRUPTED
                turn.error = "interrupted before resume"
                turn.completed_at = datetime.now(UTC)
        self.store.save(thread)
        return thread

    def fork(self, thread_id: str) -> Thread:
        return self.resume(thread_id).fork()

    async def arun(
        self,
        input: str,
        *,
        tools: Sequence[ToolDefinition] = (),
        output_schema: Mapping[str, Any] | None = None,
    ) -> ModelResponse:
        return await self.thread().arun(input, tools=tools, output_schema=output_schema)

    def run(
        self,
        input: str,
        *,
        tools: Sequence[ToolDefinition] = (),
        output_schema: Mapping[str, Any] | None = None,
    ) -> ModelResponse:
        return self.thread().run(input, tools=tools, output_schema=output_schema)

    def astream(
        self,
        input: str,
        *,
        tools: Sequence[ToolDefinition] = (),
        output_schema: Mapping[str, Any] | None = None,
    ) -> AsyncIterator[Event]:
        return self.thread().astream(input, tools=tools, output_schema=output_schema)

    def stream(
        self,
        input: str,
        *,
        tools: Sequence[ToolDefinition] = (),
        output_schema: Mapping[str, Any] | None = None,
    ) -> Iterator[Event]:
        return self.thread().stream(input, tools=tools, output_schema=output_schema)

    async def aclose(self) -> None:
        await self.provider.aclose()
