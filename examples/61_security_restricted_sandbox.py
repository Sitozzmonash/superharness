"""Use path and process denial in a restricted local sandbox."""

import tempfile
from pathlib import Path

from super_harness import LocalSandbox, SandboxMode
from super_harness.exceptions import SandboxError

with tempfile.TemporaryDirectory() as directory:
    sandbox = LocalSandbox(Path(directory), SandboxMode.READ_ONLY)
    print("allowed read path:", sandbox.resolve("input.txt"))
    for operation in (
        lambda: sandbox.resolve("output.txt", write=True),
        lambda: sandbox.resolve(Path(directory).parent / "escape.txt"),
        sandbox.require_process_access,
    ):
        try:
            operation()
        except SandboxError as error:
            print("denied:", error)
