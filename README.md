# Super Harness

Super Harness is a Python-native, Codex-inspired, provider-agnostic agent runtime.

Development is complete through Phase 6 of the 14-phase roadmap. The repository includes the
async Agent/Thread/Turn runtime, provider-neutral model and tool layers, durable context and
SQLite Threads, external search/RAG/vision adapters, cross-thread long-term memory, Agent Skills,
and MCP stdio/Streamable HTTP plus ecosystem adapters. Credential-gated live provider tests remain
explicitly pending when their environment variables are absent.

## Development setup

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
python -m ruff check src tests tools
python -m pyright --pythonpath .venv/Scripts/python.exe
python -m pytest
python tools/check_secrets.py
```

Build the documentation website:

```bash
cd website
npm ci
npm run build
```

See [`START_HERE.md`](START_HERE.md) for the authoritative development reading order and
[`03_development_agent/DEVELOPMENT_ROADMAP.md`](03_development_agent/DEVELOPMENT_ROADMAP.md)
for the full Phase 0–13 implementation route.
