# Extensions: Skills, MCP, Plugins and Hooks

## 1. Tool vs Skill vs MCP vs Plugin vs Hook

| Concept | Purpose |
|---|---|
| Tool | Executable operation exposed to the model/runtime |
| Skill | Portable procedural knowledge/instructions/resources |
| MCP | Standard protocol for external tools/resources/prompts |
| Plugin | Installable bundle contributing multiple capabilities |
| Hook | Code invoked at runtime lifecycle interception points |

Documentation must teach this decision clearly.

## 2. Agent Skills

Adopt the open Agent Skills format.

Minimum skill directory:

```text
skill-name/
└─ SKILL.md
```

Common optional:
```text
scripts/
references/
assets/
```

`SKILL.md` uses YAML frontmatter with at least:
- name
- description

Use progressive disclosure:
1. load metadata for discovery;
2. load full `SKILL.md` only when activated;
3. load resources/scripts on demand.

Validate with the open specification where possible.

## 3. Skill discovery locations

Recommended:
- runtime-explicit skills
- project `.agents/skills/`
- project `.super-harness/skills/`
- user `~/.super-harness/skills/`
- plugin-contributed skills
- bundled system skills

Document precedence and name collisions.

## 4. Skill install sources

CLI should support:
- local directory
- local git repository
- Git URL
- GitHub repository/subdirectory URL
- plugin-provided skill

Example:

```bash
super-harness skill add https://github.com/org/repo/tree/main/skills/pdf
super-harness skill add ./skills/internal-review
super-harness skill list
super-harness skill info pdf
super-harness skill update pdf
super-harness skill remove pdf
```

Installer must pin/record source revision when possible.

## 5. MCP

Use official Model Context Protocol. Do not invent a proprietary transport.

### Target protocol generation
Target the current stable MCP revision `2026-07-28` when supported by the selected official/Tier-1 SDK. Keep compatibility adapters/tests for common 2025-era servers where practical. The implementation must not bake legacy transport-level sessions into Agent core.

Current first-class transports:
- stdio
- Streamable HTTP

Important 2026 behavior to account for at the MCP adapter boundary:
- stateless protocol core;
- Multi Round-Trip Requests (MRTR) for interactions that require additional user/client input;
- `Mcp-Method` / `Mcp-Name` HTTP routing headers where required by the current transport revision;
- cache hints/deterministic list results where exposed by SDK;
- extension negotiation rather than assuming optional capabilities;
- modern authorization metadata/validation.

Compatibility:
- older 2025 Streamable HTTP where supported by SDK;
- deprecated HTTP+SSE only as an isolated compatibility path if required by a pinned real fixture, not as the canonical V1 design.

Support:
- tools
- resources/prompts where the protocol/client surface exposes them
- authentication/headers
- timeout/cancellation
- reconnect/retry only where meaningful for the transport generation
- filtering
- enable/disable
- source metadata
- capability/extension metadata

### Distribution and discovery
Support or design explicit adapters for:
- direct stdio command definitions;
- remote MCP URLs;
- imported common `mcpServers` JSON;
- MCP Bundle (`.mcpb`) for portable local-server installation;
- Official MCP Registry discovery metadata.

The Official MCP Registry is currently preview, so isolate it behind a replaceable client and never make registry availability a runtime dependency. MCPB is part of the MCP project and should be treated as the preferred portable packaging path for distributable local servers where applicable. Validate hashes/integrity metadata when supplied.

## 6. MCP configuration compatibility

Accept an import form compatible with common `mcpServers` JSON where practical.

Example:

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@example/filesystem"]
    }
  }
}
```

Normalize into internal typed config.

## 7. Plugins

A plugin is an installable bundle that may contribute:
- skills
- tools
- MCP definitions
- hooks
- agents/personas
- commands
- assets
- config schema/defaults

Prefer best-effort compatibility with Codex plugin layouts where stable.

Suggested Super Harness overlay manifest:
```text
.super-harness/plugin.toml
```

If `.codex-plugin/plugin.json` exists, attempt compatible import and document unsupported fields.

## 8. Plugin install

```bash
super-harness plugin add https://github.com/org/plugin
super-harness plugin add ./local-plugin
super-harness plugin list
super-harness plugin info <name>
super-harness plugin update <name>
super-harness plugin remove <name>
```

Installers must validate before activation.

## 9. Hooks

Hook lifecycle minimum:
- session_start
- session_end
- turn_start
- turn_end
- user_prompt
- before_model
- after_model
- pre_tool_use
- post_tool_use
- pre_compact
- post_compact
- subagent_start
- subagent_end
- error

Hooks may:
- observe
- enrich metadata/context at defined safe points
- deny/modify action only where contract explicitly allows it

Hook failure policy must be configurable:
- fail-open
- fail-closed
- warn

## 10. External compatibility tests

Do not only test our own fixtures.

At least:
- a standards-compliant external Agent Skill;
- a GitHub subdirectory skill install;
- a real stdio MCP server;
- a real HTTP MCP server if available;
- a Codex-style plugin fixture/repository where licensing permits.

Pin fixture revisions for reproducibility.
