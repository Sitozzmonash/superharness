---
id: guide-part2-models
title: "用户指南 Part II：模型与输入（Models & Inputs）"
sidebar_position: 2
description: 配置主文本模型（DeepSeek）、自定义 OpenAI 兼容提供商、视觉模型、能力回退与结构化输出，并学习流式、错误与安全处理。
---

# 用户指南 Part II：模型与输入（Models & Inputs）

本页介绍如何为 Agent 配置与使用**模型提供商**，以及如何把**输入**（文本、图片、结构化输出约束）正确地交给模型。涵盖：默认主文本模型 `DeepSeekProvider`、任意 OpenAI 兼容服务的 `OpenAICompatibleProvider`、视觉模型 `ZhipuVisionProvider`、多提供商回退 `FallbackProvider` 与 `FallbackPolicy`，以及结构化输出 `output_schema`。同时说明流式事件、错误/超时/重试、安全与故障排查。

所有代码均来自仓库中**真实可运行**的示例（`examples/`），并附"查看完整可运行示例"链接；引用的每个类、方法、字段都在 `src/super_harness` 中真实存在。

## 1. 这是什么 / 何时使用

- **主文本模型**：默认使用 `DeepSeekProvider`（模型 `deepseek-v4-flash`，`base_url` 为 `https://api.deepseek.com`，密钥从 `DEEPSEEK_API_KEY` 环境变量读取）。绝大多数对话、工具调用、结构化输出场景都用它。
- **自定义 / OpenAI 兼容提供商**：需要接入任何实现了 OpenAI Chat Completions 或 Responses 协议的第三方服务（自建网关、其他厂商、公司内部代理）时，用 `OpenAICompatibleProvider` 指定 `base_url`、`model`、`api_key_env`。
- **视觉模型**：需要让模型理解图片（本地文件、data URL、HTTPS 图片链接）时，用 `ZhipuVisionProvider`（模型 `glm-4v-flash`，密钥从 `ZHIPU_VISION_API_KEY` 读取），或通过 `KnowledgeRouter` 把视觉能力暴露成工具 `knowledge.vision_analyze`。
- **能力回退**：需要按顺序尝试多个提供商、在主提供商失败或超时后自动切换，并且让整个链路的能力声明取交集时，用 `FallbackProvider` 与 `FallbackPolicy`。
- **结构化输出**：需要模型严格返回符合 JSON Schema 的对象（而不是自由文本）时，用 `Agent.run(..., output_schema=...)`。

简言之：默认用 DeepSeek；要换后端用 OpenAICompatible；要"看"图用 Zhipu 视觉；要稳用 Fallback；要规整输出用 `output_schema`。

## 2. 前置条件（Prerequisites）

- Python 3.11+，已安装本项目：`pip install -e .`（在仓库根目录执行）。
- 至少一个有效的 API 密钥，通过环境变量提供。核心密钥：
  - `DEEPSEEK_API_KEY` —— 主文本模型必需。
  - `ZHIPU_VISION_API_KEY` —— 视觉模型必需（仅在使用视觉时）。
  - 自定义提供商用的密钥名由 `api_key_env` 指定，例如 `CUSTOM_API_KEY`。
- 密钥**在请求时**从环境变量读取，绝不写入事件、日志或代码库。可把密钥放在 `.env`（配置加载器默认不自动加载，除非 `load_dotenv=True`）或直接 `export`。
- 每个提供商在使用前都会校验密钥存在；缺失时抛出 `ModelError`（视觉为 `VisionError`）。

## 3. 模型提供商总览

| 类 | 用途 | 默认模型 | 密钥环境变量 |
| --- | --- | --- | --- |
| `DeepSeekProvider` | 主文本模型（DeepSeek 官方 API） | `deepseek-v4-flash` | `DEEPSEEK_API_KEY` |
| `OpenAICompatibleProvider` | 任意 OpenAI 兼容服务 | 由 `model` 指定（必填） | 由 `api_key_env` 指定 |
| `ZhipuVisionProvider` | 视觉理解（GLM-4V） | `glm-4v-flash` | `ZHIPU_VISION_API_KEY` |
| `FallbackProvider` | 按序回退多个提供商 | 取第一个提供商的 `model` | 取决于其内部提供商 |

所有提供商都实现同一个 `ModelProvider` 协议：`name`、`capabilities`、`complete(request)`、`stream(request)`、`aclose()`。`Agent` 只依赖这一协议，因此任何提供商（包括 `FallbackProvider`）都可以直接传给 `Agent`。

`ModelCapabilities` 声明了提供商的能力，`Agent` 依据它来决定如何驱动模型：

| 字段 | 类型 | 默认值 | 含义 |
| --- | --- | --- | --- |
| `streaming` | `bool` | `True` | 是否支持流式输出 |
| `tools` | `bool` | `True` | 是否支持工具调用 |
| `structured_output` | `bool` | `True` | 是否支持结构化输出 |
| `reasoning` | `bool` | `False` | 是否支持推理 |
| `parallel_tool_calls` | `bool` | `True` | 单步是否可并行调用多个工具 |
| `wire_apis` | `tuple[str, ...]` | `("chat_completions",)` | 支持的线上协议（`chat_completions` / `responses`） |

## 4. 主文本模型：DeepSeekProvider

### 4.1 这是什么 / 何时使用

`DeepSeekProvider` 是默认主文本模型适配器，继承自 `OpenAICompatibleProvider`，预置了 DeepSeek 的默认值。直接 `DeepSeekProvider()` 即可使用，无需额外配置，只要环境里有 `DEEPSEEK_API_KEY`。适用于：普通对话、工具调用、结构化输出、流式输出、以及多轮 `Thread` 会话。

### 4.2 快速开始

```python
from super_harness import Agent, DeepSeekProvider

provider = DeepSeekProvider()
agent = Agent(provider, instructions="Answer clearly and briefly.")
response = agent.run("Explain what an agent runtime does in one sentence.")
print(response.text)
```

这段代码与 `examples/01_basic_agent/main.py` 完全一致，是运行 Agent 的最小闭环：创建提供商 → 构造 Agent → `run` → 读取 `response.text`。`run` 会开启一个全新的 `Thread`；单次问答用 `agent.run(...)` 即可，多轮请用 `agent.thread()`。

