---
id: guide-part7-multiagent
title: "User Guide · Part VII: Multi-Agent & Workflows"
sidebar_position: 7
description: "Autonomous multi-agent orchestration (AgentManager, SpawnRequest, collaboration Tools, context inheritance, limits & budgets), deterministic workflows (sequential/parallel/conditional/router/retry/loop/DAG/resume), the Router, and hybrid orchestration (agent_node / subworkflow_node)."
---

# Part VII: Multi-Agent & Workflows

This part explains how to orchestrate multiple Agents and deterministic pipelines into larger automation systems. It covers three core capabilities, all based on the real implementation in `src/super_harness`, with runnable examples under `examples/`:

- **Autonomous Multi-Agent**: an `AgentManager` driven by a root Agent and an `AgentFactory` dynamically spawns a bounded, concurrent tree of child Agents, letting a capable model delegate tasks itself through collaboration Tools.
- **Deterministic Workflow**: `Workflow` / `Node` / `Edge` / `WorkflowEngine` where the application (not the model) controls order and branching — with parallel fan-out, conditions, routing, retries, explicit loops, DAG validation, and checkpoint resume.
- **Hybrid Orchestration**: bridging the two — embedding an autonomous Agent (`agent_node`) or a reusable sub-workflow (`subworkflow_node`) into a deterministic pipeline.

## 1. What This Is / When to Use

**Autonomous Multi-Agent** solves "split a large task among several independently configured, concurrently executing Agents." Use it when:

- You want to delegate a task to multiple roles (e.g. coder / reviewer / tester) running in parallel.
- You want the model to decide dynamically whether and how to break work into subtasks (via collaboration Tools).
- You need unified child-Agent lifecycle management: spawn, wait, steer, resume, interrupt, cancel, close.
- You need global constraints: active count, total count, depth, total token/time budget.

**Deterministic Workflow** solves "order and branching must be controlled precisely by the application." Use it when:

- Steps have fixed dependencies (build before publish).
- You need concurrent fan-out followed by a join.
- You need a boolean gate or route labels to pick a branch.
- You need retries, explicit loops, or resumable long-running pipelines.

**Router** provides lightweight, model-agnostic rule routing (`Route` / `Router` / `RouteDecision`) to evaluate predicates in priority order and pick one target before calling any downstream work.

**Hybrid Orchestration** solves "a deterministic step needs dynamic reasoning": putting an `agent_node` in a Workflow delegates that node to an autonomous Agent subtree; `subworkflow_node` nests a reusable deterministic pipeline inside a parent workflow.

> This part only covers **how to use it and what behavior you get**. Internal design rationale belongs to the Internals pages.

## 2. Prerequisites

- Install: run `pip install -e .` in the repository root.
- For real models, set the environment variable `DEEPSEEK_API_KEY` (the default China-available provider is `DeepSeekProvider`).
- Multi-agent examples (`43_`–`47_`) call a real model and need provider access; hybrid examples (`53_`–`56_`) use bundled `DemoProvider` / `SpecialistProvider` / `LeadProvider` and run offline.
- Async APIs need a running event loop. Do not call synchronous methods inside an active event loop; `Router.route` raises `RuntimeError` there — use `Router.aroute` instead.
- Child Agents are created by an `AgentFactory`, which must return an **independently configured** `Agent` (see "Real-world example" below).

## 3. Quick Start

The simplest autonomous multi-agent setup: one root Agent + one factory + spawn one child and wait for it.

```python
import asyncio

from super_harness import Agent, AgentManager, DeepSeekProvider, SpawnRequest


def factory(request: SpawnRequest) -> Agent:
    return Agent(
        DeepSeekProvider(), instructions=request.instructions, context=request.inherited_context
    )


async def main() -> None:
    manager = AgentManager(Agent(DeepSeekProvider()), factory)
    try:
        child = await manager.spawn_agent(manager.root_agent_id, "Research the API", role="researcher")
        finished = (await manager.wait_all([child.agent_id], timeout=300))[0]
        print(finished.status, finished.result.text if finished.result else None)
    finally:
        await manager.aclose()


asyncio.run(main())
```

The simplest deterministic workflow: two nodes, one edge.

```python
import asyncio

from super_harness import Edge, Node, NodeOutput, Workflow, WorkflowEngine


async def main() -> None:
    flow = Workflow(
        "release",
        [
            Node("build", lambda context: NodeOutput("artifact", {"built": True})),
            Node("publish", lambda context: f"published {context.results['build'].value}"),
        ],
        [Edge("build", "publish")],
    )
    run = await WorkflowEngine().run(flow)
    print(run.status, run.output)


asyncio.run(main())
```

Key points:

- `AgentManager(root_agent, factory)` immediately creates a thread for the root Agent and (by default) attaches the collaboration Tools; always finish with `await manager.aclose()`.
- `Workflow` calls `validate()` at construction to check the DAG; execute with `WorkflowEngine().run(workflow, input)`.

## 4. Configuration

### 4.1 Environment variables

| Environment variable | Purpose | Default |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | Request-time credential for `DeepSeekProvider` | none (errors if unset) |

Multi-agent and workflows add no environment variables of their own; token/time budgets are configured through `MultiAgentLimits` and `WorkflowEngine` parameters.

### 4.2 AgentManager constructor

```python
manager = AgentManager(
    root_agent,                 # root Agent, ancestor of all children
    factory,                    # Callable[[SpawnRequest], Agent]
    *,
    limits=None,                # MultiAgentLimits | None
    hooks=None,                 # HookRegistry | None (SUBAGENT_START / SUBAGENT_END)
    event_listener=None,        # Callable[[AgentEvent], object] (sync or async)
    include_child_deltas=False, # forward child text/tool deltas as agent.event
    expose_tools=True,          # auto-attach collaboration Tools to root/child Agents
)
```

