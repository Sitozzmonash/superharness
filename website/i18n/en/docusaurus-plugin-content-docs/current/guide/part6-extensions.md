---
id: guide-part6-extensions
title: 'User Guide Part VI: Instructions & Extensions'
sidebar_position: 6
description: "Full usage guide for Personas & roles, AGENTS.md discovery, Agent Skills, MCP, plugins, and hooks."
---

# User Guide Part VI: Instructions & Extensions

This part covers six mechanisms for instructing an Agent and injecting capabilities into the runtime, together with their lifecycles and security boundaries:

- **Persona and roles** — package "who I am, what I must do, what I must not do" into a typed identity layer reused via `Agent(..., persona=...)`.
- **AGENTS.md** — instruction files discovered level by level from the nearest repository root down to the working directory.
- **Agent Skills** — discovery, activation, local/GitHub installation, and authoring of standard `SKILL.md` packages.
- **MCP** — connect external Model Context Protocol servers over stdio and Streamable HTTP, import common configs, install `.mcpb` bundles, and query the official registry.
- **Plugins** — bundle Skills, namespaced Tools, MCP definitions, Hooks, assets, personas, and commands into an installable, explicitly enableable unit.
- **Hooks** — register callbacks at session/turn/tool/model lifecycle points for observability and application policy.

All examples are runnable as-is; the code is quoted verbatim from the `examples/` directory, with links to the complete runnable files.

---

## 1. Persona and Roles

### What is this / When to use

A `Persona` is a **typed identity and configuration layer**. It combines a name, role, goal, constraints, and application instructions into developer authority; filters Tools by qualified-name glob; records Skill and memory scope; and can hold named subagent role templates.

When you pass a Persona to `Agent(..., persona=persona)`, the Agent will:

1. Validate the optional model override (`persona.validate_provider(provider)`);
2. Filter the configured tools by `persona.tool_scopes` (`persona.select_tools(...)`);
3. Compose unified instructions via `persona.compose_instructions(...)`;
4. Store non-secret persona metadata (`persona.metadata()`) with each new Thread.

Use a Persona when multiple Agents must share the same identity and constraints, or when you want to package "model choice + tool visibility + instructions" into one reusable object.

### Prerequisites

- `super-harness` installed (`pip install -e .`).
- A configured provider environment variable (for example `DEEPSEEK_API_KEY`) when running an Agent.

### Quick start

```python
from super_harness import Persona

persona = Persona("Ari", "release reviewer", "Find release blockers", constraints=("Cite evidence",))
print(persona.compose_instructions("Review the candidate."))
```

### Configuration

`Persona` is a frozen dataclass with these fields:

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `name` | `str` | (required) | Identity name, must match `[A-Za-z0-9][A-Za-z0-9._ -]{0,63}` |
| `role` | `str` | (required) | Role, e.g. `release reviewer` |
| `goal` | `str` | (required) | Goal, e.g. `Find release blockers` |
| `instructions` | `str` | `""` | Additional instruction text |
| `constraints` | `tuple[str, ...]` | `()` | Constraint list |
| `model_override` | `str \| None` | `None` | Required model name; validated at Agent construction |
| `tool_scopes` | `tuple[str, ...]` | `("*",)` | Qualified-name globs used to filter tools |
| `skill_scopes` | `tuple[str, ...]` | `("*",)` | Allowed Skill scopes |
| `memory_scope` | `str` | `"thread"` | `none` / `thread` / `long_term` / `both` |
| `subagent_roles` | `Mapping[str, Persona]` | `{}` | Named subagent role templates |

Construction validates immediately: `name` syntax, non-empty `role`/`goal`, the `memory_scope` value, non-empty scopes, and that a Persona may not list itself as a subagent role.

### Basic example: compose identity instructions

Generate stable, structured instruction text from a `Persona`:

```python
"""Compose stable Agent identity instructions."""

from super_harness import Persona

persona = Persona("Ari", "release reviewer", "Find release blockers", constraints=("Cite evidence",))
print(persona.compose_instructions("Review the candidate."))
```

`compose_instructions` emits sections in the order `Identity` / `Role` / `Goal` / `Instructions` / `Constraints` / `Application instructions` for the model to consume.

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/75_persona_identity.py)

### Real-world example: explicit tool and Skill scopes

Control which tools a Persona can see with qualified-name globs:

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

`select_tools` keeps only tools whose `qualified_name` matches any glob in `tool_scopes` (here `repo.inspect` matches `repo.*`).

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/76_persona_scopes.py)

### Advanced example: named subagent role templates and Agent integration

A Persona can hold named subagent role templates, which take effect when handed to `Agent(..., persona=...)`:

```python
"""Select a named subagent persona template."""

from super_harness import Persona

tester = Persona("Tester", "test specialist", "Verify acceptance criteria")
lead = Persona("Lead", "delivery lead", "Ship safely", subagent_roles={"tester": tester})
print(lead.subagent("tester").metadata())
```

`lead.subagent("tester")` returns the template Persona; `metadata()` returns a non-secret snapshot (`persona`, `role`, `memory_scope`, `skill_scopes`).

To integrate with an Agent, pass the Persona as a keyword argument:

