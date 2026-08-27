---
id: internals-extensions
title: 扩展机制（Internals 6）
sidebar_position: 6
description: Skills 发现/激活/安装器、MCP 客户端与传输、插件加载器、钩子生命周期与分发、失败模型与扩展点的内部实现。
---

# 扩展机制：Skills、MCP、插件与钩子

本文档对应 Super Harness 内部实现的第 6 部分：四种运行时扩展机制如何被发现、校验、激活与分发——Open Agent Skills（技能）、MCP（Model Context Protocol 客户端与生态）、插件（Plugin 能力包）与钩子（Hook 生命周期拦截器）。它回答"这些机制内部为什么这样设计、怎样工作"，不讲解操作教程。

真实实现位于：

- `src/super_harness/skills/` —— `models.py`（元数据与渐进式激活）、`catalog.py`（有序发现）、`installer.py`（校验安装）。
- `src/super_harness/mcp/` —— `client.py`（官方 SDK 适配）、`config.py`（类型化配置与 mcpServers JSON 导入）、`mcpb.py`（MCP Bundle 校验安装）、`registry.py`（可替换注册表协议）。
- `src/super_harness/plugins/` —— `models.py`（清单与能力值）、`loader.py`（清单解析）、`manager.py`（显式激活与冲突回滚）、`installer.py`（安装生命周期）。
- `src/super_harness/hooks/` —— `models.py`（钩子生命周期值）、`registry.py`（有序分发）。
- 相关的工具注册表面在 `src/super_harness/tools/`（`definition.py`、`registry.py`），异常层级在 `src/super_harness/exceptions.py`。

