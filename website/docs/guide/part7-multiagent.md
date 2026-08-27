---
id: guide-part7-multiagent
title: "用户指南 · 第七部分：多智能体与工作流（Multi-Agent & Workflows）"
sidebar_position: 7
description: 自主多智能体编排（AgentManager、SpawnRequest、协作 Tools、上下文继承、限制与预算）、确定性工作流（顺序/并行/条件/路由/重试/循环/DAG/恢复）、Router 路由，以及混合编排（agent_node / subworkflow_node）。
---

# 第七部分：多智能体与工作流（Multi-Agent & Workflows）

本部分讲解如何把多个智能体（Agent）和确定性流程编排成更大规模的自动化系统。内容覆盖三类核心能力，均基于 `src/super_harness` 的真实实现，示例代码可以直接从 `examples/` 目录运行：

- **自主多智能体（Autonomous Multi-Agent）**：由一个根 Agent 和一个 `AgentFactory` 驱动的 `AgentManager`，动态地派生（spawn）有界并发的子 Agent 树，让足够强的模型通过协作 Tools 自行委派任务。
- **确定性工作流（Deterministic Workflow）**：由应用（而非模型）控制顺序与分支的 `Workflow` / `Node` / `Edge` / `WorkflowEngine`，支持并行、条件、路由、重试、显式循环、DAG 校验与断点恢复。
- **混合编排（Hybrid Orchestration）**：把两者接起来——在确定性流水线里嵌入一个自主 Agent（`agent_node`）或一个可复用子工作流（`subworkflow_node`）。

## 1. 这是什么 / 何时使用

**自主多智能体**解决"把一个大任务拆给多个各自配置、并发执行的 Agent"的问题。何时使用：

- 需要把任务委托给多个角色（如 coder / reviewer / tester）并行执行。
- 需要让模型动态决定是否/如何拆分子任务（通过协作 Tools）。
- 需要统一的子 Agent 生命周期管理：派生、等待、引导、恢复、中断、取消、关闭。
- 需要全局约束：活跃数、总数、深度、总令牌/时间预算。

**确定性工作流**解决"顺序与分支必须由应用精确控制"的问题。何时使用：

- 步骤有固定依赖（先 build 再 publish）。
- 需要并发扇出后汇合（fan-out / join）。
- 需要布尔门（gate）或路由标签来决定走哪条分支。
- 需要重试、显式循环、可恢复的长流程。

**Router** 提供轻量的、与模型无关的规则路由（`Route` / `Router` / `RouteDecision`），用于在调用任何下游之前按优先级评估谓词并选择一个目标。

**混合编排**解决"某个确定性步骤需要动态推理"的问题：把 `agent_node` 放进 Workflow 会让该节点委托给一个自主 Agent 子树；`subworkflow_node` 则把可复用的确定性流水线嵌套进父工作流。

> 本部分只讲**怎么用、会得到什么行为**。内部设计动机属于 Internals 页面。

## 2. 前置条件（Prerequisites）

- 安装：在仓库根目录执行 `pip install -e .`。
- 需要真实模型时，设置环境变量 `DEEPSEEK_API_KEY`（默认的中国大陆可用提供商为 `DeepSeekProvider`）。
- 多智能体示例（`43_`–`47_`）会真实调用模型，需要能访问提供商；混合编排示例（`53_`–`56_`）使用自带的 `DemoProvider` / `SpecialistProvider` / `LeadProvider`，不依赖网络，可直接运行。
- 异步 API 需要一个正在运行的事件循环。不要在活跃事件循环中调用同步方法；`Router.route` 在事件循环内会抛 `RuntimeError`，此时改用 `Router.aroute`。
- 子 Agent 由 `AgentFactory` 创建，工厂必须返回一个**单独配置**的 `Agent`（见下文"真实场景"）。

## 3. 快速开始（Quick start）

最简的自主多智能体：一个根 Agent + 一个工厂 + 派生一个子 Agent 并等待它完成。

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

最简的确定性工作流：两个节点，一条边。

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

要点：

- `AgentManager(root_agent, factory)` 会立即为根 Agent 创建线程并（默认）挂上协作 Tools；结束务必 `await manager.aclose()`。
- `Workflow` 在构造时就会调用 `validate()` 做 DAG 校验；用 `WorkflowEngine().run(workflow, input)` 执行。

## 4. 配置（Configuration）

### 4.1 环境变量

| 环境变量 | 用途 | 默认 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | `DeepSeekProvider` 的请求时凭据 | 无（未设置会报错） |

