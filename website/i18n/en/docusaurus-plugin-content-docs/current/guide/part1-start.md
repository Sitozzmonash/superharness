---
id: guide-part1-start
title: User Guide Part I — Start
sidebar_position: 1
description: Installation, five-minute quick start, project layout, configuration and .env, your first Agent, sync vs async.
---

# Part I — Start

This page covers the first part of the Super Harness user guide: what it is, how to install it, how to get a first Agent running in a minute, which directories appear in a project, how configuration files and environment variables control behaviour, and how the synchronous and asynchronous APIs differ. Later parts (Threads, Tools, Context, MCP, multi-Agent, Workflow, and so on) are covered in their own pages.

## 1. What is this / When to use

Super Harness is a **Python-native, Codex-inspired, provider-agnostic agent runtime**. It splits the "conversational agent" concept into a three-layer model:

- **Agent**: a configured entry point holding a provider, system instructions, a tool registry, an approval policy, and an optional persistence store. The `Agent` itself carries no conversation; it creates independent `Thread` objects.
- **Thread**: an ordered conversation history with a collection of turns. `agent.run(...)` opens a brand-new Thread for every call; for continuous conversation, create `agent.thread()` explicitly and call `thread.run(...)` on it repeatedly.
- **Turn**: one model interaction loop inside a Thread, which may include several "model → tool → model" steps (`max_model_steps`, default 8).

The design goal is a programming model decoupled from any specific cloud vendor: the default provider is DeepSeek (directly reachable from mainland China), and any OpenAI-compatible endpoint is supported; search, vision, and RAG are plugged in through external adapters. You can build coding assistants, research pipelines, enterprise knowledge Q&A, automation scripts, and applications in autonomous, deterministic, or hybrid orchestration modes.

**When to use this page**: you are new to Super Harness; you need to install and verify the environment on your machine; you want to understand what each directory/file in a project does; you want to switch between environments with config files and environment variables; or you are unsure whether to use `run` or `arun`.

## 2. Prerequisites

- **Python 3.11+**. The project declares `requires-python = ">=3.11"` in `pyproject.toml` and is validated against 3.11 in CI and pyright configuration. On Windows, use the official installer or `uv` to manage the interpreter.
- **pip** or **uv** for installing the package and its dependencies.
- **A usable model provider credential**. The default `DeepSeekProvider` reads the `DEEPSEEK_API_KEY` environment variable at request time. Without a credential, `agent.run(...)` raises `ModelError` with `missing credential for provider deepseek: set DEEPSEEK_API_KEY`.
- **git** (optional but recommended): project location discovery (`.git` root detection), `AGENTS.md` context loading, and the `super-harness doctor` diagnostics all use git.
- **Network reachability**: the default DeepSeek endpoint is `https://api.deepseek.com`; OpenAI-compatible providers need their own `base_url`.

:::info About when credentials are read
Credentials are read from the named environment variable at **every request** (see "Configuration" below); they are not cached on the Agent or in events, and never appear in diagnostics. This is also why commands such as `super-harness provider test` take secrets from an environment variable rather than from arguments.
:::

## 3. Installation

Install the development version from the repository root (the directory containing `pyproject.toml`):

```bash
python -m venv .venv
# Windows (git-bash / PowerShell):
# .venv/Scripts/activate
# Linux / macOS:
# source .venv/bin/activate
python -m pip install -e ".[dev]"
```

- `-e` (editable) installation makes changes under `src/super_harness` take effect immediately; no reinstall is needed while developing.
- `[dev]` additionally installs `build`, `hatchling`, `pyright`, `pytest`, `pytest-asyncio`, and `ruff` for development and validation.
- The runtime has only five required dependencies: `httpx`, `mcp`, `packaging`, `pydantic`, and `pyyaml`.
- Optional feature: OpenTelemetry tracing requires `pip install -e ".[otel]"`.

After installation the `super-harness` console script becomes available. Run a fully offline environment diagnostic first:

```bash
super-harness doctor
```

`doctor` does not touch the network; it checks the Python version, git, state-root writability, Docker and its daemon, the MCP SDK, OpenTelemetry, whether `DEEPSEEK_API_KEY` is configured, config-file resolution results, the MCP configuration, and the Thread store. Each item reports `pass` or `warn`.

