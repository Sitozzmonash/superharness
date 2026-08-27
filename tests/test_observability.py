from __future__ import annotations

import asyncio
import io
import json
import threading
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from super_harness import (
    Agent,
    AgentManager,
    CostEstimator,
    Edge,
    Event,
    HTTPRAGProvider,
    MetricsRegistry,
    ModelPrice,
    Observability,
    OpenTelemetryExporter,
    SecretRedactor,
    SecretValue,
    SpanStatus,
    SpawnRequest,
    StructuredLogger,
    StructuredLogRecord,
    TraceSpan,
    Workflow,
    WorkflowEngine,
)
from super_harness.models import (
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
    ModelStreamEventType,
    Usage,
)
from super_harness.orchestration import Node


class ObservedProvider:
    name = "observed"
    model = "observed-model"
    capabilities = ModelCapabilities()

    async def complete(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse("unused")

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        yield ModelStreamEvent(ModelStreamEventType.STARTED)
        yield ModelStreamEvent(
            ModelStreamEventType.TEXT_DELTA,
            delta="private output sk-abcdefghijklmnop",
        )
        yield ModelStreamEvent(
            ModelStreamEventType.COMPLETED,
            response=ModelResponse(
                "api_key=should-never-appear",
                usage=Usage(100, 50, 150),
            ),
        )

    async def aclose(self) -> None:
        return None


class FailingObservedProvider(ObservedProvider):
    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        yield ModelStreamEvent(ModelStreamEventType.STARTED)
        raise RuntimeError("api_key=provider-secret")


def test_secret_redactor_handles_patterns_nested_values_cycles_and_bounds() -> None:
    configured = "custom-value-123"
    cycle: list[object] = []
    cycle.append(cycle)
    redactor = SecretRedactor(
        secrets=[configured],
        secret_keys=["private-field"],
        custom=[lambda value: value],
        max_depth=4,
        max_items=3,
    )
    value = {
        "api_key": "plain-key",
        "authorization": "Bearer abc.def.ghi",
        "nested": [
            f"token={configured}",
            "sk-abcdefghijklmnop",
            "ghp_abcdefghijklmnop",
            "ignored fourth item",
        ],
        "private-field": "private",
        "cycle": cycle,
        "wrapped": SecretValue("wrapped-secret"),
    }

    serialized = json.dumps(redactor.redact(value))

    for secret in (
        configured,
        "plain-key",
        "abc.def.ghi",
        "sk-abcdefghijklmnop",
        "ghp_abcdefghijklmnop",
        "private",
        "wrapped-secret",
    ):
        assert secret not in serialized
    assert "********" in serialized
    assert "<truncated>" in serialized


def test_structured_logger_writes_human_and_jsonl_without_secret(tmp_path: Path) -> None:
    console = io.StringIO()
    path = tmp_path / "events.jsonl"
    redactor = SecretRedactor()
    details = redactor.redact({"token": "raw-secret", "message": "Bearer raw-secret"})
    logger = StructuredLogger(console=console, jsonl=path)
    logger.log(
        StructuredLogRecord(
            "INFO",
            "tool.completed",
            thread_id="thread-1",
            duration_ms=12.5,
            details=details,
        )
    )
    logger.close()

    human = console.getvalue()
    machine = path.read_text(encoding="utf-8")
    assert "tool.completed" in human and "duration_ms=12.500" in human
    assert json.loads(machine)["details"]["token"] == "********"
    assert "raw-secret" not in human + machine


@pytest.mark.asyncio
async def test_agent_observer_builds_trace_metrics_cost_and_omits_content() -> None:
    console = io.StringIO()
    jsonl = io.StringIO()
    metrics = MetricsRegistry(costs=CostEstimator({"observed-model": ModelPrice(2.0, 4.0)}))
    observer = Observability(
        logger=StructuredLogger(console=console, jsonl=jsonl),
        metrics=metrics,
    )
    response = await Agent(ObservedProvider(), observer=observer).arun("secret user prompt")

    assert response.usage == Usage(100, 50, 150)
    snapshot = metrics.snapshot()
    assert snapshot.counters["super_harness.tokens.input"] == 100
    assert snapshot.counters["super_harness.tokens.output"] == 50
    assert snapshot.estimated_cost_usd == pytest.approx(0.0004)
    spans = observer.tracer.spans()
    assert {span.category for span in spans} >= {"thread", "turn", "model"}
    trace_id = next(span.trace_id for span in spans if span.category == "turn")
    tree = observer.tracer.tree(trace_id)
    assert "turn" in tree and "model" in tree
    output = console.getvalue() + jsonl.getvalue()
    assert "model.text.delta" not in output
    assert "secret user prompt" not in output
    assert "private output" not in output
    assert "should-never-appear" not in output
    completed = [json.loads(line) for line in jsonl.getvalue().splitlines()]
    model = next(item for item in completed if item["event"] == "model.completed")
    assert model["provider"] == "observed"
    assert model["model"] == "observed-model"
    assert model["details"]["response"] == "<omitted>"


@pytest.mark.asyncio
async def test_workflow_and_agent_manager_share_one_observer() -> None:
    jsonl = io.StringIO()
    observer = Observability(logger=StructuredLogger(console=None, jsonl=jsonl))

    def factory(_: SpawnRequest) -> Agent:
        return Agent(ObservedProvider())

    manager = AgentManager(
        Agent(ObservedProvider()),
        factory,
        event_listener=observer.observe,
    )
    child = await manager.spawn_agent(manager.root_agent_id, "work")
    await manager.wait_all([child.agent_id], timeout=1)
    workflow = Workflow(
        "observed-flow",
        [Node("a", lambda _: 1), Node("b", lambda context: context.results["a"].value)],
        [Edge("a", "b")],
    )
    run = await WorkflowEngine(event_listener=observer.observe).run(workflow)

    assert run.output == 1
    event_names = {json.loads(line)["event"] for line in jsonl.getvalue().splitlines()}
    assert event_names >= {
        "agent.spawned",
        "agent.completed",
        "workflow.started",
        "node.completed",
        "workflow.completed",
    }
    snapshot = observer.metrics.snapshot()
    assert snapshot.gauges["super_harness.agents.active"] == 0
    assert snapshot.histograms["super_harness.duration_ms.node"]


@pytest.mark.asyncio
async def test_model_failure_closes_span_and_redacts_error() -> None:
    jsonl = io.StringIO()
    observer = Observability(logger=StructuredLogger(console=None, jsonl=jsonl))

    with pytest.raises(RuntimeError, match="provider-secret"):
        await Agent(FailingObservedProvider(), observer=observer).arun("fail")

    records = [json.loads(line) for line in jsonl.getvalue().splitlines()]
    failed = next(item for item in records if item["event"] == "model.failed")
    assert failed["error_class"] == "RuntimeError"
    assert "provider-secret" not in jsonl.getvalue()
    model_spans = [span for span in observer.tracer.spans() if span.category == "model"]
    assert model_spans[-1].status == SpanStatus.ERROR


@pytest.mark.asyncio
async def test_rag_boundary_emits_content_free_correlated_observations() -> None:
    async def retrieve(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content) == {"query": "private query", "top_n": 1}
        return httpx.Response(200, json={"results": [{"text": "private document"}]})

    jsonl = io.StringIO()
    observer = Observability(logger=StructuredLogger(console=None, jsonl=jsonl))
    client = httpx.AsyncClient(transport=httpx.MockTransport(retrieve))
    provider = HTTPRAGProvider("https://rag.test", client=client, observer=observer)
    try:
        documents = await provider.retrieve("private query", top_n=1)
    finally:
        await client.aclose()

    assert documents[0].text == "private document"
    output = jsonl.getvalue()
    assert "private query" not in output and "private document" not in output
    records = [json.loads(line) for line in output.splitlines()]
    assert [item["event"] for item in records] == ["rag.started", "rag.completed"]
    assert records[0]["details"]["operation_id"] == records[1]["details"]["operation_id"]
    rag_span = next(span for span in observer.tracer.spans() if span.category == "rag")
    assert rag_span.status == SpanStatus.OK and rag_span.duration_ms is not None


class _FakeOTELSpan:
    def __init__(self) -> None:
        self.attributes: dict[str, Any] = {}
        self.end_time: int | None = None

    def set_attribute(self, name: str, value: Any) -> None:
        self.attributes[name] = value

    def end(self, *, end_time: int) -> None:
        self.end_time = end_time


class _FakeOTELTracer:
    def __init__(self) -> None:
        self.span = _FakeOTELSpan()
        self.start: dict[str, Any] = {}

    def start_span(self, name: str, **kwargs: Any) -> _FakeOTELSpan:
        self.start = {"name": name, **kwargs}
        return self.span


def test_optional_otel_exporter_uses_injected_tracer_without_dependency() -> None:
    tracer = _FakeOTELTracer()
    exporter = OpenTelemetryExporter(tracer=tracer)
    started = datetime.now(UTC)
    span = TraceSpan(
        "tool",
        "tool",
        started_at=started,
        completed_at=started + timedelta(milliseconds=5),
        status=SpanStatus.OK,
        attributes={"tool": "read"},
    )

    exporter.export_span(span)

    assert tracer.start["name"] == "tool"
    assert tracer.span.attributes["super_harness.status"] == "ok"
    assert tracer.span.end_time is not None


def test_metrics_validation_and_concurrent_logging_load() -> None:
    metrics = MetricsRegistry()
    with pytest.raises(ValueError, match="invalid metric"):
        metrics.counter("bad metric")
    with pytest.raises(ValueError, match="negative"):
        metrics.counter("valid.metric", -1)

    output = io.StringIO()
    logger = StructuredLogger(console=None, jsonl=output)

    def worker(worker_id: int) -> None:
        for index in range(100):
            logger.log(
                StructuredLogRecord(
                    "INFO",
                    "load.event",
                    details={"worker": worker_id, "index": index},
                )
            )

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    lines = output.getvalue().splitlines()
    assert len(lines) == 800
    assert all(json.loads(line)["event"] == "load.event" for line in lines)


@pytest.mark.asyncio
async def test_observer_handles_500_events_concurrently_without_losing_metrics() -> None:
    observer = Observability(logger=StructuredLogger(console=None, jsonl=None))

    async def emit(offset: int) -> None:
        for index in range(50):
            await observer.observe(
                Event("load.completed", payload={"offset": offset, "index": index})
            )

    await asyncio.gather(*(emit(index) for index in range(10)))

    snapshot = observer.metrics.snapshot()
    assert snapshot.counters["super_harness.events.load.completed"] == 500
