# Multi-Agent, Workflow and Hybrid Orchestration

## 1. Three orchestration modes

Super Harness supports all three:

### A. Autonomous (Codex-style)
A main agent dynamically decides whether/how to create subagents.

### B. Deterministic Workflow
Application defines the graph/order/conditions.

### C. Hybrid
Workflow nodes can run autonomous agents; autonomous agents can invoke subflows.

These are complementary, not competing.

## 2. Autonomous multi-agent

Core operations conceptually:
- `spawn_agent`
- `send_input`
- `wait`
- `resume_agent`
- `interrupt_agent`
- `close_agent`

Required metadata:
- agent ID
- parent agent ID
- root thread ID
- child thread/task ID
- role
- status
- created/completed timestamps
- model/provider
- budgets

## 3. Agent spawning

Main agent may specify:
- role/instructions
- task
- model override
- tools/skills subset
- sandbox policy
- context inheritance policy
- timeout
- budget

Avoid copying the complete parent context blindly. Provide configurable inheritance:
- minimal task context
- selected context fragments
- full snapshot (advanced)

## 4. Limits

Required guards:
- max active agents
- max total agents per turn
- max depth
- per-agent timeout
- total multi-agent budget
- cancellation propagation

## 5. Result aggregation

Child agent returns structured result:
- summary/result text
- status
- artifacts/references
- errors
- usage
- child trace IDs

Main agent receives concise result, not every child token by default.

## 6. Workflow engine

Domain concepts:
- `Workflow`
- `Node`
- `Edge`
- `WorkflowState`
- `WorkflowRun`
- `NodeResult`

Node types:
- agent node
- tool/function node
- router node
- subworkflow
- transform node
- gate/condition

## 7. Required execution patterns

### Sequential
A -> B -> C

### Parallel
A -> [B, C, D] -> Join

### Conditional
A -> condition -> B or C

### Router
input -> route function/LLM router -> target node

### Loop
node -> evaluate termination -> repeat with strict max iterations

### Retry
policy-driven retries with backoff and idempotency awareness

### DAG
Validate graph for unsupported cycles unless cycle is explicit loop construct.

## 8. Hybrid example

```text
Research workflow node
      |
      v
Autonomous Research Agent
  |       |        |
spawn   spawn    spawn
web     papers   critic
  \       |       /
    aggregated
      |
      v
Development workflow node
```

## 9. Event integration

Emit:
- agent.spawned
- agent.started
- agent.message
- agent.completed
- agent.failed
- workflow.started
- node.started
- node.completed
- node.failed
- route.selected
- workflow.completed

## 10. Persistence/resume

Workflow state should be serializable. A failed/interrupted workflow can resume from stable checkpoints where safe.

## 11. Examples required

Autonomous: at least 5
- research decomposition
- coding/review/test team
- parallel critics
- steer child
- cancellation/budget

Workflow: at least 5
- sequence
- parallel join
- conditional
- router
- retry/loop

Hybrid: at least 4
- autonomous node
- subworkflow
- workflow invoking specialist team
- failure/resume
