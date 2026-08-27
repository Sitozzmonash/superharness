---
id: guide-part3-sessions
title: 用户指南 · 第三部分：会话（Sessions）
sidebar_position: 3
description: 线程基础、多轮对话、SQLite 持久化、流式事件、中断/引导/取消、上下文压缩，以及 AGENTS.md 发现。
---

# 第三部分：会话（Sessions / Threads）

本部分讲解如何组织一次会话的全部状态：从最简单的单次问答，到可以跨进程重启的持久化多轮对话，再到对正在执行的一轮进行流式观察、中断、引导、取消与压缩。所有内容都基于 `src/super_harness` 的真实实现，示例代码可以直接从 `examples/` 目录运行。

## 1. 这是什么 / 何时使用

在 Super Harness 中，**Thread（线程）** 是一次会话的完整状态容器：它保存了有序的对话历史（`messages`）、每一轮的执行记录（`turns`）、压缩产生的摘要（`summaries`）、上下文片段、元数据，以及所属的提供商与工具配置。

**Turn（轮次）** 是 Thread 内的一次用户输入及其完整执行过程：一次输入会经历模型调用、可能的工具调用循环，最终到达一个终态（完成 / 失败 / 中断 / 取消）。一个 Thread 在同一时刻只允许有一个活跃的 Turn（并发激活会被拒绝）。

**何时使用：**

- 只需要一次性问答 → 直接用 `Agent.run(...)` / `Agent.arun(...)`，它们会内部开启一个新 Thread。
- 需要多轮上下文（后面的轮次要记得前面的内容）→ 复用同一个 Thread：`thread = agent.thread()` 然后反复调用 `thread.run(...)`。
- 需要跨进程 / 跨重启保留会话 → 配置 `SQLiteThreadStore`，然后用 `agent.resume(thread_id)` 恢复。
- 需要在同一会话上开出一条独立分支而不污染原会话 → `agent.fork(thread_id)` 或 `thread.fork()`。
- 需要在模型还在生成时实时看到文本、或者在安全检查点介入 → 用流式事件与 `TurnHandle`（`astream`、`steer`、`interrupt`、`cancel`）。
- 需要控制上下文窗口的增长 → 手动或自动 `compact()`。
- 需要让模型了解项目规则 → 通过 `cwd` 的 `AGENTS.md` 发现，或用 `ContextFragment` 显式注入。

## 2. 前置条件（Prerequisites）

- 安装：在仓库根目录执行 `pip install -e .`。
- 需要真实模型时，设置环境变量 `DEEPSEEK_API_KEY`（默认的中国大陆可用提供商为 `DeepSeekProvider`）。
- 大多数示例都使用自定义的本地 `Provider`（例如示例里的 `LocalProvider` / `BlockingProvider` / `OfflineProvider`），它们不依赖任何网络，可以直接运行。
- 异步 API 需要一个正在运行的事件循环；不要在活跃事件循环中调用同步方法（同步方法会抛出 `RuntimeError`）。
- 使用持久化功能前先决定 SQLite 数据库文件的路径（例如 `threads.db`）。

## 3. 快速开始（Quick start）

最简多轮会话：

```python
from super_harness import Agent, DeepSeekProvider

agent = Agent(DeepSeekProvider(), instructions="Answer concisely.")
thread = agent.thread()

first = thread.run("What is 2 + 2?")
second = thread.run("Now double the previous answer.")
print(first.text)
print(second.text)
```

要点：

- `agent.thread()` 返回一个新的、独立的 `Thread`；同一个 Thread 上的多次 `run` 会自动携带之前的历史。
- `Agent.run(...)` 是 `agent.thread().run(...)` 的简写，每次都从零开始，不保留历史。
- 运行完记得 `await agent.aclose()`（异步场景）或让进程正常退出（同步场景）。

## 4. 配置（Configuration）

### 4.1 环境变量

| 环境变量 | 用途 | 默认 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | `DeepSeekProvider` 的请求时凭据 | 无（未设置会报错） |

凭据在请求时从变量中读取，**永远不会**写入事件或持久化数据。

### 4.2 Agent 构造参数（与 Thread 相关）