多智能体与工作流本身不新增环境变量；令牌/时间预算通过 `MultiAgentLimits` 与 `WorkflowEngine` 参数配置。

### 4.2 AgentManager 构造参数

```python
manager = AgentManager(
    root_agent,                 # 根 Agent，作为所有子 Agent 的祖先
    factory,                    # Callable[[SpawnRequest], Agent]
    *,
    limits=None,                # MultiAgentLimits | None
    hooks=None,                 # HookRegistry | None（SUBAGENT_START / SUBAGENT_END）
    event_listener=None,        # Callable[[AgentEvent], object]（同步或异步）
    include_child_deltas=False, # 是否把子线程的文本/tool delta 转发为 agent.event
    expose_tools=True,          # 是否自动挂载协作 Tools 到根/子 Agent
)
```

### 4.3 MultiAgentLimits（全局限制）

```python
from super_harness import MultiAgentLimits

limits = MultiAgentLimits(
    max_active_agents=4,        # 同时处于活跃（PENDING/RUNNING/WAITING）的最大数量
    max_total_agents=16,        # 除根以外的最大子 Agent 总数
    max_depth=3,                # 最大派生深度（根为 0）
    total_token_budget=100_000, # 管理器累计消耗的最大令牌数
    total_timeout=3600.0,       # 管理器从创建起的最大存活秒数
    default_agent_timeout=300.0,# 子 Agent 未显式指定 timeout 时使用的默认值
    max_result_chars=20_000,    # AgentResult.text 的最大截断长度
)
```

计数类字段必须 ≥ 1，超时字段必须 > 0，否则构造时抛 `ValueError`。

### 4.4 WorkflowEngine 构造参数

```python
engine = WorkflowEngine(
    *,
    max_concurrency=8,              # 同一批最多并发的就绪节点数
    store=None,                     # JSONWorkflowStore | None，提供断点持久化
    event_listener=None,            # Callable[[WorkflowEvent], object]
)
```

## 5. 自主多智能体：基础例子

用 `AgentManager` 派生三个角色并行执行，等待全部完成后打印结果。来自 `examples/44_coding_team.py`：

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

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/44_coding_team.py)

要点：

- `spawn_agent(parent_agent_id, task, *, role, ...)` 返回 `AgentSnapshot`；`member.agent_id` 是子 Agent 的稳定 ID。
- `wait_all([...], timeout=300)` 阻塞直到**所有**选中的子 Agent 进入终态；超时不会抛异常，而是返回当前快照。
- `manager.results()` 返回所有已有结果的 `AgentResult`，按 `result.status` / `result.text` 读取。

## 6. 自主多智能体：真实场景例子

让根 Agent 自主地把研究问题拆给两个子 Agent，等待两者，再综合。来自 `examples/43_autonomous_research.py`：

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

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/43_autonomous_research.py)

这里没有显式调用 `spawn_agent`：因为 `expose_tools=True`（默认），根 Agent 已被挂上 `spawn_agent`、`wait_agent`、`send_input`、`resume_agent`、`interrupt_agent`、`close_agent` 六个协作 Tool。能力足够强的模型会在 `arun` 过程中自己调用它们来派生并等待子 Agent。工厂收到的 `request.inherited_context` 会根据继承策略传入合适的上下文片段。

另一个并行评审场景：为每个角色派生一个"评论者"。来自 `examples/45_parallel_critics.py`：

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

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/45_parallel_critics.py)

要点：`AgentFactory` 收到的 `SpawnRequest` 携带 `role`、`task`、`instructions`、`inherited_context`、`timeout`、`token_budget` 等字段，工厂据此返回**独立配置**的 Agent。同一个工厂可以按角色返回不同提供商/指令/人设的 Agent。

## 7. 自主多智能体：进阶 / 组合例子

子 Agent 完成后继续引导并恢复：先派发一个任务，等它完成后用 `send_input` 追加要求，再用 `resume_agent` 恢复执行。来自 `examples/46_child_followup.py`：

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

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/46_child_followup.py)

要点：

- `send_input(agent_id, message)`：子 Agent 正在运行时，消息作为下一个安全检查点的 steering 入队；已进入终态时则追加到 `queued_messages`。
- `resume_agent(agent_id, message=None)`：只能恢复**非活跃**（已终态）的子 Agent，并把排队的消息作为新 prompt 重新派发一个后台任务。**运行中或 PENDING 的子 Agent 不能 resume**（抛 `MultiAgentError`）。
- `wait`（任一终态）与 `wait_all`（全部终态）的区别见下文 API 速查。

