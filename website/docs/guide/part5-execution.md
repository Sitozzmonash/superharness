---
id: guide-part5-execution
title: 用户指南 Part V —— 执行：工具、沙箱与审批
sidebar_position: 5
description: 函数工具（@tool）与工具循环、动态工具注册、内置文件/Shell/Python 工具、本地与 Docker 沙箱、审批策略的完整用法。
---

# Part V 执行：工具、沙箱与审批

本部分是用户指南的执行篇，覆盖让 Agent 真正「动手做事」的全部机制：把 Python 函数暴露给模型调用的函数工具（function tools）、运行时自动驱动的工具循环（tool loop）、可在应用运行期间动态注册与延迟加载的工具注册表（`ToolRegistry`）、开箱即用的文件/搜索/Shell/Python 内置工具、限制工具访问范围的本地与 Docker 沙箱，以及执行前的审批与权限策略（Approval）。

## 1. 这是什么 / 何时使用

| 功能 | 是什么 | 何时使用 |
| --- | --- | --- |
| 函数工具（`@tool`） | 用装饰器把带类型注解的普通 Python 函数变成模型可见、可调用的 `Tool` | 需要让模型调用业务函数、API、数据库或任意自有能力 |
| 工具循环（tool loop） | `Agent`/`Thread` 自动完成「模型请求 → 校验 → 审批 → 执行 → 结果回填 → 模型继续」的循环 | 需要端到端跑通一次带调用的对话，且不关心每步细节 |
| 动态工具（`ToolRegistry`） | 运行时注册/卸载/延迟加载工具；延迟加载只发布元数据，选中后才导入 | 插件体系、按需加载重型依赖、应用运行期间扩展能力 |
| 内置工具 | 沙箱感知的文件读/写/搜索、Shell、Python 执行工具 | 需要快速获得文件与进程能力，且不想自己写工具函数 |
| 沙箱（Sandbox） | `LocalSandbox`/`DockerSandbox` 统一管理工作区路径策略与子进程执行 | 需要约束工具能读写的路径、能执行的进程 |
| 审批（Approval） | `ApprovalPolicy` 在执行前对每次调用给出 ALLOW/DENY | 高风险写操作、生产环境、需要人工或应用层把关 |

这些机制是分层组合的：`Tool` 定义能力，`ToolRegistry` 管理能力，`ToolExecutor` 负责校验/审批/超时/执行/输出截断，`Agent` 把整条链路接入对话循环，`Sandbox` 限定文件与进程边界，`ApprovalPolicy` 在调用前把关。可以只用一个环节（例如直接 `ToolExecutor` 执行，完全不经模型），也可以全部串起来。

## 2. 前置条件

- Python 3.11+，并以可编辑模式安装：`pip install -e .`。
- 需要使用模型对话（`Agent.arun`/`run`）时，配置提供商凭据；以 DeepSeek 为例设置 `DEEPSEEK_API_KEY`。
- 仅使用 `ToolExecutor` + 注册表 + 沙箱的纯执行链路不需要任何模型凭据，示例 `examples/05_approval_and_registry`、`examples/06_builtin_tools` 均属于此类。
- 使用 `DockerSandbox` 时，需要在 PATH 中可用 `docker` CLI，且宿主机已具备所需镜像（框架从不隐式拉取镜像）。
- 示例源码位于仓库根目录 `examples/`，前 9 个为带 `main.py` 的目录（`01_`–`09_`），其余为单个 `.py` 文件。

## 3. 快速开始

最短路径：定义一个 `@tool` 函数，传给 `Agent(provider, tools=[...])`，然后运行。

```python
from super_harness import Agent, DeepSeekProvider, tool

@tool
def add(left: int, right: int) -> int:
    """Add two integers."""
    return left + right

agent = Agent(DeepSeekProvider(), tools=[add])
print(agent.run("Use add for 20 and 22.").text)
```

运行时会自动完成全部工具循环：模型看到 `add` 的函数声明（名称、描述、由参数模型推导出的 JSON Schema）→ 模型返回包含参数 JSON 的调用 → 运行时校验参数、执行函数、把结果作为 `tool` 角色的消息回填 → 模型基于结果给出最终回答。

如果不经过模型，也可以直接用 `ToolExecutor` 执行一次调用。`ToolCall` 由四个字段组成：`call_id`（调用 ID）、`name`（工具名）、`arguments`（解析后的参数字典）、`raw_arguments`（原始 JSON 字符串）：

```python
import asyncio

from super_harness import ToolExecutor, ToolRegistry, tool
from super_harness.models import ToolCall

@tool
def add(left: int, right: int) -> int:
    """Add two integers."""
    return left + right

call = ToolCall("call_1", "add", {"left": 20, "right": 22}, '{"left":20,"right":22}')
result = asyncio.run(ToolExecutor(ToolRegistry((add,))).execute(call))
print(result.success, result.output)  # True 42
```

`execute()` 返回一个 `ToolResult`：无论成功、超时还是被拒绝，都返回结构化结果而不是抛异常（详见第 13 节）。

## 4. 配置

### 4.1 环境变量

| 环境变量 | 用途 | 何时需要 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | `DeepSeekProvider` 的请求凭据，请求时读取，不写入事件 | 使用 DeepSeek 模型驱动对话时 |
| `SUPER_HARNESS_DOCKER_E2E` | 设为 `1` 时启用真实 Docker 守护进程的端到端测试 | 仅在运行需要真实容器隔离的测试时 |

工具执行本身不读取环境变量；凭据与沙箱环境变量的处理分别由提供商与沙箱负责（见 4.4）。

### 4.2 `@tool` 装饰器参数

除函数本身外，`@tool` 支持以下关键字参数（均有默认值，全部可选）：

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| `name` | 函数名 | 工具名（模型看到的名称），须非空 |
| `description` | 函数的 docstring | 工具描述，模型据此决定何时调用；无 docstring 时退化为工具名 |
| `namespace` | `None` | 命名空间前缀；设置后限定名为 `namespace.name` |
| `source` | `"runtime"` | 来源标签（如 `"builtin"`），用于来源溯源，不影响执行 |
| `risk` | `"low"` | 风险等级标签（如 `"write"`、`"process"`），供审批回调等策略读取 |
| `timeout` | `30.0` | 单次调用超时（秒），必须为正数 |
| `max_output_chars` | `20_000` | 输出上限（字符），至少 100；超出部分会被截断并标注 |
| `supports_parallel` | `False` | 为 `True` 时，该工具允许与其它并行工具在同一模型步骤并发执行 |
| `deferred` | `False` | 标记该工具为延迟加载形态 |

### 4.3 `Agent` 的执相关参数

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| `tools` | `()` | 初始工具集合（`Iterable[Tool]`），会注册到内部 `ToolRegistry` |
| `approval` | `None`（等价于 `full_access`） | 审批策略，作用于每次工具调用 |
| `hooks` | `None` | 钩子注册表，可观察/拦截 `PRE_TOOL_USE`、`POST_TOOL_USE` |
| `max_model_steps` | `8` | 单轮工具循环的最大模型步数；触顶后抛 `ToolError` |

