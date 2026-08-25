# Examples Coverage Specification

## 1. Rule

Every major public feature needs at least three runnable examples:
1. Basic
2. Real-world
3. Advanced/integration

Documentation core code must map to these examples.

## 2. Minimum example tree

```text
examples/
├─ 01_basic_agent/
├─ 02_models/
├─ 03_streaming/
├─ 04_thread_resume_fork/
├─ 05_interrupt_steer/
├─ 06_context_compaction/
├─ 07_tools/
├─ 08_sandbox_approval/
├─ 09_agents_md_persona/
├─ 10_web_search/
├─ 11_vision/
├─ 12_rag/
├─ 13_memory/
├─ 14_skills/
├─ 15_mcp/
├─ 16_plugins/
├─ 17_hooks/
├─ 18_autonomous_multi_agent/
├─ 19_workflows/
├─ 20_hybrid/
├─ 21_persistence/
├─ 22_observability/
├─ 23_config_secrets_profiles/
├─ 24_retry_fallback_errors/
├─ 25_cli_doctor/
├─ 26_security_hardening/
├─ 27_custom_provider/
└─ 28_full_application/
```

Subdirectories may contain multiple examples.

## 3. Required scenarios

### Basic Agent
- minimal sync
- async
- config file

### Models
- DeepSeek direct
- structured output
- custom OpenAI-compatible provider

### Streaming
- text events
- tool events
- web/agent events

### Thread
- multi-turn
- resume
- fork

### Interrupt/Steer
- interrupt
- steer
- cancel propagation

### Context/Compaction
- inspect assembled context
- manual compaction
- automatic threshold compaction preserving required state

### Tools
- sync decorator
- async
- dynamic registration

### Sandbox / Approval
- workspace write
- read-only failure
- Docker isolated command
- default full-access approval
- restricted allow/deny/custom policy

### AGENTS.md / Persona
- root
- nested
- override

### Web Search
- direct API
- agent automatic call
- advanced filters/custom provider

### Vision
- local image
- image URL
- vision + main-model reasoning

### RAG
- function provider
- HTTP mock service
- rich metadata + final grounded answer

### Memory
- working
- cross-thread
- custom store

### Skills
- local standard
- GitHub install
- skill with scripts/references

### MCP
- stdio
- current Streamable HTTP
- imported `mcpServers` config / external server
- MCP Bundle (`.mcpb`) install
- MCP Registry discovery/install metadata path
- compatibility test against current protocol SDK/server behavior

### Plugins
- install
- capability bundle
- disable/remove/update

### Hooks
- logging
- pre-tool policy
- plugin hook

### Autonomous multi-agent (>=5)
- research
- coding team
- parallel critics
- child steering
- budget/cancellation

### Workflows (>=5)
- sequence
- parallel
- conditional
- router
- loop/retry

### Hybrid (>=4)
- autonomous node
- subworkflow
- failure/resume
- full team pipeline

### Persistence
- save/resume thread
- fork/archive/inspect persisted state
- workflow checkpoint/resume

### Observability
- console/JSONL
- trace tree
- OTEL optional

### Config / Profiles / Secrets
- precedence and project/user/runtime config
- China/global/offline profile switch
- secret masking and diagnostics without disclosure

### Retry / Fallback / Errors
- provider retry/backoff
- timeout/cancellation distinction
- observable fallback and typed error normalization

### CLI / Doctor
- provider diagnostics
- ecosystem list/inspect commands
- thread inspect/resume

### Security / Hardening
- path traversal denied
- prompt-injection data handling
- plugin/skill source integrity/trust warning

### Full application
One realistic application using most major systems together.

## 4. Example quality

Every example includes:
- README
- runnable code
- config/example env
- expected behavior
- no real secrets
- links to docs
- deterministic fixture where possible

## 5. CI

Maintain:
- offline smoke set
- provider E2E set
- Docker/MCP integration set

The docs website should show whether an example needs external credentials.