```python
agent = Agent(
    provider,
    *,
    instructions=None,               # 开发者指令，作为每条请求开头的 DEVELOPER 消息
    max_model_steps=8,               # 单轮内最大模型步骤数（工具循环上限）
    context=(),                      # 初始 ContextFragment 列表
    cwd=None,                        # 从该目录向上查找 AGENTS.md 项目规则
    agents_loader=None,              # 自定义 AGENTS.md 加载器（默认 AgentsMdLoader）
    store=None,                      # SQLiteThreadStore，启用持久化
    compaction_threshold_chars=100_000,  # 自动压缩阈值（字符）
    persona=None,                    # 人设，见人设章节
)
```

### 4.3 Thread 相关属性

创建出的 `Thread` 暴露下列可读写字段：`thread_id`、`parent_thread_id`、`messages`、`turns`、`summaries`、`metadata`、`archived`、`created_at`、`updated_at`、`max_model_steps`、`compaction_threshold_chars`、`compaction_retain_messages`，以及只读属性 `active_turn_id`。

其中 `compaction_retain_messages` 默认 `8`，控制压缩时保留多少条最近消息。

## 5. 线程基础与多轮对话（Thread basics & multi-turn）

### 5.1 这是什么

`Thread` 是复用的对话上下文。只要你反复调用**同一个** Thread 的 `run`/`arun`，历史就会累积；调用 `Agent.run` 则每次新建。

### 5.2 基础例子（Basic）

```python
from super_harness import Agent, DeepSeekProvider

agent = Agent(DeepSeekProvider(), instructions="Answer concisely.")
thread = agent.thread()

thread.run("My name is Ada.")
thread.run("I work on the release tooling.")
reply = thread.run("What do you know about me?")
print(reply.text)  # 会引用前两轮的上下文
```

### 5.3 真实场景例子（Real-world）

多轮客服或诊断对话，把用户的偏好逐步累积到同一会话：

```python
import asyncio
from super_harness import Agent, DeepSeekProvider

async def main() -> None:
    agent = Agent(DeepSeekProvider(), instructions="Be brief and helpful.")
    thread = agent.thread()

    thread.run("Preferred deployment: Render, region us-east.")
    thread.run("Budget under $50/month.")
    reply = thread.run("Which plan fits my requirements?")
    print(reply.text)

    await agent.aclose()

if __name__ == "__main__":
    asyncio.run(main())
```

### 5.4 进阶/组合例子（Advanced）

在同一 Thread 上混合结构化输出（`output_schema`）与工具，让每一步都能看到上一步的结果：

```python
import asyncio
from super_harness import Agent, DeepSeekProvider, tool

@tool
def add(left: int, right: int) -> int:
    """Add two integers."""
    return left + right

SCHEMA = {
    "type": "object",
    "properties": {"total": {"type": "integer"}},
    "required": ["total"],
}

async def main() -> None:
    agent = Agent(DeepSeekProvider(), tools=[add], instructions="Use the add tool.")
    thread = agent.thread()
    response = await thread.arun("add 20 and 22", output_schema=SCHEMA)
    print(response.output_json)  # 归一化后的结构化结果
    await agent.aclose()

if __name__ == "__main__":
    asyncio.run(main())
```

`output_schema` 让模型按 JSON Schema 返回结构；`thread.messages` 会保留完整的对话历史供后续轮次使用。

## 6. 持久化线程（Durable SQLite threads）

### 6.1 这是什么 / 何时使用

`SQLiteThreadStore(path)` 把 Thread 的完整快照（消息、轮次、摘要、元数据、父子关系、归档标记）写入 SQLite，使用 WAL 模式与事务。它用于：

- 进程重启后恢复会话（`agent.resume(thread_id)`）。
- 在会话上开出分支而不影响原会话（`agent.fork(thread_id)`）。
- 保留历史但阻止新轮次（`thread.archive()`）。
- 通过 `store.ids()` 列出所有线程。

只要给 `Agent` 传入了 `store`，`agent.thread()` 会**立即**持久化。

### 6.2 基础例子（Basic）

