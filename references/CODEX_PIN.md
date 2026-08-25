# Pinned Codex Reference

Super Harness studies a fixed OpenAI Codex revision before implementing equivalent runtime
features. Runtime code must not be developed against an unspecified moving `main` branch.

| Field | Value |
|---|---|
| Repository | `https://github.com/openai/codex.git` |
| Commit | `7c6eb0eef113ddc16ae5b207ac9add364b489798` |
| Commit timestamp | `2026-08-25T10:29:26Z` |
| Commit subject | `Scope stop hooks for memory consolidation (#40587)` |
| Resolved and pinned | `2026-08-25` |
| Local path | `references/codex/` |

The reference is registered as a shallow Git submodule. Clone it with:

```bash
git submodule update --init --depth 1 references/codex
```

Verify the checkout:

```bash
git -C references/codex rev-parse HEAD
```

Expected output:

```text
7c6eb0eef113ddc16ae5b207ac9add364b489798
```

If a later feature needs Codex history outside this shallow checkout, deepen the submodule without
changing the recorded commit. Any intentional pin update requires a decision-log entry and a review
of affected research notes.

