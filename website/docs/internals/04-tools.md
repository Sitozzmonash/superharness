---
id: internals-tools
title: 工具层（Internals 4）
sidebar_position: 4
description: 工具规范、注册表与懒加载、执行器流水线、截断、审批引擎、沙箱后端与中性消息存储的内部实现。
---

# 工具层：注册表、执行器、审批与沙箱

本文档对应 Super Harness 内部实现的第 4 部分：模型可见的工具（Tool）如何被定义、注册、解析、校验、审批、执行、规范化与截断，以及本地与 Docker 沙箱后端如何约束文件与进程访问。它回答"工具层内部为什么这样设计、怎样工作"，不讲解操作教程。

真实实现位于 `src/super_harness/tools/`（`definition.py`、`registry.py`、`executor.py`、`approval.py`、`result.py`、`sandbox.py`、`builtins.py`）。模型侧的中性类型定义在 `src/super_harness/models/types.py`，异常层级在 `src/super_harness/exceptions.py`。完整研究与 Codex 对照见 [`docs/research/codex/tool-runtime-sandbox-approval.md`](https://github.com/Sitozzmonash/superharness/blob/main/docs/research/codex/tool-runtime-sandbox-approval.md)。

## 1. 职责（Responsibilities）

工具层由七个模块共同承担一组边界清晰的职责：

- **`definition.py`** —— 定义模型可见的工具表面。`@tool` 装饰器从一个带类型注解的函数签名派生 Pydantic 参数模型与 JSON Schema；`Tool` 把名称、描述、输入模型、处理器与元数据打包成一个不可变对象；`ToolMetadata` 携带超时、输出上限、风险、命名空间、并行性与延迟标记。
- **`registry.py`** —— 确定性注册表。维护已加载工具与延迟（lazy）工具的有序集合，负责注册/注销、启用/禁用、查找、搜索、发现与 provider 定义导出；通过 `allowed_names` 作用域在构造期锁定注册表。
- **`executor.py`** —— 单条执行流水线：解析 → 校验 → 审批 → 限时调用 → 规范化 → 截断。拒绝与校验失败被折叠成失败的 `ToolResult` 数据返回（供模型恢复），而任务取消仍是异常并向上传播。
- **`approval.py`** —— 审批策略边界。紧凑的 `ApprovalPolicy`（默认决策 + 可选回调）在任何副作用之前拦截执行；决策只有 `ALLOW` / `DENY`。
- **`result.py`** —— 输出规范化与截断。把任意返回值（字符串、字节、Pydantic 模型、dataclass、JSON 可序列化对象）规范化为字符串，并在超过字节预算时做头/尾截断并携带截断元数据。
- **`sandbox.py`** —— 沙箱后端。`LocalSandbox` 做工作区路径约束与可取消的子进程执行；`DockerSandbox` 构造安全默认的 Docker CLI 命令（无网络、能力丢弃、只读根、允许列表环境）。
- **`builtins.py`** —— 内置工具工厂。`file_read` / `file_write` / `file_search` / `shell` / `python` 以及把它们打包的 `basic_builtin_tools(workspace)`。

在 Agent 运行时，`Agent` 持有一个 `ToolRegistry` 与一个 `ToolExecutor`（见 `agent.py`），`Thread` 循环地调用 provider、把模型返回的 `tool_calls` 喂给执行器、再把 `ToolResult` 以中性 `Message` 写回历史，直到产生最终回答或耗尽模型步数预算。

## 2. 数据模型（Data model）

### 2.1 中性模型类型（`src/super_harness/models/types.py`）

工具层不依赖任何 provider 的响应类，全部基于不可变、可冻结的中性值：

```python
@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str            # 校验正则 ^[A-Za-z][A-Za-z0-9_.-]{0,127}$
    description: str
    parameters: JsonObject   # JSON Schema，构造时校验并冻结为 MappingProxyType

@dataclass(frozen=True, slots=True)
class ToolCall:
    call_id: str             # 1-256 字符，无控制字符
    name: str                # 同上安全名称正则
    arguments: JsonObject    # 已解析的参数对象（冻结）
    raw_arguments: str       # provider 原始参数字符串，上限 1_000_000 字符

@dataclass(frozen=True, slots=True)
class Message:
    role: MessageRole
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
```

`ToolDefinition.__post_init__` 校验名称正则与 JSON 参数、冻结参数；`ToolCall.__post_init__` 校验 call_id、名称与原始参数长度并冻结参数。`JsonObject` 是一棵递归冻结的 JSON 树。

### 2.2 工具侧类型（`tools/`）

```python
@dataclass(frozen=True, slots=True)
class ToolMetadata:
    namespace: str | None = None
    source: str = "runtime"        # runtime / builtin / plugin:<name> ...
    risk: str = "low"              # low / write / process ...
    timeout: float = 30.0          # 必须 > 0
    max_output_chars: int = 20_000 # 必须 >= 100
    supports_parallel: bool = False
    deferred: bool = False
    extra: Mapping[str, Any] = field(default_factory=_empty_extra)

@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    description: str
    input_model: type[BaseModel]
    handler: ToolCallable
    metadata: ToolMetadata = field(default_factory=ToolMetadata)

    @property
    def qualified_name(self) -> str: ...   # "ns.name" 或 "name"
    def provider_definition(self) -> ToolDefinition: ...
    def validate(self, arguments) -> dict: ...        # 抛 ToolValidationError
    async def invoke(self, arguments) -> object: ...

@dataclass(frozen=True, slots=True)
class LazyTool:          # 延迟工具元数据
    name: str
    description: str
    namespace: str | None = None
    source: str = "runtime"

@dataclass(frozen=True, slots=True)
class ToolResult:
    call_id: str
    name: str
    output: str
    success: bool
    truncated: bool = False
    original_chars: int = 0
    error_type: str | None = None
```

`Tool.qualified_name` 在有命名空间时拼接 `namespace.name`；`provider_definition()` 通过 `input_model.model_json_schema()` 生成 JSON Schema；`validate()` 用 `model_validate` 解析并把校验失败包装成 `ToolValidationError`；`invoke()` 先 `validate`，协程处理器直接 `await`，同步处理器经 `asyncio.to_thread` 运行。`ToolMetadata.__post_init__` 强制 `timeout > 0` 与 `max_output_chars >= 100`，并把 `extra` 冻结为 `MappingProxyType`。

`ToolResult` 是执行器对外与对模型唯一的输出载体：成功与否、截断与否、原始字符数与错误类型一并携带，供模型与可观测层消费。

### 2.3 审批类型（`approval.py`）

```python
class ApprovalDecision(StrEnum):
    ALLOW = "allow"
    DENY  = "deny"

@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    tool: Tool
    arguments: Mapping[str, Any]
    call_id: str

ApprovalCallback = Callable[[ApprovalRequest], ApprovalDecision | Awaitable[ApprovalDecision]]
```

### 2.4 沙箱类型（`sandbox.py`）

```python
class SandboxMode(StrEnum):
    READ_ONLY      = "read_only"
    WORKSPACE_WRITE = "workspace_write"
    FULL_ACCESS    = "full_access"

@dataclass(frozen=True, slots=True)
class ProcessResult:
    exit_code: int
    stdout: str
    stderr: str
```

## 3. 生命周期（Lifecycle）

### 3.1 装饰器构造（定义期）

```
函数 (带类型注解, 可选默认值)
   │  @tool(name=..., namespace=..., timeout=..., ...)
   ▼
_argument_model: 遍历签名 → 拒绝 *args/**kwargs → 要求每个参数有注解
   │              create_model(ConfigDict(extra="forbid")) → Pydantic 参数模型
   ▼
Tool(名称, 描述, input_model, handler, ToolMetadata)
   │  provider_definition() → ToolDefinition(name, description, JSON Schema)
   ▼
注册进 ToolRegistry（或 register_lazy 延迟登记）
```

### 3.2 注册表生命周期（运行期）

```
register / register_lazy
   │  校验 allowed_names 作用域（fnmatch）→ 校验重名 → 加 RLock
   ▼
已加载集合 _tools  /  延迟集合 _lazy
   │  load(name): loader() → 校验返回 Tool 且 qualified_name 精确匹配 → 移入 _tools
   │  disable(name) → _disabled 集合
   ▼
get(name): 已禁用抛 ToolError("disabled")；未知抛 ToolError("unknown")
   ▼
unregister(name)  ←→  enable(name) / disable(name)
```

延迟加载的结果必须先返回**精确的限定名称**（`qualified_name == name`）才能变为可见；返回不匹配的 `Tool` 会触发 `ToolError`。加载器抛出的任何异常都被包装成带 `details` 的 `ToolError`。

### 3.3 单次工具执行流水线（执行期）

```
ToolCall(name, arguments, raw_arguments)
   │
   ▼ registry.get(name)                    未知/禁用 → 失败 ToolResult
   ▼ item.validate(arguments)               schema 不符 → ToolValidationError → 失败 ToolResult
   ▼ approval.require(ApprovalRequest)      非 ALLOW → ApprovalDenied → 失败 ToolResult（无副作用）
   ▼ hooks.dispatch(PRE_TOOL_USE)           可拒绝；可改写 arguments（重新 validate）
   ▼ asyncio.wait_for(item.invoke(args), timeout)   超时 → TimeoutError → 失败 ToolResult
   ▼ stringify_output(value)                任意返回值 → str
   ▼ truncate_output(output, max_output_chars)      头/尾截断 + 元数据
   ▼ hooks.dispatch(POST_TOOL_USE)          可替换 result
   ▼
ToolResult(call_id, name, output, success, truncated, original_chars, error_type)
```

### 3.4 Agent 多步工具循环（`runtime/thread.py`）

```
for step in 1..max_model_steps:
    provider.complete/stream(request with definitions)
    if response.tool_calls and tool_executor:
        追加 ASSISTANT Message(tool_calls=response.tool_calls)   # WAITING_TOOL
        若 >1 个调用且全部 supports_parallel → asyncio.gather 并行
        否则顺序执行
        for call, result: 追加 TOOL Message(name, tool_call_id, result.output)
        continue                              # 回到模型，产生下一批 tool_calls 或最终回答
    else:
        turn.complete(response); 结束
```

`max_model_steps` 是**有界模型步数预算**（`Agent` 默认 8，强制 `>= 1`），它在运行时层面保证工具循环不会无限延续——每一步要么产出最终回答，要么在预算耗尽后由上层结束。

## 4. 关键接口/类（Key interfaces/classes）

### 4.1 `@tool` 装饰器（`definition.py`）

```python
@overload
def tool(function: ToolCallable, *, name=None, description=None, namespace=None,
         source="runtime", risk="low", timeout=30.0, max_output_chars=20_000,
         supports_parallel=False, deferred=False) -> Tool: ...

@overload
def tool(function: None = None, *, ... ) -> Callable[[ToolCallable], Tool]: ...
```

`_argument_model` 用 `create_model` 按函数签名动态生成 `{Name}Arguments` Pydantic 模型，配置 `ConfigDict(extra="forbid")`——多传参数会被拒绝。`inspect.signature` 与 `get_type_hints` 要求每个参数有注解；`*args` / `**kwargs` 被显式拒绝（`TypeError`）。

### 4.2 `ToolRegistry`（`registry.py`）

```python
class ToolRegistry:
    def __init__(self, tools: Iterable[Tool] = (), *, allowed_names: Iterable[str] | None = None): ...
    def register(self, item: Tool) -> None: ...
    def register_lazy(self, name, description, loader, *, namespace=None, source="runtime") -> LazyTool: ...
    def load(self, name: str) -> Tool: ...
    def unregister(self, name: str) -> Tool: ...
    def unregister_lazy(self, name: str) -> LazyTool: ...
    def get(self, name: str) -> Tool: ...
    def enable(self, name: str) -> None: ...
    def disable(self, name: str) -> None: ...
    def list(self, *, include_disabled: bool = False) -> tuple[Tool, ...]: ...
    def search(self, query: str, *, load_deferred: bool = False) -> tuple[Tool, ...]: ...
    def deferred(self) -> tuple[LazyTool, ...]: ...
    def discover(self, query: str = "") -> tuple[tuple[str, str, str, bool], ...]: ...
    def definitions(self, *, include_deferred: bool = False) -> tuple[ToolDefinition, ...]: ...
```

- **注册顺序稳定**：`list()` 按插入顺序返回，重复限定名显式报错（"already registered"），绝不静默替换当前实现。
- **作用域锁定**：`allowed_names` 用 `fnmatchcase` 匹配（`Agent` 在 persona 场景传入 `tool_scopes`）。注册/懒注册先过 `_require_allowed`，越界抛 `ToolError("outside the registry scope")`。
- **延迟名称校验**：`register_lazy` 用正则 `[A-Za-z0-9][A-Za-z0-9_.-]{0,127}` 校验限定名，并要求描述与 `loader` 可调用。
- **搜索**：`search(query, load_deferred=True)` 会实例化匹配的延迟工具；`discover` 返回 `(qualified_name, description, source, is_deferred)` 元组，用于列表而不强制加载。
- **definitions**：导出 provider 定义；默认跳过 `metadata.deferred` 标记的工具，`include_deferred=True` 时包含。

### 4.3 `ToolExecutor`（`executor.py`）

```python
class ToolExecutor:
    def __init__(self, registry: ToolRegistry, *, approval: ApprovalPolicy | None = None,
                 hooks: HookRegistry | None = None) -> None:
        self.registry = registry
        self.approval = approval or ApprovalPolicy.full_access()
        self.hooks = hooks
    async def execute(self, call: ToolCall) -> ToolResult: ...
```

`execute` 是上节流水线的实现。关键点：`registry.get` → `validate` → `approval.require` → `PRE_TOOL_USE` 钩子 → `asyncio.wait_for(item.invoke(arguments), timeout=item.metadata.timeout)` → `stringify_output` → `truncate_output` → `POST_TOOL_USE` 钩子。钩子可改写参数（改写后**重新 validate**）或替换 `ToolResult`。

### 4.4 `ApprovalPolicy`（`approval.py`）

```python
class ApprovalPolicy:
    def __init__(self, *, default: ApprovalDecision = ApprovalDecision.ALLOW,
                 callback: ApprovalCallback | None = None) -> None: ...
    @classmethod
    def full_access(cls) -> ApprovalPolicy: ...   # default=ALLOW
    @classmethod
    def deny_all(cls) -> ApprovalPolicy: ...       # default=DENY
    async def require(self, request: ApprovalRequest) -> None: ...
```

`require` 在 `callback is None` 时用 `default`，否则调用 `callback(request)`；若回调返回 `Awaitable` 则 `await`。非 `ALLOW` 即抛 `ApprovalDenied`（携带 `correlation_id=call_id` 与 `details={"tool": ...}`）。

### 4.5 `LocalSandbox`（`sandbox.py`）

```python
class LocalSandbox:
    workspace: Path
    mode: SandboxMode = SandboxMode.FULL_ACCESS
    environment_allowlist: tuple[str, ...] = (_default_environment_names())

    def __post_init__(self): ...           # workspace.resolve(strict=True) 必须是目录
    @staticmethod
    def _within(path, root) -> bool: ...
    def resolve(self, path, *, write=False) -> Path: ...   # 相对路径 → workspace 下；越界/只读写 → SandboxError
    def process_environment(self, extra=None) -> dict[str, str]: ...
    def require_process_access(self) -> None: ...          # 非 FULL_ACCESS 抛 SandboxError
    async def run_exec(self, argv, *, cwd=None, env=None) -> ProcessResult: ...
    async def run_shell(self, command, *, cwd=None, env=None) -> ProcessResult: ...
    @staticmethod
    async def terminate(process) -> None: ...
```

- **路径解析在 I/O 之前**：`resolve` 先 `resolve(strict=False)` 得到规范路径，再校验是否落在 `workspace` 内；`FULL_ACCESS` 模式跳过越界检查。`write=True` 且 `READ_ONLY` 抛 `SandboxError("read-only")`。
- **进程组终止**：Windows 用 `CREATE_NEW_PROCESS_GROUP`（0x00000200）创建子进程，取消时以 `taskkill /PID <pid> /T /F` 杀进程树；POSIX 用 `start_new_session=True`，取消时 `os.killpg(pid, SIGKILL)`。取消路径用 `asyncio.shield` 保护终止任务。
- **环境允许列表**：`process_environment` 只拷贝 `environment_allowlist` 命名的变量再加 `extra`。
- **shell/python 需完全访问**：`require_process_access` 在非 `FULL_ACCESS` 下拒绝，因为路径检查无法约束任意子进程系统调用。

### 4.6 `DockerSandbox`（`sandbox.py`）

```python
class DockerSandbox:
    workspace: Path
    image: str
    mode: SandboxMode = SandboxMode.WORKSPACE_WRITE
    network: str = "none"
    environment_allowlist: tuple[str, ...] = ()
    read_only_mounts: Mapping[Path, str] = field(default_factory=_mount_mapping)
    cpus: float = 1.0
    memory: str = "512m"
    pids_limit: int = 128
    timeout: float = 60.0
    docker_executable: str = "docker"

    def __post_init__(self): ...
    def available(self) -> bool: ...       # shutil.which(docker_executable)
    def describe(self) -> dict[str, object]: ...
    def build_command(self, argv, *, cwd=None, env=None, container_name=None) -> tuple[list[str], dict[str, str]]: ...
    async def run_exec(self, argv, *, cwd=None, env=None) -> ProcessResult: ...
    async def run_shell(self, command, *, cwd=None, env=None) -> ProcessResult: ...
    async def _cleanup(self, name, environment) -> None: ...
```

`build_command` 直接构造 argv（不经 shell），含：`--rm --init --name <name> --network <net> --read-only --cap-drop ALL --security-opt no-new-privileges --pids-limit N --memory M --cpus C --tmpfs /tmp:rw,nosuid,nodev,size=64m --mount type=bind,src=<workspace>,dst=/workspace,{ro|rw} --workdir /workspace/<rel>`，加上只读挂载与每个允许列表环境键的 `--env KEY`，最后接镜像与 argv。**环境值绝不进入 argv**（只传键名），值经宿主机进程环境注入。`__post_init__` 校验镜像引用、网络名、资源限制、内存后缀（`[1-9][0-9]*[kKmMgG]`）、挂载目标为绝对安全路径。`run_exec` 用 `asyncio.timeout(self.timeout)`，超时/取消时执行命名容器清理 `docker rm -f <name>` 并终止进程。`run_shell` 转译为 `("/bin/sh", "-lc", command)` 交给 `run_exec`。

### 4.7 内置工具（`builtins.py`）

```python
def file_read_tool(sandbox) -> Tool      # name="file_read",  source="builtin", risk="low", supports_parallel=True
def file_write_tool(sandbox) -> Tool     # name="file_write", source="builtin", risk="write"
def file_search_tool(sandbox) -> Tool    # name="file_search", source="builtin", risk="low", supports_parallel=True
def shell_tool(sandbox) -> Tool          # name="shell", source="builtin", risk="process", timeout=60.0
def python_tool(sandbox) -> Tool         # name="python", source="builtin", risk="process", timeout=60.0
def basic_builtin_tools(workspace) -> tuple[Tool, ...]   # LocalSandbox(workspace) + 上述五个
```

文件工具都先经 `sandbox.resolve(...)`（写操作 `write=True`）再在 `asyncio.to_thread` 中执行真实 I/O；`shell` / `python` 调用 `sandbox.run_shell` / `sandbox.run_exec`，因此需要 `FULL_ACCESS` 本地策略。

## 5. 并发/取消（Concurrency/cancellation）

- **注册表线程安全**：`ToolRegistry` 用 `threading.RLock` 保护所有可变状态，构造期传入的工具在 `__init__` 内注册；跨线程注册/查找安全。
- **同步处理器**：`Tool.invoke` 对非协程处理器调用 `asyncio.to_thread`，避免阻塞事件循环；协程处理器直接 `await`。
- **并行工具调用**：`Thread` 在 `len(tool_calls) > 1` 且**每个**工具 `metadata.supports_parallel` 都为真时，用 `asyncio.gather` 并行执行；否则顺序执行。未知工具会让该批次回退为顺序（捕获 `ToolError` 置 `parallel=False`）。
- **取消语义**：`ToolExecutor.execute` 中的 `asyncio.CancelledError` 被原样 `raise`（不是折叠成 `ToolResult`），因此任务取消传播到调用方与子进程清理。`LocalSandbox.run_exec/run_shell` 在 `CancelledError` 时用 `asyncio.shield` 保护 `terminate` 完成进程组终止后再重抛。
- **限时**：`asyncio.wait_for(..., timeout=item.metadata.timeout)` 实现每工具超时；`TimeoutError` 被折叠成 `error_type="TimeoutError"` 的失败 `ToolResult`。`DockerSandbox.run_exec` 用 `asyncio.timeout(self.timeout)`，超时与取消都触发容器清理。

## 6. 中性消息存储（Persistence / neutral storage）

工具调用与输出以**中性 `Message`** 存储于 Thread 历史，不携带 provider 形态。`Message.role` 为 `ASSISTANT` 的条目携带 `tool_calls: tuple[ToolCall, ...]`；`Message.role` 为 `TOOL` 的条目携带 `name` 与 `tool_call_id` 以及 `content`（即规范化后的 `ToolResult.output`）。这样同一条历史可被任一 provider 翻译：

- **Chat Completions**（`_message`）：assistant 消息的 `tool_calls` 序列化为 `{"id", "type":"function", "function":{name, arguments:raw_arguments}}`；工具结果作为 `role:"tool"` 消息并带 `tool_call_id`。
- **Responses**：工具结果转成 `{"type":"function_call_output", "call_id", "output"}`；assistant 的 `tool_calls` 转成 `{"type":"function_call", "call_id", "name", "arguments"}`。

一个 `call_id` 贯穿模型调用、事件、结果与后续消息，构成唯一的关联键。

## 7. 事件/可观测性（Events/observability）

### 7.1 运行时事件

`Thread` 在工具循环中发出（`Event` 带 `thread_id`、`turn_id`、`tool_call_id` 字段）：

- `tool.started` —— 每个调用执行前，payload 含 `{name, arguments}`。
- `tool.completed` / `tool.failed` —— 每个调用结束后，payload 含 `{result, success}`。
- 相邻还有 `model.completed` / `model.failed`（含 step、usage、tool_calls、provider/model）。

事件可通过 `Agent(observer=...)` 订阅（`EventObserver`），用于可观测与追踪。

### 7.2 钩子

`ToolExecutor` 在审批后围绕执行分发两个钩子事件（`HookRegistry`，见 `hooks/`）：

- `PRE_TOOL_USE`（**可拒绝**）—— payload `{tool, call, arguments}`；`HookResult.deny(...)` 会使执行返回 `error_type="HookDenied"` 的失败 `ToolResult`；`allow_modify=True` 的处理器可改写 `arguments`（改写后重新 `validate`）。
- `POST_TOOL_USE` —— payload `{tool, call, arguments, result}`；处理器可用 `HookResult.enrich(result=...)` 替换最终 `ToolResult`。

钩子失败策略（成功/拒绝/超时/错误）按注册项各自设置，并发出 `HookTrace`。

### 7.3 结果可观测性

`ToolResult` 携带 `truncated`、`original_chars`、`error_type`，供诊断保留截断/失败元数据而不污染模型上下文。

## 8. Codex 参考（Codex reference）

本层的行为契约、不变量与设计动机都基于对 Codex（Rust）工具栈的逆向研究，详见 [`docs/research/codex/tool-runtime-sandbox-approval.md`](https://github.com/Sitozzmonash/superharness/blob/main/docs/research/codex/tool-runtime-sandbox-approval.md)。研究的文件包括 `codex-rs/tools/src/tool_definition.rs`、`tool_executor.rs`、`tool_output.rs`、`json_schema.rs`，`codex-rs/core/src/tools/registry.rs`、`router.rs`、`orchestrator.rs`、`parallel.rs`、`sandboxing.rs`、`approvals.rs`，以及 `handlers/unified_exec.rs` 等。

从中提炼并在本层复制的**行为契约**：

- 工具把名称、描述、输入 schema、处理器、暴露、超时与风险元数据捆绑在一起。
- 注册表插入顺序稳定；重复/保留名称显式拒绝。
- 模型调用被规范化 → 解析 → 校验 → 审批 → 在所选沙箱策略下执行 → 约束输出 → 转成模型可见结果。
- 未知工具与非法参数成为模型可观察的显式失败。
- 取消中止活跃执行；已完成的执行不会被迟到的取消覆盖。
- 大输出在重新进入模型上下文前被刻意截断，诊断保留截断元数据。

**重要不变量**：审批发生在副作用之前；校验失败绝不调用处理器；一个 call ID 关联模型调用/事件/结果/后续消息；注册表冲突绝不静默改变活跃实现；文件路径在访问前解析并对照显式根检查；本地进程执行不被描述为强安全边界；工具失败是模型循环的数据，而框架/取消失败仍是类型化异常。

## 9. Python 原生重设计（Python-native redesign）

把 Codex 的 Rust 工具栈映射为 Python 原生实现：

- **`@tool` 从类型化函数签名派生 Pydantic 参数模型与 JSON Schema**，替代手写 JSON Schema（`create_model` + `model_json_schema`）。
- **`ToolRegistry`** 拥有确定性的注册、命名空间、启用/禁用、查找、搜索与 provider 定义。
- **`ToolExecutor`** 组合校验、`ApprovalPolicy`、超时/取消、结果规范化、截断与事件。
- **`LocalSandbox`** 解析工作区路径并以显式 cwd/环境运行子进程，取消时终止进程组。
- **Agent 运行时**重复「模型 → 工具调用 → 工具结果」直到最终回答或步数预算。
- **中性值**：`ToolDefinition` / `ToolCall` / `ToolResult` 不依赖 Responses API 项类、OpenAI 命名空间、托管工具、账户状态或 Codex 遥测类型。

## 10. 有意差异（Intentional differences）

相对 Codex 的刻意简化/扩展：

- **紧凑的审批策略**：暴露 allow/deny/callback 的 `ApprovalPolicy`，而非 Codex 面向 UI 的 reviewer 与 guardian 分层。决策枚举只有 `ALLOW` / `DENY`。
- **shell/python 需完全访问**：本地 `shell` 与 `python` 内置工具要求 `FULL_ACCESS` 本地策略，因为路径检查无法约束任意子进程行为（这是 Codex 本地沙箱同样承认的边界）。
- **延迟/延迟注册元数据**：现在就用 `LazyTool` 表示延迟注册元数据；模型侧动态工具搜索在后续 ecosystem 阶段完成（本层提供 `discover` / `search(load_deferred=True)` 基础）。
- **审批无副作用保证**：`deny_all` 与回调拒绝在处理器运行前返回，测试显式验证 `side_effects == []`。

## 11. 失败模型（Failure model）

异常层级（`exceptions.py`）根为 `SuperHarnessError(message, *, correlation_id=None, details=None)`，`details` 冻结为 `MappingProxyType`（只读诊断）。工具层相关：

- `ToolError(SuperHarnessError)` —— 注册/查找/加载失败（重复、未知、禁用、越界作用域、懒加载失败、名称不合法）。
- `ToolValidationError(ToolError)` —— 参数不满足声明 schema。
- `ApprovalDenied(SuperHarnessError)` —— 审批拒绝，携带 `correlation_id=call_id`。
- `SandboxError(SuperHarnessError)` —— 沙箱准备或执行失败（越界、只读写、进程访问被拒、argv 非法、Docker 资源限制、环境键不在允许列表、Docker 可执行文件不可用）。

**执行器的失败折叠规则**（`ToolExecutor.execute`）：

| 条件 | 返回 / 行为 |
|---|---|
| `asyncio.CancelledError` | 原样 `raise`（任务取消是异常，不是数据） |
| `TimeoutError` | 失败 `ToolResult`，`error_type="TimeoutError"` |
| `ApprovalDenied` / `ToolValidationError` / `ToolError` | 失败 `ToolResult`，`error_type=type(exc).__name__` |
| 其余 `Exception` | 失败 `ToolResult`，`error_type=type(exc).__name__`，消息 `"tool {name} failed: {exc}"` |

因此**工具失败是给模型的数据**（模型可观察并恢复），而框架/取消失败仍是类型化异常并向上传播到 `Thread` 与子进程清理。`ApprovalDenied`、`ToolValidationError`、`ToolError` 均可在钩子阶段被拒绝（`HookDenied`）或改写。

## 12. 扩展点（Extension points）

- **自定义工具**：用 `@tool` 装饰任意带注解的同步/异步函数；通过 `name`、`namespace`、`description`、`risk`、`timeout`、`max_output_chars`、`supports_parallel`、`deferred`、`source` 控制表面与元数据。
- **延迟加载**：`register_lazy(name, description, loader)` 注册轻量元数据，首次 `load`/`search(load_deferred=True)` 才实例化；适合插件/生态边界。
- **自定义审批**：`ApprovalPolicy(default=..., callback=...)`，回调可同步或异步，可对 `ApprovalRequest` 做任意决策（按工具、参数、call_id）。
- **钩子拦截/改写**：注册 `PRE_TOOL_USE`（拒绝或改写参数）与 `POST_TOOL_USE`（替换结果）处理器，实现应用级策略与审计。
- **自定义沙箱后端**：以 `LocalSandbox` / `DockerSandbox` 为范本，实现同构的 `run_exec` / `run_shell` / `resolve` 表面；内置工具通过注入的 `sandbox` 对象工作。
- **内置工具工厂**：`basic_builtin_tools(workspace)` 或单个工厂 `file_read_tool(sandbox)` 等，可组合进任意注册表。

## 13. 测试（Tests）

- **`tests/test_tools.py`**：
  - 装饰器 schema 生成与校验：`test_tool_decorator_builds_schema_and_validates`（限定名、JSON Schema properties/required、默认值填充、非法参数抛 `ToolValidationError`）。
  - 注解与可变参数约束：`test_tool_requires_annotations_and_rejects_variadic_parameters`（缺注解、`*args` 抛 `TypeError`）。
  - 注册表冲突/状态/顺序/搜索/延迟可见性：`test_registry_conflicts_state_order_search_and_deferred_visibility`（重复注册、disable/enable、顺序、`search`、`definitions(include_deferred)`、unregister）。
  - 执行器校验/审批/超时/截断：`test_executor_validation_approval_timeout_and_truncation`（`deny_all` 后 `side_effects == []`、回调 ALLOW 后 `truncated` 与 `original_chars`、`ToolValidationError`、`TimeoutError`）。
  - 沙箱路径策略：`test_sandbox_path_policy`（只读写拒绝、越界拒绝、进程访问需 full_access）。
  - 内置文件/进程工具（`@pytest.mark.integration`）：`test_builtin_file_and_process_tools`。
  - 进程取消终止：`test_process_cancellation_terminates_promptly`（`@pytest.mark.integration`，`sleep(30)` 取消后在 5s 内抛 `CancelledError`）。
- **`tests/test_exceptions.py`**：`test_error_preserves_read_only_diagnostics` 验证 `SuperHarnessError.details` 是只读 `MappingProxyType`（构造后不可变）。
- 相关的钩子/端到端覆盖：`tests/test_hooks.py` 验证 `PRE_TOOL_USE` 拒绝与改写、`POST_TOOL_USE` 分发及事件顺序。

## 14. 限制/未来工作（Limitations/future work）

- **本地沙箱不是强隔离**：`LocalSandbox` 的类 docstring 明确"path-constrained local runner, not a strong security boundary"——路径检查无法约束任意子进程的系统调用；`shell`/`python` 因此被限制在 `FULL_ACCESS`。需要强隔离时应使用 `DockerSandbox` 或外部容器化运行时。
- **审批是进程内策略**：`ApprovalPolicy` 是同步/异步回调式的进程内决策，不提供持久化的人工审批队列或分布式 reviewer 层。
- **模型侧动态工具搜索**：本层已提供 `discover` / `search(load_deferred=True)` 与延迟注册元数据，但模型在对话中动态发现并选择工具的完整能力在后续 ecosystem 阶段完成。
- **Docker 是部署前置条件**：`DockerSandbox.available()` 只是探测 `docker` 可执行文件与镜像是否存在；镜像不会隐式拉取。缺 Docker 或镜像时按 `test_docker_run_if_available` 示例显式跳过，而非自动下载。
- **步数预算即上限**：`max_model_steps` 是硬上限，不区分"还在推进"与"死循环"；预算耗尽由上层（`Thread`/调用方）决定如何收尾。
- **无跨进程工具状态**：注册表与执行器是单进程内的确定性结构；跨进程恢复工具调用状态属于持久化扩展，随阶段 3/8 的恢复能力演进。

## 相关链接

- 可运行示例：
  - [`04_custom_tool_loop/main.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/04_custom_tool_loop/main.py) —— 完整函数工具循环
  - [`05_approval_and_registry/main.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/05_approval_and_registry/main.py) —— 注册表 + 回调审批
  - [`06_builtin_tools/main.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/06_builtin_tools/main.py) —— 内置文件与 Python 工具
  - [`66_dynamic_tool_registration.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/66_dynamic_tool_registration.py) —— 运行期注册/注销
  - [`67_lazy_tool_discovery.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/67_lazy_tool_discovery.py) / [`68_lazy_namespaced_tools.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/68_lazy_namespaced_tools.py) —— 延迟工具发现/命名空间
  - [`69_docker_secure_command.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/69_docker_secure_command.py) / [`70_docker_allowlisted_environment.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/70_docker_allowlisted_environment.py) / [`71_docker_run_if_available.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/71_docker_run_if_available.py) —— Docker 沙箱
  - [`86_file_search_builtin.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/86_file_search_builtin.py) / [`87_local_sandbox_process.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/87_local_sandbox_process.py) —— 内置工具与本地进程
  - [`88_approval_allow.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/88_approval_allow.py) / [`89_approval_deny_all.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/89_approval_deny_all.py) —— 审批允许/全部拒绝
  - [`41_hook_pre_tool_policy.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/41_hook_pre_tool_policy.py) / [`61_security_restricted_sandbox.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/61_security_restricted_sandbox.py) —— 工具钩子与受限沙箱
- 相关 Internals：模型/流（Internals 1）、Agent/Thread/Turn（Internals 2）、插件与钩子（Internals 6 相关）、Skills 与 MCP（Internals 5 相关）。
- 源码：`src/super_harness/tools/`、`src/super_harness/models/types.py`、`src/super_harness/exceptions.py`、`src/super_harness/runtime/thread.py`。
- 研究：`docs/research/codex/tool-runtime-sandbox-approval.md`。