```python
from super_harness import Agent, SQLiteThreadStore

with SQLiteThreadStore("threads.db") as store:
    agent = Agent(provider, store=store)
    thread = agent.thread()
    thread.run("remember this")
    print(thread.thread_id)          # 稳定的 UUID，可用于重启后恢复
    print(store.ids())               # 列出所有未归档线程
```

### 6.3 真实场景例子（Real-world）

跨进程重启的完整生命周期：写入、关闭、重新打开、恢复、分叉。

```python
import asyncio
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

from super_harness import Agent, SQLiteThreadStore
from super_harness.models import (
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
    ModelStreamEventType,
)

class LocalProvider:
    name = "local"
    capabilities = ModelCapabilities()

    async def complete(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse("saved")

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        yield ModelStreamEvent(ModelStreamEventType.STARTED)
        yield ModelStreamEvent(ModelStreamEventType.COMPLETED, response=ModelResponse("saved"))

    async def aclose(self) -> None:
        return None

async def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "threads.db"
        with SQLiteThreadStore(database) as store:
            agent = Agent(LocalProvider(), store=store)
            thread = agent.thread()
            await thread.arun("remember this")
            thread_id = thread.thread_id

        # 模拟进程重启：用同一个数据库文件重新打开
        with SQLiteThreadStore(database) as store:
            agent = Agent(LocalProvider(), store=store)
            resumed = agent.resume(thread_id)
            forked = resumed.fork()
            print(resumed.thread_id, resumed.messages[-1].content)
            print("fork", forked.thread_id, "parent", forked.parent_thread_id)

if __name__ == "__main__":
    asyncio.run(main())
```

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/07_durable_thread/main.py)

### 6.4 进阶/组合例子（Advanced）

在 `resume` 之后继续对话，并利用 `agent.fork(thread_id)`（等价于 `resume` + `fork`）从历史会话开出一条独立分支，配合 `store.ids()` 管理多个会话：

```python
from super_harness import Agent, SQLiteThreadStore

with SQLiteThreadStore("threads.db") as store:
    agent = Agent(provider, store=store)

    # 列出历史会话，挑一个继续
    for thread_id in store.ids():
        continued = agent.resume(thread_id)
        continued.run("continue from where we left off")

    # 直接从一个会话分叉，产生带 parent_thread_id 的子级
    branch = agent.fork(thread_id)
    print(branch.parent_thread_id)  # 指向被分叉的父线程
```

**关于归档**：`thread.archive()` 会把 `archived` 置为 `True` 并持久化。归档后任何 `run`/`arun`/`astream` 都会抛出 `RuntimeError("cannot run an archived thread")`，但历史仍可通过 `store.load(thread_id)` 读取；`store.ids(include_archived=True)` 可以列出归档线程，`store.archive(thread_id, archived=False)` 可以解除归档。

## 7. 流式与事件（Streaming & events）

### 7.1 这是什么

运行时是原生异步的。`astream` 逐条产出**不可变**的 `Event` 对象（`@dataclass(frozen=True)`），便于实时渲染与关联。文本以 `model.text.delta` 到达，随后是 `model.completed` 与 `turn.completed`。`arun` 只是消费整个流并返回最终的归一化 `ModelResponse`。

### 7.2 基础例子（Basic）

```python
import asyncio

from super_harness import Agent, DeepSeekProvider

async def main() -> None:
    provider = DeepSeekProvider()
    agent = Agent(provider)
    try:
        async for event in agent.astream("Give three concise agent safety rules."):
            if event.type == "model.text.delta":
                print(event.payload["delta"], end="", flush=True)
        print()
    finally:
        await agent.aclose()

if __name__ == "__main__":
    asyncio.run(main())
```

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/02_streaming/main.py)

### 7.3 真实场景例子（Real-world）

在命令行/聊天 UI 中流式渲染文本增量，并统计用量：

```python
import asyncio
from super_harness import Agent, DeepSeekProvider

async def main() -> None:
    agent = Agent(DeepSeekProvider())
    try:
        usage = None
        async for event in agent.astream("Explain concurrency in one paragraph."):
            if event.type == "model.text.delta":
                print(event.payload["delta"], end="", flush=True)
            elif event.type == "model.completed":
                usage = event.payload.get("usage")
        print()
        print("usage:", usage)
    finally:
        await agent.aclose()

if __name__ == "__main__":
    asyncio.run(main())
```

