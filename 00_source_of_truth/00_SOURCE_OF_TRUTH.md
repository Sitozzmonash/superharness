# Super Harness — Source of Truth

## 1. Product definition

**Super Harness** is a Python-native Agent Runtime inspired by OpenAI Codex's runtime architecture and operational behavior.

It is intended to be a reusable foundation for coding agents, research agents, enterprise knowledge agents, multimodal agents, automation agents, and custom multi-agent applications.

It is **not**:
- a thin wrapper around Codex CLI;
- a LangChain/LangGraph clone;
- a single-provider SDK;
- a built-in vector database;
- a hard-coded workflow engine;
- a Rust-to-Python transcription exercise.

## 2. Design principles

1. **Codex-inspired, behavior-first.**
   Study Codex source/tests before implementing equivalent runtime concepts.
2. **Python-native.**
   Prefer simple, idiomatic Python APIs and async primitives.
3. **Provider-first.**
   Models, search, RAG, persistence, sandbox, and observability should be interface-driven.
4. **OpenAI optional.**
   The framework must function without OpenAI services.
5. **China-ready.**
   Default tested providers must be usable in mainland-China deployments.
6. **Model-agnostic.**
   Text, reasoning, vision, and future modalities are capabilities behind provider interfaces.
7. **Ecosystem-first.**
   Reuse Agent Skills, MCP, GitHub, Python packaging, and Codex-compatible conventions where feasible.
8. **Simple defaults, deep customization.**
   `Agent(...).run(...)` should be easy, while advanced users can customize every subsystem.
9. **Async-first.**
   The core execution model is asynchronous; ergonomic sync wrappers may be added.
10. **Everything observable.**
    Thread, turn, model, tool, RAG, search, MCP, workflow, and subagent activity should be traceable.
11. **Explicit lifecycle.**
    Thread, Turn, Event, Context, ToolCall, AgentTask, and WorkflowRun have clear states.
12. **Safe architecture even with permissive defaults.**
    Approval engine exists even though V1 default policy is full access.
13. **Documentation is product.**
    Docs and examples are part of Definition of Done.
14. **No fake completeness.**
    A stub, TODO, mock-only path, or untested integration is not implementation completion.

## 3. V1 public capability groups

### Runtime
- Agent loop
- Thread
- Turn
- context assembly
- compaction
- interrupt / steer / cancel
- event stream / streaming
- persistence and resume/fork

### Models
- unified ModelProvider abstraction
- DeepSeek provider
- Zhipu vision provider
- generic OpenAI-compatible provider
- custom provider registration
- capability metadata
- retry/timeout/fallback
- structured output
- tool calling

### Knowledge
- working/conversation memory
- long-term memory abstraction
- external RAG provider contract
- context injection
- source metadata

### Execution
- tool/function calling
- dynamic tool registry
- built-in shell/file/python/search/RAG/subagent tools
- MCP client
- sandbox backend abstraction
- approval/policy engine

### Instructions and extensions
- AGENTS.md hierarchy
- Agent Skills / SKILL.md
- plugins
- hooks
- personas/roles

### Orchestration
- Codex-style autonomous multi-agent
- deterministic workflows
- sequential / parallel / conditional / router / loop / DAG
- hybrid workflow + autonomous subagents

### Infrastructure
- config/profiles/secrets
- SQLite default persistence
- observability/tracing/metrics
- CLI
- documentation website
- compatibility matrix
- release/versioning

## 4. Hard acceptance rule

A feature is not complete merely because its source module exists.

`DONE = Code + Unit + Integration + E2E (when applicable) + User Guide + Internals + API Reference + ≥3 runnable examples + coverage update`.

## 5. Public API quality goal

The common path should feel like:

```python
from super_harness import Agent

agent = Agent(model="deepseek-v4-flash")
result = agent.run("Analyze this repository")
print(result.text)
```

Advanced configuration should be additive rather than required.

## 6. Naming

- Distribution: `super-harness`
- Import: `super_harness`
- CLI: `super-harness`
- Home: `~/.super-harness/`
- Project settings: `.super-harness/`
- Cross-agent skills directory supported: `.agents/skills/`