### 4.3 配置（Configuration）

**环境变量**

| 环境变量 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `DEEPSEEK_API_KEY` | 是 | 无 | DeepSeek API 密钥；请求时从环境读取，缺失则抛 `ModelError` |

**构造参数与默认值**（`DeepSeekProvider.__init__` 全为关键字参数）

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `model` | `"deepseek-v4-flash"` | 使用的模型名 |
| `api_key` | `None` | 直接传入密钥；缺省时读取 `DEEPSEEK_API_KEY` |
| `base_url` | `"https://api.deepseek.com"` | API 根地址（不含协议路径） |
| `wire_api` | `WireAPI.CHAT_COMPLETIONS` | 线上协议：`CHAT_COMPLETIONS` 或 `RESPONSES` |
| `timeout` | `60.0` | 单请求 HTTP 超时（秒） |
| `max_retries` | `2` | 非流式 `complete` 的重试上限 |
| `stream_max_retries` | `1` | 流式 `stream` 的重试上限 |
| `client` | `None` | 可传入共享的 `httpx.AsyncClient` |

`DeepSeekProvider` 预置的能力声明：`streaming=True`、`tools=True`、`structured_output=True`、`reasoning=True`、`parallel_tool_calls=True`、`wire_apis=("chat_completions", "responses")`。

### 4.4 DeepSeek V4 Flash 设置与线上协议

DeepSeek V4 Flash 是默认文本模型。除模型名外，`base_url` 与 `wire_api` 决定请求如何发出：

- **`WireAPI.CHAT_COMPLETIONS`（默认）**：请求发往 `{base_url}/chat/completions`，负载为 OpenAI Chat Completions 结构（`messages`、`tools`、`parallel_tool_calls`、`response_format`）。这是最常见、兼容性最好的模式。
- **`WireAPI.RESPONSES`**：请求发往 `{base_url}/responses`，负载为 Responses 协议结构（`input`、`text.format`）。工具调用与输出按 Responses 事件流解析（`response.output_text.delta`、`response.function_call_arguments.delta`、`response.output_item.added`、`response.completed`）。

两点 DeepSeek 特有的行为需要注意：

1. **`developer` 角色映射为 `system`**：DeepSeek 原生 API 拒绝 OpenAI 的 `developer` 角色、只接受 `system`。`DeepSeekProvider` 在序列化时会自动把 `developer` 改写为 `system`，其余 OpenAI 兼容逻辑保持不变。
2. **结构化输出走 `json_object`**：DeepSeek 原生 API 拒绝 `response_format: json_schema`（会报 `This response_format type is unavailable now`），只接受 `json_object`。当传了 `output_schema` 且 `wire_api` 为 `CHAT_COMPLETIONS` 时，请求会改写为 `{"type": "json_object"}`，而 Schema 符合性由运行时在本地解析后校验（见第 8 节），因此放宽线上格式是安全的。

### 4.5 基础例子（Basic）

`examples/01_basic_agent/main.py`：

```python
"""Minimal synchronous DeepSeek agent."""

from super_harness import Agent, DeepSeekProvider


def main() -> None:
    provider = DeepSeekProvider()
    agent = Agent(provider, instructions="Answer clearly and briefly.")
    response = agent.run("Explain what an agent runtime does in one sentence.")
    print(response.text)


if __name__ == "__main__":
    main()
```

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/01_basic_agent/main.py)

### 4.6 真实场景例子（Real-world）

实际应用中通常需要多轮对话——把历史消息保留在同一个 `Thread` 里，而不是每轮都开新线程。`agent.thread()` 返回一个可复用的 `Thread`，反复 `thread.run(...)` 会把之前的消息一并带上：

```python
from super_harness import Agent, DeepSeekProvider

provider = DeepSeekProvider()
agent = Agent(provider, instructions="你是数据分析师，回答用简洁的要点。")
thread = agent.thread()

first = thread.run("总结上季度营收的三个主要驱动因素。")
print(first.text)

# 第二轮会带上上一轮的全部上下文
second = thread.run("与上一季度相比，这些驱动因素有何变化？")
print(second.text)
```

这里用到的 `Agent.thread()`、`Thread.run()` 都是真实 API；多轮上下文默认保存在内存中，如需持久化（重启后恢复、fork），请配合 `SQLiteThreadStore`（见用户指南 Part IV：会话与持久化，示例 `examples/07_durable_thread/main.py`）。

### 4.7 进阶 / 组合例子（Advanced）

切换到 `WireAPI.RESPONSES` 协议并流式消费文本增量。`agent.astream` 逐个产出不可变的 `Event`，文本以 `model.text.delta` 事件到达，增量在 `event.payload["delta"]`：

```python
import asyncio

from super_harness import Agent, DeepSeekProvider
from super_harness.models import WireAPI


async def main() -> None:
    provider = DeepSeekProvider(wire_api=WireAPI.RESPONSES)
    agent = Agent(provider)
    async for event in agent.astream("Briefly explain the RESPONSES wire format."):
        if event.type == "model.text.delta":
            print(event.payload["delta"], end="", flush=True)
    print()
    await agent.aclose()


if __name__ == "__main__":
    asyncio.run(main())
```

流式的完整模式见 `examples/02_streaming/main.py`（下面第 9 节详述）。

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/02_streaming/main.py)

### 4.8 API 用法速查

```python
provider = DeepSeekProvider()                                   # 使用全部默认值
provider = DeepSeekProvider(model="deepseek-v4-flash")          # 显式指定模型
provider = DeepSeekProvider(wire_api=WireAPI.RESPONSES)         # 切换线上协议
agent = Agent(provider, instructions="...")                     # 构造 Agent
response = await agent.arun("Hello")                            # 异步，返回 ModelResponse
response = agent.run("Hello")                                   # 同步
response.text                                                   # 归一化后的文本
response.usage                                                  # Usage(input/output/total_tokens)
response.tool_calls                                             # 归一化后的 ToolCall 元组
response.output_json                                            # 结构化输出时解析出的对象
await agent.aclose()                                            # 关闭提供商持有的客户端
```

