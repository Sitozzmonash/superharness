---
id: guide-part1-start
title: 用户指南 Part I —— 开始
sidebar_position: 1
description: 安装、五分钟快速开始、项目布局、配置与 .env、第一个 Agent、同步与异步运行。
---

# Part I —— 开始（Start）

本页覆盖 Super Harness 用户指南的第一部分：它是什么、如何安装、如何在一分钟内跑通第一个 Agent、项目里会出现哪些目录、如何用配置文件与环境变量控制行为，以及同步与异步 API 的区别。后续 Part（线程、工具、上下文、MCP、多 Agent、Workflow 等）会在各自的页面展开。

## 1. 这是什么 / 何时使用

Super Harness 是一个 **Python 原生、受 Codex 启发、与提供商无关（provider-agnostic）的 Agent 运行时**。它把"对话式 Agent"拆成三层模型：

- **Agent**：一个已配置的入口对象，持有一个提供商（provider）、系统指令、工具注册表、审批策略与可选的持久化存储。`Agent` 本身不保存对话，它负责创建独立的 `Thread`。
- **Thread**：一条有序的对话历史与轮次（turn）集合。`agent.run(...)` 会为每次调用开启一个全新的 Thread；需要连续对话时，显式创建 `agent.thread()` 并在其上反复调用 `thread.run(...)`。
- **Turn**：Thread 内的一次模型交互循环，可能包含多轮"模型 → 工具 → 模型"的步骤（`max_model_steps` 默认 8）。

设计目标是提供一套与具体云端厂商解耦的编程模型：默认提供商是 DeepSeek（中国大陆可直接访问），并支持任何 OpenAI 兼容端点；搜索、视觉、RAG 通过外部适配器接入。你可以用它构建编码助手、研究流水线、企业知识问答、自动化脚本、以及自主/确定/混合三种编排模式的应用。

**何时使用本页**：你是第一次接触 Super Harness；需要在本机安装并验证环境；想知道一个项目里各目录/文件的作用；想用配置文件与环境变量做多环境切换；或者不清楚该用 `run` 还是 `arun`。

## 2. 前置条件（Prerequisites）

- **Python 3.11+**。项目在 `pyproject.toml` 中声明 `requires-python = ">=3.11"`，并在 CI 与 pyright 配置中按 3.11 校验。Windows 上建议通过官方安装包或 `uv` 管理解释器。
- **pip** 或 **uv** 用于安装本包与依赖。
- **可用的模型提供商凭据**。默认 `DeepSeekProvider` 在请求时读取环境变量 `DEEPSEEK_API_KEY`。没有凭据时，`agent.run(...)` 会抛出 `ModelError`，提示 `missing credential for provider deepseek: set DEEPSEEK_API_KEY`。
- **git**（可选但推荐）：项目定位（`.git` 根目录发现）、`AGENTS.md` 上下文加载、以及 `super-harness doctor` 诊断项都会用到 git。
- **网络可达性**：DeepSeek API 默认端点为 `https://api.deepseek.com`；OpenAI 兼容提供商需要各自的 `base_url`。

:::info 关于凭据读取时机
凭据在每次请求时从指定的环境变量读取（见下文"配置"一节），**不会**缓存在 Agent 或事件中，也不会出现在诊断输出里。这也是 `super-harness provider test` 这类命令要求从环境变量而非参数读取密钥的原因。
:::

## 3. 安装（Installation）

从仓库根目录（含 `pyproject.toml` 的目录）安装开发版：

```bash
python -m venv .venv
# Windows (git-bash / PowerShell):
# .venv/Scripts/activate
# Linux / macOS:
# source .venv/bin/activate
python -m pip install -e ".[dev]"
```

- `-e`（editable）安装使 `src/super_harness` 的改动即时生效，开发时不需要重装。
- `[dev]` 额外安装 `build`、`hatchling`、`pyright`、`pytest`、`pytest-asyncio`、`ruff`，用于开发与校验。
- 运行期最小依赖仅五个：`httpx`、`mcp`、`packaging`、`pydantic`、`pyyaml`。
- 可选特性：OpenTelemetry 追踪需要 `pip install -e ".[otel]"`。

安装后，控制台脚本 `super-harness` 可用。先做一次完全离线的环境诊断：

```bash
super-harness doctor
```

`doctor` 不访问网络，只检查 Python 版本、git、状态根目录可写性、Docker 及其守护进程、MCP SDK、OpenTelemetry、`DEEPSEEK_API_KEY` 是否配置、配置文件的解析结果、MCP 配置与 Thread 存储。每一项输出 `pass` 或 `warn`。

:::info 检查安装是否成功
```python
from super_harness import Agent, ConfigResolver, DeepSeekProvider
print(Agent, ConfigResolver, DeepSeekProvider)
```
能正常导入即说明包已就位。若控制台脚本缺失，可手动验证 `python -c "from super_harness.cli import main"`。
:::

## 4. 五分钟快速开始（Quick Start）

