# Super Harness — Requirements Specification

## 1. Functional requirements

### FR-001 Agent runtime
The framework shall execute iterative model/tool loops until completion, interruption, failure, or configured budget limit.

### FR-002 Thread / Turn
A Thread shall represent a resumable conversation/task session. A Turn shall represent one user-driven execution cycle within a Thread.

Required operations:
- create
- run
- stream
- resume
- fork
- archive
- inspect
- interrupt active turn
- steer active turn
- cancel

### FR-003 Context
Context assembly shall support:
- system/runtime instructions
- developer instructions
- AGENTS.md
- persona/role
- thread history
- compacted summaries
- activated skills
- memory
- RAG results
- tool outputs
- model-specific adaptation

### FR-004 Compaction
Support manual and automatic compaction with configurable thresholds and traceable pre/post state.

### FR-005 Models
Support:
- text/reasoning model
- vision model
- OpenAI-compatible custom endpoints
- custom provider plugins
- streaming
- structured output
- tool calls
- provider fallback
- capability declaration

### FR-006 Web search
Provide a stable `WebSearchProvider` interface. V1 real E2E default is Zhipu Web Search. Search must be usable as a direct Python API and as an agent tool.

### FR-007 Vision
Provide a vision capability routed independently from the main text model. V1 real E2E default is Zhipu `glm-4v-flash`.

### FR-008 External RAG
The framework shall call an external retrieval service and normalize Top-N results.

Minimum accepted external response:
- `list[str]`

Preferred normalized internal structure:
- text
- score optional
- source optional
- metadata optional

Core must not require Milvus/ES/embedding/vector indexing.

### FR-009 Tools
Support:
- decorator tools
- callable tools
- async tools
- runtime registration/unregistration
- JSON-schema argument definitions
- typed validation
- tool namespaces
- timeouts
- cancellation
- output truncation
- lazy/deferred discovery where useful

### FR-010 Sandbox
Sandbox abstraction with at least:
- local process backend
- Docker backend
- read-only/workspace-write/full-access policy modes where feasible

### FR-011 Approval
Approval engine must exist. Default V1 policy is permissive/full-access. Architecture must support allow/deny/ask/custom rules.

### FR-012 AGENTS.md
Support Codex-like discovery from project root to working directory, nested precedence, configurable project root markers, size limits, and a local override convention.

### FR-013 Skills
Support open Agent Skills/SKILL.md format with progressive disclosure and installation from local paths and Git repositories/GitHub.

### FR-014 MCP
Implement the official Model Context Protocol using the current stable ecosystem semantics. Target MCP protocol revision `2026-07-28` where supported by the chosen SDK, while retaining pragmatic compatibility with 2025-era servers. First-class transports are stdio and Streamable HTTP. Do not assume legacy transport-level sessions as a core invariant. Support discovery, tools/resources/prompts as applicable, authentication hooks, timeout/cancellation, filtering, enable/disable, and modern request metadata. Where relevant, support/handle current 2026 concepts such as stateless requests, Multi Round-Trip Requests (MRTR), `Mcp-Method`/`Mcp-Name` routing headers, cache hints, and extension negotiation without hard-coding optional extensions into Agent core.

Distribution/discovery requirements:
- import common `mcpServers` configuration;
- install/connect stdio and remote servers;
- support MCP Bundle (`.mcpb`) installation for portable local servers;
- support official MCP Registry discovery behind an isolated replaceable client because the registry remains preview;
- verify integrity metadata such as hashes when supplied by package/registry metadata.

### FR-015 Plugins
Support installable capability bundles that may contribute skills, tools, MCP config, hooks, agents, commands/config/assets. Prefer Codex-compatible structures where practical.

### FR-016 Hooks
Support lifecycle interception around key runtime stages. At minimum:
- session start/end
- turn start/end
- user prompt
- before/after model
- pre/post tool
- pre/post compact
- subagent start/end
- error

### FR-017 Autonomous multi-agent
Main agent can autonomously spawn, message, wait for, resume, interrupt, and close child agents. Include parent/child IDs, max threads, max depth, budgets, and event aggregation.

