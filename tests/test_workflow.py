from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from super_harness.exceptions import WorkflowError
from super_harness.orchestration import (
    Edge,
    JSONWorkflowStore,
    Node,
    NodeKind,
    NodeOutput,
    NodeResult,
    NodeStatus,
    RetryPolicy,
    Workflow,
    WorkflowContext,
    WorkflowEngine,
    WorkflowRun,
    WorkflowState,
    WorkflowStatus,
)


@pytest.mark.asyncio
async def test_sequence_passes_state_and_results() -> None:
    def first(context: WorkflowContext) -> NodeOutput:
        return NodeOutput(context.workflow_input * 2, {"factor": 2})

    def second(context: WorkflowContext) -> int:
        return int(context.results["first"].value) + int(context.state["factor"])

    workflow = Workflow(
        "sequence",
        [Node("first", first), Node("second", second)],
        [Edge("first", "second")],
    )

    run = await WorkflowEngine().run(workflow, 5)

    assert run.status == WorkflowStatus.COMPLETED
    assert run.node_results["second"].value == 12
    assert run.output == 12
    assert [event.type for event in run.events] == [
        "workflow.started",
        "node.started",
        "node.completed",
        "node.started",
        "node.completed",
        "workflow.completed",
    ]


@pytest.mark.asyncio
async def test_parallel_nodes_overlap_then_join() -> None:
    active = 0
    maximum = 0

    async def root(_: WorkflowContext) -> str:
        return "ready"

    async def branch(_: WorkflowContext) -> str:
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0.02)
        active -= 1
        return "done"

    def join(context: WorkflowContext) -> tuple[str, str, str]:
        return (
            str(context.results["a"].value),
            str(context.results["b"].value),
            str(context.results["c"].value),
        )

    workflow = Workflow(
        "parallel",
        [
            Node("root", root),
            Node("a", branch),
            Node("b", branch),
            Node("c", branch),
            Node("join", join),
        ],
        [
            Edge("root", "a"),
            Edge("root", "b"),
            Edge("root", "c"),
            Edge("a", "join"),
            Edge("b", "join"),
            Edge("c", "join"),
        ],
    )

    run = await WorkflowEngine(max_concurrency=3).run(workflow)

    assert run.status == WorkflowStatus.COMPLETED
    assert maximum == 3
    assert run.output == ("done", "done", "done")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("flag", "selected", "skipped"),
    [(True, "yes", "no"), (False, "no", "yes")],
)
async def test_conditional_route_skips_unselected_branch(
    flag: bool,
    selected: str,
    skipped: str,
) -> None:
    workflow = Workflow(
        "conditional",
        [
            Node("gate", lambda context: context.workflow_input, NodeKind.GATE),
            Node("yes", lambda _: "accepted"),
            Node("no", lambda _: "rejected"),
            Node("join", lambda context: context.results[selected].value),
        ],
        [
            Edge("gate", "yes", route="true"),
            Edge("gate", "no", route="false"),
            Edge("yes", "join"),
            Edge("no", "join"),
        ],
    )

    run = await WorkflowEngine().run(workflow, flag)

    assert run.status == WorkflowStatus.COMPLETED
    assert run.node_results[selected].status == NodeStatus.COMPLETED
    assert run.node_results[skipped].status == NodeStatus.SKIPPED


@pytest.mark.asyncio
async def test_router_emits_selected_route() -> None:
    workflow = Workflow(
        "router",
        [
            Node(
                "route",
                lambda _: NodeOutput(route="technical"),
                NodeKind.ROUTER,
            ),
            Node("technical", lambda _: "python"),
            Node("general", lambda _: "prose"),
        ],
        [
            Edge("route", "technical", route="technical"),
            Edge("route", "general", route="general"),
        ],
    )

    run = await WorkflowEngine().run(workflow)

    assert run.node_results["technical"].value == "python"
    assert run.node_results["general"].status == NodeStatus.SKIPPED
    route = next(event for event in run.events if event.type == "route.selected")
    assert route.payload == {"route": "technical"}


@pytest.mark.asyncio
async def test_router_rejects_an_unknown_route() -> None:
    workflow = Workflow(
        "unknown-route",
        [
            Node("route", lambda _: NodeOutput(route="missing"), NodeKind.ROUTER),
            Node("known", lambda _: None),
        ],
        [Edge("route", "known", route="known")],
    )

    run = await WorkflowEngine().run(workflow)

    assert run.status == WorkflowStatus.FAILED
    assert "unknown route" in str(run.error)


@pytest.mark.asyncio
async def test_retry_backoff_and_idempotency_contract() -> None:
    calls = 0

    def flaky(_: WorkflowContext) -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise ConnectionError("transient")
        return "ok"

    workflow = Workflow(
        "retry",
        [
            Node(
                "flaky",
                flaky,
                retry=RetryPolicy(max_attempts=3, backoff_seconds=0.001),
                idempotent=True,
            )
        ],
    )

    run = await WorkflowEngine().run(workflow)

    assert run.status == WorkflowStatus.COMPLETED
    assert run.node_results["flaky"].attempts == 3
    assert sum(event.type == "node.retrying" for event in run.events) == 2
    with pytest.raises(ValueError, match="idempotent"):
        Node("unsafe", flaky, retry=RetryPolicy(max_attempts=2))


