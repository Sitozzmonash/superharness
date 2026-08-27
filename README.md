# Super Harness

Super Harness is a Python-native, Codex-inspired, provider-agnostic agent runtime.

Development is complete through Phase 13 of the 14-phase roadmap as a release candidate. The repository includes the
async Agent/Thread/Turn runtime, provider-neutral model and tool layers, durable context and
SQLite Threads, external search/RAG/vision adapters, cross-thread long-term memory, Agent Skills,
MCP stdio/Streamable HTTP, plugins/hooks, autonomous multi-Agent orchestration, and a deterministic
workflow engine with routing, retry/loop guards, JSON checkpoints, resume, autonomous Agent nodes,
durable nested subworkflows, structured logs, trace trees, metrics/cost estimates, optional OTEL,
bounded secret redaction, a complete diagnostics/ecosystem CLI, typed Persona/configuration,
lazy Tools, provider-neutral routing and fallback, and a hardened Docker sandbox backend.
V1 is intentionally untagged while credential-gated provider tests, a real local Docker run, and
the deployed documentation URL lack verified evidence.

## Development setup

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
python -m ruff check src tests tools
python -m pyright --pythonpath .venv/Scripts/python.exe
python -m pytest
python tools/check_secrets.py
python tools/generate_api_reference.py
```

Run `super-harness doctor` for local diagnostics and `super-harness --help` for Skill,
MCP/MCPB/Registry, plugin, durable Thread, and provider commands. Project scope is the default;
place `--global` before the command for user scope.

Build the documentation website:

```bash
cd website
npm ci
npm run build
```

See [`START_HERE.md`](START_HERE.md) for the authoritative development reading order and
[`03_development_agent/DEVELOPMENT_ROADMAP.md`](03_development_agent/DEVELOPMENT_ROADMAP.md)
for the full Phase 0–13 implementation route.
