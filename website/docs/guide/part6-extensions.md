---
id: guide-part6-extensions
title: 用户指南 Part VI：指令与扩展
sidebar_position: 6
description: Persona 与角色、AGENTS.md 发现、Agent Skills、MCP、插件与钩子的完整用法指南。
---

# 用户指南 Part VI：指令与扩展（Instructions & Extensions）

本部分覆盖六类「给 Agent 下达指令、把能力注入运行时」的机制，以及它们各自的生命周期与安全边界：

- **Persona 与角色**——把「我是谁、要做什么、不能做什么」固化为带类型的身份层，供 `Agent(..., persona=...)` 复用。
- **AGENTS.md**——从最近的仓库根目录到当前工作目录逐层发现的指令文件。
- **Agent Skills**——标准 `SKILL.md` 包的发现、激活、本地/GitHub 安装与编写。
- **MCP**——通过 stdio 与 Streamable HTTP 连接外部 Model Context Protocol 服务器，导入通用配置、安装 `.mcpb` 包、查询官方注册表。
- **插件（Plugins）**——把 Skills、命名空间化 Tools、MCP 定义、Hooks、资产、人设与命令打包为可安装、可显式启用的单元。
- **钩子（Hooks）**——在会话/轮次/工具/模型等生命周期点注册回调，用于可观测性与应用策略。

所有示例均可直接运行，代码逐字引自 `examples/` 目录；完整可运行文件以链接形式给出。

---

## 1. Persona 与角色

### 这是什么 / 何时使用

`Persona` 是一个**带类型的身份与配置层**。它把名称、角色、目标、约束和应用指令组合成开发者权威；通过限定名 glob 过滤 Tools；记录 Skill 与记忆的作用域；并可容纳具名的子代理角色模板。

把 Persona 传给 `Agent(..., persona=persona)` 时，Agent 会：
1. 校验可选的模型覆盖项（`persona.validate_provider(provider)`）；
2. 用 `persona.tool_scopes` 过滤已配置的 Tools（`persona.select_tools(...)`）；
3. 用 `persona.compose_instructions(...)` 生成统一指令；
4. 随新的 Thread 存储非机密的人设元数据（`persona.metadata()`）。

当多个 Agent 需要共享同一套身份与约束、或希望把「模型选择 + 工具可见性 + 指令」打包成一个可复用对象时使用 Persona。

### 前置条件

- 安装 `super-harness`（`pip install -e .`）。
- 需要运行 Agent 时配置对应的提供商环境变量（例如 `DEEPSEEK_API_KEY`）。

### 快速开始

```python
from super_harness import Persona

persona = Persona("Ari", "release reviewer", "Find release blockers", constraints=("Cite evidence",))
print(persona.compose_instructions("Review the candidate."))
```

### 配置

`Persona` 是 frozen dataclass，字段如下：

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `name` | `str` | （必填） | 身份名，须匹配 `[A-Za-z0-9][A-Za-z0-9._ -]{0,63}` |
| `role` | `str` | （必填） | 角色，如 `release reviewer` |
| `goal` | `str` | （必填） | 目标，如 `Find release blockers` |
| `instructions` | `str` | `""` | 附加指令文本 |
| `constraints` | `tuple[str, ...]` | `()` | 约束列表 |
| `model_override` | `str \| None` | `None` | 要求的模型名；Agent 构造时校验 |
| `tool_scopes` | `tuple[str, ...]` | `("*",)` | 限定名 glob，用于过滤 Tools |
| `skill_scopes` | `tuple[str, ...]` | `("*",)` | 允许的 Skill 作用域 |
| `memory_scope` | `str` | `"thread"` | `none` / `thread` / `long_term` / `both` |
| `subagent_roles` | `Mapping[str, Persona]` | `{}` | 具名子代理角色模板 |

构造时会立即校验：`name` 合法性、`role`/`goal` 非空、`memory_scope` 取值、作用域非空、以及「Persona 不得把自己列为子代理角色」。

### 基础例子：组合身份指令

从 `Persona` 生成稳定、结构化的指令文本：

```python
"""Compose stable Agent identity instructions."""

from super_harness import Persona

persona = Persona("Ari", "release reviewer", "Find release blockers", constraints=("Cite evidence",))
print(persona.compose_instructions("Review the candidate."))
```

`compose_instructions` 输出按 `Identity` / `Role` / `Goal` / `Instructions` / `Constraints` / `Application instructions` 分节，供模型消费。

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/75_persona_identity.py)

### 真实场景例子：限定工具与 Skill 作用域

用限定名 glob 控制 Persona 能看到哪些 Tools：

```python
"""Apply explicit tool and Skill scopes."""

from super_harness import Persona, tool


@tool(namespace="repo")
def inspect(path: str) -> str:
    """Inspect one repository path."""
    return path


persona = Persona(
    "Reviewer", "code reviewer", "Review safely", tool_scopes=("repo.*",), skill_scopes=("code-*",)
)
print([item.qualified_name for item in persona.select_tools((inspect,))], persona.skill_scopes)
```

`select_tools` 只保留 `qualified_name` 命中任一 `tool_scopes` glob 的 Tool（此处 `repo.inspect` 命中 `repo.*`）。

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/76_persona_scopes.py)

### 进阶例子：具名子代理角色模板与 Agent 集成

Persona 可容纳具名子代理角色模板，并在交给 `Agent(..., persona=...)` 时生效：

```python
"""Select a named subagent persona template."""

from super_harness import Persona

tester = Persona("Tester", "test specialist", "Verify acceptance criteria")
lead = Persona("Lead", "delivery lead", "Ship safely", subagent_roles={"tester": tester})
print(lead.subagent("tester").metadata())
```

`lead.subagent("tester")` 返回模板 Persona；`metadata()` 返回非机密快照（`persona`、`role`、`memory_scope`、`skill_scopes`）。

与 `Agent` 集成时，把 Persona 作为关键字参数传入：

```python
from super_harness import Agent, DeepSeekProvider, Persona

persona = Persona("Ari", "release reviewer", "Find release blockers")
agent = Agent(DeepSeekProvider(), persona=persona)
print(agent.name, agent.role, agent.memory_scope)
```

`Agent` 会用 `persona.select_tools` 过滤 Tools、用 `persona.compose_instructions` 组装指令，并把 `persona.metadata()` 写入新 Thread 的元数据。

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/77_persona_subagent_roles.py)

