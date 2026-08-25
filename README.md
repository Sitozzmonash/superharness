# Super Harness

Super Harness is a Python-native, Codex-inspired, provider-agnostic agent runtime.

The project is in Phase 0. The repository foundation, quality gates, pinned Codex reference,
and documentation site are being established before runtime features are implemented.

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
[`docs/plans/2026-08-25-phase-0-foundation.md`](docs/plans/2026-08-25-phase-0-foundation.md)
for the Phase 0 implementation plan.