## 5. 自定义 / OpenAI 兼容提供商：OpenAICompatibleProvider

### 5.1 这是什么 / 何时使用

`OpenAICompatibleProvider` 是"提供商中立"的 HTTP 适配器，对接任何兼容 OpenAI Chat Completions 或 Responses 协议的服务：自建 LLM 网关、其他厂商、公司内部代理、兼容层等。只要目标服务接受 `Authorization: Bearer <key>` 并返回标准格式，就能接入。`DeepSeekProvider` 正是它的子类，只是预置了 DeepSeek 的默认值。

### 5.2 快速开始

```python
from super_harness import Agent, OpenAICompatibleProvider

provider = OpenAICompatibleProvider(
    model="your-model-name",                  # 必填
    base_url="https://api.example.com/v1",    # 必填
    api_key_env="CUSTOM_API_KEY",             # 密钥环境变量名
)
agent = Agent(provider, instructions="Answer concisely.")
print(agent.run("Hello").text)
```

### 5.3 配置（Configuration）

**环境变量**

| 环境变量 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `CUSTOM_API_KEY`（示例名） | 是（取决于 `api_key_env`） | 无 | 由 `api_key_env` 指定；也可以直接传 `api_key` 参数 |

**构造参数**（除 `model`、`base_url` 外全为关键字参数）

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `model` | （必填） | 目标模型名 |
| `base_url` | （必填） | API 根地址，自动去掉尾部 `/` |
| `api_key` | `None` | 直接传密钥；与 `api_key_env` 二选一，`api_key` 优先 |
| `api_key_env` | `None` | 读取密钥的环境变量名 |
| `wire_api` | `WireAPI.CHAT_COMPLETIONS` | 协议选择 |
| `timeout` | `60.0` | 请求超时（秒） |
| `max_retries` | `2` | 非流式重试上限 |
| `stream_max_retries` | `1` | 流式重试上限 |
| `client` | `None` | 可传入共享 `httpx.AsyncClient` |
| `name` | `"openai_compatible"` | 提供商名称（用于日志/事件/报错） |
| `capabilities` | 自动按 `wire_api` 推导 | 能力声明，可按需覆盖 |

**重试语义**：重试计数必须非负（否则抛 `ValueError`）。可重试的错误是传输错误（`httpx.TransportError`、`httpx.TimeoutException`）以及 HTTP 429 或 5xx；退避为 `min(0.25 * 2^attempt + 随机抖动, 2.0)` 秒，最多重试 `max_retries` 次。**认证错误（401/403）和其他 4xx 立即失败**，不会重试，统一包装为 `ModelError`（带 HTTP 状态码详情）。`complete` 中的 `ModelError` 不重试直接上抛；流式 `stream` 只在终端完成事件出现前失败才重试。

### 5.4 基础例子（Basic）

接入一个 OpenAI 兼容端点并做单次问答，显式指定 `api_key_env` 让密钥从环境读取而不是写死在代码里：

```python
from super_harness import Agent, OpenAICompatibleProvider

provider = OpenAICompatibleProvider(
    model="gpt-4o-mini",
    base_url="https://your-gateway.example.com/v1",
    api_key_env="CUSTOM_API_KEY",
)
agent = Agent(provider, instructions="Answer concisely.")
response = agent.run("What is the difference between Chat Completions and Responses?")
print(response.text)
```

### 5.5 真实场景例子（Real-world）

把端点、模型名、密钥全部来自环境/运行时，便于不同环境（开发、测试、生产）复用同一段代码：

```python
import os

from super_harness import Agent, OpenAICompatibleProvider

provider = OpenAICompatibleProvider(
    model=os.environ["MODEL_NAME"],
    base_url=os.environ["BASE_URL"],
    api_key_env="CUSTOM_API_KEY",
)
agent = Agent(provider, instructions="你是技术助手，回答用中文，控制在三句以内。")
print(agent.run("解释一下什么是 Agent 运行时。").text)
```

### 5.6 进阶 / 组合例子（Advanced）

用 `WireAPI.RESPONSES` 协议，并通过 `client` 注入一个共享的、超时更长的 `httpx.AsyncClient`（复用连接、集中管理超时）。异步流程用 `agent.arun`：

```python
import asyncio

import httpx

from super_harness import Agent, OpenAICompatibleProvider
from super_harness.models import WireAPI


async def main() -> None:
    async with httpx.AsyncClient(timeout=120.0) as client:
        provider = OpenAICompatibleProvider(
            model="openai-compatible-model",
            base_url="https://api.example.com/v1",
            api_key_env="CUSTOM_API_KEY",
            wire_api=WireAPI.RESPONSES,
            client=client,
        )
        agent = Agent(provider, instructions="Answer concisely.")
        response = await agent.arun("Hello")
        print(response.text)


if __name__ == "__main__":
    asyncio.run(main())
```

### 5.7 API 用法速查

```python
provider = OpenAICompatibleProvider(model="m", base_url="https://.../v1", api_key_env="K")
provider.wire_api              # WireAPI.CHAT_COMPLETIONS | WireAPI.RESPONSES
provider.base_url              # 去掉尾部 "/" 的地址
provider.timeout / provider.max_retries / provider.stream_max_retries
provider.name                  # 提供商名
provider.capabilities          # ModelCapabilities
response = await provider.complete(request)   # 低层：直接对 ModelRequest 发请求
async for event in provider.stream(request): # 低层：流式 ModelStreamEvent
await provider.aclose()
```

## 6. 视觉模型：ZhipuVisionProvider

### 6.1 这是什么 / 何时使用

`ZhipuVisionProvider` 是 GLM-4V 视觉适配器，默认模型 `glm-4v-flash`，密钥从 `ZHIPU_VISION_API_KEY` 读取。它支持三种图片输入形式：

- **本地文件路径**：`Path("image.png")` 或字符串路径。运行时会读取文件、校验大小上限（默认 `10_000_000` 字节）、按魔数校验图片格式（PNG/JPEG/GIF/WebP），再编码为 `data:` URL 发送。这保证本地图片不会离开本地、也不会把非法文件发出去。
- **data URL**：`data:image/png;base64,...` 直接透传。
- **HTTPS / HTTP URL**：`https://...` 或 `http://...` 直接透传，由智谱服务端拉取。

