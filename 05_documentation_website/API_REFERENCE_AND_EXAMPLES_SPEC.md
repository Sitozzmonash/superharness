# API Reference and Examples Specification

## 1. API Reference

Generate as much as practical from typed source/docstrings.

Required public areas:
- `Agent`
- `Thread`
- `TurnResult`
- `TurnHandle`
- event classes
- tool decorator/base
- provider protocols/config
- RAG/Search result models
- memory APIs
- sandbox/approval
- skills/MCP/plugins/hooks
- orchestration/workflow
- persistence/observability config

For every function/class:
- signature
- parameter types
- defaults
- return type
- exceptions
- sync/async behavior
- version introduced where useful

## 2. Examples are source code

The docs must not become a parallel codebase.

Repository layout:

```text
examples/
  01_basic_agent/
  02_streaming/
  03_thread/
  ...
```

Docs link to complete files.

## 3. Snippet synchronization

Preferred options:
- embed source regions from example files;
- generate snippets during docs build;
- or test exact doc snippets against same APIs.

Do not manually maintain hundreds of divergent snippets if tooling can prevent it.

## 4. Example README template

Each example directory includes:
- purpose
- prerequisites
- env variables
- run command
- expected behavior
- explanation
- troubleshooting
- links to User Guide/Internals

## 5. Examples CI

Provide a smoke runner:

```bash
python -m tools.run_examples --offline
python -m tools.run_examples --e2e
```

or equivalent.

Offline examples should run without paid APIs where designed. E2E examples may require secure secrets and must clearly state this.