:::info Verifying the installation
```python
from super_harness import Agent, ConfigResolver, DeepSeekProvider
print(Agent, ConfigResolver, DeepSeekProvider)
```
A successful import means the package is in place. If the console script is missing, verify manually with `python -c "from super_harness.cli import main"`.
:::

## 4. Five-Minute Quick Start

### 4.1 Set the credential

Put the DeepSeek key into the environment:

```bash
export DEEPSEEK_API_KEY   # bash: set your key here
# PowerShell: set the env var via $env:DEEPSEEK_API_KEY
```

### 4.2 Run your first Agent

`examples/01_basic_agent/main.py` is the minimal runnable synchronous example, quoted verbatim:

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

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/01_basic_agent/main.py)

Run it:

```bash
python examples/01_basic_agent/main.py
```

You will see a one-sentence answer. `response` is an immutable `ModelResponse`; `.text` is the final normalized text, `.usage` carries token usage (`input_tokens` / `output_tokens` / `total_tokens`), and `.tool_calls` / `.output_json` correspond to tool calls and structured output respectively (used later on this page).

### 4.3 Verify configuration resolution

Run the configuration diagnostics to see the currently resolved profile, model, and config sources:

```bash
super-harness doctor --json
```

The `configuration` entry in the JSON output lists the resolved `profile`, `model_provider`, `model`, `sandbox_backend`, `sandbox_mode`, `sources` (matched config file paths), `environment_overrides` (keys overridden by environment variables), and `dotenv` (whether a `.env` file was loaded).

### 4.4 Verify provider connectivity (requires network and a key)

```bash
super-harness provider test --provider deepseek
```

This sends a minimal request to DeepSeek (default prompt `Reply with exactly: OK`) and prints `provider`, `model`, `response`, and `usage`. Note it connects with `max_retries=0` so configuration problems surface quickly.

:::tip Already at 5 minutes?
Completing the four steps above means: the package is installed, the environment is diagnosed, an Agent can talk, and both config resolution and provider connectivity are verified. Next comes directory layout and configuration, so you can manage environment differences.
:::

## 5. Project Layout

A typical project using Super Harness looks like this:

```text
my-project/
├── .git/                      # git root; configuration anchoring starts here
├── .env                       # optional; read only when load_dotenv=True
├── .super-harness/
│   ├── config.toml            # project-level config (config.yaml / config.yml also supported)
│   ├── state.db               # default SQLite Thread persistence path (PersistenceConfig.path)
│   ├── mcp.json               # MCP server configuration managed by the CLI (MCPConfigStore)
│   ├── skills/                # SkillInstaller target directory
│   ├── plugins/               # PluginInstaller target directory
│   └── mcp-bundles/           # .mcpb installation artifacts
├── AGENTS.md                  # optional; project instructions, auto-loaded with Agent(cwd=...)
├── src/                       # your application code
└── examples/                  # 91 official runnable examples (01_…–91_…)
```

How paths relate to CLI scope:

- **Project scope (default)**: all local state lives under `<git-root>/.super-harness/`. CLI commands use project scope by default.
- **User scope**: prefix the command with `--global` (e.g. `super-harness --global doctor`); state lands in the user installation root (`~/.super-harness/`, resolved by `CLIPaths`).
- **User config file**: `ConfigResolver` defaults to `~/.super-harness/config.toml`, overridable via `ConfigResolver(user_config=...)` (examples 78/79 pass `missing.toml` that way to skip the user layer).

### When AGENTS.md takes effect

`Agent(..., cwd="...")` looks for an `AGENTS.override.md` or `AGENTS.md` from the nearest `.git` root down to (and including) the cwd, **never above the cwd**, under a default total context cap of 32 KiB. That is covered in detail in the Context part; for this page it is enough to know: place an `AGENTS.md` at the project root and create `Agent(provider, cwd=".")` and it will be injected as developer instructions automatically.

## 6. Configuration and .env

The end point of configuration is a frozen `HarnessConfig` (a pydantic model with `extra="forbid"`). Every source is merged into it, and subsystems and the `Agent` then consume it.

