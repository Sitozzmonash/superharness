# Phase 0 Foundation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Establish the reproducible repository, research reference, typed foundations, quality gates,
and documentation build required before Super Harness runtime development.

**Architecture:** Keep the Python package small and interface-ready: immutable event records,
structured exceptions, and typed configuration/secret primitives form the base for later phases.
The Codex source is pinned as research evidence rather than copied into the runtime. Docusaurus is an
independent static documentation product whose build is enforced by CI.

**Tech Stack:** Python 3.11+, Pydantic 2, Hatchling, Ruff, Pyright, Pytest, Docusaurus 3.10.2,
React 19.2.8, GitHub Actions.

---

## Roadmap and coverage mapping

| Phase 0 output | Files/evidence | Coverage impact |
|---|---|---|
| Package and tooling | `pyproject.toml`, `src/`, `tests/` | Foundation for F01-F40; no feature is marked PASS |
| Config/secrets skeleton | `src/super_harness/config/` | Starts F37 and F39, both remain TODO |
| Event/error base models | `runtime/events.py`, `exceptions.py` | Starts F06, F32, F38; all remain TODO |
| Pinned Codex reference | `references/codex/`, `references/CODEX_PIN.md` | Enables required Codex-research column |
| Project instructions | `AGENTS.md` | Development control only; F21 remains TODO |
| Documentation skeleton | `website/` and Pages workflow | Starts F34; deployment evidence is still required |
| Initial release gate | `docs/coverage/FEATURE_COVERAGE_MATRIX.md` | Exact TODO baseline copied from source of truth |

### Task 1: Repository and Python package

**Files:** `pyproject.toml`, `src/super_harness/**`, `tests/**`, `.gitignore`, `.env.example`

1. Initialize `main` as a Git repository.
2. Add package metadata and typed public foundations.
3. Write unit tests for events, exceptions, defaults, and redaction.
4. Run `python -m pip install -e ".[dev]"` and verify the editable install succeeds.
5. Run Ruff on `src tests`, Pyright with the active interpreter, and Pytest; expected result is zero
   errors and all tests passing.

### Task 2: Codex research pin

**Files:** `references/codex/`, `references/CODEX_PIN.md`, `docs/research/codex/README.md`

1. Resolve OpenAI Codex HEAD from the official repository.
2. Clone only the pinned history needed for reproducibility.
3. Checkout the exact commit in detached-HEAD state.
4. Record repository URL, commit, resolution date, and verification commands.
5. Verify `git -C references/codex rev-parse HEAD` matches `CODEX_PIN.md`.

### Task 3: Continuous integration and release baseline

**Files:** `.github/workflows/quality.yml`, `docs/coverage/FEATURE_COVERAGE_MATRIX.md`

1. Test Python 3.11 and 3.12 in CI.
2. Require formatting, linting, strict typing, tests, and docs build.
3. Copy the authoritative coverage matrix without awarding new PASS cells.
4. Validate workflow YAML structurally through repository review and local equivalent commands.

### Task 4: Documentation product skeleton

**Files:** `website/**`, `.github/workflows/docs-pages.yml`

1. Pin Docusaurus and React dependencies.
2. Create navigation matching the mandated documentation sections.
3. Clearly label unavailable runtime APIs as planned, not implemented.
4. Run `npm ci` and `npm run build`; expected result is a successful static build.
5. Configure GitHub Pages artifact build/deployment without claiming an external deployment PASS.

### Task 5: Phase 0 gate

1. Re-run all local quality commands from a clean dependency install.
2. Search tracked project material for likely live-secret patterns.
3. Confirm no unresolved runtime feature is represented as complete.
4. Record local results and remaining external CI/Pages evidence in `docs/status/phase-0.md`.
