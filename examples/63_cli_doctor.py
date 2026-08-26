"""Run the offline diagnostics command with machine-readable output."""

from super_harness.cli import main

raise SystemExit(main(["--json", "doctor"]))
