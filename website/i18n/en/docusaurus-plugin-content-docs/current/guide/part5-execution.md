---
id: guide-part5-execution
title: "User Guide Part V — Execution: Tools, Sandbox & Approval"
sidebar_position: 5
description: Complete usage of function tools (@tool) and the tool loop, dynamic tool registration, built-in file/shell/Python tools, local and Docker sandboxes, and approval policies.
---

# Part V — Execution: Tools, Sandbox & Approval

This is the execution part of the user guide. It covers every mechanism that lets an Agent actually "do things": function tools (exposing Python functions to the model), the runtime-driven tool loop, a tool registry (`ToolRegistry`) for dynamic registration and lazy loading while an application is running, out-of-the-box file/search/shell/Python built-in tools, local and Docker sandboxes that constrain what tools can read, write, and execute, and the approval/permission policy (`ApprovalPolicy`) applied before each execution.

## 1. What this is / when to use it

| Feature | What it is | When to use it |
| --- | --- | --- |
| Function tools (`@tool`) | Turns a type-annotated Python function into a model-visible, callable `Tool` | When the model must call business functions, APIs, databases, or any capability you own |
| Tool loop | `Agent`/`Thread` automatically runs "model requests → validate → approve → execute → feed result back → model continues" | When you want an end-to-end call-and-respond conversation and don't need per-step control |
| Dynamic tools (`ToolRegistry`) | Register/unregister/lazy-load tools at runtime; lazy entries publish metadata only, importing handlers when selected | Plugin systems, on-demand loading of heavy dependencies, extending capabilities at runtime |
| Built-in tools | Sandbox-aware file read/write/search, shell, and Python execution tools | When you need file and process capabilities quickly, without writing your own handlers |
| Sandbox | `LocalSandbox`/`DockerSandbox` unify workspace path policy and subprocess execution | When tools must be constrained in which paths they can read/write and which processes they can run |
| Approval | `ApprovalPolicy` gives ALLOW/DENY before every execution | High-risk write operations, production environments, human or application-level gatekeeping |

These mechanisms compose in layers: a `Tool` defines a capability, a `ToolRegistry` manages capabilities, a `ToolExecutor` handles validation/approval/timeout/execution/output bounding, an `Agent` wires the whole chain into the conversation loop, a `Sandbox` confines the file and process boundary, and an `ApprovalPolicy` gates each call. You can use a single piece (e.g. drive `ToolExecutor` directly, never touching a model) or chain everything together.

## 2. Prerequisites

- Python 3.11+, installed in editable mode with `pip install -e .`.
- When using model-driven conversations (`Agent.arun`/`run`), configure provider credentials; for DeepSeek, set `DEEPSEEK_API_KEY`.
- The pure execution path (registry + executor + sandbox) needs no model credentials at all — `examples/05_approval_and_registry` and `examples/06_builtin_tools` are of this kind.
- With `DockerSandbox`, a `docker` CLI must be available on PATH and the required image must already exist locally (the framework never pulls images implicitly).
- Example sources live in `examples/` at the repo root: the first nine (`01_`–`09_`) are directories with a `main.py`; the rest are single `.py` files.

## 3. Quick start

Shortest path: define a `@tool` function, pass it to `Agent(provider, tools=[...])`, and run.

```python
from super_harness import Agent, DeepSeekProvider, tool

@tool
def add(left: int, right: int) -> int:
    """Add two integers."""
    return left + right

agent = Agent(DeepSeekProvider(), tools=[add])
print(agent.run("Use add for 20 and 22.").text)
```

The runtime completes the whole tool loop automatically: the model sees `add`'s declaration (name, description, JSON Schema derived from the argument model) → the model returns a call with argument JSON → the runtime validates the arguments, executes the function, feeds the result back as a `tool`-role message → the model answers based on the result.

Without a model, a single call can be executed directly with `ToolExecutor`. A `ToolCall` has four fields: `call_id`, `name`, `arguments` (parsed dict), `raw_arguments` (raw JSON string):

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

`execute()` returns a `ToolResult`: success, timeout, or denial all come back as a structured result instead of an exception (see Section 13).

## 4. Configuration

### 4.1 Environment variables

| Variable | Purpose | Needed when |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | Credential for `DeepSeekProvider`, read at request time, never stored in events | Using the DeepSeek model to drive conversations |
| `SUPER_HARNESS_DOCKER_E2E` | Set to `1` to enable end-to-end tests against a real Docker daemon | Only when running tests that need real container isolation |

Tool execution itself reads no environment variables; credentials and sandbox environment handling belong to the provider and the sandbox respectively (see 4.4).

### 4.2 `@tool` decorator parameters