### 6.1 Precedence: defaults → user → project → env → runtime

The `ConfigResolver` resolution order is stated in the source as `Resolve defaults < user < project < environment < runtime`; each later layer overrides the earlier one:

1. **Defaults**: `HarnessConfig` field defaults plus the presets of the selected profile (see 6.4).
2. **User config**: `~/.super-harness/config.toml` (or the file passed to `ConfigResolver(user_config=...)`).
3. **Project config**: `<project>/.super-harness/config.toml` / `config.yaml` / `config.yml`, found from the `.git` root.
4. **Environment**: the `SUPER_HARNESS_*` family (see the table in 6.3).
5. **Runtime override**: nested dict passed to `resolve(runtime={...})`, highest priority.

`examples/79_config_precedence.py` uses a temporary directory to show environment and runtime precedence over a project file, quoted verbatim:

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

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/79_config_precedence.py)

The output is `runtime`: the project file's `"project"` is overridden by `SUPER_HARNESS_MODEL=environment`, whose `"environment"` is in turn overridden by `runtime={"model": {"model": "runtime"}}`. Remove the `runtime=` argument and rerun and the output becomes `environment`; remove `environment=` too and it becomes `project`.

Beyond the CLI, the `configuration` entry of `doctor --json` is `ResolvedConfig.diagnostics()`:

```python
resolved = ConfigResolver(user_config="missing.toml").resolve(
    environment={"SUPER_HARNESS_PROFILE": "offline"}
)
print(resolved.diagnostics())
```

`diagnostics()` returns `profile`, `model_provider`, `model`, `sandbox_backend`, `sandbox_mode`, `sources` (list of source file paths), `environment_overrides` (list of env var names in use), and `dotenv`. Note: **it lists only source paths and overridden variable names, never secret values**. The code above is the body of `examples/78_config_profiles.py` (quoted verbatim):

```python
"""Resolve a built-in credential-free profile."""

from super_harness import ConfigResolver

resolved = ConfigResolver(user_config="missing.toml").resolve(
    environment={"SUPER_HARNESS_PROFILE": "offline"}
)
print(resolved.diagnostics())
```

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/78_config_profiles.py)

### 6.2 Config file formats

`ConfigResolver` accepts both TOML and YAML: `.super-harness/config.toml`, `config.yaml`, or `config.yml`. Keys mirror the nested fields of `HarnessConfig`:

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

The YAML equivalent:

```yaml
# .super-harness/config.yaml
profile: china
model:
  provider: deepseek
  model: deepseek-v4-flash
```

Any unknown key triggers `ConfigError` at `resolve()` time (`extra="forbid"`) with pydantic validation details in `details.errors`. Unreadable files or TOML/YAML parse failures also raise `ConfigError` ("unable to read configuration" / "configuration root must be an object" / "invalid .env assignment").

### 6.3 `SUPER_HARNESS_*` environment variable table

| Environment variable | Config key | Default | Description |
| --- | --- | --- | --- |
| `SUPER_HARNESS_PROFILE` | `profile` | `china` | Built-in profile: `china` / `global` / `offline` / `test` |
| `SUPER_HARNESS_MODEL_PROVIDER` | `model.provider` | `deepseek` | Text model provider |
| `SUPER_HARNESS_MODEL` | `model.model` | `deepseek-v4-flash` | Text model name |
| `SUPER_HARNESS_VISION_PROVIDER` | `vision.provider` | `zhipu` | Vision model provider |
| `SUPER_HARNESS_VISION_MODEL` | `vision.model` | `glm-4v-flash` | Vision model name |
| `SUPER_HARNESS_SEARCH_PROVIDER` | `web_search.provider` | `zhipu` | Web search provider |
| `SUPER_HARNESS_SANDBOX_BACKEND` | `sandbox.backend` | `local` | Sandbox backend (`local` / `docker`) |
| `SUPER_HARNESS_SANDBOX_MODE` | `sandbox.mode` | `workspace_write` | Sandbox access mode |
| `SUPER_HARNESS_APPROVAL_MODE` | `approval.mode` | `full_access` | Approval mode |

