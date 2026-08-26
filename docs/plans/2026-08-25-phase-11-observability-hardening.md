# Phase 11 Plan: Observability and Hardening

1. Study pinned Codex event/log/trace/metrics/OTEL/redaction designs and freeze provider-neutral contracts.
2. Implement bounded secret redaction, human console plus JSONL logs, hierarchical spans, validated metrics, token/cost accounting, and optional OTEL export.
3. Integrate one observer with Thread/model/tool, AgentManager, WorkflowEngine, Search/RAG/Vision, and MCP lifecycle boundaries.
4. Harden tool identifiers, call IDs, and JSON schemas; review sandbox, plugin/skill, MCP, external-data, source-integrity, and secure-default boundaries.
5. Add failure, secret leakage, malicious input, concurrency/load, and regression tests plus six runnable observability/security examples.
6. Record residual risks truthfully, update documentation/matrix, run every gate, commit, and push.
