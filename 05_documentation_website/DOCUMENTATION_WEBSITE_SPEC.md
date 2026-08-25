# Documentation Website Specification

## 1. Goal

Create one official Super Harness documentation website deployable to GitHub Pages.

Recommended stack: **Docusaurus** because the project needs:
- large hierarchical docs;
- multiple doc sections;
- versioning potential;
- MD/MDX;
- code highlighting;
- search integration;
- GitHub Pages;
- future i18n.

VitePress is acceptable only if it demonstrably satisfies the same long-term requirements.

## 2. Top-level navigation

- Home
- Get Started
- User Guide
- Architecture & Internals
- Examples
- API Reference
- Ecosystem
- Compatibility & Testing
- Troubleshooting
- GitHub

## 3. Core separation

### User Guide
Answers: **How do I use it?**

No deep internal implementation unless required to avoid misuse.

### Architecture & Internals
Answers: **How does it work and why is it designed this way?**

Includes Codex mapping and Python-native decisions.

## 4. Example rule

Every core code sample on the docs website must be:
- copied/generated from, or kept in sync with, an actual runnable file under `examples/`;
- tested in CI or a documented smoke suite.

Avoid large unverified snippets.

Each page should link:

```text
View complete runnable example
```

to repository source.

## 5. Per-feature User Guide template

1. What it is
2. When to use it
3. Prerequisites
4. Quick start
5. Configuration
6. Basic example
7. Real-world example
8. Advanced example
9. API usage
10. Agent automatic usage if applicable
11. Events/streaming
12. Errors/timeouts/retries
13. Combining with other features
14. Security notes
15. Troubleshooting
16. Links to runnable examples
17. Links to internals/API reference

## 6. Per-feature Internals template

1. Responsibilities
2. Data model
3. Lifecycle diagram
4. Key interfaces/classes
5. Concurrency/cancellation
6. persistence
7. events/observability
8. Codex reference and files inspected
9. Python-native redesign
10. intentional differences
11. failure model
12. extension points
13. tests
14. limitations/future work

## 7. Website CI

On pull request:
- build docs;
- fail broken internal links;
- validate frontmatter;
- run example smoke tests;
- optional snippet-sync check;
- check for secret patterns.

On main:
- build;
- deploy GitHub Pages via GitHub Actions.

## 8. Versions

At minimum show framework version in docs. When API stabilizes, add versioned docs. Do not let docs silently describe unreleased `main` APIs as stable.

## 9. Language

Initial documentation can be English-first or bilingual, but structure must be i18n-friendly. User requested extreme clarity and detail; prioritize completeness over terse marketing language.