```python
from super_harness import Agent, DeepSeekProvider, Persona

persona = Persona("Ari", "release reviewer", "Find release blockers")
agent = Agent(DeepSeekProvider(), persona=persona)
print(agent.name, agent.role, agent.memory_scope)
```

`Agent` filters tools via `persona.select_tools`, composes instructions via `persona.compose_instructions`, and stores `persona.metadata()` on the new Thread.

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/77_persona_subagent_roles.py)

### API quick reference

```python
Persona(name, role, goal, instructions="", constraints=(), model_override=None,
        tool_scopes=("*",), skill_scopes=("*",), memory_scope="thread",
        subagent_roles={})
persona.compose_instructions(additional=None) -> str
persona.validate_provider(provider)          # validates model_override against provider.model
persona.select_tools(tools) -> tuple[Tool, ...]
persona.subagent(role) -> Persona            # KeyError for unknown roles
persona.metadata() -> dict                   # {"persona","role","memory_scope","skill_scopes"}
Agent(..., persona=persona)
```

### Errors / validation

- `ValueError("persona name is invalid")` — invalid `name`.
- `ValueError("persona role and goal are required")` — empty `role` or `goal`.
- `ValueError("persona memory_scope is invalid")` — `memory_scope` not one of the four values.
- `ValueError("persona scopes may not be empty")` — an empty entry inside a scope.
- `ValueError("persona may not contain itself as a named subagent role")` — self-reference.
- At `Agent` construction, `validate_provider` raises `ValueError` when `model_override` differs from the provider's actual model.

### Security notes

- Persona instructions are **developer authority** and can override default instructions, so only trust their origin.
- `persona.metadata()` exposes non-secret fields only; keep secrets out of persona files.

### Troubleshooting

- Model mismatch: ensure `model_override` matches the configured provider model.
- Tools invisible: check that `tool_scopes` globs cover the target tool's `qualified_name` (e.g. `repo.*` vs `repo.inspect`).

---

## 2. AGENTS.md

### What is this / When to use

`AGENTS.md` is the project instruction file, discovered level by level by `AgentsMdLoader` **from the nearest repository root down to the current working directory**, then injected into context. It puts "how this project should be worked on" into files that version with the codebase.

Typical setup: a general `AGENTS.md` at the repository root plus more local `AGENTS.override.md` files in subdirectories; each layer contributes instructions to the context in hierarchy order.

### Prerequisites

- The working directory sits inside a repository marked by a root marker (default `root_markers=(".git",)`).
- Directories contain `AGENTS.md` or `AGENTS.override.md` files.

### Quick start

```python
from super_harness import AgentsMdLoader

fragments = AgentsMdLoader().load(".")
for fragment in fragments:
    print(fragment.content)
```

Passing `cwd=...` to `Agent` runs the loader automatically:

```python
from super_harness import Agent, DeepSeekProvider

thread = Agent(DeepSeekProvider(), cwd=".").thread()
print(thread.debug_context())
```

### Configuration (discovery rules)

Configurable fields of `AgentsMdLoader`:

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `root_markers` | `tuple[str, ...]` | `(".git",)` | File markers that identify the repository root |
| `max_bytes` | `int` | `32_768` | Combined byte budget for all fragments (32 KiB) |
| `filenames` | `tuple[str, ...]` | `("AGENTS.override.md", "AGENTS.md")` | Per-directory search order |

Discovery rules:

1. `project_root(cwd)` walks upward from `cwd` and returns the first directory containing a `.git` marker; if none is found it returns `cwd`.
2. For every directory from the root down to `cwd`, check `AGENTS.override.md` first, then `AGENTS.md`; per directory only the first hit is taken.
3. **Never search above the repository root** — the boundary stops discovery.
4. Total content is capped at `max_bytes`; anything beyond is truncated.
5. Each fragment is a `ContextFragment(ContextKind.PROJECT, content, path, USER, metadata={"path": ...})` — external **user-role** data that cannot override developer or project instructions.

### Basic example: `AGENTS.override.md` precedes `AGENTS.md`

In the same directory, `AGENTS.override.md` takes precedence over `AGENTS.md`:

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

Only `override` is printed because the override file is read first.

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/90_agents_override_precedence.py)

### Real-world example: the repository boundary

Discovery stops at the nearest repository root and never reads `AGENTS.md` files above it:

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

The root of `load(child)` is `repo` (it contains `.git`), so only `inside` is read; `outside` is excluded.

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/91_agents_repository_boundary.py)

### Advanced example: nested hierarchy and redacted context inspection

Put one directive at the root and another in a subdirectory, then inspect the prioritized, sourced, redacted snapshot via `thread.debug_context()`:

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

`debug_context()` returns a redacted snapshot; sensitive values (like `api_key=...`) are redacted.

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/08_agents_context_debug/main.py)

### API quick reference

```python
AgentsMdLoader(root_markers=(".git",), max_bytes=32768,
               filenames=("AGENTS.override.md", "AGENTS.md"))
loader.project_root(cwd) -> Path
loader.discover(cwd) -> tuple[Path, ...]      # matched file paths, root to cwd
loader.load(cwd) -> tuple[ContextFragment, ...]
Agent(..., cwd=...)                            # Agent injects AGENTS.md fragments automatically
thread.debug_context() -> ContextDebugSnapshot  # redacted snapshot
```