Keys overridden by the environment appear in `diagnostics()["environment_overrides"]`, making it easy to audit "which settings currently come from the environment".

### 6.4 Built-in profiles: china / global / offline / test

The `ProfileName` enum defines four built-in composition profiles; `_profile_value` takes the first `profile` key found in runtime → env → project → user order, falling back to `china`:

| Profile | Effect |
| --- | --- |
| `china` (default) | Keeps `HarnessConfig` defaults: DeepSeek text model plus Zhipu vision/search. |
| `global` | `model.provider=openai_compatible`, `model.model=gpt-5`; `vision` also switches to OpenAI-compatible. |
| `offline` | `model.provider=offline` (local/deterministic), `web_search.provider=disabled`, `sandbox.mode=read_only`; suited to no-network environments. |
| `test` | `model.provider=test` (deterministic model), `web_search.provider=test`, `persistence.path=":memory:"`; suited to tests and CI. |

Profile values are case-insensitive and a `-dev` suffix is stripped (`china-dev` → `china`). Unknown values raise `ConfigError("unknown configuration profile ...")`.

### 6.5 `.env` loading: off by default

`.env` loading is **disabled by default**, and it **never modifies `os.environ`**. Only when `load_dotenv=True` is passed explicitly does `resolve()` read `<project>/.env`:

```python
from super_harness import ConfigResolver

resolved = ConfigResolver().resolve(load_dotenv=True)
print(resolved.dotenv)   # e.g. <project>/.env
```

Semantics (different from `python-dotenv`, note carefully):

- `.env` values are merged into the environment snapshot with `setdefault`: **real environment variables already present win**; `.env` never overrides them.
- Parse errors (lines that are not `KEY=value`, or invalid keys such as `API KEY=...`) raise `ConfigError` with a line number.
- The file still only affects "this resolution"; `os.environ` itself is untouched.
- `ResolvedConfig.dotenv` records the actually loaded `.env` path, or `None` when none was loaded.

### 6.6 Credentials and SecretProvider

Configuration picks *what*; credentials are resolved through separate `SecretProvider`s so diagnostics and logs never expose them. `SecretValue`'s `str` and `repr` always render as `********`; only an explicit `.reveal()` returns the raw value (for example at the real provider boundary).

`examples/80_secret_providers.py` demonstrates the three-layer composition, quoted verbatim:

```python
"""Resolve secrets explicitly while keeping diagnostics masked."""

from super_harness import CompositeSecretProvider, EnvironmentSecretProvider, MappingSecretProvider

secrets = CompositeSecretProvider(
    (EnvironmentSecretProvider({}), MappingSecretProvider({"SERVICE_TOKEN": "demo-secret"}))
)
token = secrets.get("SERVICE_TOKEN")
print(token, token.reveal() == "demo-secret" if token else False)
```

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/80_secret_providers.py)

- `EnvironmentSecretProvider`: reads from `os.environ` (or a passed-in mapping) by name.
- `MappingSecretProvider`: reads from a static mapping (for tests/demos).
- `CompositeSecretProvider`: tries each child provider in order and returns the first hit.
- All three implement the `SecretProvider.get(name) -> SecretValue | None` protocol; `None` means not found.

## 7. Your First Agent

The full `Agent` constructor signature (`src/super_harness/agent.py`):

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

The first parameter is the positional `provider`; everything else is keyword-only. `provider` only needs to satisfy the `ModelProvider` protocol: `name`, `capabilities`, `complete(request)`, `stream(request)`, `aclose()`. That means you can:

- Use the ready-made `DeepSeekProvider()`;
- Use `OpenAICompatibleProvider(model=..., base_url=..., api_key_env=...)` to reach any OpenAI-compatible endpoint;
- Implement your own local/deterministic provider (the 22-line `LocalProvider` in `examples/07_durable_thread/main.py` is a minimal example; Part II covers it).

**`instructions` are developer-authoritative**: in every turn's request they are placed at the front of the context with the `developer` role (DeepSeek's native API rejects the `developer` role, and `DeepSeekProvider._message` maps it to `system` automatically). `Agent(provider, instructions="...")` is equivalent to giving every conversation a fixed preamble.