Besides the function itself, `@tool` accepts the following keyword arguments (all optional, all with defaults):

| Parameter | Default | Effect |
| --- | --- | --- |
| `name` | function name | Tool name shown to the model; must be non-empty |
| `description` | function docstring | Tool description the model uses to decide when to call; falls back to the tool name without a docstring |
| `namespace` | `None` | Namespace prefix; qualified name becomes `namespace.name` |
| `source` | `"runtime"` | Provenance label (e.g. `"builtin"`) used for source tracking; does not affect execution |
| `risk` | `"low"` | Risk-level label (e.g. `"write"`, `"process"`) for approval callbacks and policy |
| `timeout` | `30.0` | Per-call timeout in seconds; must be positive |
| `max_output_chars` | `20_000` | Output limit in characters (minimum 100); longer output is truncated and annotated |
| `supports_parallel` | `False` | When `True`, the tool may run concurrently with other parallel tools in the same model step |
| `deferred` | `False` | Marks the tool as a deferred-load artifact |

### 4.3 Execution-related `Agent` parameters

| Parameter | Default | Effect |
| --- | --- | --- |
| `tools` | `()` | Initial tool set (`Iterable[Tool]`), registered into the internal `ToolRegistry` |
| `approval` | `None` (equivalent to `full_access`) | Approval policy applied to every tool call |
| `hooks` | `None` | Hook registry; can observe/intercept `PRE_TOOL_USE` and `POST_TOOL_USE` |
| `max_model_steps` | `8` | Maximum model steps per turn-loop; exceeding it raises `ToolError` |

`Agent` holds a `ToolRegistry` and a `ToolExecutor` internally. Even when the registry is initially empty, the executor stays attached, so tools registered or discovered later are immediately executable — this is the foundation of dynamic tools.

### 4.4 Sandbox and approval configuration

`LocalSandbox`'s `mode` values are covered in Section 9; `environment_allowlist` controls which environment variables child processes see (defaults: `PATH`, `PATHEXT`, `SYSTEMROOT`, `WINDIR`, `COMSPEC`, `TEMP`, `TMP`, `TMPDIR`, `LANG`, `LC_ALL`).

`DockerSandbox` ships conservative defaults: no network (`network="none"`), read-only container root, all capabilities dropped, `no-new-privileges`, `cpus=1.0`, `memory="512m"`, `pids_limit=128`, per-run `timeout=60.0`, and `--rm` auto-cleanup.

`ApprovalPolicy`'s `default` decides behavior without a callback; `callback` receives an `ApprovalRequest` and returns an `ApprovalDecision` (details in Section 10).

## 5. Function tools: @tool and the Pydantic argument model

### 5.1 Behavior

The `@tool` decorator turns a function into an immutable `Tool` value. At decoration time it does four things:

- Derives a Pydantic argument model from the function signature: every type-annotated parameter becomes a model field; parameters with defaults become optional. The model is configured with `extra="forbid"`, so unknown arguments from the model are rejected.
- Every parameter must carry a type annotation or decoration raises `TypeError`; `*args` / `**kwargs` are rejected.
- Sync handlers run in a dedicated thread via `asyncio.to_thread` when invoked (never blocking the event loop); `async def` handlers are awaited directly.
- The resulting JSON Schema is exposed to the model via `Tool.provider_definition()`; on a call, `Tool.validate(arguments)` runs first (raising `ToolValidationError` with per-field errors on failure), then the handler executes.

Key `Tool` attributes: `name`, `description`, `input_model`, `handler`, `metadata` (`ToolMetadata`: `namespace`, `source`, `risk`, `timeout`, `max_output_chars`, `supports_parallel`, `deferred`, `extra`), and `qualified_name` (`namespace.name` when namespaced).

### 5.2 Basic example: define and run a weather tool

`examples/04_custom_tool_loop/main.py` shows the minimal full tool loop: define a `weather` tool with a typed return value, hand it to an `Agent`, ask the model to call it, and print the final answer.

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

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/04_custom_tool_loop/main.py)

Note the `await agent.aclose()` in the `finally` block: the runtime is natively async, and closing the Agent releases the resources it holds.

### 5.3 Real-world example: tool factories and batch execution

`examples/06_builtin_tools/main.py` shows another real shape: built-in tools are factory functions taking a sandbox and returning a `Tool`; several tools go into a `ToolRegistry` and a `ToolExecutor` executes each `ToolCall` one by one — no model involved. The argument model does type validation: `file_write` requires two string parameters, `path` and `content`.

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

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/06_builtin_tools/main.py)