### API 用法速查

```python
Persona(name, role, goal, instructions="", constraints=(), model_override=None,
        tool_scopes=("*",), skill_scopes=("*",), memory_scope="thread",
        subagent_roles={})
persona.compose_instructions(additional=None) -> str
persona.validate_provider(provider)          # 校验 model_override 与 provider.model
persona.select_tools(tools) -> tuple[Tool, ...]
persona.subagent(role) -> Persona            # 未知角色抛 KeyError
persona.metadata() -> dict                   # {"persona","role","memory_scope","skill_scopes"}
Agent(..., persona=persona)
```

### 错误 / 校验

- `ValueError("persona name is invalid")`——`name` 不合法。
- `ValueError("persona role and goal are required")`——`role` 或 `goal` 为空。
- `ValueError("persona memory_scope is invalid")`——`memory_scope` 不在四选一内。
- `ValueError("persona scopes may not be empty")`——任一作用域条目为空串。
- `ValueError("persona may not contain itself as a named subagent role")`——自我引用。
- `Agent` 构造时若 `model_override` 与提供商实际模型不符，`validate_provider` 抛 `ValueError`。

### 安全注意事项

- Persona 指令属于**开发者权威**，可覆盖默认指令，因此只应来自可信来源。
- `persona.metadata()` 只暴露非机密字段；不要把人设文件放入机密信息。

### 故障排查

- 模型不匹配：确认 `model_override` 与提供商配置的模型名一致。
- 工具不可见：检查 `tool_scopes` glob 是否覆盖了目标 Tool 的 `qualified_name`（如 `repo.*` 与 `repo.inspect`）。

---

## 2. AGENTS.md

### 这是什么 / 何时使用

`AGENTS.md` 是项目指令文件，由 `AgentsMdLoader` 在**最近的仓库根目录到当前工作目录**之间逐层发现并注入上下文。它把「项目该怎么做」沉淀成文件，随代码库一起版本化。

典型场景：仓库根放通用的 `AGENTS.md`，子目录放更局部的 `AGENTS.override.md`，各层指令按层级顺序进入上下文。

### 前置条件

- 项目目录位于某个带 `.git` 标记（默认 `root_markers=(".git",)`）的仓库内。
- 目录中放置 `AGENTS.md` 或 `AGENTS.override.md` 文件。

### 快速开始

```python
from super_harness import AgentsMdLoader

fragments = AgentsMdLoader().load(".")
for fragment in fragments:
    print(fragment.content)
```

把 `cwd=...` 传给 `Agent` 时，加载器会自动运行：

```python
from super_harness import Agent, DeepSeekProvider

thread = Agent(DeepSeekProvider(), cwd=".").thread()
print(thread.debug_context())
```

### 配置（发现规则）

`AgentsMdLoader` 的可配置字段：

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `root_markers` | `tuple[str, ...]` | `(".git",)` | 判定仓库根的文件标记 |
| `max_bytes` | `int` | `32_768` | 所有片段合计的字节上限（32 KiB） |
| `filenames` | `tuple[str, ...]` | `("AGENTS.override.md", "AGENTS.md")` | 每个目录按此顺序查找 |

发现规则：

1. `project_root(cwd)` 从 `cwd` 逐级向上，返回第一个含 `.git` 标记的目录；找不到则返回 `cwd`。
2. 从根目录到 `cwd` 的每一层目录，先查 `AGENTS.override.md`、再查 `AGENTS.md`，每层只取先命中的那个。
3. **绝不越过仓库根向上查找**（仓库边界即停止）。
4. 总内容不超过 `max_bytes`；超出的部分被截断。
5. 每个片段是 `ContextFragment(ContextKind.PROJECT, content, path, USER, metadata={"path": ...})`，属于**用户角色**的外部数据，不能覆盖开发者或项目指令。

### 基础例子：`AGENTS.override.md` 优先于 `AGENTS.md`

同一目录下，`AGENTS.override.md` 覆盖 `AGENTS.md`：

```python
"""Prefer AGENTS.override.md over AGENTS.md in the same directory."""

import tempfile
from pathlib import Path

from super_harness import AgentsMdLoader

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    (root / ".git").mkdir()
    (root / "AGENTS.md").write_text("ordinary", encoding="utf-8")
    (root / "AGENTS.override.md").write_text("override", encoding="utf-8")
    print([fragment.content for fragment in AgentsMdLoader().load(root)])
```

输出只有 `override`，因为同目录优先读 `AGENTS.override.md`。

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/90_agents_override_precedence.py)

### 真实场景例子：仓库边界（不越界向上）

发现过程在最近的仓库根处停止，绝不读取外层目录的 `AGENTS.md`：

```python
"""Stop AGENTS.md discovery at the nearest repository boundary."""

import tempfile
from pathlib import Path

from super_harness import AgentsMdLoader

with tempfile.TemporaryDirectory() as directory:
    outer = Path(directory)
    (outer / "AGENTS.md").write_text("outside", encoding="utf-8")
    repo = outer / "repo"
    child = repo / "src"
    child.mkdir(parents=True)
    (repo / ".git").mkdir()
    (repo / "AGENTS.md").write_text("inside", encoding="utf-8")
    print([fragment.content for fragment in AgentsMdLoader().load(child)])
```

`load(child)` 的根是 `repo`（含 `.git`），因此只读到 `inside`，`outside` 被排除。

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/91_agents_repository_boundary.py)

### 进阶例子：嵌套层级与脱敏上下文检查

根目录与子目录各放一份指令，并通过 `thread.debug_context()` 查看带优先级与来源的脱敏快照：

```python
"""Discover hierarchical AGENTS.md and inspect redacted context."""

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

`debug_context()` 返回脱敏快照；敏感值（如 `api_key=...`）会被脱敏处理。

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/08_agents_context_debug/main.py)

### API 用法速查

```python
AgentsMdLoader(root_markers=(".git",), max_bytes=32768,
               filenames=("AGENTS.override.md", "AGENTS.md"))
