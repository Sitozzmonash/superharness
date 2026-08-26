# Phase 11 Security Review

Date: 2026-08-25

## Reviewed boundaries

| Boundary | Controls verified | Status |
|---|---|---|
| Secrets / telemetry | Masked wrapper, nested key/pattern/configured-value redaction, content omission, bounded traversal, failure tests | PASS |
| Tool input | Safe bounded names/call IDs, finite JSON-only cyclic/depth/item validation, Pydantic argument validation | PASS |
| Local paths | Resolved path confinement in restricted modes, read-only writes denied, installer path/symlink/archive checks | PASS |
| Shell / Python | Disabled unless local sandbox is explicitly `full_access`; process groups terminated on cancellation | PASS |
| RAG / search | Rendered as marked user-role external context; queries/content omitted from default telemetry | PASS |
| Skills | Metadata-first activation, confined resource reads, safe staged installation, source/revision provenance | PASS |
| Plugins | Data-only staged install and explicit activation; entry/path/version validation; rollback on conflict | PARTIAL |
| MCP | Official SDK negotiation, timeouts/cancellation, filters, pagination/size limits, HTTPS-capable auth headers, remote-risk tool metadata | PASS |
| Package/source | Pinned Codex reference, pinned compatibility fixtures, hashes for MCPB, secret scan, build validation | PASS |
| Concurrency | Thread-safe log/metrics/trace state; bounded Agent/workflow concurrency and load tests | PASS |

## Changes made

- Default telemetry drops prompt/model delta and request/response/tool content fields.
- Recursive redaction masks common assignments, bearer/JWT/OpenAI/GitHub-shaped tokens, secret-valued fields, configured exact values, `SecretValue`, exceptions, and application-hook results.
- Redaction is depth/item/string bounded and cycle aware.
- Model errors now emit `model.failed`; failed Tool results emit `tool.failed`.
- Tool names and model-returned ToolCall names reject whitespace, traversal/control characters, and excessive length.
- ToolCall IDs and raw arguments are bounded; JSON values reject cycles, deep nesting, non-string keys, non-finite numbers, and non-JSON objects.
- External knowledge and MCP observations contain metadata only.

## Residual risks and required deployment controls

1. `LocalSandbox` is path policy, not OS isolation. `full_access` child processes may access network and the host. Run untrusted code in an external container/VM policy; the planned Docker backend (F19) is not implemented.
2. Plugin Python entry points execute in-process after explicit `enable`. Install/inspection is safe, but activation must be limited to trusted reviewed plugins or wrapped by an application sandbox. This keeps F39 `PARTIAL`.
3. MCP authentication headers are application-provided. Use HTTPS, least-privilege short-lived credentials, allowlists, and explicit user approval for external-risk Tools.
4. Prompt-injection marking changes authority, not model fallibility. Applications must preserve citations, constrain side effects with approval/sandbox policy, and validate downstream actions.
5. Telemetry content can be enabled explicitly with `include_content=True`; applications then own data classification, retention, and exporter access control.
6. Local trace IDs are not W3C propagation headers. Cross-process trace propagation is deferred.
7. Python threads/tasks share process memory; resource exhaustion outside configured Agent/workflow/log/redaction bounds still requires process/container limits.

## Conclusion

Phase 11 delivers the required security review and concrete hardening, but strong execution isolation and trusted-plugin enforcement remain deployment/application responsibilities. The coverage matrix intentionally retains F39 as `PARTIAL` until those product gaps are closed.
