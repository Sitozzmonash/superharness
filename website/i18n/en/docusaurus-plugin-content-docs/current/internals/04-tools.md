---
id: internals-tools
title: Tool Layer (Internals 4)
sidebar_position: 4
description: Internal implementation of tool specification, registry with lazy loading, executor pipeline, truncation, approval engine, sandbox backends, and neutral message storage.
---

# Tool Layer: Registry, Executor, Approval, and Sandbox

This document covers part 4 of Super Harness internals: how model-visible tools are defined, registered, resolved, validated, approved, executed, normalized, and truncated, and how the local and Docker sandbox backends constrain file and process access. It answers "why is the tool layer designed this way and how does it work"; it is not an operations tutorial.

The real implementation lives in `src/super_harness/tools/` (`definition.py`, `registry.py`, `executor.py`, `approval.py`, `result.py`, `sandbox.py`, `builtins.py`). Neutral model-side types are defined in `src/super_harness/models/types.py` and the exception hierarchy in `src/super_harness/exceptions.py`. Full research and the Codex comparison live in [`docs/research/codex/tool-runtime-sandbox-approval.md`](https://github.com/Sitozzmonash/superharness/blob/main/docs/research/codex/tool-runtime-sandbox-approval.md).

## 1. Responsibilities

The tool layer is split across seven modules, each with a clearly bounded responsibility:

- **`definition.py`** — the model-visible tool surface. The `@tool` decorator derives a Pydantic argument model and JSON Schema from a typed function signature; `Tool` bundles name, description, input model, handler, and metadata into one immutable object; `ToolMetadata` carries timeout, output limit, risk, namespace, parallelism, and deferred flags.
- **`registry.py`** — the deterministic registry. It keeps an ordered collection of loaded tools and lazy tools, and handles register/unregister, enable/disable, lookup, search, discovery, and provider-definition export; `allowed_names` can lock the registry scope at construction time.
- **`executor.py`** — the single execution pipeline: resolve → validate → approve → time-bound invoke → normalize → truncate. Denials and validation failures collapse into failed `ToolResult` data (so the model can recover), while task cancellation remains an exception and propagates up.
- **`approval.py`** — the approval-policy boundary. A compact `ApprovalPolicy` (default decision plus optional callback) intercepts execution before any side effect; the only decisions are `ALLOW` / `DENY`.
- **`result.py`** — output normalization and truncation. It normalizes arbitrary return values (strings, bytes, Pydantic models, dataclasses, JSON-serializable objects) to strings and head/tail-truncates past a byte budget while retaining truncation metadata.
- **`sandbox.py`** — sandbox backends. `LocalSandbox` does workspace path constraints and cancellable subprocess execution; `DockerSandbox` builds a Docker CLI command with secure defaults (no network, capability drop, read-only root, allowlisted environment).
- **`builtins.py`** — built-in tool factories: `file_read` / `file_write` / `file_search` / `shell` / `python`, and `basic_builtin_tools(workspace)` that bundles them.

In the agent runtime, `Agent` owns one `ToolRegistry` and one `ToolExecutor` (see `agent.py`). `Thread` loops over the provider, feeds the returned `tool_calls` to the executor, and writes each `ToolResult` back to history as a neutral `Message`, until a final answer is produced or the model-step budget is exhausted.

## 2. Data model

### 2.1 Neutral model types (`src/super_harness/models/types.py`)

The tool layer never depends on any provider's response classes; everything is based on immutable, frozen neutral values:

```python
@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str            # validated ^[A-Za-z][A-Za-z0-9_.-]{0,127}$
    description: str
    parameters: JsonObject   # JSON Schema; validated and frozen to MappingProxyType on construction

@dataclass(frozen=True, slots=True)
class ToolCall:
    call_id: str             # 1-256 chars, no control characters
    name: str                # same safe-name regex
    arguments: JsonObject    # parsed argument object (frozen)
    raw_arguments: str       # provider raw argument string, max 1_000_000 chars

@dataclass(frozen=True, slots=True)
class Message:
    role: MessageRole
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
```

`ToolDefinition.__post_init__` validates the name regex and JSON parameters and freezes the parameters; `ToolCall.__post_init__` validates call_id, name, and raw-argument length and freezes the arguments. `JsonObject` is a recursively frozen JSON tree.

### 2.2 Tool-side types (`tools/`)

```python
@dataclass(frozen=True, slots=True)
class ToolMetadata:
    namespace: str | None = None
    source: str = "runtime"        # runtime / builtin / plugin:<name> ...
    risk: str = "low"              # low / write / process ...
    timeout: float = 30.0          # must be > 0
    max_output_chars: int = 20_000 # must be >= 100
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
    def qualified_name(self) -> str: ...   # "ns.name" or "name"
    def provider_definition(self) -> ToolDefinition: ...
    def validate(self, arguments) -> dict: ...        # raises ToolValidationError
    async def invoke(self, arguments) -> object: ...

@dataclass(frozen=True, slots=True)
class LazyTool:          # deferred tool metadata
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

`Tool.qualified_name` concatenates `namespace.name` when a namespace is present; `provider_definition()` produces JSON Schema via `input_model.model_json_schema()`; `validate()` parses with `model_validate` and wraps failures in `ToolValidationError`; `invoke()` validates first, then awaits a coroutine handler directly or runs a sync handler through `asyncio.to_thread`. `ToolMetadata.__post_init__` enforces `timeout > 0` and `max_output_chars >= 100`, and freezes `extra` into a `MappingProxyType`.

`ToolResult` is the single output carrier from the executor to the model: success, truncation, original char count, and error type all travel with it for both the model and observability layers.

### 2.3 Approval types (`approval.py`)

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

### 2.4 Sandbox types (`sandbox.py`)

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

## 3. Lifecycle

### 3.1 Decorator construction (definition time)

```
Function (typed annotations, optional defaults)
   │  @tool(name=..., namespace=..., timeout=..., ...)
   ▼
_argument_model: walk signature → reject *args/**kwargs → require annotations
   │              create_model(ConfigDict(extra="forbid")) → Pydantic argument model
   ▼
Tool(name, description, input_model, handler, ToolMetadata)
   │  provider_definition() → ToolDefinition(name, description, JSON Schema)
   ▼
registered into ToolRegistry (or register_lazy for deferred registration)
```

### 3.2 Registry lifecycle (runtime)

```
register / register_lazy
   │  check allowed_names scope (fnmatch) → check duplicates → take RLock
   ▼
loaded set _tools  /  deferred set _lazy
   │  load(name): loader() → verify a Tool whose qualified_name matches exactly → move to _tools
   │  disable(name) → _disabled set
   ▼
get(name): disabled → ToolError("disabled"); unknown → ToolError("unknown")
   ▼
unregister(name)  ←→  enable(name) / disable(name)
```

A lazy load must return a `Tool` whose **exact qualified name matches** (`qualified_name == name`) before it becomes visible; a mismatched return triggers `ToolError`. Any exception from the loader is wrapped into a `ToolError` with `details`.

### 3.3 Single tool-execution pipeline (execution time)

```
ToolCall(name, arguments, raw_arguments)
   │
   ▼ registry.get(name)                     unknown/disabled → failed ToolResult
   ▼ item.validate(arguments)               schema mismatch → ToolValidationError → failed ToolResult
   ▼ approval.require(ApprovalRequest)      not ALLOW → ApprovalDenied → failed ToolResult (no side effect)
   ▼ hooks.dispatch(PRE_TOOL_USE)           deniable; may rewrite arguments (re-validated)
   ▼ asyncio.wait_for(item.invoke(args), timeout)   timeout → TimeoutError → failed ToolResult
   ▼ stringify_output(value)                any return value → str
   ▼ truncate_output(output, max_output_chars)      head/tail truncation + metadata
   ▼ hooks.dispatch(POST_TOOL_USE)          may replace the result
   ▼
ToolResult(call_id, name, output, success, truncated, original_chars, error_type)
```

### 3.4 Agent multi-step tool loop (`runtime/thread.py`)

```
for step in 1..max_model_steps:
    provider.complete/stream(request with definitions)
    if response.tool_calls and tool_executor:
        append ASSISTANT Message(tool_calls=response.tool_calls)   # WAITING_TOOL
        if >1 call and all supports_parallel → asyncio.gather in parallel
        else execute sequentially
        for call, result: append TOOL Message(name, tool_call_id, result.output)
        continue                              # back to the model for the next batch or final answer
    else:
        turn.complete(response); done
```

`max_model_steps` is the **bounded model-step budget** (`Agent` defaults to 8, enforced `>= 1`). At runtime it guarantees the tool loop cannot run forever — every step either produces a final answer or ends when the budget is exhausted at the caller's discretion.

## 4. Key interfaces/classes

### 4.1 The `@tool` decorator (`definition.py`)

```python
@overload
def tool(function: ToolCallable, *, name=None, description=None, namespace=None,
         source="runtime", risk="low", timeout=30.0, max_output_chars=20_000,
         supports_parallel=False, deferred=False) -> Tool: ...

@overload
def tool(function: None = None, *, ... ) -> Callable[[ToolCallable], Tool]: ...
```

`_argument_model` dynamically builds a `{Name}Arguments` Pydantic model from the function signature via `create_model` with `ConfigDict(extra="forbid")` — extra arguments are rejected. `inspect.signature` plus `get_type_hints` require an annotation on every parameter; `*args` / `**kwargs` are explicitly rejected (`TypeError`).

### 4.2 `ToolRegistry` (`registry.py`)

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

- **Stable insertion order**: `list()` returns in insertion order; duplicate qualified names error explicitly ("already registered") and never silently replace the active implementation.
- **Scope lock**: `allowed_names` is matched with `fnmatchcase` (the `Agent` passes `tool_scopes` under persona). Registration/lazy registration first passes `_require_allowed`; out-of-scope names raise `ToolError("outside the registry scope")`.
- **Lazy-name validation**: `register_lazy` validates the qualified name against `[A-Za-z0-9][A-Za-z0-9_.-]{0,127}` and requires a non-empty description and a callable `loader`.
- **Search**: `search(query, load_deferred=True)` instantiates matching deferred tools; `discover` returns `(qualified_name, description, source, is_deferred)` tuples for listing without forcing a load.
- **definitions**: exports provider definitions; by default skips tools flagged `metadata.deferred`, includes them with `include_deferred=True`.

### 4.3 `ToolExecutor` (`executor.py`)

```python
class ToolExecutor:
    def __init__(self, registry: ToolRegistry, *, approval: ApprovalPolicy | None = None,
                 hooks: HookRegistry | None = None) -> None:
        self.registry = registry
        self.approval = approval or ApprovalPolicy.full_access()
        self.hooks = hooks
    async def execute(self, call: ToolCall) -> ToolResult: ...
```

`execute` implements the pipeline above. Key points: `registry.get` → `validate` → `approval.require` → `PRE_TOOL_USE` hook → `asyncio.wait_for(item.invoke(arguments), timeout=item.metadata.timeout)` → `stringify_output` → `truncate_output` → `POST_TOOL_USE` hook. A hook may rewrite arguments (which are **re-validated**) or replace the `ToolResult`.

### 4.4 `ApprovalPolicy` (`approval.py`)

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

`require` uses `default` when `callback is None`, otherwise calls `callback(request)`; if the callback returns an `Awaitable`, it is awaited. Anything other than `ALLOW` raises `ApprovalDenied` (with `correlation_id=call_id` and `details={"tool": ...}`).

### 4.5 `LocalSandbox` (`sandbox.py`)

```python
class LocalSandbox:
    workspace: Path
    mode: SandboxMode = SandboxMode.FULL_ACCESS
    environment_allowlist: tuple[str, ...] = (_default_environment_names())

    def __post_init__(self): ...           # workspace.resolve(strict=True) must be a directory
    @staticmethod
    def _within(path, root) -> bool: ...
    def resolve(self, path, *, write=False) -> Path: ...   # relative → under workspace; escape/read-only-write → SandboxError
    def process_environment(self, extra=None) -> dict[str, str]: ...
    def require_process_access(self) -> None: ...          # raises SandboxError unless FULL_ACCESS
    async def run_exec(self, argv, *, cwd=None, env=None) -> ProcessResult: ...
    async def run_shell(self, command, *, cwd=None, env=None) -> ProcessResult: ...
    @staticmethod
    async def terminate(process) -> None: ...
```

- **Path resolution happens before I/O**: `resolve` first calls `resolve(strict=False)` to get a canonical path, then checks it stays within `workspace`; `FULL_ACCESS` skips the escape check. `write=True` under `READ_ONLY` raises `SandboxError("read-only")`.
- **Process-group termination**: on Windows the child is created with `CREATE_NEW_PROCESS_GROUP` (0x00000200) and cancellation kills the tree with `taskkill /PID <pid> /T /F`; on POSIX it uses `start_new_session=True` and cancellation sends `os.killpg(pid, SIGKILL)`. The cancellation path shields the terminate task with `asyncio.shield`.
- **Environment allowlist**: `process_environment` copies only names in `environment_allowlist`, then applies `extra`.
- **shell/python require full access**: `require_process_access` denies anything below `FULL_ACCESS`, because path checks cannot constrain arbitrary child-process system calls.

### 4.6 `DockerSandbox` (`sandbox.py`)

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

`build_command` builds argv directly (no shell): `--rm --init --name <name> --network <net> --read-only --cap-drop ALL --security-opt no-new-privileges --pids-limit N --memory M --cpus C --tmpfs /tmp:rw,nosuid,nodev,size=64m --mount type=bind,src=<workspace>,dst=/workspace,{ro|rw} --workdir /workspace/<rel>`, plus read-only mounts and one `--env KEY` per allowlisted environment key, ending with the image and argv. **Environment values never enter argv** (only key names); values are injected through the host process environment. `__post_init__` validates the image reference, network name, resource limits, memory suffix (`[1-9][0-9]*[kKmMgG]`), and that mount targets are absolute safe paths. `run_exec` uses `asyncio.timeout(self.timeout)`; on timeout/cancellation it runs named-container cleanup `docker rm -f <name>` and terminates the process. `run_shell` translates to `("/bin/sh", "-lc", command)` and delegates to `run_exec`.

### 4.7 Built-in tools (`builtins.py`)

```python
def file_read_tool(sandbox) -> Tool      # name="file_read",  source="builtin", risk="low", supports_parallel=True
def file_write_tool(sandbox) -> Tool     # name="file_write", source="builtin", risk="write"
def file_search_tool(sandbox) -> Tool    # name="file_search", source="builtin", risk="low", supports_parallel=True
def shell_tool(sandbox) -> Tool          # name="shell", source="builtin", risk="process", timeout=60.0
def python_tool(sandbox) -> Tool         # name="python", source="builtin", risk="process", timeout=60.0
def basic_builtin_tools(workspace) -> tuple[Tool, ...]   # LocalSandbox(workspace) + the five above
```

File tools all resolve through `sandbox.resolve(...)` (with `write=True` for writes) before performing real I/O inside `asyncio.to_thread`; `shell` / `python` call `sandbox.run_shell` / `sandbox.run_exec` and therefore require the `FULL_ACCESS` local policy.

## 5. Concurrency/cancellation

- **Thread-safe registry**: `ToolRegistry` guards all mutable state with `threading.RLock`; tools passed at construction are registered inside `__init__`. Cross-thread register/lookup is safe.
- **Sync handlers**: `Tool.invoke` runs non-coroutine handlers via `asyncio.to_thread` so the event loop is never blocked; coroutine handlers are awaited directly.
- **Parallel tool calls**: `Thread` uses `asyncio.gather` when `len(tool_calls) > 1` and **every** tool has `metadata.supports_parallel == True`; otherwise it runs sequentially. An unknown tool makes the batch fall back to sequential (a caught `ToolError` sets `parallel=False`).
- **Cancellation semantics**: `ToolExecutor.execute` re-raises `asyncio.CancelledError` (it is not folded into a `ToolResult`), so task cancellation propagates to the caller and to subprocess cleanup. `LocalSandbox.run_exec/run_shell` shield `terminate` with `asyncio.shield` on `CancelledError`, finish process-group termination, then re-raise.
- **Time bounds**: `asyncio.wait_for(..., timeout=item.metadata.timeout)` provides per-tool timeouts; `TimeoutError` collapses into a failed `ToolResult` with `error_type="TimeoutError"`. `DockerSandbox.run_exec` uses `asyncio.timeout(self.timeout)`; both timeout and cancellation trigger container cleanup.

## 6. Neutral message storage

Tool calls and outputs are stored as **neutral `Message`s** in Thread history with no provider-specific shape. An `ASSISTANT` message carries `tool_calls: tuple[ToolCall, ...]`; a `TOOL` message carries `name` and `tool_call_id` plus `content` (the normalized `ToolResult.output`). The same history can then be translated by any provider:

- **Chat Completions** (`_message`): the assistant message's `tool_calls` serialize to `{"id", "type":"function", "function":{name, arguments:raw_arguments}}`; tool results become `role:"tool"` messages with `tool_call_id`.
- **Responses**: tool results become `{"type":"function_call_output", "call_id", "output"}`; the assistant's `tool_calls` become `{"type":"function_call", "call_id", "name", "arguments"}`.

A single `call_id` runs through the model call, events, result, and follow-up message, forming the unique join key.

## 7. Events/observability

### 7.1 Runtime events

`Thread` emits the following during the tool loop (the `Event` carries `thread_id`, `turn_id`, and `tool_call_id` fields):

- `tool.started` — before each call executes, payload `{name, arguments}`.
- `tool.completed` / `tool.failed` — after each call, payload `{result, success}`.
- Adjacent `model.completed` / `model.failed` events carry step, usage, tool_calls, and provider/model.

Events are subscribable via `Agent(observer=...)` (`EventObserver`) for observability and tracing.

### 7.2 Hooks

`ToolExecutor` dispatches two hook events around execution (via `HookRegistry`, see `hooks/`):

- `PRE_TOOL_USE` (**deniable**) — payload `{tool, call, arguments}`; `HookResult.deny(...)` makes execution return a failed `ToolResult` with `error_type="HookDenied"`; a handler with `allow_modify=True` can rewrite `arguments` (re-validated afterward).
- `POST_TOOL_USE` — payload `{tool, call, arguments, result}`; a handler can replace the final `ToolResult` via `HookResult.enrich(result=...)`.

Hook failure policies (success/denial/timeout/error) are set per registration and each emits a `HookTrace`.

### 7.3 Result observability

`ToolResult` carries `truncated`, `original_chars`, and `error_type` so diagnostics retain truncation/failure metadata without polluting model context.

## 8. Codex reference

This layer's behavioral contract, invariants, and design rationale are drawn from a reverse-engineering study of Codex's (Rust) tool stack; see [`docs/research/codex/tool-runtime-sandbox-approval.md`](https://github.com/Sitozzmonash/superharness/blob/main/docs/research/codex/tool-runtime-sandbox-approval.md). Files studied include `codex-rs/tools/src/tool_definition.rs`, `tool_executor.rs`, `tool_output.rs`, `json_schema.rs`, `codex-rs/core/src/tools/registry.rs`, `router.rs`, `orchestrator.rs`, `parallel.rs`, `sandboxing.rs`, `approvals.rs`, and `handlers/unified_exec.rs`.

**Behavioral contract** carried over to this layer:

- A tool keeps its name, description, input schema, execution handler, exposure, timeout, and risk metadata together.
- Registry insertion order is stable; duplicate or reserved names are rejected explicitly.
- A model tool call is normalized, resolved, validated, approved, executed under the selected sandbox policy, bounded, and converted into a model-facing result.
- Unknown tools and invalid arguments become explicit, model-observable failures.
- Cancellation aborts active execution; completed execution is not overwritten by a late cancellation.
- Large outputs are deliberately truncated before they re-enter model context, while diagnostics retain truncation metadata.

**Important invariants**: approval happens before side effects; validation failure never invokes the callable; one call ID links the model call, events, result, and follow-up message; a registry collision never silently changes the active implementation; filesystem paths are resolved and checked against explicit roots before access; local process execution is not described as a strong security boundary; tool failures are data for the model loop, while framework/cancellation failures remain typed exceptions.

## 9. Python-native redesign

Mapping the Codex Rust tool stack to a Python-native implementation:

- **`@tool` derives a Pydantic argument model and JSON Schema from a typed function signature**, replacing hand-written JSON Schema (`create_model` + `model_json_schema`).
- **`ToolRegistry`** owns deterministic registration, namespace, enable/disable, lookup, search, and provider definitions.
- **`ToolExecutor`** composes validation, `ApprovalPolicy`, timeout/cancellation, result normalization, truncation, and events.
- **`LocalSandbox`** resolves workspace paths and runs subprocesses with explicit cwd/environment, terminating process groups on cancellation.
- **The Agent runtime** repeats model → tool calls → tool results until a final answer or the step budget.
- **Neutral values**: `ToolDefinition` / `ToolCall` / `ToolResult` do not depend on Responses API item classes, OpenAI namespaces, hosted tools, account state, or Codex telemetry types.

## 10. Intentional differences

Deliberate simplifications/extensions relative to Codex:

- **Compact approval policy**: an allow/deny/callback `ApprovalPolicy` instead of Codex's UI-oriented reviewer and guardian layers. The decision enum has only `ALLOW` / `DENY`.
- **shell/python require full access**: the local `shell` and `python` built-ins require the `FULL_ACCESS` local policy because path checks cannot constrain arbitrary child-process behavior (a boundary Codex's local sandbox also concedes).
- **Deferred registration metadata**: `LazyTool` represents deferred registration metadata now; model-side dynamic tool search lands in the later ecosystem phase (this layer provides the `discover` / `search(load_deferred=True)` foundations).
- **No-side-effect guarantee on denial**: `deny_all` and callback denials return before the handler runs; tests explicitly verify `side_effects == []`.

## 11. Failure model

The exception hierarchy (`exceptions.py`) is rooted at `SuperHarnessError(message, *, correlation_id=None, details=None)`, with `details` frozen to a `MappingProxyType` (read-only diagnostics). Tool-layer exceptions:

- `ToolError(SuperHarnessError)` — register/lookup/load failures (duplicate, unknown, disabled, out-of-scope, lazy-load failure, invalid name).
- `ToolValidationError(ToolError)` — arguments do not satisfy the declared schema.
- `ApprovalDenied(SuperHarnessError)` — approval denial, carrying `correlation_id=call_id`.
- `SandboxError(SuperHarnessError)` — sandbox preparation or execution failure (escape, read-only write, process access denied, invalid argv, Docker resource limits, environment key not allowlisted, Docker executable unavailable).

**Executor failure-collapse rules** (`ToolExecutor.execute`):

| Condition | Returns / behavior |
|---|---|
| `asyncio.CancelledError` | re-raised (task cancellation is an exception, not data) |
| `TimeoutError` | failed `ToolResult`, `error_type="TimeoutError"` |
| `ApprovalDenied` / `ToolValidationError` / `ToolError` | failed `ToolResult`, `error_type=type(exc).__name__` |
| any other `Exception` | failed `ToolResult`, `error_type=type(exc).__name__`, message `"tool {name} failed: {exc}"` |

So **tool failures are data for the model** (observable and recoverable), while framework/cancellation failures remain typed exceptions that propagate to `Thread` and subprocess cleanup. `ApprovalDenied`, `ToolValidationError`, and `ToolError` can also be short-circuited at the hook stage (`HookDenied`) or rewritten.

## 12. Extension points

- **Custom tools**: decorate any annotated sync/async function with `@tool`; control the surface and metadata via `name`, `namespace`, `description`, `risk`, `timeout`, `max_output_chars`, `supports_parallel`, `deferred`, and `source`.
- **Lazy loading**: `register_lazy(name, description, loader)` registers lightweight metadata; the first `load`/`search(load_deferred=True)` instantiates it — suited to plugin/ecosystem boundaries.
- **Custom approval**: `ApprovalPolicy(default=..., callback=...)` with a sync or async callback that can decide arbitrarily on an `ApprovalRequest` (by tool, arguments, call_id).
- **Hook interception/rewriting**: register `PRE_TOOL_USE` (deny or rewrite arguments) and `POST_TOOL_USE` (replace the result) handlers for application policy and audit.
- **Custom sandbox backend**: model `LocalSandbox` / `DockerSandbox` and implement the same `run_exec` / `run_shell` / `resolve` surface; built-ins work through the injected `sandbox` object.
- **Built-in tool factories**: `basic_builtin_tools(workspace)` or individual factories such as `file_read_tool(sandbox)` compose into any registry.

## 13. Tests

- **`tests/test_tools.py`**:
  - Decorator schema generation and validation: `test_tool_decorator_builds_schema_and_validates` (qualified name, JSON Schema properties/required, default filling, invalid arguments raising `ToolValidationError`).
  - Annotation and variadic constraints: `test_tool_requires_annotations_and_rejects_variadic_parameters` (missing annotation, `*args` raise `TypeError`).
  - Registry conflicts/state/order/search/deferred visibility: `test_registry_conflicts_state_order_search_and_deferred_visibility` (duplicate registration, disable/enable, ordering, `search`, `definitions(include_deferred)`, unregister).
  - Executor validation/approval/timeout/truncation: `test_executor_validation_approval_timeout_and_truncation` (`deny_all` leaves `side_effects == []`, callback-ALLOW produces `truncated` and `original_chars`, `ToolValidationError`, `TimeoutError`).
  - Sandbox path policy: `test_sandbox_path_policy` (read-only write denied, escape denied, process access requires full_access).
  - Built-in file/process tools (`@pytest.mark.integration`): `test_builtin_file_and_process_tools`.
  - Process-cancellation termination: `test_process_cancellation_terminates_promptly` (`@pytest.mark.integration`, a `sleep(30)` child raises `CancelledError` within 5s of cancellation).
- **`tests/test_exceptions.py`**: `test_error_preserves_read_only_diagnostics` verifies `SuperHarnessError.details` is a read-only `MappingProxyType` (immutable after construction).
- Related hook/end-to-end coverage: `tests/test_hooks.py` verifies `PRE_TOOL_USE` denial and rewriting, `POST_TOOL_USE` dispatch, and event ordering.

## 14. Limitations/future work

- **Local sandbox is not strong isolation**: `LocalSandbox`'s class docstring states it is a "path-constrained local runner, not a strong security boundary" — path checks cannot constrain arbitrary subprocess system calls; `shell`/`python` are therefore restricted to `FULL_ACCESS`. For strong isolation use `DockerSandbox` or an external containerized runtime.
- **Approval is an in-process policy**: `ApprovalPolicy` is a sync/async-callback in-process decision with no persistent human approval queue or distributed reviewer layer.
- **Model-side dynamic tool search**: this layer already provides `discover` / `search(load_deferred=True)` and deferred registration metadata, but full dynamic discovery and selection by the model during a conversation lands in the later ecosystem phase.
- **Docker is a deployment prerequisite**: `DockerSandbox.available()` only probes for the `docker` executable and image; images are never pulled implicitly. When Docker or an image is missing, execution is skipped explicitly (as in `test_docker_run_if_available`), never auto-downloaded.
- **The step budget is a hard cap**: `max_model_steps` is a hard upper bound and does not distinguish "still making progress" from "spinning"; how to finish once the budget is exhausted is decided by the upper layer (`Thread`/caller).
- **No cross-process tool state**: the registry and executor are deterministic, single-process structures; recovering tool-call state across processes belongs to the persistence extensions and evolves with phases 3/8 recovery capabilities.

## Related links

- Runnable examples:
  - [`04_custom_tool_loop/main.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/04_custom_tool_loop/main.py) — full function-tool loop
  - [`05_approval_and_registry/main.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/05_approval_and_registry/main.py) — registry + callback approval
  - [`06_builtin_tools/main.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/06_builtin_tools/main.py) — built-in file and Python tools
  - [`66_dynamic_tool_registration.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/66_dynamic_tool_registration.py) — runtime register/unregister
  - [`67_lazy_tool_discovery.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/67_lazy_tool_discovery.py) / [`68_lazy_namespaced_tools.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/68_lazy_namespaced_tools.py) — deferred tool discovery/namespaces
  - [`69_docker_secure_command.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/69_docker_secure_command.py) / [`70_docker_allowlisted_environment.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/70_docker_allowlisted_environment.py) / [`71_docker_run_if_available.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/71_docker_run_if_available.py) — Docker sandbox
  - [`86_file_search_builtin.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/86_file_search_builtin.py) / [`87_local_sandbox_process.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/87_local_sandbox_process.py) — built-ins and local processes
  - [`88_approval_allow.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/88_approval_allow.py) / [`89_approval_deny_all.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/89_approval_deny_all.py) — approval allow/deny-all
  - [`41_hook_pre_tool_policy.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/41_hook_pre_tool_policy.py) / [`61_security_restricted_sandbox.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/61_security_restricted_sandbox.py) — tool hooks and the restricted sandbox
- Related Internals: model/streaming (Internals 1), Agent/Thread/Turn (Internals 2), plugins and hooks (Internals 6 related), Skills and MCP (Internals 5 related).
- Source: `src/super_harness/tools/`, `src/super_harness/models/types.py`, `src/super_harness/exceptions.py`, `src/super_harness/runtime/thread.py`.
- Research: `docs/research/codex/tool-runtime-sandbox-approval.md`.
