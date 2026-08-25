"""In-memory Turn state."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from super_harness.models import ModelResponse


class TurnStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_TOOL = "waiting_tool"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class Turn:
    """One user-initiated execution and its terminal diagnostics."""

    input: str
    turn_id: str = field(default_factory=lambda: str(uuid4()))
    status: TurnStatus = TurnStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    response: ModelResponse | None = None
    error: str | None = None

    def start(self) -> None:
        if self.status is not TurnStatus.PENDING:
            raise RuntimeError("only a pending turn can start")
        self.status = TurnStatus.RUNNING
        self.started_at = datetime.now(UTC)

    def complete(self, response: ModelResponse) -> None:
        if self.status is not TurnStatus.RUNNING:
            raise RuntimeError("only a running turn can complete")
        self.response = response
        self.status = TurnStatus.COMPLETED
        self.completed_at = datetime.now(UTC)

    def fail(self, error: BaseException) -> None:
        self.error = str(error)
        self.status = TurnStatus.FAILED
        self.completed_at = datetime.now(UTC)

    def cancel(self) -> None:
        self.status = TurnStatus.CANCELLED
        self.completed_at = datetime.now(UTC)