完整研究与 Codex 对照见 [`docs/research/codex/skills-and-mcp.md`](https://github.com/Sitozzmonash/superharness/blob/main/docs/research/codex/skills-and-mcp.md) 与 [`docs/research/codex/plugins-and-hooks.md`](https://github.com/Sitozzmonash/superharness/blob/main/docs/research/codex/plugins-and-hooks.md)。

## 1. 职责（Responsibilities）

四个子系统各承担一组边界清晰的职责：

- **`skills/` —— Skills 子系统**：
  - `models.py` 定义 `SkillMetadata`（仅 frontmatter 的轻量元数据）与 `ActivatedSkill`（元数据 + 指令主体），并提供 `parse_skill`（只解析 frontmatter）与 `activate_skill`（读取指令主体）、`read_resource`（资源读取被限定在 Skill 目录内）。
  - `catalog.py` 按固定优先顺序遍历显式、项目、用户、插件、系统根目录，构建目录时**只解析 frontmatter**，记录碰撞与解析错误。
  - `installer.py` 把本地目录或 HTTPS Git/GitHub 子目录**先暂存再校验后复制**到安装根目录，记录来源（provenance）并支持更新。
- **`mcp/` —— MCP 子系统**：
  - `client.py` 包装官方 MCP Python SDK 的 `Client`（`mcp.client.client.Client`），对 stdio 用 `StdioServerParameters`，对 Streamable HTTP 提供一个隔离的 `httpx2` 客户端；公共方法绑定分页、应用超时、保留取消、规范化错误，并把远端工具翻译为标准 `Tool` 表面。
  - `config.py` 定义 `MCPServerConfig` 与 `MCPTransport`，提供 `import_mcp_servers` 导入通用 `mcpServers` JSON。
  - `mcpb.py` 在解压前对 `.mcpb` 归档做 SHA-256、清单字段、路径、符号链接、文件数与展开大小校验。
  - `registry.py` 把官方注册表预览 API 放在精简可替换的 `MCPRegistry` 协议之后。
- **`plugins/` —— 插件子系统**：
  - `models.py` 定义 `PluginManifest`、`PluginHookSpec`、`PluginCapabilities`、`InstalledPlugin`、`PluginTrace`。
  - `loader.py` 解析 `.super-harness/plugin.toml` 或 `.codex-plugin/plugin.json`，校验路径/版本要求（**仅数据，不执行代码**）。
  - `manager.py` 的 `enable` **显式激活**：导入 Python 入口符号、命名空间化 Tools、以强制的 `plugin:<name>` 归属注册钩子、加载 MCP 配置，出现冲突则回滚较早的注册。
  - `installer.py` 负责安装/更新/移除的生命周期与来源记录。
- **`hooks/` —— 钩子子系统**：
  - `models.py` 定义 `HookEvent`（14 个生命周期事件）、`HookFailurePolicy`、`HookContext`、`HookResult`、`HookTrace`、`HookOutcome`。
  - `registry.py` 以 `(priority, source, name)` 顺序分发注册项，每个回调收到累积数据上的一个全新不可变上下文视图，异步与同步处理器共享同一条超时/取消路径。

在运行时中，这些机制交汇于 `Agent` / `Thread` / `ToolExecutor`：`ToolExecutor` 在审批后分发 `PRE_TOOL_USE` / `POST_TOOL_USE`；`Thread` 启动时分发 session/prompt/turn 钩子、每个模型步分发 before/after 钩子、异步压缩分发 pre/post；`PluginManager` 把激活的插件能力（Tools、钩子、MCP 配置、Skill 根）注入对应的注册表。

## 2. 数据模型（Data model）

### 2.1 Skills（`skills/models.py`）

```python
@dataclass(frozen=True, slots=True)
class SkillMetadata:
    name: str               # 校验 ^[a-z0-9]+(?:-[a-z0-9]+)*$，最长 64，description 必填
    description: str        # 空白折叠（" ".join(description.split())）
    path: Path              # 解析后的 SKILL.md 路径
    source: str = "runtime" # runtime / explicit / project-agents / project-super-harness / user / plugin / system / local / git / installed / pinned-codex
    extra: Mapping[str, Any] = field(default_factory=_extra)  # 冻结为 MappingProxyType（frontmatter 全量）

@dataclass(frozen=True, slots=True)
class ActivatedSkill:
    metadata: SkillMetadata
    instructions: str       # frontmatter 之后的主体（去除首尾空白），非空才有效
    def read_resource(self, relative_path: str) -> bytes: ...   # 被限定在 Skill 目录内

@dataclass(frozen=True, slots=True)
class SkillSource:
    source_type: str        # "local" / "git"
    location: str           # 原始来源
    revision: str | None    # git 解析到的 commit 哈希
    installed_at: str       # UTC ISO 时间戳
```

`SkillMetadata.__post_init__` 把 `extra` 冻结为 `MappingProxyType`。`parse_skill(path, *, source)` 若传入目录则定位 `SKILL.md`，解析 YAML frontmatter；第三方的**未加引号且含冒号的描述**会先经 `_repair_colon_scalars` 做一次窄兼容性修复（把形如 `key: a: b` 的标量用 `json.dumps` 加引号），再回退 `yaml.safe_load`。`ActivatedSkill.read_resource` 先把 `root = metadata.path.parent.resolve()`，再 `(root / relative_path).resolve()`，用 `path.relative_to(root)` 校验不越界，否则抛 `SkillError("skill resource escapes its directory")`；文件不存在抛 `SkillError`。

### 2.2 MCP（`mcp/config.py`、`mcp/mcpb.py`）

```python
class MCPTransport(StrEnum):
    STDIO = "stdio"
    STREAMABLE_HTTP = "streamable_http"

@dataclass(frozen=True, slots=True)
class MCPServerConfig:
    name: str
    transport: MCPTransport
    command: str | None = None          # STDIO 必填
    args: tuple[str, ...] = ()
    env: Mapping[str, str] = field(default_factory=_string_mapping)
    cwd: Path | None = None
    url: str | None = None              # STREAMABLE_HTTP 必填
    headers: Mapping[str, str] = field(default_factory=_string_mapping)
    timeout: float = 30.0               # 必须 > 0
    enabled: bool = True
    include_tools: tuple[str, ...] = () # 为空表示全包含
    exclude_tools: tuple[str, ...] = ()

@dataclass(frozen=True, slots=True)
class MCPBundle:
    name: str
    version: str
    manifest_version: str
    description: str
    config: MCPServerConfig
```

`MCPServerConfig.__post_init__` 校验 name 非空、timeout 为正、stdio 必须有 command、Streamable HTTP 必须有 url，并把 `env` / `headers` 冻结为 `MappingProxyType`。`import_mcp_servers(value)` 接受 `Mapping` 或 JSON 路径，读取 `mcpServers` 对象，逐个映射为 `MCPServerConfig`（含 `includeTools` / `excludeTools` / `disabled` / `timeout`），把 `cwd` 转为 `Path`。

### 2.3 插件（`plugins/models.py`）

```python
@dataclass(frozen=True, slots=True)
class PluginHookSpec:
    event: HookEvent
    entry: str                  # "./file.py:symbol"
    name: str | None = None
    priority: int = 100
    timeout: float = 10.0
    failure_policy: HookFailurePolicy = HookFailurePolicy.WARN
    allow_modify: bool = False

@dataclass(frozen=True, slots=True)
class PluginManifest:
    name: str
    version: str
    description: str
    root: Path
    format: str                 # "super-harness" / "codex"
    requires_super_harness: str = ""     # 如 ">=0.1.0,<1"
    skill_roots: tuple[Path, ...] = ()
    tool_entries: tuple[str, ...] = ()   # "./extension.py:TOOLS"
    mcp_path: Path | None = None
    inline_mcp: Mapping[str, Any] | None = None
    hook_specs: tuple[PluginHookSpec, ...] = ()
    assets: tuple[Path, ...] = ()
    personas: tuple[Path, ...] = ()
    commands: tuple[Path, ...] = ()
    config_schema: Path | None = None
    config_defaults: Path | None = None
    warnings: tuple[str, ...] = ()
    extra: Mapping[str, Any] = field(default_factory=_extra)

@dataclass(frozen=True, slots=True)
class PluginCapabilities:
    plugin: str
    skills: tuple[Path, ...] = ()
    tools: tuple[Tool, ...] = ()
    mcp_servers: tuple[MCPServerConfig, ...] = ()
    hooks: tuple[str, ...] = ()          # 钩子名
    assets: tuple[Path, ...] = ()
    personas: tuple[Path, ...] = ()
    commands: tuple[Path, ...] = ()

@dataclass(frozen=True, slots=True)
class InstalledPlugin:
    manifest: PluginManifest
    enabled: bool
    source: Mapping[str, Any]            # 来源记录，冻结

@dataclass(frozen=True, slots=True)
class PluginTrace:
    operation: str      # install / enable / disable / update / remove
    plugin: str
    success: bool
    capabilities: tuple[str, ...] = ()   # skills/tools/mcp/hooks 中激活的能力键
    warning: str | None = None
```

### 2.4 钩子（`hooks/models.py`）

```python
class HookEvent(StrEnum):
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    TURN_START = "turn_start"
    TURN_END = "turn_end"
    USER_PROMPT = "user_prompt"        # 可拒绝
    BEFORE_MODEL = "before_model"      # 可拒绝
    AFTER_MODEL = "after_model"
    PRE_TOOL_USE = "pre_tool_use"      # 可拒绝、可改写
    POST_TOOL_USE = "post_tool_use"
    PRE_COMPACT = "pre_compact"        # 可拒绝
    POST_COMPACT = "post_compact"
    SUBAGENT_START = "subagent_start"
    SUBAGENT_END = "subagent_end"
    ERROR = "error"

class HookFailurePolicy(StrEnum):
    FAIL_OPEN = "fail_open"
    FAIL_CLOSED = "fail_closed"
    WARN = "warn"

@dataclass(frozen=True, slots=True)
class HookContext:
    event: HookEvent
    data: Mapping[str, Any] = field(default_factory=_mapping)  # 冻结
    thread_id: str | None = None
    turn_id: str | None = None
    source: str = "runtime"

@dataclass(frozen=True, slots=True)
class HookResult:
    updates: Mapping[str, Any] = field(default_factory=_mapping)  # 冻结
    deny_reason: str | None = None      # 非空校验
    @classmethod
    def enrich(cls, **updates: Any) -> HookResult: ...
    @classmethod
    def deny(cls, reason: str) -> HookResult: ...

@dataclass(frozen=True, slots=True)
class HookTrace:
    event: HookEvent
    hook: str
    source: str
    success: bool
    duration_ms: float
    denied: bool = False
    warning: str | None = None

@dataclass(frozen=True, slots=True)
class HookOutcome:
    data: Mapping[str, Any]             # 累积数据（冻结）
    traces: tuple[HookTrace, ...] = ()
    denied: bool = False
    deny_reason: str | None = None
```

注册项本身（`hooks/registry.py`）也是不可变值：

```python
@dataclass(frozen=True, slots=True)
class HookRegistration:
    event: HookEvent
    handler: HookCallable
    name: str               # 注册时提供或回退 handler.__name__
    source: str = "runtime"
    priority: int = 100
    timeout: float = 10.0
    failure_policy: HookFailurePolicy = HookFailurePolicy.WARN
    allow_modify: bool = False
```

`HookRegistration.__post_init__` 校验 name 非空、timeout 为正。

## 3. 生命周期（Lifecycle）

### 3.1 Skill 发现：根目录遍历与优先顺序（`catalog.py`）

`SkillCatalog.discover` 按以下**优先顺序**构建根列表，先出现者优先级更高：

```text
1. explicit       显式传入的路径（命令行/调用方显式指定）
2. project-agents      cwd 所在项目根的 .agents/skills
3. project-super-harness 项目根的 .super-harness/skills
4. user                user_root 或 ~/.super-harness/skills
5. plugin              插件根（插件贡献的 skills）
6. system              系统根
```

`_project_root(cwd)` 从 cwd 向上遍历，第一个含 `.git` 的目录即为项目根；找不到则回退到 cwd 本身。对每个根：若 `root/SKILL.md` 是文件，则该根本身是单个 Skill 候选；否则以 `root.glob("*/SKILL.md")` 的父目录作为候选集（排序保证稳定）。每个候选调用 `parse_skill(candidate, source=source)`；解析失败的 `SkillError` 被收集进 `catalog.errors`；**名称已存在**的候选被记录进 `catalog.collisions[name]` 并**跳过**——先发现的（高优先级）保留。构建目录期间**从不读取指令主体**，只解析 frontmatter。

```text
discover(explicit=[...], cwd=..., user_root=..., plugin_roots=..., system_roots=...)
  │  组装 roots: [(source, Path), ...]（固定顺序）
  ▼
for source, root in roots:
  │  candidates = root/SKILL.md 是文件 ? [root] : sorted(glob("*/SKILL.md") 的父目录)
  ▼
for candidate in candidates:
  │  parse_skill(candidate, source=source)      # 只解析 frontmatter
  │    │ 失败 → catalog.errors.append(exc); continue
  │    ▼ 名称已存在 → catalog.collisions[name].append(path); continue
  ▼
  catalog.skills[name] = metadata                 # 首个（高优先级）胜出
```

`list()` 返回元组；`get(name)` 对未知名称抛 `SkillError`；`activate(name)` = `activate_skill(get(name))`，此时才读取指令主体，空指令抛 `SkillError("SKILL.md instructions are empty")`。

### 3.2 Skill 安装：暂存 → 校验 → 复制（`installer.py`）

`SkillInstaller.install(source)`：

- 本地来源：`Path(source).resolve()`，`parse_skill(path, source="local")`。
- 远程来源：要求 HTTPS（`https://` 或 `git+https://`，去掉 `git+` 前缀）。对 `github.com/.../tree/<rev>[/<subdir>]` 形态解析出修订与子目录，把 `repo_url` 规范为 `https://github.com<repo_path>.git`。

Git 流程在 `tempfile.TemporaryDirectory` 中进行：

```text
git clone --depth 1 <repo_url> <clone>
  ▼ 若请求了修订 revision
git -C <clone> fetch --depth 1 origin <revision>
git -C <clone> checkout --detach FETCH_HEAD
  ▼
skill_root = (clone / subdirectory).resolve()
  │  relative_to(clone.resolve()) 校验子目录不越出仓库
  ▼
parse_skill(skill_root, source="git")
  ▼ rev-parse HEAD 得到不可变 commit 哈希
  ▼ _copy(metadata, SkillSource("git", source, commit, _now()))
```

`_copy`：目标 `destination/name` 必须先 `relative_to(destination)`（名称不得越出安装根）；已存在则抛 `SkillError("already installed")`（**绝不静默覆盖**）；`rglob("*")` 中出现任一符号链接即拒绝（`SkillError("skill packages may not contain symbolic links")`）；`shutil.copytree(..., symlinks=True)` 复制；随后写入 `.super-harness-source.json`（来源记录），返回对已安装副本重新 `parse_skill` 的结果。

`update(name)` 是**可恢复的替换**：`info(name)` 取回来源 location，用 `SkillInstaller(staging_root)` 在隐藏暂存根安装新版本，校验更新后名称不变；然后把 `target.rename(backup)`、`staged.rename(target)`；任一步失败则 `backup.rename(target)` 回滚；成功后删除 backup 与 staging。

`remove(name)` 解析目标并校验越界后 `shutil.rmtree`。`list()` 遍历安装根下非隐藏目录并 `parse_skill(source="installed")`。`info(name)` 解析安装目录与 `.super-harness-source.json`，缺失/损坏抛 `SkillError`。

### 3.3 MCP 客户端连接与调用（`client.py`）

```text
async with MCPClient(config, observer=...) as client:
  │  __aenter__:
  │    若 config.enabled 为假 → MCPError("disabled")
  │    STDIO:      StdioServerParameters(command, args, env, cwd) → target
  │    HTTP:       httpx2.AsyncClient(headers, timeout, follow_redirects=False)
  │                → streamable_http_client(url, http_client=http) → target
  │    client = Client(target, read_timeout_seconds=config.timeout)
  │    发 mcp.connected 事件 (server, transport, protocol_version)
  ▼
client.list_tools() / call_tool() / list_resources() / read_resource()
client.list_prompts() / get_prompt() / as_tools()
  │  每个操作经 _run(operation, label)：
  │    发 mcp.call.started → asyncio.wait_for(operation, timeout)
  │    成功: mcp.call.completed(duration_ms) → 返回
  │    TimeoutError → mcp.call.failed → MCPError("timed out")
  │    其他异常 → mcp.call.failed → MCPError("failed")
  ▼
__aexit__: AsyncExitStack.aclose()（HTTP 客户端、SDK 客户端、stdio 进程都被关闭）
```

连接失败时 `stack.aclose()` 保证部分创建的资源被清理，`asyncio.CancelledError` 原样重抛，其余异常包装成 `MCPError(f"MCP server {name!r} connection failed")`。

**分页绑定**：`list_tools` / `list_resources` / `list_prompts` 都带游标循环，上限 `_MAX_PAGES = 20`、累计条目 `_MAX_ITEMS = 1_000`。`_next_cursor` 拒绝超过 4096 字节的游标与**重复游标**（`MCPError("repeated pagination cursor")`）。

**工具过滤**：`_tool_allowed(name)` =（`include_tools` 为空或 `name in include_tools`）且 `name not in exclude_tools`。`as_tools` 过滤被排除工具；`call_tool` 先 `_allow_tool` 校验，越界抛 `MCPError("disabled by filter")`。

### 3.4 MCP Bundle 校验与安装（`mcpb.py`）

`inspect_mcpb(path, *, expected_sha256=None)` 在**解压前**校验：

```text
SHA-256(bundle_bytes) 与 expected_sha256 比对（不匹配 → "integrity check failed"）
  ▼ 打开 zip：成员名无重复、含 manifest.json
  ▼ 文件数 <= 10_000，展开总大小 <= 256 MiB
  ▼ 无"不安全成员"（绝对路径 / 含 ".." / 含盘符冒号）
  ▼ 无符号链接（external_attr >> 16 为 S_ISLNK）
  ▼ 读取 manifest.json → 必需字段 (manifest_version, name, version, description, author, server)
  ▼ name 必须匹配 ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$（文件系统安全）
  ▼ server.type == "uv"    → command="uv",     args=("run", "${__dirname}/<entry>")
    server.type == "python"→ command="python", args=("${__dirname}/<entry>",)
    否则需要显式 mcp_config.command
  ▼ 构造 MCPServerConfig(name, STDIO, ...)
```

`install_mcpb(path, destination, *, expected_sha256=None)` 先 `inspect_mcpb`；目标 `destination/name` 校验不越出安装根、已存在则拒绝；解压到临时目录 staging，再 `copytree` 到目标；随后**在解压后才**把 command/args/env 里的 `${__dirname}` 替换为目标绝对路径，并把 `cwd` 设为目标。这保证占位符在归档内容落地后才解析。

### 3.5 插件生命周期（`installer.py` + `manager.py`）

```text
install(source)  → 暂存来源(本地目录 copytree 或 git clone --depth 1 + 修订 checkout + 子目录)
                 → load_plugin(暂存根) → 目标已存在? 拒绝
                 → _validate_tree(无符号链接) → copytree 到目标
                 → 写 .super-harness-source.json → InstalledPlugin(enabled=False)   # 不执行任何插件代码
enable(name)     → 读清单 → _load_tools(命名空间化) + _load_mcp(前缀命名)
                 → 逐个 register Tool / register Hook(source="plugin:<name>")
                 → 冲突/异常 → 回滚已注册的 Tool 与 Hook → PluginError
                 → PluginCapabilities 存入 _enabled → PluginTrace
disable(name)    → 从 _enabled 弹出 → unregister 全部 Tool / Hook
update(name)     → 要求先 disable；暂存新来源 → 校验名称一致 → staging/backup 交换替换
remove(name)     → 要求先 disable；shutil.rmtree
```

`_load_tools` 对每个入口符号调用 `_symbol(manifest, entry)` 导入 Python 模块（见下文），接受单个 `Tool` 或 `Tool` 可迭代；每个工具用 `replace(candidate.metadata, namespace=manifest.name, source=f"plugin:{manifest.name}")` **重命名空间**；检测重复限定名（`PluginError`）。`_load_mcp` 从 `mcp_path` 或 `inline_mcp` 导入，把每个服务器 `name` 前缀为 `{plugin}.{server}`，stdio 的 `cwd` 设为插件根。钩子注册以 `source=f"plugin:{name}"` 归属，`failure_policy` / `allow_modify` / `priority` / `timeout` 取自清单。

`enable` 的回滚是事务性的：先在 `registered_tools` / `registered_hooks` 里累积，任何 `SuperHarnessError` / `TypeError` / `ValueError` 触发时逐个 `unregister` 后重抛；同时 `_load_tools` / `_load_mcp` 阶段失败不会产生任何注册（无副作用）。失败路径都会发 `PluginTrace(enable, name, False, warning=...)`。

**Python 符号导入**（`_symbol` → `_module`）：入口 `./file.py:symbol` 解析为插件根内路径，用 `importlib.util.spec_from_file_location` 以唯一模块名 `_super_harness_plugin_<plugin>_<uuid>` 加载并 `exec_module`，再 `getattr(module, symbol)`。**只有 `enable` 才导入并执行插件 Python**；`install` / `load_plugin` 不执行任何代码（`test_plugin_validation_..._and_no_auto_execution` 显式验证安装后 `marker` 不存在）。

### 3.6 钩子分发（`registry.py`）

```text
dispatch(HookContext(event, data, thread_id, turn_id))
  │  data = dict(context.data)              # 事件累积数据的工作副本
  ▼
for item in sorted(_hooks[event], key=(priority, source, name)):
  │  ctx = HookContext(event, data, thread_id, turn_id, item.source)   # 每个回调一个全新不可变视图
  │  result = await asyncio.wait_for(_resolve(item.handler(ctx)), item.timeout)
  │    _resolve: 返回可等待则 await，否则原样
  ▼
  if result and result.updates:
      if not item.allow_modify: raise HookError("not allowed to modify this event")
      data.update(result.updates)
  ▼
  if result and result.deny_reason is not None:
      if event not in _DENIABLE_EVENTS: raise HookError("event cannot be denied")
      trace(denied=True) → 立即返回 HookOutcome(data, traces, denied=True, deny_reason)
  ▼
  trace(success=True, duration_ms)
  ▼
  异常（非 CancelledError）→ trace(success=False, warning)
    FAIL_CLOSED → raise HookError("failed closed")
    WARN        → warnings.warn(RuntimeWarning)
    FAIL_OPEN   → 继续
  ▼
返回 HookOutcome(data, traces)
```

`_DENIABLE_EVENTS = {USER_PROMPT, BEFORE_MODEL, PRE_TOOL_USE, PRE_COMPACT}`——只有这四个安全拦截点允许 `HookResult.deny(...)`；其他事件尝试拒绝会抛 `HookError`。`asyncio.CancelledError` 永远原样重抛（不被策略吞掉）。`register` 在追加后 `sort(key=(priority, source, name))` 保证确定性顺序；同名同源重复注册抛 `HookError`。

## 4. 关键接口/类（Key interfaces/classes）

### 4.1 `SkillCatalog`（`catalog.py`）

```python
@dataclass(slots=True)
class SkillCatalog:
    skills: dict[str, SkillMetadata] = field(default_factory=_skills)
    collisions: dict[str, list[Path]] = field(default_factory=_collisions)
    errors: list[SkillError] = field(default_factory=_errors)
    @classmethod
    def discover(cls, *, cwd=None, explicit=(), user_root=None, plugin_roots=(), system_roots=()) -> SkillCatalog: ...
    def list(self) -> tuple[SkillMetadata, ...]: ...
    def get(self, name: str) -> SkillMetadata: ...
    def activate(self, name: str) -> ActivatedSkill: ...
```

### 4.2 `SkillInstaller`（`installer.py`）

```python
class SkillInstaller:
    def __init__(self, destination: str | Path) -> None: ...
    def install(self, source: str | Path) -> SkillMetadata: ...
    def remove(self, name: str) -> None: ...
    def info(self, name: str) -> tuple[SkillMetadata, SkillSource]: ...
    def list(self) -> tuple[SkillMetadata, ...]: ...
    def update(self, name: str) -> SkillMetadata: ...
```

### 4.3 `parse_skill` / `activate_skill`（`models.py`）

```python
def parse_skill(path: str | Path, *, source: str = "runtime") -> SkillMetadata: ...
def activate_skill(metadata: SkillMetadata) -> ActivatedSkill: ...
```

### 4.4 `MCPServerConfig` / `import_mcp_servers`（`config.py`）

```python
@dataclass(frozen=True, slots=True)
class MCPServerConfig: ...   # 见 2.2

def import_mcp_servers(value: str | Path | Mapping[str, Any]) -> tuple[MCPServerConfig, ...]: ...
```

### 4.5 `MCPClient`（`client.py`）

```python
class MCPClient:
    def __init__(self, config: MCPServerConfig, *, observer: EventObserver | None = None) -> None: ...
    async def __aenter__(self) -> MCPClient: ...
    async def __aexit__(self, *exc) -> None: ...
    @property
    def protocol_version(self) -> str | None: ...
    @property
    def capabilities(self) -> object: ...
    async def list_tools(self) -> tuple[object, ...]: ...
    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]: ...
    async def list_resources(self) -> tuple[object, ...]: ...
    async def read_resource(self, uri: str) -> dict[str, Any]: ...
    async def list_prompts(self) -> tuple[object, ...]: ...
    async def get_prompt(self, name: str, arguments: dict[str, str] | None = None) -> dict[str, Any]: ...
    async def as_tools(self) -> tuple[Tool, ...]: ...
```

`as_tools` 把每个远端工具翻译成标准 `Tool`：`_arguments_model(name, schema)` 用 `create_model(f"MCP{Name}Arguments", __config__=ConfigDict(extra="forbid"), **fields)` 从 JSON Schema 的 `properties` / `required` 生成 Pydantic 参数模型；`ToolMetadata(namespace=self.config.name, source="mcp", risk="external", timeout=self.config.timeout)` 保留**服务器命名空间**与**外部风险元数据**；限定名因此是 `{server}.{tool}`。

### 4.6 MCPB 与注册表（`mcpb.py`、`registry.py`）

```python
def inspect_mcpb(path: str | Path, *, expected_sha256: str | None = None) -> MCPBundle: ...
def install_mcpb(path: str | Path, destination: str | Path, *, expected_sha256: str | None = None) -> MCPBundle: ...

class MCPRegistry(Protocol):                      # 可替换协议
    async def search(self, query: str, *, limit: int = 20) -> tuple[Mapping[str, Any], ...]: ...
    async def get(self, name: str, version: str = "latest") -> Mapping[str, Any]: ...

class OfficialMCPRegistry:
    def __init__(self, base_url: str = "https://registry.modelcontextprotocol.io", *,
                 timeout: float = 20.0, client: httpx.AsyncClient | None = None) -> None: ...
    async def search(self, query: str, *, limit: int = 20) -> tuple[Mapping[str, Any], ...]: ...
    async def get(self, name: str, version: str = "latest") -> Mapping[str, Any]: ...
```

`search` 命中 `/v0.1/servers`（`search` + `limit`，1–100）；`get` 命中 `/v0.1/servers/{name}/versions/{version}`（URL 编码）。`_get` 在未注入客户端时自建 `httpx.AsyncClient(timeout)` 并在结束时关闭；任何 `httpx.HTTPError` / `ValueError` 都包装成 `MCPError`。`limit` 越界抛 `ValueError`（非 MCP 错误）。

### 4.7 插件（`loader.py`、`manager.py`、`installer.py`）

```python
def load_plugin(path: str | Path) -> PluginManifest: ...   # 优先 .super-harness/plugin.toml，其次 .codex-plugin/plugin.json

class PluginInstaller:
    def __init__(self, destination: str | Path) -> None: ...
    def install(self, source: str | Path) -> InstalledPlugin: ...
    def update(self, name: str) -> InstalledPlugin: ...
    def remove(self, name: str) -> None: ...
    def list(self) -> tuple[PluginManifest, ...]: ...
    def info(self, name: str) -> InstalledPlugin: ...

class PluginManager:
    def __init__(self, installer: PluginInstaller, *, tools: ToolRegistry | None = None,
                 hooks: HookRegistry | None = None, trace_sink: Callable[[PluginTrace], None] | None = None) -> None: ...
    def install(self, source: str | Path) -> InstalledPlugin: ...
    def update(self, name: str) -> InstalledPlugin: ...
    def remove(self, name: str) -> None: ...
    def list(self) -> tuple[InstalledPlugin, ...]: ...
    def info(self, name: str) -> InstalledPlugin: ...
    def enable(self, name: str) -> PluginCapabilities: ...
    def disable(self, name: str) -> None: ...
    def capabilities(self) -> tuple[PluginCapabilities, ...]: ...
```

`load_plugin` 的清单校验要点：名称必须是 1–64 个 `[a-z0-9]+(?:-[a-z0-9]+)*`（kebab-case）；版本用 `packaging.version.Version` 校验；`requires_super_harness` 用 `packaging.specifiers.SpecifierSet` 对 `importlib.metadata.version("super-harness")` 求值，不匹配抛 `PluginError("plugin requires an incompatible Super Harness version")`；所有路径必须以 `./` 开头、不越出插件根；工具/钩子入口必须是 `./file.py:symbol` 且文件存在。未知清单字段被记入 `warnings` 而非报错。

### 4.8 `HookRegistry`（`registry.py`）

```python
class HookRegistry:
    def __init__(self, *, trace_sink: HookTraceSink | None = None) -> None: ...
    def register(self, event, handler, *, name=None, source="runtime", priority=100,
                 timeout=10.0, failure_policy=HookFailurePolicy.WARN, allow_modify=False) -> HookRegistration: ...
    def unregister(self, event: HookEvent, name: str, *, source: str = "runtime") -> None: ...
    def list(self, event: HookEvent | None = None) -> tuple[HookRegistration, ...]: ...
    async def dispatch(self, context: HookContext) -> HookOutcome: ...
```

## 5. 并发/取消（Concurrency/cancellation）

- **MCP 操作超时与取消**：`_run` 用 `asyncio.wait_for(operation, config.timeout)`。`asyncio.CancelledError` 原样重抛（`test_mcp_timeout_is_typed_and_cancellation_propagates` 验证 `task.cancel()` 后调用方收到 `CancelledError`）；`TimeoutError` 映射为 `MCPError("timed out")`。`__aenter__` 中取消会先 `stack.aclose()` 清理已建资源再重抛。
- **观察者可等待**：`_observe(event)` 调用 `observer.observe(event)`，若返回 awaitable 则 `await`——同步与异步观察者都受支持，且都在等待超时之外执行（不占用调用预算）。
- **钩子同步/异步统一**：`HookRegistry.dispatch` 对每个回调 `_resolve(handler(ctx))`，同步回调返回的值直接使用，异步回调被 `await`；两者都受 `asyncio.wait_for(..., item.timeout)` 约束。`asyncio.CancelledError` 永远重抛（`test_hook_failure_policies_timeout_denial_and_cancellation` 验证）。
- **插件 Python 导入**是同步 `importlib` 调用，在 `enable` 期间于事件循环内执行；插件钩子与工具随后按各自注册表的时间/取消路径运行。
- **安装器的 Git 子进程**用 `subprocess.run`（阻塞式）在安装命令期间执行；`SkillInstaller` / `PluginInstaller` 是同步 API，通常由 CLI 调用而非热路径。
- **资源读取**（`ActivatedSkill.read_resource`）是同步 `read_bytes`，被限定在 Skill 目录内。

## 6. 持久化（Persistence）

- **Skill 来源记录**：每个安装的 Skill 目录内含 `.super-harness-source.json`（`SkillSource` 的 JSON：`source_type` / `location` / `revision` / `installed_at`），`SkillInstaller.info` 依赖它重建来源。
- **插件来源记录**：安装的插件目录内含 `.super-harness-source.json`（`{"source_type","location","revision","installed_at"}`），`PluginInstaller.info` 读取并注入 `InstalledPlugin.source`。
- **MCP 配置导入**：`import_mcp_servers` 把通用 `mcpServers` JSON 映射为 `MCPServerConfig`；注册表查找通过 `OfficialMCPRegistry` 实时进行，不持久化。
- **安装目录**：`SkillInstaller(destination)` / `PluginInstaller(destination)` 把已安装项放入指定目录（隐藏的暂存/备份目录以 `.` 开头，`list()` 会跳过）。更新用 staging + backup 交换，是崩溃/失败安全的替换。
- **运行期状态**（`PluginManager._enabled`、`HookRegistry._hooks`、`ToolRegistry`）是进程内结构；跨进程恢复属于持久化扩展。

## 7. 事件/可观测性（Events/observability）

- **MCP 事件**（经 `EventObserver`，事件在 `runtime/events.py`）：`mcp.connected`（server、transport、protocol_version）；`mcp.call.started` / `mcp.call.completed` / `mcp.call.failed`（server、operation、operation_id、duration_ms、error_class）。`test_real_stdio_...` 验证观察到 `>= {mcp.connected, mcp.call.started, mcp.call.completed}`。
- **钩子追踪**：每个注册项执行都产生 `HookTrace`（event、hook、source、success、duration_ms、denied、warning），经 `trace_sink` 汇出；`HookOutcome` 把累积数据与全部 traces 一并返回给分发方。
- **插件追踪**：`PluginTrace`（operation、plugin、success、capabilities、warning）经 `PluginManager(trace_sink=...)` 汇出；`enable` 成功时 `capabilities` 列出实际激活的 `skills` / `tools` / `mcp` / `hooks` 键。
- **Skills 可观测性**：`SkillCatalog` 的 `collisions` 与 `errors` 字段让发现阶段的重名与解析问题保持可检查；`SkillMetadata.source` 记录来源供审计。
- **钩子与运行时的连接**：`Agent` / `Thread` / `ToolExecutor` / 压缩器在生命周期点分发 `HookEvent`；失败的钩子接收原始异常上下文（`ERROR` 事件），成功/拒绝/超时/错误都发追踪。

## 8. Codex 参考（Codex reference）

本层的契约、不变量与设计动机基于对 Codex（Rust）扩展栈的逆向研究：

- **Skills 与 MCP**：见 [`docs/research/codex/skills-and-mcp.md`](https://github.com/Sitozzmonash/superharness/blob/main/docs/research/codex/skills-and-mcp.md)。研究文件包括 `codex-rs/skills/src/{loading,model,parser}.rs`、`codex-rs/ext/skills/src/loader/{discovery,metadata}.rs`、`codex-rs/codex-mcp/src/connection_manager.rs`（及 `resources.rs`、`tool_catalog.rs`）。
- **插件与钩子**：见 [`docs/research/codex/plugins-and-hooks.md`](https://github.com/Sitozzmonash/superharness/blob/main/docs/research/codex/plugins-and-hooks.md)。研究文件包括 `codex-rs/core-plugins/src/{manifest,loader,manager,store,executor_hooks}.rs`、`codex-rs/hooks/src/types.rs` 与 `codex-rs/hooks/src/engine/{dispatcher,mod}.rs`。

从 Codex 提炼并在此复制的**行为契约**：

- Skill 以廉价元数据被发现，选中后才激活，支撑资源按需加载；高优先级根确定性胜出，碰撞保持可检查。
- 安装分阶段校验内容，拒绝覆盖、路径逃逸与符号链接，记录解析后的来源修订。
- MCP 用官方 SDK 而非私有线上协议；分页、游标大小、操作时长、归档数量与大小都有界；工具过滤对广告适配器与直接调用都生效；取消传播，操作失败成为类型化 `MCPError`。
- 插件是惰性元数据直到显式启用；禁用插件贡献为零；重复身份与不兼容版本被报告；安装/更新先校验后激活。
- 钩子是有序、带归属、限时的生命周期拦截器，带显式的变更/拒绝权限与可观察的失败结果；拒绝不替代审批策略。

**重要不变量**：`SKILL.md` 有校验过的 frontmatter 与非空指令；发现阶段不把每个 Skill 主体/资源急切注入上下文；安装绝不静默覆盖、绝不包含符号链接；只有显式 `enable` 才导入 Python 入口；激活是事务性的（冲突回滚）；钩子优先级确定性、取消始终传播；每次执行都记录钩子/插件的来源归属与结果追踪。

## 9. Python 原生重设计（Python-native redesign）

把 Codex 的 Rust 扩展栈映射为 Python 原生实现：

- **`SkillCatalog`** 做有序元数据发现并在按需时激活 `ActivatedSkill`；`SkillInstaller` 接受本地目录与 HTTPS Git/GitHub 子目录、检出请求的修订、校验后复制并记录 provenance。
- **`MCPClient`** 包装官方 MCP Python SDK `Client`（stdio 与 Streamable HTTP），把远端工具转换成普通 `Tool`；`import_mcp_servers`、`inspect_mcpb`/`install_mcpb` 与 `OfficialMCPRegistry`（其后是 `MCPRegistry` 协议）是独立助手。
- **`HookRegistry`** 存类型化 `HookRegistration`，经同步或异步回调分发不可变 `HookContext`；`HookResult` 可充实数据或拒绝合格事件；`HookTrace` 记录归属、时长、成功、警告与拒绝。Agent/Thread/压缩/模型/工具流水线发出生命周期事件。
- **`PluginInstaller`** 暂存本地或固定 HTTPS Git/GitHub 来源并支持安装/更新/移除；`load_plugin` 解析 `.super-harness/plugin.toml` 或 `.codex-plugin/plugin.json`；`PluginManager.enable` 显式导入声明的 Python `Tool`/钩子符号、命名空间化、加载 MCP 配置、暴露 Skill 根与被动 assets/personas/commands，并回滚冲突。
- **中性值**：`SkillMetadata` / `MCPServerConfig` / `PluginManifest` / `HookContext` 等都不依赖 OpenAI 命名空间、托管服务、账户状态或 Codex 遥测类型。

## 10. 有意差异（Intentional differences）

相对 Codex 的刻意简化/扩展：

- **Skill 名称安全**：安装要求文件系统安全的 kebab-case 名称（`^[a-z0-9]+(?:-[a-z0-9]+)*$`、≤64 字符），Codex 允许更宽松的产品化命名。
- **描述冒号兼容修复**：第三方未加引号且含冒号的描述会得到一次窄兼容性修复（`_repair_colon_scalars`），避免 `yaml.safe_load` 把含冒号标量误判。
- **Git 修订解析为不可变哈希**：`SkillInstaller` / `PluginInstaller` 把请求的修订检出为 `FETCH_HEAD` 并用 `rev-parse HEAD` 记录不可变 commit 哈希。
- **MCPB 加固**：`install_mcpb` 强制执行文件数与展开大小上限，且只在解压后才解析 `${__dirname}` 占位符。
- **MCP 协议定位**：Streamable HTTP 目标 `2026-07-28`；客户端也通过隔离的 `mcp==1.29.1` 进程与 2025 代表服务器互通（`test_official_mcp_1x_2025_protocol_compatibility`）。
- **插件 TOML 覆盖层**：新增紧凑的 `.super-harness/plugin.toml`，带显式框架版本说明符与 Python 入口符号；仍尽力导入 Codex 清单元数据。
- **Codex 命令/MCP 钩子仅元数据**：Codex 的 command/MCP 钩子被当作 metadata-only，**不自动执行**——执行不可信 shell 定义会违反"显式启用才导入 Python"的契约。
- **Codex apps/interface 被动保留**：apps 与 interface 元数据被保留但不激活，并报告为 warning。
- **完整 14 事件钩子面**：包括阶段 8 集成前的未来 subagent 点（`SUBAGENT_START` / `SUBAGENT_END`）。
- **外部兼容检查可选**：默认测试套件保持确定性且离线，GitHub/MCP 1.x/注册表 E2E 都要求 `SUPER_HARNESS_EXTERNAL_COMPAT=1`。

## 11. 失败模型（Failure model）

异常层级（`exceptions.py`）根为 `SuperHarnessError(message, *, correlation_id=None, details=None)`，`details` 冻结为 `MappingProxyType`。扩展层相关异常：

- `SkillError(SuperHarnessError)` —— frontmatter 缺失/未闭合/YAML 无效、名称非法或超长、description 缺失、指令为空、资源越出目录或不存在、安装已存在/名称越出安装根/含符号链接、Git clone/checkout 失败、来源元数据缺失或损坏。
- `MCPError(SuperHarnessError)` —— 服务器禁用、连接失败、操作超时、分页/游标/条目越限、工具被过滤器禁用、MCPB 完整性/清单/路径/符号链接/大小校验失败、注册表请求失败。
- `PluginError(SuperHarnessError)` —— 清单缺失/非法、名称/版本/框架版本不兼容、路径逃逸或越出插件根、入口不存在或符号不存在、重复工具、激活失败（包装底层异常并回滚）。
- `HookError(SuperHarnessError)` —— 重复注册、未知钩子、不允许修改事件、不允许拒绝事件、`fail_closed` 失败。

**关键失败规则**：

| 场景 | 行为 |
|---|---|
| 任务取消（`CancelledError`） | MCP `_run`、钩子 `dispatch` 都原样重抛，从不折叠 |
| MCP 操作超时 | `MCPError("timed out")`；连接/其他异常 → `MCPError("failed")` |
| 钩子回调超时 | 按 `failure_policy`：`FAIL_CLOSED` 抛 `HookError`；`WARN` 发 `RuntimeWarning`；`FAIL_OPEN` 继续 |
| 钩子非 `allow_modify` 却返回 updates | `HookError("not allowed to modify")` |
| 钩子在不可拒绝事件上返回 deny | `HookError("event cannot be denied")` |
| Skill/Plugin 安装冲突 | `SkillError` / `PluginError("already installed")`，绝不覆盖 |
| 插件激活中途冲突 | 回滚全部已注册 Tool/Hook 后抛 `PluginError` |

**默认策略**：钩子默认 `WARN`（`HookFailurePolicy.WARN`），即失败被记录并告警但不阻断；插件钩子可在清单中声明 `fail_closed` 或 `fail_open`。因此**扩展失败通常是可观察的追踪 + 可配置的阻断**，而非静默吞掉。

## 12. 扩展点（Extension points）

- **新增 Skill**：任何含 `SKILL.md`（frontmatter + 指令）的目录，放在显式、项目（`.agents/skills` / `.super-harness/skills`）、用户（`~/.super-harness/skills`）、插件或系统根即可被发现；用 `SkillInstaller` 安装本地目录或 GitHub 子目录。
- **新增 MCP 服务器**：用 `MCPServerConfig`（stdio 或 Streamable HTTP）或通用 `mcpServers` JSON 经 `import_mcp_servers` 导入；`as_tools` 自动翻译为带 `namespace` 与 `risk="external"` 的 `Tool`。
- **替换注册表实现**：实现 `MCPRegistry` 协议（`search` / `get`）注入任意后端；`OfficialMCPRegistry` 是默认的官方预览 API 适配器。
- **编写插件**：`PluginManifest` 可贡献 skills、tools（Python 符号）、MCP 配置、hooks、assets、personas、commands、config_schema / config_defaults；`enable` 才激活。
- **注册钩子**：`HookRegistry.register(event, handler, *, priority, timeout, failure_policy, allow_modify, source)`；在 `USER_PROMPT` / `BEFORE_MODEL` / `PRE_TOOL_USE` / `PRE_COMPACT` 上可拒绝，在 `allow_modify=True` 时可改写数据。
- **消费追踪**：为 `HookRegistry(trace_sink=...)`、`PluginManager(trace_sink=...)`、`MCPClient(observer=...)` 注入汇点实现应用级审计与可观测。

## 13. 测试（Tests）

- **`tests/test_skills.py`**：
  - `test_skill_progressive_discovery_precedence_activation_and_resources` —— 元数据优先发现、显式 > 项目根 > 用户根优先级、碰撞报告、激活读取指令、资源路径限定（`../outside.txt` 抛 `SkillError("escapes")`）。
  - `test_skill_validation_local_install_metadata_and_remove` —— 本地安装来源记录、重复安装拒绝、移除、缺 frontmatter / 非法名称拒绝。
  - `test_pinned_codex_skill_is_compatible_external_fixture` —— 对 `references/codex/.codex/skills/code-review` 固定 fixture 解析兼容。
  - `test_install_pinned_github_subdirectory_skill`（`@pytest.mark.e2e`，需 `SUPER_HARNESS_EXTERNAL_COMPAT=1`）—— 安装固定的 GitHub 子目录 Skill。
- **`tests/test_mcp.py`**：
  - `test_real_stdio_mcp_tools_resources_prompts_and_adapter`（`@pytest.mark.integration`）—— 真实 stdio 服务器的 tools/resources/prompts、`as_tools` 适配、`mcp.connected` / `mcp.call.started` / `mcp.call.completed` 事件。
  - `test_real_streamable_http_uses_2026_protocol_and_filter`（`@pytest.mark.integration`）—— Streamable HTTP `protocol_version == "2026-07-28"`、`exclude_tools` 过滤、`as_tools` 限定名。
  - `test_mcp_timeout_is_typed_and_cancellation_propagates`（`@pytest.mark.integration`）—— 超时映射为 `MCPError("timed out")`、`task.cancel()` 传播 `CancelledError`。
  - `test_import_common_mcp_servers_config` —— `import_mcp_servers` 对 stdio/HTTP/headers/timeout/excludeTools 的映射。
  - `test_mcpb_integrity_safe_install_and_traversal_rejection` —— SHA-256 完整性、安全安装、`${__dirname}` 解析、遍历（`../escape.py`）拒绝。
  - `test_replaceable_registry_adapter_normalizes_preview_api` —— 用 `MockTransport` 验证 `OfficialMCPRegistry.search` / `get` 对预览 API 的规范化。
  - `test_official_mcp_1x_2025_protocol_compatibility` / `test_real_official_registry_search`（`@pytest.mark.e2e`）—— 隔离 `mcp==1.29.1` 互通与真实注册表搜索。
- **`tests/test_plugins.py`**：
  - `test_plugin_install_enable_bundle_disable_update_and_remove`（`@pytest.mark.integration`）—— 安装不启用、enable 打包能力（skills/MCP/钩子）、命名空间工具经 `ToolExecutor` 执行（`echo` → `HELLO`）、disable 注销、update 到 1.1.0、remove、`PluginTrace` 序列。
  - `test_plugin_validation_codex_import_conflicts_and_no_auto_execution` —— 安装不执行代码（`marker` 不存在）、enable 才导入（`marker` 存在）、工具冲突回滚（`hooks.list() == ()`）、框架版本不兼容、路径逃逸（`./../outside`）、Codex 清单导入（`format == "codex"`）。
  - `test_official_codex_plugin_repository_compatibility`（`@pytest.mark.e2e`）—— 安装固定 `openai/plugins` 的 `plugin-eval` 子目录。
- **`tests/test_hooks.py`**：
  - `test_all_hook_events_are_ordered_observable_and_modification_is_explicit` —— 全部 14 个事件的有序分发、数据充实（`value=2`）、追踪完整性、`allow_modify` 显式性。
  - `test_hook_failure_policies_timeout_denial_and_cancellation` —— WARN 告警、FAIL_OPEN 继续、FAIL_CLOSED 抛 `HookError`、`PRE_TOOL_USE` 拒绝、取消传播。
  - `test_runtime_and_tool_pipeline_dispatch_hooks` —— 真实 `Agent` 的 session/prompt/turn/before/after/tool 钩子顺序，`PRE_TOOL_USE` 改写参数生效。
  - `test_error_and_compaction_hooks` —— `PRE_COMPACT` / `POST_COMPACT` / `ERROR` 分发与 `BEFORE_MODEL` 拒绝。
- 相关：`tests/test_cli.py` 覆盖 `test_skill_full_lifecycle`、`test_mcp_stdio_remote_import_inspect_remove_and_redaction`、`test_mcp_bundle_integrity_install_and_cleanup`、`test_mcp_store_rejects_duplicate_import`、`test_plugin_full_lifecycle` 等 CLI 级生命周期。

## 14. 限制/未来工作（Limitations/future work）

- **Git 安装要求联网与 git**：`SkillInstaller` / `PluginInstaller` 的远程路径调用 `git clone`（`--depth 1`），要求 `git` 可用且网络可达；`github.com/tree/` 之外的托管平台不支持子目录形态（仅整体仓库）。
- **插件 Python 是在进程内执行的受信代码**：`enable` 的 `importlib` 导入会在事件循环内运行任意插件代码；插件被当作应用级受信扩展，安装阶段只做结构校验，不做代码审计。执行不可信插件前应人工审查。
- **MCP 不保证运行时动态发现**：`as_tools` 在客户端连接时枚举工具；模型侧运行时动态发现/选择远端工具的完整能力属于后续 ecosystem 阶段。
- **官方注册表是预览 API**：`OfficialMCPRegistry` 命中官方注册表 v0.1 预览端点，其协议与运行时独立版本控制，因此被藏在可替换的 `MCPRegistry` 协议之后；搜索/获取没有本地缓存或离线支持。
- **`SUPER_HARNESS_EXTERNAL_COMPAT` 门控**：GitHub 子目录安装、MCP 1.x 互通、真实注册表搜索等需要联网的 E2E 默认跳过，保证默认套件确定性且离线。
- **钩子是进程内拦截器**：不提供跨进程或分布式的钩子代理；追踪经汇点汇出，但采集/导出后端由应用决定。
- **无跨进程扩展状态**：`PluginManager`、`HookRegistry`、`ToolRegistry` 与 MCP 连接都是单进程结构；跨进程恢复扩展状态属于持久化扩展。

## 相关链接

- 可运行示例：
  - [`25_skill_discovery.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/25_skill_discovery.py) / [`26_skill_activation.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/26_skill_activation.py) / [`27_skill_install.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/27_skill_install.py) —— Skill 发现/激活/安装
  - [`28_mcp_stdio_list.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/28_mcp_stdio_list.py) / [`29_mcp_stdio_call.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/29_mcp_stdio_call.py) / [`30_mcp_stdio_resources.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/30_mcp_stdio_resources.py) / [`31_mcp_http_list.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/31_mcp_http_list.py) / [`32_mcp_http_call.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/32_mcp_http_call.py) / [`33_mcp_http_prompts.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/33_mcp_http_prompts.py) —— MCP stdio/HTTP
  - [`34_mcp_config_import.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/34_mcp_config_import.py) / [`35_mcpb_install.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/35_mcpb_install.py) / [`36_mcp_registry.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/36_mcp_registry.py) —— MCP 配置/MCPB/注册表
  - [`37_plugin_install.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/37_plugin_install.py) / [`38_plugin_capabilities.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/38_plugin_capabilities.py) / [`39_plugin_lifecycle.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/39_plugin_lifecycle.py) / [`42_plugin_hook.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/42_plugin_hook.py) —— 插件生命周期与插件钩子
  - [`40_hook_logging.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/40_hook_logging.py) / [`41_hook_pre_tool_policy.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/41_hook_pre_tool_policy.py) —— 钩子日志与工具前策略
- 相关 Internals：架构与横切边界（Internals 1）、Agent/Thread/Turn（Internals 2）、工具层（Internals 4）、外部知识与记忆（Internals 5）、自主编排（Internals 7）、可观测性与持久化（Internals 8）。
- 源码：`src/super_harness/skills/`、`src/super_harness/mcp/`、`src/super_harness/plugins/`、`src/super_harness/hooks/`、`src/super_harness/tools/definition.py`、`src/super_harness/tools/registry.py`、`src/super_harness/exceptions.py`。
- 研究：`docs/research/codex/skills-and-mcp.md`、`docs/research/codex/plugins-and-hooks.md`。