### 7.4 进阶/组合例子（Advanced）

用 `thread.start(input)` 得到 `TurnHandle`，通过 `handle.events()` 在后台消费全部事件（包括工具生命周期），从而追踪一轮里的模型与工具步骤：

```python
import asyncio
from super_harness import Agent, DeepSeekProvider

async def main() -> None:
    agent = Agent(DeepSeekProvider())
    try:
        thread = agent.thread()
        handle = thread.start("Summarize the event model briefly.")
        async for event in handle.events():
            print(event.type, dict(event.payload) if event.payload else "")
        response = await handle.wait()
        print("done:", response.text[:80])
    finally:
        await agent.aclose()

if __name__ == "__main__":
    asyncio.run(main())
```

### 7.5 事件类型一览

| 事件类型 | 触发时机 | 关键 payload |
| --- | --- | --- |
| `turn.started` | 一轮开始 | `thread_id`, `turn_id` |
| `model.started` | 模型调用开始 | `provider`, `model`, `step` |
| `model.text.delta` | 文本增量 | `delta`, `step` |
| `model.tool_call.delta` | 工具调用参数流式增量 | `index`, `name`, `delta` |
| `model.completed` | 模型完成一次响应 | `response`, `usage`, `tool_calls`, `step` |
| `model.failed` | 模型调用抛错 | `error_class`, `message`, `step` |
| `tool.started` | 工具开始执行 | `name`, `arguments` |
| `tool.completed` / `tool.failed` | 工具结束 | `result`, `success` |
| `turn.steered` | 收到 steer 引导 | `instruction` |
| `turn.completed` | 一轮正常完成 | `response` |
| `turn.failed` | 一轮失败 | `error_type`, `message` |
| `compaction.started` / `compaction.completed` | 压缩前后 | 见压缩章节 |

## 8. 中断、引导与取消（Interrupt, steer & cancel）

### 8.1 这是什么 / 何时使用

`TurnHandle` 是对一个活跃 Turn 的句柄，提供三种控制手段：

- `await handle.steer(instruction)`：在安全检查点**引导**正在运行的一轮（追加一条 `<steering>` 指令），不终止它。
- `await handle.interrupt()`：请求中断当前一轮，记录 `INTERRUPTED` 终态。
- `handle.cancel()`：硬取消底层任务，记录 `CANCELLED` 终态。

`steer` 与 `interrupt` 都需要等 Turn 真正启动（内部等待 ready），且会校验 `turn_id` 是否有效。

### 8.2 基础例子（Basic）

```python
import asyncio
from super_harness import Agent

async def main() -> None:
    thread = Agent(provider).thread()
    handle = thread.start("long operation")
    iterator = handle.events().__aiter__()
    print((await anext(iterator)).type)  # turn.started
    await handle.interrupt()
    try:
        async for event in iterator:
            print(event.type)
    except asyncio.CancelledError:
        print("turn interrupted")

if __name__ == "__main__":
    asyncio.run(main())
```

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/09_compaction_and_control/main.py)

### 8.3 真实场景例子（Real-world）

运行一个可能很长的任务，实时展示进度；一旦用户点击"停止"，就中断；若在安全检查点给出新指令，则引导模型调整方向：

```python
import asyncio
from super_harness import Agent, DeepSeekProvider

async def main() -> None:
    agent = Agent(DeepSeekProvider())
    try:
        thread = agent.thread()
        handle = thread.start("Draft a long release plan.")
        async for event in handle.events():
            if event.type == "model.text.delta":
                print(event.payload["delta"], end="", flush=True)
            # 安全检查点：引导模型补充测试部分
            if event.type == "turn.started":
                await handle.steer("After drafting, always add a testing section.")
        response = await handle.wait()
        print("\nfinal:", response.text[:60])
    finally:
        await agent.aclose()

if __name__ == "__main__":
    asyncio.run(main())
```

> 注意：`steer` 引导会追加一条 `<steering>` 用户消息，并在之后发出 `turn.steered` 事件；它适合在模型开始生成前调整方向，而不是在文本已经输出后强行改写。

