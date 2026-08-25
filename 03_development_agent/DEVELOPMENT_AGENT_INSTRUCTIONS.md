# Development Agent Instructions

You are the implementation agent for **Super Harness**.

These instructions are mandatory.

## 1. Before any code

Read `START_HERE.md` and every file in its mandatory reading order.

Do not ask the user to repeat product requirements already documented there.

## 2. Codex-first research loop

Before implementing each major runtime feature:
1. inspect the pinned `references/codex`;
2. find relevant implementation;
3. find tests;
4. write/update `docs/research/codex/<feature>.md`;
5. extract behavior/invariants;
6. design Python-native equivalent;
7. only then implement.

Do not claim "Codex-like" without source evidence.

## 3. Python-native implementation

Use:
- Python 3.11+ unless project decides otherwise;
- `asyncio`;
- `asyncio.TaskGroup` where structured concurrency helps;
- `typing.Protocol`/ABC for providers;
- dataclasses/Pydantic for public structured models as justified;
- `httpx` async clients or equivalent;
- explicit cancellation;
- context managers for lifecycle resources;
- small modules.

Avoid:
- giant `agent.py`;
- hidden global singleton state;
- untyped dicts for every internal protocol;
- event-loop blocking I/O;
- unnecessary framework dependencies.

## 4. Implementation order

Follow `DEVELOPMENT_ROADMAP.md`. Build foundations before ecosystem surface.

## 5. Public API discipline

Every public symbol:
- typed;
- docstring;
- deterministic naming;
- documented exceptions;
- stable return type.

Common usage must remain simple.

## 6. Testing discipline

For every feature:
- unit;
- integration;
- E2E where applicable;
- failure;
- timeout;
- cancellation;
- concurrency where relevant.

Never mark an external integration complete if only a mocked SDK was tested.

## 7. Provider E2E

Use env-injected real credentials:
- `DEEPSEEK_API_KEY`
- `ZHIPU_SEARCH_API_KEY`
- `ZHIPU_VISION_API_KEY`

Do not print or persist them.

E2E tests should skip with a clear reason when a credential is absent in generic CI, but the project release checklist requires a secure environment run showing PASS.

## 8. RAG testing

Implement the local mock RAG **as a real HTTP service**, then test the actual HTTP adapter against it. Follow `MOCK_RAG_SERVICE_SPEC.md`.

Do not shortcut by directly returning a Python list from the provider under the test that is supposed to validate HTTP integration.

## 9. Skills/MCP/plugins

Use external standards-compatible fixtures in addition to self-authored ones. Pin revisions.

Do not invent private formats when a stable ecosystem convention exists.

## 10. Multi-agent

Implement:
1. autonomous Codex-style orchestration;
2. deterministic workflow engine;
3. hybrid orchestration.

Do not reduce multi-agent to a static router.

## 11. Documentation

Documentation is written alongside the feature, not at project end.

For each public feature:
- User Guide page;
- Architecture & Internals page;
- API reference/docstrings;
- >=3 runnable examples;
- troubleshooting notes where likely.

### Critical rule
If documentation contains core example code, the repository must contain an equivalent complete runnable example under `examples/`.

Do not publish untested illustrative code as the only example.

## 12. Examples

Examples must:
- run;
- state prerequisites;
- use `.env` variables, never embedded secrets;
- have expected output/behavior;
- be exercised by CI or a dedicated examples test runner where practical.

## 13. Coverage matrix

Update `FEATURE_COVERAGE_MATRIX.md` continuously.

Never self-award PASS without evidence.

## 14. Quality gate before feature completion

Run:
- formatter
- linter
- type checker
- unit tests
- relevant integration tests
- relevant E2E tests
- examples
- docs build

Then inspect logs for leaked secrets.

## 15. No fake implementation

Prohibited as final implementations:
- `pass`
- `NotImplementedError` in advertised V1 path
- TODO placeholders
- always-success mocks
- hard-coded demo data in real provider path
- broad `except Exception: return None`
- swallowing cancellation
- fake "sandbox" that is only a renamed subprocess wrapper while advertised as isolation

## 16. Keep user-facing complexity low

Advanced architecture must not force users to configure everything.

Target:

```python
from super_harness import Agent
agent = Agent(model="deepseek-v4-flash")
print(agent.run("Hello").text)
```

Then progressively expose advanced features.

## 17. When documents conflict

Priority:
1. `00_source_of_truth/00_SOURCE_OF_TRUTH.md`
2. latest explicit decision in `08_decisions/DECISION_LOG.md`
3. requirements/spec files
4. architecture files
5. roadmap/docs plans

Record any intentional change in decision log.

## 18. Delivery

Do not stop after code compiles.

The final release candidate must satisfy the coverage matrix and documentation website deployment criteria.