loader.project_root(cwd) -> Path
loader.discover(cwd) -> tuple[Path, ...]      # 命中的文件路径，从根到 cwd
loader.load(cwd) -> tuple[ContextFragment, ...]
Agent(..., cwd=...)                            # Agent 自动注入 AGENTS.md 片段
thread.debug_context() -> ContextDebugSnapshot  # 脱敏快照
```

### 错误 / 限制

- `ValueError("AGENTS.md cwd must be a directory")`——`cwd` 不是目录。
- 上限 32 KiB：超出部分被截断；如需更大预算可自行构造 `AgentsMdLoader(max_bytes=...)` 并手动装配片段。
- `AGENTS.md` 片段是用户角色数据，不能覆盖开发者/项目指令。

### 故障排查

- 指令没生效：确认目录在 `.git` 标记的仓库内，且文件名是 `AGENTS.md` 或 `AGENTS.override.md`。
- 读到外层目录的指令：检查是否缺少仓库根标记（`.git`），边界会在此停止。
- 想同时保留同名覆盖与基础文件：注意每层目录只取一个（`AGENTS.override.md` 优先）。

---

## 3. Agent Skills

### 这是什么 / 何时使用

Skill 是**标准的 `SKILL.md` 包**：一个目录，含 YAML frontmatter（`name`、`description`）加正文指令，可选附带的引用/模板/脚本资源。Super Harness 通过 `SkillCatalog` 做**元数据优先的渐进式加载**，用 `SkillInstaller` 从本地或 Git/GitHub 安装。

当需要给 Agent 注入可复用、按需激活的领域知识或工作流（代码评审清单、发布脚本、文档规范等）时使用 Skill。

### 前置条件

- 项目中存在 `.agents/skills/` 或 `.super-harness/skills/` 目录（或提供 `explicit` 路径）。
- 每个 Skill 目录内含 `SKILL.md`。

### 快速开始

```python
from super_harness import SkillCatalog

catalog = SkillCatalog.discover(cwd=".")
skill = catalog.activate("code-review")
print(skill.instructions)
```

### 配置（发现与作用域）

`SkillCatalog.discover(...)` 按以下 root 顺序合并（同名冲突时后发现的被记入 `collisions`）：

| 来源 | 路径 | source 标记 |
| --- | --- | --- |
| `explicit` | 调用方显式传入的路径 | `explicit` |
| 项目（`.agents`） | `<project>/.agents/skills` | `project-agents` |
| 项目（`.super-harness`） | `<project>/.super-harness/skills` | `project-super-harness` |
| 用户 | `~/.super-harness/skills`（或 `user_root`） | `user` |
| 插件 | `plugin_roots` 提供的路径 | `plugin` |
| 系统 | `system_roots` 提供的路径 | `system` |

发现阶段只解析并缓存 `name` 与 `description`（元数据）；**激活**选中的 Skill 后才读取其指令正文，支持文件（`references/`、`templates/`、`scripts/`）在显式请求前保持未加载。

### `SKILL.md` 结构

```markdown
---
name: code-review
description: Run a checklist-based code review and report blockers.
---

Review the provided diff and report:
1. Blocking issues (correctness, security, credentials).
2. Suggested improvements.
3. A concise verdict.
```

解析规则（`parse_skill`）：

- `SKILL.md` 必须以 `---` 开头并有闭合的 YAML frontmatter。
- `name` 取自 frontmatter 或目录名，须匹配 `[a-z0-9]+(?:-[a-z0-9]+)*`，且不超过 64 字符。
- `description` 必填，非空白。
- frontmatter 中其余键进入 `extra` 原样保留。
- 激活后，正文（frontmatter 之后的部分）即 `instructions`，不可为空。

### 基础例子：发现并列出 Skill

```python
from super_harness import SkillCatalog

catalog = SkillCatalog.discover(cwd=".")
for skill in catalog.list():
    print(skill.name, skill.description, skill.source)
```

`list()` 返回元数据（`SkillMetadata`），只加载名称/描述，不读取正文。

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/25_skill_discovery.py)

### 真实场景例子：激活并读取指令与支持文件

```python
from super_harness import SkillCatalog

catalog = SkillCatalog.discover(cwd=".")
skill = catalog.activate("code-review")
print(skill.instructions)
# Supporting files stay unloaded until explicitly requested:
# print(skill.read_resource("references/checklist.md").decode())
```

`activate(name)` 返回 `ActivatedSkill`，其 `read_resource(relative_path)` 按需读取包内资源（限定在 Skill 目录内，防止路径逃逸）。

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/26_skill_activation.py)

### 进阶例子：从本地路径安装 Skill

`SkillInstaller` 安装到指定目标目录，并写入出处元数据：

```python
from super_harness import SkillInstaller

installer = SkillInstaller(".super-harness/skills")
installed = installer.install("./my-skill")
print(installed.name, installed.path)
```

`install(source)` 接受三种来源：

- **本地路径**（如 `./my-skill`）。
- **HTTPS Git 仓库**（`https://...` 或 `git+https://...`）。
- **GitHub `/tree/<revision>/<subdir>` URL**：从仓库指定分支/标签/提交的指定子目录安装（例如 `https://github.com/owner/repo/tree/main/skills/code-review`）。

安装时写入 `.super-harness-source.json`（`source_type`、`location`、`revision`、`installed_at`）。安装器**绝不覆盖**已存在的 Skill、拒绝符号链接与路径逃逸，并记录解析后的提交。另有 `info` / `list` / `update` / `remove` 方法。

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/27_skill_install.py)

### 写一个 Skill（推荐结构）

```
my-skill/
├── SKILL.md
└── references/
    └── checklist.md
```

- `SKILL.md` 的 frontmatter 至少含 `name` 与 `description`。
- 正文写触发条件、编号步骤、注意事项与验证步骤（尽量简洁、可执行）。
- 长内容放 `references/`、`templates/`、`scripts/`，通过 `ActivatedSkill.read_resource` 按需读取。
- 命名用小写连字符（如 `code-review`）。

### API 用法速查

```python
SkillCatalog.discover(cwd=None, explicit=(), user_root=None,
                      plugin_roots=(), system_roots=()) -> SkillCatalog
catalog.list() -> tuple[SkillMetadata, ...]
catalog.get(name) -> SkillMetadata
catalog.activate(name) -> ActivatedSkill     # 读取正文指令
activated.read_resource(relative_path) -> bytes
parse_skill(path, *, source="runtime") -> SkillMetadata
activate_skill(metadata) -> ActivatedSkill
SkillInstaller(destination)                   # 见 install/info/list/update/remove
installer.install(source) -> SkillMetadata
```

