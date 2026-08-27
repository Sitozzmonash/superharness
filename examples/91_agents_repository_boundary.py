"""Stop AGENTS.md discovery at the nearest repository boundary."""

import tempfile
from pathlib import Path

from super_harness import AgentsMdLoader

with tempfile.TemporaryDirectory() as directory:
    outer = Path(directory)
    (outer / "AGENTS.md").write_text("outside", encoding="utf-8")
    repo = outer / "repo"
    child = repo / "src"
    child.mkdir(parents=True)
    (repo / ".git").mkdir()
    (repo / "AGENTS.md").write_text("inside", encoding="utf-8")
    print([fragment.content for fragment in AgentsMdLoader().load(child)])
