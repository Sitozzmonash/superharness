# Phase 0 Status

Date: 2026-08-25

## Outcome

The Phase 0 repository and research foundation is implemented and passes the complete local
equivalent of the configured quality workflow. No runtime feature is represented as complete, and
the copied coverage matrix remains the authoritative all-TODO baseline.

## Local acceptance evidence

| Gate | Result | Evidence |
|---|---|---|
| Editable clean-environment install | PASS | Fresh `.venv`; `pip install -e ".[dev]"` succeeded |
| Ruff format | PASS | 15 project-owned files formatted |
| Ruff lint | PASS | All checks passed |
| Pyright strict | PASS | 0 errors, 0 warnings |
| Pytest | PASS | 13 tests passed |
| Secret scan | PASS | High-confidence scan passed; repository `.env` absent |
| CLI entry point | PASS | `super-harness 0.0.1.dev0` |
| Codex pin | PASS | Local HEAD equals `7c6eb0eef113ddc16ae5b207ac9add364b489798` |
| Coverage baseline copy | PASS | Source and repository SHA-256 both `A733AFE9FDD3D72B5F3ECF42E3C72BD142911C2FADA0340DF0F1CF325F85AF4B` |
| Reproducible docs install | PASS | `npm ci` installed from `package-lock.json` |
| Docusaurus production build | PASS | Client/server bundles compiled; static files generated |
| Broken docs links | PASS | Docusaurus build configured to throw; build completed |

## Explicitly pending external evidence

- No Git remote is configured, so GitHub Actions has not run on an external runner.
- GitHub Pages has not been deployed; F34 deployment evidence remains TODO.
- No provider credentials were used and no real-provider E2E belongs to Phase 0.

## Known dependency risk

`npm audit --audit-level=high` reports 18 high and 6 moderate vulnerabilities in the current
Docusaurus 3.10.2 transitive build/development dependency tree. The high findings are rooted in
`image-size` and `serialize-javascript`; npm reports no fix currently available through the selected
Docusaurus release. The generated website is static, but CI and local documentation builds process
repository-controlled content with these packages. Track upstream fixes and do not treat the later
security/hardening release gate as PASS while applicable high findings remain unresolved.

## Next roadmap step

Phase 1 must begin with pinned-Codex research notes for the model provider abstraction, runtime loop,
Thread/Turn, streaming events, and structured tool-call normalization. Implementation starts only
after those source files and tests are inspected and their behavioral contracts are recorded.