### 错误 / 故障排查

- `SkillError("SKILL.md is missing YAML frontmatter")`——缺 frontmatter。
- `SkillError("skill name must contain lowercase letters, numbers, and hyphens")`——命名不规范。
- `SkillError("skill description is required")`——缺描述。
- `SkillError("skill ... is already installed")`——目标已存在，安装器不覆盖。
- `SkillError("skill packages may not contain symbolic links")` / `"... escapes installation root"`——安全校验。
- `SkillError("unknown skill ...")`——`activate` 了一个未发现的 Skill，先确认 `discover` 的 root 覆盖了它。

---

## 4. MCP（Model Context Protocol）

### 这是什么 / 何时使用

MCP 让 Agent 通过标准协议连接外部服务器，暴露 Tools、Resources 与 Prompts。Super Harness 通过 `MCPClient` 适配**官方 Python SDK**，支持两种一等传输：**stdio**（本地子进程）与 **Streamable HTTP**（远程 URL）。

当需要把外部能力（文件系统、数据库、远程 API）作为 Agent 可调用的工具接入，或复用已有的 `mcpServers` 配置时使用 MCP。

### 前置条件

- 安装了官方 MCP SDK（`mcp` 包）。
- 目标是本地的可执行服务器（stdio）或可访问的 HTTP 端点（Streamable HTTP）。

### 快速开始

```python
import asyncio

from super_harness import MCPClient, MCPServerConfig, MCPTransport


async def main() -> None:
    config = MCPServerConfig("remote", MCPTransport.STREAMABLE_HTTP, url="http://127.0.0.1:8000/mcp")
    async with MCPClient(config) as client:
        print(client.protocol_version, await client.list_tools())


asyncio.run(main())
```

### 配置

`MCPTransport` 枚举：`STDIO = "stdio"`、`STREAMABLE_HTTP = "streamable_http"`。

`MCPServerConfig` 字段：

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `name` | `str` | （必填） | 服务器名（非空） |
| `transport` | `MCPTransport` | （必填） | 传输类型 |
| `command` | `str \| None` | `None` | stdio 可执行命令（必填） |
| `args` | `tuple[str, ...]` | `()` | stdio 参数 |
| `env` | `Mapping[str, str]` | `{}` | 子进程环境变量 |
| `cwd` | `Path \| None` | `None` | 子进程工作目录 |
| `url` | `str \| None` | `None` | HTTP 端点（必填） |
| `headers` | `Mapping[str, str]` | `{}` | HTTP 请求头 |
| `timeout` | `float` | `30.0` | 每操作超时（须为正） |
| `enabled` | `bool` | `True` | 禁用则不连接 |
| `include_tools` | `tuple[str, ...]` | `()` | 允许名单（空=全部） |
| `exclude_tools` | `tuple[str, ...]` | `()` | 拒绝名单 |

校验：`name` 非空且 `timeout > 0`；stdio 必须有 `command`；HTTP 必须有 `url`。`MCPClient` 必须作为**异步上下文管理器**使用。

### 基础例子：stdio 列出 Tools

```python
import asyncio

from super_harness import MCPClient, MCPServerConfig, MCPTransport


async def main() -> None:
    config = MCPServerConfig("demo", MCPTransport.STDIO, command="python", args=("server.py",))
    async with MCPClient(config) as client:
        print([tool.name for tool in await client.list_tools()])


asyncio.run(main())
```

stdio 模式启动一个子进程（`python server.py`）并与之通信。

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/28_mcp_stdio_list.py)

### 真实场景例子：stdio 调用工具 + 读取资源

调用远端工具：

```python
import asyncio

from super_harness import MCPClient, MCPServerConfig, MCPTransport


async def main() -> None:
    config = MCPServerConfig("math", MCPTransport.STDIO, command="python", args=("server.py",))
    async with MCPClient(config) as client:
        print(await client.call_tool("add", {"left": 20, "right": 22}))


asyncio.run(main())
```

读取资源（`list_resources` / `read_resource`）：

```python
import asyncio

from super_harness import MCPClient, MCPServerConfig, MCPTransport


async def main() -> None:
    config = MCPServerConfig("notes", MCPTransport.STDIO, command="python", args=("server.py",))
    async with MCPClient(config) as client:
        print(await client.list_resources())
        print(await client.read_resource("note://release"))


asyncio.run(main())
```

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/29_mcp_stdio_call.py) · [资源示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/30_mcp_stdio_resources.py)

### 进阶例子：Streamable HTTP 调用与 Prompts

远程 HTTP 服务器调用工具：

```python
import asyncio

from super_harness import MCPClient, MCPServerConfig, MCPTransport


async def main() -> None:
    config = MCPServerConfig("remote", MCPTransport.STREAMABLE_HTTP, url="http://127.0.0.1:8000/mcp")
    async with MCPClient(config) as client:
        print(await client.call_tool("add", {"left": 2, "right": 3}))


asyncio.run(main())
```

列出并获取 Prompts：

```python
import asyncio

from super_harness import MCPClient, MCPServerConfig, MCPTransport


async def main() -> None:
    config = MCPServerConfig("remote", MCPTransport.STREAMABLE_HTTP, url="http://127.0.0.1:8000/mcp")
    async with MCPClient(config) as client:
        print(await client.list_prompts())
        print(await client.get_prompt("summarize", {"topic": "MCP"}))


asyncio.run(main())
```

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/32_mcp_http_call.py) · [HTTP 列表](https://github.com/Sitozzmonash/superharness/blob/main/examples/31_mcp_http_list.py) · [Prompts 示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/33_mcp_http_prompts.py)

### 导入已有 `mcpServers` 配置

`import_mcp_servers` 接受常见的 `{ "mcpServers": ... }` JSON（文件路径或 Mapping），转换为 `MCPServerConfig` 元组：

```python
from super_harness import import_mcp_servers

configs = import_mcp_servers("mcp.json")
for config in configs:
    print(config.name, config.transport)
```

支持 `url`（→ Streamable HTTP）与 `command`/`args`（→ stdio），以及 `env`、`headers`、`cwd`、`timeout`、`disabled`、`includeTools`、`excludeTools`。CLI 侧用 `MCPConfigStore` 持久化这些配置（`super-harness mcp add/import/...`）。

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/34_mcp_config_import.py)