另一个进阶：预算 + 中断。用 `MultiAgentLimits` 收紧全局约束，然后对单个子 Agent 调用 `interrupt_agent`。来自 `examples/47_agent_budget_cancel.py`：

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

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/47_agent_budget_cancel.py)

要点：

- `interrupt_agent(agent_id)` 只影响单个子 Agent，其终态记为 `INTERRUPTED`（与级联的 `CANCELLED` 区分）。
- `cancel(parent_id=None)` 会级联作用于该子树的所有后代（默认是整个管理器）。
- `token_budget` 是子 Agent 级预算；超过时该子 Agent 终态为 `BUDGET_EXHAUSTED`。
- `manager.tokens_used` 报告管理器累计消耗。

### 7.1 协作 Tools 与 expose_tools

`AgentManager` 通过 `collaboration_tools(parent_agent_id)` 生成六个 Tool，`_attach_tools` 把它们注册到根与每个子 Agent：

| Tool 名 | 作用 |
| --- | --- |
| `spawn_agent` | 派发一个有界子 Agent 并并发启动其任务（参数含 `role`、`inheritance`、`selected_sources`、`timeout`、`token_budget`） |
| `send_input` | 向子 Agent 发送引导，或为其排队后续输入 |
| `wait_agent` | 等待至少一个选中子 Agent 进入终态（默认 `timeout=30.0`） |
| `resume_agent` | 用排队/显式输入恢复一个非活跃子 Agent |
| `interrupt_agent` | 中断单个活跃子 Agent 而不取消其父级 |
| `close_agent` | 关闭一个子子树但保留可恢复状态 |

若只希望由**应用**控制派生（不让模型自行调用），构造时传 `expose_tools=False`。

## 8. 子代理上下文继承（Subagent Context Inheritance）

`spawn_agent` 的 `inheritance` 参数控制子 Agent 继承多少父级上下文，取值来自 `ContextInheritance` 枚举：

```python
class ContextInheritance(StrEnum):
    MINIMAL = "minimal"   # 默认：不继承任何片段
    SELECTED = "selected" # 只继承 selected_sources 指定的来源片段
    FULL = "full"         # 继承全部父级片段 + 一段带标记的对话历史快照
```

- `MINIMAL`（默认）：子 Agent 从零上下文开始，最省令牌。
- `SELECTED`：必须提供非空 `selected_sources`（来源标签集合），否则抛 `MultiAgentError("selected context inheritance requires sources")`。只继承 `source` 命中的片段。
- `FULL`：把父级线程的全部 `ContextFragment` 传下去，并追加一条 `ContextKind.MEMORY` 的对话历史快照（来源为 `agent:<parent_id>:history`）。应**审慎**使用——它会显著放大上下文与令牌消耗。

```python
child = await manager.spawn_agent(
    manager.root_agent_id,
    "Summarize the release policy docs",
    inheritance=ContextInheritance.SELECTED,
    selected_sources=["release-policy", "security-policy"],
)
```

要点：`selected_sources` 匹配的是 `ContextFragment.source` 字段。协作 Tool 的 `spawn_agent` 也暴露 `inheritance`（字符串）与 `selected_sources` 参数，供模型通过工具调用指定策略。

## 9. 子代理限制与预算（Limits & Budgets）

派生与恢复时都会做预算校验，超出即抛 `MultiAgentError`：

- **活跃数**：`_active_count() >= max_active_agents` → "multi-agent active agent limit exceeded"。
- **总数**：`children >= max_total_agents` → "multi-agent total agent limit exceeded"。
- **深度**：`depth > max_depth` → "multi-agent depth limit exceeded"。
- **全局令牌**：`_tokens_used >= total_token_budget` → "multi-agent token budget exhausted"。
- **全局时间**：从管理器创建起的 `_remaining_seconds() <= 0` → "multi-agent time budget exhausted"。

子 Agent 运行期还会被校验：

- 子级自身 `token_budget` 超限 → 终态 `BUDGET_EXHAUSTED`。
- 管理器累计超 `total_token_budget` → 终态 `BUDGET_EXHAUSTED`。
- 单个子 Agent 运行超过 `min(child.timeout, _remaining_seconds())` → 终态 `FAILED`，错误为 `agent timed out`。

## 10. 确定性工作流：基础例子（顺序）

