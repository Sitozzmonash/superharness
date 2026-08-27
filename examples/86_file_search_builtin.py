"""Search workspace files through the sandboxed built-in Tool."""

import asyncio
import tempfile
from pathlib import Path

from super_harness import LocalSandbox
from super_harness.tools import file_search_tool


async def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "notes.txt").write_text("release ready", encoding="utf-8")
        result = await file_search_tool(LocalSandbox(root)).invoke({"pattern": "*.txt"})
        print(result)


asyncio.run(main())