`Agent` 内部会持有 `ToolRegistry` 与 `ToolExecutor`。即使构造时注册表为空，执行器也保持挂接，因此之后注册或发现的工具立即可用（这也正是动态工具的基础）。

### 4.4 沙箱与审批配置

`LocalSandbox` 的 `mode` 取值见第 9 节，`environment_allowlist` 控制子进程可见的环境变量名单（默认包含 `PATH`、`PATHEXT`、`SYSTEMROOT`、`WINDIR`、`COMSPEC`、`TEMP`、`TMP`、`TMPDIR`、`LANG`、`LC_ALL`）。

`DockerSandbox` 内置一组保守默认值：无网络（`network="none"`）、容器根只读、丢弃全部 capabilities、`no-new-privileges`、`cpus=1.0`、`memory="512m"`、`pids_limit=128`、单次执行 `timeout=60.0`，并使用 `--rm` 自动清理容器。

`ApprovalPolicy` 的 `default` 决定无回调时的行为，`callback` 接收 `ApprovalRequest` 返回 `ApprovalDecision`（详见第 10 节）。

## 5. 函数工具：@tool 与 Pydantic 参数模型

### 5.1 行为说明

`@tool` 装饰器把函数转换为不可变的 `Tool` 值。装饰时会做四件事：

- 从函数签名推导出一个 Pydantic 参数模型：每个带类型注解的参数成为模型字段，有默认值的参数成为可选字段。模型配置为 `extra="forbid"`，因此模型传入未知参数会被拒绝。
- 参数必须有类型注解，否则装饰时抛 `TypeError`；工具函数不允许 `*args` / `**kwargs`。
- 同步 handler 在调用时通过 `asyncio.to_thread` 在独立线程中执行（不会阻塞事件循环）；`async def` 的 handler 直接被 `await`。
- 生成的 JSON Schema 通过 `Tool.provider_definition()` 提供给模型；调用时先 `Tool.validate(arguments)` 校验，失败抛 `ToolValidationError`（带具体字段错误），再执行 handler。

`Tool` 的关键属性：`name`、`description`、`input_model`、`handler`、`metadata`（`ToolMetadata`：`namespace`、`source`、`risk`、`timeout`、`max_output_chars`、`supports_parallel`、`deferred`、`extra`）、`qualified_name`（有命名空间时为 `namespace.name`）。

### 5.2 基础例子：定义并运行一个天气工具

`examples/04_custom_tool_loop/main.py` 展示了最小完整的工具循环：定义一个带类型返回值的 `weather` 工具，交给 `Agent`，请求模型调用它，打印最终回答。

```python
"""Run a complete DeepSeek function-tool loop."""

import asyncio

from super_harness import Agent, DeepSeekProvider, tool


@tool
def weather(city: str) -> dict[str, object]:
    """Get example weather for a city."""

    return {"city": city, "temperature_c": 25, "condition": "sunny"}


async def main() -> None:
    provider = DeepSeekProvider()
    agent = Agent(provider, tools=[weather])
    try:
        response = await agent.arun(
            "Call the weather tool for Chengdu and then answer with the result."
        )
        print(response.text)
    finally:
        await agent.aclose()


if __name__ == "__main__":
    asyncio.run(main())
```

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/04_custom_tool_loop/main.py)

注意 `finally` 块中的 `await agent.aclose()`：运行时是原生异步的，关闭 Agent 会释放其持有的资源。

### 5.3 真实场景例子：工具工厂与批量执行

`examples/06_builtin_tools/main.py` 演示了另一个真实形态：内置工具是「工厂函数」，接收沙箱返回 `Tool`；多个工具放入 `ToolRegistry`，由 `ToolExecutor` 逐个执行 `ToolCall`——完全不需要模型。参数模型会做类型校验：`file_write` 要求 `path` 与 `content` 两个字符串参数。

```python
"""Exercise sandbox-aware file and Python built-ins locally."""

import asyncio
import tempfile
from pathlib import Path

from super_harness import LocalSandbox, ToolExecutor, ToolRegistry
from super_harness.models import ToolCall
from super_harness.tools import file_read_tool, file_write_tool, python_tool


async def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        sandbox = LocalSandbox(Path(directory))
        registry = ToolRegistry(
            [file_write_tool(sandbox), file_read_tool(sandbox), python_tool(sandbox)]
        )
        executor = ToolExecutor(registry)
        write = ToolCall(
            "write_1",
            "file_write",
            {"path": "answer.txt", "content": "42"},
            '{"path":"answer.txt","content":"42"}',
        )
        read = ToolCall("read_1", "file_read", {"path": "answer.txt"}, '{"path":"answer.txt"}')
        run = ToolCall("python_1", "python", {"code": "print(6 * 7)"}, '{"code":"print(6 * 7)"}')
        print(await executor.execute(write))
        print(await executor.execute(read))
        print(await executor.execute(run))


if __name__ == "__main__":
    asyncio.run(main())
```

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/06_builtin_tools/main.py)

执行结果分别是三个 `ToolResult`：写入返回 `{"path": "...", "characters": 2}`、读取返回 `"42"`、Python 执行返回包含 `exit_code`/`stdout`/`stderr` 的字典。

### 5.4 进阶/组合例子：元数据驱动的工具标注

工具元数据不会改变执行语义，但会暴露给审批策略与可观测层。下面的例子（基于 `examples/05_approval_and_registry/main.py` 的 `publish` 工具提取）说明了 `risk`、`name`、`timeout`、`max_output_chars` 的用法，以及如何读取 `Tool` 的元数据：

```python
from super_harness import tool


@tool(name="publish_note", risk="write", timeout=10.0, max_output_chars=2_000)
def publish(message: str) -> str:
    """Publish an example message."""

    return f"published: {message}"


print(publish.name)             # publish_note
print(publish.qualified_name)   # publish_note (equals name without a namespace)
print(publish.metadata.risk)    # write
print(publish.metadata.timeout) # 10.0
print(publish.input_model.model_json_schema())
```

`input_model.model_json_schema()` 返回的就是随请求发给模型的 JSON Schema（`type: object`，含 `message` 字符串字段）。审批回调可以通过 `request.tool.metadata.risk` 决定高风险工具是否放行；可观测层可以通过 `metadata.source` 区分内置工具与业务工具。

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/05_approval_and_registry/main.py)

## 6. 工具循环与 ToolExecutor

### 6.1 行为说明

`ToolExecutor.execute(call)` 在单次调用上执行完整的执行管线，顺序固定：