### 4.1 设置凭据

把 DeepSeek 密钥放进环境：

```bash
export DEEPSEEK_API_KEY   # bash：设置为你的密钥
# PowerShell：通过 $env:DEEPSEEK_API_KEY 设置环境变量
```

### 4.2 跑通第一个 Agent

`examples/01_basic_agent/main.py` 是最小可运行的同步示例，原样如下：

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

运行：

```bash
python examples/01_basic_agent/main.py
```

你会看到一句话的解释输出。`response` 是一个不可变的 `ModelResponse`，`.text` 是最终归一化文本，`.usage` 携带 token 用量（`input_tokens` / `output_tokens` / `total_tokens`），`.tool_calls` 与 `.output_json` 分别对应工具调用与结构化输出（本页后面会用到）。

### 4.3 验证配置解析

运行配置诊断，确认当前的 profile、模型与配置来源：

```bash
super-harness doctor --json
```

JSON 输出中的 `configuration` 项会列出解析出的 `profile`、`model_provider`、`model`、`sandbox_backend`、`sandbox_mode`、`sources`（命中的配置文件路径）、`environment_overrides`（被环境变量覆盖的键名）与 `dotenv`（是否加载了 `.env`）。

### 4.4 验证提供商连通性（需要网络与密钥）

```bash
super-harness provider test --provider deepseek
```

该命令向 DeepSeek 发送一条最小请求（默认提示词 `Reply with exactly: OK`），输出 `provider`、`model`、`response` 与 `usage`。注意它会用 `max_retries=0` 直连，便于快速暴露配置问题。

:::tip 已经 5 分钟了？
完成上面四步意味着：包已安装、环境已诊断、Agent 可以对话、配置解析与提供商连通性都已验证。接下来进入目录布局与配置，把环境差异管起来。
:::

## 5. 项目布局（Project Layout）

一个使用了 Super Harness 的典型项目结构如下：

```text
my-project/
├── .git/                      # git 根目录；配置定位以此为锚
├── .env                       # 可选；仅当 load_dotenv=True 时读取
├── .super-harness/
│   ├── config.toml            # 项目级配置文件（也支持 config.yaml / config.yml）
│   ├── state.db               # 默认 SQLite Thread 持久化路径（PersistenceConfig.path）
│   ├── mcp.json               # CLI 管理的 MCP 服务器配置（MCPConfigStore）
│   ├── skills/                # SkillInstaller 目标目录
│   ├── plugins/               # PluginInstaller 目标目录
│   └── mcp-bundles/           # .mcpb 安装产物
├── AGENTS.md                  # 可选；项目指令，Agent(cwd=...) 时自动加载
├── src/                       # 你的应用代码
└── examples/                  # 官方 91 个可运行示例（01_…–91_…）
```

各路径与 CLI scope 的关系：

- **项目作用域（默认）**：所有本地状态都在 `<git-root>/.super-harness/` 下。CLI 命令默认使用项目作用域。
- **用户作用域**：命令前加 `--global`（如 `super-harness --global doctor`），状态落到用户安装根目录（`~/.super-harness/`，由 `CLIPaths` 解析）。
- **用户配置文件**：`ConfigResolver` 默认的用户配置路径是 `~/.super-harness/config.toml`，可通过 `ConfigResolver(user_config=...)` 覆盖（示例 78/79 就是这样传入 `missing.toml` 以跳过用户层）。

### AGENTS.md 何时生效

`Agent(..., cwd="...")` 会从最近的 `.git` 根目录向下（含 cwd 本身）寻找 `AGENTS.override.md` 或 `AGENTS.md`，**绝不越过 cwd 向上**，并受到默认 32 KiB 的总上下文上限约束。这部分在"上下文"Part 中详述；本页只需要知道：项目根目录放一个 `AGENTS.md`，创建 `Agent(provider, cwd=".")` 时它会被自动注入为开发者指令。

## 6. 配置与 .env（Configuration）

配置的尽头是一个冻结的 `HarnessConfig`（pydantic 模型，`extra="forbid"`）。所有来源都合并进它，再被各子系统和 `Agent` 使用。

### 6.1 优先级：defaults → user → project → env → runtime

`ConfigResolver` 的解析顺序在源码注释中明确写作 `Resolve defaults < user < project < environment < runtime`，后一层覆盖前一层：

1. **默认值（defaults）**：`HarnessConfig` 的字段默认值，以及所选 profile 的预设（见 6.4）。
2. **用户配置（user）**：`~/.super-harness/config.toml`（或 `ConfigResolver(user_config=...)` 指定的文件）。
3. **项目配置（project）**：从 `.git` 根目录向上（实际是向下）找到的 `<project>/.super-harness/config.toml` / `config.yaml` / `config.yml`。
4. **环境变量（environment）**：`SUPER_HARNESS_*` 系列（见 6.3 的表）。
5. **运行时覆盖（runtime）**：`resolve(runtime={...})` 传入的嵌套字典，优先级最高。

