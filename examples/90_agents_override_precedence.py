"""Prefer AGENTS.override.md over AGENTS.md in the same directory."""

import tempfile
from pathlib import Path

from super_harness import AgentsMdLoader

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    (root / ".git").mkdir()
    (root / "AGENTS.md").write_text("ordinary", encoding="utf-8")
    (root / "AGENTS.override.md").write_text("override", encoding="utf-8")
    print([fragment.content for fragment in AgentsMdLoader().load(root)])
