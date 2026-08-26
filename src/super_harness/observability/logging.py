"""Human-readable console and machine-readable JSONL logging."""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from typing import TextIO

from .models import StructuredLogRecord


class StructuredLogger:
    """Thread-safe structured logger with independently optional outputs."""

    def __init__(
        self,
        *,
        console: TextIO | None = sys.stderr,
        jsonl: str | Path | TextIO | None = None,
    ) -> None:
        self.console = console
        self._owns_jsonl = isinstance(jsonl, (str, Path))
        self.jsonl = (
            Path(jsonl).open("a", encoding="utf-8")  # noqa: SIM115 - owned until close()
            if isinstance(jsonl, (str, Path))
            else jsonl
        )
        self._lock = threading.RLock()

    def log(self, record: StructuredLogRecord) -> None:
        with self._lock:
            if self.console is not None:
                identifiers = " ".join(
                    value
                    for value in (
                        f"trace={record.trace_id}" if record.trace_id else "",
                        f"thread={record.thread_id}" if record.thread_id else "",
                        f"turn={record.turn_id}" if record.turn_id else "",
                        f"agent={record.agent_id}" if record.agent_id else "",
                        f"workflow={record.workflow_run_id}" if record.workflow_run_id else "",
                        f"node={record.node_id}" if record.node_id else "",
                    )
                    if value
                )
                duration = (
                    f" duration_ms={record.duration_ms:.3f}"
                    if record.duration_ms is not None
                    else ""
                )
                suffix = f" {identifiers}" if identifiers else ""
                self.console.write(
                    f"{record.timestamp.isoformat()} {record.level} {record.event}"
                    f"{duration}{suffix}\n"
                )
                self.console.flush()
            if self.jsonl is not None:
                self.jsonl.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
                self.jsonl.flush()

    def close(self) -> None:
        if self._owns_jsonl and self.jsonl is not None:
            self.jsonl.close()

    def __enter__(self) -> StructuredLogger:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