### 4.3 MultiAgentLimits (global limits)

```python
from super_harness import MultiAgentLimits

limits = MultiAgentLimits(
    max_active_agents=4,        # max concurrently active (PENDING/RUNNING/WAITING)
    max_total_agents=16,        # max total child Agents excluding the root
    max_depth=3,                # max spawn depth (root is 0)
    total_token_budget=100_000, # cumulative tokens the manager may consume
    total_timeout=3600.0,       # max lifetime in seconds since manager creation
    default_agent_timeout=300.0,# default child timeout when not specified
    max_result_chars=20_000,    # truncation length for AgentResult.text
)
```

Count fields must be ≥ 1 and timeout fields must be > 0, or construction raises `ValueError`.

### 4.4 WorkflowEngine constructor

```python
engine = WorkflowEngine(
    *,
    max_concurrency=8,              # max concurrently ready nodes per batch
    store=None,                     # JSONWorkflowStore | None, enables checkpoints
    event_listener=None,            # Callable[[WorkflowEvent], object]
)
```

## 5. Autonomous Multi-Agent: Basic Example

Spawn three roles, run them in parallel, wait for all, then print results. From `examples/44_coding_team.py`:

```python
import asyncio

from super_harness import Agent, AgentManager, DeepSeekProvider, SpawnRequest


def factory(request: SpawnRequest) -> Agent:
    return Agent(DeepSeekProvider(), instructions=request.instructions)


async def main() -> None:
    manager = AgentManager(Agent(DeepSeekProvider()), factory)
    try:
        members = await asyncio.gather(
            manager.spawn_agent(manager.root_agent_id, "Propose the implementation", role="coder"),
            manager.spawn_agent(manager.root_agent_id, "Find correctness risks", role="reviewer"),
            manager.spawn_agent(manager.root_agent_id, "Design the tests", role="tester"),
        )
        await manager.wait_all([member.agent_id for member in members], timeout=300)
        for result in manager.results():
            print(result.status, result.text)
    finally:
        await manager.aclose()


asyncio.run(main())
```

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/44_coding_team.py)

Key points:

- `spawn_agent(parent_agent_id, task, *, role, ...)` returns an `AgentSnapshot`; `member.agent_id` is the child's stable ID.
- `wait_all([...], timeout=300)` blocks until **all** selected children reach a terminal state; a timeout does not raise — it returns the current snapshots.
- `manager.results()` returns all collected `AgentResult`s, read via `result.status` / `result.text`.

## 6. Autonomous Multi-Agent: Real-world Example

Let the root Agent split a research question into two subagents, wait for both, and synthesize. From `examples/43_autonomous_research.py`:

```python
import asyncio

from super_harness import Agent, AgentManager, DeepSeekProvider, SpawnRequest


def factory(request: SpawnRequest) -> Agent:
    return Agent(
        DeepSeekProvider(), instructions=request.instructions, context=request.inherited_context
    )


async def main() -> None:
    manager = AgentManager(Agent(DeepSeekProvider()), factory)
    try:
        response = await manager.thread(manager.root_agent_id).arun(
            "Split this research question between two subagents, wait for both, and synthesize: "
            "What makes an agent harness reliable?"
        )
        print(response.text)
    finally:
        await manager.aclose()


asyncio.run(main())
```

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/43_autonomous_research.py)

Here there is no explicit `spawn_agent` call: because `expose_tools=True` (the default), the root Agent has already been equipped with six collaboration Tools — `spawn_agent`, `wait_agent`, `send_input`, `resume_agent`, `interrupt_agent`, `close_agent`. A capable model calls them itself during `arun` to spawn and wait for children. The factory's `request.inherited_context` carries the appropriate context fragments according to the inheritance policy.

Another parallel-review scenario: spawn one "critic" per role. From `examples/45_parallel_critics.py`:

```python
import asyncio

from super_harness import Agent, AgentManager, DeepSeekProvider, SpawnRequest


def factory(request: SpawnRequest) -> Agent:
    return Agent(DeepSeekProvider(), instructions=f"You are the {request.role} critic.")


async def main() -> None:
    manager = AgentManager(Agent(DeepSeekProvider()), factory)
    try:
        critics = [
            await manager.spawn_agent(manager.root_agent_id, "Critique the proposal", role=role)
            for role in ("security", "reliability", "usability")
        ]
        await manager.wait_all([critic.agent_id for critic in critics], timeout=300)
        print("\n\n".join(result.text for result in manager.results()))
    finally:
        await manager.aclose()


asyncio.run(main())
```

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/45_parallel_critics.py)

Key points: the `SpawnRequest` the factory receives carries `role`, `task`, `instructions`, `inherited_context`, `timeout`, `token_budget`, and more; the factory uses them to return an **independently configured** Agent. The same factory can return Agents with different providers/instructions/personas per role.

## 7. Autonomous Multi-Agent: Advanced / Combined Example

Steer a finished child and resume it: spawn a task, wait, append a requirement with `send_input`, then resume with `resume_agent`. From `examples/46_child_followup.py`:

```python
import asyncio

from super_harness import Agent, AgentManager, DeepSeekProvider, SpawnRequest


def factory(request: SpawnRequest) -> Agent:
    return Agent(DeepSeekProvider(), instructions=request.instructions)


async def main() -> None:
    manager = AgentManager(Agent(DeepSeekProvider()), factory)
    try:
        child = await manager.spawn_agent(manager.root_agent_id, "Draft a release checklist")
        await manager.wait_all([child.agent_id], timeout=300)
        await manager.send_input(child.agent_id, "Now make it five bullets maximum")
        await manager.resume_agent(child.agent_id)
        final = (await manager.wait_all([child.agent_id], timeout=300))[0]
        print(final.result.text if final.result else final.status)
    finally:
        await manager.aclose()


asyncio.run(main())
```

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/46_child_followup.py)