适用于：OCR、图片理解、图表解读、截图分析、把"看图"能力暴露给 Agent 作为工具等。

### 6.2 快速开始

```python
import asyncio
from pathlib import Path

from super_harness import ZhipuVisionProvider


async def main() -> None:
    result = await ZhipuVisionProvider().analyze(Path("image.png"), "Describe this image")
    print(result.text)


asyncio.run(main())
```

`analyze(image, prompt)` 返回 `VisionResult`，其 `text` 字段是模型对图片的描述。

### 6.3 配置（Configuration）

**环境变量**

| 环境变量 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `ZHIPU_VISION_API_KEY` | 是 | 无 | 智谱 GLM-4V API 密钥；缺失时 `analyze` 抛 `VisionError` |

**构造参数**（全为关键字参数）

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `api_key` | `None` | 直接传密钥；缺省读 `ZHIPU_VISION_API_KEY` |
| `endpoint` | `"https://open.bigmodel.cn/api/paas/v4/chat/completions"` | 智谱对话接口 |
| `model` | `"glm-4v-flash"` | 视觉模型名 |
| `timeout` | `30.0` | 请求超时（秒） |
| `retries` | `1` | 单次调用重试次数 |
| `max_image_bytes` | `10_000_000` | 本地图片大小上限（字节） |
| `client` | `None` | 可传入共享 `httpx.AsyncClient` |
| `trace_sink` | `None` | 知识溯源回调（`KnowledgeTrace`） |
| `observer` | `None` | 事件观察者 |

**图片输入校验**：本地路径会做格式魔数校验，仅接受 PNG/JPEG/GIF/WebP 魔数；大小超过 `max_image_bytes` 抛 `VisionError("local image exceeds size limit")`；非图片文件抛 `VisionError("local input is not a recognized image")`；读取失败抛 `VisionError("unable to read local image")`。`prompt` 为空串抛 `ValueError("vision prompt must be non-empty")`。

### 6.4 基础例子（Basic）

分析本地图片，`examples/16_vision_local.py`：

```python
import asyncio
from pathlib import Path

from super_harness import ZhipuVisionProvider


async def main() -> None:
    result = await ZhipuVisionProvider().analyze(Path("image.png"), "Describe this image")
    print(result.text)


asyncio.run(main())
```

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/16_vision_local.py)

### 6.5 真实场景例子（Real-world）

分析远程 HTTPS 图片（例如一张线上截图），`examples/17_vision_url.py`：

```python
import asyncio

from super_harness import ZhipuVisionProvider


async def main() -> None:
    result = await ZhipuVisionProvider().analyze(
        "https://example.com/image.png", "List visible objects"
    )
    print(result.text)


asyncio.run(main())
```

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/17_vision_url.py)

### 6.6 进阶 / 组合例子（Advanced）

把视觉能力注册为 Agent 可调用的工具。`KnowledgeRouter(vision=...)` 会把视觉提供商暴露成工具 `knowledge.vision_analyze`，这样模型在对话中"按需看图"。`examples/18_vision_tool.py`：

```python
from super_harness import KnowledgeRouter, ZhipuVisionProvider

router = KnowledgeRouter(vision=ZhipuVisionProvider())
vision_tool = router.tools()[0]
print(vision_tool.qualified_name, vision_tool.provider_definition().parameters)
```

- `vision_tool.qualified_name` → `"knowledge.vision_analyze"`（命名空间 `knowledge` + 名称 `vision_analyze`）。
- `vision_tool.provider_definition()` → 提供给模型的 `ToolDefinition`（含参数 JSON Schema）。
- 把 `router.tools()` 传给 `Agent(..., tools=router.tools())`，模型即可调用视觉工具。

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/18_vision_tool.py)

**批量分析**（进阶）：对多张图片并行调用 `analyze`，用 `asyncio.gather` 加速：

```python
import asyncio
from pathlib import Path

from super_harness import ZhipuVisionProvider


async def main() -> None:
    provider = ZhipuVisionProvider()
    frames = [Path("frame_1.png"), Path("frame_2.png"), Path("frame_3.png")]
    results = await asyncio.gather(*(provider.analyze(f, "What changed?") for f in frames))
    for result in results:
        print(result.text)


asyncio.run(main())
```

### 6.7 API 用法速查

```python
provider = ZhipuVisionProvider()
result = await provider.analyze(image, prompt)   # image: str | Path
result.text       # 描述文本
result.model      # 使用的模型名（默认 glm-4v-flash）
result.provider   # "zhipu"
router = KnowledgeRouter(vision=provider)
await router.vision(image, prompt)               # 经路由调用
tools = router.tools()                           # 含 knowledge.vision_analyze
```

### 6.8 事件 / 可观测性

传入 `observer` 后，每次 `analyze` 会发出事件（可用于成本/延迟统计）：

| 事件类型 | 时机 | 负载要点 |
| --- | --- | --- |
| `vision.started` | 请求发出前 | `provider`、`model`、`operation_id` |
| `vision.completed` | 成功返回 | `provider`、`model`、`operation_id`、`item_count`、`duration_ms` |
| `vision.failed` | 失败时 | `provider`、`model`、`operation_id`、`duration_ms`、`error_class` |

### 6.9 错误 / 超时 / 重试

- 缺失密钥：`VisionError("ZHIPU_VISION_API_KEY is required")`。
- 网络/HTTP 失败：`VisionError`（由 `VisionError` 类型归一化，带重试 `retries` 次）。
- 本地文件：读取失败、超大小、非图片格式分别抛出对应 `VisionError`。
- 服务端返回结构异常：`VisionError("vision response has invalid choices")`。

## 7. 模型能力与回退：FallbackProvider + FallbackPolicy

### 7.1 这是什么 / 何时使用

