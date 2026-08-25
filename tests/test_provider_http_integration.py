from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, ClassVar, cast

import pytest

from super_harness import Agent, Tool, tool
from super_harness.models import (
    Message,
    MessageRole,
    ModelRequest,
    ModelStreamEventType,
    OpenAICompatibleProvider,
)


class ModelHandler(BaseHTTPRequestHandler):
    requests: ClassVar[list[dict[str, object]]] = []

    def do_POST(self) -> None:
        length = int(self.headers["Content-Length"])
        decoded: object = json.loads(self.rfile.read(length))
        assert isinstance(decoded, dict)
        body = cast(dict[str, Any], decoded)
        self.requests.append(body)
        if body.get("stream"):
            payload = (
                b'data: {"id":"local","choices":[{"delta":{"content":"local "}}]}\n\n'
                b'data: {"id":"local","choices":[{"delta":{"content":"stream"}}],'
                b'"usage":{"prompt_tokens":2,"completion_tokens":2,"total_tokens":4}}\n\n'
                b"data: [DONE]\n\n"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        payload = json.dumps(
            {
                "id": "local",
                "choices": [{"message": {"content": "local response"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 2, "total_tokens": 4},
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        return


class ToolLoopHandler(BaseHTTPRequestHandler):
    requests: ClassVar[list[dict[str, object]]] = []

    def do_POST(self) -> None:
        length = int(self.headers["Content-Length"])
        decoded: object = json.loads(self.rfile.read(length))
        assert isinstance(decoded, dict)
        body = cast(dict[str, Any], decoded)
        self.requests.append(body)
        messages = cast(list[dict[str, Any]], body["messages"])
        has_result = any(message.get("role") == "tool" for message in messages)
        if has_result:
            chunks = [
                {"id": "step_2", "choices": [{"delta": {"content": "42"}}]},
            ]
        else:
            chunks = [
                {
                    "id": "step_1",
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call_local",
                                        "function": {
                                            "name": "add",
                                            "arguments": '{"left":20,"right":22}',
                                        },
                                    }
                                ]
                            }
                        }
                    ],
                }
            ]
        payload = (
            "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        return


@pytest.fixture
def model_server() -> Iterator[str]:
    ModelHandler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), ModelHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    address = cast(tuple[str, int], server.server_address)
    host, port = address
    try:
        yield f"http://{host}:{port}/v1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.fixture
def tool_loop_server() -> Iterator[str]:
    ToolLoopHandler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), ToolLoopHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = cast(tuple[str, int], server.server_address)
    try:
        yield f"http://{host}:{port}/v1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_complete_and_stream_over_real_local_http(model_server: str) -> None:
    provider = OpenAICompatibleProvider(
        model="local", base_url=model_server, api_key="local-test-key"
    )
    request = ModelRequest([Message(MessageRole.USER, "hello")])
    try:
        response = await provider.complete(request)
        events = [event async for event in provider.stream(request)]
        thread = Agent(provider).thread()
        runtime_response = await thread.arun("through the runtime")
    finally:
        await provider.aclose()

    assert response.text == "local response"
    assert events[-1].type is ModelStreamEventType.COMPLETED
    assert events[-1].response is not None
    assert events[-1].response.text == "local stream"
    assert events[-1].response.usage.total_tokens == 4
    assert runtime_response.text == "local stream"
    assert thread.turns[0].response == runtime_response
    assert len(ModelHandler.requests) == 3


@pytest.mark.integration
@pytest.mark.asyncio
async def test_agent_tool_loop_over_real_local_http(tool_loop_server: str) -> None:
    @tool
    def add(left: int, right: int) -> int:
        """Add two integers."""

        return left + right

    assert isinstance(add, Tool)
    provider = OpenAICompatibleProvider(
        model="local", base_url=tool_loop_server, api_key="local-test-key"
    )
    thread = Agent(provider, tools=[add]).thread()
    try:
        events = [event async for event in thread.astream("calculate")]
    finally:
        await provider.aclose()

    assert thread.turns[0].response is not None
    assert thread.turns[0].response.text == "42"
    assert [event.type for event in events].count("tool.completed") == 1
    assert ToolLoopHandler.requests[0]["tools"]
    second_messages = cast(list[dict[str, Any]], ToolLoopHandler.requests[1]["messages"])
    assert [message["role"] for message in second_messages] == [
        "user",
        "assistant",
        "tool",
    ]
    assert second_messages[-1]["tool_call_id"] == "call_local"
