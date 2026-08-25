# Persistence, Events and Observability

## 1. Persistence goal

Persist enough structured state to:
- resume thread;
- fork thread;
- inspect prior turns;
- recover workflow checkpoints;
- query memory;
- debug execution;
- correlate traces.

Default backend: SQLite.

Do not require a server database for local use.

## 2. Suggested persistent entities

- threads
- turns
- events
- messages/items
- tool calls/results
- agent tasks
- workflow runs/node runs
- compaction summaries
- memories
- provider usage
- artifacts metadata

Use schema migrations from first release.

## 3. Event model

Events are immutable observations.

Common fields:
- event_id
- type
- timestamp
- thread_id
- turn_id
- agent_id
- parent_agent_id optional
- workflow_run_id optional
- node_id optional
- tool_call_id optional
- payload
- trace_id/span_id optional

## 4. Event taxonomy

Minimum:
- thread.created
- turn.started/completed/failed/interrupted
- model.started/delta/completed/failed
- tool.started/completed/failed
- search.started/completed/failed
- rag.started/completed/failed
- mcp.connected/call.started/call.completed/call.failed
- compaction.started/completed
- agent.spawned/started/completed/failed
- workflow.started/node.started/node.completed/node.failed/completed
- error

Do not expose hidden chain-of-thought. Reasoning metadata must respect provider/safety constraints.

## 5. Streaming API

```python
async for event in thread.astream("task"):
    ...
```

Streaming must continue through tool/subagent events, not only text token deltas.

Final result is available as terminal event/handle result.

## 6. Structured logs

Default logger should output human-readable console plus optional JSONL.

Log fields:
- timestamp
- level
- event
- IDs
- duration
- provider/model/tool
- status
- error class
- redacted details

## 7. Metrics

Where available:
- input/output tokens
- cached tokens
- latency
- provider errors
- tool durations
- RAG/search latency
- active agents
- workflow node duration
- retries
- cost estimate

## 8. OpenTelemetry

Provide optional OTEL exporter/instrumentation without making it a core runtime dependency if avoidable.

Trace hierarchy example:
```text
thread
  turn
    model_call
    tool_call
    rag_call
    child_agent
      child_turn
```

## 9. Redaction

Before logging/persisting telemetry:
- mask API keys/bearer tokens;
- redact configured secret fields;
- avoid raw environment dumps;
- allow application redaction hooks.

## 10. Debug tooling

CLI ideas:
```bash
super-harness thread inspect <id>
super-harness trace show <trace_id>
super-harness doctor
```

Debug views must be useful without exposing secrets.
