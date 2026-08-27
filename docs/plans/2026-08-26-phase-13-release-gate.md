# Phase 13 — Documentation and Release Gate

Date: 2026-08-26

## Objective

Close every locally achievable V1 matrix gap, audit the complete documentation/example surface,
record machine-readable release evidence, and tag V1 only if every required external gate is
actually proven.

## Implementation route

1. Add real deferred Tool loaders, a provider-neutral Router, Persona/Role configuration,
   deterministic config/profile/secret resolution, observable provider fallback, and a bounded
   Docker Sandbox backend.
2. Test unit behavior, integration boundaries, cancellation, timeout, cleanup, precedence,
   secret non-disclosure, and concurrent access.
3. Add at least three runnable examples for every newly closed cross-cutting matrix row.
4. Audit User Guide, Internals, API reference, Examples, Compatibility, Troubleshooting, website
   production build, package/wheel smoke, and GitHub Pages workflow.
5. Store a machine-readable release summary and update every matrix cell from evidence.
6. Run all local gates and push a release-candidate commit.
7. Create a V1 tag only if credentialed provider/search/vision and required Docker/external
   compatibility gates have real PASS evidence. Missing credentials/runtimes are explicit release
   blockers, never converted to PASS or N/A for convenience.

## Safety constraints

- Docker defaults to no network, a read-only root filesystem, dropped capabilities, bounded
  CPU/memory/PIDs, and `--rm`; only validated mounts and allowlisted environment values cross the
  boundary.
- Fallback never catches caller cancellation and never switches after visible streamed output.
- Persona is typed configuration rendered as developer instructions; user/external content cannot
  impersonate it.
- Config diagnostics expose source names and secret presence only.