用 `Workflow` 表达确定性的三步流水线（draft → review → publish）。来自 `examples/48_workflow_sequence.py`：

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

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/48_workflow_sequence.py)

要点：

- 每个 `Node(node_id, handler, ...)` 的 handler 接收一个**不可变**的 `WorkflowContext`，返回普通值或 `NodeOutput(value, updates, route)`。
- `context.workflow_input` 是本次运行输入；`context.results["draft"].value` 读取上游节点结果；`context.state["reviewed"]` 读取 `NodeOutput.updates` 写入的原子状态。
- `WorkflowEngine().run(workflow, input)` 返回 `WorkflowRun`；`run.status`、`run.output`（最后一个 COMPLETED 节点的值）可直接读取。

## 11. 确定性工作流：真实场景例子（并行 + 汇合）

并发扇出三个检查节点，再用一个普通的多输入节点 `join` 汇合。来自 `examples/49_workflow_parallel.py`：

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

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/49_workflow_parallel.py)

要点：

- 多个"就绪"节点（依赖全部完成）会**并发**执行；`WorkflowEngine(max_concurrency=3)` 限制同一批并发数。
- 一个普通的多输入节点（这里 `join` 依赖 security/quality/docs）充当**汇合点**：只有所有入边来源都 COMPLETED 且边条件通过才执行。
- handler 可以是同步或异步（`inspect` 是 `async def`）；引擎会自动 `await` 可等待的返回值。

## 12. 确定性工作流：条件与路由

### 12.1 布尔门（GATE）与 true/false 路由

用 `NodeKind.GATE` 节点返回布尔值，配合 `route="true"` / `route="false"` 的边选择分支，再安全汇合。来自 `examples/50_workflow_conditional.py`：

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

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/50_workflow_conditional.py)

要点：布尔输出会被规范化为 `"true"` / `"false"` 字符串来匹配边的 `route`；未选中的分支节点被标记为 `SKIPPED`。汇合节点 `notify` 用 `next(...)` 从两个可能分支中取实际产生的那个值。

### 12.2 具名路由节点（ROUTER）

用 `NodeKind.ROUTER` 节点返回 `NodeOutput(route="label")`，把输入路由到恰好一个专家节点。来自 `examples/51_workflow_router.py`：

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

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/51_workflow_router.py)

要点：

- 节点选中了未声明的路由会抛 `WorkflowError`（"node ... selected unknown route"），因此声明边的 `route` 必须覆盖节点可能产生的所有标签。
- 路由选择会发出 `route.selected` 事件（`event.payload["route"]`），可从 `run.events` 读取。

## 13. 重试与显式循环（Retry & Loop）

### 13.1 重试要求 idempotent=True

`Node` 校验规则：`retry.max_attempts > 1` 且未声明 `idempotent=True` 时，构造即抛 `ValueError("retried nodes must explicitly declare idempotent=True")`。这是为了让作者显式承认"重放节点处理器是安全的"。

### 13.2 显式循环要求 loop_until + max_iterations

`Node` 校验规则：`max_iterations > 1` 且未提供 `loop_until` 时抛 `ValueError`；图环（self-cycle 或多节点环）一律被 `validate()` 拒绝，只能通过单个节点的显式循环表达。

两者结合的示例，来自 `examples/52_workflow_retry_loop.py`：

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

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/52_workflow_retry_loop.py)

要点：

- `RetryPolicy(max_attempts, backoff_seconds, multiplier, max_backoff_seconds)`：指数退避，`delay(attempt) = min(backoff_seconds * multiplier**(attempt-1), max_backoff_seconds)`。
- `loop_until(context, value)` 返回 `True` 时停止；达到 `max_iterations` 仍未满足会抛 `WorkflowError("node ... reached its max loop iterations without satisfying loop_until")`。
- `run.node_results["poll"].attempts` 反映实际调用次数；`context.iteration` 是当前循环轮次（从 1 起）。

### 13.3 DAG 校验（acyclic / Kahn）

`Workflow.validate()` 在构造与每次 `run`/`resume` 前执行：

- `workflow_id` 非空、至少一个节点。
- 节点 ID 唯一；边两端都指向已知节点；禁止 self-cycle。
- 用 **Kahn 算法**做拓扑排序检测环：若访问节点数 ≠ 节点总数，抛 `WorkflowError("unsupported graph cycle; use Node.loop_until with a strict limit")`。

因此多节点环**永远不可用**；需要迭代时把迭代塞进单个节点，用 `loop_until` + `max_iterations` 表达有界循环。