The three executions yield three `ToolResult`s: the write returns `{"path": "...", "characters": 2}`, the read returns `"42"`, and the Python run returns a dict with `exit_code`/`stdout`/`stderr`.

### 5.4 Advanced/combined example: metadata-driven tool annotation

Tool metadata does not change execution semantics, but it is exposed to approval policies and observability. The following snippet (extracted from the `publish` tool in `examples/05_approval_and_registry/main.py`) shows `risk`, `name`, `timeout`, and `max_output_chars`, plus how to read `Tool` metadata:

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

`input_model.model_json_schema()` returns exactly the JSON Schema sent to the model with each request (`type: object` with a `message` string field). An approval callback can read `request.tool.metadata.risk` to decide whether high-risk tools pass; observability can use `metadata.source` to distinguish built-in tools from business tools.

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/05_approval_and_registry/main.py)

## 6. Tool loop and ToolExecutor

### 6.1 Behavior

`ToolExecutor.execute(call)` runs the full execution pipeline for a single call, in this fixed order:

1. `registry.get(call.name)` looks up the tool (unregistered or disabled tools come back as a `ToolResult`, see Section 13).
2. `item.validate(call.arguments)` validates against the Pydantic argument model; failure returns `error_type="ToolValidationError"`.
3. `approval.require(ApprovalRequest(...))` runs approval; denial returns `error_type="ApprovalDenied"`.
4. With hooks configured: `PRE_TOOL_USE` dispatch first (can deny, returning `error_type="HookDenied"`, or rewrite arguments), then `POST_TOOL_USE` after execution (can rewrite the result).
5. `await asyncio.wait_for(item.invoke(arguments), timeout=item.metadata.timeout)` executes with a timeout; sync handlers run in `to_thread`. Timeout returns `error_type="TimeoutError"`.
6. Output is normalized by `stringify_output` (strings pass through; `bytes` decode as UTF-8; `BaseModel`/dataclass serialize to JSON; otherwise `json.dumps`/`str` fallback), then truncated to `max_output_chars`; `truncated`/`original_chars` record the truncation state.

Inside the `Agent` conversation loop, this `execute` is chained automatically:

- Each model step emits `model.started` → text deltas `model.text.delta` → tool-call deltas `model.tool_call.delta` → `model.completed`.
- If the response contains `tool_calls`: emit `tool.started` per call; if there is more than one call and **every** target tool has `supports_parallel=True`, run them concurrently with `asyncio.gather`; otherwise run serially. Then each `ToolResult` is appended as a `tool`-role message, with `tool.completed` (success) / `tool.failed` (failure) emitted per call, and the loop moves to the next model step.
- The loop continues until the model returns a response with no tool calls, then emits `turn.completed`.
- If the turn is still running after `max_model_steps` (default 8) steps, it fails with `ToolError("tool loop exceeded maximum of ... model steps")`.

### 6.2 Basic example: direct execution without a model

`examples/05_approval_and_registry/main.py` uses no model: it chains the registry, executor, and an approval callback to execute one `publish` call. The `@tool(risk="write")` publishing tool is denied by the `review` callback (`DENY`), so the handler never runs:

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

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/05_approval_and_registry/main.py)

The output first shows the callback's review log `reviewing publish: {'message': 'hello'}`, then the `ToolResult`: `success=False`, `error_type="ApprovalDenied"`, `output` an explanation. Approval happens before the handler runs, so `published: hello` never appears.

### 6.3 Real-world example: event-stream driven tool loop

Every tool call in a conversational loop emits `tool.started` / `tool.completed` / `tool.failed` events. Through `agent.astream` the whole tool loop can be observed event by event (an extension of `examples/04_custom_tool_loop/main.py`):

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

Events are immutable: `event.type` is the string type, `event.payload` is a read-only mapping, and tool events also carry `tool_call_id`. `payload["result"]` on `tool.completed` / `tool.failed` is the `ToolResult` itself, so `output`, `success`, and `error_type` are directly readable.

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/04_custom_tool_loop/main.py)

### 6.4 Advanced/combined example: parallel tool calls

When multiple independent tools are marked `supports_parallel=True`, and the model requests them in the same reply, the runtime executes them concurrently with `asyncio.gather` (otherwise they degrade to serial). Async handlers pair naturally with the parallel flag:

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

The parallelism rule: more than one requested call in the step, and every target tool satisfying `metadata.supports_parallel == True`, triggers concurrency. The built-in `file_read` and `file_search` tools are shipped with `supports_parallel=True` (see the tool family built in `examples/06_builtin_tools/main.py`). Sync handlers marked parallel still run in the thread pool without blocking the event loop.

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/06_builtin_tools/main.py)

## 7. Dynamic tools: ToolRegistry and LazyTool