### Errors / limits

- `ValueError("AGENTS.md cwd must be a directory")` — `cwd` is not a directory.
- Budget of 32 KiB: excess is truncated; for a larger budget construct `AgentsMdLoader(max_bytes=...)` yourself and assemble fragments manually.
- `AGENTS.md` fragments carry user role and cannot override developer/project instructions.

### Troubleshooting

- Instructions missing: confirm the directory is inside a repository with a `.git` marker and the file is named `AGENTS.md` or `AGENTS.override.md`.
- Reading outer-directory instructions: check for a missing repository root marker (`.git`); the boundary stops there.
- Keen to keep both an override and a base file in one directory: only one is taken per directory (`AGENTS.override.md` wins).

---

## 3. Agent Skills

### What is this / When to use

A Skill is a **standard `SKILL.md` package**: a directory with YAML frontmatter (`name`, `description`) plus body instructions, and optional accompanying reference/template/script resources. Super Harness discovers them via `SkillCatalog` with **metadata-first progressive loading** and installs them locally or from Git/GitHub via `SkillInstaller`.

Use Skills to inject reusable, on-demand domain knowledge or workflows (code-review checklists, release scripts, documentation conventions) into an Agent.

### Prerequisites

- The project contains `.agents/skills/` or `.super-harness/skills/` (or explicit paths passed to discovery).
- Each Skill directory contains a `SKILL.md`.

### Quick start

```python
from super_harness import SkillCatalog

catalog = SkillCatalog.discover(cwd=".")
skill = catalog.activate("code-review")
print(skill.instructions)
```

### Configuration (discovery and scopes)

`SkillCatalog.discover(...)` merges the following roots in order (late duplicates are recorded in `collisions`):

| Source | Path | `source` tag |
| --- | --- | --- |
| `explicit` | paths passed by the caller | `explicit` |
| Project (`.agents`) | `<project>/.agents/skills` | `project-agents` |
| Project (`.super-harness`) | `<project>/.super-harness/skills` | `project-super-harness` |
| User | `~/.super-harness/skills` (or `user_root`) | `user` |
| Plugin | paths from `plugin_roots` | `plugin` |
| System | paths from `system_roots` | `system` |

Discovery parses and caches only `name` and `description` (metadata); **activation** of a selected Skill reads its instruction body, and supporting files (`references/`, `templates/`, `scripts/`) stay unloaded until explicitly requested.

### The `SKILL.md` structure

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

Parsing rules (`parse_skill`):

- `SKILL.md` must start with `---` and have a closed YAML frontmatter.
- `name` comes from the frontmatter or the directory name, must match `[a-z0-9]+(?:-[a-z0-9]+)*`, and be at most 64 characters.
- `description` is required and non-blank.
- Remaining frontmatter keys are preserved verbatim in `extra`.
- Upon activation, the body (everything after the frontmatter) becomes `instructions` and must be non-empty.

### Basic example: discover and list Skills

```python
from super_harness import SkillCatalog

catalog = SkillCatalog.discover(cwd=".")
for skill in catalog.list():
    print(skill.name, skill.description, skill.source)
```

`list()` returns metadata (`SkillMetadata`) only — names/descriptions, with instruction bodies unloaded.

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/25_skill_discovery.py)

### Real-world example: activate and read instructions plus support files

```python
from super_harness import SkillCatalog

catalog = SkillCatalog.discover(cwd=".")
skill = catalog.activate("code-review")
print(skill.instructions)
# Supporting files stay unloaded until explicitly requested:
# print(skill.read_resource("references/checklist.md").decode())
```

`activate(name)` returns an `ActivatedSkill`; its `read_resource(relative_path)` reads package resources on demand (bounded to the Skill directory to prevent path escape).

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/26_skill_activation.py)

### Advanced example: install a Skill from a local path

`SkillInstaller` installs into a destination directory and records provenance metadata:

```python
from super_harness import SkillInstaller

installer = SkillInstaller(".super-harness/skills")
installed = installer.install("./my-skill")
print(installed.name, installed.path)
```

`install(source)` accepts three source kinds:

- **Local paths** (e.g. `./my-skill`).
- **HTTPS Git repositories** (`https://...` or `git+https://...`).
- **GitHub `/tree/<revision>/<subdir>` URLs**: install from a specified subdirectory of a branch/tag/commit (e.g. `https://github.com/owner/repo/tree/main/skills/code-review`).

Installation writes `.super-harness-source.json` (`source_type`, `location`, `revision`, `installed_at`). The installer **never overwrites** an existing Skill, rejects symbolic links and path escape, and records the resolved commit. Additional methods: `info` / `list` / `update` / `remove`.

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/27_skill_install.py)

### Writing a Skill (recommended layout)

```
my-skill/
├── SKILL.md
└── references/
    └── checklist.md
```

