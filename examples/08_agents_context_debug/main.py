"""Discover hierarchical AGENTS.md and inspect redacted context."""

import tempfile
from pathlib import Path

from super_harness import Agent, DeepSeekProvider


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / ".git").mkdir()
        nested = root / "src"
        nested.mkdir()
        (root / "AGENTS.md").write_text("Root rule", encoding="utf-8")
        (nested / "AGENTS.override.md").write_text(
            "Nested rule; api_" + "key=example-sensitive-value", encoding="utf-8"
        )
        thread = Agent(DeepSeekProvider(), cwd=str(nested)).thread()
        for entry in thread.debug_context().entries:
            print(entry.priority, entry.source, entry.content)


if __name__ == "__main__":
    main()
