# Codex Research: Plugins and Hooks

## Codex files inspected

- `codex-rs/core-plugins/src/manifest.rs`
- `codex-rs/core-plugins/src/loader.rs`
- `codex-rs/core-plugins/src/manager.rs`
- `codex-rs/core-plugins/src/store.rs`
- `codex-rs/core-plugins/src/executor_hooks.rs`
- `codex-rs/hooks/src/types.rs`
- `codex-rs/hooks/src/engine/dispatcher.rs`
- `codex-rs/hooks/src/engine/mod.rs`

## Codex tests inspected

- `codex-rs/core-plugins/src/agent_plugin_manifest_tests.rs`
- `codex-rs/core-plugins/src/loader_tests.rs`
- `codex-rs/core-plugins/src/manager_tests.rs`
- `codex-rs/core-plugins/src/store_tests.rs`
- `codex-rs/core-plugins/src/executor_hooks_tests.rs`
- `codex-rs/hooks/src/engine/mod_tests.rs`
- `codex-rs/hooks/src/engine/command_runner_tests.rs`
- `codex-rs/app-server/tests/suite/v2/plugin_install.rs`
- `codex-rs/app-server/tests/suite/v2/plugin_uninstall.rs`

## Behavioral contract

A plugin is inert metadata until explicitly enabled. Manifests resolve capability paths under the plugin root, disabled plugins contribute nothing, duplicate identities and incompatible versions are reported, and install/update operations validate before activation. Hooks are ordered, attributed, time-bounded lifecycle interceptors with explicit mutation/denial permissions and observable failure outcomes.

## Important invariants

- Plugin names and versions are filesystem safe and conflicts never overwrite silently.
- Manifest paths start with `./`, reject parent traversal, and resolve under the plugin root.
- Installation rejects symbolic links, records source/revision/time, and executes no plugin code.
- Only explicit `enable` imports Python entry points; disable removes every registered tool and hook.
- Activation is transactional: partial tool/hook registration is rolled back on conflict or failure.
- Hook priority is deterministic and cancellation always propagates.
- Hook callbacks have finite timeouts and configurable `fail_open`, `fail_closed`, or `warn` behavior.
- Hook denial is limited to declared safe interception points and does not replace approval policy.
- Every execution records hook/plugin source attribution and outcome traces.

## OpenAI-specific coupling to remove

Codex includes marketplace services, remote bundles, app/connectors, product policy, Rust executor environments, command hooks, and managed enterprise configuration. Super Harness keeps capability interfaces local and provider-neutral. It imports stable Codex manifest metadata best-effort but does not require OpenAI services and does not auto-execute Codex command/MCP hooks.

## Python-native design

`HookRegistry` stores typed `HookRegistration` values and dispatches immutable `HookContext` through sync or async callbacks. `HookResult` can enrich allowed data or deny eligible events; `HookTrace` records attribution, duration, success, warning, and denial. Agent, Thread, compaction, model, and tool pipelines emit lifecycle events.

`PluginInstaller` stages local or pinned HTTPS Git/GitHub sources and supports install/update/remove. `load_plugin` parses `.super-harness/plugin.toml` or `.codex-plugin/plugin.json`. `PluginManager.enable` explicitly imports declared Python `Tool`/hook symbols, namespaces them, loads MCP config, exposes Skill roots and passive assets/personas/commands, and rolls back conflicts.

## Differences/intentional extensions

- Adds a compact TOML overlay with an explicit framework version specifier and Python entry symbols.
- Keeps Codex apps/interface metadata passive and reports unsupported fields as warnings.
- Treats Codex command/MCP hooks as metadata-only because executing untrusted shell definitions would violate the explicit-enable Python contract.
- Exposes all fourteen roadmap lifecycle events, including future subagent points before Phase 8 integration.
- Supports recoverable local-source updates with staging and backup restoration.

## Tests to reproduce behavior

- Every hook event, deterministic priority, data enrichment, eligible denial, tracing, timeout, three failure policies, and cancellation.
- Real Agent/model/tool/compaction/error/session lifecycle dispatch and pre-tool argument modification after approval.
- Local plugin install without code execution, capability bundle activation, namespacing, MCP/Skill contribution, hook behavior, trace output, disable, update, and remove.
- Incompatible framework version, invalid paths, duplicate tool conflict, transactional rollback, and Codex manifest import.
- Pinned official `openai/plugins` `plugin-eval` GitHub subdirectory installation and validation at commit `11c74d6ba24d3a6d48f54a194cd00ef3beea18f9`.
