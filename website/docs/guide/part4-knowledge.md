---
id: guide-part4-knowledge
title: 知识（记忆 / RAG / 搜索 / 视觉）
sidebar_position: 4
description: 掌握 Super Harness 的知识体系——有界工作记忆、跨线程长期记忆、外部 RAG 检索、Web 搜索与视觉分析，并通过 KnowledgeRouter 把它们组合进 Agent。
---

# 知识（记忆 / RAG / 搜索 / 视觉）

本页讲解 Super Harness 的"知识"能力：如何让 Agent 记住短期状态、跨线程记住长期事实、从外部 RAG 服务检索文档、搜索实时网页、分析图片，以及如何通过 `KnowledgeRouter` 把检索结果注入上下文、把检索能力暴露成模型可见的 Tool。所有能力都聚焦"怎么用、会得到什么行为"，不讨论内部实现。

## 这是什么 / 何时使用

Super Harness 把"知识"拆成四个层次，按生命周期和来源区分：

| 能力 | 代表类型 | 生命周期 | 典型用途 |
| --- | --- | --- | --- |
| 工作记忆 | `WorkingMemory` | 进程内、有界（默认 64 项）、LRU 淘汰 | 保存当前任务的临时偏好、目标、上下文快照 |
| 长期记忆 | `SQLiteMemoryStore` + `MemoryManager` | 持久化到 SQLite、可跨 Thread 复用 | 记住用户长期偏好、事实、决策，跨会话复用 |
| 外部 RAG | `HTTPRAGProvider` | 外部服务、随用随取 | 检索企业知识库、发布政策、文档切片 |
| Web 搜索 | `ZhipuWebSearchProvider` | 实时联网 | 获取最新、外部或模型知识之外的信息 |
| 视觉 | `ZhipuVisionProvider` | 按需分析单张图片 | 读取本地/URL/Data-URI 图片内容 |

何时使用哪种：

- **只需要在本次运行内记住一点临时状态**（例如"用中文回复"、"目标是发布 Phase 5"）→ `WorkingMemory`。
- **希望跨 Thread、跨进程记住事实**（例如"用户偏好茉莉花茶"、"发布需要 canary"）→ `SQLiteMemoryStore` + `MemoryManager`。
- **有独立的知识库 / 文档库**（例如发布政策、鉴权规则）→ 外部 RAG 服务 + `HTTPRAGProvider`。
- **需要最新或联网信息**（例如"最新 Python 版本"）→ `ZhipuWebSearchProvider`。
- **需要理解图片内容**（例如"描述这张图"、"识别截图里的按钮"）→ `ZhipuVisionProvider`。
- **希望把上述检索能力交给模型自行决定何时调用**→ `KnowledgeRouter.tools()` 注册为模型可见 Tool。
- **希望把检索结果直接作为上下文注入**，不经过模型决策 → `KnowledgeRouter.search_context()` / `rag_context()`。

所有搜索 / RAG / 记忆片段在上下文中都归属 `ContextKind.RAG` 或 `ContextKind.MEMORY`，被视为**用户角色的外部数据**，永远不能覆盖开发者指令或项目指令。

## 前置条件（Prerequisites）

- 已安装 Super Harness（`pip install -e .`）。
- 本页示例大部分基于 `DeepSeekProvider`；按需配置 `DEEPSEEK_API_KEY`。
- **只配置你实际用到的提供商**。搜索需要 `ZHIPU_SEARCH_API_KEY`；视觉需要 `ZHIPU_VISION_API_KEY`；RAG 需要 `RAG_BASE_URL`（和可选的 `RAG_API_KEY`）。没有配置的提供商不要实例化。
- 运行需要联网 / 外部服务的示例前，确保对应服务可达（RAG 服务需自行启动，见下文"Mock RAG 服务教程"）。
- 长期记忆示例会在当前目录生成 `memory.sqlite3` 数据库文件。

## 快速开始（Quick start）

最简的"记忆 + 注入上下文"工作流——把一段工作记忆变成上下文片段喂给 Agent：

```python
from super_harness import Agent, DeepSeekProvider, WorkingMemory

memory = WorkingMemory()
memory.set("response_language", "Chinese")
fragment = memory.context()
agent = Agent(DeepSeekProvider(), context=(() if fragment is None else (fragment,)))
print(agent.run("Introduce this project briefly.").text)
```

