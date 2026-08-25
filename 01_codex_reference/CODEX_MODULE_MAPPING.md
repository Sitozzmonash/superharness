# Codex → Super Harness Module Mapping

This is a research map, not a demand for one-to-one source translation.

| Super Harness concern | Primary Codex areas to inspect | What to extract |
|---|---|---|
| Runtime loop | `codex-rs/core`, `rollout`, `protocol` | lifecycle, tool loop, turn state, errors |
| Thread/Turn | `thread-store`, `state`, `protocol`, `app-server` | persistence, IDs, resume/fork semantics |
| Context | `core`, `context-fragments`, prompts | instruction/context assembly |
| AGENTS.md | `core/src/agents_md.rs`, tests | discovery, precedence, limits |
| Tools | `tools`, `core` tool plumbing | specs, dispatch, outputs, truncation |
| Shell/patch/files | `exec`, `apply-patch`, `file-system`, shell crates | safe execution patterns |
| Sandbox | `sandboxing`, `linux-sandbox`, Windows sandbox, `execpolicy` | capability/policy boundaries |
| Approval | config/protocol/approval utils | decision model and escalation |
| Model providers | `model-provider`, provider info, `ollama`, `lmstudio` | abstraction boundaries |
| Web search | `ext/web-search` | tool surface and normalized behavior |
| Skills | `skills`, `ext/skills` | discovery, progressive loading |
| MCP | `ext/mcp`, `rmcp-client`, `codex-mcp`, `mcp-server` | transports, tool exposure |
| Plugins | `plugin`, `core-plugins`, plugin utils | manifest/registration/lifecycle |
| Hooks | `hooks` | lifecycle interception |
| Memories | `ext/memories`, `memories/read`, `memories/write`, state | extraction/consolidation/store patterns |
| Multi-agent | `ext/agent`, protocol/app-server integration | spawn/send/wait/close semantics |
| Events | `protocol`, `app-server-protocol`, rollout | structured event model |
| Observability | `otel`, `rollout-trace`, diagnostics | correlation IDs, metrics |
| Secrets | `secrets`, `keyring-store` | secret resolution/masking |
| Config | `config`, core config schema/types | layered configuration |

## Research output per feature

Before coding a feature, create a short implementation note in the project:

```text
docs/research/codex/<feature>.md
```

Required headings:
1. Codex files inspected
2. Codex tests inspected
3. Behavioral contract
4. Important invariants
5. OpenAI-specific coupling to remove
6. Python-native design
7. Differences/intentional extensions
8. Tests to reproduce behavior

## Design rule

If a Codex subsystem is deeply entangled, do not copy the entanglement. Preserve the external behavior and split responsibilities into smaller Python components.