@pytest.mark.asyncio
async def test_loop_terminates_and_strict_guard_fails() -> None:
    def increment(context: WorkflowContext) -> int:
        return context.iteration

    successful = Workflow(
        "loop-success",
        [Node("loop", increment, loop_until=lambda _, value: value == 3, max_iterations=3)],
    )
    guarded = Workflow(
        "loop-guard",
        [Node("loop", increment, loop_until=lambda _, value: value == 4, max_iterations=3)],
    )

    success_run = await WorkflowEngine().run(successful)
    failed_run = await WorkflowEngine().run(guarded)

    assert success_run.node_results["loop"].iterations == 3
    assert success_run.output == 3
    assert failed_run.status == WorkflowStatus.FAILED
    assert "max loop iterations" in str(failed_run.error)


def test_dag_validation_rejects_unknown_nodes_duplicates_and_cycles() -> None:
    node = Node("a", lambda _: None)
    with pytest.raises(WorkflowError, match="unknown node"):
        Workflow("unknown", [node], [Edge("a", "missing")])
    with pytest.raises(WorkflowError, match="unique"):
        Workflow("duplicates", [node, Node("a", lambda _: None)])
    with pytest.raises(WorkflowError, match="cycle"):
        Workflow(
            "cycle",
            [node, Node("b", lambda _: None)],
            [Edge("a", "b"), Edge("b", "a")],
        )


@pytest.mark.asyncio
async def test_failure_checkpoint_can_resume_without_replaying_completed_nodes(
    tmp_path: Path,
) -> None:
    first_calls = 0
    second_calls = 0
    should_fail = True

    def first(_: WorkflowContext) -> NodeOutput:
        nonlocal first_calls
        first_calls += 1
        return NodeOutput("stable", {"saved": True})

    def second(_: WorkflowContext) -> str:
        nonlocal second_calls
        second_calls += 1
        if should_fail:
            raise RuntimeError("not yet")
        return "recovered"

    workflow = Workflow(
        "resumable",
        [Node("first", first), Node("second", second)],
        [Edge("first", "second")],
    )
    store = JSONWorkflowStore(tmp_path)
    engine = WorkflowEngine(store=store)

    failed = await engine.run(workflow, run_id="stable-run")
    restored = store.load("stable-run")
    should_fail = False
    resumed = await engine.resume(workflow, restored)

    assert failed.status == WorkflowStatus.FAILED
    assert resumed.status == WorkflowStatus.COMPLETED
    assert resumed.output == "recovered"
    assert resumed.state.values == {"saved": True}
    assert first_calls == 1
    assert second_calls == 2
    assert WorkflowRun.from_json(resumed.to_json()).to_dict() == resumed.to_dict()


@pytest.mark.asyncio
async def test_public_cancel_interrupts_running_node_and_checkpoint_resumes(
    tmp_path: Path,
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow(_: WorkflowContext) -> str:
        started.set()
        await release.wait()
        return "done"

    workflow = Workflow("cancel", [Node("slow", slow)])
    store = JSONWorkflowStore(tmp_path)
    engine = WorkflowEngine(store=store)
    task = asyncio.create_task(engine.run(workflow, run_id="cancel-run"))
    await started.wait()

    assert await engine.cancel("cancel-run") is True
    interrupted = await task

    assert interrupted.status == WorkflowStatus.INTERRUPTED
    assert interrupted.node_results["slow"].status == NodeStatus.INTERRUPTED
    release.set()
    resumed = await engine.resume(workflow, store.load("cancel-run"))
    assert resumed.status == WorkflowStatus.COMPLETED


@pytest.mark.asyncio
async def test_caller_task_cancellation_propagates_and_persists_interruption(
    tmp_path: Path,
) -> None:
    started = asyncio.Event()

    async def slow(_: WorkflowContext) -> None:
        started.set()
        await asyncio.sleep(60)

    store = JSONWorkflowStore(tmp_path)
    engine = WorkflowEngine(store=store)
    task = asyncio.create_task(
        engine.run(Workflow("caller-cancel", [Node("slow", slow)]), run_id="caller-cancel")
    )
    await started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    checkpoint = store.load("caller-cancel")
    assert checkpoint.status == WorkflowStatus.INTERRUPTED
    assert checkpoint.node_results["slow"].status == NodeStatus.INTERRUPTED


@pytest.mark.asyncio
async def test_timeout_is_normalized_as_node_failure() -> None:
    async def slow(_: WorkflowContext) -> None:
        await asyncio.sleep(1)

    workflow = Workflow("timeout", [Node("slow", slow, timeout=0.001)])
    run = await WorkflowEngine().run(workflow)

    assert run.status == WorkflowStatus.FAILED
    assert "TimeoutError" in str(run.error)


@pytest.mark.asyncio
async def test_predicate_edges_and_async_event_listener() -> None:
    observed: list[str] = []

    async def listener(event: Any) -> None:
        observed.append(str(event.type))

    workflow = Workflow(
        "predicate",
        [Node("source", lambda _: 7), Node("target", lambda _: "odd")],
        [Edge("source", "target", predicate=lambda _, result: int(result.value) % 2 == 1)],
    )
    run = await WorkflowEngine(event_listener=listener).run(workflow)

    assert run.status == WorkflowStatus.COMPLETED
    assert run.output == "odd"
    assert observed == [event.type for event in run.events]


def test_checkpoint_rejects_non_json_state_and_path_traversal(tmp_path: Path) -> None:
    run = WorkflowRun(
        "unsafe",
        "run",
        None,
        state=WorkflowState({"bad": object()}),
        node_results={"node": NodeResult("node")},
    )
    with pytest.raises(WorkflowError, match="not JSON serializable"):
        run.to_json()
    with pytest.raises(WorkflowError, match="invalid workflow run ID"):
        JSONWorkflowStore(tmp_path).load("../escape")
