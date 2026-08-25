from __future__ import annotations

from pathlib import Path


def test_all_python_examples_compile() -> None:
    root = Path(__file__).parents[1] / "examples"
    files = sorted(root.glob("**/*.py"))
    assert len(files) >= 3
    for path in files:
        compile(path.read_text(encoding="utf-8"), str(path), "exec")
