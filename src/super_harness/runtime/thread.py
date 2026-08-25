"""Streaming-first in-memory Thread runtime."""

from __future__ import annotations

import asyncio
import copy
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, TypeVar
from uuid import uuid4

from super_harness.context import (
    ContextAssembler,
    ContextDebugEntry,
    ContextDebugSnapshot,
    ContextFragment,
    ContextKind,
    ContextSummary,
    extractive_summary,
    redact_text,
)
from super_harness.exceptions import HookError, ToolError
from super_harness.hooks import HookContext, HookEvent, HookRegistry
from super_harness.models import (
    Message,
    MessageRole,
    ModelProvider,
    ModelRequest,
    ModelResponse,
    ModelStreamEventType,
    ToolDefinition,
)
from super_harness.tools import ToolExecutor, ToolRegistry, ToolResult

from .events import Event
from .turn import Turn, TurnStatus

if TYPE_CHECKING:
    from super_harness.persistence import SQLiteThreadStore

    from .handle import TurnHandle

T = TypeVar("T")


def _message_list() -> list[Message]:
    return []


def _turn_list() -> list[Turn]:
    return []


def _summary_list() -> list[ContextSummary]:
    return []


def _metadata() -> dict[str, Any]:
    return {}


def _context() -> ContextAssembler:
    return ContextAssembler()


def _interrupts() -> set[str]:
    return set()


def _steering() -> dict[str, list[str]]:
    return {}


def _sync(operation: AsyncIterator[T]) -> list[T]:
    try:
        asyncio.get_running_loop()
    except RuntimeError:

        async def collect() -> list[T]:
            return [item async for item in operation]

        return asyncio.run(collect())
    raise RuntimeError("sync API cannot run inside an active event loop; use the async API")