在配置好 `RAG_BASE_URL` 的情况下，最简的 RAG 检索：

```python
import asyncio
from super_harness import HTTPRAGProvider, KnowledgeRouter

async def main() -> None:
    router = KnowledgeRouter(rag=HTTPRAGProvider())
    fragments = await router.rag_context("What is the release policy?", top_n=3)
    for fragment in fragments:
        print(fragment.render().content)

asyncio.run(main())
```

把 `fragments` 传给 `Agent(..., context=fragments)` 即可让 Agent 看到检索结果；或注册 `router.tools()` 让模型按需检索。

## 配置（Configuration）

Super Harness 在请求时从环境变量读取凭据，**永不把凭据写入事件或日志**。所有知识提供商都支持在构造函数里显式传参覆盖环境变量。

| 环境变量 | 用途 | 默认值 |
| --- | --- | --- |
| `ZHIPU_SEARCH_API_KEY` | Web 搜索的智谱 API Key | 无（缺失时 `search()` 抛 `SearchError`） |
| `ZHIPU_VISION_API_KEY` | 视觉分析的智谱 API Key | 无（缺失时 `analyze()` 抛 `VisionError`） |
| `RAG_BASE_URL` | RAG 服务的基础 URL，如 `http://127.0.0.1:8765` | 空（缺失时 `retrieve()` 抛 `RAGError`） |
| `RAG_API_KEY` | RAG 服务的可选 Bearer Token | 无 |

示例：`RAG_BASE_URL` 默认值通过 `HTTPRAGProvider` 构造时读取：

```python
from super_harness import HTTPRAGProvider

provider = HTTPRAGProvider()  # base_url 来自 RAG_BASE_URL
```

也可以在构造函数显式覆盖（优先级高于环境变量）：

```python
provider = HTTPRAGProvider(
    "http://127.0.0.1:8765",
    api_key="rag-secret-token",
    retrieve_path="/retrieve",
    timeout=10.0,
    retries=1,
)
```

---

# 工作记忆（WorkingMemory）

`WorkingMemory` 是**进程内、有界、线程局部**的键值存储，默认最多保留 `max_items=64` 项，采用最近最少使用（LRU）淘汰。适合保存一次运行 / 一个 Thread 生命周期内的临时状态。

## 基本用法

```python
from super_harness import WorkingMemory

memory = WorkingMemory(max_items=3)
memory.set("goal", "ship Phase 5")
memory.set("branch", "main")
print(memory.snapshot())
print(memory.context())
```

## 工作记忆的 API

- `WorkingMemory(max_items=64)` — 构造；`max_items < 1` 抛 `ValueError`。
- `set(key, value)` — 写入；key 为空抛 `ValueError`。超出上限时淘汰最早未使用的项。
- `get(key, default=None)` — 读取并把该项标记为最近使用；不存在返回 `default`。
- `delete(key)` — 删除；返回 `True`/`False` 表示是否存在。
- `clear()` — 清空全部。
- `snapshot()` — 返回当前全部键值对（普通 `dict` 拷贝）。
- `context(*, source="working-memory")` — 若为空返回 `None`；否则把全部项渲染成一个 `ContextFragment(ContextKind.MEMORY, ...)`，可直接传给 `Agent(context=...)`。

## 基础例子

保存一段运行内的偏好并把渲染出的片段注入 Agent：

```python
from super_harness import Agent, DeepSeekProvider, WorkingMemory

memory = WorkingMemory()
memory.set("response_language", "Chinese")
fragment = memory.context()
agent = Agent(DeepSeekProvider(), context=(() if fragment is None else (fragment,)))
print(agent.run("Introduce this project briefly.").text)
```

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/21_working_memory_agent.py)

## 真实场景例子

在一个多轮对话中维护"用户偏好 + 当前分支 + 剩余预算"，用 `get` 读取并刷新、超限自动淘汰最旧项：

```python
from super_harness import WorkingMemory

memory = WorkingMemory(max_items=64)
memory.set("user_name", "Ada")
memory.set("branch", "feature/knowledge")
memory.set("budget_remaining", 1200)

name = memory.get("user_name")          # 读取并标记为最近使用
memory.set("budget_remaining", 1100)    # 更新，刷新 MRU 位置
print(memory.snapshot())
print(memory.context())
```