## 14. 工作流恢复（Workflow Resume）

在 `WorkflowEngine` 上配置 `JSONWorkflowStore`，引擎会在每次依赖批次边界、开始/结束、失败/中断时原子地保存检查点（写 `.tmp` 后 `replace`）。`resume(workflow, checkpoint)` 会**保留已完成节点**（不重放），只把非 COMPLETED 节点重置为 PENDING 继续推进。因此，处理器应把持久性副作用放在已完成节点的边界之后。

```python
from pathlib import Path
from super_harness import JSONWorkflowStore, WorkflowEngine

store = JSONWorkflowStore(Path("checkpoints"))
engine = WorkflowEngine(store=store)

run = await engine.run(workflow, run_id="release-run")     # 首次运行
resumed = await engine.resume(workflow, store.load("release-run"))  # 从断点恢复
```

`resume` 接受的 checkpoint 可以是 `WorkflowRun`、JSON 字符串或 `Mapping`。校验规则：checkpoint 的 `workflow_id` 必须与 workflow 一致、节点集合必须完全匹配、schema 版本必须为 1；已完成运行会直接返回原 `WorkflowRun`。

## 15. Router（规则路由）

`Router` 与 `Workflow` 的 ROUTER 节点不同：它独立于任何 Workflow，按 `(priority, name)` 顺序评估显式 `Route` 谓词，选择第一个匹配项，否则落到 `default`。用于在进入模型或下游流程之前做轻量的、确定性的分派。

### 15.1 基础：按优先级路由

来自 `examples/72_router_priority.py`：

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

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/72_router_priority.py)

要点：`Route(name, target, predicate, priority=100, metadata=...)`。`priority` 越小越先评估（示例中 `urgent` priority=10 优先于 `ordinary` priority=20），同优先级按名称排序。`route(value)` 返回 `RouteDecision`（含 `route`、`target`、`matched`、`reason`）。**在事件循环内调用 `route` 会抛 `RuntimeError`**，请改用 `aroute`。

### 15.2 进阶：异步谓词 + 不可变上下文

来自 `examples/73_router_async_context.py`：

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

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/73_router_async_context.py)

要点：谓词可以是 `async def`；`aroute` 会 `await` 可等待的谓词结果，并把 `context` 包装为不可变 `MappingProxyType`。谓词必须返回布尔，否则抛 `WorkflowError("route predicate ... did not return bool")`。没有路由匹配且未提供 `default` 时抛 `WorkflowError`。

### 15.3 可观测性：观察路由决策

来自 `examples/74_router_observation.py`：

```python
"""Observe a routing decision without exposing routed content."""

from super_harness import Event, Route, Router


class Observer:
    def observe(self, event: object) -> None:
        if isinstance(event, Event):
            print(event.type, dict(event.payload))


Router((Route("safe", "worker", lambda value, context: value >= 0),), observer=Observer()).route(1)
```

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/74_router_observation.py)

要点：`Router(..., observer=...)` 会在每次决策后发出 `route.selected` 事件，payload 含 `route`、`target`、`matched`、`reason`、`metadata`。**不包含**被路由的值本身，因此可在不泄露输入内容的前提下观测路由行为。

## 16. 混合编排（Hybrid Orchestration）

当一个确定性步骤需要动态推理，把它替换为 `agent_node`；当需要复用确定性流水线，用 `subworkflow_node`。

### 16.1 agent_node：把自主 Agent 嵌进 Workflow

`agent_node(node_id, manager, task, *, role, parent_agent_id, instructions, inheritance, selected_sources, timeout, token_budget) -> Node`，handler 是一个 `AutonomousAgentNode`，`NodeKind.AGENT`。派生的 Agent 会获得常规协作 Tools，**可能创建自己的专家子级**；只有当整个 Agent 子树进入终态且全部成功，节点才算 COMPLETED。来自 `examples/53_hybrid_agent_node.py` 的核心部分：

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

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/53_hybrid_agent_node.py)

要点：

- `task` 可以是字符串或 `Callable[[WorkflowContext], str]`（这里用 lambda 依据 `context.workflow_input` 生成 prompt）。
- 子 Agent 或任意后代未 COMPLETED 时节点抛 `WorkflowError`（"autonomous agent node failed: ..." / "autonomous agent descendant failed: ..."）。
- 节点成功时返回 `NodeOutput(result.text, {...})`，其中 updates 写入 `hybrid.<node_id>.agent_id`、`hybrid.<node_id>.thread_id`、`hybrid.<node_id>.tokens` 状态键。
- 混合事件转发（`source: "autonomous_agent"`）**只含元数据**（agent_sequence / agent_id / parent_agent_id）；完整的本地细节请查询 `AgentManager`（如 `manager.get(...)`、`manager.event_history()`）。