`examples/79_config_precedence.py` 用一个临时目录演示"环境与运行时覆盖项目文件"，原样如下：

```python
"""Show environment and runtime precedence over a project file."""

import tempfile
from pathlib import Path

from super_harness import ConfigResolver

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    (root / ".git").mkdir()
    (root / ".super-harness").mkdir()
    (root / ".super-harness" / "config.toml").write_text('[model]\nmodel="project"\n', encoding="utf-8")
    resolved = ConfigResolver(user_config=root / "missing.toml").resolve(
        cwd=root,
        environment={"SUPER_HARNESS_MODEL": "environment"},
        runtime={"model": {"model": "runtime"}},
    )
    print(resolved.config.model.model)
```

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/79_config_precedence.py)

输出是 `runtime`：项目文件里写的 `"project"` 被环境变量 `SUPER_HARNESS_MODEL=environment` 覆盖，而后者的 `"environment"` 又被 `runtime={"model": {"model": "runtime"}}` 覆盖。把 `runtime=` 参数删掉再跑一次，输出会变成 `environment`；把 `environment=` 也删掉，则输出 `project`。

`build_parser` 之外，CLI 的 `doctor --json` 的 `configuration` 项就是 `ResolvedConfig.diagnostics()`：

```python
resolved = ConfigResolver(user_config="missing.toml").resolve(
    environment={"SUPER_HARNESS_PROFILE": "offline"}
)
print(resolved.diagnostics())
```

`diagnostics()` 返回 `profile`、`model_provider`、`model`、`sandbox_backend`、`sandbox_mode`、`sources`（来源文件路径列表）、`environment_overrides`（被使用的环境变量名列表）与 `dotenv`。注意：**它只列出来源路径与被覆盖的变量名，绝不输出任何秘密值**。上面的代码就是 `examples/78_config_profiles.py` 的正文（原样如下）：

```python
"""Resolve a built-in credential-free profile."""

from super_harness import ConfigResolver

resolved = ConfigResolver(user_config="missing.toml").resolve(
    environment={"SUPER_HARNESS_PROFILE": "offline"}
)
print(resolved.diagnostics())
```

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/78_config_profiles.py)

### 6.2 配置文件格式

`ConfigResolver` 同时接受 TOML 与 YAML：`.super-harness/config.toml`、`config.yaml`、`config.yml` 均可。键结构对应 `HarnessConfig` 的嵌套字段：

```toml
# .super-harness/config.toml
profile = "china"

[model]
provider = "deepseek"
model = "deepseek-v4-flash"

[sandbox]
backend = "local"
mode = "workspace_write"

[approval]
mode = "full_access"

[persistence]
backend = "sqlite"
path = ".super-harness/state.db"
```

YAML 等价写法：

```yaml
# .super-harness/config.yaml
profile: china
model:
  provider: deepseek
  model: deepseek-v4-flash
```

任何未知键都会在 `resolve()` 时触发 `ConfigError`（`extra="forbid"`），并在 `details.errors` 中给出 pydantic 的校验错误明细。文件不可读或 TOML/YAML 解析失败同样抛 `ConfigError`（"unable to read configuration" / "configuration root must be an object" / "invalid .env assignment"）。

### 6.3 `SUPER_HARNESS_*` 环境变量表

| 环境变量 | 对应配置键 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `SUPER_HARNESS_PROFILE` | `profile` | `china` | 内置 profile：`china` / `global` / `offline` / `test` |
| `SUPER_HARNESS_MODEL_PROVIDER` | `model.provider` | `deepseek` | 文本模型提供商 |
| `SUPER_HARNESS_MODEL` | `model.model` | `deepseek-v4-flash` | 文本模型名 |
| `SUPER_HARNESS_VISION_PROVIDER` | `vision.provider` | `zhipu` | 视觉模型提供商 |
| `SUPER_HARNESS_VISION_MODEL` | `vision.model` | `glm-4v-flash` | 视觉模型名 |
| `SUPER_HARNESS_SEARCH_PROVIDER` | `web_search.provider` | `zhipu` | 网页搜索提供商 |
| `SUPER_HARNESS_SANDBOX_BACKEND` | `sandbox.backend` | `local` | 沙箱后端（`local` / `docker`） |
| `SUPER_HARNESS_SANDBOX_MODE` | `sandbox.mode` | `workspace_write` | 沙箱访问模式 |
| `SUPER_HARNESS_APPROVAL_MODE` | `approval.mode` | `full_access` | 审批模式 |

被环境变量覆盖到的键会出现在 `diagnostics()["environment_overrides"]` 里，方便审计"当前哪些配置来自环境"。

### 6.4 内置 profile：china / global / offline / test

`ProfileName` 枚举定义了四个内置组合 profile，`_profile_value` 从 runtime → env → 项目 → 用户依次取第一个出现的 `profile` 键，找不到则回退到 `china`：