Key points:

- `send_input(agent_id, message)`: while the child is running, the message is queued as steering at the next safety checkpoint; once it has reached a terminal state, it is appended to `queued_messages`.
- `resume_agent(agent_id, message=None)`: can only resume an **inactive** (terminal) child and re-dispatches a background task with the queued messages as a new prompt. Resuming a RUNNING or PENDING child raises `MultiAgentError`.
- `wait` (any terminal) vs `wait_all` (all terminal) is covered in the API cheat-sheet below.

Another advanced case: budgets + interrupt. Tighten global limits with `MultiAgentLimits`, then interrupt a single child with `interrupt_agent`. From `examples/47_agent_budget_cancel.py`:

```python
import asyncio

from super_harness import Agent, AgentManager, DeepSeekProvider, MultiAgentLimits, SpawnRequest


def factory(request: SpawnRequest) -> Agent:
    return Agent(DeepSeekProvider())


async def main() -> None:
    limits = MultiAgentLimits(max_active_agents=2, max_depth=2, total_token_budget=2_000)
    manager = AgentManager(Agent(DeepSeekProvider()), factory, limits=limits)
    try:
        child = await manager.spawn_agent(
            manager.root_agent_id, "Explore many alternatives", timeout=60, token_budget=1_000
        )
        await asyncio.sleep(0.1)
        await manager.interrupt_agent(child.agent_id)
        print(manager.get(child.agent_id).status, manager.tokens_used)
    finally:
        await manager.aclose()


asyncio.run(main())
```

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/47_agent_budget_cancel.py)

Key points:

- `interrupt_agent(agent_id)` affects only one child; its terminal state is `INTERRUPTED` (distinct from the cascading `CANCELLED`).
- `cancel(parent_id=None)` cascades to all descendants of the subtree (the whole manager by default).
- `token_budget` is the per-child budget; exceeding it yields a `BUDGET_EXHAUSTED` terminal state.
- `manager.tokens_used` reports the manager's cumulative consumption.

### 7.1 Collaboration Tools and expose_tools

`AgentManager` produces six Tools via `collaboration_tools(parent_agent_id)` and `_attach_tools` registers them on the root and every child:

| Tool | Purpose |
| --- | --- |
| `spawn_agent` | Spawn a bounded child Agent and start its task concurrently (args include `role`, `inheritance`, `selected_sources`, `timeout`, `token_budget`) |
| `send_input` | Send steering to a child, or queue follow-up input |
| `wait_agent` | Wait until at least one selected child reaches a terminal state (default `timeout=30.0`) |
| `resume_agent` | Resume an inactive child with queued or explicit input |
| `interrupt_agent` | Interrupt a single active child without cancelling its parent |
| `close_agent` | Close a child subtree while retaining resumable state |

If spawning should be **application-only** (the model must not call these itself), pass `expose_tools=False` at construction.

## 8. Subagent Context Inheritance

`spawn_agent`'s `inheritance` parameter controls how much parent context a child inherits. Values come from the `ContextInheritance` enum:

```python
class ContextInheritance(StrEnum):
    MINIMAL = "minimal"   # default: inherit nothing
    SELECTED = "selected" # inherit only fragments whose source is in selected_sources
    FULL = "full"         # inherit all parent fragments + a tagged dialogue-history snapshot
```

- `MINIMAL` (default): the child starts with no context — cheapest on tokens.
- `SELECTED`: requires a non-empty `selected_sources` (a set of source labels), otherwise raises `MultiAgentError("selected context inheritance requires sources")`. Only fragments whose `source` matches are inherited.
- `FULL`: forwards all of the parent thread's `ContextFragment`s plus one `ContextKind.MEMORY` dialogue-history snapshot (source `agent:<parent_id>:history`). Use **judiciously** — it significantly inflates context and token consumption.

```python
child = await manager.spawn_agent(
    manager.root_agent_id,
    "Summarize the release policy docs",
    inheritance=ContextInheritance.SELECTED,
    selected_sources=["release-policy", "security-policy"],
)
```

Key points: `selected_sources` matches the `ContextFragment.source` field. The collaboration `spawn_agent` Tool also exposes `inheritance` (string) and `selected_sources` so the model can pick a policy through a tool call.

## 9. Subagent Limits & Budgets

Both spawn and resume check budgets and raise `MultiAgentError` on violation:

- **Active count**: `_active_count() >= max_active_agents` → "multi-agent active agent limit exceeded".
- **Total count**: `children >= max_total_agents` → "multi-agent total agent limit exceeded".
- **Depth**: `depth > max_depth` → "multi-agent depth limit exceeded".
- **Global tokens**: `_tokens_used >= total_token_budget` → "multi-agent token budget exhausted".
- **Global time**: `_remaining_seconds() <= 0` since manager creation → "multi-agent time budget exhausted".

Child execution is also checked at runtime:

- A child exceeding its own `token_budget` → terminal `BUDGET_EXHAUSTED`.
- The manager cumulatively exceeding `total_token_budget` → terminal `BUDGET_EXHAUSTED`.
- A single child running past `min(child.timeout, _remaining_seconds())` → terminal `FAILED` with error `agent timed out`.

## 10. Deterministic Workflow: Basic Example (Sequential)

Express a deterministic three-step pipeline (draft → review → publish) with `Workflow`. From `examples/48_workflow_sequence.py`:

```python
"""Run a deterministic three-step workflow."""

import asyncio

from super_harness import Edge, Node, NodeOutput, Workflow, WorkflowEngine


async def main() -> None:
    workflow = Workflow(
        "publish-article",
        [
            Node("draft", lambda context: str(context.workflow_input).strip()),
            Node(
                "review",
                lambda context: NodeOutput(
                    context.results["draft"].value,
                    {"reviewed": True},
                ),
            ),
            Node(
                "publish",
                lambda context: {
                    "text": context.results["review"].value,
                    "reviewed": context.state["reviewed"],
                },
            ),
        ],
        [Edge("draft", "review"), Edge("review", "publish")],
    )
    run = await WorkflowEngine().run(workflow, "  Hello workflows  ")
    print(run.status, run.output)


if __name__ == "__main__":
    asyncio.run(main())
```

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/48_workflow_sequence.py)

Key points:

- Each `Node(node_id, handler, ...)` handler receives an **immutable** `WorkflowContext` and returns a plain value or `NodeOutput(value, updates, route)`.
- `context.workflow_input` is the run input; `context.results["draft"].value` reads an upstream node's result; `context.state["reviewed"]` reads atomic state written by `NodeOutput.updates`.
- `WorkflowEngine().run(workflow, input)` returns a `WorkflowRun`; `run.status` and `run.output` (the last COMPLETED node's value) are directly readable.

## 11. Deterministic Workflow: Real-world Example (Parallel + Join)

Fan out three review nodes concurrently, then rejoin with a plain multi-input `join` node. From `examples/49_workflow_parallel.py`:

```python
"""Fan out work concurrently and join the branch results."""

import asyncio

from super_harness import Edge, Node, Workflow, WorkflowContext, WorkflowEngine


async def inspect(context: WorkflowContext) -> str:
    await asyncio.sleep(0.05)
    return f"{context.node_id}:{context.workflow_input}"


async def main() -> None:
    workflow = Workflow(
        "parallel-review",
        [
            Node("start", lambda _: "ready"),
            Node("security", inspect),
            Node("quality", inspect),
            Node("docs", inspect),
            Node(
                "join",
                lambda context: [
                    context.results[node_id].value
                    for node_id in ("security", "quality", "docs")
                ],
            ),
        ],
        [
            Edge("start", "security"),
            Edge("start", "quality"),
            Edge("start", "docs"),
            Edge("security", "join"),
            Edge("quality", "join"),
            Edge("docs", "join"),
        ],
    )
    run = await WorkflowEngine(max_concurrency=3).run(workflow, "release-1")
    print(run.output)


if __name__ == "__main__":
    asyncio.run(main())
```

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/49_workflow_parallel.py)

Key points:

- Multiple "ready" nodes (all dependencies complete) run **concurrently**; `WorkflowEngine(max_concurrency=3)` bounds the per-batch concurrency.
- A plain multi-input node (here `join`, depending on security/quality/docs) acts as a **join point**: it runs only when all incoming-edge sources are COMPLETED and edge conditions pass.
- Handlers may be sync or async (`inspect` is `async def`); the engine auto-awaits awaitable return values.

## 12. Deterministic Workflow: Conditions and Routing

### 12.1 Boolean gate (GATE) and true/false routing

Use a `NodeKind.GATE` node returning a boolean, pick a branch with `route="true"` / `route="false"` edges, then rejoin safely. From `examples/50_workflow_conditional.py`:

```python
"""Select one branch with a boolean gate and rejoin safely."""

import asyncio

from super_harness import Edge, Node, NodeKind, Workflow, WorkflowEngine


async def main() -> None:
    workflow = Workflow(
        "approval-gate",
        [
            Node("approved", lambda context: context.workflow_input, NodeKind.GATE),
            Node("deploy", lambda _: "deployed"),
            Node("hold", lambda _: "held for review"),
            Node(
                "notify",
                lambda context: next(
                    result.value
                    for result in context.results.values()
                    if result.node_id in {"deploy", "hold"} and result.value is not None
                ),
            ),
        ],
        [
            Edge("approved", "deploy", route="true"),
            Edge("approved", "hold", route="false"),
            Edge("deploy", "notify"),
            Edge("hold", "notify"),
        ],
    )
    run = await WorkflowEngine().run(workflow, True)
    print(run.output)


if __name__ == "__main__":
    asyncio.run(main())
```

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/50_workflow_conditional.py)

Key points: boolean outputs are normalized to `"true"` / `"false"` strings to match edge `route`s; unselected branch nodes are marked `SKIPPED`. The join node `notify` uses `next(...)` to pick whichever branch actually produced a value.

### 12.2 Named-route node (ROUTER)

Use a `NodeKind.ROUTER` node returning `NodeOutput(route="label")` to route input to exactly one specialist node. From `examples/51_workflow_router.py`:

```python
"""Route input to exactly one specialist node."""

import asyncio

from super_harness import Edge, Node, NodeKind, NodeOutput, Workflow, WorkflowEngine


async def main() -> None:
    workflow = Workflow(
        "support-router",
        [
            Node(
                "route",
                lambda context: NodeOutput(
                    route="billing" if "invoice" in str(context.workflow_input) else "technical"
                ),
                NodeKind.ROUTER,
            ),
            Node("billing", lambda _: "billing specialist"),
            Node("technical", lambda _: "technical specialist"),
        ],
        [
            Edge("route", "billing", route="billing"),
            Edge("route", "technical", route="technical"),
        ],
    )
    run = await WorkflowEngine().run(workflow, "My invoice is incorrect")
    selected = next(
        event.payload["route"] for event in run.events if event.type == "route.selected"
    )
    print(selected)


if __name__ == "__main__":
    asyncio.run(main())
```

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/51_workflow_router.py)

Key points:

- Selecting an undeclared route raises `WorkflowError` ("node ... selected unknown route"), so declared edge `route`s must cover every label the node can produce.
- Routing emits a `route.selected` event (`event.payload["route"]`), readable from `run.events`.

## 13. Retry and Explicit Loops

### 13.1 Retry requires idempotent=True

