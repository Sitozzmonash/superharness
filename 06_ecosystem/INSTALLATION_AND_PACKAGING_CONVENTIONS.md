# Installation and Packaging Conventions

## 1. Framework

```bash
pip install super-harness
```

Preferred modern alternative:

```bash
uv add super-harness
```

Import:
```python
import super_harness
```

CLI:
```bash
super-harness --help
```

## 2. Skills

Examples:

```bash
super-harness skill add ./my-skill
super-harness skill add https://github.com/org/repo/tree/main/skills/my-skill
super-harness skill list
super-harness skill info my-skill
super-harness skill update my-skill
super-harness skill remove my-skill
```

Scope flags:
```bash
--global
--project
```

Installer validates before activation.

## 3. MCP

Examples:

```bash
super-harness mcp add filesystem --stdio -- npx -y @example/filesystem
super-harness mcp add company --url https://example.com/mcp
super-harness mcp import ./mcp.json
super-harness mcp add ./local-server.mcpb
super-harness mcp search <query>          # Official Registry client when enabled
super-harness mcp add <registry-server>   # resolve standardized install metadata
super-harness mcp list
super-harness mcp inspect filesystem
super-harness mcp remove filesystem
```

Exact CLI may evolve, but docs/examples/tests must be synchronized. Registry support is optional-at-runtime because the Official Registry is preview. MCPB installation should validate manifest/schema and package integrity metadata before activation and must not silently execute untrusted install-time code.

## 4. Plugins

```bash
super-harness plugin add ./plugin
super-harness plugin add https://github.com/org/plugin
super-harness plugin list
super-harness plugin info <name>
super-harness plugin update <name>
super-harness plugin remove <name>
```

## 5. Python function tools

No installer required:

```python
from super_harness import tool

@tool
def add(a: int, b: int) -> int:
    return a + b
```

Larger Python integrations may ship as normal PyPI packages and register entry points.

## 6. Installation safety

Before enabling remote content:
- clone/download to staging;
- inspect/validate metadata;
- verify expected file boundaries;
- record revision;
- do not execute install-time scripts by default;
- run skill/plugin scripts later under configured sandbox/policy;
- show user what capabilities are added.

## 7. `info` UX

`skill info`, `mcp inspect`, and `plugin info` should clearly show:
- source
- scope
- revision/version
- status
- capabilities contributed
- config requirements
- tools exposed
- scripts/hooks present
- trust warnings