## 进阶 / 组合例子（LRU 淘汰行为）

验证有界淘汰：`max_items=2` 时，插入第三项会淘汰最久未使用的 `second`，而 `get("first")` 已刷新过 MRU 位置所以保留：

```python
from super_harness import WorkingMemory

memory = WorkingMemory(max_items=2)
memory.set("first", 1)
memory.set("second", 2)
memory.get("first")     # 刷新 first 的 MRU 位置
memory.set("third", 3)  # 淘汰最久未使用的 second
print(memory.snapshot())  # first and third remain
```

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/20_working_memory_lru.py)

---

# 长期记忆（Long-term Memory）

当记忆需要**跨 Thread、跨进程**持久化时，使用 `SQLiteMemoryStore` 作为存储，`MemoryManager` 作为管道（抽取 → 固话 → 检索）。`Thread.messages` 仍是单 Thread 的持久对话记忆；长期记忆专门用于可复用的跨 Thread 事实。

## 基本用法

```python
import asyncio
from super_harness import MemoryCandidate, SQLiteMemoryStore

async def main() -> None:
    store = SQLiteMemoryStore("memory.sqlite3")
    await store.remember(MemoryCandidate("Release requires a canary"), source_thread_id="thread-a")
    print(await store.search("release canary"))
    await store.close()

asyncio.run(main())
```

## 关键类型与 API

- `MemoryCandidate(content, kind=NOTE, tags=(), importance=0.5, metadata={})` — 待固话的记忆；content 非空、`importance ∈ [0,1]`。
- `MemoryKind` — 枚举：`FACT` / `PREFERENCE` / `DECISION` / `SUMMARY` / `NOTE`。
- `MemoryRecord` — 已固话记录，含 `memory_id`、`source_thread_id`、`created_at`、`updated_at`、`usage_count`、`last_accessed_at`。
- `SQLiteMemoryStore(path)` — 持久化存储：
  - `remember(candidate, *, source_thread_id=None)` — 固话；按内容指纹去重，重复写入会合并并提升 importance。
  - `get(memory_id)` / `forget(memory_id)` — 读取 / 删除。
  - `search(query, *, limit=5, exclude_thread_id=None, kinds=())` — 关键词+短语重叠评分检索，命中会累加 `usage_count` 并更新 `last_accessed_at`。
  - `close()` — 关闭连接。
- `MemoryManager(store, extractor=None, *, trace_sink=None)`：
  - `consolidate(thread_id, messages)` — 用抽取器从消息中提取候选并固话，返回 `MemoryRecord` 元组。
  - `retrieve_context(query, *, current_thread_id=None, limit=5)` — 检索并渲染成 `ContextFragment` 元组，可用于注入 Agent 上下文。
- `MemoryExtractor` — 协议：`async def extract(messages) -> tuple[MemoryCandidate, ...]`。

## 配置 / 环境变量

长期记忆没有专有环境变量；数据库路径在构造 `SQLiteMemoryStore(path)` 时指定。默认抽取器**不访问任何凭据**，只匹配显式记忆语句。

### 默认抽取器（HeuristicMemoryExtractor）

默认抽取器**只接受以 `Remember:` 或 `Memory:` 开头的显式行**（大小写不敏感、行首允许空白）。例如用户消息 `Remember: use jasmine tea` 会被抽取为一条 `FACT` 候选（importance 0.8、标签 `("explicit",)`）。

```python
from super_harness.memory.pipeline import HeuristicMemoryExtractor

extractor = HeuristicMemoryExtractor()
```

如需应用特定或基于模型的抽取，请提供自定义 `MemoryExtractor`（实现 `extract(messages)` 协议）。

## 基础例子

固话一条事实并检索：

```python
import asyncio
from super_harness import MemoryCandidate, SQLiteMemoryStore

async def main() -> None:
    store = SQLiteMemoryStore("memory.sqlite3")
    await store.remember(MemoryCandidate("Release requires a canary"), source_thread_id="thread-a")
    print(await store.search("release canary"))
    await store.close()

asyncio.run(main())
```

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/22_long_term_memory.py)

## 真实场景例子（跨 Thread 复用）