@dataclass(slots=True)
class Thread:
    """Ordered conversation history and turns for one Agent session."""

    provider: ModelProvider
    instructions: str | None = None
    tool_registry: ToolRegistry | None = None
    tool_executor: ToolExecutor | None = None
    max_model_steps: int = 8
    context: ContextAssembler = field(default_factory=_context)
    store: SQLiteThreadStore | None = None
    archived: bool = False
    parent_thread_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=_metadata)
    summaries: list[ContextSummary] = field(default_factory=_summary_list)
    compaction_threshold_chars: int = 100_000
    compaction_retain_messages: int = 8
    hooks: HookRegistry | None = None
    _session_started: bool = field(default=False, repr=False)
    _interrupt_turn_ids: set[str] = field(default_factory=_interrupts, repr=False)
    _steering_by_turn: dict[str, list[str]] = field(default_factory=_steering, repr=False)
    _active_turn_id: str | None = field(default=None, repr=False)
    thread_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    messages: list[Message] = field(default_factory=_message_list)
    turns: list[Turn] = field(default_factory=_turn_list)

    def _request(
        self,
        *,
        tools: Sequence[ToolDefinition],
        output_schema: Mapping[str, Any] | None,
    ) -> ModelRequest:
        messages: list[Message] = []
        if self.instructions:
            messages.append(Message(MessageRole.DEVELOPER, self.instructions))
        messages.extend(self.context.messages())
        messages.extend(
            ContextFragment(
                ContextKind.SUMMARY,
                summary.content,
                f"summary:{summary.summary_id}",
            ).render()
            for summary in self.summaries
        )
        messages.extend(self.messages)
        definitions = list(tools)
        if self.tool_registry is not None:
            definitions.extend(self.tool_registry.definitions())
        return ModelRequest(messages, tools=definitions, output_schema=output_schema)

    async def astream(
        self,
        input: str,
        *,
        tools: Sequence[ToolDefinition] = (),
        output_schema: Mapping[str, Any] | None = None,
    ) -> AsyncIterator[Event]:
        if self.archived:
            raise RuntimeError("cannot run an archived thread")
        if self._active_turn_id is not None:
            raise RuntimeError("thread already has an active turn")
        if not input.strip():
            raise ValueError("turn input must be non-empty")
        if self.hooks is not None:
            if not self._session_started:
                await self.hooks.dispatch(
                    HookContext(HookEvent.SESSION_START, thread_id=self.thread_id)
                )
                self._session_started = True
            prompt = await self.hooks.dispatch(
                HookContext(
                    HookEvent.USER_PROMPT,
                    {"input": input},
                    thread_id=self.thread_id,
                )
            )
            if prompt.denied:
                raise HookError(prompt.deny_reason or "user prompt denied by hook")
            candidate_input = prompt.data.get("input")
            if isinstance(candidate_input, str):
                input = candidate_input
            if not input.strip():
                raise HookError("user prompt hook produced empty input")
        turn = Turn(input)
        self._active_turn_id = turn.turn_id
        self.turns.append(turn)
        self.messages.append(Message(MessageRole.USER, input))
        self.updated_at = datetime.now(UTC)
        turn.start()
        try:
            if self.hooks is not None:
                await self.hooks.dispatch(
                    HookContext(
                        HookEvent.TURN_START,
                        {"input": input},
                        self.thread_id,
                        turn.turn_id,
                    )
                )
            self._persist()
            yield Event("turn.started", thread_id=self.thread_id, turn_id=turn.turn_id)
            if self._history_characters() > self.compaction_threshold_chars:
                for event in await self.acompact():
                    yield event
            for step in range(1, self.max_model_steps + 1):
                for instruction in self._steering_by_turn.pop(turn.turn_id, []):
                    self.messages.append(
                        Message(
                            MessageRole.USER,
                            f"<steering>{instruction}</steering>",
                        )
                    )
                    yield Event(
                        "turn.steered",
                        thread_id=self.thread_id,
                        turn_id=turn.turn_id,
                        payload={"instruction": instruction},
                    )
                response: ModelResponse | None = None
                request = self._request(tools=tools, output_schema=output_schema)
                if self.hooks is not None:
                    before_model = await self.hooks.dispatch(
                        HookContext(
                            HookEvent.BEFORE_MODEL,
                            {"request": request, "step": step},
                            self.thread_id,
                            turn.turn_id,
                        )
                    )
                    if before_model.denied:
                        raise HookError(before_model.deny_reason or "model request denied by hook")
                    candidate_request = before_model.data.get("request")
                    if isinstance(candidate_request, ModelRequest):
                        request = candidate_request
                async for model_event in self.provider.stream(request):
                    if model_event.type is ModelStreamEventType.STARTED:
                        yield Event(
                            "model.started",
                            thread_id=self.thread_id,
                            turn_id=turn.turn_id,
                            payload={"provider": self.provider.name, "step": step},
                        )
                    elif model_event.type is ModelStreamEventType.TEXT_DELTA:
                        yield Event(
                            "model.text.delta",
                            thread_id=self.thread_id,
                            turn_id=turn.turn_id,
                            payload={"delta": model_event.delta, "step": step},
                        )
                    elif model_event.type is ModelStreamEventType.TOOL_CALL_DELTA:
                        yield Event(
                            "model.tool_call.delta",
                            thread_id=self.thread_id,
                            turn_id=turn.turn_id,
                            tool_call_id=model_event.tool_call_id,
                            payload={
                                "index": model_event.tool_call_index,
                                "name": model_event.tool_name,
                                "delta": model_event.delta,
                                "step": step,
                            },
                        )
                    elif model_event.type is ModelStreamEventType.COMPLETED:
                        response = model_event.response
                        if response is None:
                            raise RuntimeError("provider completed without a normalized response")
                        yield Event(
                            "model.completed",
                            thread_id=self.thread_id,
                            turn_id=turn.turn_id,
                            payload={
                                "response": response,
                                "usage": response.usage,
                                "tool_calls": response.tool_calls,
                                "step": step,
                            },
                        )
                        break
                if response is None:
                    raise RuntimeError("provider stream ended without a completed event")
                if self.hooks is not None:
                    await self.hooks.dispatch(
                        HookContext(
                            HookEvent.AFTER_MODEL,
                            {"request": request, "response": response, "step": step},
                            self.thread_id,
                            turn.turn_id,
                        )
                    )
                if response.tool_calls and self.tool_executor is not None:
                    self.messages.append(
                        Message(
                            MessageRole.ASSISTANT,
                            response.text,
                            tool_calls=response.tool_calls,
                        )
                    )
                    turn.status = TurnStatus.WAITING_TOOL
                    registry = self.tool_registry
                    parallel = len(response.tool_calls) > 1 and registry is not None
                    if parallel and registry is not None:
                        try:
                            parallel = all(
                                registry.get(call.name).metadata.supports_parallel
                                for call in response.tool_calls
                            )
                        except ToolError:
                            parallel = False
                    for call in response.tool_calls:
                        yield Event(
                            "tool.started",
                            thread_id=self.thread_id,
                            turn_id=turn.turn_id,
                            tool_call_id=call.call_id,
                            payload={"name": call.name, "arguments": call.arguments},
                        )
                    results: list[ToolResult]
                    if parallel:
                        results = await asyncio.gather(
                            *(self.tool_executor.execute(call) for call in response.tool_calls)
                        )
                    else:
                        results = []
                        for call in response.tool_calls:
                            results.append(await self.tool_executor.execute(call))
                    for call, result in zip(response.tool_calls, results, strict=True):
                        self.messages.append(
                            Message(
                                MessageRole.TOOL,
                                result.output,
                                name=result.name,
                                tool_call_id=result.call_id,
                            )
                        )
                        self._persist()
                        yield Event(
                            "tool.completed",
                            thread_id=self.thread_id,
                            turn_id=turn.turn_id,
                            tool_call_id=call.call_id,
                            payload={"result": result, "success": result.success},
                        )
                    turn.status = TurnStatus.RUNNING
                    continue
                turn.complete(response)
                if response.text or response.tool_calls:
                    self.messages.append(
                        Message(
                            MessageRole.ASSISTANT,
                            response.text,
                            tool_calls=response.tool_calls,
                        )
                    )
                self.updated_at = datetime.now(UTC)
                self._persist()
                if self.hooks is not None:
                    await self.hooks.dispatch(
                        HookContext(
                            HookEvent.TURN_END,
                            {"response": response, "status": turn.status},
                            self.thread_id,
                            turn.turn_id,
                        )
                    )
                yield Event(
                    "turn.completed",
                    thread_id=self.thread_id,
                    turn_id=turn.turn_id,
                    payload={"response": response},
                )
                break
            if turn.status in {TurnStatus.RUNNING, TurnStatus.WAITING_TOOL}:
                raise ToolError(f"tool loop exceeded maximum of {self.max_model_steps} model steps")
        except GeneratorExit:
            turn.status = TurnStatus.INTERRUPTED
            turn.error = "event stream consumer closed"
            turn.completed_at = datetime.now(UTC)
            self.updated_at = datetime.now(UTC)
            self._persist()
            raise
        except asyncio.CancelledError:
            if turn.turn_id in self._interrupt_turn_ids:
                turn.status = TurnStatus.INTERRUPTED
                turn.completed_at = datetime.now(UTC)
                self._interrupt_turn_ids.discard(turn.turn_id)
            else:
                turn.cancel()
            self.updated_at = datetime.now(UTC)
            self._persist()
            raise
        except Exception as exc:
            turn.fail(exc)
            self.updated_at = datetime.now(UTC)
            self._persist()
            if self.hooks is not None:
                await self.hooks.dispatch(
                    HookContext(
                        HookEvent.ERROR,
                        {"error": exc, "error_type": type(exc).__name__},
                        self.thread_id,
                        turn.turn_id,
                    )
                )
            yield Event(
                "turn.failed",
                thread_id=self.thread_id,
                turn_id=turn.turn_id,
                payload={"error_type": type(exc).__name__, "message": str(exc)},
            )
            raise
        finally:
            self._active_turn_id = None

    def _persist(self) -> None:
        if self.store is not None:
            self.store.save(self)

    def queue_steering(self, turn_id: str, instruction: str) -> None:
        self._steering_by_turn.setdefault(turn_id, []).append(instruction)

    def request_interrupt(self, turn_id: str) -> None:
        self._interrupt_turn_ids.add(turn_id)

    def start(
        self,
        input: str,
        *,
        tools: Sequence[ToolDefinition] = (),
        output_schema: Mapping[str, Any] | None = None,
    ) -> TurnHandle:
        from .handle import TurnHandle

        return TurnHandle(self, input, tools=tools, output_schema=output_schema)

    def _history_characters(self) -> int:
        return sum(len(message.content) for message in self.messages)

    def compact(
        self,
        summary: str | None = None,
        *,
        retain_messages: int | None = None,
    ) -> tuple[Event, Event]:
        retain = self.compaction_retain_messages if retain_messages is None else retain_messages
        if retain < 1:
            raise ValueError("compaction must retain at least one recent message")
        count = max(len(self.messages) - retain, 0)
        started = Event(
            "compaction.started",
            thread_id=self.thread_id,
            payload={"before_messages": len(self.messages), "summarized_messages": count},
        )
        if count:
            old = self.messages[:count]
            previous_count = sum(item.summarized_messages for item in self.summaries)
            previous_messages = [Message(MessageRole.USER, item.content) for item in self.summaries]
            content = summary or extractive_summary([*previous_messages, *old])
            self.summaries[:] = [ContextSummary(content, previous_count + count)]
            del self.messages[:count]
            self.updated_at = datetime.now(UTC)
            self._persist()
        completed = Event(
            "compaction.completed",
            thread_id=self.thread_id,
            payload={
                "after_messages": len(self.messages),
                "summary_id": self.summaries[-1].summary_id if count else None,
            },
        )
        return started, completed

    async def acompact(
        self,
        summary: str | None = None,
        *,
        retain_messages: int | None = None,
    ) -> tuple[Event, Event]:
        if self.hooks is not None:
            outcome = await self.hooks.dispatch(
                HookContext(
                    HookEvent.PRE_COMPACT,
                    {"summary": summary, "retain_messages": retain_messages},
                    self.thread_id,
                )
            )
            if outcome.denied:
                raise HookError(outcome.deny_reason or "compaction denied by hook")
            candidate_summary = outcome.data.get("summary")
            if candidate_summary is None or isinstance(candidate_summary, str):
                summary = candidate_summary
            candidate_retain = outcome.data.get("retain_messages")
            if candidate_retain is None or isinstance(candidate_retain, int):
                retain_messages = candidate_retain
        events = self.compact(summary, retain_messages=retain_messages)
        if self.hooks is not None:
            await self.hooks.dispatch(
                HookContext(
                    HookEvent.POST_COMPACT,
                    {"summary": self.summaries[-1] if self.summaries else None, "events": events},
                    self.thread_id,
                )
            )
        return events

    async def aclose(self) -> None:
        if self.hooks is not None and self._session_started:
            await self.hooks.dispatch(
                HookContext(HookEvent.SESSION_END, thread_id=self.thread_id)
            )
            self._session_started = False

    def debug_context(self) -> ContextDebugSnapshot:
        entries = tuple(
            ContextDebugEntry(
                fragment.kind,
                fragment.source,
                fragment.role,
                fragment.effective_priority,
                redact_text(fragment.content),
            )
            for fragment in self.context.ordered()
        ) + tuple(
            ContextDebugEntry(
                ContextKind.SUMMARY,
                f"summary:{summary.summary_id}",
                MessageRole.USER,
                70,
                redact_text(summary.content),
            )
            for summary in self.summaries
        )
        return ContextDebugSnapshot(
            self.thread_id,
            entries,
            len(self.messages),
            sum(len(entry.content) for entry in entries) + self._history_characters(),
        )

    def archive(self) -> None:
        self.archived = True
        self.updated_at = datetime.now(UTC)
        self._persist()

    def fork(self, *, thread_id: str | None = None) -> Thread:
        forked = Thread(
            provider=self.provider,
            instructions=self.instructions,
            tool_registry=self.tool_registry,
            tool_executor=self.tool_executor,
            max_model_steps=self.max_model_steps,
            context=ContextAssembler(self.context.max_chars, list(self.context.fragments)),
            store=self.store,
            thread_id=thread_id or str(uuid4()),
            parent_thread_id=self.thread_id,
            metadata=copy.deepcopy(self.metadata),
            messages=list(self.messages),
            turns=copy.deepcopy(self.turns),
            summaries=list(self.summaries),
            compaction_threshold_chars=self.compaction_threshold_chars,
            compaction_retain_messages=self.compaction_retain_messages,
            hooks=self.hooks,
        )
        forked._persist()
        return forked

    async def arun(
        self,
        input: str,
        *,
        tools: Sequence[ToolDefinition] = (),
        output_schema: Mapping[str, Any] | None = None,
    ) -> ModelResponse:
        response: ModelResponse | None = None
        async for event in self.astream(input, tools=tools, output_schema=output_schema):
            if event.type == "turn.completed":
                candidate = event.payload.get("response")
                if isinstance(candidate, ModelResponse):
                    response = candidate
        if response is None:
            raise RuntimeError("turn ended without a response")
        return response

    def stream(
        self,
        input: str,
        *,
        tools: Sequence[ToolDefinition] = (),
        output_schema: Mapping[str, Any] | None = None,
    ) -> Iterator[Event]:
        return iter(_sync(self.astream(input, tools=tools, output_schema=output_schema)))

    def run(
        self,
        input: str,
        *,
        tools: Sequence[ToolDefinition] = (),
        output_schema: Mapping[str, Any] | None = None,
    ) -> ModelResponse:
        response: ModelResponse | None = None
        for event in self.stream(input, tools=tools, output_schema=output_schema):
            if event.type == "turn.completed":
                candidate = event.payload.get("response")
                if isinstance(candidate, ModelResponse):
                    response = candidate
        if response is None:
            raise RuntimeError("turn ended without a response")
        return response