| Profile | 效果 |
| --- | --- |
| `china`（默认） | 保持 `HarnessConfig` 默认值：DeepSeek 文本模型 + 智谱视觉/搜索。 |
| `global` | `model.provider=openai_compatible`，`model.model=gpt-5`；`vision` 同样切到 OpenAI 兼容。 |
| `offline` | `model.provider=offline`（本地/确定性），`web_search.provider=disabled`，`sandbox.mode=read_only`，适合无网络环境。 |
| `test` | `model.provider=test`（确定性模型），`web_search.provider=test`，`persistence.path=":memory:"`，用于测试与 CI。 |

`profile` 值的大小写不敏感，且 `-dev` 后缀会被剥离（`china-dev` → `china`）。未知值抛 `ConfigError("unknown configuration profile ...")`。

### 6.5 `.env` 加载：默认关闭

`.env` 加载**默认禁用**，并且**绝不会修改 `os.environ`**。只有显式传入 `load_dotenv=True` 时，`resolve()` 才读取 `<project>/.env`：

```python
from super_harness import ConfigResolver

resolved = ConfigResolver().resolve(load_dotenv=True)
print(resolved.dotenv)   # 例如 <project>/.env
```

语义细节（与 `python-dotenv` 不同，务必注意）：

- `.env` 的值通过 `setdefault` 填入解析用的环境快照：**已存在的真实环境变量优先**，`.env` 不会覆盖它们。
- 解析错误（如 `KEY=value extra` 之外的行、或读到 `API KEY=...` 之类非法键名）抛 `ConfigError`，报错带行号。
- 该文件仍只影响"本次解析"，`os.environ` 本身不动。
- `ResolvedConfig.dotenv` 记录实际加载的 `.env` 路径；未加载时为 `None`。

### 6.6 凭据与 SecretProvider

配置负责"选型"，凭据则通过独立的 `SecretProvider` 解析，避免在诊断与日志中暴露。`SecretValue` 的 `str` 与 `repr` 始终显示 `********`，只有显式调用 `.reveal()` 才返回原始值（例如在真正的提供商边界处）。

`examples/80_secret_providers.py` 演示三层组合，原样如下：

```python
"""Resolve secrets explicitly while keeping diagnostics masked."""

from super_harness import CompositeSecretProvider, EnvironmentSecretProvider, MappingSecretProvider

secrets = CompositeSecretProvider(
    (EnvironmentSecretProvider({}), MappingSecretProvider({"SERVICE_TOKEN": "demo-secret"}))
)
token = secrets.get("SERVICE_TOKEN")
print(token, token.reveal() == "demo-secret" if token else False)
```

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/80_secret_providers.py)

- `EnvironmentSecretProvider`：从 `os.environ`（或传入的 mapping）按名取值。
- `MappingSecretProvider`：从一个静态 mapping 取值（测试/演示用）。
- `CompositeSecretProvider`：按顺序尝试各子 provider，返回第一个命中。
- 三者都实现 `SecretProvider.get(name) -> SecretValue | None` 协议；`None` 表示未命中。

## 7. 第一个 Agent（First Agent）

`Agent` 的完整构造签名（`src/super_harness/agent.py`）：

```python
Agent(
    provider: ModelProvider,
    *,
    instructions: str | None = None,
    tools: Iterable[Tool] = (),
    approval: ApprovalPolicy | None = None,
    hooks: HookRegistry | None = None,
    observer: EventObserver | None = None,
    max_model_steps: int = 8,
    context: Iterable[ContextFragment] = (),
    cwd: str | None = None,
    agents_loader: AgentsMdLoader | None = None,
    store: SQLiteThreadStore | None = None,
    compaction_threshold_chars: int = 100_000,
    persona: Persona | None = None,
)
```

第一个参数是位置参数 `provider`，其余全是关键字参数。`provider` 只需满足 `ModelProvider` 协议：`name`、`capabilities`、`complete(request)`、`stream(request)`、`aclose()`。这意味着你可以：

- 用现成的 `DeepSeekProvider()`；
- 用 `OpenAICompatibleProvider(model=..., base_url=..., api_key_env=...)` 接任意 OpenAI 兼容端点；
- 自己实现一个本地/确定性 Provider（`examples/07_durable_thread/main.py` 里的 `LocalProvider` 就是 22 行的最小实现，Part II 会讲到）。

**`instructions` 是开发者权威指令**：它在每个 turn 的请求里以 `developer` 角色置于上下文最前（DeepSeek 原生 API 拒绝 `developer` 角色，`DeepSeekProvider._message` 会自动映射为 `system`）。`Agent(provider, instructions="...")` 等价于给每一次对话一个固定开场白。

### Agent 与 Thread 的关系