一个让工作流 Agent 自主派生并汇合专家团队的例子（`examples/55_hybrid_specialist_team.py` 的核心）：lead 角色通过 `spawn_agent` 派生两个 specialist、再用 `wait_agent` 等待并汇总：

```python
workflow = Workflow(
    "team-pipeline",
    [agent_node("team", manager, "coordinate the analysis", role="lead", timeout=2)],
)
run = await WorkflowEngine().run(workflow)
print(run.output)
print("agents:", len(manager.list_agents()) - 1)
```

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/55_hybrid_specialist_team.py)

要点：`manager.list_agents()` 返回所有 `AgentSnapshot`；`agent_node` 里的角色通过 `role="lead"` 传入 `SpawnRequest.role`，工厂据此返回不同的 Agent。

### 16.2 subworkflow_node：嵌套确定性流水线

`subworkflow_node(node_id, workflow, *, engine, input_builder, state_builder) -> Node`，handler 是一个 `SubworkflowNode`，`NodeKind.SUBWORKFLOW`。子工作流使用独立的 `WorkflowEngine`；传入 `engine=WorkflowEngine(store=JSONWorkflowStore(...))` 可获得独立断点。来自 `examples/54_hybrid_subworkflow.py` 的核心部分：

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

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/54_hybrid_subworkflow.py)

要点：

- 子运行 ID 由父运行 ID + 节点 ID 派生（`<parent_run_id>-<node_id>`），例如 `demo-normalize`。
- 节点成功时写入 `hybrid.<node_id>.workflow_id` 与 `hybrid.<node_id>.run_id` 状态键。
- 子工作流事件以 `subworkflow.<event_type>` 前缀、`source: "subworkflow"` 转发（同样只含元数据）。

### 16.3 失败与恢复的级联

父级取消会级联到 `agent_node`（`AutonomousAgentNode.cancel` → `manager.cancel(child)`）与 `subworkflow_node`（`SubworkflowNode.cancel` → `engine.cancel(child_run_id)`）。当失败/恢复必须在父级重试且需要保留已完成的子节点时，给子 `WorkflowEngine` 配上 `JSONWorkflowStore`。来自 `examples/56_hybrid_failure_resume.py` 的核心部分：

```python
failed = await parent_engine.run(parent, run_id="release-run")
print("first:", failed.status)
service_ready = True
resumed = await parent_engine.resume(parent, parent_store.load("release-run"))
print("resumed:", resumed.status, resumed.output)
```

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/56_hybrid_failure_resume.py)

要点：父工作流与子工作流各配一个 `JSONWorkflowStore`；首次运行子 `publish` 因 `service_ready=False` 抛 `ConnectionError` 而失败（父 `FAILED`），修复后 `resume` 从 checkpoint 继续，已完成的 `build` 等节点被保留而非重放。

## 17. API 用法速查（关键签名）

```python
# 自主多智能体
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

# 确定性工作流
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

# 混合编排
agent_node(node_id, manager, task, *, role="worker", parent_agent_id=None, instructions=None,
           inheritance=ContextInheritance.MINIMAL, selected_sources=(), timeout=None,
           token_budget=None) -> Node
subworkflow_node(node_id, workflow, *, engine=None, input_builder=_input, state_builder=None) -> Node

# Router
Router(routes, *, default=None, observer=None)
Router.route(value, *, context=None) -> RouteDecision      # 事件循环内抛 RuntimeError
await Router.aroute(value, *, context=None) -> RouteDecision
Route(name, target, predicate, priority=100, metadata=None)
RouteDecision(route, target, matched, reason, timestamp, metadata)
```

## 18. 事件与流式（Events）

### 18.1 AgentManager 事件

通过 `event_listener` 回调或 `events(after_sequence=...)` 异步迭代 `AgentEvent`（字段：`sequence`、`type`、`agent_id`、`parent_agent_id`、`timestamp`、`payload`）。事件类型：

