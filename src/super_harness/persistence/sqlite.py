"""Versioned transactional SQLite Thread snapshots."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from super_harness.context import ContextSummary
from super_harness.models import Message, MessageRole, ModelResponse, ToolCall, Usage
from super_harness.runtime.turn import Turn, TurnStatus


@dataclass(frozen=True, slots=True)
class ThreadSnapshot:
    thread_id: str
    created_at: datetime
    updated_at: datetime
    instructions: str | None
    archived: bool
    parent_thread_id: str | None
    metadata: Mapping[str, Any]
    messages: tuple[Message, ...]
    turns: tuple[Turn, ...]
    summaries: tuple[ContextSummary, ...]


def _tool_call_data(call: ToolCall) -> dict[str, Any]:
    return {
        "call_id": call.call_id,
        "name": call.name,
        "arguments": dict(call.arguments),
        "raw_arguments": call.raw_arguments,
    }


def _tool_call(value: Mapping[str, Any]) -> ToolCall:
    return ToolCall(
        str(value["call_id"]),
        str(value["name"]),
        cast(Mapping[str, Any], value["arguments"]),
        str(value["raw_arguments"]),
    )


def _message_data(message: Message) -> dict[str, Any]:
    return {
        "role": message.role.value,
        "content": message.content,
        "name": message.name,
        "tool_call_id": message.tool_call_id,
        "tool_calls": [_tool_call_data(call) for call in message.tool_calls],
    }


def _message(value: Mapping[str, Any]) -> Message:
    return Message(
        MessageRole(str(value["role"])),
        str(value["content"]),
        cast(str | None, value.get("name")),
        cast(str | None, value.get("tool_call_id")),
        tuple(
            _tool_call(cast(Mapping[str, Any], call))
            for call in cast(list[object], value.get("tool_calls") or [])
        ),
    )


def _response_data(response: ModelResponse | None) -> dict[str, Any] | None:
    if response is None:
        return None
    return {
        "text": response.text,
        "tool_calls": [_tool_call_data(call) for call in response.tool_calls],
        "usage": {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "total_tokens": response.usage.total_tokens,
        },
        "response_id": response.response_id,
        "finish_reason": response.finish_reason,
        "output_json": dict(response.output_json) if response.output_json is not None else None,
    }


def _response(value: Mapping[str, Any] | None) -> ModelResponse | None:
    if value is None:
        return None
    usage = cast(Mapping[str, Any], value.get("usage") or {})
    return ModelResponse(
        text=str(value.get("text") or ""),
        tool_calls=tuple(
            _tool_call(cast(Mapping[str, Any], call))
            for call in cast(list[object], value.get("tool_calls") or [])
        ),
        usage=Usage(
            int(usage.get("input_tokens", 0)),
            int(usage.get("output_tokens", 0)),
            int(usage.get("total_tokens", 0)),
        ),
        response_id=cast(str | None, value.get("response_id")),
        finish_reason=cast(str | None, value.get("finish_reason")),
        output_json=cast(Mapping[str, Any] | None, value.get("output_json")),
    )


def _turn_data(turn: Turn) -> dict[str, Any]:
    return {
        "input": turn.input,
        "turn_id": turn.turn_id,
        "status": turn.status.value,
        "created_at": turn.created_at.isoformat(),
        "started_at": turn.started_at.isoformat() if turn.started_at else None,
        "completed_at": turn.completed_at.isoformat() if turn.completed_at else None,
        "response": _response_data(turn.response),
        "error": turn.error,
    }


def _turn(value: Mapping[str, Any]) -> Turn:
    return Turn(
        input=str(value["input"]),
        turn_id=str(value["turn_id"]),
        status=TurnStatus(str(value["status"])),
        created_at=datetime.fromisoformat(str(value["created_at"])),
        started_at=(
            datetime.fromisoformat(str(value["started_at"])) if value.get("started_at") else None
        ),
        completed_at=(
            datetime.fromisoformat(str(value["completed_at"]))
            if value.get("completed_at")
            else None
        ),
        response=_response(cast(Mapping[str, Any] | None, value.get("response"))),
        error=cast(str | None, value.get("error")),
    )


class SQLiteThreadStore:
    """Transactional snapshot store for provider-neutral Thread state."""

    SCHEMA_VERSION = 1

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._migrate()

    def _migrate(self) -> None:
        current = int(self._connection.execute("PRAGMA user_version").fetchone()[0])
        if current > self.SCHEMA_VERSION:
            raise RuntimeError(
                f"database schema {current} is newer than supported {self.SCHEMA_VERSION}"
            )
        with self._connection:
            self._connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA foreign_keys=ON;
                CREATE TABLE IF NOT EXISTS threads (
                    thread_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    instructions TEXT,
                    archived INTEGER NOT NULL DEFAULT 0,
                    parent_thread_id TEXT,
                    metadata_json TEXT NOT NULL,
                    summaries_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    thread_id TEXT NOT NULL REFERENCES threads(thread_id) ON DELETE CASCADE,
                    position INTEGER NOT NULL,
                    data_json TEXT NOT NULL,
                    PRIMARY KEY(thread_id, position)
                );
                CREATE TABLE IF NOT EXISTS turns (
                    thread_id TEXT NOT NULL REFERENCES threads(thread_id) ON DELETE CASCADE,
                    position INTEGER NOT NULL,
                    data_json TEXT NOT NULL,
                    PRIMARY KEY(thread_id, position)
                );
                """
            )
            if current < self.SCHEMA_VERSION:
                self._connection.execute(f"PRAGMA user_version={self.SCHEMA_VERSION}")

    def save(self, thread: object) -> None:
        from super_harness.runtime.thread import Thread

        if not isinstance(thread, Thread):
            raise TypeError("SQLiteThreadStore.save expects a Thread")
        summaries = [
            {
                "content": summary.content,
                "summarized_messages": summary.summarized_messages,
                "summary_id": summary.summary_id,
                "created_at": summary.created_at.isoformat(),
            }
            for summary in thread.summaries
        ]
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO threads VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(thread_id) DO UPDATE SET
                    updated_at=excluded.updated_at,
                    instructions=excluded.instructions,
                    archived=excluded.archived,
                    parent_thread_id=excluded.parent_thread_id,
                    metadata_json=excluded.metadata_json,
                    summaries_json=excluded.summaries_json
                """,
                (
                    thread.thread_id,
                    thread.created_at.isoformat(),
                    thread.updated_at.isoformat(),
                    thread.instructions,
                    int(thread.archived),
                    thread.parent_thread_id,
                    json.dumps(thread.metadata, ensure_ascii=False),
                    json.dumps(summaries, ensure_ascii=False),
                ),
            )
            self._connection.execute("DELETE FROM messages WHERE thread_id=?", (thread.thread_id,))
            self._connection.execute("DELETE FROM turns WHERE thread_id=?", (thread.thread_id,))
            self._connection.executemany(
                "INSERT INTO messages VALUES (?, ?, ?)",
                (
                    (
                        thread.thread_id,
                        index,
                        json.dumps(_message_data(message), ensure_ascii=False),
                    )
                    for index, message in enumerate(thread.messages)
                ),
            )
            self._connection.executemany(
                "INSERT INTO turns VALUES (?, ?, ?)",
                (
                    (thread.thread_id, index, json.dumps(_turn_data(turn), ensure_ascii=False))
                    for index, turn in enumerate(thread.turns)
                ),
            )

    def load(self, thread_id: str) -> ThreadSnapshot:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM threads WHERE thread_id=?", (thread_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown thread {thread_id!r}")
            message_rows = self._connection.execute(
                "SELECT data_json FROM messages WHERE thread_id=? ORDER BY position",
                (thread_id,),
            ).fetchall()
            turn_rows = self._connection.execute(
                "SELECT data_json FROM turns WHERE thread_id=? ORDER BY position",
                (thread_id,),
            ).fetchall()
        metadata = cast(dict[str, Any], json.loads(row["metadata_json"]))
        summary_values = cast(list[Mapping[str, Any]], json.loads(row["summaries_json"]))
        summaries = tuple(
            ContextSummary(
                str(value["content"]),
                int(value["summarized_messages"]),
                str(value["summary_id"]),
                datetime.fromisoformat(str(value["created_at"])),
            )
            for value in summary_values
        )
        return ThreadSnapshot(
            thread_id=str(row["thread_id"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
            instructions=cast(str | None, row["instructions"]),
            archived=bool(row["archived"]),
            parent_thread_id=cast(str | None, row["parent_thread_id"]),
            metadata=metadata,
            messages=tuple(
                _message(cast(Mapping[str, Any], json.loads(item["data_json"])))
                for item in message_rows
            ),
            turns=tuple(
                _turn(cast(Mapping[str, Any], json.loads(item["data_json"]))) for item in turn_rows
            ),
            summaries=summaries,
        )

    def archive(self, thread_id: str, *, archived: bool = True) -> None:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "UPDATE threads SET archived=? WHERE thread_id=?",
                (int(archived), thread_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"unknown thread {thread_id!r}")

    def ids(self, *, include_archived: bool = False) -> tuple[str, ...]:
        query = "SELECT thread_id FROM threads"
        if not include_archived:
            query += " WHERE archived=0"
        query += " ORDER BY created_at, thread_id"
        with self._lock:
            return tuple(str(row[0]) for row in self._connection.execute(query).fetchall())

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> SQLiteThreadStore:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