- The `SKILL.md` frontmatter requires at least `name` and `description`.
- In the body, write trigger conditions, numbered steps, a pitfalls section, and verification steps (concise and executable).
- Keep lengthy content in `references/`, `templates/`, `scripts/`, read on demand via `ActivatedSkill.read_resource`.
- Use lowercase hyphenated names (e.g. `code-review`).

### API quick reference

```python
SkillCatalog.discover(cwd=None, explicit=(), user_root=None,
                      plugin_roots=(), system_roots=()) -> SkillCatalog
catalog.list() -> tuple[SkillMetadata, ...]
catalog.get(name) -> SkillMetadata
catalog.activate(name) -> ActivatedSkill     # reads the instruction body
activated.read_resource(relative_path) -> bytes
parse_skill(path, *, source="runtime") -> SkillMetadata
activate_skill(metadata) -> ActivatedSkill
SkillInstaller(destination)                   # see install/info/list/update/remove
installer.install(source) -> SkillMetadata
```

### Errors / troubleshooting

- `SkillError("SKILL.md is missing YAML frontmatter")` — frontmatter missing.
- `SkillError("skill name must contain lowercase letters, numbers, and hyphens")` — invalid name.
- `SkillError("skill description is required")` — description missing.
- `SkillError("skill ... is already installed")` — destination exists; the installer does not overwrite.
- `SkillError("skill packages may not contain symbolic links")` / `"... escapes installation root"` — security checks.
- `SkillError("unknown skill ...")` — activated an undiscovered Skill; confirm `discover` covers it.

---

## 4. MCP (Model Context Protocol)

### What is this / When to use

MCP lets the Agent connect to external servers over a standard protocol, exposing Tools, Resources, and Prompts. Super Harness adapts the **official Python SDK** through `MCPClient`, with two first-class transports: **stdio** (local subprocess) and **Streamable HTTP** (remote URL).

Use MCP to wire external capabilities (filesystem, databases, remote APIs) in as Agent-callable tools, or to reuse an existing `mcpServers` configuration.

### Prerequisites

- The official MCP SDK (`mcp` package) installed.
- A runnable local executable (stdio) or reachable HTTP endpoint (Streamable HTTP).

### Quick start

```python
import asyncio

from super_harness import MCPClient, MCPServerConfig, MCPTransport


async def main() -> None:
    config = MCPServerConfig("remote", MCPTransport.STREAMABLE_HTTP, url="http://127.0.0.1:8000/mcp")
    async with MCPClient(config) as client:
        print(client.protocol_version, await client.list_tools())


asyncio.run(main())
```

### Configuration

`MCPTransport` enum: `STDIO = "stdio"`, `STREAMABLE_HTTP = "streamable_http"`.

`MCPServerConfig` fields:

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `name` | `str` | (required) | Server name (non-empty) |
| `transport` | `MCPTransport` | (required) | Transport type |
| `command` | `str \| None` | `None` | stdio executable command (required) |
| `args` | `tuple[str, ...]` | `()` | stdio arguments |
| `env` | `Mapping[str, str]` | `{}` | Subprocess environment |
| `cwd` | `Path \| None` | `None` | Subprocess working directory |
| `url` | `str \| None` | `None` | HTTP endpoint (required) |
| `headers` | `Mapping[str, str]` | `{}` | HTTP request headers |
| `timeout` | `float` | `30.0` | Per-operation timeout (positive) |
| `enabled` | `bool` | `True` | When disabled, no connection is made |
| `include_tools` | `tuple[str, ...]` | `()` | Allowlist (empty = all) |
| `exclude_tools` | `tuple[str, ...]` | `()`` | Denylist |

Validation: `name` non-empty and `timeout > 0`; stdio requires `command`; HTTP requires `url`. `MCPClient` must be used as an **async context manager**.

### Basic example: list tools over stdio

```python
import asyncio

from super_harness import MCPClient, MCPServerConfig, MCPTransport


async def main() -> None:
    config = MCPServerConfig("demo", MCPTransport.STDIO, command="python", args=("server.py",))
    async with MCPClient(config) as client:
        print([tool.name for tool in await client.list_tools()])


asyncio.run(main())
```

stdio mode spawns a subprocess (`python server.py`) and communicates with it.

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/28_mcp_stdio_list.py)

### Real-world example: call tools and read resources over stdio

Call a remote tool:

```python
import asyncio

from super_harness import MCPClient, MCPServerConfig, MCPTransport


async def main() -> None:
    config = MCPServerConfig("math", MCPTransport.STDIO, command="python", args=("server.py",))
    async with MCPClient(config) as client:
        print(await client.call_tool("add", {"left": 20, "right": 22}))


asyncio.run(main())
```

List and read resources (`list_resources` / `read_resource`):

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

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/29_mcp_stdio_call.py) · [Resources example](https://github.com/Sitozzmonash/superharness/blob/main/examples/30_mcp_stdio_resources.py)

### Advanced example: Streamable HTTP calls and Prompts

Call a tool on a remote HTTP server:

```python
import asyncio

from super_harness import MCPClient, MCPServerConfig, MCPTransport


async def main() -> None:
    config = MCPServerConfig("remote", MCPTransport.STREAMABLE_HTTP, url="http://127.0.0.1:8000/mcp")
    async with MCPClient(config) as client:
        print(await client.call_tool("add", {"left": 2, "right": 3}))