`Node` validation: if `retry.max_attempts > 1` and `idempotent=True` is not declared, construction raises `ValueError("retried nodes must explicitly declare idempotent=True")`. This forces authors to acknowledge that replaying the node handler is safe.

### 13.2 Explicit loops require loop_until + max_iterations

`Node` validation: `max_iterations > 1` without `loop_until` raises `ValueError`; graph cycles (self-cycles or multi-node cycles) are always rejected by `validate()` and can only be expressed as an explicit loop on a single node.

Combined example, from `examples/52_workflow_retry_loop.py`:

```python
"""Combine an idempotent retry policy with a bounded explicit loop."""

import asyncio

from super_harness import Node, RetryPolicy, Workflow, WorkflowContext, WorkflowEngine

attempts = 0


def flaky_counter(context: WorkflowContext) -> int:
    global attempts
    attempts += 1
    if attempts == 1:
        raise ConnectionError("temporary service failure")
    return context.iteration


async def main() -> None:
    workflow = Workflow(
        "retry-loop",
        [
            Node(
                "poll",
                flaky_counter,
                retry=RetryPolicy(max_attempts=2, backoff_seconds=0.05),
                idempotent=True,
                loop_until=lambda _, value: value >= 3,
                max_iterations=4,
            )
        ],
    )
    run = await WorkflowEngine().run(workflow)
    print(run.status, run.output, run.node_results["poll"].attempts)


if __name__ == "__main__":
    asyncio.run(main())
```

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/52_workflow_retry_loop.py)

Key points:

- `RetryPolicy(max_attempts, backoff_seconds, multiplier, max_backoff_seconds)`: exponential backoff, `delay(attempt) = min(backoff_seconds * multiplier**(attempt-1), max_backoff_seconds)`.
- `loop_until(context, value)` stops when it returns `True`; exhausting `max_iterations` first raises `WorkflowError("node ... reached its max loop iterations without satisfying loop_until")`.
- `run.node_results["poll"].attempts` reflects the real invocation count; `context.iteration` is the current loop round (starting at 1).

### 13.3 DAG validation (acyclic / Kahn)

`Workflow.validate()` runs at construction and before every `run`/`resume`:

- `workflow_id` is non-empty and there is at least one node.
- Node IDs are unique; every edge points at known nodes; self-cycles are forbidden.
- **Kahn's algorithm** performs a topological sort for cycle detection: if the visited count ≠ total node count, it raises `WorkflowError("unsupported graph cycle; use Node.loop_until with a strict limit")`.

So multi-node cycles are **never allowed**; when you need iteration, fold it into a single node expressed as a bounded `loop_until` + `max_iterations`.

## 14. Workflow Resume

Configure a `JSONWorkflowStore` on the `WorkflowEngine`, and the engine atomically saves checkpoints at every dependency-batch boundary and at start/end/failure/interrupt (writes a `.tmp` file then `replace`s it). `resume(workflow, checkpoint)` **preserves completed nodes** (no replay) and only resets non-COMPLETED nodes to PENDING before continuing. Therefore handlers should put persistent side effects after the boundary of a completed node.

```python
from pathlib import Path
from super_harness import JSONWorkflowStore, WorkflowEngine

store = JSONWorkflowStore(Path("checkpoints"))
engine = WorkflowEngine(store=store)

run = await engine.run(workflow, run_id="release-run")     # first run
resumed = await engine.resume(workflow, store.load("release-run"))  # resume from checkpoint
```

`resume` accepts a checkpoint as a `WorkflowRun`, a JSON string, or a `Mapping`. Validation rules: the checkpoint's `workflow_id` must match the workflow, the node set must match exactly, and the schema version must be 1; an already-completed run is returned as-is.

## 15. Router (Rule Routing)

`Router` differs from a Workflow ROUTER node: it is independent of any Workflow, evaluates explicit `Route` predicates in `(priority, name)` order, selects the first match, and otherwise falls back to `default`. Use it for lightweight, deterministic dispatch before entering a model or a downstream pipeline.

### 15.1 Basic: route by priority

From `examples/72_router_priority.py`:

```python
"""Route requests by deterministic priority."""

from super_harness import Route, Router

router = Router(
    (
        Route("ordinary", "queue", lambda value, context: True, priority=20),
        Route("urgent", "pager", lambda value, context: value == "urgent", priority=10),
    )
)
print(router.route("urgent"))
```

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/72_router_priority.py)

Key points: `Route(name, target, predicate, priority=100, metadata=...)`. Lower `priority` is evaluated first (here `urgent` priority=10 beats `ordinary` priority=20); ties break by name. `route(value)` returns a `RouteDecision` (with `route`, `target`, `matched`, `reason`). **Calling `route` inside an event loop raises `RuntimeError`** — use `aroute`.

### 15.2 Advanced: async predicate + immutable context

From `examples/73_router_async_context.py`:

```python
"""Use an async predicate with immutable routing context."""

import asyncio
from collections.abc import Mapping
from typing import Any

from super_harness import Route, Router


async def enabled(value: str, context: Mapping[str, Any]) -> bool:
    await asyncio.sleep(0)
    return value == "deploy" and context.get("approved") is True


async def main() -> None:
    router = Router((Route("deploy", "release", enabled),), default="review")
    print(await router.aroute("deploy", context={"approved": True}))


asyncio.run(main())
```

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/73_router_async_context.py)

Key points: predicates may be `async def`; `aroute` awaits awaitable predicates and wraps `context` in an immutable `MappingProxyType`. A predicate must return a boolean or `WorkflowError("route predicate ... did not return bool")` is raised. If nothing matches and no `default` is set, `WorkflowError` is raised.

### 15.3 Observability: observe routing decisions

From `examples/74_router_observation.py`:

```python
"""Observe a routing decision without exposing routed content."""

from super_harness import Event, Route, Router


class Observer:
    def observe(self, event: object) -> None:
        if isinstance(event, Event):
            print(event.type, dict(event.payload))


Router((Route("safe", "worker", lambda value, context: value >= 0),), observer=Observer()).route(1)
```

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/74_router_observation.py)

Key points: `Router(..., observer=...)` emits a `route.selected` event after each decision, with a payload of `route`, `target`, `matched`, `reason`, `metadata`. The routed **value itself is not included**, so routing can be observed without leaking the input.

## 16. Hybrid Orchestration

When a deterministic step needs dynamic reasoning, replace it with `agent_node`; when you need to reuse a deterministic pipeline, use `subworkflow_node`.

### 16.1 agent_node: embed an autonomous Agent in a Workflow

`agent_node(node_id, manager, task, *, role, parent_agent_id, instructions, inheritance, selected_sources, timeout, token_budget) -> Node`, whose handler is an `AutonomousAgentNode` with `NodeKind.AGENT`. The spawned Agent gets the usual collaboration Tools and **may create its own specialist children**; the node is COMPLETED only once the whole Agent subtree has reached a terminal state and succeeded. Core of `examples/53_hybrid_agent_node.py`:

```python
manager = AgentManager(Agent(DemoProvider()), factory)
workflow = Workflow(
    "agent-node",
    [agent_node("researcher", manager, lambda context: f"research {context.workflow_input}")],
)
run = await WorkflowEngine().run(workflow, "Python workflows")
print(run.output)
print([event.type for event in run.events if event.payload.get("source")])
```

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/53_hybrid_agent_node.py)

Key points:

- `task` may be a string or a `Callable[[WorkflowContext], str]` (here a lambda builds the prompt from `context.workflow_input`).
- If the child or any descendant is not COMPLETED, the node raises `WorkflowError` ("autonomous agent node failed: ..." / "autonomous agent descendant failed: ...").
- On success the node returns `NodeOutput(result.text, {...})` whose updates write the state keys `hybrid.<node_id>.agent_id`, `hybrid.<node_id>.thread_id`, and `hybrid.<node_id>.tokens`.
- Hybrid event forwarding (`source: "autonomous_agent"`) carries **metadata only** (`agent_sequence` / `agent_id` / `parent_agent_id`); for full local detail query the `AgentManager` (e.g. `manager.get(...)`, `manager.event_history()`).

A workflow Agent autonomously spawning and joining a specialist team (core of `examples/55_hybrid_specialist_team.py`): the lead role spawns two specialists with `spawn_agent`, then waits with `wait_agent` and aggregates:

```python
workflow = Workflow(
    "team-pipeline",
    [agent_node("team", manager, "coordinate the analysis", role="lead", timeout=2)],
)
run = await WorkflowEngine().run(workflow)
print(run.output)
print("agents:", len(manager.list_agents()) - 1)
```

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/55_hybrid_specialist_team.py)

Key points: `manager.list_agents()` returns all `AgentSnapshot`s; the role flows into `SpawnRequest.role` via `role="lead"`, and the factory returns a different Agent accordingly.

### 16.2 subworkflow_node: nest a deterministic pipeline

`subworkflow_node(node_id, workflow, *, engine, input_builder, state_builder) -> Node`, whose handler is a `SubworkflowNode` with `NodeKind.SUBWORKFLOW`. The child workflow uses its own `WorkflowEngine`; passing `engine=WorkflowEngine(store=JSONWorkflowStore(...))` gives it independent checkpoints. Core of `examples/54_hybrid_subworkflow.py`:

```python
child = Workflow(
    "normalize",
    [
        Node("strip", lambda context: str(context.workflow_input).strip()),
        Node("upper", lambda context: str(context.results["strip"].value).upper()),
    ],
    [Edge("strip", "upper")],
)
child_engine = WorkflowEngine(store=JSONWorkflowStore(Path(directory) / "child"))
parent = Workflow(
    "publish",
    [
        subworkflow_node("normalize", child, engine=child_engine),
        Node("publish", lambda context: f"published:{context.results['normalize'].value}"),
    ],
    [Edge("normalize", "publish")],
)
run = await WorkflowEngine().run(parent, "  release note  ", run_id="demo")
print(run.output)
print(run.state.values["hybrid.normalize.run_id"])
```

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/54_hybrid_subworkflow.py)

Key points:

- The child run ID is derived from the parent run ID plus the node ID (`<parent_run_id>-<node_id>`), e.g. `demo-normalize`.
- On success the node writes the state keys `hybrid.<node_id>.workflow_id` and `hybrid.<node_id>.run_id`.
- Child-workflow events are forwarded with the `subworkflow.<event_type>` prefix and `source: "subworkflow"` (again metadata only).

### 16.3 Cascading failure and resume

Parent cancellation cascades to `agent_node` (`AutonomousAgentNode.cancel` → `manager.cancel(child)`) and `subworkflow_node` (`SubworkflowNode.cancel` → `engine.cancel(child_run_id)`). When failure/resume must be retried at the parent while preserving completed child nodes, give the child `WorkflowEngine` a `JSONWorkflowStore`. Core of `examples/56_hybrid_failure_resume.py`:

```python
failed = await parent_engine.run(parent, run_id="release-run")
print("first:", failed.status)
service_ready = True
resumed = await parent_engine.resume(parent, parent_store.load("release-run"))
print("resumed:", resumed.status, resumed.output)
```

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/56_hybrid_failure_resume.py)

Key points: the parent and child workflows each get their own `JSONWorkflowStore`; on the first run the child `publish` raises `ConnectionError` because `service_ready=False`, failing the parent (`FAILED`). After the fix, `resume` continues from the checkpoint, preserving already-completed nodes such as `build` instead of replaying them.

## 17. API Cheat-sheet (key signatures)