1. `registry.get(call.name)` 查找工具（未注册或已禁用会得到 `ToolResult`，见第 13 节）。
2. `item.validate(call.arguments)` 按 Pydantic 参数模型校验，失败返回 `error_type="ToolValidationError"`。
3. `approval.require(ApprovalRequest(...))` 审批，拒绝返回 `error_type="ApprovalDenied"`。
4. 若配置了 hooks：先派发 `PRE_TOOL_USE`（可拒绝，返回 `error_type="HookDenied"`，也可改写参数），执行后派发 `POST_TOOL_USE`（可改写结果）。
5. `await asyncio.wait_for(item.invoke(arguments), timeout=item.metadata.timeout)` 带超时执行；同步 handler 在 `to_thread` 中运行，超时返回 `error_type="TimeoutError"`。
6. 输出经 `stringify_output` 规范化为字符串（字符串原样；`bytes` 按 UTF-8 解码；`BaseModel`/dataclass 序列化为 JSON；其余回退为 `json.dumps`/`str`），再按 `max_output_chars` 截断，`truncated`/`original_chars` 记录截断状态。

在 `Agent` 的对话循环中，上述 `execute` 被自动串联：

- 每轮模型步：发出 `model.started` → 文本增量 `model.text.delta` → 工具调用增量 `model.tool_call.delta` → `model.completed`。
- 若响应含 `tool_calls`：对每个调用发出 `tool.started`；若调用数 >1 且**所有**目标工具 `supports_parallel=True`，则用 `asyncio.gather` 并发执行，否则逐个串行执行；之后把 `ToolResult` 以 `tool` 角色消息回填，逐个发出 `tool.completed`（成功）/ `tool.failed`（失败），然后进入下一模型步继续。
- 循环持续到模型返回不再含工具调用的响应，此时发出 `turn.completed`。
- 若 `max_model_steps`（默认 8）步后仍未结束，抛 `ToolError("tool loop exceeded maximum of ... model steps")`。

### 6.2 基础例子：不经模型直接执行

`examples/05_approval_and_registry/main.py` 不使用模型，把注册表、执行器、审批回调全部串起来执行一次 `publish` 调用。`@tool(risk="write")` 标记的发布工具被 `review` 回调拒绝（`DENY`），因此 handler 不会运行：

```python
"""Use registry and callback approval without a model call."""

import asyncio

from super_harness import (
    ApprovalDecision,
    ApprovalPolicy,
    ApprovalRequest,
    ToolExecutor,
    ToolRegistry,
    tool,
)
from super_harness.models import ToolCall


@tool(risk="write")
def publish(message: str) -> str:
    """Publish an example message."""

    return f"published: {message}"


def review(request: ApprovalRequest) -> ApprovalDecision:
    print(f"reviewing {request.tool.qualified_name}: {dict(request.arguments)}")
    return ApprovalDecision.DENY


async def main() -> None:
    registry = ToolRegistry([publish])
    executor = ToolExecutor(registry, approval=ApprovalPolicy(callback=review))
    call = ToolCall("call_1", "publish", {"message": "hello"}, '{"message":"hello"}')
    print(await executor.execute(call))


if __name__ == "__main__":
    asyncio.run(main())
```

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/05_approval_and_registry/main.py)

输出先打印回调的审查日志 `reviewing publish: {'message': 'hello'}`，随后打印 `ToolResult`：`success=False`、`error_type="ApprovalDenied"`、`output` 为拒绝说明。审批发生在 handler 执行之前，所以 `published: hello` 永远不会出现。

### 6.3 真实场景例子：事件流驱动工具循环

对话循环中每次工具调用都会发出 `tool.started` / `tool.completed` / `tool.failed` 事件。通过 `agent.astream` 可以逐事件观察整个工具循环（基于 `examples/04_custom_tool_loop/main.py` 扩展）：

```python
import asyncio

from super_harness import Agent, DeepSeekProvider, tool


@tool
def weather(city: str) -> dict[str, object]:
    """Get example weather for a city."""

    return {"city": city, "temperature_c": 25, "condition": "sunny"}


async def main() -> None:
    agent = Agent(DeepSeekProvider(), tools=[weather])
    try:
        async for event in agent.astream("Call the weather tool for Chengdu."):
            if event.type == "tool.started":
                print(f"started  {event.tool_call_id} {event.payload['name']}")
            elif event.type == "tool.completed":
                print(f"completed {event.tool_call_id}: {event.payload['result'].output}")
            elif event.type == "turn.completed":
                print("turn done")
    finally:
        await agent.aclose()


asyncio.run(main())
```

事件对象不可变：`event.type` 为字符串类型，`event.payload` 为只读映射，工具事件还携带 `tool_call_id`。`tool.completed` / `tool.failed` 的 `payload["result"]` 就是 `ToolResult`，可直接读取 `output`、`success`、`error_type`。

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/04_custom_tool_loop/main.py)

### 6.4 进阶/组合例子：并行工具调用

把多个相互独立的工具标注为 `supports_parallel=True` 后，当模型在一次回复中同时请求它们时，运行时用 `asyncio.gather` 并发执行（否则退化为串行）。异步 handler 与并行标记天然搭配：

```python
import asyncio

from super_harness import Agent, DeepSeekProvider, tool


@tool(supports_parallel=True)
async def fetch_quote(symbol: str) -> dict[str, object]:
    """Fetch a market quote."""
    await asyncio.sleep(0.01)  # simulated I/O
    return {"symbol": symbol, "price": 1.23}


@tool(supports_parallel=True)
async def fetch_sentiment(symbol: str) -> dict[str, object]:
    """Fetch market sentiment."""
    await asyncio.sleep(0.01)  # simulated I/O
    return {"symbol": symbol, "sentiment": "positive"}


agent = Agent(DeepSeekProvider(), tools=[fetch_quote, fetch_sentiment])
```

并行判定规则：模型请求的工具调用数大于 1，且每个工具都满足 `metadata.supports_parallel == True`，才会并发。内置的 `file_read` 与 `file_search` 工具本身就带 `supports_parallel=True`（见 `examples/06_builtin_tools/main.py` 所构建的工具族）。同步 handler 即使标了并行也会在线程池中执行，不会因此阻塞事件循环。

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/06_builtin_tools/main.py)

## 7. 动态工具：ToolRegistry 与 LazyTool

### 7.1 行为说明

`ToolRegistry` 是确定性的工具注册表，支持在应用运行期间增删工具：