asyncio.run(main())
```

List and fetch Prompts:

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

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/32_mcp_http_call.py) · [HTTP list](https://github.com/Sitozzmonash/superharness/blob/main/examples/31_mcp_http_list.py) · [Prompts example](https://github.com/Sitozzmonash/superharness/blob/main/examples/33_mcp_http_prompts.py)

### Importing an existing `mcpServers` config

`import_mcp_servers` accepts the common `{ "mcpServers": ... }` JSON (file path or Mapping) and converts it into an `MCPServerConfig` tuple:

```python
from super_harness import import_mcp_servers

configs = import_mcp_servers("mcp.json")
for config in configs:
    print(config.name, config.transport)
```

Both `url` (→ Streamable HTTP) and `command`/`args` (→ stdio) shapes are supported, along with `env`, `headers`, `cwd`, `timeout`, `disabled`, `includeTools`, and `excludeTools`. On the CLI side, `MCPConfigStore` persists these configs (`super-harness mcp add/import/...`).

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/34_mcp_config_import.py)

### Installing an MCP Bundle (`.mcpb`)

A `.mcpb` is a portable local-server packaging format. Validate first with `inspect_mcpb` (SHA-256, archive safety, required manifest fields), then install with `install_mcpb`:

```python
from super_harness import install_mcpb

bundle = install_mcpb("server.mcpb", ".super-harness/mcp", expected_sha256="EXPECTED_SHA256")
print(bundle.name, bundle.config.command, bundle.config.args)
```

Checks include: SHA-256 integrity, no duplicate archive paths, `manifest.json` required, file count ≤ 10,000, total uncompressed size ≤ 256 MiB, no absolute paths/`..` escape/symlinks, a filesystem-safe `name`, and a server entry point (`uv`/`python`) or explicit `mcp_config` command. After installation, `${__dirname}` in `command`/`args`/`env` is resolved to the actual install directory.

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/35_mcpb_install.py)

### The MCP Registry (official)

`OfficialMCPRegistry` accesses the official registry preview endpoint:

```python
import asyncio

from super_harness import OfficialMCPRegistry


async def main() -> None:
    for server in await OfficialMCPRegistry().search("filesystem", limit=5):
        print(server)


asyncio.run(main())
```

`search(query, limit)` and `get(name, version)` hit the `/v0.1/servers` endpoints. **Registry discovery is not trust and not auto-install** — installation and review remain your responsibility.

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/36_mcp_registry.py)

### MCP 2026 compatibility notes

- The protocol revision target is **`2026-07-28`** (where supported by the official/Tier-1 SDK), while retaining pragmatic compatibility with representative 2025-era servers.
- First-class transports are stdio and Streamable HTTP; **do not assume legacy transport-level sessions in the Agent core**.
- Protocol negotiation is handled by the official SDK (exposed via `protocol_version` and `capabilities`).
- MCPB is a supported portable local-server packaging path; the official registry is an optional, isolated runtime capability (the registry remains in preview).

### API quick reference

```python
MCPServerConfig(name, transport, command=None, args=(), env={}, cwd=None,
                url=None, headers={}, timeout=30.0, enabled=True,
                include_tools=(), exclude_tools=())