- `agent.run(input)` / `agent.arun(input)`：便捷方法，内部等价于 `agent.thread().run(input)`——**每次调用都开启一个全新 Thread**，互不共享历史。
- 需要多轮对话时：`thread = agent.thread()`，然后反复 `thread.run(...)`，消息会累积在同一 Thread 里。
- `agent.resume(thread_id)` / `agent.fork(thread_id)` 需要 `store`（`SQLiteThreadStore`），属于持久化 Part 的内容，这里不展开。

## 8. 同步与异步（Sync vs Async）

运行时**原生异步**：所有模型 I/O 都是协程。同步 API 是在"没有活跃事件循环"的前提下，用 `asyncio.run` 包一层收集器实现的（`thread.py` 中的 `_sync`）。

### 8.1 同一套操作的四个入口

| 同步 | 异步 | 返回 |
| --- | --- | --- |
| `agent.run(input)` | `await agent.arun(input)` | `ModelResponse`（最终归一化结果） |
| `agent.stream(input)` | `async for ... in agent.astream(input)` | `Event`（不可变事件流） |

`thread` 上也有同名方法：`thread.run` / `thread.arun` / `thread.stream` / `thread.astream`。

### 8.2 铁律：不要在活跃事件循环里调用同步 API

`_sync` 的实现是：

```python
def _sync(operation: AsyncIterator[T]) -> list[T]:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        async def collect() -> list[T]:
            return [item async for item in operation]
        return asyncio.run(collect())
    raise RuntimeError("sync API cannot run inside an active event loop; use the async API")
```

也就是说：

- 在**没有**事件循环的普通脚本里，`agent.run(...)` 正常工作。
- 在**运行着**事件循环的协程内部（例如 `async def main()` 里，或 Jupyter/服务器里已有 loop），调用 `agent.run(...)` 会直接抛 `RuntimeError: sync API cannot run inside an active event loop; use the async API`。这时必须用 `await agent.arun(...)` 或 `async for ... in agent.astream(...)`。

正确的异步写法是 `async def main()` + `asyncio.run(main())`；同步脚本则直接调 `run`/`stream`。

### 8.3 异步示例：订阅事件流

`examples/02_streaming/main.py` 演示在异步环境里消费事件流，原样如下：

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

要点：

- `agent.aclose()` 在 `finally` 中关闭提供商持有的 `httpx.AsyncClient`；同步脚本没有这个负担，但异步长进程应显式关闭。
- 事件是 **不可变** 的 `Event`：`event.type`、`event.payload`（只读 mapping）、`event.thread_id`、`event.turn_id`、`event.event_id`、`event.timestamp`。
- 文本增量以 `model.text.delta` 到达，随后是 `model.completed` 与 `turn.completed`；`turn.completed` 的 `payload["response"]` 就是最终 `ModelResponse`。

### 8.4 同步与异步的正确取舍

- **脚本/自动化/CLI 的一次性任务**：直接用同步 `run`，最简单。
- **Web 服务、并发任务、需要流式 UI 或事件驱动的集成**：用 `arun` / `astream`。
- **两者混用**：在异步代码里只碰 `await` 版本；模块顶层、`__main__` 或 `asyncio.run(...)` 之外才允许同步入口。不要把 `asyncio.run` 嵌套调用，也不要期望 `run` 会返回给你一个可等待对象。

## 9. 基础例子（Basic Example）

**最小同步 Agent**：见 4.2 的 `examples/01_basic_agent/main.py`（本节即以其为准，不重复粘贴）。

运行它需要且仅需要：包已安装 + `DEEPSEEK_API_KEY` 已设置。它演示了本框架最核心的三行：

```python
provider = DeepSeekProvider()
agent = Agent(provider, instructions="Answer clearly and briefly.")
response = agent.run("Explain what an agent runtime does in one sentence.")
```

`Agent.run` 会开启一个全新 Thread：`response` 是归一化后的 `ModelResponse`，不依赖任何厂商专属字段。

## 10. 真实场景例子（Real-world Example）

**多环境项目：按 profile 解析配置，再据此构造 Agent。** 真实项目通常有一份项目配置文件，希望在 CI（`test`）、离线开发（`offline`）、本地联调（`china`）之间切换，而不是改代码。把 `ConfigResolver` 与 `Agent` 组合即可：

```python
"""Resolve the project configuration, then build an Agent from it."""

from super_harness import Agent, ConfigResolver, DeepSeekProvider

resolved = ConfigResolver().resolve()          # defaults < user < project < env
config = resolved.config
print(resolved.diagnostics())

provider = DeepSeekProvider(model=config.model.model)
agent = Agent(provider, instructions="Answer clearly and briefly.")
response = agent.run("Explain what an agent runtime does in one sentence.")
print(response.text)
```

配合 6.4 的 profile：CI 里 `SUPER_HARNESS_PROFILE=test` 走确定性模型；需要离线验证时 `offline` 直接禁用搜索并把沙箱切到 `read_only`。`config.model.model` 始终反映"合并后"的模型名（例 79 已经证明：项目文件里的 `model` 默认可能被环境变量换掉）。

**交互式对话脚本**：真实地的多轮助手要用同一个 Thread：