### 安装 MCP Bundle（`.mcpb`）

`.mcpb` 是便携的本地服务器打包格式。先用 `inspect_mcpb` 校验（SHA-256、归档安全、manifest 必需字段），再用 `install_mcpb` 安装：

```python
from super_harness import install_mcpb

bundle = install_mcpb("server.mcpb", ".super-harness/mcp", expected_sha256="EXPECTED_SHA256")
print(bundle.name, bundle.config.command, bundle.config.args)
```

校验项包括：SHA-256 完整性、无重复归档路径、`manifest.json` 必需、文件数 ≤ 10,000、解压总量 ≤ 256 MiB、无绝对路径/`..` 逃逸/符号链接、`name` 文件系统安全、服务器入口点（`uv`/`python`）或显式 `mcp_config` 命令。安装后 `command`/`args`/`env` 中的 `${__dirname}` 被解析为实际安装目录。

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/35_mcpb_install.py)

### MCP Registry（官方注册表）

`OfficialMCPRegistry` 访问官方注册表预览端点：

```python
import asyncio

from super_harness import OfficialMCPRegistry


async def main() -> None:
    for server in await OfficialMCPRegistry().search("filesystem", limit=5):
        print(server)


asyncio.run(main())
```

`search(query, limit)` 与 `get(name, version)` 走 `/v0.1/servers` 端点。**注册表发现并不等于信任或自动安装**——仍需自行安装与审查。

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/36_mcp_registry.py)

### MCP 2026 兼容说明

- 目标协议修订为 **`2026-07-28`**（由官方/Tier-1 SDK 支持时），同时为代表性 2025 时代的服务器保留务实兼容。
- 一等传输是 stdio 与 Streamable HTTP；**不要在 Agent 核心假设遗留的传输级会话**。
- 协议协商由官方 SDK 完成（`MCPClient` 暴露 `protocol_version` 与 `capabilities`）。
- MCPB 是受支持的便携本地服务器打包路径；官方注册表为可选运行时能力且隔离（注册表仍属预览）。

### API 用法速查

```python
MCPServerConfig(name, transport, command=None, args=(), env={}, cwd=None,
                url=None, headers={}, timeout=30.0, enabled=True,
                include_tools=(), exclude_tools=())
async with MCPClient(config, observer=None) as client: ...
client.protocol_version / client.capabilities
await client.list_tools() / call_tool(name, arguments=None)
await client.list_resources() / read_resource(uri)
await client.list_prompts() / get_prompt(name, arguments=None)
await client.as_tools() -> tuple[Tool, ...]     # 命名为 config.name，source="mcp"，risk="external"
import_mcp_servers(value) -> tuple[MCPServerConfig, ...]
inspect_mcpb(path, expected_sha256=None) -> MCPBundle
install_mcpb(path, destination, expected_sha256=None) -> MCPBundle
OfficialMCPRegistry(base_url=..., timeout=20.0, client=None).search/get
```

### 事件

`MCPClient` 通过可选的 `observer` 发出事件：

- `mcp.connected`——连接成功，含 `server`、`transport`、`protocol_version`。
- `mcp.call.started` / `mcp.call.completed` / `mcp.call.failed`——每个操作的开始/完成/失败，含 `operation`、`operation_id`、`duration_ms`、`error_class`。

### 错误 / 超时 / 重试

- 连接失败：`MCPError("MCP server ... connection failed")`。
- 禁用服务器：`MCPError("MCP server ... is disabled")`（`enabled=False`）。
- 过滤命中：`call_tool` 对不在允许名单/在拒绝名单的工具抛 `MCPError("MCP tool ... is disabled by filter")`。
- 超时：每个操作受 `config.timeout` 约束，超时抛 `MCPError("MCP <op> timed out")`；其他失败为 `MCPError("MCP <op> failed")`。
- 目录分页上限 20 页 / 1,000 项，超限抛 `MCPError`。

### 与其他功能组合

`await client.as_tools()` 把远程工具转成 `Tool` 值（`namespace=config.name`、`source="mcp"`、`risk="external"`），可直接交给 `Agent(tools=...)` 或 `ToolRegistry`。远程工具照常经过工具抽象、审批与超时。

### 安全注意事项

- 将远程工具与资源视为**不可信的外部输入**。
- 用 `include_tools`/`exclude_tools` 限制暴露面。
- 配置有限的 `timeout`；对 HTTP 使用 HTTPS 与受控的请求头。
- 让外部 MCP 工具保持位于允许名单、审批、有限超时与 HTTPS 凭据之后。
- 安装 `.mcpb` 时校验 `expected_sha256`。

### 故障排查

- `ValueError("stdio MCP requires command")` / `ValueError("Streamable HTTP MCP requires url")`——配置与传输不匹配。
- 连接失败：确认服务器可执行/端点可达、`mcp` SDK 已安装。
- 工具不出现：检查 `include_tools`/`exclude_tools` 过滤。
- CLI 里配置：`super-harness mcp add <name> --stdio -- python server.py`、`super-harness mcp add <name> --url <url>`、`super-harness mcp import ./mcp.json`、`super-harness mcp add ./server.mcpb --sha256 <digest>`、`super-harness mcp search <query>`、`super-harness mcp list/inspect/remove <name>`。

---

## 5. 插件（Plugins）

### 这是什么 / 何时使用

插件把多种能力捆绑成一个**可安装、可显式启用**的单元：Skills、命名空间化的 Tools、MCP 定义、Hooks、资产、人设与命令。插件**安装时只涉及数据**，在被显式 `enable` 之前始终保持禁用；`enable` 是信任边界，此时才会执行声明的 `./file.py:symbol` 条目。

当需要把一组相关能力（如一套发布工具 + 对应 Skills + 钩子）打包分发、并在应用层显式开启时使用插件。

### 前置条件

- 插件源是含清单的目录：`.super-harness/plugin.toml`（Super Harness 原生）或 `.codex-plugin/plugin.json`（Codex 兼容，尽力导入）。

### 快速开始

```python
from super_harness import HookRegistry, PluginInstaller, PluginManager, ToolRegistry

tools = ToolRegistry()
hooks = HookRegistry()
manager = PluginManager(
    PluginInstaller(".super-harness/plugins"), tools=tools, hooks=hooks
)
capabilities = manager.enable("release-tools")
print(capabilities.skills, capabilities.tools, capabilities.mcp_servers, capabilities.hooks)
```