### 7.1 Behavior

`ToolRegistry` is a deterministic tool registry supporting add/remove while an application runs:

- `register(item)` / `unregister(name)`: register/unregister an already-loaded `Tool`; duplicate registration or unknown unregister raises `ToolError`.
- `register_lazy(name, description, loader, *, namespace=None, source="runtime")`: publishes "metadata + loader" without **importing** the handler. Returns a `LazyTool`. The name must match `[A-Za-z0-9][A-Za-z0-9_.-]{0,127}`; both description and loader are required.
- `load(name)`: performs one validated import, returns the `Tool`, and moves it into the loaded set; if the loader raises or returns a tool with a mismatched name, `load` raises `ToolError` and keeps the loader registered for explicit retry.
- `discover(query="")`: metadata-only matching, returns `(qualified_name, description, source, is_deferred)` tuples; `is_deferred=True` means the entry is not yet loaded.
- `search(query, *, load_deferred=False)`: case-insensitive substring match over **name or description**; with `load_deferred=True` the matching deferred entries are loaded too.
- `enable` / `disable` / `list` / `deferred()` / `get(name)`: activation, listing, lookup.
- `definitions(include_deferred=False)`: builds the `ToolDefinition` list sent to the model (deferred entries excluded by default, since they have no parameter schema).
- `allowed_names` (constructor): limits the registration scope — each entry name must match at least one fnmatch pattern, otherwise `ToolError("tool ... is outside the registry scope")`.

`Agent` registers its `tools` into the internal registry and keeps an executor attached permanently — so tools registered at runtime via `agent.tool_registry` are callable by the model in the next turn.

### 7.2 Basic example: register and unregister at runtime

`examples/66_dynamic_tool_registration.py` shows the most basic dynamism: register, invoke immediately, then unregister.

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

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/66_dynamic_tool_registration.py)

### 7.3 Real-world example: lazy loading

`examples/67_lazy_tool_discovery.py` demonstrates the plugin-style boundary: type information belongs to the plugin/application layer; registration publishes only metadata, and the handler is imported only after being selected.

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

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/67_lazy_tool_discovery.py)

`discover("weather")` returns `(('weather', 'Look up weather', 'demo', True),)` — `is_deferred=True` means the handler is not imported yet; after `load`, the entry becomes loaded and the flag flips to `False`.

### 7.4 Advanced/combined example: namespaces and deferred search

`examples/68_lazy_namespaced_tools.py` combines namespaces with `search(load_deferred=True)`: only deferred tools matching the name/description search are loaded.

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

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/68_lazy_namespaced_tools.py)

Two things to note: `register_lazy` with `namespace="ops"` makes the qualified name `ops.status`; `search("service", load_deferred=True)` matches "Service" in the description, triggering one `load`, and `matched[0]` is the loaded `Tool` ready for `invoke`. The loader must return a `Tool` whose qualified name matches the registered name, or `load` raises `ToolError("lazy tool loader returned a mismatched tool")`.

## 8. Built-in tools: files, search, shell, Python

### 8.1 Behavior

Built-in tools live in `super_harness.tools` (note: they are **not** exported from the top-level `super_harness` namespace; import them explicitly from `super_harness.tools`). All are factory functions taking a `LocalSandbox` and returning a `Tool`:

| Factory | Tool name | Parameters | Risk | Timeout | Behavior |
| --- | --- | --- | --- | --- | --- |
| `file_read_tool(sandbox)` | `file_read` | `path` | `low` | 30s | Reads one UTF-8 text file inside the workspace (`supports_parallel=True`) |
| `file_write_tool(sandbox)` | `file_write` | `path`, `content` | `write` | 30s | Writes a UTF-8 text file, creating parent directories; returns path and character count |
| `file_search_tool(sandbox)` | `file_search` | `pattern`, `path="."` | `low` | 30s | Finds workspace files by glob pattern; returns workspace-relative paths (`supports_parallel=True`) |
| `shell_tool(sandbox)` | `shell` | `command`, `cwd="."` | `process` | 60s | Runs a command via `sandbox.run_shell`; returns `exit_code`/`stdout`/`stderr` |
| `python_tool(sandbox)` | `python` | `code`, `cwd="."` | `process` | 60s | Runs code in a child process with the current interpreter (`sys.executable -c code`) |

`basic_builtin_tools(workspace)` is the convenience function creating all five at once: it builds a `LocalSandbox` around the directory and returns `tuple[Tool, ...]`, which can be spread straight into `Agent(tools=basic_builtin_tools(Path(...)))`.