`FallbackProvider` 按顺序尝试一串提供商：前一个失败（或超时、或不可重试）时切换到下一个。用于：多主/备模型、限流时切换、按可用性降级、主服务不可达时保住可用性。与"静默切换"不同，**每次尝试与切换都是可观测的**（通过 `observer` 发出事件），调用方始终清楚当前用的是哪个提供商。

`FallbackProvider.capabilities` 是**所有子提供商能力声明的交集**：只要有一个子提供商不支持某能力（如流式、工具、结构化输出、推理、并行工具调用），整条链就声明不支持；`wire_apis` 取各子提供商支持协议的并集交集（实际为排序后的交集）。这样 `Agent` 不会在部分提供商不支持某能力时误用。

### 7.2 快速开始

把主模型与备用模型包进一条回退链，直接交给 `Agent`：

```python
from super_harness import Agent, DeepSeekProvider, FallbackProvider, OpenAICompatibleProvider

master = DeepSeekProvider()
backup = OpenAICompatibleProvider(
    model="backup-model",
    base_url="https://api.example.com/v1",
    api_key_env="BACKUP_API_KEY",
)
agent = Agent(FallbackProvider((master, backup)))
print(agent.run("Hello").text)
```

主提供商（DeepSeek）失败时，`FallbackProvider.complete` 会自动尝试备用提供商并返回其结果。

### 7.3 配置（Configuration）

**`FallbackPolicy`**（不可变 dataclass）

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `timeout` | `60.0` | 每次提供商尝试的**有界超时**（秒），必须为正，否则抛 `ValueError` |
| `retry_if` | `_retryable_error` | 判定异常是否"可回退"的谓词 `Callable[[Exception], bool]`；默认对 `ModelError` 与 `TimeoutError` 返回 `True` |

**`FallbackProvider`**

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `providers` | （必填，非空） | 按顺序尝试的提供商序列；为空抛 `ValueError` |
| `policy` | `FallbackPolicy()` | 回退策略 |
| `observer` | `None` | 事件观察者 |

`FallbackProvider.name` 形如 `"fallback[a,b]"`；`.model` 取第一个提供商的 `model`。

### 7.4 基础例子（Basic）

显式构造一个失败的主提供商与一个成功的备用提供商，验证回退行为。`examples/81_provider_fallback.py`：

```python
"""Fall back after an explicit provider failure."""

import asyncio
from collections.abc import AsyncIterator

from super_harness import FallbackProvider
from super_harness.exceptions import ModelError
from super_harness.models import ModelCapabilities, ModelRequest, ModelResponse, ModelStreamEvent


class Provider:
    capabilities = ModelCapabilities()

    def __init__(self, name: str, answer: str = "") -> None:
        self.name, self.answer = name, answer

    async def complete(self, request: ModelRequest) -> ModelResponse:
        if not self.answer:
            raise ModelError("unavailable")
        return ModelResponse(text=self.answer)

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        if False:
            yield ModelStreamEvent("started")

    async def aclose(self) -> None:
        pass


print(asyncio.run(FallbackProvider((Provider("primary"), Provider("backup", "ok"))).complete(ModelRequest(()))).text)
```

运行输出为 `ok`：`primary` 抛 `ModelError("unavailable")`，可回退，于是 `FallbackProvider` 切到 `backup` 并返回其文本。这里演示了任何实现了 `complete`/`stream`/`aclose` 并带 `name` 与 `capabilities` 的对象都可以作为回退链的一员。

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/81_provider_fallback.py)

### 7.5 真实场景例子（Real-world）

给每次提供商尝试加一个有界超时——某个提供商卡住时不会无限等待。`examples/83_fallback_timeout.py`：

```python
"""Apply a bounded timeout per provider attempt."""

import asyncio
from collections.abc import AsyncIterator

from super_harness import FallbackPolicy, FallbackProvider
from super_harness.models import ModelCapabilities, ModelRequest, ModelResponse, ModelStreamEvent


class SlowProvider:
    name = "slow"
    capabilities = ModelCapabilities()

    async def complete(self, request: ModelRequest) -> ModelResponse:
        await asyncio.sleep(10)
        return ModelResponse()

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        if False:
            yield ModelStreamEvent("started")

    async def aclose(self) -> None:
        pass


async def main() -> None:
    try:
        await FallbackProvider((SlowProvider(),), policy=FallbackPolicy(timeout=0.01)).complete(ModelRequest(()))
    except Exception as error:
        print(type(error).__name__, str(error))


asyncio.run(main())
```

`SlowProvider.complete` 睡 10 秒，而 `FallbackPolicy(timeout=0.01)` 把每次尝试限制在 0.01 秒内。超时被归一化为 `ModelError`（`"model provider attempt timed out"`，详情含提供商名与超时值），因 `TimeoutError` 默认可回退但此处没有备用提供商，最终上抛。运行输出形如：

```
ModelError model provider attempt timed out
```

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/83_fallback_timeout.py)

### 7.6 进阶 / 组合例子（Advanced）

**流式回退的"可见输出即不安全"规则**。流式场景下，`FallbackProvider` 只允许在**尚未产生任何可见输出**之前切换到备用提供商。一旦已经流出了文本或工具增量（`TEXT_DELTA` / `TOOL_CALL_DELTA`），若当前提供商中途失败，会抛 `ModelError("provider stream failed after visible output; fallback is unsafe")` 而不是静默切换——避免在已向用户展示半截内容后，再从备用模型重复输出造成重复响应。`examples/82_stream_fallback_safety.py` 演示了主提供商在产生输出**前**失败、从而安全切换到备份的情况：

```python
"""Stream from a backup only when the first provider emitted no visible output."""

import asyncio
from collections.abc import AsyncIterator

from super_harness import FallbackProvider
from super_harness.exceptions import ModelError
from super_harness.models import (
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
    ModelStreamEventType,
)


class StreamProvider:
    capabilities = ModelCapabilities()

    def __init__(self, name: str, fail: bool) -> None:
        self.name, self.fail = name, fail

    async def complete(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse()

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        if self.fail:
            raise ModelError("before output")
        response = ModelResponse(text="safe")
        yield ModelStreamEvent(ModelStreamEventType.TEXT_DELTA, delta="safe")
        yield ModelStreamEvent(ModelStreamEventType.COMPLETED, response=response)

    async def aclose(self) -> None:
        pass


async def main() -> None:
    provider = FallbackProvider((StreamProvider("primary", True), StreamProvider("backup", False)))
    print([event.type async for event in provider.stream(ModelRequest(()))])


asyncio.run(main())
```

