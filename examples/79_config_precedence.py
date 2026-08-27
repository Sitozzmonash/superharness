"""Show environment and runtime precedence over a project file."""

import tempfile
from pathlib import Path

from super_harness import ConfigResolver

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    (root / ".git").mkdir()
    (root / ".super-harness").mkdir()
    (root / ".super-harness" / "config.toml").write_text('[model]\nmodel="project"\n', encoding="utf-8")
    resolved = ConfigResolver(user_config=root / "missing.toml").resolve(
        cwd=root,
        environment={"SUPER_HARNESS_MODEL": "environment"},
        runtime={"model": {"model": "runtime"}},
    )
    print(resolved.config.model.model)