### 8.4 进阶/组合例子（Advanced）

超时控制：给一轮任务设置外部截止时间，超时则 `cancel()`，并把取消后的终态打印出来：

```python
import asyncio
from super_harness import Agent, DeepSeekProvider

async def main() -> None:
    agent = Agent(DeepSeekProvider())
    try:
        thread = agent.thread()
        handle = thread.start("Write a very long analysis.")
        try:
            await asyncio.wait_for(handle.wait(), timeout=30)
        except asyncio.TimeoutError:
            handle.cancel()
            print("cancelled after timeout")
        # 检查 Thread 记录的终态
        for turn in thread.turns:
            print(turn.status.value)
    finally:
        await agent.aclose()

if __name__ == "__main__":
    asyncio.run(main())
```

**并发约束**：一个 Thread 在同一时刻只允许一个活跃 Turn。若已有活跃轮次，再次 `run`/`start`/`astream` 会抛出 `RuntimeError("thread already has an active turn")`。因此在启动后台执行后，要么消费完 `handle.events()`，要么 `await handle.wait()`，再发起下一轮。

## 9. 压缩（Compaction）

### 9.1 这是什么 / 何时使用

长时间会话会累积大量历史，逼近上下文窗口。`thread.compact(summary=None, *, retain_messages=None)` 会用一条**摘要**替换旧的历史前缀，把新近的若干条消息保留下来。

- 默认的 `extractive_summary` 是确定性的抽取式摘要（无需额外模型请求），并且**特意保留**提到 `permission` / `approval` / `sandbox` / `secret` / `credential` / `denied` 的行，避免丢失安全与权限状态。
- 也可以传入你自己的 `summary` 字符串。
- `retain_messages` 覆盖 `compaction_retain_messages`（默认 `8`）。
- 自动压缩：当 `_history_characters()`（所有消息内容长度之和）超过 `compaction_threshold_chars` 时，新一轮会在开始前自动压缩。
- `compact` 返回 `(Event, Event)`：`compaction.started` 与 `compaction.completed`。

### 9.2 基础例子（Basic）

```python
from super_harness import Agent

thread = Agent(provider).thread()
# 灌入 12 条旧消息
thread.messages.extend(...)          # 见完整示例
for event in thread.compact(retain_messages=3):
    print(event.type, dict(event.payload))
```

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/09_compaction_and_control/main.py)

### 9.3 真实场景例子（Real-world）

用应用提供的摘要替换旧前缀，只保留最新 1 条消息：

```python
from collections.abc import AsyncIterator

from super_harness import Agent
from super_harness.models import (
    Message,
    MessageRole,
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
)

class OfflineProvider:
    name = "offline"
    capabilities = ModelCapabilities()

    async def complete(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse()

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        if False:
            yield ModelStreamEvent("started")

    async def aclose(self) -> None:
        pass

thread = Agent(OfflineProvider()).thread()
thread.messages.extend(
    (
        Message(MessageRole.USER, "Remember release policy"),
        Message(MessageRole.ASSISTANT, "Recorded"),
    )
)
print([event.type for event in thread.compact("Release policy was recorded.", retain_messages=1)])
```

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/84_compaction_custom_summary.py)

### 9.4 进阶/组合例子（Advanced）

检查压缩的保留行为：保留最新 `retain_messages` 条，其余进入摘要，并读取 `thread.summaries` 中的元信息：

```python
from collections.abc import AsyncIterator

from super_harness import Agent
from super_harness.models import Message, MessageRole, ModelCapabilities, ModelRequest, ModelResponse, ModelStreamEvent

class OfflineProvider:
    name = "offline"
    capabilities = ModelCapabilities()

    async def complete(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse()

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        if False:
            yield ModelStreamEvent("started")

    async def aclose(self) -> None:
        pass

thread = Agent(OfflineProvider()).thread()
thread.messages.extend(Message(MessageRole.USER, f"message {index}") for index in range(8))
thread.compact(retain_messages=2)
print(thread.summaries[-1].summarized_messages, len(thread.messages))
```

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/85_compaction_retention.py)

**自动压缩配置**：