主提供商在产生任何输出前就抛 `ModelError`，因此回退安全；输出为 `['started', 'text_delta', 'completed']`。

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/82_stream_fallback_safety.py)

### 7.7 API 用法速查

```python
chain = FallbackProvider((a, b), policy=FallbackPolicy(timeout=30.0), observer=obs)
chain.name                      # "fallback[a,b]"
chain.model                     # 第一个提供商的 model
chain.capabilities              # 子提供商能力声明取交集
response = await chain.complete(request)
async for event in chain.stream(request):
    ...
await chain.aclose()            # 并行关闭所有子提供商
```

### 7.8 事件 / 可观测性

传入 `observer` 后，每次尝试都会发出事件，且切换方向对调用方可见：

| 事件类型 | 时机 | 负载要点 |
| --- | --- | --- |
| `provider.attempt.started` | 尝试某提供商前 | `provider`、`attempt`（从 1 计） |
| `provider.attempt.completed` | 某提供商成功 | `provider`、`attempt` |
| `provider.attempt.failed` | 某提供商失败 | `provider`、`attempt`、`error_class` |
| `provider.fallback.selected` | 决定切换到下一家 | `provider`（下一家）、`attempt`、`previous_provider` |

### 7.9 错误 / 超时 / 重试

- 每次尝试都在 `asyncio.timeout(policy.timeout)` 内执行；超时归一化为 `ModelError("model provider attempt timed out")`。
- 非 `ModelError`/`TimeoutError` 的异常按 `retry_if` 判定是否可回退；不可回退则立即上抛归一化 `ModelError`。
- 所有提供商都失败时抛 `ModelError("provider fallback exhausted", details={"attempts": [...]})`。
- 流式：内部流未以 `COMPLETED` 事件结束抛 `ModelError("provider stream ended without a completed event")`；可见输出后失败抛 `ModelError("provider stream failed after visible output; fallback is unsafe")`。
- 调用方取消（`asyncio.CancelledError`）始终向上传播，不会被吞掉。

## 8. 结构化输出（Structured output）

### 8.1 这是什么 / 何时使用

用 `output_schema`（JSON Schema）约束模型返回**结构化的 JSON 对象**，而不是自由文本。适用于：把模型输出解析进类型化结构、数据抽取、表单填充、下游系统直接消费等。返回值在 `ModelResponse.output_json` 中，是已解析并冻结（只读映射）的 JSON 对象。

不同协议的线上行为：

- **OpenAI 兼容 `CHAT_COMPLETIONS`**：发送 `response_format: {type: "json_schema", json_schema: {name: "super_harness_output", strict: true, schema: ...}}`。
- **OpenAI 兼容 `RESPONSES`**：发送 `text.format: {type: "json_schema", ...}`。
- **DeepSeek（`CHAT_COMPLETIONS`）**：原生拒绝 `json_schema`，因此改写为 `response_format: {type: "json_object"}`；Schema 符合性由运行时**本地解析后校验**（把响应文本 `json.loads` 成对象，放入 `output_json`），所以放宽线上格式是安全的。

### 8.2 快速开始

```python
from super_harness import Agent, DeepSeekProvider

agent = Agent(DeepSeekProvider())
schema = {
    "type": "object",
    "properties": {
        "city": {"type": "string"},
        "temperature_c": {"type": "number"},
    },
    "required": ["city", "temperature_c"],
    "additionalProperties": False,
}
response = agent.run("Weather in Chengdu?", output_schema=schema)
print(response.output_json)
```

`response.output_json` 是一个只读映射，例如 `{"city": "Chengdu", "temperature_c": 28.0}`。

### 8.3 基础例子（Basic）

请求严格 JSON，并读取归一化后的工具调用。`examples/03_structured_and_tools/main.py`：

```python
"""Request strict JSON and normalize a provider tool call."""

import asyncio

from super_harness import Agent, DeepSeekProvider
from super_harness.models import ToolDefinition


async def main() -> None:
    provider = DeepSeekProvider()
    agent = Agent(provider)
    schema = {
        "type": "object",
        "properties": {"summary": {"type": "string"}},
        "required": ["summary"],
        "additionalProperties": False,
    }
    weather = ToolDefinition(
        "weather",
        "Get current weather for a city",
        {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
            "additionalProperties": False,
        },
    )
    try:
        structured = await agent.arun("Summarize Chengdu in JSON.", output_schema=schema)
        print(structured.text)
        tool_response = await agent.arun("Use weather for Chengdu.", tools=[weather])
        for call in tool_response.tool_calls:
            print(call.call_id, call.name, dict(call.arguments))
    finally:
        await agent.aclose()


if __name__ == "__main__":
    asyncio.run(main())
```

- `output_schema` 与 `tools` 是 `arun` 的两个独立关键字参数，可分别或同时使用。
- `ToolDefinition(name, description, parameters)` 定义提供给模型的函数。
- 归一化后的 `ToolCall` 带 `call_id`、`name`、`arguments`（只读映射）与 `raw_arguments`。

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/03_structured_and_tools/main.py)

### 8.4 真实场景例子（Real-world）

在应用里消费 `output_json`，把模型输出映射进业务字段，并处理未返回对象的情况：

```python
from super_harness import Agent, DeepSeekProvider

agent = Agent(DeepSeekProvider())
schema = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "keywords": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
    },
    "required": ["title", "keywords"],
    "additionalProperties": False,
}
response = agent.run("为这篇技术文章生成标题和三个关键词。", output_schema=schema)
if response.output_json is not None:
    title = response.output_json["title"]
    keywords = list(response.output_json["keywords"])
    print(title, keywords)
else:
    print("模型未返回结构化对象，文本为：", response.text)
```

### 8.5 进阶 / 组合例子（Advanced）

