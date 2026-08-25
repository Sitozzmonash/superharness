"""Fail CI when project-owned text contains a likely live credential."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = (
    "src",
    "tests",
    "tools",
    "docs",
    "website/docs",
    ".github",
)
ROOT_FILES = (
    "README.md",
    "AGENTS.md",
    "pyproject.toml",
    ".env.example",
    "website/package.json",
    "website/docusaurus.config.js",
)
TEXT_SUFFIXES = {".css", ".html", ".js", ".json", ".md", ".py", ".toml", ".yaml", ".yml"}
LIVE_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{20,}"),
    re.compile(
        r"(?:DEEPSEEK_API_KEY|ZHIPU_SEARCH_API_KEY|ZHIPU_VISION_API_KEY|RAG_API_KEY)"
        r"\s*=\s*\S+"
    ),
)


def iter_project_text_files(root: Path = PROJECT_ROOT) -> Iterable[Path]:
    """Yield project-owned text files while excluding dependencies and generated artifacts."""
    for relative_root in SCAN_ROOTS:
        directory = root / relative_root
        if not directory.exists():
            continue
        for path in directory.rglob("*"):
            if path.is_file() and path.suffix in TEXT_SUFFIXES and "__pycache__" not in path.parts:
                yield path
    for relative_file in ROOT_FILES:
        path = root / relative_file
        if path.is_file():
            yield path


def find_likely_secrets(paths: Iterable[Path]) -> list[tuple[Path, int, str]]:
    """Return high-confidence credential matches with paths and line numbers."""
    findings: list[tuple[Path, int, str]] = []
    for path in paths:
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
        ):
            if any(pattern.search(line) for pattern in LIVE_SECRET_PATTERNS):
                findings.append((path, line_number, line.strip()))
    return findings


def main() -> int:
    """Run the repository scan and return a process exit code."""
    findings = find_likely_secrets(iter_project_text_files())
    if findings:
        for path, line_number, _line in findings:
            relative_path = path.relative_to(PROJECT_ROOT)
            print(f"likely secret: {relative_path}:{line_number}")
        return 1
    if (PROJECT_ROOT / ".env").exists():
        print("local .env must not be tracked or included in release material")
        return 1
    print("secret scan passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
