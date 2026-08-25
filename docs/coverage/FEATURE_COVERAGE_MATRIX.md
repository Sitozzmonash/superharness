# Feature Coverage Matrix

This is a release gate, not a marketing checklist.

Legend:
- `TODO` not implemented
- `PARTIAL` incomplete
- `PASS` satisfies requirement
- `N/A` justified and documented

Every row must reach `PASS` in required columns before V1 release.

| ID | Feature | Codex research | Impl | Unit | Integration | Real E2E | User Guide | Internals | API Ref | >=3 examples | Obs | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| F01 | Agent runtime loop | PASS | PASS | PASS | PASS | TODO | PASS | PASS | PASS | PASS | PASS | PARTIAL |
| F02 | Thread / Turn | PASS | PASS | PASS | PASS | TODO | PASS | PASS | PASS | PASS | PASS | PARTIAL |
| F03 | Context assembly | PASS | PASS | PASS | PASS | TODO | PASS | PASS | PASS | PASS | PASS | PARTIAL |
| F04 | Compaction | PASS | PASS | PASS | PASS | TODO | PASS | PASS | PASS | PARTIAL | PASS | PARTIAL |
| F05 | Interrupt / steer / cancel | PASS | PASS | PASS | PASS | TODO | PASS | PASS | PASS | PARTIAL | PASS | PARTIAL |
| F06 | Event streaming | PASS | PARTIAL | PASS | PASS | TODO | PASS | PASS | PASS | PASS | PASS | PARTIAL |
| F07 | Model provider abstraction | PASS | PASS | PASS | PASS | TODO | PASS | PASS | PASS | PASS | PASS | PARTIAL |
| F08 | DeepSeek provider | PASS | PASS | PASS | PARTIAL | TODO | PASS | PASS | PASS | PASS | PASS | PARTIAL |
| F09 | Vision provider / GLM | PASS | PASS | PASS | PASS | TODO | PASS | PASS | PASS | PASS | PASS | PARTIAL |
| F10 | OpenAI-compatible provider | PASS | PASS | PASS | PASS | TODO | PASS | PASS | PASS | PASS | PASS | PARTIAL |
| F11 | Web search / Zhipu | PASS | PASS | PASS | PASS | TODO | PASS | PASS | PASS | PASS | PASS | PARTIAL |
| F12 | External RAG provider | PASS | PASS | PASS | PASS | PASS (fixture) | PASS | PASS | PASS | PASS | PASS | PASS |
| F13 | Working memory | PASS | PASS | PASS | PASS | TODO | PASS | PASS | PASS | PASS | PASS | PARTIAL |
| F14 | Long-term memory | PASS | PASS | PASS | PASS | TODO | PASS | PASS | PASS | PASS | PASS | PARTIAL |
| F15 | Function/tool calling | PASS | PASS | PASS | PASS | TODO | PASS | PASS | PASS | PASS | PASS | PARTIAL |
| F16 | Built-in shell/file/python tools | PASS | PASS | PASS | PASS | TODO | PASS | PASS | PASS | PARTIAL | PASS | PARTIAL |
| F17 | Dynamic/lazy tool registry | PASS | PARTIAL | PARTIAL | TODO | TODO | PASS | PASS | PASS | PARTIAL | PARTIAL | PARTIAL |
| F18 | Sandbox local | PASS | PASS | PASS | PASS | TODO | PASS | PASS | PASS | PARTIAL | PASS | PARTIAL |
| F19 | Sandbox Docker | TODO | TODO | TODO | TODO | TODO | TODO | TODO | TODO | TODO | TODO | TODO |
| F20 | Approval engine | PASS | PASS | PASS | PASS | TODO | PASS | PASS | PASS | PARTIAL | PASS | PARTIAL |
| F21 | AGENTS.md | PASS | PASS | PASS | PASS | TODO | PASS | PASS | PASS | PARTIAL | PASS | PARTIAL |
| F22 | Agent Skills / SKILL.md | PASS | PASS | PASS | PASS | PASS (pinned GitHub) | PASS | PASS | PASS | PASS | PASS | PASS |
| F23 | MCP stdio | PASS | PASS | PASS | PASS | PASS (official 1.x/2.x SDKs) | PASS | PASS | PASS | PASS | PASS | PASS |
| F24 | MCP HTTP | PASS | PASS | PASS | PASS | PASS (official SDK server) | PASS | PASS | PASS | PASS | PASS | PASS |
| F25 | Plugin system | PASS | PASS | PASS | PASS | PASS (official pinned repo) | PASS | PASS | PASS | PASS | PASS | PASS |
| F26 | Hooks | PASS | PASS | PASS | PASS | N/A (in-process lifecycle) | PASS | PASS | PASS | PASS | PASS | PASS |
| F27 | Autonomous multi-agent | TODO | TODO | TODO | TODO | TODO | TODO | TODO | TODO | >=5 | TODO | TODO |
| F28 | Workflow engine | TODO | TODO | TODO | TODO | TODO | TODO | TODO | TODO | >=5 | TODO | TODO |
| F29 | Hybrid orchestration | TODO | TODO | TODO | TODO | TODO | TODO | TODO | TODO | >=4 | TODO | TODO |
| F30 | Router | TODO | TODO | TODO | TODO | TODO | TODO | TODO | TODO | TODO | TODO | TODO |
| F31 | Persistence / SQLite | PASS | PASS | PASS | PASS | TODO | PASS | PASS | PASS | PARTIAL | PASS | PARTIAL |
| F32 | Observability | PASS | PARTIAL | PASS | PASS | TODO | PASS | PASS | PASS | PARTIAL | PASS | PARTIAL |
| F33 | CLI | TODO | TODO | TODO | TODO | TODO | TODO | TODO | TODO | TODO | TODO | TODO |
| F34 | Documentation website | N/A | TODO | TODO | TODO | deployed | N/A | N/A | N/A | N/A | N/A | TODO |
| F35 | Ecosystem installers | PASS | PASS | PASS | PASS | PASS (pinned GitHub) | PASS | PASS | PASS | PASS | PASS | PASS |
| F36 | Persona / role | TODO | TODO | TODO | TODO | TODO | TODO | TODO | TODO | >=3 | TODO | TODO |
| F37 | Config / profiles / secrets | TODO | TODO | TODO | TODO | TODO | TODO | TODO | TODO | >=3 | TODO | TODO |
| F38 | Retry / timeout / fallback / error model | PASS | PARTIAL | PASS | PASS | TODO | PASS | PASS | PARTIAL | PARTIAL | PASS | PARTIAL |
| F39 | Security / hardening | TODO | TODO | TODO | TODO | TODO | TODO | TODO | TODO | >=3 | TODO | TODO |
| F40 | MCPB / MCP Registry compatibility | PASS | PASS | PASS | PASS | PASS (live Registry) | PASS | PASS | PASS | PASS | PASS | PASS |

## Required matrix discipline

- Update the matrix in the same PR/commit that changes feature completeness.
- Never mark `Real E2E=PASS` if only a mocked HTTP client was used.
- A fixture server is acceptable for RAG because the product contract is external RAG service connectivity; the test must still use real HTTP transport.
- For skills/MCP/plugins, compatibility tests should consume at least one external standards-compliant fixture/repository, not only self-authored fixtures.