直接在提供商层构造 `ModelRequest`，可以额外控制 `temperature` 等运行时字段（`Agent.run` 不暴露这些字段）。用 `Message` / `MessageRole` / `ModelRequest` 与 `output_schema`：

```python
import asyncio

from super_harness import Agent, DeepSeekProvider
from super_harness.models import Message, MessageRole, ModelRequest


async def main() -> None:
    agent = Agent(DeepSeekProvider())
    schema = {
        "type": "object",
        "properties": {"answer": {"type": "string"}, "confidence": {"type": "number"}},
        "required": ["answer", "confidence"],
        "additionalProperties": False,
    }
    request = ModelRequest(
        messages=(Message(MessageRole.USER, "Summarize in JSON."),),
        output_schema=schema,
        temperature=0.0,
    )
    response = await agent.provider.complete(request)
    print(response.output_json)


if __name__ == "__main__":
    asyncio.run(main())
```

`agent.provider` 就是构造 Agent 时传入的提供商；`provider.complete(ModelRequest)` 走的是与 `Agent.run` 相同的归一化路径，`output_json` 同样可用。

### 8.6 API 用法速查

```python
response = agent.run(input, output_schema=json_schema)      # 同步
response = await agent.arun(input, output_schema=json_schema)  # 异步
response.output_json      # 解析后的只读映射，或 None
response.text             # 原始文本（JSON 字符串）
# 也可在 ModelRequest 层设置 temperature / extra
```

### 8.7 错误

- 提供商返回无法解析的 JSON：`ModelError("provider returned invalid tool-call JSON")`。
- 提供商返回非对象 JSON：`ModelError("provider returned non-object tool-call arguments")`。
- DeepSeek 的 `json_object` 只保证"是 JSON"，不保证符合 Schema；Schema 符合性由本地 `_structured` 解析后放入 `output_json`，应用读取时应自行校验必填字段。

## 9. 事件与流式输出（Events & streaming）

### 9.1 提供商层：ModelStreamEvent

`provider.stream(ModelRequest)` 逐个产出 `ModelStreamEvent`，其 `type` 取值：

| 类型 | 含义 |
| --- | --- |
| `ModelStreamEventType.STARTED` | 流开始 |
| `ModelStreamEventType.TEXT_DELTA` | 文本增量（`delta`） |
| `ModelStreamEventType.TOOL_CALL_DELTA` | 工具调用增量（`tool_call_index`、`tool_call_id`、`tool_name`、`delta`） |
| `ModelStreamEventType.COMPLETED` | 流结束，携带完整 `response` |

### 9.2 Agent 层：Event

`agent.astream(...)` 把模型事件再包装成运行时 `Event`，`event.type` 与负载：

| 事件类型 | 负载要点 |
| --- | --- |
| `model.started` | `provider`、`model`、`step` |
| `model.text.delta` | `delta`、`step` |
| `model.tool_call.delta` | `index`、`name`、`delta`、`step`（`Event.tool_call_id`） |
| `model.completed` | `response`、`usage`、`tool_calls`、`provider`、`model`、`step` |
| `model.failed` | `provider`、`model`、`error_type`、`message` |

### 9.3 快速开始

`examples/02_streaming/main.py`——流式消费文本增量，边到边打印：

```python
"""Stream correlated runtime events from DeepSeek."""

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

### 9.4 真实场景例子（Real-world）

累积所有文本增量拼出完整回答，并从 `model.completed` 事件读取用量统计：

```python
import asyncio

from super_harness import Agent, DeepSeekProvider


async def main() -> None:
    agent = Agent(DeepSeekProvider())
    parts: list[str] = []
    usage = None
    async for event in agent.astream("Give three concise agent safety rules."):
        if event.type == "model.text.delta":
            parts.append(event.payload["delta"])
        elif event.type == "model.completed":
            usage = event.payload["usage"]
    print("".join(parts))
    print("usage:", usage)
    await agent.aclose()


if __name__ == "__main__":
    asyncio.run(main())
```

### 9.5 进阶 / 组合例子（Advanced）

在提供商层直接消费 `ModelStreamEvent`，同时处理文本增量与工具调用增量（例如为工具参数做流式累积或展示）：

```python
import asyncio

from super_harness import DeepSeekProvider
from super_harness.models import Message, MessageRole, ModelRequest, ModelStreamEventType


async def main() -> None:
    provider = DeepSeekProvider()
    request = ModelRequest(
        messages=(Message(MessageRole.USER, "Give three concise agent safety rules."),)
    )
    async for event in provider.stream(request):
        if event.type is ModelStreamEventType.TEXT_DELTA:
            print(event.delta, end="", flush=True)
        elif event.type is ModelStreamEventType.TOOL_CALL_DELTA:
            print(f"\n[tool {event.tool_call_index} {event.tool_name}] {event.delta}", end="")
    print()
    await provider.aclose()


if __name__ == "__main__":
    asyncio.run(main())