| 事件 | 触发时机 |
| --- | --- |
| `agent.spawned` | 子 Agent 派生成功（payload 含 `role`、`depth`） |
| `agent.started` | 子 Agent 任务开始执行 |
| `agent.message` | `send_input` 记录一条消息 |
| `agent.resumed` | `resume_agent` 重新派发任务 |
| `agent.completed` | 子 Agent 成功进入 COMPLETED（payload 含 `result`） |
| `agent.failed` | 子 Agent 失败（payload 含 `error_type`） |
| `agent.interrupted` / `agent.cancelled` / `agent.budget_exhausted` / `agent.closed` | 对应终态 |
| `agent.event` | 转发子线程事件（默认跳过 `model.text.delta` / `model.tool_call.delta`，除非 `include_child_deltas=True`） |

另可读取 `manager.event_history(after_sequence=0)` 获取全部已发生事件。

### 18.2 Workflow 事件

`WorkflowRun.events` 保存 `WorkflowEvent`（`sequence`、`type`、`workflow_id`、`run_id`、`node_id`、`timestamp`、`payload`），也可通过 `WorkflowEngine(event_listener=...)` 实时观察：

| 事件 | 触发时机 |
| --- | --- |
| `workflow.started` / `workflow.resumed` | 运行开始 / 从断点恢复 |
| `node.started` / `node.completed` / `node.failed` / `node.skipped` / `node.interrupted` | 节点生命周期 |
| `node.retrying` | 重试前发出（payload 含 `attempt`、`delay_seconds`、`iteration`） |
| `route.selected` | 路由/布尔门节点选中一条边（payload 含 `route`） |
| `workflow.completed` / `workflow.failed` / `workflow.interrupted` | 运行终态 |

### 18.3 Router 事件

`Router` 通过 `observer` 发出 `route.selected` 事件，payload 含 `route`、`target`、`matched`、`reason`、`metadata`，不含被路由的值。

## 19. 错误、超时与重试（Errors / Timeouts / Retries）

### 19.1 多智能体

- 派生/恢复时的预算或校验失败：抛 `MultiAgentError`（例如 active/total/depth limit、token/time budget exhausted、`resume requires queued or explicit input`、`cannot resume an active agent`、`child task and role must be non-empty`、未知 agent ID）。
- 子 Agent 运行时超时（`min(child.timeout, remaining_seconds)`）→ 终态 `FAILED`，`AgentResult.error = "agent timed out"`。
- `wait` / `wait_all` 的 `timeout` 到期**不会抛异常**：返回当前快照，由调用方检查 `status`。
- 子 Agent 工厂抛异常 → `MultiAgentError("child Agent factory failed")`。
- 协作 Tool 名冲突 → `MultiAgentError("Agent has a conflicting collaboration tool")`。

### 19.2 工作流

- 节点 handler 抛异常 → 节点终态 `FAILED`，错误信息 `"<Type>: <msg>"`；随后整批结束后工作流进入 `FAILED`，`run.error` 汇总所有失败节点。
- 重试：`idempotent=True` + `RetryPolicy`；每次重试前发出 `node.retrying`。**未声明 idempotent 却配了 retry 会在构造时抛 `ValueError`**。
- 显式循环：`loop_until` 满足前耗尽 `max_iterations` → 节点失败，`WorkflowError("... reached its max loop iterations ...")`。
- 节点超时：`Node(..., timeout=...)` 对异步 handler 使用 `asyncio.wait_for`。
- 取消：`await engine.cancel(run_id)` 发出取消请求并取消运行中的节点任务 → `INTERRUPTED`。
- DAG 环 / 未知边 / 重复节点 ID → 构造或 `run` 时抛 `WorkflowError`。

### 19.3 Router

- 谓词未返回布尔 → `WorkflowError("route predicate ... did not return bool")`。
- 无匹配且无 `default` → `WorkflowError("router found no matching route and has no default")`。
- 事件循环内调用同步 `route` → `RuntimeError("Router.route cannot run inside an active event loop; use aroute")`。

## 20. 与其他功能组合（Combining）

- **与 Hook**：`AgentManager(..., hooks=HookRegistry())` 在子 Agent 开始/结束时派发 `SUBAGENT_START` / `SUBAGENT_END`。
- **与 Observability**：把 `Observability` 注入每个 Agent，并把 `observer.observe` 作为 `WorkflowEngine(event_listener=...)`，可观察混合编排的完整边界。可参考 `examples/58_observability_trace_metrics.py`。
- **与 RAG/搜索**：子 Agent 工厂可用 `KnowledgeRouter` 为不同角色装配不同的知识工具；`inheritance=SELECTED` 可把 RAG 片段（`source` 标签）选择性传给子 Agent。
- **与 Persona**：工厂可为每个 `role` 返回带不同 `Persona` 的 `Agent`，实现角色化子团队。
- **与持久化 Thread**：`AgentManager` 的每个 Agent 内部都有独立 `Thread`；配合 `SQLiteThreadStore` 可让子 Agent 会话跨重启。
- **与 MCP/插件**：子 Agent 通过工厂获得的工具集可以是 MCP/插件提供的；`expose_tools=False` 时不会自动注入协作 Tools，避免与命名冲突。