```python
from super_harness import Agent

agent = Agent(
    provider,
    compaction_threshold_chars=50_000,   # 历史超过 50k 字符就自动压缩
)
```

**约束**：`retain_messages` 必须至少为 `1`，否则抛出 `ValueError`。压缩前缀来自 `messages[:count]`，`count = max(len(messages) - retain, 0)`；若 `count == 0`，则只发出 `compaction.started`/`compaction.completed` 事件而不真正改动历史。每次压缩会把 `summarized_messages` 的计数累计进 `ContextSummary`。

## 10. 上下文片段与 AGENTS.md 发现（Context fragments & AGENTS.md）

### 10.1 这是什么 / 何时使用

`ContextFragment` 是一种带类型的上下文单元，携带**类型（kind）、来源（source）、角色（role）、优先级（priority）与元数据**。多个片段由 `ContextAssembler` 排序、去重并做总字数上限约束后注入每条请求。

`AGENTS.md` 发现是项目规则注入的便捷机制：给 `Agent` 传 `cwd`，运行时从最近的 `.git` 根目录向下直到 `cwd`，在每个目录中查找 `AGENTS.override.md` 或 `AGENTS.md`（同目录内 override 优先），**绝不会越过 `cwd` 向上查找**。默认总上限为 32 KiB。

### 10.2 基础例子（Basic）

```python
from super_harness import Agent, ContextFragment, ContextKind

agent = Agent(
    provider,
    context=[
        ContextFragment(ContextKind.PROJECT, "Release cadence is monthly.", "docs/releases"),
        ContextFragment(ContextKind.RAG, "Team prefers Python.", "knowledge/team"),
    ],
)
thread = agent.thread()
print([e.priority for e in thread.debug_context().entries])
```

`ContextKind` 取值：`RUNTIME`、`DEVELOPER`、`PROJECT`、`PERSONA`、`SKILL`、`MEMORY`、`RAG`、`SUMMARY`。优先级默认按类型（`ContextPriority`），也可显式传入 `priority=` 覆盖。

### 10.3 真实场景例子（Real-world）

层级式 `AGENTS.md` 发现并检查脱敏后的上下文快照：

```python
import tempfile
from pathlib import Path

from super_harness import Agent, DeepSeekProvider

def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / ".git").mkdir()
        nested = root / "src"
        nested.mkdir()
        (root / "AGENTS.md").write_text("Root rule", encoding="utf-8")
        (nested / "AGENTS.override.md").write_text(
            "Nested rule; api_" + "key=example-sensitive-value", encoding="utf-8"
        )
        thread = Agent(DeepSeekProvider(), cwd=str(nested)).thread()
        for entry in thread.debug_context().entries:
            print(entry.priority, entry.source, entry.content)

if __name__ == "__main__":
    main()
```

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/08_agents_context_debug/main.py)

观察：因为 `cwd = nested`，发现范围是 `root` → `nested`，两个文件都被加载；`AGENTS.override.md` 的内容里出现 `api_key=example-sensitive-value`，而 `debug_context()` 输出经过脱敏，`entry.content` 中的密钥会被替换为 `[REDACTED]`。

### 10.4 进阶/组合例子（Advanced）

显式构造 `AgentsMdLoader` 并自定义发现行为，或直接读取调试快照的结构化字段：

```python
from super_harness import Agent, AgentsMdLoader

# 自定义 loader：把总上限改小、只认 AGENTS.md
loader = AgentsMdLoader(root_markers=(".git",), max_bytes=16_384, filenames=("AGENTS.md",))
agent = Agent(provider, cwd="./src", agents_loader=loader)

thread = agent.thread()
snapshot = thread.debug_context()
print(snapshot.thread_id)
print(snapshot.history_messages)     # 当前历史消息数
print(snapshot.estimated_characters) # 上下文估算总字符数（含片段与摘要）
for entry in snapshot.entries:
    print(entry.kind.value, entry.source, entry.priority)
```

`thread.debug_context()` 返回 `ContextDebugSnapshot(thread_id, entries, history_messages, estimated_characters)`，其中 `entries` 是 `ContextDebugEntry(kind, source, role, priority, content)`，内容已经过 `redact_text` 脱敏。RAG/记忆片段被视为**数据而非指令权威**，不能覆盖开发者或项目指令。