### 配置（`plugin.toml`）

`load_plugin` 读取 `.super-harness/plugin.toml`；结构为 `[plugin]`、`[capabilities]`、`[[hooks]]`：

```toml
[plugin]
name = "release-tools"
version = "0.1.0"
description = "Release tooling bundle"
requires_super_harness = ">=0.1.0"

[capabilities]
skills = ["./skills"]
tools = ["./tools.py:release_tools"]
mcp = "./mcp.json"
assets = ["./assets/"]
personas = ["./personas/"]
commands = ["./commands/"]

[[hooks]]
event = "pre_tool_use"
entry = "./hooks.py:guard_release"
name = "guard-release"
priority = 100
timeout = 10.0
failure_policy = "warn"
allow_modify = false
```

规则：

- 每个相对能力路径（如 `./tools.py:release_tools`、`./skills`）必须以 `./` 开头，且保持在插件根目录之内；禁止 `..` 逃逸。
- 工具条目格式为 `./file.py:symbol`，`.py` 结尾，符号在启用时导入。
- `requires_super_harness` 用 PEP 440 约束校验当前包版本。
- 未知字段记入 `warnings`（不阻断）。
- 清单校验**不导入**插件的 Python；只有 `enable` 才导入声明条目。

### 基础例子：安装插件

```python
from super_harness import PluginInstaller

installer = PluginInstaller(".super-harness/plugins")
installed = installer.install("./plugins/release-tools")
print(installed.manifest.name, installed.manifest.version, installed.source)
```

`install(source)` 接受本地目录或 HTTPS Git/GitHub 源（含 `/tree/<rev>/<subdir>`），写入 `.super-harness-source.json`，拒绝符号链接与路径逃逸。返回 `InstalledPlugin`（此时 `enabled=False`）。

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/37_plugin_install.py)

### 真实场景例子：启用并查看能力

`PluginManager.enable(name)` 加载 Tools、MCP、Hooks 并把它们注册到传入的注册表：

```python
from super_harness import HookRegistry, PluginInstaller, PluginManager, ToolRegistry

tools = ToolRegistry()
hooks = HookRegistry()
manager = PluginManager(
    PluginInstaller(".super-harness/plugins"), tools=tools, hooks=hooks
)
capabilities = manager.enable("release-tools")
print(capabilities.skills, capabilities.tools, capabilities.mcp_servers, capabilities.hooks)
```

`PluginCapabilities` 返回 `plugin`、`skills`、`tools`、`mcp_servers`、`hooks`、`assets`、`personas`、`commands`。插件 Tools 会被命名空间化为 `manifest.name`，MCP 服务器命名为 `<plugin>.<server>`，Hook 注册带 `source="plugin:<name>"`。启用失败会回滚已注册的 Tools/Hooks。

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/38_plugin_capabilities.py)

### 进阶例子：生命周期管理

```python
from super_harness import PluginInstaller, PluginManager

manager = PluginManager(PluginInstaller(".super-harness/plugins"))
for installed in manager.list():
    print(installed.manifest.name, installed.enabled, installed.source)
manager.update("release-tools")  # disabled plugins only
manager.remove("release-tools")
```

`update` 与 `remove` **仅对已禁用的插件**可用（启用中抛 `PluginError`）；`list` 显示启用状态与来源元数据。

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/39_plugin_lifecycle.py)

### 插件携带 Hooks

启用插件时其声明 Hooks 被注册：

```python
from super_harness import HookRegistry, PluginInstaller, PluginManager

hooks = HookRegistry()
manager = PluginManager(PluginInstaller(".super-harness/plugins"), hooks=hooks)
capabilities = manager.enable("release-tools")
print("registered plugin hooks:", capabilities.hooks)
```

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/42_plugin_hook.py)

### 写一个插件

```
plugins/release-tools/
├── .super-harness/
│   └── plugin.toml
├── skills/            # 可选 Skill 包目录
├── tools.py           # 导出 Tool 值或可迭代 Tool
├── hooks.py           # 导出 hook 处理器
└── assets/            # 被动资产
```

`tools.py` 导出 `Tool` 值或 `Tool` 的可迭代对象；`hooks.py` 导出被 `[[hooks]]` 引用的可调用对象。所有相对路径以 `./` 开头并留在插件根内。

### Codex 插件导入

`load_plugin` 也读取 `.codex-plugin/plugin.json`：`skills`（字符串或数组）、`mcpServers`（路径或内联对象或 `.mcp.json`）、`hooks`/`commands`/`assets`/`agents`（元数据）。Codex 的 command/MCP hooks 与 apps/interface **只作元数据保留，不会被自动执行**，并产生 `warnings`。

### API 用法速查

```python
PluginInstaller(destination)                  # install/update/remove/list/info
PluginManager(installer, tools=None, hooks=None, trace_sink=None)
manager.install(source) -> InstalledPlugin
manager.enable(name) -> PluginCapabilities    # 信任边界：导入 ./file.py:symbol
manager.disable(name)
manager.update(name) / manager.remove(name)   # 仅禁用插件
manager.list() / manager.info(name) / manager.capabilities()
load_plugin(path) -> PluginManifest
```

### 错误 / 故障排查

- `PluginError("plugin ... is already enabled")`——重复启用。
- `PluginError("disable a plugin before updating/removing it")`——先禁用再更新/移除。
- `PluginError("plugin tool entry ... does not export Tool values")` / `"plugin entry module ... does not exist"` / `"plugin entry symbol ... does not exist"`——清单条目指向错误。
- `PluginError("plugin requires an incompatible Super Harness version")`——`requires_super_harness` 不满足。
- `PluginError("plugin packages may not contain symbolic links")` / `"... escapes plugin root"`——安全校验。
- CLI：`super-harness plugin add <source>`、`plugin list/info/update/remove <name>`。

### 安全注意事项

- 插件安装**只涉及数据**；显式 `enable` 会在进程内导入并执行插件 Python，**必须只对可信且经审查的来源**进行。
- 所有能力路径限定在插件根内；符号链接被拒绝。
- 更新/移除前先禁用，避免半激活状态。

---

## 6. 钩子（Hooks）

### 这是什么 / 何时使用

