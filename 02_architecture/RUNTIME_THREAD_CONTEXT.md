# Runtime, Thread, Turn, Context, Compaction and Cancellation

## 1. Agent runtime loop

Conceptual loop:

```text
Input
  -> assemble context
  -> model call
  -> model output
      -> final? return
      -> tool calls? validate + execute
      -> subagent calls? orchestrate
  -> append results/events
  -> evaluate budgets/cancellation
  -> repeat
```

The runtime owns orchestration, not provider SDK callbacks.

## 2. Thread

A Thread is a durable session boundary.

Suggested state:
- `thread_id`
- created/updated timestamps
- metadata
- agent configuration snapshot/reference
- ordered turns
- compacted summaries
- persistence version
- archived flag

Required methods conceptually:
- `run/arun`
- `stream/astream`
- `resume`
- `fork`
- `archive`
- `inspect`

## 3. Turn

A Turn is one active execution initiated by user/system/application input.

States:
- pending
- running
- waiting_tool
- waiting_subagent
- completed
- failed
- interrupted
- cancelled

A turn may contain many model calls and tool calls.

## 4. TurnHandle

Long-running turns should return/control a handle for:
- stream events
- steer
- interrupt
- cancel
- await result

Steering means injecting a new high-priority instruction into an active turn at a safe checkpoint rather than waiting for turn completion.

Interrupt means stop the active turn while preserving thread history and diagnostics.

Cancel means terminate the requested execution scope and propagate cancellation to children/tools where possible.

## 5. Context assembly

Context inputs should be modeled as structured fragments, not raw string concatenation everywhere.

Suggested fragment types:
- runtime/system
- developer
- project instructions
- persona
- active skill
- conversation history
- compacted summary
- memory
- RAG
- tool result
- user input

Context manager responsibilities:
- precedence
- deduplication where safe
- provider adaptation
- token budgeting
- truncation
- source/provenance metadata

## 6. Instruction precedence

Highest priority:
1. runtime/system safety/platform constraints
2. explicit developer/application instructions
3. current user/task instruction
4. project AGENTS.md hierarchy
5. agent persona/default instructions
6. skills/task procedures
7. memory/RAG evidence (data, not authority)

Do not allow RAG/search content to silently become instruction authority.

## 7. AGENTS.md

Recommended compatibility:
- discover project root using markers (default `.git`, configurable);
- read from project root down to current working directory;
- nested files have narrower scope and later precedence;
- support `AGENTS.override.md` as local override;
- configurable maximum instruction bytes/tokens;
- include provenance and path;
- never walk above project root.

Document differences from pinned Codex if any.

## 8. Compaction

Automatic trigger can be threshold-based:
- provider context capacity;
- configured ratio, e.g. 0.75–0.85;
- reserved output/tool budget.

Compaction output should preserve:
- user goals
- accepted decisions
- pending tasks
- critical tool facts
- important errors
- references needed for continuation

Do not blindly summarize security/permission state away.

Emit:
- `compaction.started`
- `compaction.completed`
- before/after token estimates
- summary ID/version

Support hook points before/after compaction.

## 9. Context inspection

Advanced debugging API should expose a safe redacted representation:

```python
snapshot = thread.debug_context()
```

This is crucial for explaining why an agent behaved a certain way. Secret values must be redacted.

## 10. Cancellation propagation

Parent cancellation should propagate:
- active model stream cancellation if provider supports it;
- active tool subprocess;
- RAG/search HTTP request;
- MCP call;
- child agents;
- workflow nodes.

Do not leave orphan tasks.