```

## 10. 错误 / 超时 / 重试（Errors / timeouts / retries）

**异常层级**：所有框架错误以 `SuperHarnessError` 为基类；模型相关错误为 `ProviderError` → `ModelError`（视觉为 `VisionError`、搜索为 `SearchError`、RAG 为 `RAGError`）。`ModelError` 带 `message`、可选 `correlation_id` 与只读 `details` 映射（已脱敏）。

| 场景 | 行为 |
| --- | --- |
| 缺失密钥 | `ModelError("missing credential for provider <name>: set <source>")`；视觉为 `VisionError("ZHIPU_VISION_API_KEY is required")` |
| 网络/传输错误、HTTP 429、HTTP 5xx | 可重试；退避 `min(0.25*2^attempt+抖动, 2.0)` 秒，上限 `max_retries`（流式 `stream_max_retries`） |
| 认证错误（401/403）与其他 4xx | **立即失败**，包装为 `ModelError`（详情含 HTTP 状态码） |
| 单请求超时 | `timeout` 参数（默认 60s）；`FallbackPolicy.timeout` 为每次回退尝试的有界超时 |
| 提供商层 `ModelError` | 不重试，直接上抛 |
| 回退链全部失败 | `ModelError("provider fallback exhausted", details={"attempts": [...]})` |
| 流未以 `COMPLETED` 结束 | `ModelError("provider stream ended without a completed event")`（`FallbackProvider` 内） |
| 流可见输出后失败 | `ModelError("provider stream failed after visible output; fallback is unsafe")` |

**取消**：`asyncio.CancelledError` 在 `FallbackProvider` 中始终向上传播；在事件循环中不要调用同步方法（`run`/`stream`），应使用 `arun`/`astream`。

## 11. 与其他功能组合（Combining）

- **回退 + 视觉 / 搜索 / RAG**：`KnowledgeRouter` 的提供商各有自己的重试；`FallbackProvider` 适合把多个"文本模型"串成主备链。视觉是独立调用（`analyze`），不参与 `FallbackProvider` 的文本链，但可通过 `KnowledgeRouter.tools()` 暴露给同一个 Agent。
- **回退 + 多智能体**：`AgentManager` 的工厂返回 `Agent`，可以把 `FallbackProvider` 作为所有子 Agent 的提供商，让每个子 Agent 都具备主备能力（见用户指南 Part V：编排）。
- **结构化输出 + 回退**：`FallbackProvider.capabilities` 会取 `structured_output` 交集；只有全部子提供商都支持结构化输出时，Agent 才会用 `output_schema`。
- **回退 + 可观测性**：把同一个 `observer` 同时传给 `Agent(observer=...)` 与 `FallbackProvider(observer=...)`，即可在一条事件流里同时看到模型事件（`model.*`）与回退事件（`provider.*`）。
- **视觉 + 工具循环**：`KnowledgeRouter.tools()` 返回的 `knowledge.vision_analyze` 直接传给 `Agent(tools=...)`，模型即可在对话中按需"看图"。

## 12. 安全注意事项（Security notes）

- **密钥只从环境变量/显式参数读取**，请求时才解析，绝不写入事件、日志或代码；如需输出日志，配合 `SecretRedactor` 与结构化日志（见用户指南 Part VIII：可观测性）。
- 不要在 `instructions`、提示词或工具参数里放密钥/令牌。
- 视觉本地图片会在**本地**编码为 data URL，不经过中间网络；远程图片仅应使用可信的 HTTPS URL。
- 自定义提供商的 `base_url` 与 `api_key` 视为敏感配置；通过 `api_key_env` 而非命令行参数传递。
- 回退链中，备用提供商的密钥同样经环境变量解析，避免硬编码。
- 所有框架错误（`ModelError` 等）的 `details` 是脱敏后的诊断元数据，不含机密值。

## 13. 故障排查（Troubleshooting）

| 现象 | 排查 |
| --- | --- |
| `ModelError: missing credential for provider deepseek: set DEEPSEEK_API_KEY` | 未设置 `DEEPSEEK_API_KEY`。`export DEEPSEEK_API_KEY` 后重试。 |
| `VisionError: ZHIPU_VISION_API_KEY is required` | 使用视觉前需设置 `ZHIPU_VISION_API_KEY`。 |
| `ModelError: ... model request failed with HTTP 401/403` | 密钥错误或无权限；认证错误不重试，直接失败。 |
| `ModelError: ... model request failed with HTTP 429/5xx` | 限流或服务端错误，会自动重试；仍失败请检查配额与网络。 |
| `ModelError: provider stream ended without a completed event` | 流未收到 `COMPLETED`；通常是服务端提前断开或协议不匹配，检查 `wire_api` 是否与服务一致。 |
| DeepSeek 报 `This response_format type is unavailable now` | 使用 `DeepSeekProvider`（`CHAT_COMPLETIONS`）时已自动改写为 `json_object`；如自定义 `OpenAICompatibleProvider` 直连 DeepSeek，请勿发送 `json_schema`。 |
| `VisionError: local input is not a recognized image` | 本地文件不是受支持的 PNG/JPEG/GIF/WebP。 |
| `VisionError: local image exceeds size limit` | 本地图片超过 `max_image_bytes`（默认 10 MB）。 |
| `ValueError: fallback timeout must be positive` | `FallbackPolicy(timeout=...)` 传了非正数。 |
| 在事件循环里调用 `run()` 卡住/报错 | 事件循环中请用 `await agent.arun(...)` / `async for ... in agent.astream(...)`。 |
| `output_json` 为 `None` 但 `text` 有值 | 未传 `output_schema`，或提供商返回的不是合法 JSON；检查 `output_schema` 与响应文本。 |

## 14. 链接（Links）

**可运行示例**（本页引用）：

- [examples/01_basic_agent/main.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/01_basic_agent/main.py) —— 最小 DeepSeek Agent
- [examples/02_streaming/main.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/02_streaming/main.py) —— 流式事件消费
- [examples/03_structured_and_tools/main.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/03_structured_and_tools/main.py) —— 结构化输出 + 工具
- [examples/16_vision_local.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/16_vision_local.py) —— 本地图片视觉
- [examples/17_vision_url.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/17_vision_url.py) —— URL 图片视觉
- [examples/18_vision_tool.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/18_vision_tool.py) —— 视觉工具 `knowledge.vision_analyze`
- [examples/81_provider_fallback.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/81_provider_fallback.py) —— 提供商回退
- [examples/82_stream_fallback_safety.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/82_stream_fallback_safety.py) —— 流式回退安全
- [examples/83_fallback_timeout.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/83_fallback_timeout.py) —— 每次尝试有界超时
- [examples/07_durable_thread/main.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/07_durable_thread/main.py) —— 持久化多轮会话（相关）

**相关页面**：

- 用户指南 Part I：入门（创建 Agent 的最小流程）
- 用户指南 Part III：上下文与输入（如何组装上下文片段）
- 用户指南 Part IV：会话与持久化（`SQLiteThreadStore`、`Thread`）
- 用户指南 Part VIII：可观测性（`observer`、事件、`SecretRedactor`）
- API 参考：`DeepSeekProvider`、`OpenAICompatibleProvider`、`ZhipuVisionProvider`、`FallbackProvider`、`FallbackPolicy`、`ModelCapabilities`、`ModelRequest`、`ModelResponse`、`ToolDefinition`