Hook 在**会话、轮次、用户提示、模型前后、工具前后、压缩前后、子代理、错误**等生命周期点注册同步或异步回调，用于可观测性与应用策略。钩子是审批引擎与沙箱的补充，不取代它们。

### 前置条件

- 需要回调运行在异步循环中（`dispatch` 是异步的）。

### 快速开始

```python
import asyncio

from super_harness import HookContext, HookEvent, HookRegistry

hooks = HookRegistry()


def log_turn(context: HookContext) -> None:
    print(context.event, context.thread_id, context.turn_id)


hooks.register(HookEvent.TURN_END, log_turn)
asyncio.run(hooks.dispatch(HookContext(HookEvent.TURN_END, thread_id="thread-1")))
```

### 配置（事件与策略）

`HookEvent` 枚举：

| 事件 | 值 | 可否 deny |
| --- | --- | --- |
| `SESSION_START` / `SESSION_END` | `session_start` / `session_end` | 否 |
| `TURN_START` / `TURN_END` | `turn_start` / `turn_end` | 否 |
| `USER_PROMPT` | `user_prompt` | 是 |
| `BEFORE_MODEL` / `AFTER_MODEL` | `before_model` / `after_model` | 是（前）/ 否（后） |
| `PRE_TOOL_USE` / `POST_TOOL_USE` | `pre_tool_use` / `post_tool_use` | 是（前）/ 否（后） |
| `PRE_COMPACT` / `POST_COMPACT` | `pre_compact` / `post_compact` | 是（前）/ 否（后） |
| `SUBAGENT_START` / `SUBAGENT_END` | `subagent_start` / `subagent_end` | 否 |
| `ERROR` | `error` | 否 |

只有 `USER_PROMPT`、`BEFORE_MODEL`、`PRE_TOOL_USE`、`PRE_COMPACT` 这四类**执行前**事件可以返回 `HookResult.deny(...)`。

`HookFailurePolicy`：`WARN`（默认，发警告继续）、`FAIL_OPEN`（继续）、`FAIL_CLOSED`（抛 `HookError` 中断）。

`register` 参数：`event`、`handler`，以及 `name`、`source`、`priority`（越小越先）、`timeout`、`failure_policy`、`allow_modify`。

### 基础例子：日志钩子

```python
import asyncio

from super_harness import HookContext, HookEvent, HookRegistry

hooks = HookRegistry()


def log_turn(context: HookContext) -> None:
    print(context.event, context.thread_id, context.turn_id)


hooks.register(HookEvent.TURN_END, log_turn)
asyncio.run(hooks.dispatch(HookContext(HookEvent.TURN_END, thread_id="thread-1")))
```

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/40_hook_logging.py)

### 真实场景例子：执行前策略拒绝

在 `PRE_TOOL_USE` 拒绝破坏性工具：

```python
import asyncio
from types import SimpleNamespace

from super_harness import HookContext, HookEvent, HookRegistry, HookResult

hooks = HookRegistry()


def protect_delete(context: HookContext) -> HookResult | None:
    tool = context.data["tool"]
    if tool.name == "delete_all":
        return HookResult.deny("destructive tool blocked by application policy")
    return None


hooks.register(HookEvent.PRE_TOOL_USE, protect_delete)
outcome = asyncio.run(
    hooks.dispatch(HookContext(HookEvent.PRE_TOOL_USE, {"tool": SimpleNamespace(name="read")}))
)
print(outcome.denied, outcome.deny_reason)
```

处理器通过 `context.data["tool"]` 访问上下文；返回 `HookResult.deny(reason)` 拒绝，返回 `None` 放行。`dispatch` 返回 `HookOutcome`，含 `denied` 与 `deny_reason`。

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/41_hook_pre_tool_policy.py)

### 进阶例子：`enrich`、`FAIL_CLOSED` 与插件钩子

用 `HookResult.enrich(**updates)` 修改事件数据（仅当注册时 `allow_modify=True`）：

```python
import asyncio

from super_harness import HookContext, HookEvent, HookRegistry, HookResult

hooks = HookRegistry()


def stamp(context: HookContext) -> HookResult:
    return HookResult.enrich(origin="policy")  # requires allow_modify=True at registration


hooks.register(HookEvent.BEFORE_MODEL, stamp, allow_modify=True)
outcome = asyncio.run(hooks.dispatch(HookContext(HookEvent.BEFORE_MODEL)))
print(outcome.data)
```

要点：

- `allow_modify=False`（默认）时若处理器返回 `updates`，`dispatch` 抛 `HookError("hook ... is not allowed to modify this event")`。
- 对 `FAIL_CLOSED` 的钩子，任何异常都会升级为 `HookError("hook ... failed closed")`；`WARN` 只发 `RuntimeWarning`。
- 每个钩子有独立 `timeout`，超时按失败策略处理。
- 钩子也可以由插件提供（见第 5 节 `42_plugin_hook.py`）。

[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/41_hook_pre_tool_policy.py)

### API 用法速查

```python
HookRegistry(trace_sink=None)
hooks.register(event, handler, *, name=None, source="runtime", priority=100,
               timeout=10.0, failure_policy=WARN, allow_modify=False) -> HookRegistration
hooks.unregister(event, name, *, source="runtime")
hooks.list(event=None) -> tuple[HookRegistration, ...]
await hooks.dispatch(context) -> HookOutcome
HookResult.enrich(**updates) / HookResult.deny(reason)
HookContext(event, data={}, thread_id=None, turn_id=None, source="runtime")
```

### 事件 / 追踪

`dispatch` 按 `(priority, source, name)` 排序执行；每次调用生成 `HookTrace`（`event`、`hook`、`source`、`success`、`duration_ms`、`denied`、`warning`），可经 `trace_sink` 收集。首个 `deny` 立即返回 `HookOutcome(denied=True, deny_reason=...)` 并停止后续钩子。

### 错误 / 故障排查

- `HookError("hook <source>:<name> is already registered")`——同名同源重复注册。
- `HookError("hook <name> is not allowed to modify this event")`——未开 `allow_modify` 却返回更新。
- `HookError("event <value> cannot be denied")`——在不可 deny 的事件上返回 `deny`。
- `HookError("hook <source>:<name> failed closed")`——`FAIL_CLOSED` 钩子抛错。
- 每个钩子务必设置**有限超时**；无限运行的钩子会阻塞 `dispatch`。