### FR-018 Workflow engine
Support deterministic orchestration:
- sequence
- parallel
- conditional
- router
- loop with termination guards
- retry
- DAG

### FR-019 Hybrid orchestration
A workflow node may run an autonomous agent that itself spawns subagents; autonomous agents may call deterministic subflows.

### FR-020 Memory
Support working/conversation memory plus a long-term memory interface. Storage default may be SQLite. Long-term extraction/consolidation should be pluggable.

### FR-021 Persistence
Persist thread/turn/event state sufficiently for resume, fork, inspection, and debugging.

### FR-022 Events / Streaming
Expose structured events through async iteration. Events must carry relevant correlation IDs.

### FR-023 Observability
Structured logs and traces for:
- model calls
- tools
- RAG
- search
- MCP
- subagents
- workflow nodes
- compaction
- errors
- token/latency/cost when known

### FR-024 CLI
CLI must support diagnostics plus ecosystem install/inspect flows.

### FR-025 Documentation website
One static documentation website deployable to GitHub Pages with:
- User Guide
- Architecture & Internals
- Examples
- API Reference
- Ecosystem
- Compatibility/Testing
- Troubleshooting

### FR-026 Examples
Every major public feature has at least three runnable examples, and documentation core code maps to corresponding `examples/` files.

### FR-027 Persona / Role
Support explicit agent identity/persona configuration including name, role, goal/instructions, constraints, model override, tool/skill scopes, memory scope, and subagent role templates. Persona must remain an instruction/configuration layer rather than a hard-coded prompt trick.

### FR-028 Configuration / Profiles / Secrets
Provide typed configuration with deterministic precedence, project/user/runtime scopes, China/global/offline/test profiles, `.env`-based local development, secret redaction, and pluggable secret resolution. Configuration and secrets must be inspectable through diagnostics without exposing secret values.

### FR-029 Retry / Timeout / Fallback / Error Semantics
Define explicit, observable policy-driven retry, timeout, cancellation and fallback semantics for model providers, search, RAG, MCP, tools, subagents and workflow nodes. Do not silently switch providers or swallow errors/cancellation. Public errors must normalize provider-specific failures into typed framework exceptions while retaining diagnostic cause metadata.

### FR-030 Security / Hardening
Security is a product feature and release gate, not only a test category. Cover sandbox boundaries, path traversal, shell/network restrictions, secret leakage/redaction, plugin/skill trust boundaries, package/source integrity, MCP authentication/remote trust, prompt injection from RAG/search/tool output, unsafe schema/tool names, and secure defaults for production profiles. V1 may default approval to full access, but restricted modes must behave as documented.

### FR-031 Ecosystem packaging and compatibility
Skill/MCP/plugin installers must record source/revision/version, expose added capabilities, support project/global scopes where applicable, validate before activation, and avoid install-time code execution by default. External compatibility tests must pin representative standards-compliant sources.

## 2. Non-functional requirements

### NFR-001 Python
Target modern supported Python (recommend 3.11+ unless a stronger compatibility reason exists).

### NFR-002 Async
Async-first internals; avoid blocking network/subprocess operations on the event loop.

### NFR-003 Performance
Avoid loading full skill/tool/plugin metadata into every prompt. Use progressive/lazy loading.

### NFR-004 Reliability
Explicit retry/backoff/timeout/cancellation semantics.

### NFR-005 Security
Secrets must be masked; untrusted skill/plugin scripts execute under configured sandbox/policy.

### NFR-006 Maintainability
Small modules, typed APIs, clear dependency direction, minimal global state.

### NFR-007 Testability
Providers and execution backends must be injectable and independently testable.

### NFR-008 Reproducibility
Pin Codex reference commit and external compatibility fixtures used in CI.

### NFR-009 Documentation accuracy
Examples should be tested. Broken links/code should fail documentation CI where practical.

## 3. Out of scope for V1 core

- Built-in Milvus/Elasticsearch indexing pipeline
- Built-in embedding pipeline
- built-in web crawler
- building a proprietary MCP-like protocol
- graphical workflow editor
- managed cloud service
- proprietary plugin marketplace backend