从 Thread A 固话记忆，之后在 Thread B 检索并注入上下文。`current_thread_id` 让检索**排除当前 Thread 自己的记忆**，从而复用"别的 Thread 记得的事"：

```python
import asyncio
from super_harness import MemoryManager, SQLiteMemoryStore

async def main() -> None:
    store = SQLiteMemoryStore("memory.sqlite3")
    manager = MemoryManager(store)
    fragments = await manager.retrieve_context("preferred editor", current_thread_id="thread-b")
    for fragment in fragments:
        print(fragment.source, fragment.content)
    await store.close()

asyncio.run(main())
```

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/23_cross_thread_memory.py)

## 进阶 / 组合例子（抽取 → 固话 → 检索链路）

把一段包含显式记忆语句的消息交给 `consolidate`，自动抽取并固话，然后检索回来：

```python
import asyncio
from super_harness import MemoryManager, SQLiteMemoryStore
from super_harness.models import Message, MessageRole

async def main() -> None:
    store = SQLiteMemoryStore("memory.sqlite3")
    manager = MemoryManager(store)
    records = await manager.consolidate(
        "thread-a", [Message(MessageRole.USER, "Remember: use jasmine tea")]
    )
    print(records)
    await store.close()

asyncio.run(main())
```

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/24_memory_extraction.py)

### 自定义抽取器

```python
import asyncio
from super_harness import MemoryCandidate, MemoryKind, MemoryManager, SQLiteMemoryStore
from super_harness.memory.pipeline import MemoryExtractor
from super_harness.models import Message

class MyExtractor(MemoryExtractor):
    async def extract(self, messages):
        out = []
        for message in messages:
            if "CONSOLIDATE:" in message.content:
                for line in message.content.splitlines():
                    if line.startswith("CONSOLIDATE:"):
                        out.append(MemoryCandidate(line.split(":", 1)[1].strip(), MemoryKind.SUMMARY))
        return tuple(out)

async def main() -> None:
    store = SQLiteMemoryStore("memory.sqlite3")
    manager = MemoryManager(store, extractor=MyExtractor())
    records = await manager.consolidate("thread-a", [Message(1, "CONSOLIDATE: meet the deadline")])
    print(records)
    await store.close()

asyncio.run(main())
```

---

# 外部 RAG（External RAG）

`HTTPRAGProvider` 是对**冻结的 `POST /retrieve` RAG 契约**的适配器：向 `RAG_BASE_URL/retrieve` 发送 `{"query": ..., "top_n": ...}`，解析返回的 `results` 列表为 `RAGDocument`。适合把独立知识库接入 Agent。

## 请求 / 响应契约

- 端点：`POST {RAG_BASE_URL}/retrieve`
- 请求体：`{"query": "<检索词>", "top_n": <数量>}`
- 可选鉴权：`Authorization: Bearer <RAG_API_KEY>`
- 响应：JSON 对象，`results` 为列表；每项可以是字符串，或 `{"text": ..., "score": ..., "source": ..., "metadata": {...}}` 对象。

## 基本用法

```python
import asyncio
from super_harness import HTTPRAGProvider

async def main() -> None:
    for document in await HTTPRAGProvider().retrieve("release policy", top_n=3):
        print(document.source, document.score, document.text)

asyncio.run(main())
```

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/13_rag_retrieve.py)

## 真实场景例子（注入上下文）

用 `KnowledgeRouter.rag_context` 把检索文档渲染成上下文片段，供注入 Agent：

```python
import asyncio
from super_harness import KnowledgeRouter
from super_harness.knowledge import HTTPRAGProvider

async def main() -> None:
    router = KnowledgeRouter(rag=HTTPRAGProvider())
    for fragment in await router.rag_context("authentication rules"):
        print(fragment.render().content)

asyncio.run(main())
```

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/14_rag_context.py)

## 进阶 / 组合例子（注册为 Tool）

把 RAG 检索注册成模型可见 Tool，让模型在需要时自行检索：

```python
from super_harness import HTTPRAGProvider, KnowledgeRouter

router = KnowledgeRouter(rag=HTTPRAGProvider())
rag_tool = router.tools()[0]
print(rag_tool.qualified_name, rag_tool.description)
```

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/15_rag_tool.py)

