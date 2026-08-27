---
id: internals-extensions
title: Extension Mechanisms (Internals 6)
sidebar_position: 6
description: Internal implementation of Skill discovery/activation/installer, the MCP client and transports, the plugin loader, and the hook lifecycle and dispatch, including failure models and extension points.
---

# Extension Mechanisms: Skills, MCP, Plugins, and Hooks

This document covers part 6 of Super Harness internals: how the four runtime extension mechanisms are discovered, validated, activated, and dispatched — Open Agent Skills, MCP (Model Context Protocol clients and ecosystem), Plugins (capability bundles), and Hooks (lifecycle interceptors). It answers "why are these mechanisms designed this way and how do they work"; it is not an operations tutorial.

The real implementation lives in:

- `src/super_harness/skills/` — `models.py` (metadata and progressive activation), `catalog.py` (ordered discovery), `installer.py` (validated installation).
- `src/super_harness/mcp/` — `client.py` (official SDK adapter), `config.py` (typed configuration and mcpServers JSON import), `mcpb.py` (MCP Bundle validation and installation), `registry.py` (replaceable registry protocol).
- `src/super_harness/plugins/` — `models.py` (manifest and capability values), `loader.py` (manifest parsing), `manager.py` (explicit activation and conflict rollback), `installer.py` (installation lifecycle).
- `src/super_harness/hooks/` — `models.py` (hook lifecycle values), `registry.py` (ordered dispatch).
- The related tool registration surface lives in `src/super_harness/tools/` (`definition.py`, `registry.py`) and the exception hierarchy in `src/super_harness/exceptions.py`.