- `register(item)` / `unregister(name)`：注册/卸载已加载的 `Tool`；重名注册、未知卸载均抛 `ToolError`。
- `register_lazy(name, description, loader, *, namespace=None, source="runtime")`：发布「元数据 + 加载器」，**不导入** handler。返回 `LazyTool`。名称须匹配 `[A-Za-z0-9][A-Za-z0-9_.-]{0,127}`，描述与 loader 都必须提供。
- `load(name)`：执行一次经校验的导入，返回 `Tool` 并加入已加载集合；若 loader 抛异常或返回的工具与名称不匹配，抛 `ToolError`，且加载器会保留在注册表中供显式重试。
- `discover(query="")`：只做元数据匹配，返回 `(qualified_name, description, source, is_deferred)` 元组序列。`is_deferred=True` 表示该条目尚未加载。
- `search(query, *, load_deferred=False)`：在**名称或描述**中做大小写不敏感的子串匹配；`load_deferred=True` 时把匹配到的延迟条目一并加载。
- `enable` / `disable` / `list` / `deferred()` / `get(name)`：启停、列出、查询。
- `definitions(include_deferred=False)`：生成发给模型的 `ToolDefinition` 列表（默认不含延迟条目，因为延迟条目没有参数 Schema）。
- `allowed_names`（构造参数）：限定注册范围，条目名须匹配其中至少一个 fnmatch 模式，否则抛 `ToolError("tool ... is outside the registry scope")`。

`Agent` 构造时把 `tools` 注册进内部注册表，且执行器常驻挂接——因此运行期用 `agent.tool_registry` 注册的新工具，下一轮对话即可被模型调用。

### 7.2 基础例子：运行期注册与卸载

`examples/66_dynamic_tool_registration.py` 展示了最基础的动态性：注册、立即调用、再卸载。

```python
"""Register and remove a tool while an application is running."""

import asyncio

from super_harness import ToolRegistry, tool


@tool
def greet(name: str) -> str:
    """Return a greeting."""
    return f"Hello, {name}!"


registry = ToolRegistry()
registry.register(greet)
print(asyncio.run(registry.get("greet").invoke({"name": "Ada"})))
registry.unregister("greet")
```

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/66_dynamic_tool_registration.py)

### 7.3 真实场景例子：延迟加载

`examples/67_lazy_tool_discovery.py` 演示插件式边界：类型信息属于插件/应用层，注册时只给元数据，直到被真正选中才导入 handler。

```python
"""Discover a deferred tool without importing it until selected."""

import asyncio

from super_harness import ToolRegistry, tool


def load_weather():  # type information belongs at the plugin/application boundary
    @tool
    def weather(city: str) -> str:
        """Return deterministic demo weather."""
        return f"{city}: clear"

    return weather


registry = ToolRegistry()
registry.register_lazy("weather", "Look up weather", load_weather, source="demo")
print(registry.discover("weather"))
print(asyncio.run(registry.load("weather").invoke({"city": "Chengdu"})))
```

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/67_lazy_tool_discovery.py)

`discover("weather")` 返回 `(('weather', 'Look up weather', 'demo', True),)`——`is_deferred=True` 表示处理器尚未导入；`load` 之后该条目变为已加载，`discover` 中的标记变为 `False`。

### 7.4 进阶/组合例子：命名空间与延迟搜索

`examples/68_lazy_namespaced_tools.py` 组合了命名空间与 `search(load_deferred=True)`：只按名称/描述搜索并加载匹配的延迟工具。

```python
"""Load only deferred tools that match a namespace search."""

import asyncio

from super_harness import ToolRegistry, tool


@tool(namespace="ops")
def status(service: str) -> str:
    """Return a local service status."""
    return f"{service}=ready"


registry = ToolRegistry()
registry.register_lazy("status", "Service status", lambda: status, namespace="ops")
matched = registry.search("service", load_deferred=True)
print(asyncio.run(matched[0].invoke({"service": "api"})))
```

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/68_lazy_namespaced_tools.py)

注意两点：`register_lazy` 的 `namespace="ops"` 使限定名为 `ops.status`；`search("service", load_deferred=True)` 匹配的是描述中的 "Service"，命中后触发一次 `load`，`matched[0]` 即为已加载的 `Tool`，可直接 `invoke`。提供的 loader 必须返回限定名与注册名一致的 `Tool`，否则 `load` 抛 `ToolError("lazy tool loader returned a mismatched tool")`。

## 8. 内置工具：文件、搜索、Shell、Python

### 8.1 行为说明

内置工具位于 `super_harness.tools`（注意：它们**不在**顶层 `super_harness` 命名空间导出，需显式从 `super_harness.tools` 导入）。全部为「工厂函数」，接收一个 `LocalSandbox` 返回一个 `Tool`：

| 工厂函数 | 工具名 | 参数 | 风险 | 超时 | 行为 |
| --- | --- | --- | --- | --- | --- |
| `file_read_tool(sandbox)` | `file_read` | `path` | `low` | 30s | 读取工作区内一个 UTF-8 文本文件（`supports_parallel=True`） |
| `file_write_tool(sandbox)` | `file_write` | `path`, `content` | `write` | 30s | 写入 UTF-8 文本文件，自动创建父目录，返回路径与字符数 |
| `file_search_tool(sandbox)` | `file_search` | `pattern`, `path="."` | `low` | 30s | 按 glob 模式搜索工作区文件，返回相对路径列表（`supports_parallel=True`） |
| `shell_tool(sandbox)` | `shell` | `command`, `cwd="."` | `process` | 60s | 经 `sandbox.run_shell` 执行命令，返回 `exit_code`/`stdout`/`stderr` |
| `python_tool(sandbox)` | `python` | `code`, `cwd="."` | `process` | 60s | 用当前解释器在子进程执行代码（`sys.executable -c code`） |

`basic_builtin_tools(workspace)` 是一次性创建全部五个工具的便捷函数：内部用该目录构造 `LocalSandbox`，返回 `tuple[Tool, ...]`，可直接展开传给 `Agent(tools=basic_builtin_tools(Path(...)))`。

所有文件类内置工具都通过沙箱的 `resolve()` 解析路径：相对路径基于沙箱工作区；若沙箱模式受限，越界路径与写操作会被 `SandboxError` 拒绝。`shell`/`python` 属于进程类工具，要求沙箱为 `full_access`，否则抛 `SandboxError`（"local shell and Python processes require full_access..."）。

### 8.2 基础例子：文件搜索

`examples/86_file_search_builtin.py`：在工作区写入一个文件后，用 `file_search_tool` 按模式搜索。

```python
"""Search workspace files through the sandboxed built-in Tool."""

import asyncio
import tempfile
from pathlib import Path

from super_harness import LocalSandbox
from super_harness.tools import file_search_tool


async def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "notes.txt").write_text("release ready", encoding="utf-8")
        result = await file_search_tool(LocalSandbox(root)).invoke({"pattern": "*.txt"})
        print(result)


asyncio.run(main())
```

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/86_file_search_builtin.py)

`file_search_tool(sandbox)` 是一个工厂：传入沙箱即得到工具；`invoke` 返回 `["notes.txt"]`——相对工作区的路径列表。

### 8.3 真实场景例子：一键五件套与 Agent 接线

`sandbox`（沙箱）与 `basic_builtin_tools` 结合，可以一行把文件/搜索/Shell/Python 能力全部暴露给模型。半自动化的项目 Agent 通常配 `ApprovalPolicy.full_access()`（或自定义策略）与更高的 `max_model_steps`，因为内置工具的行动链可能较长：