```python
from super_harness import Agent, DeepSeekProvider

agent = Agent(DeepSeekProvider(), instructions="You are a terse CLI assistant.")
thread = agent.thread()
first = thread.run("List three agent runtime safety rules.")
second = thread.run("Now turn the first rule into a one-line mnemonic.")
print(first.text)
print(second.text)
print(f"history length: {len(thread.messages)}")
```

两次 `thread.run` 共享历史——第二次提问时模型能看到第一次的问答——这是 `agent.run` 做不到的（它每次都新建 Thread）。

## 11. 进阶/组合例子（Advanced Example）

**组合：配置 + 密钥 + 流式异步。** 把前三节的能力拼起来：用 `ConfigResolver` 决定模型与 profile，用 `CompositeSecretProvider` 显式解析应用级密钥（只进日志脱敏边界，不经过配置诊断），再用 `astream` 逐步消费事件：

```python
"""Combine config resolution, explicit secrets, and async streaming."""

import asyncio

from super_harness import (
    Agent,
    CompositeSecretProvider,
    ConfigResolver,
    DeepSeekProvider,
    EnvironmentSecretProvider,
    MappingSecretProvider,
)


async def main() -> None:
    resolved = ConfigResolver().resolve(load_dotenv=True)
    config = resolved.config

    secrets = CompositeSecretProvider(
        (EnvironmentSecretProvider(), MappingSecretProvider({"DEMO_SECRET": "demo"}))
    )
    secret = secrets.get("DEMO_SECRET")
    token_label = "configured" if secret else "missing"

    provider = DeepSeekProvider(model=config.model.model)
    agent = Agent(provider, instructions="Answer clearly and briefly.")
    try:
        async for event in agent.astream(
            f"In one sentence, note the secret status: {token_label}."
        ):
            if event.type == "model.text.delta":
                print(event.payload["delta"], end="", flush=True)
        print()
    finally:
        await agent.aclose()


if __name__ == "__main__":
    asyncio.run(main())
```

本示例中的每个符号（`ConfigResolver` / `CompositeSecretProvider` / `EnvironmentSecretProvider` / `MappingSecretProvider` / `DeepSeekProvider` / `Agent` / `agent.astream` / `event.payload`）都已在 `src/super_harness` 中验证存在；把它作为模板扩展即可。

**进阶 2：结构化输出与工具调用的异步写法。** `examples/03_structured_and_tools/main.py` 演示 `output_schema`（严格 JSON）与 `tools=[ToolDefinition(...)]` 在异步下的用法，原样如下：

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

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/03_structured_and_tools/main.py)

注意两点与"开始"主题直接相关的行为：

1. `output_schema` 传 JSON Schema，`response.output_json` 是本地校验过的解析结果；DeepSeek 走 chat completions 时 `DeepSeekProvider` 会自动把 `response_format` 放宽为 `json_object`，再由本地 `_structured` 校验一致性，保证"严格 schema"仍然成立。
2. `ToolCall` 是归一化值：`call.call_id`、`call.name`、`call.arguments`（解析后的 dict）与 `call.raw_arguments`（原始 JSON 字符串）。阶段 1 只返回调用，阶段 2（执行）由 ToolExecutor 接管——本页不展开，在工具 Part 详述。

## 12. API 用法速查（API Cheat Sheet）

本页涉及的公共 API（全部已在 `src/super_harness` 的 `__init__.py` / `agent.py` / `config/` / `models/` 中验证存在）：

```python
# 提供商
DeepSeekProvider(*, model="deepseek-v4-flash", api_key=None,
                  base_url="https://api.deepseek.com", wire_api=WireAPI.CHAT_COMPLETIONS,
                  timeout=60.0, max_retries=2, stream_max_retries=1) -> DeepSeekProvider

# Agent
Agent(provider, *, instructions=None, tools=(), approval=None, hooks=None,
      observer=None, max_model_steps=8, context=(), cwd=None,
      agents_loader=None, store=None, compaction_threshold_chars=100_000,
      persona=None) -> Agent
agent.thread() -> Thread                      # 持久化 Thread（需 store）
agent.run(input, *, tools=(), output_schema=None) -> ModelResponse      # 同步
agent.arun(input, *, tools=(), output_schema=None) -> Awaitable[ModelResponse]
agent.stream(input, *, tools=(), output_schema=None) -> Iterator[Event]
agent.astream(input, *, tools=(), output_schema=None) -> AsyncIterator[Event]
await agent.aclose() -> None

# ModelResponse（不可变）
response.text          # 最终文本
response.tool_calls    # tuple[ToolCall, ...]
response.usage         # Usage(input_tokens, output_tokens, total_tokens)
response.output_json   # Mapping | None（结构化输出）
response.response_id / finish_reason

# 配置
ConfigResolver(*, user_config=None) -> ConfigResolver
resolved = resolver.resolve(*, cwd=None, runtime=None,
                            environment=None, load_dotenv=False) -> ResolvedConfig
resolved.config            # HarnessConfig（冻结）
resolved.config.model.model / .provider
resolved.config.sandbox.backend / .mode
resolved.config.approval.mode
resolved.config.persistence.path
resolved.diagnostics()     # dict：profile/model_provider/model/sources/environment_overrides/dotenv

# 密钥
secrets.get(name) -> SecretValue | None
secret.reveal() -> str                          # 显式边界操作；str/repr 恒为 ********

# CLI（Python 内调用）
from super_harness.cli import main
raise SystemExit(main(["--json", "doctor"]))    # 返回 int（0 成功 / 2 错误）
```

