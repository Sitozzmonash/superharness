# Codex Research: Skills and MCP

## Codex files inspected

- `codex-rs/skills/src/loading.rs`
- `codex-rs/skills/src/model.rs`
- `codex-rs/skills/src/parser.rs`
- `codex-rs/ext/skills/src/loader/discovery.rs`
- `codex-rs/ext/skills/src/loader/metadata.rs`
- `codex-rs/codex-mcp/src/connection_manager.rs`
- `codex-rs/codex-mcp/src/connection_manager/resources.rs`
- `codex-rs/codex-mcp/src/connection_manager/tool_catalog.rs`

## Codex tests inspected

- `codex-rs/skills/src/loading_tests.rs`
- `codex-rs/skills/src/model_tests.rs`
- `codex-rs/skills/src/parser_tests.rs`
- `codex-rs/ext/skills/src/loader/discovery_tests.rs`
- `codex-rs/codex-mcp/src/connection_manager_tests.rs`
- `codex-rs/codex-mcp/src/pagination_tests.rs`
- `codex-rs/config/src/mcp_types_tests.rs`
- `codex-rs/core/src/mcp_tool_call_tests.rs`

## Behavioral contract

Skills are discovered as inexpensive metadata, activated only when selected, and load supporting resources only on demand. Higher-precedence roots win deterministically and collisions remain inspectable. MCP connections expose server tools, resources, prompts, capabilities, source identity, filters, bounded pagination, timeout, and cancellation over standard transports.

## Important invariants

- `SKILL.md` has validated YAML frontmatter and non-empty instructions.
- Discovery does not eagerly inject every Skill body or resource into context.
- Installations stage and validate content, reject overwrite, path escape, and symbolic links, and record the resolved source revision.
- MCP uses the official SDK rather than a private wire protocol.
- Streamable HTTP targets `2026-07-28`; the client also interoperates with representative 2025 servers.
- Catalog pagination, cursor size, operation time, archive count, and archive size are bounded.
- Tool filters apply both to advertised adapters and direct invocation.
- Cancellation propagates; operational failures become typed `MCPError` values.

## OpenAI-specific coupling to remove

Codex has Rust-specific host services, internal app routing, config types, telemetry, and product-owned Skill roots. Super Harness keeps Skill roots explicit and exposes Python values. MCP behavior is delegated to the official Python SDK, while registry and installation adapters are replaceable and contain no OpenAI service dependency.

## Python-native design

`SkillCatalog` performs ordered metadata discovery and activates an `ActivatedSkill` on demand. `SkillInstaller` accepts local directories and HTTPS Git/GitHub subdirectories, checks out the requested revision, validates before copying, and records provenance. `MCPClient` wraps the official SDK `Client` for stdio and Streamable HTTP and converts remote tools into normal Super Harness `Tool` objects. Separate helpers import common `mcpServers` JSON, validate/install `.mcpb` archives, and query the Official MCP Registry preview API behind an `MCPRegistry` protocol.

## Differences/intentional extensions

- Skill installation requires filesystem-safe kebab-case names.
- Third-party unquoted descriptions containing a colon receive a narrow compatibility repair.
- MCPB installation enforces file-count and uncompressed-size limits and resolves `${__dirname}` only after extraction.
- Git revisions are resolved to and recorded as immutable commit hashes.
- External compatibility checks are opt-in so the default suite remains deterministic and offline.

## Tests to reproduce behavior

- Metadata-only discovery, precedence, collision reporting, activation, and resource path confinement.
- Local installation metadata, duplicate rejection, removal, invalid frontmatter, and pinned GitHub subdirectory installation.
- Real stdio tools/resources/prompts and Streamable HTTP `2026-07-28` negotiation through the official SDK.
- Timeout mapping, cancellation propagation, filters, config import, and tool adaptation.
- Official MCP 1.x server compatibility using an isolated `mcp==1.29.1` process.
- MCPB integrity, traversal/symlink/size controls, installation path resolution, and real Registry search.