```python
import asyncio
from pathlib import Path

from super_harness import Agent, ApprovalPolicy, DeepSeekProvider, basic_builtin_tools


async def main() -> None:
    agent = Agent(
        DeepSeekProvider(),
        tools=basic_builtin_tools(Path.cwd() / "workspace"),
        approval=ApprovalPolicy.full_access(),
        max_model_steps=12,
    )
    try:
        response = await agent.arun(
            "Write notes.txt with content 42 in the workspace, then use file_search "
            "for *.txt and report the result."
        )
        print(response.text)
    finally:
        await agent.aclose()


asyncio.run(main())
```

`basic_builtin_tools(workspace)` 负责构造沙箱与全部五个工具，模型可以自主编排「写文件 → 搜索 → 读取 → 执行」的多步行动链。所有文件操作都被限定在 workspace 目录内。

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/06_builtin_tools/main.py)

### 8.4 进阶/组合例子：受限沙箱下的进程工具

`shell` 与 `python` 工具要求 `full_access`。把 `shell_tool` 放进 `READ_ONLY` 沙箱时，调用会在执行前被拒绝。这与 `examples/61_security_restricted_sandbox.py` 展示的拒绝机制一致：

```python
import asyncio
import tempfile
from pathlib import Path

from super_harness import LocalSandbox, SandboxMode
from super_harness.exceptions import SandboxError
from super_harness.tools import shell_tool


async def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        sandbox = LocalSandbox(Path(directory), mode=SandboxMode.READ_ONLY)
        shell = shell_tool(sandbox)
        try:
            await shell.invoke({"command": "echo hi"})
        except SandboxError as error:
            print("denied:", error)


asyncio.run(main())
```

输出为 `denied: local shell and Python processes require full_access because the local runner is not a strong isolation boundary`。若工具经 `ToolExecutor` 执行，同一错误会变成 `success=False`、`error_type="SandboxError"` 的 `ToolResult` 而不是异常。

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/61_security_restricted_sandbox.py)

## 9. 沙箱：LocalSandbox 与 DockerSandbox

### 9.1 行为说明

`LocalSandbox(workspace, mode=..., environment_allowlist=...)` 是路径受限的本地执行器（源码注释明确定位为 "a path-constrained local runner, not a strong security boundary"）。`SandboxMode` 三档：

| 模式 | 路径规则 | 进程规则 |
| --- | --- | --- |
| `READ_ONLY` | 读操作限工作区内；写操作一律拒绝（`resolve(path, write=True)` 抛 `SandboxError`） | 禁止：`require_process_access()` 抛 `SandboxError` |
| `WORKSPACE_WRITE` | 读写均限工作区内 | 禁止进程执行 |
| `FULL_ACCESS` | 不限路径（`resolve` 直接放行） | 允许 `run_exec` / `run_shell` |

`resolve(path, write=False)`：相对路径基于 `workspace` 拼接；`FULL_ACCESS` 之外的模式执行越界检查，越界抛 `SandboxError`（`details` 含 `workspace` 与 `path`）。`run_exec(argv, cwd=None, env=None)` 以 argv 列表启动子进程（Windows 使用 `CREATE_NEW_PROCESS_GROUP`，POSIX 使用 `start_new_session`），取消时自动清理进程组；`run_shell(command, ...)` 走 shell 字符串。两者都返回 `ProcessResult(exit_code, stdout, stderr)`。子进程环境经过 `process_environment(extra)` 构造：只含 `environment_allowlist` 内的变量加显式传入的 `extra`。

`DockerSandbox(workspace, image, mode=WORKSPACE_WRITE, ...)` 是基于 Docker CLI 的隔离后端，适用于「本地进程隔离不足」的场景。默认 `network="none"`、容器根 `--read-only`、`--cap-drop ALL`、`--security-opt no-new-privileges`、`--pids-limit 128`、`--memory 512m`、`--cpus 1.0`、`--rm` 自动清理，并挂载 `--tmpfs /tmp`。特点：

- `available()`：检查 `docker` 可执行文件是否存在（不检查守护进程）。
- `build_command(argv, cwd=None, env=None, container_name=None)`：把一次执行转成 `(docker 命令列表, 进程环境)`，不启动容器——适合预检与审查。
- `env` 中每个键都必须出现在 `environment_allowlist`，否则抛 `SandboxError`；环境值经 `--env KEY` 传入，值本身永不进入 argv（避免泄漏到进程列表）。
- 镜像绝不隐式拉取；`cwd` 必须位于工作区内（否则抛 `SandboxError("Docker cwd escapes workspace")`）。
- `run_exec` 带 `timeout`（默认 60s），超时或取消时先 `docker rm -f` 清理容器再终止进程。
- `run_shell(command)` 等价于 `run_exec(("/bin/sh", "-lc", command))`。

### 9.2 基础例子：本地进程执行

`examples/87_local_sandbox_process.py` 是最小的 `run_exec` 用法：在沙箱内启动一个 Python 子进程。

```python
"""Run an argv-based local process with cancellation-safe cleanup."""

import asyncio
import sys
from pathlib import Path

from super_harness import LocalSandbox

result = asyncio.run(LocalSandbox(Path.cwd()).run_exec((sys.executable, "-c", "print(6 * 7)")))
print(result.stdout.strip())
```

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/87_local_sandbox_process.py)

`LocalSandbox` 默认模式为 `FULL_ACCESS`，因此 `run_exec` 允许执行；输出 `42`。注意传参使用 argv 列表而非 shell 字符串（需要 shell 语义时用 `run_shell`）。

### 9.3 真实场景例子：只读沙箱的路径与进程拒绝

`examples/61_security_restricted_sandbox.py` 在 `READ_ONLY` 模式下逐一验证三种被拒绝的操作，并捕获 `SandboxError`：

```python
"""Use path and process denial in a restricted local sandbox."""

import tempfile
from pathlib import Path

from super_harness import LocalSandbox, SandboxMode
from super_harness.exceptions import SandboxError

with tempfile.TemporaryDirectory() as directory:
    sandbox = LocalSandbox(Path(directory), SandboxMode.READ_ONLY)
    print("allowed read path:", sandbox.resolve("input.txt"))
    for operation in (
        lambda: sandbox.resolve("output.txt", write=True),
        lambda: sandbox.resolve(Path(directory).parent / "escape.txt"),
        sandbox.require_process_access,
    ):
        try:
            operation()
        except SandboxError as error:
            print("denied:", error)
```

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/61_security_restricted_sandbox.py)

三种拒绝分别对应：只读模式写操作、路径逃逸出工作区、非 `full_access` 下的进程访问。`SandboxError` 的 `details` 包含拒绝原因所需的路径/工作区信息。

### 9.4 进阶/组合例子：DockerSandbox

`examples/71_docker_run_if_available.py` 展示了生产可用的 Docker 执行模式：先检查 CLI 与本地镜像（框架不隐式拉取），再执行：