## 21. 安全注意事项（Security notes）

- `AgentManager` 协作 Tools 是 `risk="runtime"` 的工具：`expose_tools=True` 时模型可以**自主派生/中断/恢复子 Agent**。只在可信模型或受控提示下开启；需要应用独占控制时用 `expose_tools=False`。
- 子 Agent 继承的上下文（尤其 `FULL`）可能携带敏感信息；`SELECTED` 应作为默认，只选明确需要的来源。
- 预算（`MultiAgentLimits`）是防止失控（无限派生/令牌爆炸）的第一道闸：务必设合理的 `max_total_agents`、`max_depth`、`total_token_budget`、`total_timeout`。
- 子 Agent 工厂返回的 Agent 拥有与根相同的工具/沙箱能力；不要给不可信任务的子 Agent 授予 `full_access` 沙箱。
- 混合编排会执行工作流里声明的任意 handler 代码——只运行可信、已评审的工作流定义。
- `Router` 的 observer 不泄露被路由的值，适合在敏感数据上做可观测路由。

## 22. 故障排查（Troubleshooting）

| 症状 | 原因与处理 |
| --- | --- |
| `RuntimeError: Router.route cannot run inside an active event loop` | 在异步代码里调用了同步 `route`；改用 `await router.aroute(...)`。 |
| `MultiAgentError: multi-agent active agent limit exceeded` | 同时活跃的子 Agent 超过 `max_active_agents`；调大限制或用 `wait_all` 先收尾。 |
| `MultiAgentError: multi-agent depth limit exceeded` | 派生深度超过 `max_depth`；减少嵌套层级。 |
| `MultiAgentError: cannot resume an active agent` | 对 RUNNING/PENDING 的子 Agent 调了 `resume_agent`；先 `wait` 到终态。 |
| `MultiAgentError: resume requires queued or explicit input` | 恢复时既无排队消息也未传 `message`；补一条输入。 |
| `ValueError: retried nodes must explicitly declare idempotent=True` | 配了 `RetryPolicy` 但 `Node` 未声明 `idempotent=True`；如处理器可安全重放则加上。 |
| `ValueError: max_iterations greater than one requires loop_until` | `max_iterations > 1` 缺 `loop_until`；补上终止谓词。 |
| `WorkflowError: unsupported graph cycle; use Node.loop_until ...` | 图里有环；改成单节点显式循环。 |
| `WorkflowError: node ... selected unknown route ...` | 节点产生了未在边上声明的路由标签；补齐对应的 `Edge(..., route=...)`。 |
| `WorkflowError: checkpoint nodes do not match the workflow` | `resume` 的 checkpoint 来自不同的 workflow 结构；确保 `workflow_id` 与节点集合一致。 |
| 子 Agent 永远处于活跃态、`wait_all` 不返回 | 检查 `timeout` 与全局 `total_timeout`；必要时 `cancel`。 |

## 23. 链接（Links）

- 可运行示例：`examples/43_autonomous_research.py`、`44_coding_team.py`、`45_parallel_critics.py`、`46_child_followup.py`、`47_agent_budget_cancel.py`、`48_workflow_sequence.py`、`49_workflow_parallel.py`、`50_workflow_conditional.py`、`51_workflow_router.py`、`52_workflow_retry_loop.py`、`53_hybrid_agent_node.py`、`54_hybrid_subworkflow.py`、`55_hybrid_specialist_team.py`、`56_hybrid_failure_resume.py`、`72_router_priority.py`、`73_router_async_context.py`、`74_router_observation.py`。
- 相关 Internals：多智能体与工作流的内部设计、数据模型、并发/取消与失败模型。
- API 参考：`AgentManager`、`MultiAgentLimits`、`SpawnRequest`、`Workflow`、`Node`、`Edge`、`WorkflowEngine`、`JSONWorkflowStore`、`Router`、`Route`、`agent_node`、`subworkflow_node` 的签名与字段。