### 与其他功能组合

- 钩子是审批引擎/沙箱的**补充**，不取代它们。
- 插件可声明 Hooks（`[[hooks]]`），启用时注册到共享 `HookRegistry`。
- 用 `HookResult.enrich` 与 `allow_modify` 在进入模型前注入策略字段。

### 安全注意事项

- `allow_modify` 只在可信处理器上开启。
- 用 `FAIL_CLOSED` 表达「策略不可绕过」；`WARN`/`FAIL_OPEN` 表达「尽力而为」。
- 钩子能读到 `context.data`，不要在不可信回调中泄漏机密。

---

## 7. 组合用法（Combining）

把本部分各机制串起来：Persona 限定身份与工具、Skill 提供领域指令、MCP 暴露外部工具、Hook 施加应用策略、插件打包复用。

```python
import asyncio

from super_harness import (
    Agent,
    DeepSeekProvider,
    HookContext,
    HookEvent,
    HookRegistry,
    MCPClient,
    MCPServerConfig,
    MCPTransport,
    Persona,
    SkillCatalog,
    ToolRegistry,
)

async def main() -> None:
    persona = Persona("Ops", "release operator", "Ship safely", tool_scopes=("repo.*",))

    catalog = SkillCatalog.discover(cwd=".")
    if "code-review" in {s.name for s in catalog.list()}:
        skill = catalog.activate("code-review")
        print("skill instructions:", skill.instructions[:60], "...")

    hooks = HookRegistry()
    hooks.register(HookEvent.PRE_TOOL_USE, lambda ctx: None, name="noop")

    config = MCPServerConfig("remote", MCPTransport.STREAMABLE_HTTP, url="http://127.0.0.1:8000/mcp")
    async with MCPClient(config) as client:
        mcp_tools = await client.as_tools()

    registry = ToolRegistry()
    for tool in mcp_tools:
        registry.register(tool)

    agent = Agent(DeepSeekProvider(), persona=persona, tools=list(registry.list()))
    print("agent persona:", agent.name, agent.role)

asyncio.run(main())
```

> 注：`registry.list()` 返回 `Tool` 元组；`Agent(tools=...)` 接受 `Tool` 可迭代。生产环境请按需选择 MCP 服务器、审批策略与 Hook 的 `allow_modify`。

---

## 8. CLI 参考

```bash
# Skills
super-harness skill add ./my-skill
super-harness skill list
super-harness skill info <name>
super-harness skill update <name>
super-harness skill remove <name>

# MCP
super-harness mcp add <name> --stdio -- python server.py
super-harness mcp add <name> --url https://example.com/mcp
super-harness mcp add ./server.mcpb --sha256 <digest>
super-harness mcp import ./mcp.json
super-harness mcp list
super-harness mcp inspect <name>
super-harness mcp search <query> [--limit N] [--registry-url URL]
super-harness mcp remove <name>

# Plugins
super-harness plugin add <source>
super-harness plugin list
super-harness plugin info <name>
super-harness plugin update <name>
super-harness plugin remove <name>
```

- 默认作用于本地项目状态（`.super-harness`）；`--global` 切换到用户安装根目录。
- 插件管理**绝不激活 Python**（激活是 Python API 的显式信任边界）。
- 输出默认省略机密；加 `--json` 获得稳定的机器可读输出。

---

## 9. 安全注意事项汇总

- **Persona / AGENTS.md / Skill 指令**属于权威指令来源，只应来自可信来源。
- **MCP 远程工具与资源**是不可信外部输入：用 `include_tools`/`exclude_tools` 收窄、配置有限超时、使用 HTTPS、保持审批在中间。
- **`.mcpb`** 安装务必校验 `expected_sha256`。
- **插件 `enable` 是信任边界**：它在进程内导入并执行插件 Python，只对可信、经审查的来源启用；安装本身只涉及数据。
- **Hooks** 是补充，不取代审批引擎或沙箱；`allow_modify` 只对可信处理器开启；每个钩子设置有限超时。

---

## 10. 故障排查速查

| 现象 | 检查项 |
| --- | --- |
| Persona 模型不匹配 | `model_override` 与提供商模型名是否一致 |
| 工具不可见 | `tool_scopes` glob 是否覆盖 `qualified_name` |
| AGENTS.md 未注入 | 目录是否在 `.git` 仓库内、文件名是否正确 |
| Skill 激活失败 | `discover` 的 root 是否覆盖目标 Skill、frontmatter 是否合规 |
| MCP 连接失败 | `mcp` SDK 是否安装、端点是否可达、传输与配置是否匹配 |
| MCP 工具不出现 | `include_tools`/`exclude_tools` 过滤 |
| 插件无法更新/移除 | 是否先 `disable` |
| Hook 报 `not allowed to modify` | 注册时是否传 `allow_modify=True` |
| Hook 卡死 | 是否设置了有限 `timeout` |

---

## 11. 链接

**可运行示例**（本页全部示例）：

- Persona：`examples/75_persona_identity.py` · `76_persona_scopes.py` · `77_persona_subagent_roles.py`
- AGENTS.md：`examples/90_agents_override_precedence.py` · `91_agents_repository_boundary.py` · `08_agents_context_debug/main.py`
- Skills：`examples/25_skill_discovery.py` · `26_skill_activation.py` · `27_skill_install.py`
- MCP：`examples/28_mcp_stdio_list.py` · `29_mcp_stdio_call.py` · `30_mcp_stdio_resources.py` · `31_mcp_http_list.py` · `32_mcp_http_call.py` · `33_mcp_http_prompts.py` · `34_mcp_config_import.py` · `35_mcpb_install.py` · `36_mcp_registry.py`
- Plugins / Hooks：`examples/37_plugin_install.py` · `38_plugin_capabilities.py` · `39_plugin_lifecycle.py` · `40_hook_logging.py` · `41_hook_pre_tool_policy.py` · `42_plugin_hook.py`

**相关页面**：

- 用户指南其余部分：Part I–V（Agent、Thread、工具与审批、上下文与持久化、记忆与 RAG）、Part VII+（自主多 Agent 与工作流）。
- API 参考：`api-reference.md` · `generated-api.md`。
- 生态系统与兼容性：`ecosystem.md` · `compatibility.md`。
- 内部原理（不属本页范围）：`internals/` 下与扩展相关的页面。