### Agent vs Thread

- `agent.run(input)` / `agent.arun(input)`: convenience methods equivalent to `agent.thread().run(input)` — **every call opens a brand-new Thread**; no history is shared.
- For multi-turn conversation: `thread = agent.thread()`, then call `thread.run(...)` repeatedly; messages accumulate in the same Thread.
- `agent.resume(thread_id)` / `agent.fork(thread_id)` require a `store` (`SQLiteThreadStore`) and belong to the persistence part; not expanded here.

## 8. Sync vs Async

The runtime is **natively asynchronous**: all model I/O is coroutine-based. The synchronous API is implemented by wrapping the async generator in `asyncio.run` behind a collector, *only when no event loop is running* (`_sync` in `thread.py`).

### 8.1 Four entry points for the same operations

| Sync | Async | Returns |
| --- | --- | --- |
| `agent.run(input)` | `await agent.arun(input)` | `ModelResponse` (final normalized result) |
| `agent.stream(input)` | `async for ... in agent.astream(input)` | `Event` (immutable event stream) |

The `thread` object exposes the same names: `thread.run` / `thread.arun` / `thread.stream` / `thread.astream`.

### 8.2 The rule: never call the sync API inside an active event loop

The `_sync` implementation is:

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

In other words:

- In an ordinary script with **no** event loop, `agent.run(...)` works fine.
- Inside a coroutine where an event loop **is** running (e.g. inside `async def main()`, or in Jupyter/a server with an existing loop), calling `agent.run(...)` raises `RuntimeError: sync API cannot run inside an active event loop; use the async API` immediately. You must use `await agent.arun(...)` or `async for ... in agent.astream(...)` there.

The correct async shape is `async def main()` plus `asyncio.run(main())`; synchronous scripts call `run`/`stream` directly.

### 8.3 Async example: subscribing to the event stream

`examples/02_streaming/main.py` consumes an event stream in an async context, quoted verbatim:

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

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/02_streaming/main.py)

Key points:

- `agent.aclose()` in `finally` closes the `httpx.AsyncClient` owned by the provider; synchronous scripts do not carry this burden, but long-running async processes should close it explicitly.
- Events are **immutable** `Event` objects: `event.type`, `event.payload` (read-only mapping), `event.thread_id`, `event.turn_id`, `event.event_id`, `event.timestamp`.
- Text deltas arrive as `model.text.delta`, followed by `model.completed` and `turn.completed`; `turn.completed`'s `payload["response"]` is the final `ModelResponse`.

### 8.4 Choosing sync vs async

- **Scripts / automation / one-shot CLI tasks**: use the synchronous `run`; simplest.
- **Web services, concurrent tasks, streaming UIs, event-driven integrations**: use `arun` / `astream`.
- **Mixing**: in async code touch only the `await` versions; sync entry points are allowed at module top level, in `__main__`, or outside `asyncio.run(...)`. Never nest `asyncio.run`, and do not expect `run` to hand you something awaitable.

## 9. Basic Example

**Minimal synchronous Agent**: see `examples/01_basic_agent/main.py` in 4.2 (this section defers to it; not re-pasted).

Running it requires and only requires: the package installed and `DEEPSEEK_API_KEY` set. It demonstrates the three core lines of the framework:

```python
provider = DeepSeekProvider()
agent = Agent(provider, instructions="Answer clearly and briefly.")
response = agent.run("Explain what an agent runtime does in one sentence.")
```

`Agent.run` opens a brand-new Thread: `response` is a normalized `ModelResponse` with no vendor-specific fields.

## 10. Real-world Example

**Multi-environment project: resolve config by profile, then build an Agent from it.** Real projects usually keep one project config file and want to switch between CI (`test`), offline development (`offline`), and local integration (`china`) without editing code. Compose `ConfigResolver` with `Agent`:

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

Combined with 6.4's profiles: in CI set `SUPER_HARNESS_PROFILE=test` to use the deterministic model; for offline verification `offline` disables search and switches the sandbox to `read_only`. `config.model.model` always reflects the *merged* model name (example 79 proved the project file's `model` can be swapped out by an environment variable).