Full research and the Codex comparison live in [`docs/research/codex/skills-and-mcp.md`](https://github.com/Sitozzmonash/superharness/blob/main/docs/research/codex/skills-and-mcp.md) and [`docs/research/codex/plugins-and-hooks.md`](https://github.com/Sitozzmonash/superharness/blob/main/docs/research/codex/plugins-and-hooks.md).

## 1. Responsibilities

Each of the four subsystems owns a clearly bounded set of responsibilities:

- **`skills/` — the Skills subsystem**:
  - `models.py` defines `SkillMetadata` (lightweight frontmatter-only metadata) and `ActivatedSkill` (metadata + instruction body), and provides `parse_skill` (frontmatter only) and `activate_skill` (reads the instruction body), plus `read_resource`, which confines resource reads to the Skill directory.
  - `catalog.py` walks explicit, project, user, plugin, and system roots in a fixed precedence order, resolves **frontmatter only** while building the catalog, and records collisions and parse errors.
  - `installer.py` stages, validates, and only then copies local directories or HTTPS Git/GitHub subdirectories into an installation root, recording provenance and supporting updates.
- **`mcp/` — the MCP subsystem**:
  - `client.py` wraps the official MCP Python SDK `Client` (`mcp.client.client.Client`), using `StdioServerParameters` for stdio and an isolated `httpx2` client for the Streamable HTTP transport; public methods bind pagination, apply timeouts, preserve cancellation, and normalize errors, and `as_tools` translates remote tools into the standard `Tool` surface.
  - `config.py` defines `MCPServerConfig` and `MCPTransport`, and provides `import_mcp_servers` to import common `mcpServers` JSON.
  - `mcpb.py` validates `.mcpb` archives before extraction (SHA-256, manifest fields, paths, symlinks, file count, expanded size).
  - `registry.py` places the official Registry preview API behind the small, replaceable `MCPRegistry` protocol.
- **`plugins/` — the plugin subsystem**:
  - `models.py` defines `PluginManifest`, `PluginHookSpec`, `PluginCapabilities`, `InstalledPlugin`, and `PluginTrace`.
  - `loader.py` parses `.super-harness/plugin.toml` or `.codex-plugin/plugin.json`, validating paths/version requirements (data only, never executes code).
  - `manager.py` `enable` performs **explicit activation**: it imports Python entry symbols, namespaces Tools, registers hooks under the mandatory `plugin:<name>` attribution, loads MCP config, and rolls back earlier registrations on conflict.
  - `installer.py` owns the install/update/remove lifecycle and provenance records.
- **`hooks/` — the hook subsystem**:
  - `models.py` defines `HookEvent` (14 lifecycle events), `HookFailurePolicy`, `HookContext`, `HookResult`, `HookTrace`, and `HookOutcome`.
  - `registry.py` dispatches registrations in `(priority, source, name)` order; every callback receives a fresh immutable context view over the accumulated data, and sync and async handlers share the same timeout/cancellation path.

At runtime these mechanisms converge in `Agent` / `Thread` / `ToolExecutor`: `ToolExecutor` dispatches `PRE_TOOL_USE` / `POST_TOOL_USE` after approval; `Thread` dispatches session/prompt/turn hooks at thread start and before/after hooks on each model step, plus pre/post hooks around async compaction; `PluginManager` injects activated plugin capabilities (Tools, hooks, MCP config, Skill roots) into the corresponding registries.

## 2. Data model

### 2.1 Skills (`skills/models.py`)

```python
@dataclass(frozen=True, slots=True)
class SkillMetadata:
    name: str               # validated ^[a-z0-9]+(?:-[a-z0-9]+)*$, max 64, description required
    description: str        # whitespace collapsed (" ".join(description.split()))
    path: Path              # resolved SKILL.md path
    source: str = "runtime" # runtime / explicit / project-agents / project-super-harness / user / plugin / system / local / git / installed / pinned-codex
    extra: Mapping[str, Any] = field(default_factory=_extra)  # frozen to MappingProxyType (full frontmatter)

@dataclass(frozen=True, slots=True)
class ActivatedSkill:
    metadata: SkillMetadata
    instructions: str       # body after the frontmatter (stripped); must be non-empty
    def read_resource(self, relative_path: str) -> bytes: ...   # confined to the Skill directory

@dataclass(frozen=True, slots=True)
class SkillSource:
    source_type: str        # "local" / "git"
    location: str           # original source
    revision: str | None    # resolved commit hash for git
    installed_at: str       # UTC ISO timestamp
```

`SkillMetadata.__post_init__` freezes `extra` to a `MappingProxyType`. `parse_skill(path, *, source)` locates `SKILL.md` when handed a directory and parses the YAML frontmatter; third-party descriptions that are unquoted and contain a colon first pass through a narrow compatibility repair (`_repair_colon_scalars`, which quotes scalars shaped like `key: a: b` via `json.dumps`) before falling back to `yaml.safe_load`. `ActivatedSkill.read_resource` resolves `root = metadata.path.parent.resolve()`, then `(root / relative_path).resolve()`, verifying with `path.relative_to(root)` that it does not escape; otherwise it raises `SkillError("skill resource escapes its directory")`. A missing file raises `SkillError`.

### 2.2 MCP (`mcp/config.py`, `mcp/mcpb.py`)

```python
class MCPTransport(StrEnum):
    STDIO = "stdio"
    STREAMABLE_HTTP = "streamable_http"

@dataclass(frozen=True, slots=True)
class MCPServerConfig:
    name: str
    transport: MCPTransport
    command: str | None = None          # required for STDIO
    args: tuple[str, ...] = ()
    env: Mapping[str, str] = field(default_factory=_string_mapping)
    cwd: Path | None = None
    url: str | None = None              # required for STREAMABLE_HTTP
    headers: Mapping[str, str] = field(default_factory=_string_mapping)
    timeout: float = 30.0               # must be > 0
    enabled: bool = True
    include_tools: tuple[str, ...] = () # empty means include all
    exclude_tools: tuple[str, ...] = ()

@dataclass(frozen=True, slots=True)
class MCPBundle:
    name: str
    version: str
    manifest_version: str
    description: str
    config: MCPServerConfig
```

`MCPServerConfig.__post_init__` validates that name is non-empty, timeout is positive, stdio has a command, and Streamable HTTP has a url, then freezes `env` / `headers` to `MappingProxyType`. `import_mcp_servers(value)` accepts a `Mapping` or JSON path, reads the `mcpServers` object, and maps each entry to an `MCPServerConfig` (including `includeTools` / `excludeTools` / `disabled` / `timeout`, converting `cwd` to `Path`).

### 2.3 Plugins (`plugins/models.py`)

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
    requires_super_harness: str = ""     # e.g. ">=0.1.0,<1"
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
    hooks: tuple[str, ...] = ()          # hook names
    assets: tuple[Path, ...] = ()
    personas: tuple[Path, ...] = ()
    commands: tuple[Path, ...] = ()

@dataclass(frozen=True, slots=True)
class InstalledPlugin:
    manifest: PluginManifest
    enabled: bool
    source: Mapping[str, Any]            # provenance record, frozen

@dataclass(frozen=True, slots=True)
class PluginTrace:
    operation: str      # install / enable / disable / update / remove
    plugin: str
    success: bool
    capabilities: tuple[str, ...] = ()   # activated capability keys among skills/tools/mcp/hooks
    warning: str | None = None
```

### 2.4 Hooks (`hooks/models.py`)

```python
class HookEvent(StrEnum):
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    TURN_START = "turn_start"
    TURN_END = "turn_end"
    USER_PROMPT = "user_prompt"        # deniable
    BEFORE_MODEL = "before_model"      # deniable
    AFTER_MODEL = "after_model"
    PRE_TOOL_USE = "pre_tool_use"      # deniable, modifiable
    POST_TOOL_USE = "post_tool_use"
    PRE_COMPACT = "pre_compact"        # deniable
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
    data: Mapping[str, Any] = field(default_factory=_mapping)  # frozen
    thread_id: str | None = None
    turn_id: str | None = None
    source: str = "runtime"

@dataclass(frozen=True, slots=True)
class HookResult:
    updates: Mapping[str, Any] = field(default_factory=_mapping)  # frozen
    deny_reason: str | None = None      # non-empty validation
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
    data: Mapping[str, Any]             # accumulated data (frozen)
    traces: tuple[HookTrace, ...] = ()
    denied: bool = False
    deny_reason: str | None = None
```

The registration value itself (`hooks/registry.py`) is also immutable:

```python
@dataclass(frozen=True, slots=True)
class HookRegistration:
    event: HookEvent
    handler: HookCallable
    name: str               # provided at registration or falls back to handler.__name__
    source: str = "runtime"
    priority: int = 100
    timeout: float = 10.0
    failure_policy: HookFailurePolicy = HookFailurePolicy.WARN
    allow_modify: bool = False
```

`HookRegistration.__post_init__` validates that name is non-empty and timeout is positive.

## 3. Lifecycle

### 3.1 Skill discovery: root walk and precedence (`catalog.py`)

`SkillCatalog.discover` builds its root list in the following **precedence order**; earlier entries win:

```text
1. explicit       paths passed by the caller
2. project-agents      <project root>/.agents/skills for the cwd's project root
3. project-super-harness <project root>/.super-harness/skills
4. user                user_root or ~/.super-harness/skills
5. plugin              plugin roots (skills contributed by plugins)
6. system              system roots
```

`_project_root(cwd)` walks up from cwd and returns the first directory containing `.git`; it falls back to cwd itself. For each root: if `root/SKILL.md` is a file, the root itself is a single Skill candidate; otherwise the parents of `root.glob("*/SKILL.md")` are the candidate set (sorted for stability). Each candidate goes through `parse_skill(candidate, source=source)`; a failed parse appends a `SkillError` to `catalog.errors`; a candidate whose **name already exists** is recorded in `catalog.collisions[name]` and **skipped** — the first (higher-precedence) discovery wins. While building the catalog, instruction bodies are never read, only frontmatter.

```text
discover(explicit=[...], cwd=..., user_root=..., plugin_roots=..., system_roots=...)
  │  assemble roots: [(source, Path), ...] (fixed order)
  ▼
for source, root in roots:
  │  candidates = root/SKILL.md is file ? [root] : sorted(parents of glob("*/SKILL.md"))
  ▼
for candidate in candidates:
  │  parse_skill(candidate, source=source)      # frontmatter only
  │    │  failure → catalog.errors.append(exc); continue
  │    ▼  name already present → catalog.collisions[name].append(path); continue
  ▼
  catalog.skills[name] = metadata                 # first (highest precedence) wins
```

`list()` returns a tuple; `get(name)` raises `SkillError` for unknown names; `activate(name)` = `activate_skill(get(name))` — this is the only point where the instruction body is read, and empty instructions raise `SkillError("SKILL.md instructions are empty")`.

### 3.2 Skill installation: stage → validate → copy (`installer.py`)

`SkillInstaller.install(source)`:

- Local sources: `Path(source).resolve()`, then `parse_skill(path, source="local")`.
- Remote sources: HTTPS is required (`https://` or `git+https://`, with the `git+` prefix stripped). A `github.com/.../tree/<rev>[/<subdir>]` form is decomposed into revision and subdirectory, and `repo_url` is normalized to `https://github.com<repo_path>.git`.

The Git flow runs inside a `tempfile.TemporaryDirectory`:

```text
git clone --depth 1 <repo_url> <clone>
  ▼ when a revision is requested
git -C <clone> fetch --depth 1 origin <revision>
git -C <clone> checkout --detach FETCH_HEAD
  ▼
skill_root = (clone / subdirectory).resolve()
  │  relative_to(clone.resolve()) check: subdirectory must not escape the repository
  ▼
parse_skill(skill_root, source="git")
  ▼ rev-parse HEAD → immutable commit hash
  ▼ _copy(metadata, SkillSource("git", source, commit, _now()))
```

`_copy`: the target `destination/name` must pass `relative_to(destination)` (the name may not escape the installation root); an existing target raises `SkillError("already installed")` (**never silently overwrites**); any symlink found via `rglob("*")` is rejected (`SkillError("skill packages may not contain symbolic links")`); the tree is copied with `shutil.copytree(..., symlinks=True)`; a `.super-harness-source.json` provenance record is written; and the result is re-parsed from the installed copy.

`update(name)` is a **recoverable replacement**: `info(name)` retrieves the source location, a `SkillInstaller(staging_root)` installs the new version into a hidden staging root, the updated name is verified unchanged; then `target.rename(backup)` and `staged.rename(target)`; any failure rolls back via `backup.rename(target)`; on success both backup and staging are removed.

`remove(name)` resolves the target, validates it against the installation root, and `shutil.rmtree`. `list()` walks non-hidden directories under the installation root and `parse_skill(source="installed")` each. `info(name)` parses the installed directory and `.super-harness-source.json`; missing/corrupt data raises `SkillError`.

### 3.3 MCP client connect and calls (`client.py`)

```text
async with MCPClient(config, observer=...) as client:
  │  __aenter__:
  │    enabled == False → MCPError("disabled")
  │    STDIO:      StdioServerParameters(command, args, env, cwd) → target
  │    HTTP:       httpx2.AsyncClient(headers, timeout, follow_redirects=False)
  │                → streamable_http_client(url, http_client=http) → target
  │    client = Client(target, read_timeout_seconds=config.timeout)
  │    emit mcp.connected event (server, transport, protocol_version)
  ▼
client.list_tools() / call_tool() / list_resources() / read_resource()
client.list_prompts() / get_prompt() / as_tools()
  │  every operation goes through _run(operation, label):
  │    emit mcp.call.started → asyncio.wait_for(operation, timeout)
  │    success: mcp.call.completed(duration_ms) → return
  │    TimeoutError → mcp.call.failed → MCPError("timed out")
  │    other exceptions → mcp.call.failed → MCPError("failed")
  ▼
__aexit__: AsyncExitStack.aclose() (HTTP client, SDK client, stdio process all closed)
```

On connection failure, `stack.aclose()` cleans up partially created resources; `asyncio.CancelledError` is re-raised unchanged; anything else is wrapped as `MCPError(f"MCP server {name!r} connection failed")`.

**Bounded pagination**: `list_tools` / `list_resources` / `list_prompts` all run a cursor loop bounded by `_MAX_PAGES = 20` and `_MAX_ITEMS = 1_000` cumulative items. `_next_cursor` rejects cursors over 4096 bytes and **repeated cursors** (`MCPError("repeated pagination cursor")`).

**Tool filters**: `_tool_allowed(name)` = (`include_tools` empty or `name in include_tools`) and `name not in exclude_tools`. `as_tools` skips excluded tools; `call_tool` first runs `_allow_tool`, raising `MCPError("disabled by filter")` out of scope.

### 3.4 MCP Bundle validation and installation (`mcpb.py`)

`inspect_mcpb(path, *, expected_sha256=None)` validates **before extraction**:

```text
SHA-256(bundle_bytes) compared to expected_sha256 (mismatch → "integrity check failed")
  ▼ open zip: no duplicate member names, manifest.json present
  ▼ file count <= 10_000, total expanded size <= 256 MiB
  ▼ no "unsafe members" (absolute path / contains ".." / drive-letter colon)
  ▼ no symlinks (external_attr >> 16 is S_ISLNK)
  ▼ read manifest.json → required fields (manifest_version, name, version, description, author, server)
  ▼ name must match ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ (filesystem safe)
  ▼ server.type == "uv"    → command="uv",     args=("run", "${__dirname}/<entry>")
    server.type == "python"→ command="python", args=("${__dirname}/<entry>",)
    otherwise an explicit mcp_config.command is required
  ▼ construct MCPServerConfig(name, STDIO, ...)
```

`install_mcpb(path, destination, *, expected_sha256=None)` calls `inspect_mcpb` first; the target `destination/name` must not escape the installation root and must not already exist; the archive is extracted to a temporary staging directory and copied into the target; only **after extraction** are `${__dirname}` placeholders in command/args/env resolved to the target's absolute path, with `cwd` set to the target. Placeholders are resolved only once the archive contents have landed.

### 3.5 Plugin lifecycle (`installer.py` + `manager.py`)

```text
install(source)  → stage source (local dir copytree or git clone --depth 1 + revision checkout + subdir)
                 → load_plugin(staging root) → target exists? reject
                 → _validate_tree(no symlinks) → copytree to target
                 → write .super-harness-source.json → InstalledPlugin(enabled=False)   # executes no plugin code
enable(name)     → read manifest → _load_tools(namespaced) + _load_mcp(prefix-named)
                 → register Tool / register Hook(source="plugin:<name>") one by one
                 → conflict/exception → roll back registered Tools and Hooks → PluginError
                 → store PluginCapabilities in _enabled → PluginTrace
disable(name)    → pop from _enabled → unregister all Tools / Hooks
update(name)     → requires disable first; stage new source → name match → staging/backup swap
remove(name)     → requires disable first; shutil.rmtree
```

`_load_tools` resolves each entry symbol via `_symbol(manifest, entry)` (Python import, below), accepting a single `Tool` or an iterable of `Tool`; every tool is **re-namespaced** with `replace(candidate.metadata, namespace=manifest.name, source=f"plugin:{manifest.name}")`; duplicate qualified names are rejected (`PluginError`). `_load_mcp` imports from `mcp_path` or `inline_mcp`, prefixes every server name as `{plugin}.{server}`, and sets `cwd` to the plugin root for stdio servers. Hook registrations carry `source=f"plugin:{name}"`, with `failure_policy` / `allow_modify` / `priority` / `timeout` from the manifest.

`enable`'s rollback is transactional: registrations accumulate in `registered_tools` / `registered_hooks`; any `SuperHarnessError` / `TypeError` / `ValueError` triggers unregistering each and re-raises. Failures in `_load_tools` / `_load_mcp` produce no registrations at all (no side effects). Every failure path emits `PluginTrace(enable, name, False, warning=...)`.

**Python symbol import** (`_symbol` → `_module`): an entry `./file.py:symbol` resolves to a path inside the plugin root, loaded via `importlib.util.spec_from_file_location` under the unique module name `_super_harness_plugin_<plugin>_<uuid>`, `exec_module` is run, and `getattr(module, symbol)` returns the value. **Only `enable` imports and executes plugin Python**; `install` / `load_plugin` execute nothing (`test_plugin_validation_..._and_no_auto_execution` explicitly verifies the marker file is absent after install).

### 3.6 Hook dispatch (`registry.py`)

```text
dispatch(HookContext(event, data, thread_id, turn_id))
  │  data = dict(context.data)              # working copy of the event's accumulated data
  ▼
for item in sorted(_hooks[event], key=(priority, source, name)):
  │  ctx = HookContext(event, data, thread_id, turn_id, item.source)   # a fresh immutable view per callback
  │  result = await asyncio.wait_for(_resolve(item.handler(ctx)), item.timeout)
  │    _resolve: awaits awaitables, returns plain values as-is
  ▼
  if result and result.updates:
      if not item.allow_modify: raise HookError("not allowed to modify this event")
      data.update(result.updates)
  ▼
  if result and result.deny_reason is not None:
      if event not in _DENIABLE_EVENTS: raise HookError("event cannot be denied")
      trace(denied=True) → return HookOutcome(data, traces, denied=True, deny_reason) immediately
  ▼
  trace(success=True, duration_ms)
  ▼
  exception (non-CancelledError) → trace(success=False, warning)
    FAIL_CLOSED → raise HookError("failed closed")
    WARN        → warnings.warn(RuntimeWarning)
    FAIL_OPEN   → continue
  ▼
return HookOutcome(data, traces)
```

`_DENIABLE_EVENTS = {USER_PROMPT, BEFORE_MODEL, PRE_TOOL_USE, PRE_COMPACT}` — only these four safe interception points allow `HookResult.deny(...)`; denying any other event raises `HookError`. `asyncio.CancelledError` is always re-raised (never consumed by a policy). `register` appends then `sort(key=(priority, source, name))` for deterministic order; a duplicate (name, source) registration raises `HookError`.

## 4. Key interfaces/classes

### 4.1 `SkillCatalog` (`catalog.py`)

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

### 4.2 `SkillInstaller` (`installer.py`)

```python
class SkillInstaller:
    def __init__(self, destination: str | Path) -> None: ...
    def install(self, source: str | Path) -> SkillMetadata: ...
    def remove(self, name: str) -> None: ...
    def info(self, name: str) -> tuple[SkillMetadata, SkillSource]: ...
    def list(self) -> tuple[SkillMetadata, ...]: ...
    def update(self, name: str) -> SkillMetadata: ...
```

### 4.3 `parse_skill` / `activate_skill` (`models.py`)

```python
def parse_skill(path: str | Path, *, source: str = "runtime") -> SkillMetadata: ...
def activate_skill(metadata: SkillMetadata) -> ActivatedSkill: ...
```

### 4.4 `MCPServerConfig` / `import_mcp_servers` (`config.py`)

```python
@dataclass(frozen=True, slots=True)
class MCPServerConfig: ...   # see 2.2

def import_mcp_servers(value: str | Path | Mapping[str, Any]) -> tuple[MCPServerConfig, ...]: ...
```

### 4.5 `MCPClient` (`client.py`)

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

`as_tools` translates each remote tool into a standard `Tool`: `_arguments_model(name, schema)` builds a Pydantic argument model from the JSON Schema's `properties` / `required` via `create_model(f"MCP{Name}Arguments", __config__=ConfigDict(extra="forbid"), **fields)`; `ToolMetadata(namespace=self.config.name, source="mcp", risk="external", timeout=self.config.timeout)` preserves the **server namespace** and **external risk metadata**; the qualified name is therefore `{server}.{tool}`.

### 4.6 MCPB and registry (`mcpb.py`, `registry.py`)

```python
def inspect_mcpb(path: str | Path, *, expected_sha256: str | None = None) -> MCPBundle: ...
def install_mcpb(path: str | Path, destination: str | Path, *, expected_sha256: str | None = None) -> MCPBundle: ...

class MCPRegistry(Protocol):                      # replaceable protocol
    async def search(self, query: str, *, limit: int = 20) -> tuple[Mapping[str, Any], ...]: ...
    async def get(self, name: str, version: str = "latest") -> Mapping[str, Any]: ...

class OfficialMCPRegistry:
    def __init__(self, base_url: str = "https://registry.modelcontextprotocol.io", *,
                 timeout: float = 20.0, client: httpx.AsyncClient | None = None) -> None: ...
    async def search(self, query: str, *, limit: int = 20) -> tuple[Mapping[str, Any], ...]: ...
    async def get(self, name: str, version: str = "latest") -> Mapping[str, Any]: ...
```

`search` hits `/v0.1/servers` (`search` + `limit`, 1–100); `get` hits `/v0.1/servers/{name}/versions/{version}` (URL-encoded). `_get` builds its own `httpx.AsyncClient(timeout)` when no client was injected and closes it afterwards; any `httpx.HTTPError` / `ValueError` is wrapped as `MCPError`. An out-of-range `limit` raises `ValueError` (not an MCP error).

### 4.7 Plugins (`loader.py`, `manager.py`, `installer.py`)

```python
def load_plugin(path: str | Path) -> PluginManifest: ...   # prefers .super-harness/plugin.toml, then .codex-plugin/plugin.json

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

Key `load_plugin` manifest validations: the name must be 1–64 `[a-z0-9]+(?:-[a-z0-9]+)*` (kebab-case); the version is validated with `packaging.version.Version`; `requires_super_harness` is evaluated as a `packaging.specifiers.SpecifierSet` against `importlib.metadata.version("super-harness")`, and a mismatch raises `PluginError("plugin requires an incompatible Super Harness version")`; all paths must start with `./` and stay inside the plugin root; tool/hook entries must be `./file.py:symbol` pointing at an existing file. Unknown manifest fields are recorded in `warnings` rather than rejected.

### 4.8 `HookRegistry` (`registry.py`)

```python
class HookRegistry:
    def __init__(self, *, trace_sink: HookTraceSink | None = None) -> None: ...
    def register(self, event, handler, *, name=None, source="runtime", priority=100,
                 timeout=10.0, failure_policy=HookFailurePolicy.WARN, allow_modify=False) -> HookRegistration: ...
    def unregister(self, event: HookEvent, name: str, *, source: str = "runtime") -> None: ...
    def list(self, event: HookEvent | None = None) -> tuple[HookRegistration, ...]: ...
    async def dispatch(self, context: HookContext) -> HookOutcome: ...
```

## 5. Concurrency/cancellation

- **MCP operation timeout and cancellation**: `_run` uses `asyncio.wait_for(operation, config.timeout)`. `asyncio.CancelledError` is re-raised unchanged (`test_mcp_timeout_is_typed_and_cancellation_propagates` verifies the caller receives `CancelledError` after `task.cancel()`); `TimeoutError` maps to `MCPError("timed out")`. Cancellation inside `__aenter__` first runs `stack.aclose()` to clean up partially created resources and then re-raises.
- **Observers may be awaitable**: `_observe(event)` calls `observer.observe(event)` and awaits it when it returns an awaitable — both sync and async observers are supported, and observation runs outside the call timeout budget.
- **Unified sync/async hooks**: `HookRegistry.dispatch` calls `_resolve(handler(ctx))` per callback — plain return values are used directly, awaitables are awaited; both are bounded by `asyncio.wait_for(..., item.timeout)`. `asyncio.CancelledError` always re-raises (`test_hook_failure_policies_timeout_denial_and_cancellation`).
- **Plugin Python imports** are synchronous `importlib` calls executed inside the event loop during `enable`; plugin hooks and tools then run under their respective registry timeout/cancellation paths.
- **Installer Git subprocesses** use blocking `subprocess.run` during install commands; `SkillInstaller` / `PluginInstaller` are synchronous APIs typically driven by the CLI rather than hot paths.
- **Resource reads** (`ActivatedSkill.read_resource`) are synchronous `read_bytes` calls confined to the Skill directory.

## 6. Persistence

- **Skill provenance**: every installed Skill directory contains `.super-harness-source.json` (the `SkillSource` as JSON: `source_type` / `location` / `revision` / `installed_at`), which `SkillInstaller.info` relies on to reconstruct provenance.
- **Plugin provenance**: installed plugin directories contain `.super-harness-source.json` (`{"source_type","location","revision","installed_at"}`), read by `PluginInstaller.info` and injected into `InstalledPlugin.source`.
- **MCP config import**: `import_mcp_servers` maps common `mcpServers` JSON to `MCPServerConfig`; registry lookups run live through `OfficialMCPRegistry` and are not persisted.
- **Install roots**: `SkillInstaller(destination)` / `PluginInstaller(destination)` place installed items in the given directory (hidden staging/backup directories start with `.` and are skipped by `list()`). Updates use a staging + backup swap, a crash/failure-safe replacement.
- **Runtime state** (`PluginManager._enabled`, `HookRegistry._hooks`, `ToolRegistry`) is in-process; cross-process recovery belongs to the persistence extensions.

## 7. Events/observability

- **MCP events** (via `EventObserver`; events in `runtime/events.py`): `mcp.connected` (server, transport, protocol_version); `mcp.call.started` / `mcp.call.completed` / `mcp.call.failed` (server, operation, operation_id, duration_ms, error_class). `test_real_stdio_...` verifies observation of `>= {mcp.connected, mcp.call.started, mcp.call.completed}`.
- **Hook traces**: every registration execution produces a `HookTrace` (event, hook, source, success, duration_ms, denied, warning) emitted through `trace_sink`; `HookOutcome` returns the accumulated data and all traces to the dispatcher.
- **Plugin traces**: `PluginTrace` (operation, plugin, success, capabilities, warning) is emitted through `PluginManager(trace_sink=...)`; on successful `enable`, `capabilities` lists the actually activated `skills` / `tools` / `mcp` / `hooks` keys.
- **Skills observability**: `SkillCatalog`'s `collisions` and `errors` fields keep duplicate-name and parse problems from discovery inspectable; `SkillMetadata.source` records provenance for audit.
- **Hooks and the runtime**: `Agent` / `Thread` / `ToolExecutor` / compactor dispatch `HookEvent` at lifecycle points; failed hooks receive the raw exception context (`ERROR` event), and success/denial/timeout/error all emit traces.

## 8. Codex reference

The contracts, invariants, and design motivations of this layer are based on reverse-engineered research of the Codex (Rust) extension stack:

- **Skills and MCP**: see [`docs/research/codex/skills-and-mcp.md`](https://github.com/Sitozzmonash/superharness/blob/main/docs/research/codex/skills-and-mcp.md). Inspected files include `codex-rs/skills/src/{loading,model,parser}.rs`, `codex-rs/ext/skills/src/loader/{discovery,metadata}.rs`, and `codex-rs/codex-mcp/src/connection_manager.rs` (with `resources.rs`, `tool_catalog.rs`).
- **Plugins and hooks**: see [`docs/research/codex/plugins-and-hooks.md`](https://github.com/Sitozzmonash/superharness/blob/main/docs/research/codex/plugins-and-hooks.md). Inspected files include `codex-rs/core-plugins/src/{manifest,loader,manager,store,executor_hooks}.rs`, `codex-rs/hooks/src/types.rs`, and `codex-rs/hooks/src/engine/{dispatcher,mod}.rs`.

**Behavioral contracts** extracted from Codex and reproduced here:

- Skills are discovered as cheap metadata, activated only when selected, and supporting resources load on demand; higher-precedence roots win deterministically and collisions remain inspectable.
- Installations stage and validate content, reject overwrite, path escape, and symlinks, and record the resolved source revision.
- MCP uses the official SDK rather than a private wire protocol; pagination, cursor size, operation duration, archive count, and archive size are all bounded; tool filters apply to both advertised adapters and direct invocation; cancellation propagates and operational failures become typed `MCPError` values.
- A plugin is inert metadata until explicitly enabled; disabled plugins contribute nothing; duplicate identities and incompatible versions are reported; install/update validate before activation.
- Hooks are ordered, attributed, time-bounded lifecycle interceptors with explicit mutation/denial permissions and observable failure outcomes; denial does not replace approval policy.

**Important invariants**: `SKILL.md` has validated YAML frontmatter and non-empty instructions; discovery never eagerly injects every Skill body or resource into context; installation never silently overwrites and never accepts symlinks; only explicit `enable` imports Python entry points; activation is transactional (conflicts roll back); hook priority is deterministic and cancellation always propagates; every execution records hook/plugin source attribution and outcome traces.

## 9. Python-native redesign

Mapping the Codex Rust extension stack to a Python-native implementation:

- **`SkillCatalog`** performs ordered metadata discovery and activates an `ActivatedSkill` on demand; `SkillInstaller` accepts local directories and HTTPS Git/GitHub subdirectories, checks out the requested revision, validates before copying, and records provenance.
- **`MCPClient`** wraps the official MCP Python SDK `Client` (stdio and Streamable HTTP) and converts remote tools into ordinary `Tool` objects; `import_mcp_servers`, `inspect_mcpb`/`install_mcpb`, and `OfficialMCPRegistry` (behind the `MCPRegistry` protocol) are standalone helpers.
- **`HookRegistry`** stores typed `HookRegistration` values and dispatches immutable `HookContext` through sync or async callbacks; `HookResult` can enrich allowed data or deny eligible events; `HookTrace` records attribution, duration, success, warning, and denial. Agent/Thread/compaction/model/tool pipelines emit lifecycle events.
- **`PluginInstaller`** stages local or pinned HTTPS Git/GitHub sources and supports install/update/remove; `load_plugin` parses `.super-harness/plugin.toml` or `.codex-plugin/plugin.json`; `PluginManager.enable` explicitly imports declared Python `Tool`/hook symbols, namespaces them, loads MCP config, exposes Skill roots and passive assets/personas/commands, and rolls back conflicts.
- **Neutral values**: `SkillMetadata` / `MCPServerConfig` / `PluginManifest` / `HookContext` and friends carry no OpenAI namespaces, hosted services, account state, or Codex telemetry types.

## 10. Intentional differences

Deliberate simplifications/extensions relative to Codex:

- **Skill name safety**: installation requires filesystem-safe kebab-case names (`^[a-z0-9]+(?:-[a-z0-9]+)*$`, ≤ 64 chars), where Codex allows looser product-style naming.
- **Description colon repair**: third-party unquoted descriptions containing a colon receive a narrow compatibility repair (`_repair_colon_scalars`) so `yaml.safe_load` does not mis-parse colon-bearing scalars.
- **Git revisions resolve to immutable hashes**: `SkillInstaller` / `PluginInstaller` check out the requested revision as `FETCH_HEAD` and record the immutable `rev-parse HEAD` commit hash.
- **MCPB hardening**: `install_mcpb` enforces file-count and expanded-size limits and resolves `${__dirname}` placeholders only after extraction.
- **MCP protocol targeting**: Streamable HTTP targets `2026-07-28`; the client also interoperates with representative 2025 servers through an isolated `mcp==1.29.1` process (`test_official_mcp_1x_2025_protocol_compatibility`).
- **Plugin TOML overlay**: a compact `.super-harness/plugin.toml` adds an explicit framework version specifier and Python entry symbols; Codex manifest metadata is still imported best-effort.
- **Codex command/MCP hooks are metadata-only**: they are never auto-executed — running untrusted shell definitions would violate the explicit-enable Python contract.
- **Codex apps/interface stay passive**: apps and interface metadata are retained but not activated and reported as warnings.
- **Full 14-event hook surface**: includes future subagent points (`SUBAGENT_START` / `SUBAGENT_END`) declared before Phase 8 integration.
- **External compatibility checks are opt-in**: the default suite stays deterministic and offline; GitHub/MCP 1.x/Registry E2E require `SUPER_HARNESS_EXTERNAL_COMPAT=1`.

## 11. Failure model

The exception hierarchy (`exceptions.py`) is rooted at `SuperHarnessError(message, *, correlation_id=None, details=None)`, with `details` frozen to a `MappingProxyType`. Extension-layer exceptions:

- `SkillError(SuperHarnessError)` — missing/unclosed/invalid frontmatter, invalid or too-long name, missing description, empty instructions, resource escaping the directory or missing, install already present/name escaping the installation root/symlinks present, Git clone/checkout failure, missing or corrupt source metadata.
- `MCPError(SuperHarnessError)` — server disabled, connection failure, operation timeout, pagination/cursor/item limits exceeded, tool disabled by filter, MCPB integrity/manifest/path/symlink/size failures, registry request failure.
- `PluginError(SuperHarnessError)` — missing/invalid manifest, invalid name/version/framework compatibility, path escaping or leaving the plugin root, missing entry or symbol, duplicate tools, activation failure (wraps the underlying exception and rolls back).
- `HookError(SuperHarnessError)` — duplicate registration, unknown hook, mutation not allowed, denial not allowed for the event, `fail_closed` failure.

**Key failure rules**:

| Scenario | Behavior |
|---|---|
| Task cancellation (`CancelledError`) | re-raised unchanged by MCP `_run` and hook `dispatch`; never collapsed |
| MCP operation timeout | `MCPError("timed out")`; connection/other exceptions → `MCPError("failed")` |
| Hook callback timeout | per `failure_policy`: `FAIL_CLOSED` raises `HookError`; `WARN` emits a `RuntimeWarning`; `FAIL_OPEN` continues |
| Hook returns updates without `allow_modify` | `HookError("not allowed to modify")` |
| Hook denies a non-deniable event | `HookError("event cannot be denied")` |
| Skill/Plugin install conflict | `SkillError` / `PluginError("already installed")`, never overwrites |
| Conflict mid-plugin-activation | rolls back all registered Tools/Hooks, then `PluginError` |

**Default policy**: hooks default to `WARN` (`HookFailurePolicy.WARN`) — failures are traced and warned but do not block; plugin hooks can declare `fail_closed` or `fail_open` in the manifest. So **extension failures are normally observable traces plus a configurable gate**, never silently swallowed.

## 12. Extension points

- **Add a Skill**: any directory containing `SKILL.md` (frontmatter + instructions) placed in the explicit, project (`.agents/skills` / `.super-harness/skills`), user (`~/.super-harness/skills`), plugin, or system roots becomes discoverable; `SkillInstaller` installs local directories or GitHub subdirectories.
- **Add an MCP server**: use `MCPServerConfig` (stdio or Streamable HTTP) or import a common `mcpServers` JSON via `import_mcp_servers`; `as_tools` automatically translates it to `Tool`s carrying the `namespace` and `risk="external"` metadata.
- **Replace the registry implementation**: implement the `MCPRegistry` protocol (`search` / `get`) for any backend; `OfficialMCPRegistry` is the default official preview API adapter.
- **Write a plugin**: `PluginManifest` can contribute skills, tools (Python symbols), MCP config, hooks, assets, personas, commands, and `config_schema` / `config_defaults`; only `enable` activates them.
- **Register hooks**: `HookRegistry.register(event, handler, *, priority, timeout, failure_policy, allow_modify, source)`; denial is allowed on `USER_PROMPT` / `BEFORE_MODEL` / `PRE_TOOL_USE` / `PRE_COMPACT`, and data mutation with `allow_modify=True`.
- **Consume traces**: inject sinks for `HookRegistry(trace_sink=...)`, `PluginManager(trace_sink=...)`, and `MCPClient(observer=...)` for application-level audit and observability.

## 13. Tests

- **`tests/test_skills.py`**:
  - `test_skill_progressive_discovery_precedence_activation_and_resources` — metadata-first discovery, explicit > project > user precedence, collision reporting, activation reading instructions, resource confinement (`../outside.txt` raises `SkillError("escapes")`).
  - `test_skill_validation_local_install_metadata_and_remove` — local install provenance, duplicate rejection, removal, missing-frontmatter/invalid-name rejection.
  - `test_pinned_codex_skill_is_compatible_external_fixture` — parsing compatibility against the pinned `references/codex/.codex/skills/code-review` fixture.
  - `test_install_pinned_github_subdirectory_skill` (`@pytest.mark.e2e`, requires `SUPER_HARNESS_EXTERNAL_COMPAT=1`) — installs a pinned GitHub subdirectory Skill.
- **`tests/test_mcp.py`**:
  - `test_real_stdio_mcp_tools_resources_prompts_and_adapter` (`@pytest.mark.integration`) — a real stdio server's tools/resources/prompts, `as_tools` adaptation, and `mcp.connected` / `mcp.call.started` / `mcp.call.completed` events.
  - `test_real_streamable_http_uses_2026_protocol_and_filter` (`@pytest.mark.integration`) — Streamable HTTP `protocol_version == "2026-07-28"`, `exclude_tools` filtering, `as_tools` qualified names.
  - `test_mcp_timeout_is_typed_and_cancellation_propagates` (`@pytest.mark.integration`) — timeouts map to `MCPError("timed out")`; `task.cancel()` propagates `CancelledError`.
  - `test_import_common_mcp_servers_config` — `import_mcp_servers` mapping for stdio/HTTP/headers/timeout/excludeTools.
  - `test_mcpb_integrity_safe_install_and_traversal_rejection` — SHA-256 integrity, safe install, `${__dirname}` resolution, traversal (`../escape.py`) rejection.
  - `test_replaceable_registry_adapter_normalizes_preview_api` — `OfficialMCPRegistry.search` / `get` normalization against the preview API via `MockTransport`.
  - `test_official_mcp_1x_2025_protocol_compatibility` / `test_real_official_registry_search` (`@pytest.mark.e2e`) — isolated `mcp==1.29.1` interop and a real registry search.
- **`tests/test_plugins.py`**:
  - `test_plugin_install_enable_bundle_disable_update_and_remove` (`@pytest.mark.integration`) — install without enable, enable bundles capabilities (skills/MCP/hooks), namespaced tools execute through `ToolExecutor` (`echo` → `HELLO`), disable unregisters, update to 1.1.0, remove, and the `PluginTrace` sequence.
  - `test_plugin_validation_codex_import_conflicts_and_no_auto_execution` — install executes no code (no `marker`), enable imports (marker appears), tool-conflict rollback (`hooks.list() == ()`), framework version incompatibility, path escape (`./../outside`), and Codex manifest import (`format == "codex"`).
  - `test_official_codex_plugin_repository_compatibility` (`@pytest.mark.e2e`) — installs the pinned `openai/plugins` `plugin-eval` subdirectory.
- **`tests/test_hooks.py`**:
  - `test_all_hook_events_are_ordered_observable_and_modification_is_explicit` — ordered dispatch across all 14 events, data enrichment (`value=2`), trace completeness, explicit `allow_modify`.
  - `test_hook_failure_policies_timeout_denial_and_cancellation` — WARN warning, FAIL_OPEN continues, FAIL_CLOSED raises `HookError`, `PRE_TOOL_USE` denial, cancellation propagation.
  - `test_runtime_and_tool_pipeline_dispatch_hooks` — a real `Agent`'s session/prompt/turn/before/after/tool hook ordering and `PRE_TOOL_USE` argument rewriting taking effect.
  - `test_error_and_compaction_hooks` — `PRE_COMPACT` / `POST_COMPACT` / `ERROR` dispatch and `BEFORE_MODEL` denial.
- Related: `tests/test_cli.py` covers `test_skill_full_lifecycle`, `test_mcp_stdio_remote_import_inspect_remove_and_redaction`, `test_mcp_bundle_integrity_install_and_cleanup`, `test_mcp_store_rejects_duplicate_import`, and `test_plugin_full_lifecycle` at the CLI level.

## 14. Limitations/future work

- **Git installs need network and git**: remote paths in `SkillInstaller` / `PluginInstaller` shell out to `git clone` (`--depth 1`), requiring `git` on PATH and network access; non-`github.com/tree/` hosts do not support the subdirectory form (whole-repository only).
- **Plugin Python is trusted in-process code**: `enable`'s `importlib` import runs arbitrary plugin code inside the event loop; plugins are treated as application-level trusted extensions, and installation performs structural validation only, no code audit. Review untrusted plugins manually before enabling.
- **MCP has no runtime dynamic discovery**: `as_tools` enumerates tools at connection time; full runtime dynamic discovery/selection of remote tools by the model belongs to a later ecosystem phase.
- **The official registry is a preview API**: `OfficialMCPRegistry` targets the official registry v0.1 preview endpoints, whose protocol is versioned independently of the runtime — hence the replaceable `MCPRegistry` protocol behind it; there is no local cache or offline support for search/get.
- **`SUPER_HARNESS_EXTERNAL_COMPAT` gating**: network-dependent E2E (GitHub subdirectory install, MCP 1.x interop, real registry search) is skipped by default so the default suite stays deterministic and offline.
- **Hooks are in-process interceptors**: there is no cross-process or distributed hook proxy; traces are emitted through sinks, but collection/export backends are the application's choice.
- **No cross-process extension state**: `PluginManager`, `HookRegistry`, `ToolRegistry`, and MCP connections are single-process structures; recovering extension state across processes belongs to the persistence extensions.

## Related links

- Runnable examples:
  - [`25_skill_discovery.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/25_skill_discovery.py) / [`26_skill_activation.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/26_skill_activation.py) / [`27_skill_install.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/27_skill_install.py) — Skill discovery/activation/install
  - [`28_mcp_stdio_list.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/28_mcp_stdio_list.py) / [`29_mcp_stdio_call.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/29_mcp_stdio_call.py) / [`30_mcp_stdio_resources.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/30_mcp_stdio_resources.py) / [`31_mcp_http_list.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/31_mcp_http_list.py) / [`32_mcp_http_call.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/32_mcp_http_call.py) / [`33_mcp_http_prompts.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/33_mcp_http_prompts.py) — MCP stdio/HTTP
  - [`34_mcp_config_import.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/34_mcp_config_import.py) / [`35_mcpb_install.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/35_mcpb_install.py) / [`36_mcp_registry.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/36_mcp_registry.py) — MCP config/MCPB/registry
  - [`37_plugin_install.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/37_plugin_install.py) / [`38_plugin_capabilities.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/38_plugin_capabilities.py) / [`39_plugin_lifecycle.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/39_plugin_lifecycle.py) / [`42_plugin_hook.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/42_plugin_hook.py) — plugin lifecycle and plugin hooks
  - [`40_hook_logging.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/40_hook_logging.py) / [`41_hook_pre_tool_policy.py`](https://github.com/Sitozzmonash/superharness/blob/main/examples/41_hook_pre_tool_policy.py) — hook logging and pre-tool policy
- Related Internals: architecture and cross-cutting boundaries (Internals 1), Agent/Thread/Turn (Internals 2), tool layer (Internals 4), external knowledge and memory (Internals 5), autonomous orchestration (Internals 7), observability and persistence (Internals 8).
- Source: `src/super_harness/skills/`, `src/super_harness/mcp/`, `src/super_harness/plugins/`, `src/super_harness/hooks/`, `src/super_harness/tools/definition.py`, `src/super_harness/tools/registry.py`, `src/super_harness/exceptions.py`.
- Research: `docs/research/codex/skills-and-mcp.md`, `docs/research/codex/plugins-and-hooks.md`.