All file built-ins resolve paths through the sandbox's `resolve()`: relative paths are anchored to the sandbox workspace; in restricted modes, escaping paths and write operations are rejected with `SandboxError`. `shell`/`python` are process-class tools and require `full_access`; otherwise `SandboxError` is raised ("local shell and Python processes require full_access...").

### 8.2 Basic example: file search

`examples/86_file_search_builtin.py`: write a file into the workspace, then search by pattern with `file_search_tool`.

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

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/86_file_search_builtin.py)

`file_search_tool(sandbox)` is a factory: pass a sandbox and you get the tool; `invoke` returns `["notes.txt"]` — the workspace-relative path list.

### 8.3 Real-world example: the one-liner five-pack wired into an Agent

`sandbox` plus `basic_builtin_tools` exposes file/search/shell/Python capabilities to the model in one line. A semi-automated project Agent usually pairs it with `ApprovalPolicy.full_access()` (or a custom policy) and a higher `max_model_steps`, because built-in action chains can be long:

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

`basic_builtin_tools(workspace)` constructs the sandbox and all five tools, letting the model orchestrate multi-step chains like "write file → search → read → execute" on its own. All file operations stay confined to the workspace directory.

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/06_builtin_tools/main.py)

### 8.4 Advanced/combined example: process tools under a restricted sandbox

The `shell` and `python` tools require `full_access`. Putting `shell_tool` into a `READ_ONLY` sandbox makes the call fail before execution — the same denial mechanism demonstrated in `examples/61_security_restricted_sandbox.py`:

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

The output is `denied: local shell and Python processes require full_access because the local runner is not a strong isolation boundary`. Through `ToolExecutor`, the same failure surfaces as a `ToolResult` with `success=False` and `error_type="SandboxError"` instead of an exception.

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/61_security_restricted_sandbox.py)

## 9. Sandbox: LocalSandbox and DockerSandbox

### 9.1 Behavior

`LocalSandbox(workspace, mode=..., environment_allowlist=...)` is a path-constrained local runner (the source docstring puts it plainly: "a path-constrained local runner, not a strong security boundary"). The three `SandboxMode` values:

| Mode | Path rules | Process rules |
| --- | --- | --- |
| `READ_ONLY` | Reads confined to the workspace; any write is rejected (`resolve(path, write=True)` raises `SandboxError`) | Forbidden: `require_process_access()` raises `SandboxError` |
| `WORKSPACE_WRITE` | Reads and writes confined to the workspace | Process execution forbidden |
| `FULL_ACCESS` | Paths unrestricted (`resolve` passes through) | `run_exec` / `run_shell` allowed |

`resolve(path, write=False)`: relative paths are joined to `workspace`; modes other than `FULL_ACCESS` run an escape check, raising `SandboxError` on escape (with `workspace` and `path` in `details`). `run_exec(argv, cwd=None, env=None)` launches a subprocess from an argv list (Windows uses `CREATE_NEW_PROCESS_GROUP`, POSIX uses `start_new_session`) and cleans up the process group on cancellation; `run_shell(command, ...)` goes through a shell string. Both return `ProcessResult(exit_code, stdout, stderr)`. Subprocess environments are built by `process_environment(extra)`: only allowlisted variables plus explicitly passed `extra`.

`DockerSandbox(workspace, image, mode=WORKSPACE_WRITE, ...)` is the Docker-CLI-based isolation backend for when "local process isolation is not enough". Defaults: `network="none"`, `--read-only` root, `--cap-drop ALL`, `--security-opt no-new-privileges`, `--pids-limit 128`, `--memory 512m`, `--cpus 1.0`, `--rm` auto-removal, plus a `--tmpfs /tmp`. Notable behaviors:

- `available()`: checks whether the `docker` executable exists (not whether the daemon answers).
- `build_command(argv, cwd=None, env=None, container_name=None)`: turns one execution into `(docker command list, process environment)` without starting a container — ideal for previewing and auditing.
- Every key in `env` must be present in `environment_allowlist`, or `SandboxError` is raised; environment values are passed via `--env KEY`, so values themselves never enter argv (no leakage into the process list).
- Images are never pulled implicitly; `cwd` must be inside the workspace (otherwise `SandboxError("Docker cwd escapes workspace")`).
- `run_exec` enforces `timeout` (default 60s); on timeout or cancellation it first `docker rm -f`'s the container, then terminates the process.
- `run_shell(command)` is equivalent to `run_exec(("/bin/sh", "-lc", command))`.

### 9.2 Basic example: local process execution

`examples/87_local_sandbox_process.py` is the minimal `run_exec` usage: start a Python subprocess inside a sandbox.

