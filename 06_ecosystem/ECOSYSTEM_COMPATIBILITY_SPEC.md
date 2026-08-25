# Ecosystem Compatibility Specification

## 1. Principle

**Consume existing standards before inventing proprietary formats.**

## 2. Agent Skills

Use the open Agent Skills specification:
- directory with `SKILL.md`;
- YAML frontmatter;
- required name/description;
- optional scripts/references/assets;
- progressive disclosure.

Authoritative spec should be checked during implementation:
- https://openagentskills.dev/docs/specification
- project repository for Agent Skills reference tooling

Compatibility target:
- a standard skill should not need a Super Harness rewrite.

## 3. Skill installation semantics

Sources:
- local directory
- git repository
- GitHub repo/subdirectory
- plugin-provided
- future registry source

Store source metadata:
- source type
- URL/path
- revision/commit
- installed time
- version if declared

Install scopes:
- global `~/.super-harness/skills/`
- project `.agents/skills/`
- project `.super-harness/skills/`

## 4. Codex skills

Install and test several publicly available Codex/Agent Skills that are license-compatible. The goal is compatibility proof, not bundling arbitrary copyrighted repositories.

Prefer fetching in tests/examples rather than copying third-party content into distribution unless licensing is explicit.

## 5. MCP

Use official MCP Python SDK/protocol.

Primary transports:
- stdio
- Streamable HTTP

Support common ecosystem server launch patterns:
- `npx`
- `uvx`
- Python command
- direct executable

Registry:
- official MCP Registry is currently preview;
- implement behind a replaceable registry client if included;
- never make registry availability required to use MCP.

## 6. Plugin compatibility

Plugins are less universally standardized than MCP/Agent Skills.

Therefore:
- define a small Super Harness plugin manifest;
- import Codex-compatible plugin structures best-effort;
- keep internal capability interfaces independent from manifest format;
- document compatibility matrix by field/capability.

## 7. Python tool packages

Third-party Python extensions may use package entry points.

Suggested groups:
- `super_harness.tools`
- `super_harness.plugins`

Do not auto-execute untrusted entry points without explicit install/enable behavior.

## 8. Version conflicts

Installers must report:
- duplicate name
- incompatible framework version
- missing dependencies
- unsupported manifest field
- invalid skill frontmatter
- MCP launch failure

No silent overwrites.

## 9. Compatibility test matrix

Release should publish tested combinations:
- standard Agent Skill
- GitHub subdir install
- Codex-compatible skill
- local stdio MCP
- npx MCP
- uvx/Python MCP
- HTTP MCP
- plugin with skill/tool/hook
- Python function tool
- runtime dynamic tool

State exact tested version/revision.
