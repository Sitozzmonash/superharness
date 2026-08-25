# Configuration and Secrets Specification

## 1. Configuration precedence

Highest priority first:

1. explicit runtime arguments
2. environment variables
3. project `.super-harness/config.toml` or `config.yaml`
4. user `~/.super-harness/config.toml`
5. built-in defaults

Document and test the exact precedence.

## 2. Recommended config

Prefer a typed internal configuration model. Support TOML as canonical runtime format if practical; YAML may be supported as user-friendly input. Avoid maintaining divergent semantics.

Example:

```toml
[model]
provider = "deepseek"
model = "deepseek-v4-flash"

[vision]
provider = "zhipu"
model = "glm-4v-flash"

[web_search]
provider = "zhipu"
count = 10

[approval]
mode = "full_access"

[sandbox]
backend = "local"
mode = "workspace_write"

[multi_agent]
max_agents = 6
max_depth = 2

[persistence]
backend = "sqlite"
path = ".super-harness/state.db"
```

## 3. Profiles

Profiles allow China/global/offline/dev/test combinations without code forks.

Example conceptual profiles:
- `china`
- `global`
- `offline`
- `test`

A profile is configuration composition, not a separate package.

## 4. Secrets

Use environment variables or user-supplied secret resolvers.

Requirements:
- never serialize raw secret values in persisted Thread/Turn/Event objects;
- mask secrets in repr/logs;
- redact common bearer/API key patterns;
- support custom SecretProvider in future;
- document `.env` for local development only;
- `.env` must be gitignored.

## 5. `.env.example`

Repository may include:

```env
DEEPSEEK_API_KEY=
ZHIPU_SEARCH_API_KEY=
ZHIPU_VISION_API_KEY=
RAG_BASE_URL=http://127.0.0.1:8765
RAG_API_KEY=
SUPER_HARNESS_E2E=0
```

## 6. Diagnostics

`super-harness doctor` should report:
- Python version
- package version
- config sources found
- provider configured? yes/no, never secret value
- Docker availability
- MCP runtime prerequisites
- writable state directory
- docs/examples compatibility version