```python
"""Run an argv-based local process with cancellation-safe cleanup."""

import asyncio
import sys
from pathlib import Path

from super_harness import LocalSandbox

result = asyncio.run(LocalSandbox(Path.cwd()).run_exec((sys.executable, "-c", "print(6 * 7)")))
print(result.stdout.strip())
```

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/87_local_sandbox_process.py)

`LocalSandbox` defaults to `FULL_ACCESS`, so `run_exec` is permitted; the output is `42`. Note the argv list rather than a shell string (use `run_shell` when shell semantics are needed).

### 9.3 Real-world example: path and process denial in a read-only sandbox

`examples/61_security_restricted_sandbox.py` verifies, under `READ_ONLY`, all three denied operations and catches `SandboxError`:

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

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/61_security_restricted_sandbox.py)

The three denials correspond to: a write in read-only mode, a path escaping the workspace, and process access without `full_access`. `SandboxError.details` carries the path/workspace information needed to diagnose.

### 9.4 Advanced/combined example: DockerSandbox

`examples/71_docker_run_if_available.py` shows the production-grade Docker pattern: check the CLI and the local image first (the framework never pulls implicitly), then execute:

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

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/71_docker_run_if_available.py)

Two companion preview tools: `examples/69_docker_secure_command.py` prints the docker command it would run via `build_command` without starting a container; `examples/70_docker_allowlisted_environment.py` verifies environment forwarding by name only (values never enter argv):

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

The first prints the full `docker run --rm --init --network none --read-only --cap-drop ALL ...` command; the second prints `True True test` — `APP_MODE` appears as an `--env` key, its value `test` never hits the command line, and `environment["APP_MODE"]` is readable inside the container.

[View the complete runnable example 69](https://github.com/Sitozzmonash/superharness/blob/main/examples/69_docker_secure_command.py) · [View the complete runnable example 70](https://github.com/Sitozzmonash/superharness/blob/main/examples/70_docker_allowlisted_environment.py) · [View the complete runnable example 71](https://github.com/Sitozzmonash/superharness/blob/main/examples/71_docker_run_if_available.py)

## 10. Approval and permissions: ApprovalPolicy

### 10.1 Behavior

`ApprovalPolicy` is the permission boundary before execution. Constructor parameters: `default` (`ApprovalDecision.ALLOW` / `DENY`) and `callback` (sync or async, receiving an `ApprovalRequest` and returning an `ApprovalDecision`).

- `ApprovalPolicy.full_access()`: allow by default (`default=ALLOW`) — the default policy for `Agent`/`ToolExecutor`.
- `ApprovalPolicy.deny_all()`: deny everything (`default=DENY`).
- With `callback`: `require(request)` calls it; awaitable returns are awaited; any decision other than `ALLOW` raises `ApprovalDenied` (surfaced by `ToolExecutor` as a `ToolResult` with `error_type="ApprovalDenied"`).
- `ApprovalRequest` fields: `tool` (the `Tool`, including `metadata.risk`), `arguments` (the validated argument dict), `call_id`.

Approval runs after argument validation and before the handler executes; in `Agent` mode it applies to every tool call the model requests. Callbacks can decide on anything — tool name, risk level, argument content — e.g. "only low-risk tools", "writes must be confirmed by a human", "allow a specific namespace".

### 10.2 Basic example: deny everything

`examples/89_approval_deny_all.py`: the `deny_all()` policy guarantees the handler never runs (the tool would raise `RuntimeError` if it did).

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

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/89_approval_deny_all.py)

Output: `False ApprovalDenied`. Approval happens before the handler, so the `RuntimeError` is never triggered.

### 10.3 Real-world example: per-call approval

`examples/88_approval_allow.py`: the callback explicitly returns `ALLOW`, passing reviewed calls (e.g. writes confirmed by a human). The callback can inspect `request.tool.qualified_name` and `request.arguments` for fine-grained decisions.

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

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/88_approval_allow.py)

Output: `ToolResult(call_id='1', name='save', output='saved:draft', success=True, ...)`.

### 10.4 Advanced/combined example: async callbacks and argument-based decisions

Callbacks may be `async def` (`ApprovalPolicy.require` awaits them automatically), which suits external audit services or human-confirmation queues. The policy below decides on the argument content: empty `value` is denied, otherwise allowed (the link points to the fully runnable `examples/05_approval_and_registry/main.py`, which demonstrates the same callback mechanism in its sync form):

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

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/05_approval_and_registry/main.py)

`request.arguments` are the **validated** arguments (the output of `Tool.validate`), so fields read in the callback are guaranteed to fit the argument model; `request.tool.metadata.risk` can route `risk="write"` and `risk="process"` tools to human approval channels.

