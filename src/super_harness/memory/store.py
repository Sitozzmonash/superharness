"""Async long-term memory protocol and durable SQLite implementation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import sqlite3
import threading
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast

from super_harness.exceptions import SuperHarnessError

from .types import MemoryCandidate, MemoryKind, MemoryMatch, MemoryRecord


class MemoryError(SuperHarnessError):
    """Raised for durable memory failures."""


class MemoryStore(Protocol):
    async def remember(
        self, candidate: MemoryCandidate, *, source_thread_id: str | None = None
    ) -> MemoryRecord: ...

    async def get(self, memory_id: str) -> MemoryRecord | None: ...

    async def search(
        self,
        query: str,
        *,
        limit: int = 5,
        exclude_thread_id: str | None = None,
        kinds: Sequence[MemoryKind] = (),
    ) -> tuple[MemoryMatch, ...]: ...

    async def forget(self, memory_id: str) -> bool: ...

    async def close(self) -> None: ...


def _fingerprint(candidate: MemoryCandidate) -> str:
    normalized = " ".join(candidate.content.casefold().split())
    return hashlib.sha256(f"{candidate.kind.value}\0{normalized}".encode()).hexdigest()


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[\w]+", value.casefold()))


class SQLiteMemoryStore:
    schema_version = 1

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._initialize()

    def _initialize(self) -> None:
        with self._lock, self._connection:
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute(
                "CREATE TABLE IF NOT EXISTS memory_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            row = self._connection.execute(
                "SELECT value FROM memory_meta WHERE key='schema_version'"
            ).fetchone()
            if row is not None and int(row["value"]) > self.schema_version:
                raise MemoryError("memory database schema is newer than this runtime")
            self._connection.execute(
                "INSERT OR IGNORE INTO memory_meta(key, value) VALUES('schema_version', ?)",
                (str(self.schema_version),),
            )
            self._connection.execute(
                """CREATE TABLE IF NOT EXISTS memories (
                    memory_id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL UNIQUE,
                    content TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    source_thread_id TEXT,
                    tags_json TEXT NOT NULL,
                    importance REAL NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    usage_count INTEGER NOT NULL DEFAULT 0,
                    last_accessed_at TEXT
                )"""
            )

    async def remember(
        self, candidate: MemoryCandidate, *, source_thread_id: str | None = None
    ) -> MemoryRecord:
        return await asyncio.to_thread(self._remember, candidate, source_thread_id)

    def _remember(self, candidate: MemoryCandidate, source_thread_id: str | None) -> MemoryRecord:
        now = datetime.now(UTC)
        proposed = MemoryRecord(
            candidate.content,
            candidate.kind,
            source_thread_id,
            candidate.tags,
            candidate.importance,
            candidate.metadata,
            created_at=now,
            updated_at=now,
        )
        fingerprint = _fingerprint(candidate)
        with self._lock, self._connection:
            existing = self._connection.execute(
                "SELECT * FROM memories WHERE fingerprint=?", (fingerprint,)
            ).fetchone()
            if existing is not None:
                self._connection.execute(
                    """UPDATE memories SET updated_at=?, importance=MAX(importance, ?),
                    source_thread_id=COALESCE(source_thread_id, ?) WHERE fingerprint=?""",
                    (now.isoformat(), candidate.importance, source_thread_id, fingerprint),
                )
                refreshed = self._connection.execute(
                    "SELECT * FROM memories WHERE fingerprint=?", (fingerprint,)
                ).fetchone()
                assert refreshed is not None
                return self._record(refreshed)
            self._connection.execute(
                """INSERT INTO memories VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    proposed.memory_id,
                    fingerprint,
                    proposed.content,
                    proposed.kind.value,
                    proposed.source_thread_id,
                    json.dumps(proposed.tags, ensure_ascii=False),
                    proposed.importance,
                    json.dumps(dict(proposed.metadata), ensure_ascii=False),
                    proposed.created_at.isoformat(),
                    proposed.updated_at.isoformat(),
                    0,
                    None,
                ),
            )
        return proposed

    async def get(self, memory_id: str) -> MemoryRecord | None:
        return await asyncio.to_thread(self._get, memory_id)

    def _get(self, memory_id: str) -> MemoryRecord | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM memories WHERE memory_id=?", (memory_id,)
            ).fetchone()
        return self._record(row) if row is not None else None

    async def search(
        self,
        query: str,
        *,
        limit: int = 5,
        exclude_thread_id: str | None = None,
        kinds: Sequence[MemoryKind] = (),
    ) -> tuple[MemoryMatch, ...]:
        if not query.strip() or limit < 1:
            raise ValueError("query must be non-empty and limit must be positive")
        return await asyncio.to_thread(self._search, query, limit, exclude_thread_id, tuple(kinds))

    def _search(
        self,
        query: str,
        limit: int,
        exclude_thread_id: str | None,
        kinds: tuple[MemoryKind, ...],
    ) -> tuple[MemoryMatch, ...]:
        clauses: list[str] = []
        values: list[object] = []
        if exclude_thread_id is not None:
            clauses.append("(source_thread_id IS NULL OR source_thread_id != ?)")
            values.append(exclude_thread_id)
        if kinds:
            clauses.append(f"kind IN ({','.join('?' for _ in kinds)})")
            values.extend(kind.value for kind in kinds)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock:
            rows = self._connection.execute(f"SELECT * FROM memories{where}", values).fetchall()
        query_tokens = _tokens(query)
        matches: list[MemoryMatch] = []
        for row in rows:
            record = self._record(row)
            overlap = len(query_tokens & _tokens(record.content))
            phrase = 2 if query.casefold() in record.content.casefold() else 0
            score = float(overlap + phrase) + record.importance
            if overlap or phrase:
                matches.append(MemoryMatch(record, score))
        matches.sort(key=lambda item: (-item.score, -item.record.importance, item.record.memory_id))
        selected = tuple(matches[:limit])
        now = datetime.now(UTC).isoformat()
        with self._lock, self._connection:
            self._connection.executemany(
                "UPDATE memories SET usage_count=usage_count+1, "
                "last_accessed_at=? WHERE memory_id=?",
                ((now, item.record.memory_id) for item in selected),
            )
        return selected

    async def forget(self, memory_id: str) -> bool:
        return await asyncio.to_thread(self._forget, memory_id)

    def _forget(self, memory_id: str) -> bool:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "DELETE FROM memories WHERE memory_id=?", (memory_id,)
            )
            return cursor.rowcount > 0

    async def close(self) -> None:
        await asyncio.to_thread(self._close)

    def _close(self) -> None:
        with self._lock:
            self._connection.close()

    @staticmethod
    def _record(row: sqlite3.Row) -> MemoryRecord:
        tags = cast(list[str], json.loads(cast(str, row["tags_json"])))
        metadata = cast(dict[str, Any], json.loads(cast(str, row["metadata_json"])))
        last_accessed = cast(str | None, row["last_accessed_at"])
        return MemoryRecord(
            cast(str, row["content"]),
            MemoryKind(cast(str, row["kind"])),
            cast(str | None, row["source_thread_id"]),
            tuple(tags),
            float(row["importance"]),
            metadata,
            cast(str, row["memory_id"]),
            datetime.fromisoformat(cast(str, row["created_at"])),
            datetime.fromisoformat(cast(str, row["updated_at"])),
            int(row["usage_count"]),
            datetime.fromisoformat(last_accessed) if last_accessed else None,
        )