**Interactive conversation script**: a real multi-turn assistant must reuse one Thread:

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

The two `thread.run` calls share history — by the second question the model sees the first exchange — which `agent.run` cannot do (it creates a new Thread every time).

## 11. Advanced Example

**Combination: configuration + secrets + async streaming.** Put the previous sections together: use `ConfigResolver` to decide the model and profile, `CompositeSecretProvider` to resolve application-level secrets explicitly (kept out of diagnostics, redacted at log boundaries), and `astream` to consume events incrementally:

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

Every symbol in this example (`ConfigResolver` / `CompositeSecretProvider` / `EnvironmentSecretProvider` / `MappingSecretProvider` / `DeepSeekProvider` / `Agent` / `agent.astream` / `event.payload`) has been verified to exist in `src/super_harness`; use it as a template and extend.

**Advanced 2: structured output and tool calls the async way.** `examples/03_structured_and_tools/main.py` shows `output_schema` (strict JSON) and `tools=[ToolDefinition(...)]` under async, quoted verbatim:

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

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/03_structured_and_tools/main.py)

Two behaviours directly relevant to the Start topic:

1. `output_schema` takes a JSON Schema; `response.output_json` is the locally validated parsed result. Over DeepSeek chat completions, `DeepSeekProvider` relaxes `response_format` to `json_object` and the local `_structured` step validates conformance, so "strict schema" still holds.
2. `ToolCall` is a normalized value: `call.call_id`, `call.name`, `call.arguments` (parsed dict), and `call.raw_arguments` (raw JSON string). Stage 1 only returns calls; stage 2 (execution) is handled by the `ToolExecutor` — detailed in the Tools part, not here.

## 12. API Cheat Sheet

