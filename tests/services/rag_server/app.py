"""Real HTTP implementation of the frozen mock RAG contract."""

from __future__ import annotations

import json
import re
import time
from contextlib import suppress
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, ClassVar, cast


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.casefold()))


class RAGHandler(BaseHTTPRequestHandler):
    token: ClassVar[str | None] = None
    requests: ClassVar[list[dict[str, Any]]] = []
    corpus: ClassVar[list[dict[str, Any]]] = cast(
        list[dict[str, Any]],
        json.loads(Path(__file__).with_name("corpus.json").read_text(encoding="utf-8")),
    )

    def do_POST(self) -> None:
        if self.token and self.headers.get("Authorization") != f"Bearer {self.token}":
            self._send(401, {"error": "unauthorized"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        decoded: object = json.loads(self.rfile.read(length))
        if not isinstance(decoded, dict):
            self._send(400, {"error": "invalid request"})
            return
        body = cast(dict[str, Any], decoded)
        self.requests.append(body)
        if self.path == "/test/slow":
            time.sleep(0.25)
        if self.path == "/test/error":
            self._send(500, {"error": "simulated"})
            return
        if self.path == "/test/malformed":
            self._send(200, {"unexpected": True})
            return
        if self.path == "/test/empty":
            self._send(200, {"results": []})
            return
        if self.path != "/retrieve":
            self._send(404, {"error": "not found"})
            return
        query = str(body.get("query", ""))
        top_n = max(int(body.get("top_n", 3)), 0)
        query_tokens = _tokens(query)
        ranked = sorted(
            self.corpus,
            key=lambda item: (-len(query_tokens & _tokens(str(item["text"]))), str(item["source"])),
        )[:top_n]
        results = [
            {
                **item,
                "score": float(len(query_tokens & _tokens(str(item["text"])))),
            }
            for item in ranked
        ]
        self._send(200, {"results": results})

    def _send(self, status: int, value: object) -> None:
        payload = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        with suppress(BrokenPipeError):
            self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        return