生成的 Tool 的 `qualified_name` 为 `knowledge.rag_retrieve`，声明参数 `query`、`top_n`。

## Mock RAG 服务教程

仓库自带一个**真实可运行的 Mock RAG 服务**：`tests/services/rag_server/app.py` 中的 `RAGHandler` 实现了一个 `ThreadingHTTPServer` handler，通过 `POST /retrieve` 提供**确定性的 token 重叠检索**，并支持可选 Bearer 鉴权与多个测试端点。

它从同目录的 `corpus.json` 加载语料（例如 "The release policy requires a canary deployment before production." 等三条）。

### 如何启动

`RAGHandler` 本身不提供 `__main__` 入口，需要用 `ThreadingHTTPServer` 把它跑起来。可用以下代码在 `127.0.0.1:8765` 启动：

```python
import threading
from http.server import ThreadingHTTPServer
from tests.services.rag_server import RAGHandler

RAGHandler.token = "rag-secret-token"   # 可选：启用 Bearer 鉴权；不需要可设为 None
server = ThreadingHTTPServer(("127.0.0.1", 8765), RAGHandler)
threading.Thread(target=server.serve_forever, daemon=True).start()
print("RAG mock listening on http://127.0.0.1:8765")
```

### 指向它的提供商

启动后，把 `HTTPRAGProvider` 指向该服务：

```python
import asyncio
from super_harness import HTTPRAGProvider

async def main() -> None:
    provider = HTTPRAGProvider("http://127.0.0.1:8765", api_key="rag-secret-token")
    for document in await provider.retrieve("release policy", top_n=2):
        print(document.source, document.score, document.text)

asyncio.run(main())
```

### 测试端点

`RAGHandler` 支持若干特殊路径，用于模拟异常与边界（`RAG_BASE_URL` 指基础 URL）：

| 路径 | 行为 |
| --- | --- |
| `/retrieve` | 正常检索，按 token 重叠排序并限制 `top_n` |
| `/test/empty` | 返回 `{"results": []}`（空结果） |
| `/test/slow` | 人为延迟 0.25s（测试超时） |
| `/test/error` | 返回 500（测试错误路径） |
| `/test/malformed` | 返回 200 但无 `results`（测试畸形响应） |
| 其它路径 | 返回 404 |

> 鉴权校验发生在任何路径处理之前：若设置了 `RAGHandler.token`，请求头必须为 `Authorization: Bearer <token>`，否则返回 401。

---

# Web 搜索（Web Search）

`ZhipuWebSearchProvider` 调用智谱独立 web 搜索接口（默认 `https://open.bigmodel.cn/api/paas/v4/web_search`），返回归一化的 `SearchResponse`，其中包含 `title` / `url` / `snippet` / `published_at` 等字段。

## 基本用法

```python
import asyncio
from super_harness import ZhipuWebSearchProvider

async def main() -> None:
    response = await ZhipuWebSearchProvider().search("Python async context manager", top_n=3)
    for item in response.results:
        print(item.title, item.url)

asyncio.run(main())
```

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/10_search_basic.py)

## 真实场景例子（注入上下文）

用 `KnowledgeRouter.search_context` 把搜索结果渲染成带来源 URL 的上下文片段：

```python
import asyncio
from super_harness import KnowledgeRouter, ZhipuWebSearchProvider

async def main() -> None:
    router = KnowledgeRouter(search=ZhipuWebSearchProvider())
    for fragment in await router.search_context("latest Python release", top_n=2):
        print(fragment.source, fragment.content)

asyncio.run(main())
```

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/11_search_context.py)

## 进阶 / 组合例子（注册为 Tool）

```python
from super_harness import KnowledgeRouter, ZhipuWebSearchProvider

router = KnowledgeRouter(search=ZhipuWebSearchProvider())
for item in router.tools():
    print(item.qualified_name, item.provider_definition().parameters)
```

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/12_search_tool.py)

生成的 Tool 的 `qualified_name` 为 `knowledge.web_search`。

---

# 视觉（Vision）

`ZhipuVisionProvider` 基于 GLM-4V（默认模型 `glm-4v-flash`），`analyze(image, prompt)` 接受三种图片输入：**本地文件路径**、**HTTPS/HTTP URL**、**Data-URI**。本地文件会被校验为真实图片（PNG/JPEG/GIF/WebP 魔数）并转为 Base64 Data-URI 发送。