## 11. API quick reference

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

## 12. Events and streaming

Tool execution is visible as events in `agent.astream` / `thread.astream` (all immutable `Event`s, `payload` is a read-only mapping):

| Event type | When emitted | Key payload fields |
| --- | --- | --- |
| `tool.started` | Requested by the model, per call before execution | `name`, `arguments`; `tool_call_id` |
| `tool.completed` | A single call succeeded | `result` (the `ToolResult`), `success=True` |
| `tool.failed` | A single call failed (denied, timed out, etc.) | `result` with `error_type`, `success=False` |
| `model.tool_call.delta` | Model streams a tool-call argument fragment | `index`, `name`, `delta`, `step` |
| `model.started` / `model.completed` | Start/end of each model step | `provider`, `model`, `step`, `usage`, `tool_calls` |
| `turn.started` / `turn.completed` / `turn.failed` | Whole-turn start/success/failure | `turn_id`, `response` or `error_type` |

Parallel calls each emit their own `tool.started`/`tool.completed` (sharing one `turn_id`); ordering across them is not guaranteed to match the model's request order. Every event carries `event_id`, `timestamp` (timezone-aware), `thread_id`, `turn_id`, and tool events additionally carry `tool_call_id`. `thread.astream` consumption is identical to `agent.astream` (see 6.3).

## 13. Errors, timeouts, and retries

`ToolExecutor.execute` almost never raises — failures are normalized into a `ToolResult` with `success=False` and an `error_type` label:

| `error_type` | Meaning |
| --- | --- |
| `TimeoutError` | Handler did not return within `metadata.timeout` (default 30s) |
| `ApprovalDenied` | The approval policy denied the call |
| `ToolValidationError` | Arguments do not fit the Pydantic argument model (including extra/unknown parameters) |
| `ToolError` | Registry lookup failure, unregistered/disabled tool, lazy-load failure, loop cap reached, etc. |
| `HookDenied` | A `PRE_TOOL_USE` hook denied the call |
| Other class names (e.g. `SandboxError`, `ValueError`, any handler exception class) | Exception type raised by the handler or sandbox |

Other points:

- Output bounding: `max_output_chars` (default 20_000). Beyond it, `truncated=True` and `original_chars` record the original length; the content keeps head and tail with a `... truncated N characters ...` marker in between, keeping giant output from polluting context.
- Cancellation propagation: `asyncio.CancelledError` is never swallowed and propagates upward; `LocalSandbox`/`DockerSandbox` clean up subprocesses/containers before re-raising.
- Loop cap: a turn exceeding `max_model_steps` (default 8) tool-loop steps fails with `ToolError("tool loop exceeded maximum of N model steps")` (`turn.failed` event + exception).
- Registration failures: duplicate registration, unknown unregister, registration outside `allowed_names`, or invalid lazy names all raise `ToolError`.
- Sandbox failures: path escape / read-only write / restricted process access / invalid Docker parameters raise `SandboxError` (converted to a `ToolResult` under the executor).
- Retries: the pipeline never auto-retries tools (retrying a denied call is pointless). For retry scenarios: raise `timeout=` for slow tools, raise `max_model_steps=` so the model can retry, or implement application-level retry around `execute`.

## 14. Combining with other features

- **Hooks**: a `HookRegistry` can be configured on `Agent(tools=..., hooks=...)` / `ToolExecutor(..., hooks=...)`; `PRE_TOOL_USE` can deny or rewrite arguments, `POST_TOOL_USE` can rewrite results. Hooks complement approval and observability but never replace the sandbox.
- **Workflow / hybrid orchestration**: deterministic `Workflow` node handlers can call a `ToolExecutor`; sub-agents spawned by `agent_node` bring their own collaboration tools.
- **Multi-agent**: `AgentManager` automatically attaches `spawn_agent`, `send_input`, `wait_agent`, `resume_agent`, `interrupt_agent`, and `close_agent` tools to root and child agents; use `expose_tools=False` for application-only control.
- **Persona**: `persona.select_tools(...)` filters the `Agent` tool set with `tool_scopes` fnmatch rules, enforced via `ToolRegistry(allowed_names=...)`.
- **Observability**: injecting `Observability(observer)` into the Agent surfaces tool calls as normalized events in tracing; `ToolResult` fields (including `error_type`, `truncated`) ride along.
- **CLI**: `super-harness doctor` diagnoses provider/configuration; tools themselves have no CLI subcommand and are used through the Python API.

## 15. Security notes