```python
# Autonomous multi-agent
AgentManager(root_agent, factory, *, limits=None, hooks=None, event_listener=None,
             include_child_deltas=False, expose_tools=True)
await manager.spawn_agent(parent_agent_id, task, *, role="worker", instructions=None,
                          inheritance=ContextInheritance.MINIMAL, selected_sources=(),
                          timeout=None, token_budget=None) -> AgentSnapshot
await manager.send_input(agent_id, message) -> AgentSnapshot
await manager.resume_agent(agent_id, message=None) -> AgentSnapshot
await manager.wait(agent_ids=None, *, timeout=None) -> tuple[AgentSnapshot, ...]
await manager.wait_all(agent_ids=None, *, timeout=None) -> tuple[AgentSnapshot, ...]
await manager.interrupt_agent(agent_id) -> AgentSnapshot
await manager.cancel(agent_id=None) -> None
await manager.close_agent(agent_id) -> AgentSnapshot
await manager.aclose() -> None
manager.list_agents(*, parent_agent_id=None) -> tuple[AgentSnapshot, ...]
manager.get(agent_id) -> AgentSnapshot
manager.thread(agent_id) -> Thread
manager.results(agent_ids=None) -> tuple[AgentResult, ...]
manager.event_history(*, after_sequence=0) -> tuple[AgentEvent, ...]
manager.tokens_used -> int
manager.collaboration_tools(parent_agent_id) -> tuple[Tool, ...]
manager.root_agent_id -> str

# Deterministic workflow
Workflow(workflow_id, nodes, edges=())
Node(node_id, handler, kind=NodeKind.FUNCTION, retry=RetryPolicy(), timeout=None,
     idempotent=False, loop_until=None, max_iterations=1)
Edge(source, target, route=None, predicate=None)
NodeOutput(value=None, updates=None, route=None)
RetryPolicy(max_attempts=1, backoff_seconds=0.0, multiplier=2.0, max_backoff_seconds=60.0)
WorkflowEngine(*, max_concurrency=8, store=None, event_listener=None)
await engine.run(workflow, workflow_input=None, *, state=None, run_id=None) -> WorkflowRun
await engine.resume(workflow, checkpoint) -> WorkflowRun        # checkpoint: WorkflowRun | str | Mapping
await engine.cancel(run_id) -> bool
JSONWorkflowStore(directory); store.save(run) -> Path; store.load(run_id) -> WorkflowRun

# Hybrid orchestration
agent_node(node_id, manager, task, *, role="worker", parent_agent_id=None, instructions=None,
           inheritance=ContextInheritance.MINIMAL, selected_sources=(), timeout=None,
           token_budget=None) -> Node
subworkflow_node(node_id, workflow, *, engine=None, input_builder=_input, state_builder=None) -> Node

# Router
Router(routes, *, default=None, observer=None)
Router.route(value, *, context=None) -> RouteDecision      # raises RuntimeError inside an event loop
await Router.aroute(value, *, context=None) -> RouteDecision
Route(name, target, predicate, priority=100, metadata=None)
RouteDecision(route, target, matched, reason, timestamp, metadata)
```

## 18. Events & Streaming

### 18.1 AgentManager events

Consume `AgentEvent` via the `event_listener` callback or asynchronously via `events(after_sequence=...)` (fields: `sequence`, `type`, `agent_id`, `parent_agent_id`, `timestamp`, `payload`). Event types:

| Event | When |
| --- | --- |
| `agent.spawned` | a child is spawned successfully (payload has `role`, `depth`) |
| `agent.started` | a child task begins executing |
| `agent.message` | `send_input` records a message |
| `agent.resumed` | `resume_agent` re-dispatches a task |
| `agent.completed` | a child reaches COMPLETED (payload has `result`) |
| `agent.failed` | a child fails (payload has `error_type`) |
| `agent.interrupted` / `agent.cancelled` / `agent.budget_exhausted` / `agent.closed` | the corresponding terminal state |
| `agent.event` | forwarded child-thread events (by default skipping `model.text.delta` / `model.tool_call.delta` unless `include_child_deltas=True`) |

You can also read all past events with `manager.event_history(after_sequence=0)`.

### 18.2 Workflow events

`WorkflowRun.events` stores `WorkflowEvent` (`sequence`, `type`, `workflow_id`, `run_id`, `node_id`, `timestamp`, `payload`), and `WorkflowEngine(event_listener=...)` observes them live:

| Event | When |
| --- | --- |
| `workflow.started` / `workflow.resumed` | run starts / resumes from a checkpoint |
| `node.started` / `node.completed` / `node.failed` / `node.skipped` / `node.interrupted` | node lifecycle |
| `node.retrying` | before a retry (payload has `attempt`, `delay_seconds`, `iteration`) |
| `route.selected` | a router/gate node selects an edge (payload has `route`) |
| `workflow.completed` / `workflow.failed` / `workflow.interrupted` | run terminal states |

### 18.3 Router events

`Router` emits a `route.selected` event through its `observer`, with payload `route`, `target`, `matched`, `reason`, `metadata`, excluding the routed value.

## 19. Errors, Timeouts & Retries

### 19.1 Multi-agent

- Budget/validation failures at spawn or resume raise `MultiAgentError` (e.g. active/total/depth limit, token/time budget exhausted, `resume requires queued or explicit input`, `cannot resume an active agent`, `child task and role must be non-empty`, unknown agent ID).
- A child timing out at runtime (`min(child.timeout, remaining_seconds)`) → terminal `FAILED` with `AgentResult.error = "agent timed out"`.
- A `timeout` expiring in `wait` / `wait_all` does **not** raise: it returns the current snapshots, and the caller checks `status`.
- A child factory raising → `MultiAgentError("child Agent factory failed")`.
- A collaboration Tool name conflict → `MultiAgentError("Agent has a conflicting collaboration tool")`.