Public APIs relevant to this page (all verified to exist in `src/super_harness`'s `__init__.py` / `agent.py` / `config/` / `models/`):

```python
# Providers
DeepSeekProvider(*, model="deepseek-v4-flash", api_key=None,
                  base_url="https://api.deepseek.com", wire_api=WireAPI.CHAT_COMPLETIONS,
                  timeout=60.0, max_retries=2, stream_max_retries=1) -> DeepSeekProvider

# Agent
Agent(provider, *, instructions=None, tools=(), approval=None, hooks=None,
      observer=None, max_model_steps=8, context=(), cwd=None,
      agents_loader=None, store=None, compaction_threshold_chars=100_000,
      persona=None) -> Agent
agent.thread() -> Thread                      # persistent Thread (requires store)
agent.run(input, *, tools=(), output_schema=None) -> ModelResponse      # sync
agent.arun(input, *, tools=(), output_schema=None) -> Awaitable[ModelResponse]
agent.stream(input, *, tools=(), output_schema=None) -> Iterator[Event]
agent.astream(input, *, tools=(), output_schema=None) -> AsyncIterator[Event]
await agent.aclose() -> None

# ModelResponse (immutable)
response.text          # final text
response.tool_calls    # tuple[ToolCall, ...]
response.usage         # Usage(input_tokens, output_tokens, total_tokens)
response.output_json   # Mapping | None (structured output)
response.response_id / finish_reason

# Configuration
ConfigResolver(*, user_config=None) -> ConfigResolver
resolved = resolver.resolve(*, cwd=None, runtime=None,
                            environment=None, load_dotenv=False) -> ResolvedConfig
resolved.config            # HarnessConfig (frozen)
resolved.config.model.model / .provider
resolved.config.sandbox.backend / .mode
resolved.config.approval.mode
resolved.config.persistence.path
resolved.diagnostics()     # dict: profile/model_provider/model/sources/environment_overrides/dotenv

# Secrets
secrets.get(name) -> SecretValue | None
secret.reveal() -> str                          # explicit boundary op; str/repr always ********

# CLI (callable from Python)
from super_harness.cli import main
raise SystemExit(main(["--json", "doctor"]))    # returns int (0 ok / 2 error)
```

## 13. Events & Streaming

`astream` / `stream` yield immutable `Event` objects. Within Part I you are likely to see at least these event types (emitted in `thread.py._astream_unobserved`):

| Event type | When | Key payload |
| --- | --- | --- |
| `turn.started` | start of each turn | — |
| `model.started` | start of each model request | `provider`, `model`, `step` |
| `model.text.delta` | text delta | `delta`, `step` |
| `model.tool_call.delta` | tool argument delta (streamed) | `index`, `name`, `delta` |
| `model.completed` | single model step done | `response`, `usage`, `tool_calls`, `step` |
| `model.failed` | model step exception | `error_class`, `message`, `step` |
| `tool.started` / `tool.completed` / `tool.failed` | tool execution lifecycle | `name`, `arguments`, `result`, `success` |
| `turn.steered` | steering instruction received | `instruction` |
| `turn.completed` | whole turn finished | `response` (final `ModelResponse`) |
| `turn.failed` | turn ended with an error | `error_type`, `message` |
| `compaction.started` / `compaction.completed` | auto/manual compaction | `before_messages`, `summarized_messages`, etc. |

Internally `arun` / `run` consume `astream` / `stream` and take the `payload["response"]` of `turn.completed`; so "final normalized response" and "event stream" are two views of the same path. Events are all immutable, payloads are read-only mappings, and they are relayed through `observer` (`Agent(observer=...)`) — the Observability part uses this.

## 14. Errors, Timeouts, Retries

Exceptions you will meet on this page (`src/super_harness/exceptions.py`):

- `SuperHarnessError`: base class for all public framework errors, carrying `message`, `correlation_id`, and `details` (redacted metadata).
- `ConfigError`: configuration cannot be resolved/validated (unknown profile, invalid `.env` line, unknown config key, `extra="forbid"` violation, file read failure).
- `ModelError` (inherits `ProviderError`): provider operation failure, e.g. missing credential `missing credential for provider deepseek: set DEEPSEEK_API_KEY`, HTTP 4xx auth errors, invalid tool JSON.
- `RuntimeError`: three common scenarios — archived Thread cannot run (`cannot run an archived thread`), Thread already has an active turn (`thread already has an active turn`), and **calling the sync API inside an event loop** (`sync API cannot run inside an active event loop; use the async API`).
- `ValueError`: empty input (`turn input must be non-empty`) or `max_model_steps < 1`.

**Timeouts and retries (`OpenAICompatibleProvider` / `DeepSeekProvider`)**:

- Defaults: `timeout=60.0` seconds (httpx client timeout), `max_retries=2` (non-streaming), `stream_max_retries=1` (streaming).
- Retryable failures: `httpx.TransportError` / `TimeoutException`, plus HTTP 429 or HTTP ≥ 500 (the `_retryable` check).
- Retries use exponential backoff `0.25 * 2**attempt + jitter`, capped at 2 seconds.
- **Not retryable**: auth errors and other HTTP 4xx fail immediately as `ModelError` (`details.status_code` carries the code); `ModelError` itself is never retried.
- The CLI's `provider test` and `thread resume` use `max_retries=0` — direct connects that surface problems fast.

**Tool loop cap**: a single turn runs at most `max_model_steps` (default 8) model steps; exceeding them raises `ToolError("tool loop exceeded maximum of 8 model steps")`. Raise it with `Agent(..., max_model_steps=...)`.

## 15. Combining with other features

Part I is the foundation for every other part. Think through these three things before moving on:

1. **Persistence**: for cross-process conversation recovery, construct `SQLiteThreadStore(path)` and pass it to `Agent(store=...)`. `agent.thread()` persists immediately, and `agent.resume(thread_id)` restores after a restart. Part II covers this.
2. **Tools and approval**: `Agent(tools=[...])` attaches the registry to threads; `Agent(approval=...)` controls the default `ApprovalPolicy.full_access()`. Detailed in the Tools part.
3. **Context and observability**: `Agent(context=..., cwd=...)` assembles `AGENTS.md` and external fragments; `Agent(observer=...)` receives the event stream from section 13. Covered in the corresponding parts.

There is no magic in how they combine: config files decide *what to use* (provider/profile), the `Agent` constructor decides *how to run* (instructions/tools/approval), and Thread/Store decide *what to remember*. The three evolve independently without blocking each other.

## 16. Security Notes

- **Keys go through environment variables, never arguments or logs**: providers read from the `api_key_env`-named variable at request time; input to `provider test` / `thread resume` never carries keys. `SecretValue`'s `str`/`repr` are always `********`; `.reveal()` is used only at explicit boundaries.
- **Diagnostics expose metadata only**: `ConfigResolver.diagnostics()` lists source paths and overridden variable names, not values; all CLI output is filtered through `SecretRedactor` (patterns like `api_key=`, `token=`, `Bearer ...`).
- **`.env` is not loaded by default**: treat `.env` as "inject on demand" rather than "auto-applied"; as long as you do not pass `load_dotenv=True`, it has no effect on your process and never pollutes `os.environ`.
- **Config files carry authoritative instructions**: `instructions` and `AGENTS.md` content are treated as developer authority; external data (search/RAG fragments, tool returns) is in the user role and cannot override developer/project instructions.
- **Sandbox boundary** (heads-up): `LocalSandbox` is a developer convenience, not OS isolation; for strong boundaries use `DockerSandbox` later.

## 17. Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `missing credential for provider deepseek: set DEEPSEEK_API_KEY` | `DEEPSEEK_API_KEY` is absent from the environment. Set it and retry; in CLI scenarios confirm the child process inherits the variable. |
| `sync API cannot run inside an active event loop; use the async API` | `run`/`stream` called inside a coroutine/event loop. Switch to `await agent.arun(...)` or `async for ... in agent.astream(...)`; at script top level use `asyncio.run(main())`. |
| `configuration validation failed` | Unknown key (`extra="forbid"`) or type error in a config file. Inspect `ConfigError.details["errors"]` (pydantic details), or run `super-harness doctor --json` and check the `configuration` entry first. |
| `unknown configuration profile ...` | The `SUPER_HARNESS_PROFILE` or a config `profile` value is not `china/global/offline/test` (a `-dev` suffix is allowed). |
| `cannot run an archived thread` / `thread already has an active turn` | Thread state constraints. Archived threads are read-only; a Thread allows only one active turn at a time — for background execution use `thread.start(...)` (a `TurnHandle`). |
| `tool loop exceeded maximum of N model steps` | The model is stuck in a tool loop. Give tools clearer descriptions, or raise `max_model_steps`; also check whether the approval policy keeps denying, prompting the model to retry. |
| `provider response contained no choices` / HTTP 4xx | Usually a model/endpoint mismatch. Verify connectivity with `super-harness provider test`; for OpenAI-compatible endpoints pass the correct `base_url`, `model`, and `api_key_env` when constructing `OpenAICompatibleProvider`. |
| Diagnostics show `dotenv: null` | `.env` is not loaded (off by default). Call `resolve(load_dotenv=True)` and make sure `.env` sits at the project root (the `.git` root). |
| Occasional failures on bad networks | Transport errors/429/5xx are retried automatically (2 non-streaming, 1 streaming); if timeouts recur, raise `DeepSeekProvider(timeout=...)`. |

## 18. Links

**Runnable examples referenced on this page**

- [examples/01_basic_agent/main.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/01_basic_agent/main.py) — minimal sync Agent (basic)
- [examples/02_streaming/main.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/02_streaming/main.py) — async event stream (sync vs async)
- [examples/03_structured_and_tools/main.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/03_structured_and_tools/main.py) — structured output + tool definitions (advanced async)
- [examples/63_cli_doctor.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/63_cli_doctor.py) — run `doctor` with `--json`
- [examples/78_config_profiles.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/78_config_profiles.py) — resolve a built-in profile
- [examples/79_config_precedence.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/79_config_precedence.py) — config precedence (env/runtime over project file)
- [examples/80_secret_providers.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/80_secret_providers.py) — SecretProvider composition and masking

**Related documentation**

- User Guide Part II — Threads and persistence (`guide/part2-threads`)
- User Guide Part III — Tools and approval (`guide/part3-tools`)
- Internals — configuration resolution and the runtime (`internals/...`)
- API reference (`api-reference` / `generated-api`)
- Troubleshooting index (`troubleshooting`)