- `LocalSandbox` enforces **path policy only** — it is not OS/network isolation. `full_access` allows every path and subprocess execution and should only run in trusted environments.
- Keep untrusted code/input behind `DockerSandbox` (no network by default, read-only root, dropped capabilities, resource limits) or a container/VM.
- Process-class built-in tools (`shell`, `python`) require `full_access` — they are rejected in restricted sandboxes; that is expected behavior.
- The default approval policy is `full_access`. Production should configure at least `deny_all` or an `ApprovalPolicy` with a callback so that write-/process-class high-risk tools (via the `risk` metadata) pass human or application confirmation.
- `DockerSandbox` forwards environment variables by allowlisted name only, with values never in argv; images are never pulled implicitly, avoiding supply-chain surprise.
- Tool output is bounded and truncation-marked, preventing long-output injection or context overflow; raw model argument JSON is also length-limited (`ToolCall.raw_arguments` cap of one million characters).

## 16. Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `ToolError: tool 'x' is already registered` | Duplicate tool name. Check namespaces or `unregister` first. |
| `ToolError: tool 'x' is outside the registry scope` | The registry has `allowed_names` (e.g. a Persona's tool_scopes) and the name matches no fnmatch pattern. |
| `ToolError: tool 'x' is disabled` / `unknown tool 'x'` | The tool is `disable`d, never registered, or already unregistered. |
| `ToolError: lazy tool 'x' failed to load` | The loader raised; `load` keeps the loader, so fix and retry explicitly. |
| `ToolError: lazy tool loader returned a mismatched tool` | The loader returned a `Tool` whose `qualified_name` differs from the registered name (including namespace prefix). |
| `error_type="ToolValidationError"` | Model arguments do not fit the argument model; check that annotations exist and no `*args`/`**kwargs` broke decoration. |
| `error_type="TimeoutError"` | Execution exceeded `timeout`; raise `@tool(timeout=...)` for long tasks. |
| `error_type="ApprovalDenied"` | The approval policy denied the call; check the `ApprovalPolicy` config or callback logic. |
| `SandboxError: path escapes sandbox workspace` | A relative path resolved outside the workspace; the tool used an absolute path or `..` escape under a restricted sandbox. |
| `SandboxError: sandbox is read-only` | A write was attempted under `READ_ONLY`. |
| `SandboxError: local shell and Python processes require full_access...` | `shell`/`python` tools or `run_exec`/`run_shell` used under a non-`full_access` sandbox; confirm process capability is really needed. |
| The model never calls a tool | Check the tool's `description` and argument model; confirm the tool is registered, not denied by approval, and visible in `discover`/`definitions`. |
| Tool parallelism not happening | Parallelism requires >1 calls in the step and every target tool with `supports_parallel=True`. |
| `ToolError: tool loop exceeded maximum of N model steps` | The tool chain is too long or the model keeps requesting tools without converging; raise `max_model_steps` or simplify instructions. |
| `DockerSandbox` execution fails | Preview with `sandbox.available()` and `sandbox.build_command(...)`; confirm the image exists locally (no implicit pulls); confirm every `env` key is in `environment_allowlist`. |

## 17. Links

**Runnable examples (examples/)**

- [04_custom_tool_loop/main.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/04_custom_tool_loop/main.py) — a complete function-tool loop
- [05_approval_and_registry/main.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/05_approval_and_registry/main.py) — registry + approval callback + executor
- [06_builtin_tools/main.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/06_builtin_tools/main.py) — sandbox-aware file/Python built-ins
- [61_security_restricted_sandbox.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/61_security_restricted_sandbox.py) — path/process denial in a restricted sandbox
- [66_dynamic_tool_registration.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/66_dynamic_tool_registration.py) — runtime register/unregister
- [67_lazy_tool_discovery.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/67_lazy_tool_discovery.py) — lazy loading and discover
- [68_lazy_namespaced_tools.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/68_lazy_namespaced_tools.py) — namespaces + deferred search
- [69_docker_secure_command.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/69_docker_secure_command.py) — inspect the Docker command
- [70_docker_allowlisted_environment.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/70_docker_allowlisted_environment.py) — Docker environment allowlist
- [71_docker_run_if_available.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/71_docker_run_if_available.py) — Docker availability check and run
- [86_file_search_builtin.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/86_file_search_builtin.py) — built-in file search
- [87_local_sandbox_process.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/87_local_sandbox_process.py) — local process execution
- [88_approval_allow.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/88_approval_allow.py) — approval allow
- [89_approval_deny_all.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/89_approval_deny_all.py) — approval deny-all

**Related docs**

- User Guide Parts I–IV (Agent, Thread, context and instructions)
- API reference (`super_harness.tools` / `super_harness.models` / `super_harness.exceptions`)
- Internals: the tool runtime (`src/super_harness/tools/`)