```python
"""Run a local Docker image when it is already installed; never pull implicitly."""

import asyncio
import subprocess
from pathlib import Path

from super_harness import DockerSandbox


async def main() -> None:
    sandbox = DockerSandbox(Path.cwd(), "alpine:3.20")
    available = sandbox.available() and subprocess.run(
        ["docker", "image", "inspect", "alpine:3.20"],
        capture_output=True,
        check=False,
    ).returncode == 0
    if not available:
        print("SKIP: Docker or local alpine:3.20 image is unavailable")
        return
    result = await sandbox.run_exec(("printf", "isolated"))
    print(result.stdout)


asyncio.run(main())
```

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/71_docker_run_if_available.py)

两个配套的预检工具：`examples/69_docker_secure_command.py` 用 `build_command` 打印出将要执行的 docker 命令而不启动容器；`examples/70_docker_allowlisted_environment.py` 验证环境变量只按名字转发（值不进 argv）：

```python
# examples/69_docker_secure_command.py (excerpt)
sandbox = DockerSandbox(Path.cwd(), "python:3.12-alpine", mode=SandboxMode.READ_ONLY)
command, _ = sandbox.build_command(("python", "-c", "print('isolated')"))
print(" ".join(command))
```

```python
# examples/70_docker_allowlisted_environment.py (excerpt)
sandbox = DockerSandbox(Path.cwd(), "alpine:3.20", environment_allowlist=("APP_MODE",))
command, environment = sandbox.build_command(("sh", "-lc", "printf '%s' \"$APP_MODE\""), env={"APP_MODE": "test"})
print("APP_MODE" in command, "test" not in " ".join(command), environment["APP_MODE"])
```

前者输出完整的 `docker run --rm --init --network none --read-only --cap-drop ALL ...` 命令；后者打印 `True True test`——`APP_MODE` 作为 `--env` 键出现、其值 `test` 不进入命令行、`environment["APP_MODE"]` 可被容器读取。

[查看完整可运行示例 69](https://github.com/Sitozzmonash/superharness/blob/main/examples/69_docker_secure_command.py) · [查看完整可运行示例 70](https://github.com/Sitozzmonash/superharness/blob/main/examples/70_docker_allowlisted_environment.py) · [查看完整可运行示例 71](https://github.com/Sitozzmonash/superharness/blob/main/examples/71_docker_run_if_available.py)

## 10. 审批与权限：ApprovalPolicy

### 10.1 行为说明

`ApprovalPolicy` 是执行前的权限边界，构造参数：`default`（`ApprovalDecision.ALLOW` / `DENY`）与 `callback`（同步或异步，接收 `ApprovalRequest` 返回 `ApprovalDecision`）。

- `ApprovalPolicy.full_access()`：默认放行（`default=ALLOW`），是 `Agent`/`ToolExecutor` 的默认策略。
- `ApprovalPolicy.deny_all()`：一律拒绝（`default=DENY`）。
- 提供 `callback` 时：`require(request)` 调用回调，若返回值是 awaitable 则先 `await`；只要决策不是 `ALLOW`，就抛 `ApprovalDenied`（可由 `ToolExecutor` 捕获为 `error_type="ApprovalDenied"` 的 `ToolResult`）。
- `ApprovalRequest` 的字段：`tool`（`Tool`，含 `metadata.risk` 等）、`arguments`（校验后的参数字典）、`call_id`。

审批发生在参数校验之后、handler 执行之前；`Agent` 模式下它作用于模型请求的每一次工具调用。回调可以基于工具名、风险等级、参数内容做任何判定，例如「只允许低风险工具」「写操作必须人工确认」「特定命名空间放行」。

### 10.2 基础例子：全部拒绝

`examples/89_approval_deny_all.py`：`deny_all()` 策略保证 handler 绝不运行（该工具本身会抛 `RuntimeError`，如果被执行就会暴露）。

```python
"""Deny every Tool call before its handler can run."""

import asyncio

from super_harness import ApprovalPolicy, ToolExecutor, ToolRegistry, tool
from super_harness.models import ToolCall


@tool(risk="write")
def destructive() -> str:
    """Represent a side effect that must not execute."""
    raise RuntimeError("must not run")


result = asyncio.run(
    ToolExecutor(ToolRegistry((destructive,)), approval=ApprovalPolicy.deny_all()).execute(
        ToolCall("1", "destructive", {}, "{}")
    )
)
print(result.success, result.error_type)
```

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/89_approval_deny_all.py)

输出 `False ApprovalDenied`。审批在 handler 之前发生，因此 `RuntimeError` 永远不会被触发。

### 10.3 真实场景例子：逐调用放行

`examples/88_approval_allow.py`：回调显式返回 `ALLOW`，放行被审查的调用（例如人工确认过的写操作）。回调可以访问 `request.tool.qualified_name` 与 `request.arguments` 来做精细判定。

```python
"""Allow a reviewed Tool call explicitly."""

import asyncio

from super_harness import ApprovalDecision, ApprovalPolicy, ToolExecutor, ToolRegistry, tool
from super_harness.models import ToolCall


@tool(risk="write")
def save(value: str) -> str:
    """Return a deterministic save result."""
    return f"saved:{value}"


policy = ApprovalPolicy(callback=lambda request: ApprovalDecision.ALLOW)
call = ToolCall("1", "save", {"value": "draft"}, '{"value":"draft"}')
print(asyncio.run(ToolExecutor(ToolRegistry((save,)), approval=policy).execute(call)))
```

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/88_approval_allow.py)

输出 `ToolResult(call_id='1', name='save', output='saved:draft', success=True, ...)`。

### 10.4 进阶/组合例子：异步回调与基于参数的判定

回调可以是 `async def`（`ApprovalPolicy.require` 会自动 `await`），适合对接外部审计服务、人工确认队列等。下面的策略按参数内容判定：空 `value` 拒绝，否则放行（链接指向完整可运行的 `examples/05_approval_and_registry/main.py`，其中展示了同一回调机制的非异步版本）：

```python
import asyncio

from super_harness import (
    ApprovalDecision,
    ApprovalPolicy,
    ToolExecutor,
    ToolRegistry,
    tool,
)
from super_harness.models import ToolCall


@tool(risk="write")
async def save(value: str) -> str:
    """Return a deterministic save result."""
    return f"saved:{value}"


async def review(request) -> ApprovalDecision:
    await asyncio.sleep(0.01)  # pretend to call an external audit service
    return ApprovalDecision.ALLOW if request.arguments.get("value") else ApprovalDecision.DENY


async def main() -> None:
    executor = ToolExecutor(
        ToolRegistry((save,)),
        approval=ApprovalPolicy(callback=review),
    )
    result = await executor.execute(
        ToolCall("1", "save", {"value": "draft"}, '{"value":"draft"}')
    )
    print(result.success, result.output)


asyncio.run(main())
```

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/05_approval_and_registry/main.py)