## 基本用法

本地图片：

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

## 真实场景例子（URL 图片）

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

## 进阶 / 组合例子（注册为 Tool）

```python
from super_harness import KnowledgeRouter, ZhipuVisionProvider

router = KnowledgeRouter(vision=ZhipuVisionProvider())
vision_tool = router.tools()[0]
print(vision_tool.qualified_name, vision_tool.provider_definition().parameters)
```

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/18_vision_tool.py)

生成的 Tool 的 `qualified_name` 为 `knowledge.vision_analyze`，声明参数 `image`、`prompt`。

---

# KnowledgeRouter（组合路由）

`KnowledgeRouter` 把所有知识提供商聚合到一个门面，提供两种使用形态：**上下文注入**（`search_context` / `rag_context`，返回 `ContextFragment`）与 **Tool 暴露**（`tools()`，返回模型可见 Tool）。可同时配置 `search`、`rag`、`vision` 任意组合；未配置的提供商在调用对应方法时会抛 `RuntimeError`。

## 基本用法（上下文注入）

```python
import asyncio
from super_harness import KnowledgeRouter, ZhipuWebSearchProvider

async def main() -> None:
    router = KnowledgeRouter(search=ZhipuWebSearchProvider())
    for fragment in await router.search_context("latest Python release", top_n=2):
        print(fragment.source, fragment.content)

asyncio.run(main())
```

## 方法速查

- `search(query, *, top_n=5)` → `SearchResponse`（未配置搜索时抛 `RuntimeError`）。
- `retrieve(query, *, top_n=3)` → `tuple[RAGDocument, ...]`（未配置 RAG 时抛 `RuntimeError`）。
- `vision(image, prompt)` → `VisionResult`（未配置视觉时抛 `RuntimeError`）。
- `search_context(query, *, top_n=5)` → `tuple[ContextFragment, ...]`，来源为结果 URL，kind 为 `RAG`。
- `rag_context(query, *, top_n=3)` → `tuple[ContextFragment, ...]`，来源为文档 source，kind 为 `RAG`。
- `tools()` → `tuple[Tool, ...]`，按已配置提供商生成：`knowledge.web_search`、`knowledge.rag_retrieve`、`knowledge.vision_analyze`（均 `supports_parallel=True`）。

## 真实场景例子（全部配置并注入 Agent）

同时配置搜索 + RAG，把两组片段都注入 Agent 上下文，让模型基于"最新网页证据 + 企业知识库"作答：

```python
import asyncio
from super_harness import Agent, DeepSeekProvider, HTTPRAGProvider, KnowledgeRouter, ZhipuWebSearchProvider

async def main() -> None:
    router = KnowledgeRouter(
        search=ZhipuWebSearchProvider(),
        rag=HTTPRAGProvider(),
    )
    web_fragments = await router.search_context("Super Harness release notes", top_n=2)
    rag_fragments = await router.rag_context("release policy", top_n=2)
    fragments = web_fragments + rag_fragments
    agent = Agent(DeepSeekProvider(), context=fragments)
    print(agent.run("Summarize what we know about releases.").text)

asyncio.run(main())
```

## 进阶 / 组合例子（把全部能力暴露为 Tool）

把搜索、RAG、视觉一次性暴露为模型可见 Tool，交给 `Agent` 使用：

```python
from super_harness import Agent, DeepSeekProvider, HTTPRAGProvider, KnowledgeRouter, ZhipuVisionProvider, ZhipuWebSearchProvider

router = KnowledgeRouter(
    search=ZhipuWebSearchProvider(),
    rag=HTTPRAGProvider(),
    vision=ZhipuVisionProvider(),
)
agent = Agent(DeepSeekProvider(), tools=router.tools())
print(agent.run("Look up the current Python version, check the release policy, and read image.png.").text)
```

---

# API 用法速查

