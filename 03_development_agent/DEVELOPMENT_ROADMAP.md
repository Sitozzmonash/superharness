# Development Roadmap

Do not implement all subsystems simultaneously. Follow dependency order.

## Phase 0 — Repository and research foundation
Deliver:
- Python package skeleton
- tooling: format/lint/type/test
- CI
- pinned Codex reference
- `CODEX_PIN.md`
- project `AGENTS.md`
- config/secrets skeleton
- event/error base models
- docs website skeleton build
- initial coverage matrix copied into repository

Gate: clean install + CI + docs build.

## Phase 1 — Model/provider and basic runtime
Deliver:
- ModelProvider interface
- DeepSeek provider
- OpenAI-compatible provider
- Agent basic run
- Thread/Turn basic in-memory model
- streaming text/events
- structured output/tool call normalization

Real E2E: DeepSeek text, stream, JSON/tool call.

## Phase 2 — Tool runtime
Deliver:
- tool decorator
- registry
- executor
- validation
- timeouts/cancel
- output truncation
- built-in basic file/shell/python tools
- approval engine default full access
- local sandbox

Gate: tool loop E2E with DeepSeek.

## Phase 3 — Durable Thread/context
Deliver:
- SQLite persistence
- resume/fork/archive
- context fragments
- AGENTS.md
- compaction
- interrupt/steer/cancel
- context debug snapshot

## Phase 4 — Search, RAG and vision
Deliver:
- WebSearchProvider + Zhipu real provider
- RAGProvider + real HTTP adapter
- mock RAG HTTP service fixture
- Vision provider + `glm-4v-flash`
- routing and context injection

E2E:
- fresh web search
- actual image analysis
- HTTP RAG full chain

## Phase 5 — Memory
Deliver:
- working/conversation memory
- long-term MemoryStore
- extraction/consolidation pipeline or minimal pluggable implementation
- cross-thread retrieval
- memory docs/examples

## Phase 6 — Skills and MCP
Deliver:
- Agent Skills discovery/activation
- installer local/GitHub
- progressive loading
- standard validation
- MCP stdio
- MCP Streamable HTTP targeting current `2026-07-28` semantics via a compatible SDK
- compatibility isolation for representative 2025-era servers
- config import
- MCPB (`.mcpb`) validation/install
- Official MCP Registry client behind optional/replaceable adapter
- external compatibility fixtures

## Phase 7 — Plugins and hooks
Deliver:
- hook lifecycle
- plugin manifest/loader
- plugin capability registration
- install/update/remove
- Codex-compatible import where feasible
- conflict/version handling

## Phase 8 — Autonomous multi-agent
Deliver:
- AgentManager
- spawn/send/wait/resume/interrupt/close
- parent/child state
- budgets/depth
- context inheritance
- aggregated events
- 5+ examples

## Phase 9 — Workflow engine
Deliver:
- nodes/edges/state
- sequence
- parallel
- conditional
- router
- retry
- loop
- DAG validation
- persistence/resume
- 5+ examples

## Phase 10 — Hybrid orchestration
Deliver:
- autonomous agent node
- subworkflow node
- cross-boundary cancellation/observability
- 4+ examples

## Phase 11 — Observability and hardening
Deliver:
- structured logging
- trace model
- token/latency/cost
- OTEL optional exporter
- security review
- secret redaction tests
- concurrency/load tests

## Phase 12 — CLI/ecosystem UX
Deliver:
- doctor
- skill add/list/info/update/remove
- mcp add/list/inspect/remove/search/import
- mcp bundle/registry installation UX
- plugin add/list/info/update/remove
- thread inspect/resume
- provider test command

## Phase 13 — Documentation/release gate
Documentation was written continuously; now audit:
- User Guide complete
- Internals complete
- API reference generated
- examples complete and tested
- compatibility matrix
- troubleshooting
- GitHub Pages deployment
- all feature matrix rows PASS
- secure real E2E evidence recorded

Only then tag V1.