`request.arguments` 是**校验后**的参数（`Tool.validate` 的产物），所以回调中读到的字段保证符合参数模型；`request.tool.metadata.risk` 可以被用来把 `risk="write"`、`risk="process"` 的工具单独引流到人工审批。

## 11. API 用法速查

```python
# Tool definition
tool(function=None, *, name=None, description=None, namespace=None, source="runtime",
     risk="low", timeout=30.0, max_output_chars=20_000, supports_parallel=False,
     deferred=False) -> Tool

# Tool value
Tool(name, description, input_model, handler, metadata)
Tool.qualified_name            # namespace.name, or name
Tool.provider_definition()     # -> ToolDefinition(name, description, parameters)
Tool.validate(arguments)       # -> dict; raises ToolValidationError on failure
Tool.invoke(arguments)         # async -> object (validates, then executes)

# Registry
ToolRegistry(tools=(), *, allowed_names=None)
registry.register(item) / unregister(name) / get(name) / enable(name) / disable(name)
registry.register_lazy(name, description, loader, *, namespace=None, source="runtime") -> LazyTool
registry.unregister_lazy(name) -> LazyTool
registry.load(name) -> Tool
registry.list(*, include_disabled=False) / deferred() -> tuple
registry.search(query, *, load_deferred=False) -> tuple[Tool, ...]
registry.discover(query="")   # -> tuple[(qualified_name, description, source, is_deferred)]
registry.definitions(*, include_deferred=False) -> tuple[ToolDefinition, ...]
LazyTool(name, description, namespace=None, source="runtime")

# Executor and results
ToolExecutor(registry, *, approval=None, hooks=None)
await executor.execute(call) -> ToolResult
ToolResult(call_id, name, output, success, truncated=False, original_chars=0, error_type=None)
ToolCall(call_id, name, arguments, raw_arguments)

# Approval
ApprovalPolicy(*, default=ApprovalDecision.ALLOW, callback=None)
ApprovalPolicy.full_access(); ApprovalPolicy.deny_all()
await policy.require(request)   # raises ApprovalDenied unless ALLOW
ApprovalDecision.ALLOW / .DENY
ApprovalRequest(tool, arguments, call_id)

# Sandbox
SandboxMode.READ_ONLY / .WORKSPACE_WRITE / .FULL_ACCESS
LocalSandbox(workspace, mode=SandboxMode.FULL_ACCESS, environment_allowlist=(...))
sandbox.resolve(path, *, write=False) -> Path
sandbox.process_environment(extra=None) -> dict
sandbox.require_process_access()
await sandbox.run_exec(argv, *, cwd=None, env=None) -> ProcessResult
await sandbox.run_shell(command, *, cwd=None, env=None) -> ProcessResult
DockerSandbox(workspace, image, mode=SandboxMode.WORKSPACE_WRITE, network="none",
              environment_allowlist=(), read_only_mounts={}, cpus=1.0, memory="512m",
              pids_limit=128, timeout=60.0, docker_executable="docker")
sandbox.available() -> bool; sandbox.describe() -> dict
sandbox.build_command(argv, *, cwd=None, env=None, container_name=None) -> (list[str], dict)
await sandbox.run_exec(argv, *, cwd=None, env=None) / run_shell(command, ...)
ProcessResult(exit_code, stdout, stderr)

# Built-in tools (import from super_harness.tools)
file_read_tool(sandbox) -> Tool   # tool "file_read", risk=low, supports_parallel=True
file_write_tool(sandbox) -> Tool  # tool "file_write", risk=write
file_search_tool(sandbox) -> Tool # tool "file_search", risk=low, supports_parallel=True
shell_tool(sandbox) -> Tool       # tool "shell", risk=process, timeout=60.0
python_tool(sandbox) -> Tool      # tool "python", risk=process, timeout=60.0
basic_builtin_tools(workspace) -> tuple[Tool, ...]
```

## 12. 事件与流式

工具执行在 `agent.astream` / `thread.astream` 中按事件可见（全部不可变 `Event`，`payload` 为只读映射）：

| 事件类型 | 触发时机 | 关键 payload 字段 |
| --- | --- | --- |
| `tool.started` | 模型请求了工具、执行前的每个调用 | `name`、`arguments`；`tool_call_id` |
| `tool.completed` | 单个调用执行成功 | `result`（`ToolResult`）、`success=True` |
| `tool.failed` | 单个调用失败（含被拒/超时） | `result`（`error_type` 标记原因）、`success=False` |
| `model.tool_call.delta` | 模型流式输出工具调用参数片段 | `index`、`name`、`delta`、`step` |
| `model.started` / `model.completed` | 每个模型步的开端/结束 | `provider`、`model`、`step`、`usage`、`tool_calls` |
| `turn.started` / `turn.completed` / `turn.failed` | 整个 turn 的开始/成功/失败 | `turn_id`、`response` 或 `error_type` |

并行执行的多个调用会各自发出独立的 `tool.started`/`tool.completed`（共享同一个 `turn_id`），事件顺序不保证与模型请求顺序一致。所有事件都携带 `event_id`、`timestamp`（带时区）、`thread_id`、`turn_id`，工具事件额外携带 `tool_call_id`。`thread.astream` 的消费方式与 `agent.astream` 一致（见 6.3）。

## 13. 错误、超时与重试

`ToolExecutor.execute` 几乎从不抛异常——它把失败归一化为 `ToolResult`，`success=False`，用 `error_type` 标注类别：

| `error_type` | 含义 |
| --- | --- |
| `TimeoutError` | handler 超过 `metadata.timeout`（默认 30s）仍未返回 |
| `ApprovalDenied` | 审批策略拒绝该调用 |
| `ToolValidationError` | 参数不符合 Pydantic 参数模型（含多参/未知参数） |
| `ToolError` | 注册表查找失败、工具未注册/已禁用、懒加载失败、循环触顶等 |
| `HookDenied` | `PRE_TOOL_USE` 钩子拒绝了调用 |
| 其它类名（如 `SandboxError`、`ValueError`、任意 handler 异常类名） | handler 或沙箱抛出的异常类型名 |

其他要点：

- 输出截断：`max_output_chars`（默认 20_000）。超出时 `truncated=True`、`original_chars` 记录原始长度，内容保留头尾、中间插入 `... truncated N characters ...` 标记，防止巨型输出污染上下文。
- 取消传播：`asyncio.CancelledError` 不会被吞掉，会原样向上传播；`LocalSandbox`/`DockerSandbox` 在取消时先清理子进程/容器再重抛。
- 循环上限：单轮工具循环超过 `max_model_steps`（默认 8）步时，turn 以 `ToolError("tool loop exceeded maximum of N model steps")` 失败（`turn.failed` 事件 + 异常）。
- 注册失败：重名注册、未知卸载、`allowed_names` 范围外的注册、非法懒加载名称均抛 `ToolError`。
- 沙箱失败：路径逃逸/只读写/受限进程/非法 Docker 参数均抛 `SandboxError`（经执行器转为 `ToolResult`）。
- 重试：执行管线本身不自动重试工具（审批被拒后重试无意义）。需要重试的场景应：超时调大 `timeout=`、扩容 `max_model_steps=` 让模型重试、或由应用在 `execute` 外层实现重试策略。