```python
# 工作记忆
memory = WorkingMemory(max_items=64)
memory.set("key", value); memory.get("key", default); memory.delete("key"); memory.clear()
fragment = memory.context()              # ContextFragment | None
mapping = memory.snapshot()              # dict

# 长期记忆
store = SQLiteMemoryStore("memory.sqlite3")
record = await store.remember(MemoryCandidate("...", kind=MemoryKind.FACT), source_thread_id="t")
matches = await store.search("query", limit=5, exclude_thread_id="t", kinds=(MemoryKind.FACT,))
await store.close()
manager = MemoryManager(store, extractor=None, trace_sink=traces.append)
records = await manager.consolidate(thread_id, messages)
fragments = await manager.retrieve_context("query", current_thread_id="t", limit=5)

# 外部 RAG
provider = HTTPRAGProvider(base_url, api_key=None, retrieve_path="/retrieve", timeout=10.0, retries=1)
documents = await provider.retrieve("query", top_n=3)   # tuple[RAGDocument, ...]

# Web 搜索
search = ZhipuWebSearchProvider(api_key=None, timeout=20.0, retries=2)
response = await search.search("query", top_n=3)        # SearchResponse(results=[SearchResult])

# 视觉
vision = ZhipuVisionProvider(api_key=None, model="glm-4v-flash", timeout=30.0, retries=1)
result = await vision.analyze(Path("image.png") | "https://...", "prompt")  # VisionResult

# 组合路由
router = KnowledgeRouter(search=..., rag=..., vision=...)
fragments = await router.search_context("q", top_n=5)   # tuple[ContextFragment, ...]
fragments = await router.rag_context("q", top_n=3)      # tuple[ContextFragment, ...]
tools = router.tools()                                  # tuple[Tool, ...]
```

# 事件（Events）

各提供商在配置 `observer` 时发出如下事件（均不带内容，payload 只含元数据）：

| 事件 | 提供者 | payload 关键字段 |
| --- | --- | --- |
| `search.started` / `search.completed` / `search.failed` | 搜索 | `provider`, `operation_id`, `item_count`, `duration_ms`, `error_class` |
| `rag.started` / `rag.completed` / `rag.failed` | RAG | `provider`, `operation_id`, `item_count`, `duration_ms`, `error_class` |
| `vision.started` / `vision.completed` / `vision.failed` | 视觉 | `provider`, `model`, `operation_id`, `item_count`, `duration_ms`, `error_class` |

跟踪（`trace_sink`）：各提供商还支持 `trace_sink: Callable[[KnowledgeTrace], ...]`，接收 `KnowledgeTrace(operation, provider, success, item_count, metadata)`。`MemoryManager` 支持 `trace_sink` 接收 `MemoryTrace(operation, success, item_count, thread_id)`。

示例——在测试中统计 RAG 调用：

```python
traces: list = []
provider = HTTPRAGProvider("http://127.0.0.1:8765", trace_sink=traces.append)
```

# 错误 / 超时 / 重试（Errors / Timeouts / Retries）

| 场景 | 异常 | 说明 |
| --- | --- | --- |
| 缺少搜索 Key | `SearchError` | 未设置 `ZHIPU_SEARCH_API_KEY` |
| 缺少视觉 Key | `VisionError` | 未设置 `ZHIPU_VISION_API_KEY` |
| 缺少 RAG URL | `RAGError` | 未设置 `RAG_BASE_URL` |
| 空 query / 非正 top_n | `ValueError` | `search` / `retrieve` / `analyze` 入参校验 |
| 本地图片无效 / 超限 | `VisionError` | 无法读取、超 `max_image_bytes`（默认 10MB）、非识别格式 |
| 传输 / HTTP 5xx / 429 | 对应 `*Error` | 可重试；带指数退避（`0.05 * 2**attempt`） |
| HTTP 4xx（除 429） | 对应 `*Error` | 立即失败，不重试 |
| 响应畸形 | 对应 `*Error` | RAG 缺 `results`、结果项形状非法等 |
| 提供商未配置 | `RuntimeError` | 调用 `router.search` / `retrieve` / `vision` 但对应 provider 为 `None` |

重试预算由各 provider 的 `retries` 参数控制（搜索默认 2、RAG 默认 1、视觉默认 1）。`HTTPRAGProvider` 默认超时 10s、`ZhipuWebSearchProvider` 默认 20s、`ZhipuVisionProvider` 默认 30s。调用方取消（`asyncio.CancelledError`）始终向上传播。

# 与其他功能组合（Combining）