## 13. 事件 / 流式（Events & Streaming）

`astream` / `stream` 产出不可变 `Event`。`Part I` 范围内你至少会看到这些事件类型（`thread.py._astream_unobserved` 逐一发射）：

| 事件类型 | 时机 | 关键 payload |
| --- | --- | --- |
| `turn.started` | 每个 turn 开始 | — |
| `model.started` | 每次模型请求开始 | `provider`、`model`、`step` |
| `model.text.delta` | 文本增量 | `delta`、`step` |
| `model.tool_call.delta` | 工具参数增量（流式） | `index`、`name`、`delta` |
| `model.completed` | 单个模型步骤完成 | `response`、`usage`、`tool_calls`、`step` |
| `model.failed` | 模型步骤异常 | `error_class`、`message`、`step` |
| `tool.started` / `tool.completed` / `tool.failed` | 工具执行生命周期 | `name`、`arguments`、`result`、`success` |
| `turn.steered` | 收到 steering 指令 | `instruction` |
| `turn.completed` | 整个 turn 结束 | `response`（最终 `ModelResponse`） |
| `turn.failed` | turn 异常结束 | `error_type`、`message` |
| `compaction.started` / `compaction.completed` | 自动/手动压缩 | `before_messages`、`summarized_messages` 等 |

`arun` / `run` 的内部实现就是消费 `astream` / `stream` 并取 `turn.completed` 的 `payload["response"]`；所以"最终归一化响应"与"事件流"是同一条路径的两个视图。事件全部不可变、payload 是只读 mapping，且会经过 `observer`（`Agent(observer=...)`）转播——可观测性 Part 会用到。

## 14. 错误 / 超时 / 重试（Errors, Timeouts, Retries）

本页会遇到的异常（`src/super_harness/exceptions.py`）：

- `SuperHarnessError`：所有公共框架错误的基类，带 `message`、`correlation_id`、`details`（脱敏元数据）。
- `ConfigError`：配置无法解析/校验失败（未知 profile、非法 `.env` 行、未知配置键、`extra="forbid"` 违规、文件读取失败）。
- `ModelError`（继承 `ProviderError`）：提供商操作失败，例如缺凭据 `missing credential for provider deepseek: set DEEPSEEK_API_KEY`、HTTP 4xx 认证错误、无效工具 JSON 等。
- `RuntimeError`：两类常见场景——存档 Thread 不可运行（`cannot run an archived thread`）、Thread 已有活跃 turn（`thread already has an active turn`）、以及**在事件循环里调用同步 API**（`sync API cannot run inside an active event loop; use the async API`）。
- `ValueError`：空输入（`turn input must be non-empty`）或 `max_model_steps < 1`。

**超时与重试（OpenAICompatibleProvider / DeepSeekProvider）**：

- 默认 `timeout=60.0` 秒（httpx 客户端超时），`max_retries=2`（非流式）、`stream_max_retries=1`（流式）。
- 可重试的失败：`httpx.TransportError` / `TimeoutException`，以及 HTTP 429 或 HTTP ≥500（`_retryable` 判定）。
- 重试使用指数退避 `0.25 * 2**attempt + 抖动`，上限 2 秒。
- **不可重试**：认证错误与其他 HTTP 4xx 会以 `ModelError` 形式立即失败（`details.status_code` 给出状态码）；`ModelError` 本身从不重试。
- CLI 的 `provider test` 与 `thread resume` 使用 `max_retries=0`，直连以便快速暴露问题。

**工具循环上限**：单个 turn 最多 `max_model_steps`（默认 8）个模型步骤；超限抛 `ToolError("tool loop exceeded maximum of 8 model steps")`。可以通过 `Agent(..., max_model_steps=...)` 调大。

## 15. 与其他功能组合（Combining）

Part I 是其余所有 Part 的地基，先想清楚这三件事再继续：

1. **持久化**：需要跨进程恢复对话时，构造 `SQLiteThreadStore(path)` 并传给 `Agent(store=...)`。`agent.thread()` 会立即持久化，`agent.resume(thread_id)` 重启后可恢复。Part II 详述。
2. **工具与审批**：`Agent(tools=[...])` 把注册表挂到线程；`Agent(approval=...)` 控制默认 `ApprovalPolicy.full_access()`。工具 Part 详述。
3. **上下文与可观测性**：`Agent(context=..., cwd=...)` 装配 AGENTS.md 与外部片段；`Agent(observer=...)` 接收本页 13 节的事件流。对应 Part 详述。