async with MCPClient(config, observer=None) as client: ...
client.protocol_version / client.capabilities
await client.list_tools() / call_tool(name, arguments=None)
await client.list_resources() / read_resource(uri)
await client.list_prompts() / get_prompt(name, arguments=None)
await client.as_tools() -> tuple[Tool, ...]     # named after config.name, source="mcp", risk="external"
import_mcp_servers(value) -> tuple[MCPServerConfig, ...]
inspect_mcpb(path, expected_sha256=None) -> MCPBundle
install_mcpb(path, destination, expected_sha256=None) -> MCPBundle
OfficialMCPRegistry(base_url=..., timeout=20.0, client=None).search/get
```

### Events

`MCPClient` emits events through the optional `observer`:

- `mcp.connected` — successful connection with `server`, `transport`, `protocol_version`.
- `mcp.call.started` / `mcp.call.completed` / `mcp.call.failed` — per-operation start/completion/failure with `operation`, `operation_id`, `duration_ms`, `error_class`.

### Errors / timeouts / retries

- Connection failure: `MCPError("MCP server ... connection failed")`.
- Disabled server: `MCPError("MCP server ... is disabled")` (`enabled=False`).
- Filter hit: `call_tool` raises `MCPError("MCP tool ... is disabled by filter")` for tools outside the allowlist or inside the denylist.
- Timeouts: each operation is bounded by `config.timeout`; timeouts raise `MCPError("MCP <op> timed out")`; other failures raise `MCPError("MCP <op> failed")`.
- Catalog pagination is capped at 20 pages / 1,000 items; exceeding the cap raises `MCPError`.

### Combining with other features

`await client.as_tools()` converts remote tools into `Tool` values (`namespace=config.name`, `source="mcp"`, `risk="external"`) that can be handed straight to `Agent(tools=...)` or a `ToolRegistry`. Remote tools flow through the normal tool abstraction, approval, and timeouts.

### Security notes

- Treat remote tools and resources as **untrusted external input**.
- Narrow the exposure with `include_tools`/`exclude_tools`.
- Configure a bounded `timeout`; use HTTPS and controlled headers for HTTP.
- Keep external MCP tools behind allowlists, approval, bounded timeouts, and HTTPS credentials.
- Validate `expected_sha256` when installing a `.mcpb`.

### Troubleshooting

- `ValueError("stdio MCP requires command")` / `ValueError("Streamable HTTP MCP requires url")` — configuration/transport mismatch.
- Connection failure: confirm the server is executable/endpoint reachable and the `mcp` SDK is installed.
- Tools missing: check `include_tools`/`exclude_tools` filters.
- CLI configuration: `super-harness mcp add <name> --stdio -- python server.py`, `super-harness mcp add <name> --url <url>`, `super-harness mcp import ./mcp.json`, `super-harness mcp add ./server.mcpb --sha256 <digest>`, `super-harness mcp search <query>`, `super-harness mcp list/inspect/remove <name>`.

---

## 5. Plugins

### What is this / When to use

A plugin bundles multiple capabilities into one **installable, explicitly enableable** unit: Skills, namespaced Tools, MCP definitions, Hooks, assets, personas, and commands. Plugin **installation is data-only**; a plugin stays disabled until explicitly `enable`d, and `enable` is the trust boundary at which declared `./file.py:symbol` entries are executed.

Use a plugin to package a related set of capabilities (say, a release-tooling bundle with matching Skills and hooks) for distribution, with activation controlled at the application layer.

### Prerequisites

- A plugin source directory with a manifest: `.super-harness/plugin.toml` (native) or `.codex-plugin/plugin.json` (Codex-compatible, best-effort import).

### Quick start

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

### Configuration (`plugin.toml`)

`load_plugin` reads `.super-harness/plugin.toml`; the shape is `[plugin]`, `[capabilities]`, `[[hooks]]`:

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

Rules:

- Every relative capability path (e.g. `./tools.py:release_tools`, `./skills`) must start with `./` and stay inside the plugin root; `..` escapes are forbidden.
- Tool entries use the `./file.py:symbol` form with a `.py` suffix; the symbol is imported at enable time.
- `requires_super_harness` is validated against the current package version with a PEP 440 constraint.
- Unknown fields are recorded in `warnings` (non-blocking).
- Manifest validation **never imports** plugin Python; only `enable` imports the declared entries.

### Basic example: install a plugin

```python
from super_harness import PluginInstaller

installer = PluginInstaller(".super-harness/plugins")
installed = installer.install("./plugins/release-tools")
print(installed.manifest.name, installed.manifest.version, installed.source)
```

`install(source)` accepts a local directory or an HTTPS Git/GitHub source (including `/tree/<rev>/<subdir>`), writes `.super-harness-source.json`, and rejects symbolic links and path escape. It returns an `InstalledPlugin` (with `enabled=False` at this point).

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/37_plugin_install.py)

### Real-world example: enable and inspect capabilities

`PluginManager.enable(name)` loads tools, MCP servers, and hooks, registering them into the registries you provided:

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

`PluginCapabilities` returns `plugin`, `skills`, `tools`, `mcp_servers`, `hooks`, `assets`, `personas`, `commands`. Plugin tools are namespaced as `manifest.name`, MCP servers are named `<plugin>.<server>`, and hooks register with `source="plugin:<name>"`. A failed enable rolls back the tools/hooks already registered.

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/38_plugin_capabilities.py)

### Advanced example: lifecycle management

```python
from super_harness import PluginInstaller, PluginManager

manager = PluginManager(PluginInstaller(".super-harness/plugins"))
for installed in manager.list():
    print(installed.manifest.name, installed.enabled, installed.source)
manager.update("release-tools")  # disabled plugins only
manager.remove("release-tools")
```

`update` and `remove` **apply to disabled plugins only** (raising `PluginError` while enabled); `list` shows enable state and source metadata.

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/39_plugin_lifecycle.py)

### Plugins carrying Hooks

Enabling a plugin registers its declared hooks:

```python
from super_harness import HookRegistry, PluginInstaller, PluginManager

