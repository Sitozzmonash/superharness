# Execution, Tools, Sandbox and Approval

## 1. Tool abstraction

A tool has:
- name
- description
- input schema
- optional output schema/metadata
- async callable
- capability/risk metadata
- namespace/source
- timeout policy

Python ergonomic API:

```python
from super_harness import tool

@tool
async def lookup_order(order_id: str) -> dict:
    ...
```

## 2. Registry

`ToolRegistry` responsibilities:
- register/unregister
- name conflict rules
- namespace
- list/search
- enable/disable
- provider schema conversion
- deferred/lazy loading
- tool source metadata (builtin/plugin/MCP/runtime)

Do not push every tool's full schema into context if the set becomes large.

## 3. Tool execution pipeline

```text
Model tool request
 -> schema validation
 -> approval policy
 -> PreToolUse hooks
 -> sandbox/environment selection
 -> execution
 -> timeout/cancellation
 -> output normalization/truncation
 -> PostToolUse hooks
 -> event + trace
 -> append ToolResult to context
```

## 4. Built-in tools

V1 should include:
- shell
- file read
- file write
- file search
- patch/edit
- Python execution
- web search
- RAG retrieve
- optional vision analysis adapter
- autonomous subagent tools

Each has separate permissions and tests.

## 5. Output limits

Tool results can destroy context if unbounded.

Implement:
- byte/character/token estimates
- head/tail truncation options
- artifact/file references for large output
- metadata indicating truncation
- clear docs

## 6. Sandbox abstraction

Suggested protocol:
- prepare execution
- run command
- read/write allowed paths
- terminate
- describe capabilities

Backends:

### LocalProcessSandbox
For developer convenience. Uses constrained cwd/env/path checks but is not treated as a strong security boundary.

### DockerSandbox
For stronger isolated execution. Configure:
- workspace mount
- read-only mounts
- network mode
- environment allowlist
- CPU/memory/pids
- timeout
- cleanup

Potential future platform-specific backends can be plugins.

## 7. Sandbox policy modes

Expose conceptual modes:
- `read_only`
- `workspace_write`
- `full_access`

Default product policy may be permissive during initial development, but tests must verify restricted modes.

## 8. Approval engine

V1 default:

```text
approval.mode = full_access
```

But engine must support:
- allow
- deny
- ask (callback/UI boundary)
- custom policy

Policy input may include:
- tool
- arguments
- filesystem paths
- network target
- command risk
- source (MCP/plugin/runtime)
- agent identity
- workflow identity

## 9. Hooks are not approval

Hooks are generic lifecycle extension points. Approval is a dedicated decision subsystem. A hook may enrich/audit approval but must not be the only security architecture.

## 10. Testing

Must test:
- validation failures
- timeout
- cancellation
- output truncation
- denied operation
- read-only violation
- workspace path escape
- Docker cleanup
- concurrent tools
- child process cleanup