组合使用的顺序没有魔法：配置文件决定"用什么"（provider/profile），`Agent` 构造决定"怎么跑"（instructions/tools/approval），Thread/Store 决定"记住什么"。三者可以独立演进、互不阻塞。

## 16. 安全注意事项（Security Notes）

- **密钥走环境变量，不经参数与日志**：提供商在请求时从 `api_key_env` 指定的变量读取；`provider test` / `thread resume` 的用户输入也绝不携带密钥。`SecretValue` 的 `str`/`repr` 恒为 `********`，`.reveal()` 只在显式边界使用。
- **诊断输出只有元数据**：`ConfigResolver.diagnostics()` 列出的是来源路径与被覆盖的变量名，不是值；CLI 输出统一经 `SecretRedactor` 过滤（`api_key=`、`token=`、`Bearer ...` 模式）。
- **`.env` 默认不加载**：把 `.env` 视为"按需注入"而非"自动生效"；只要不传 `load_dotenv=True`，它对你的进程毫无影响，也不会污染 `os.environ`。
- **配置文件是权威指令的载体**：`instructions` 与 `AGENTS.md` 内容按开发者权威处理；外部数据（搜索/RAG 片段、工具返回）属于用户角色，不能覆盖开发者/项目指令。
- **沙箱边界**（提前提醒）：`LocalSandbox` 是开发者便利设施，不是操作系统隔离；需要强边界时后续使用 `DockerSandbox`。

## 17. 故障排查（Troubleshooting）

| 症状 | 原因与处理 |
| --- | --- |
| `missing credential for provider deepseek: set DEEPSEEK_API_KEY` | 环境里没有 `DEEPSEEK_API_KEY`。设置后重试；CLI 场景确认子进程继承了该变量。 |
| `sync API cannot run inside an active event loop; use the async API` | 在协程/事件循环里调了 `run`/`stream`。改用 `await agent.arun(...)` 或 `async for ... in agent.astream(...)`；脚本顶层用 `asyncio.run(main())`。 |
| `configuration validation failed` | 配置文件里有未知键（`extra="forbid"`）或类型错误。查看 `ConfigError.details["errors"]`（pydantic 校验明细），或先运行 `super-harness doctor --json` 看 `configuration` 项。 |
| `unknown configuration profile ...` | `SUPER_HARNESS_PROFILE` 或配置里的 `profile` 值不是 `china/global/offline/test`（注意允许 `-dev` 后缀）。 |
| `cannot run an archived thread` / `thread already has an active turn` | Thread 状态约束。归档线程只读；一个 Thread 同时只允许一个活跃 turn，后台执行用 `thread.start(...)`（`TurnHandle`）。 |
| `tool loop exceeded maximum of N model steps` | 模型陷入工具循环。给工具更明确的描述，或调大 `max_model_steps`；同时检查审批策略是否一直在拒绝导致模型重试。 |
| `provider response contained no choices` / HTTP 4xx | 通常是与端点/模型名不匹配。用 `super-harness provider test` 验证连通性；OpenAI 兼容端点需要构造 `OpenAICompatibleProvider` 时传对 `base_url`、`model`、`api_key_env`。 |
| 诊断显示 `dotenv: null` | `.env` 没加载（默认关闭）。调用 `resolve(load_dotenv=True)`，且确认 `.env` 位于项目根（`.git` 根目录）。 |
| 网络差时偶发失败 | 传输错误/429/5xx 会自动重试（非流式 2 次、流式 1 次）；若经常超时，调大 `DeepSeekProvider(timeout=...)`。 |

## 18. 链接（Links）

**本页引用的可运行示例**

- [examples/01_basic_agent/main.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/01_basic_agent/main.py) —— 最小同步 Agent（基础）
- [examples/02_streaming/main.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/02_streaming/main.py) —— 异步事件流（同步 vs 异步）
- [examples/03_structured_and_tools/main.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/03_structured_and_tools/main.py) —— 结构化输出 + 工具定义（异步进阶）
- [examples/63_cli_doctor.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/63_cli_doctor.py) —— 以 `--json` 运行 `doctor`
- [examples/78_config_profiles.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/78_config_profiles.py) —— 解析内置 profile
- [examples/79_config_precedence.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/79_config_precedence.py) —— 配置优先级（env/runtime 覆盖项目文件）
- [examples/80_secret_providers.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/80_secret_providers.py) —— SecretProvider 组合与脱敏

**相关文档**

- 用户指南 Part II —— Thread 与持久化（`guide/part2-threads`）
- 用户指南 Part III —— Tools 与审批（`guide/part3-tools`）
- Internals —— 配置解析与运行时（`internals/...`）
- API 参考（`api-reference` / `generated-api`）
- 故障排查总表（`troubleshooting`）