## 14. 与其他功能组合

- **Hooks**：`HookRegistry` 配置在 `Agent(tools=..., hooks=...)` / `ToolExecutor(..., hooks=...)` 上；`PRE_TOOL_USE` 可拒绝调用或改写参数，`POST_TOOL_USE` 可改写结果。Hooks 补充审批与可观测性，但不替代沙箱。
- **Workflow/混合编排**：确定性 `Workflow` 的节点 handler 可以调用 `ToolExecutor`；`agent_node` 派生的子 Agent 自带其协作工具。
- **多智能体**：`AgentManager` 会自动给根/子 Agent 附加 `spawn_agent`、`send_input`、`wait_agent`、`resume_agent`、`interrupt_agent`、`close_agent` 等工具；需要仅应用可控时用 `expose_tools=False`。
- **Persona**：`persona.select_tools(...)` 会用 `tool_scopes` 的 fnmatch 规则过滤 `Agent` 的工具集，通过 `ToolRegistry(allowed_names=...)` 强制注册范围。
- **可观测性**：`Observability(observer)` 注入 Agent 后，工具调用会以归一化事件进入跟踪；`ToolResult` 的字段（含 `error_type`、`truncated`）会随事件暴露。
- **CLI**：`super-harness doctor` 可用于诊断提供商/配置；工具本身无 CLI 子命令，通过 Python API 使用。

## 15. 安全注意事项

- `LocalSandbox` 只做**路径策略**，不是操作系统/网络隔离。`full_access` 模式放行所有路径与子进程执行，仅应在可信环境中使用。
- 不可信代码/不可信输入请放到 `DockerSandbox`（默认无网络、只读根、丢弃 capabilities、资源上限）或容器/虚拟机中。
- 进程类内置工具（`shell`、`python`）需要 `full_access`——在受限沙箱中它们会被拒绝，这正是预期行为。
- 默认审批策略是 `full_access`。生产环境应至少配置 `deny_all` 或带回调的 `ApprovalPolicy`，让写类/进程类高风险工具（`risk` 元数据）经过人工或应用层确认。
- `DockerSandbox` 的环境变量只按 allowlist 名转发，值不进 argv；镜像从不隐式拉取，防止供应链意外。
- 工具输出有上限与截断标记，防止长输出注入或撑爆上下文；模型返回的原始参数 JSON 长度也被限制（`ToolCall.raw_arguments` 上限一百万字符）。

## 16. 故障排查

| 现象 | 原因与处理 |
| --- | --- |
| `ToolError: tool 'x' is already registered` | 同名工具重复注册。检查命名空间或先 `unregister`。 |
| `ToolError: tool 'x' is outside the registry scope` | 注册表配置了 `allowed_names`（如 Persona 的 tool_scopes），名称不匹配 fnmatch 规则。 |
| `ToolError: tool 'x' is disabled` / `unknown tool 'x'` | 工具被 `disable` 或从未注册/已卸载。 |
| `ToolError: lazy tool 'x' failed to load` | loader 抛异常；`load` 保留加载器，修正后显式重试。 |
| `ToolError: lazy tool loader returned a mismatched tool` | loader 返回的 `Tool.qualified_name` 与注册名不一致（含 namespace 前缀）。 |
| `error_type="ToolValidationError"` | 模型传入的参数不符合参数模型；检查参数注解是否有 `*args`/`**kwargs`/缺注解导致装饰失败。 |
| `error_type="TimeoutError"` | 工具执行超过 `timeout`；为长任务调大 `@tool(timeout=...)`。 |
| `error_type="ApprovalDenied"` | 审批策略拒绝了调用；检查 `ApprovalPolicy` 配置或回调逻辑。 |
| `SandboxError: path escapes sandbox workspace` | 相对路径解析后越出工作区；工具在受限沙箱中使用了绝对路径或 `..` 越界。 |
| `SandboxError: sandbox is read-only` | `READ_ONLY` 模式下写操作被拒。 |
| `SandboxError: local shell and Python processes require full_access...` | `shell`/`python` 工具或 `run_exec`/`run_shell` 在非 `full_access` 沙箱中使用；确认是否真的需要进程能力。 |
| 模型从不调用某个工具 | 检查工具 `description` 是否清晰、参数模型是否合理；确认工具已注册且未被审批拒绝；确认 `discover`/`definitions` 能输出该工具。 |
| 工具并行未生效 | 并行要求调用数 >1 且所有目标工具 `supports_parallel=True`。 |
| `ToolError: tool loop exceeded maximum of N model steps` | 工具链过长或模型反复请求工具而未收敛；调大 `max_model_steps` 或简化指令。 |
| `DockerSandbox` 执行失败 | 先 `sandbox.available()` 与 `sandbox.build_command(...)` 预检；确认镜像已在本地（框架不拉取）；确认 `env` 键都在 `environment_allowlist`。 |

## 17. 链接

**可运行示例（examples/）**

- [04_custom_tool_loop/main.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/04_custom_tool_loop/main.py) — 完整函数工具循环
- [05_approval_and_registry/main.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/05_approval_and_registry/main.py) — 注册表 + 审批回调 + 执行器
- [06_builtin_tools/main.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/06_builtin_tools/main.py) — 沙箱感知的文件/Python 内置工具
- [61_security_restricted_sandbox.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/61_security_restricted_sandbox.py) — 受限沙箱的路径/进程拒绝
- [66_dynamic_tool_registration.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/66_dynamic_tool_registration.py) — 运行期注册/卸载
- [67_lazy_tool_discovery.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/67_lazy_tool_discovery.py) — 延迟加载与 discover
- [68_lazy_namespaced_tools.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/68_lazy_namespaced_tools.py) — 命名空间 + 延迟搜索
- [69_docker_secure_command.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/69_docker_secure_command.py) — 检查 Docker 命令
- [70_docker_allowlisted_environment.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/70_docker_allowlisted_environment.py) — Docker 环境变量允许名单
- [71_docker_run_if_available.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/71_docker_run_if_available.py) — Docker 可用性检查与执行
- [86_file_search_builtin.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/86_file_search_builtin.py) — 内置文件搜索
- [87_local_sandbox_process.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/87_local_sandbox_process.py) — 本地进程执行
- [88_approval_allow.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/88_approval_allow.py) — 审批放行
- [89_approval_deny_all.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/89_approval_deny_all.py) — 审批全拒

**相关文档**

- 用户指南 Part I–IV（Agent、Thread、上下文与指令）
- API 参考（`super_harness.tools` / `super_harness.models` / `super_harness.exceptions`）
- Internals：工具运行时（`src/super_harness/tools/`）