hooks = HookRegistry()
manager = PluginManager(PluginInstaller(".super-harness/plugins"), hooks=hooks)
capabilities = manager.enable("release-tools")
print("registered plugin hooks:", capabilities.hooks)
```

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/42_plugin_hook.py)

### Writing a plugin

```
plugins/release-tools/
├── .super-harness/
│   └── plugin.toml
├── skills/            # optional Skill package directories
├── tools.py           # exports Tool values or an iterable of Tools
├── hooks.py           # exports hook handlers
└── assets/            # passive assets
```

`tools.py` exports a `Tool` value or an iterable of `Tool`s; `hooks.py` exports the callables referenced by `[[hooks]]`. All relative paths start with `./` and stay inside the plugin root.

### Codex plugin import

`load_plugin` also reads `.codex-plugin/plugin.json`: `skills` (string or array), `mcpServers` (path, inline object, or `.mcp.json`), and `hooks`/`commands`/`assets`/`agents` (metadata). Codex command/MCP hooks and apps/interface are **retained as metadata only and never auto-executed**, producing `warnings`.

### API quick reference

```python
PluginInstaller(destination)                  # install/update/remove/list/info
PluginManager(installer, tools=None, hooks=None, trace_sink=None)
manager.install(source) -> InstalledPlugin
manager.enable(name) -> PluginCapabilities    # trust boundary: imports ./file.py:symbol
manager.disable(name)
manager.update(name) / manager.remove(name)   # disabled plugins only
manager.list() / manager.info(name) / manager.capabilities()
load_plugin(path) -> PluginManifest
```

### Errors / troubleshooting

- `PluginError("plugin ... is already enabled")` — double enable.
- `PluginError("disable a plugin before updating/removing it")` — disable, then update/remove.
- `PluginError("plugin tool entry ... does not export Tool values")` / `"plugin entry module ... does not exist"` / `"plugin entry symbol ... does not exist"` — manifest entry pointing elsewhere.
- `PluginError("plugin requires an incompatible Super Harness version")` — `requires_super_harness` not satisfied.
- `PluginError("plugin packages may not contain symbolic links")` / `"... escapes plugin root"` — security checks.
- CLI: `super-harness plugin add <source>`, `plugin list/info/update/remove <name>`.

### Security notes

- Plugin installation is **data-only**; explicit `enable` imports and executes plugin Python in-process, and **must be restricted to trusted, reviewed sources**.
- All capability paths stay inside the plugin root; symbolic links are rejected.
- Disable before updating/removing to avoid half-activated states.

---

## 6. Hooks

### What is this / When to use

Hooks register sync or async callbacks at **session, turn, user prompt, pre/post model, pre/post tool, pre/post compaction, subagent, and error** lifecycle points for observability and application policy. Hooks complement the approval engine and sandbox; they do not replace them.

### Prerequisites

- Callbacks run in an async loop (`dispatch` is async).

### Quick start

```python
import asyncio

from super_harness import HookContext, HookEvent, HookRegistry

hooks = HookRegistry()


def log_turn(context: HookContext) -> None:
    print(context.event, context.thread_id, context.turn_id)


hooks.register(HookEvent.TURN_END, log_turn)
asyncio.run(hooks.dispatch(HookContext(HookEvent.TURN_END, thread_id="thread-1")))
```

### Configuration (events and policies)

The `HookEvent` enum:

| Event | Value | Can deny |
| --- | --- | --- |
| `SESSION_START` / `SESSION_END` | `session_start` / `session_end` | No |
| `TURN_START` / `TURN_END` | `turn_start` / `turn_end` | No |
| `USER_PROMPT` | `user_prompt` | Yes |
| `BEFORE_MODEL` / `AFTER_MODEL` | `before_model` / `after_model` | Yes (before) / No (after) |
| `PRE_TOOL_USE` / `POST_TOOL_USE` | `pre_tool_use` / `post_tool_use` | Yes (before) / No (after) |
| `PRE_COMPACT` / `POST_COMPACT` | `pre_compact` / `post_compact` | Yes (before) / No (after) |
| `SUBAGENT_START` / `SUBAGENT_END` | `subagent_start` / `subagent_end` | No |
| `ERROR` | `error` | No |

Only the four **pre-execution** events — `USER_PROMPT`, `BEFORE_MODEL`, `PRE_TOOL_USE`, `PRE_COMPACT` — may return `HookResult.deny(...)`.

`HookFailurePolicy`: `WARN` (default; warns and continues), `FAIL_OPEN` (continues), `FAIL_CLOSED` (raises `HookError` and aborts).

`register` arguments: `event`, `handler`, plus `name`, `source`, `priority` (lower runs earlier), `timeout`, `failure_policy`, `allow_modify`.

### Basic example: a logging hook

```python
import asyncio

from super_harness import HookContext, HookEvent, HookRegistry

hooks = HookRegistry()


def log_turn(context: HookContext) -> None:
    print(context.event, context.thread_id, context.turn_id)