## 11. API 用法速查（API quick reference）

```python
# Agent
agent.thread()                                  # -> Thread（若配置 store 则立即持久化）
agent.resume(thread_id)                         # -> Thread（需 store）
agent.fork(thread_id)                           # -> Thread（= resume + fork）
agent.run(input, *, tools=(), output_schema=None)      # -> ModelResponse（新线程，同步）
agent.arun(input, *, tools=(), output_schema=None)     # -> ModelResponse（异步）
agent.stream(input, *, tools=(), output_schema=None)   # -> Iterator[Event]
agent.astream(input, *, tools=(), output_schema=None)  # -> AsyncIterator[Event]

# Thread
thread.run(input, *, tools=(), output_schema=None)     # -> ModelResponse
thread.arun(input, *, tools=(), output_schema=None)    # -> ModelResponse
thread.stream(input, *, tools=(), output_schema=None)  # -> Iterator[Event]
thread.astream(input, *, tools=(), output_schema=None) # -> AsyncIterator[Event]
thread.start(input, *, tools=(), output_schema=None)   # -> TurnHandle
thread.compact(summary=None, *, retain_messages=None)  # -> tuple[Event, Event]
thread.acompact(summary=None, *, retain_messages=None) # -> tuple[Event, Event]（异步，会触发 hooks）
thread.debug_context()                                  # -> ContextDebugSnapshot
thread.archive()                                        # 归档（阻止新轮次）
thread.fork(*, thread_id=None)                          # -> Thread（带 parent_thread_id）
thread.aclose()                                         # 触发 SESSION_END hook

# TurnHandle
handle.events()                     # -> AsyncIterator[Event]
await handle.wait()                 # -> ModelResponse
await handle.steer(instruction)     # 在检查点引导
handle.cancel()                     # 硬取消
await handle.interrupt()            # 中断

# SQLiteThreadStore
SQLiteThreadStore(path)             # 可用作上下文管理器
store.save(thread)                  # 持久化快照
store.load(thread_id)               # -> ThreadSnapshot
store.archive(thread_id, archived=True)
store.ids(include_archived=False)   # -> tuple[str, ...]
store.close()
```

## 12. 错误 / 超时 / 重试（Errors / timeouts / retries）

- **模型错误**：传输错误、HTTP 429 与 HTTP 5xx 可重试（有界预算）；身份认证与其他 HTTP 4xx 立即以 `ModelError` 失败。
- **无法运行归档线程**：对 `archived=True` 的线程调用任何 `run`/`arun`/`astream` 抛出 `RuntimeError("cannot run an archived thread")`。
- **并发冲突**：已有活跃 Turn 时再次启动抛出 `RuntimeError("thread already has an active turn")`。
- **空输入**：`turn input must be non-empty`（`ValueError`）。
- **空引导指令**：`handle.steer("")` 抛出 `ValueError`。
- **压缩保留数过小**：`retain_messages < 1` 抛出 `ValueError`。
- **恢复未知线程**：`store.load(unknown_id)` 抛出 `KeyError`。
- **同步方法进入活跃事件循环**：抛出 `RuntimeError`，提示改用异步 API。
- **超时**：运行时内部有模型步骤上限 `max_model_steps`（默认 8）；超出会以 `ToolError("tool loop exceeded maximum ...")` 终止。应用层超时用 `asyncio.wait_for(handle.wait(), timeout=...)` 配合 `handle.cancel()`。
- **取消语义**：`interrupt` 记录 `INTERRUPTED`，`cancel` 记录 `CANCELLED`；`resume` 时发现历史里有 `pending/running/waiting_tool` 的轮次会统一标记为 `INTERRUPTED` 并写入 `"interrupted before resume"`。

## 13. 与其他功能组合（Combining）

