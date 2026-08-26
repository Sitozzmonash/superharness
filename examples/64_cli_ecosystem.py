"""Install, inspect, and remove a local skill through the CLI."""

import os
import tempfile
from pathlib import Path

from super_harness.cli import main

with tempfile.TemporaryDirectory(prefix="super-harness-cli-example-") as temporary:
    project = Path(temporary)
    (project / ".git").mkdir()
    skill = project / "source" / "example-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: example-skill\ndescription: CLI example\n---\nFollow the example.",
        encoding="utf-8",
    )
    previous = Path.cwd()
    try:
        os.chdir(project)
        assert main(["skill", "add", str(skill)]) == 0
        assert main(["skill", "list"]) == 0
        assert main(["skill", "info", "example-skill"]) == 0
        assert main(["skill", "remove", "example-skill"]) == 0
    finally:
        os.chdir(previous)
