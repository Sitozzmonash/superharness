# Super Harness — START HERE

> This is the only file the development agent should be told to open first.

Super Harness is a **Python-native, Codex-inspired, general-purpose Agent Runtime**.  
The goal is not to wrap Codex and not to translate Rust line-by-line. The goal is to study the current OpenAI Codex runtime architecture and behavior, then design a clean Python-native implementation with broader provider, RAG, workflow, and China-ready support.

## Mandatory reading order

Read these files **in order before coding**:

1. `00_source_of_truth/00_SOURCE_OF_TRUTH.md`
2. `00_source_of_truth/REQUIREMENTS_SPEC.md`
3. `00_source_of_truth/PROVIDERS_AND_SERVICES.md`
4. `00_source_of_truth/CONFIG_AND_SECRETS_SPEC.md`
5. `00_source_of_truth/FEATURE_COVERAGE_MATRIX.md`
6. `01_codex_reference/CODEX_REFERENCE_GUIDE.md`
7. `01_codex_reference/CODEX_MODULE_MAPPING.md`
8. `02_architecture/ARCHITECTURE_OVERVIEW.md`
9. `02_architecture/RUNTIME_THREAD_CONTEXT.md`
10. `02_architecture/EXECUTION_TOOLS_SANDBOX.md`
11. `02_architecture/MEMORY_RAG_SEARCH_VISION.md`
12. `02_architecture/MULTI_AGENT_AND_WORKFLOW.md`
13. `02_architecture/EXTENSIONS_SKILLS_MCP_PLUGINS_HOOKS.md`
14. `02_architecture/PERSISTENCE_EVENTS_OBSERVABILITY.md`
15. `03_development_agent/DEVELOPMENT_AGENT_INSTRUCTIONS.md`
16. `03_development_agent/CODING_STANDARDS.md`
17. `03_development_agent/DEVELOPMENT_ROADMAP.md`
18. `04_testing/TESTING_AND_ACCEPTANCE_STANDARD.md`
19. `04_testing/E2E_TEST_PLAN.md`
20. `04_testing/MOCK_RAG_SERVICE_SPEC.md`
21. `05_documentation_website/DOCUMENTATION_WEBSITE_SPEC.md`
22. `05_documentation_website/USER_GUIDE_STRUCTURE.md`
23. `05_documentation_website/INTERNALS_STRUCTURE.md`
24. `05_documentation_website/API_REFERENCE_AND_EXAMPLES_SPEC.md`
25. `06_ecosystem/ECOSYSTEM_COMPATIBILITY_SPEC.md`
26. `06_ecosystem/INSTALLATION_AND_PACKAGING_CONVENTIONS.md`
27. `07_examples/EXAMPLES_COVERAGE_SPEC.md`
28. `08_decisions/DECISION_LOG.md`

## Non-negotiable rules

1. **Study Codex before implementing each equivalent runtime feature.**
2. **Python-native design.** Use Python idioms such as `asyncio`, protocols/ABCs, dataclasses/Pydantic where appropriate, async generators, context managers, entry points, and structured exceptions.
3. **OpenAI must be optional.** Core operation must work in mainland-China deployments using configured providers.
4. **Every public feature must be real, tested, documented, and demonstrated.**
5. **Core documentation code must have a corresponding runnable file under `examples/`.**
6. Every major public feature requires at least:
   - one minimal example,
   - one realistic example,
   - one advanced/integration example.
7. Unit tests alone are not enough. Use integration and real-provider E2E tests where the feature depends on an external provider.
8. RAG is an **external retrieval service contract**. Super Harness calls it and receives Top-N text/documents. Do not build a vector database into core.
9. Multi-agent must support:
   - Codex-style autonomous subagents,
   - deterministic workflow orchestration,
   - hybrid orchestration.
10. Skill/MCP/plugin integration must prioritize existing open ecosystem conventions.
11. Do not put secrets in source, examples, documentation, fixtures, logs, traces, or git history.
12. A feature is not `DONE` until its row in `FEATURE_COVERAGE_MATRIX.md` is fully satisfied.

## Before implementation

Create or verify the actual project repository contains a pinned Codex reference under a path such as:

```text
references/codex/
```

Record the exact Codex commit in:

```text
references/CODEX_PIN.md
```

Do not develop permanently against a moving `main`.

## Expected repository layout

```text
super-harness/
├─ src/super_harness/
├─ tests/
├─ examples/
├─ docs/
├─ website/
├─ references/
│  └─ codex/
├─ AGENTS.md
├─ .env.example
├─ pyproject.toml
└─ README.md
```

## Definition of Done

A public feature is complete only when all are true:

- implementation exists;
- public API is typed and documented;
- unit tests pass;
- integration tests pass;
- real E2E test passes where applicable;
- failure/timeout/cancellation behavior is tested;
- User Guide page exists;
- Architecture & Internals page exists;
- API reference exists or is generated;
- at least 3 runnable examples exist;
- docs code and `examples/` stay synchronized;
- observability is emitted where appropriate;
- coverage matrix is updated;
- no unresolved critical TODO/stub/mock remains.

If any item is missing, mark the feature **NOT DONE**.

## Start

After reading all files above, produce a short implementation plan mapped to the roadmap and coverage matrix, then begin from Phase 0. Do not ask the user to restate requirements already defined in this folder.