- **与工具/审批**：同一 Thread 上的多轮可以持续使用 `tools` 与 `approval` 策略；工具结果追加进 `thread.messages`。
- **与 Hooks**：`_astream` 在轮次生命周期会派发 `SESSION_START`、`USER_PROMPT`、`TURN_START`、`BEFORE_MODEL`、`AFTER_MODEL`、`TURN_END`、`ERROR`、`SESSION_END`；压缩会派发 `PRE_COMPACT` / `POST_COMPACT`（`acompact`）。可以用 Hooks 做策略拦截与观测。
- **与可观测性**：把 `observer` 传给 `Agent`，`astream` 的每个事件都会经过 `observer.observe(event)`，可接入 JSONL / OpenTelemetry。
- **与持久化记忆**：把 `SQLiteThreadStore` 与 `MemoryManager` 结合，`thread.messages` 作为持久的线程本地对话记忆，长期事实交给 `SQLiteMemoryStore`。
- **与 Persona**：`Agent(..., persona=...)` 会把非机密的人设元数据随新 Thread 存储；`fork` 会深拷贝 `metadata`。
- **与多智能体**：`AgentManager` 的每个子 Agent 各自持有 Thread；`fork`/`resume` 可用于隔离不同实验分支。

## 14. 安全注意事项（Security notes）

- `debug_context()` 输出经过 `redact_text` 脱敏（匹配 `api_key`/`token`/`secret`/`password` 等以及 `sk-...` 形态），不要把未脱敏的 `context` 片段直接打印到日志。
- 默认的抽取式压缩**保留**安全相关行（`permission`/`approval`/`sandbox`/`secret`/`credential`/`denied`），避免在压缩后丢失权限状态；自定义 `summary` 时注意别丢弃这类信息。
- SQLite 数据库文件包含完整对话历史与摘要，视为敏感数据，按你应用的安全策略存放与备份。
- `store.ids()` 默认只列未归档线程；归档线程的历史仍在磁盘上，只是不可再运行。
- 恢复会话使用稳定 ID，不要在日志或外部系统里泄漏 `thread_id` 以外的未脱敏内容。

## 15. 故障排查（Troubleshooting）

- **同步方法报 `RuntimeError: sync API cannot run inside an active event loop`** → 改用 `arun`/`astream`/`await handle.wait()`。
- **`thread already has an active turn`** → 上一轮还没结束。消费完 `handle.events()` 或 `await handle.wait()` 后再发起新一轮；不要在后台 handle 仍活跃时重复 `start`。
- **`cannot run an archived thread`** → 该线程已归档。如需继续，用 `store.archive(thread_id, archived=False)` 解除归档。
- **`Agent.resume requires a SQLiteThreadStore`** → 构造 `Agent` 时忘了传 `store=`。
- **`unknown thread '<id>'`（KeyError）** → `thread_id` 不存在于该数据库，或换了数据库文件。
- **恢复后上下文不对** → 确认你给 `resume` 的 `Agent` 配置了与原始会话相同的 `instructions`、`context`、`cwd`/`agents_loader`；`resume` 恢复的是历史消息/轮次/摘要，而上下文片段来自当前 `Agent` 的配置。
- **压缩后仍超窗口** → 提高 `retain_messages` 或降低 `compaction_threshold_chars`；确认触发的是自动压缩（历史字符数超过阈值）。
- **`steer` 报 `turn is no longer active`** → 引导必须发生在 Turn 仍活跃期间；模型已结束就来不及引导。
- **流里没看到 `model.completed`** → 若消费者提前 break，会触发 `GeneratorExit` 并把该轮标记为 `INTERRUPTED`；完整消费整个流即可。

## 16. 链接（Links）

- 可运行示例（本页引用）：
  - [07_durable_thread/main.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/07_durable_thread/main.py)
  - [08_agents_context_debug/main.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/08_agents_context_debug/main.py)
  - [09_compaction_and_control/main.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/09_compaction_and_control/main.py)
  - [84_compaction_custom_summary.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/84_compaction_custom_summary.py)
  - [85_compaction_retention.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/85_compaction_retention.py)
  - [02_streaming/main.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/02_streaming/main.py)
- 相关页面：[API 参考](../api-reference.md) · [示例索引](../examples.md) · [故障排查](../troubleshooting.md) · [用户指南 Part I](../guide/part1-start.md)
- 相关 Internals：线程运行时、持久化与压缩的底层原理详见 Internals 章节。
