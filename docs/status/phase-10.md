# Phase 10 Status

Date: 2026-08-25

## Outcome

Phase 10 is implemented. Deterministic workflows can run autonomous Agent trees and nested workflows with correlated observations, cross-boundary cancellation, and safe child checkpoint resume.

## Delivered

- `AutonomousAgentNode` and `agent_node` public APIs.
- `SubworkflowNode` and `subworkflow_node` public APIs.
- Agent node task builders, role/instructions/context policy, timeout, and token budget.
- Actual model-callable specialist delegation inside a workflow Agent node.
- Agent descendant discovery/join, failure enforcement, and orphan prevention.
- Stable nested run IDs plus optional JSON child checkpoint reuse.
- Parent workflow node correlation for redacted Agent and nested workflow events.
- Parent-to-Agent-subtree and parent-to-child-workflow cancellation propagation.
- Failure/resume that does not replay completed nested nodes.
- Four credential-free runnable hybrid examples and six focused tests.

## Acceptance evidence

| Gate | Result | Evidence |
|---|---|---|
| Pinned Codex research | PASS | Collaboration lifecycle, resume, notifications, tool-handler, and plan separation recorded |
| Autonomous Agent node | PASS | Deterministic sequence runs an independent Agent/Thread and consumes terminal result |
| Specialist team | PASS | Lead Agent invokes real spawn/wait Tools for two descendants and aggregates them |
| Subworkflow node | PASS | Stable child run, child state/output, parent continuation, and child checkpoint |
| Cross-boundary cancellation | PASS | Agent subtree cancelled; nested parent/child runs checkpoint as interrupted |
| Cross-boundary observability | PASS | Parent run/node-correlated Agent and child workflow lifecycle events |
| Failure / resume | PASS | Failed child and parent resume; completed child node executes once |
| Focused regression | PASS | 21 workflow/hybrid tests pass |
| Examples | PASS | Examples 53–56 execute successfully |
| Real E2E | N/A | Hybrid control boundaries are in-process; external model E2E remains tracked under F27 |

## Full repository gates

- Pytest: 105 passed, eight credential/network compatibility tests explicitly skipped.
- Ruff: clean across `src`, `tests`, `tools`, and `examples`.
- Pyright strict: zero errors and zero warnings.
- Secret scan: passed.
- Docusaurus production build: passed.
- Source distribution and wheel: passed.