- **记忆 + 持久 Thread**：`SQLiteThreadStore` 的 `Thread.messages` 是单 Thread 持久对话记忆；`SQLiteMemoryStore` 补充跨 Thread 的长期事实。可先用 `thread.debug_context()` 检查已注入的 RAG/记忆片段及其大小。
- **RAG / 搜索 + 上下文注入**：把 `search_context` / `rag_context` / `manager.retrieve_context` 返回的 `ContextFragment` 直接传入 `Agent(context=...)`，一次性注入。
- **RAG / 搜索 / 视觉 + Tool**：`router.tools()` 交给 `Agent(tools=...)`，让模型按需调用；`supports_parallel=True` 允许单步并发调用多个知识 Tool。
- **压缩 + 记忆**：`thread.compact()` 负责压缩对话历史；长期记忆固话独立于压缩，可跨会话复用。
- **观测 + 知识**：为知识 provider 配置 `observer` 即可在 `Observability` 中看到 `search.*` / `rag.*` / `vision.*` 事件。

# 安全注意事项（Security Notes）

- 凭据（`ZHIPU_SEARCH_API_KEY`、`ZHIPU_VISION_API_KEY`、`RAG_API_KEY`）在请求时从环境变量读取，**绝不写入事件、日志或 trace**。
- 搜索 / RAG / 记忆片段在上下文中是**用户角色数据**，不能覆盖开发者或项目指令；`ContextKind.RAG` / `MEMORY` 优先级低于 `DEVELOPER` / `PROJECT`。
- 默认 `HeuristicMemoryExtractor` 刻意**不访问任何凭据**，只匹配显式 `Remember:` / `Memory:` 行，避免把敏感信息抽入长期记忆。
- 外部 RAG 服务视为不可信输入：检索到的文档内容应被当作数据而非指令权威。
- 远程图片 URL 会被直接发送给视觉提供商；Data-URI / 本地文件会被 Base64 编码后发送，请注意待分析内容本身的敏感性。
- 生产环境应为 RAG 服务启用 `RAG_API_KEY`（Bearer 鉴权）并用 HTTPS。

# 故障排查（Troubleshooting）

| 现象 | 排查 |
| --- | --- |
| `SearchError: ZHIPU_SEARCH_API_KEY is required` | 未设置搜索 Key；`export ZHIPU_SEARCH_API_KEY` 或在构造函数传 `api_key=` |
| `VisionError: ZHIPU_VISION_API_KEY is required` | 未设置视觉 Key |
| `RAGError: RAG_BASE_URL is required` | 未设置 `RAG_BASE_URL`；确认 RAG 服务已启动 |
| 调用 `router.search` 抛 `RuntimeError` | 构造 `KnowledgeRouter` 时未传入对应 provider |
| RAG 返回空结果 | 检查 `/test/empty` 或语料不匹配；确认 `top_n` 有效 |
| RAG 超时 / 500 | 用 `/test/slow`、`/test/error` 复现；调大 `timeout` 或检查服务 |
| RAG 响应畸形 | 用 `/test/malformed` 复现；确认服务返回 `results` 列表 |
| RAG 返回 401 | `RAGHandler.token` 已设置但未传 `api_key=`，或 token 不匹配 |
| 本地图片报"not a recognized image" | 确认文件是 PNG/JPEG/GIF/WebP，且魔数正确 |
| 长期记忆没检索到 | 默认抽取器只认 `Remember:` / `Memory:` 前缀；确认消息里用了显式语句 |
| `context()` 返回 `None` | 工作记忆为空；先 `set` 若干键值 |

# 链接

- 可运行示例：`examples/10_search_basic.py` 至 `examples/24_memory_extraction.py`（见上文各例链接）。
- 相关 Internals：`src/super_harness/memory/`（working / types / store / pipeline）与 `src/super_harness/knowledge/`（providers / routing / types）。
- API 参考：`HTTPRAGProvider`、`ZhipuWebSearchProvider`、`ZhipuVisionProvider`、`KnowledgeRouter`、`WorkingMemory`、`SQLiteMemoryStore`、`MemoryManager`、`MemoryCandidate`、`HeuristicMemoryExtractor`。
- Mock RAG 服务：`tests/services/rag_server/app.py`（handler）与 `tests/services/rag_server/corpus.json`（语料）。
- 测试：`tests/test_knowledge.py`、`tests/test_memory.py`。