hooks.register(HookEvent.TURN_END, log_turn)
asyncio.run(hooks.dispatch(HookContext(HookEvent.TURN_END, thread_id="thread-1")))
```

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/40_hook_logging.py)

### Real-world example: pre-execution policy denial

Deny a destructive tool at `PRE_TOOL_USE`:

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

Handlers access context via `context.data["tool"]`; return `HookResult.deny(reason)` to deny or `None` to allow. `dispatch` returns a `HookOutcome` with `denied` and `deny_reason`.

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/41_hook_pre_tool_policy.py)

### Advanced example: `enrich`, `FAIL_CLOSED`, and plugin hooks

Mutate event data with `HookResult.enrich(**updates)` (only when registered with `allow_modify=True`):

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

The essentials:

- With `allow_modify=False` (default), a handler returning `updates` makes `dispatch` raise `HookError("hook ... is not allowed to modify this event")`.
- For `FAIL_CLOSED` hooks, any exception escalates to `HookError("hook ... failed closed")`; `WARN` only issues a `RuntimeWarning`.
- Each hook has its own `timeout`; timeouts follow the failure policy.
- Hooks can also be provided by plugins (see section 5, `42_plugin_hook.py`).

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/41_hook_pre_tool_policy.py)

### API quick reference

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

### Events / tracing

`dispatch` runs hooks ordered by `(priority, source, name)`; each run produces a `HookTrace` (`event`, `hook`, `source`, `success`, `duration_ms`, `denied`, `warning`), collectable via `trace_sink`. The first `deny` returns `HookOutcome(denied=True, deny_reason=...)` immediately and stops the remaining hooks.

### Errors / troubleshooting

- `HookError("hook <source>:<name> is already registered")` — same name/source registered twice.
- `HookError("hook <name> is not allowed to modify this event")` — returned updates without `allow_modify`.
- `HookError("event <value> cannot be denied")` — `deny` on a non-deniable event.
- `HookError("hook <source>:<name> failed closed")` — a `FAIL_CLOSED` hook raised.
- Always set a **bounded timeout** per hook; an unbounded hook blocks `dispatch`.

### Combining with other features

- Hooks **complement** the approval engine and sandbox; they do not replace them.
- Plugins can declare Hooks (`[[hooks]]`), registered into the shared `HookRegistry` at enable time.
- Use `HookResult.enrich` plus `allow_modify` to inject policy fields before the model.

### Security notes

- Enable `allow_modify` only for trusted handlers.
- Use `FAIL_CLOSED` for "policy must not be bypassed"; `WARN`/`FAIL_OPEN` for best-effort.
- Hooks see `context.data`; do not leak secrets into untrusted callbacks.

---

## 7. Combining the features

Wire this part's mechanisms together: a Persona constrains identity and tools, a Skill supplies domain instructions, MCP exposes external tools, a Hook applies application policy, and plugins package reusable capability.

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

> Note: `registry.list()` returns a `Tool` tuple; `Agent(tools=...)` accepts a `Tool` iterable. In production, choose MCP servers, approval policies, and hook `allow_modify` flags deliberately.

---

## 8. CLI reference

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

- Defaults to local project state (`.super-harness`); `--global` switches to the user installation root.
- Plugin management **never activates Python** (activation is the explicit Python-API trust boundary).
- Output omits secrets by default; add `--json` for stable machine-readable output.

---

## 9. Security notes summary

- **Persona / AGENTS.md / Skill instructions** are authoritative instruction sources; only trust their origin.
- **MCP remote tools and resources** are untrusted external input: narrow with `include_tools`/`exclude_tools`, configure a bounded timeout, use HTTPS, and keep approval in between.
- **`.mcpb`** installs must validate `expected_sha256`.
- **Plugin `enable` is the trust boundary**: it imports and executes plugin Python in-process; enable only trusted, reviewed sources. Installation itself is data-only.
- **Hooks** complement, not replace, the approval engine and sandbox; turn on `allow_modify` only for trusted handlers; give every hook a bounded timeout.

---

## 10. Troubleshooting quick reference

| Symptom | Check |
| --- | --- |
| Persona model mismatch | Does `model_override` match the provider model? |
| Tools invisible | Do `tool_scopes` globs cover the `qualified_name`? |
| AGENTS.md not injected | Is the directory inside a `.git` repository with a correctly named file? |
| Skill activation fails | Does `discover` cover the Skill and is the frontmatter valid? |
| MCP connection failure | Is the `mcp` SDK installed, the endpoint reachable, and transport/config aligned? |
| MCP tools missing | Check the `include_tools`/`exclude_tools` filters. |
| Plugin cannot update/remove | `disable` it first. |
| Hook reports `not allowed to modify` | Was `allow_modify=True` passed at registration? |
| Hook hangs | Was a bounded `timeout` configured? |

---

## 11. Links

**Runnable examples** (all examples on this page):

- Persona: `examples/75_persona_identity.py` · `76_persona_scopes.py` · `77_persona_subagent_roles.py`
- AGENTS.md: `examples/90_agents_override_precedence.py` · `91_agents_repository_boundary.py` · `08_agents_context_debug/main.py`
- Skills: `examples/25_skill_discovery.py` · `26_skill_activation.py` · `27_skill_install.py`
- MCP: `examples/28_mcp_stdio_list.py` · `29_mcp_stdio_call.py` · `30_mcp_stdio_resources.py` · `31_mcp_http_list.py` · `32_mcp_http_call.py` · `33_mcp_http_prompts.py` · `34_mcp_config_import.py` · `35_mcpb_install.py` · `36_mcp_registry.py`
- Plugins / Hooks: `examples/37_plugin_install.py` · `38_plugin_capabilities.py` · `39_plugin_lifecycle.py` · `40_hook_logging.py` · `41_hook_pre_tool_policy.py` · `42_plugin_hook.py`

**Related pages**:

- The rest of the User Guide: Parts I–V (Agent, Thread, tools & approval, context & persistence, memory & RAG), Part VII+ (autonomous multi-Agent and workflows).
- API reference: `api-reference.md` · `generated-api.md`.
- Ecosystem and compatibility: `ecosystem.md` · `compatibility.md`.
- Internals (out of scope for this page): the extension-related pages under `internals/`.