### 19.2 Workflow

- A node handler raising → the node is `FAILED` with `"<Type>: <msg>"`; after the batch the workflow enters `FAILED` and `run.error` aggregates all failed nodes.
- Retries: `idempotent=True` + `RetryPolicy`; `node.retrying` is emitted before each retry. **Configuring retry without `idempotent` raises `ValueError` at construction**.
- Explicit loops: exhausting `max_iterations` before `loop_until` is satisfied fails the node with `WorkflowError("... reached its max loop iterations ...")`.
- Node timeout: `Node(..., timeout=...)` uses `asyncio.wait_for` for async handlers.
- Cancellation: `await engine.cancel(run_id)` requests cancellation and cancels running node tasks → `INTERRUPTED`.
- DAG cycles / unknown edges / duplicate node IDs → `WorkflowError` at construction or `run`.

### 19.3 Router

- A predicate not returning a boolean → `WorkflowError("route predicate ... did not return bool")`.
- No match and no `default` → `WorkflowError("router found no matching route and has no default")`.
- Calling synchronous `route` inside an event loop → `RuntimeError("Router.route cannot run inside an active event loop; use aroute")`.

## 20. Combining with Other Features

- **With Hooks**: `AgentManager(..., hooks=HookRegistry())` dispatches `SUBAGENT_START` / `SUBAGENT_END` when children start/end.
- **With Observability**: inject an `Observability` into every Agent and pass `observer.observe` as `WorkflowEngine(event_listener=...)` to observe the full hybrid boundary. See `examples/58_observability_trace_metrics.py`.
- **With RAG/Search**: the child factory can use a `KnowledgeRouter` to equip different roles with different knowledge tools; `inheritance=SELECTED` selectively passes RAG fragments (by `source`) to children.
- **With Persona**: the factory can return Agents with different `Persona`s per `role` for a role-based sub-team.
- **With persisted Threads**: every Agent inside an `AgentManager` has its own `Thread`; combined with `SQLiteThreadStore`, child sessions can survive restarts.
- **With MCP/Plugins**: child Agents' tool sets can come from MCP/plugins via the factory; with `expose_tools=False` the collaboration Tools are not injected, avoiding name conflicts.

## 21. Security Notes

- `AgentManager` collaboration Tools are `risk="runtime"` tools: with `expose_tools=True` the model can **autonomously spawn/interrupt/resume** child Agents. Enable only with trusted models or controlled prompts; use `expose_tools=False` when the application must retain exclusive control.
- Inherited child context (especially `FULL`) may carry sensitive information; prefer `SELECTED` and pass only explicitly needed sources.
- Budgets (`MultiAgentLimits`) are the first gate against runaway behavior (unbounded spawning, token explosions): set sane `max_total_agents`, `max_depth`, `total_token_budget`, and `total_timeout`.
- A child Agent created by the factory has the same tool/sandbox capabilities as the root; do not grant a `full_access` sandbox to children running untrusted tasks.
- Hybrid orchestration executes any handler code declared in the workflow — run only trusted, reviewed workflow definitions.
- A `Router`'s observer does not leak the routed value, making it suitable for observable routing over sensitive data.

## 22. Troubleshooting

| Symptom | Cause & fix |
| --- | --- |
| `RuntimeError: Router.route cannot run inside an active event loop` | Called sync `route` in async code; use `await router.aroute(...)`. |
| `MultiAgentError: multi-agent active agent limit exceeded` | Too many simultaneously active children vs `max_active_agents`; raise the limit or finish with `wait_all` first. |
| `MultiAgentError: multi-agent depth limit exceeded` | Spawn depth exceeds `max_depth`; reduce nesting. |
| `MultiAgentError: cannot resume an active agent` | Called `resume_agent` on a RUNNING/PENDING child; `wait` to a terminal state first. |
| `MultiAgentError: resume requires queued or explicit input` | Resumed with neither queued messages nor an explicit `message`; supply input. |
| `ValueError: retried nodes must explicitly declare idempotent=True` | Configured `RetryPolicy` without `idempotent=True` on the `Node`; add it if the handler can be safely replayed. |
| `ValueError: max_iterations greater than one requires loop_until` | `max_iterations > 1` without `loop_until`; add the termination predicate. |
| `WorkflowError: unsupported graph cycle; use Node.loop_until ...` | The graph has a cycle; express it as a single-node explicit loop. |
| `WorkflowError: node ... selected unknown route ...` | The node produced a route label not declared on any edge; add the matching `Edge(..., route=...)`. |
| `WorkflowError: checkpoint nodes do not match the workflow` | The `resume` checkpoint comes from a different workflow structure; ensure `workflow_id` and node set match. |
| A child stays active and `wait_all` never returns | Check `timeout` and the global `total_timeout`; call `cancel` if needed. |

## 23. Links

- Runnable examples: `examples/43_autonomous_research.py`, `44_coding_team.py`, `45_parallel_critics.py`, `46_child_followup.py`, `47_agent_budget_cancel.py`, `48_workflow_sequence.py`, `49_workflow_parallel.py`, `50_workflow_conditional.py`, `51_workflow_router.py`, `52_workflow_retry_loop.py`, `53_hybrid_agent_node.py`, `54_hybrid_subworkflow.py`, `55_hybrid_specialist_team.py`, `56_hybrid_failure_resume.py`, `72_router_priority.py`, `73_router_async_context.py`, `74_router_observation.py`.
- Related Internals: internal design, data models, concurrency/cancellation, and failure models for multi-agent and workflows.
- API reference: signatures and fields for `AgentManager`, `MultiAgentLimits`, `SpawnRequest`, `Workflow`, `Node`, `Edge`, `WorkflowEngine`, `JSONWorkflowStore`, `Router`, `Route`, `agent_node`, `subworkflow_node`.
