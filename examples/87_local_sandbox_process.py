"""Run an argv-based local process with cancellation-safe cleanup."""

import asyncio
import sys
from pathlib import Path

from super_harness import LocalSandbox

result = asyncio.run(LocalSandbox(Path.cwd()).run_exec((sys.executable, "-c", "print(6 * 7)")))
print(result.stdout.strip())

