from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from super_harness.exceptions import ModelError
from super_harness.models import (
    DeepSeekProvider,
    Message,
    MessageRole,
    ModelRequest,
    ModelStreamEvent,
    ModelStreamEventType,
    OpenAICompatibleProvider,
    ToolDefinition,
    WireAPI,
)


def request() -> ModelRequest:
    return ModelRequest(
        [Message(MessageRole.USER, "weather")],
        tools=[
            ToolDefinition(
                "weather",
                "Get weather",
                {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                    "additionalProperties": False,
                },
            )
        ],
        output_schema={
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
            "additionalProperties": False,
        },
    )


def plain_request(*, tools: bool = False) -> ModelRequest:
    definitions = request().tools if tools else ()
    return ModelRequest([Message(MessageRole.USER, "weather")], tools=definitions)


def test_deepseek_defaults_and_capabilities() -> None:
    provider = DeepSeekProvider(api_key="test")
    assert provider.name == "deepseek"
    assert provider.model == "deepseek-v4-flash"
    assert provider.base_url == "https://api.deepseek.com"
    assert provider.capabilities.streaming
    assert provider.capabilities.tools
    assert provider.capabilities.structured_output
    assert set(provider.capabilities.wire_apis) == {"chat_completions", "responses"}


@pytest.mark.asyncio
async def test_missing_credential_fails_before_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MISSING_TEST_KEY", raising=False)
    called = False

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(
        model="test",
        base_url="https://example.invalid/v1",
        api_key_env="MISSING_TEST_KEY",
        client=client,
    )
    with pytest.raises(ModelError, match="missing credential"):
        await provider.complete(request())
    assert not called
    await client.aclose()


@pytest.mark.asyncio
async def test_chat_payload_and_tool_call_normalization() -> None:
    captured: dict[str, Any] = {}

    async def handler(incoming: httpx.Request) -> httpx.Response:
        captured.update(json.loads(incoming.content))
        return httpx.Response(
            200,
            json={
                "id": "r1",
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "weather",
                                        "arguments": '{"city":"Chengdu"}',
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {
                    "prompt_tokens": 5,
                    "completion_tokens": 3,
                    "total_tokens": 8,
                },
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(
        model="test", base_url="https://example.invalid/v1", api_key="test", client=client
    )
    response = await provider.complete(request())

    assert captured["response_format"]["json_schema"]["strict"] is True
    assert captured["tools"][0]["function"]["name"] == "weather"
    assert response.tool_calls[0].arguments == {"city": "Chengdu"}
    assert response.usage.total_tokens == 8
    await client.aclose()


@pytest.mark.asyncio
async def test_responses_payload_and_response_normalization() -> None:
    captured: dict[str, Any] = {}

    async def handler(incoming: httpx.Request) -> httpx.Response:
        captured.update(json.loads(incoming.content))
        return httpx.Response(
            200,
            json={
                "id": "resp_1",
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": '{"answer":"sunny"}'}],
                    }
                ],
                "usage": {"input_tokens": 4, "output_tokens": 2, "total_tokens": 6},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(
        model="test",
        base_url="https://example.invalid/v1",
        api_key="test",
        wire_api=WireAPI.RESPONSES,
        client=client,
    )
    response = await provider.complete(request())

    assert captured["text"]["format"]["schema"]["type"] == "object"
    assert response.text == '{"answer":"sunny"}'
    assert response.output_json == {"answer": "sunny"}
    assert response.usage.input_tokens == 4
    await client.aclose()


@pytest.mark.asyncio
async def test_responses_stream_normalizes_text_tool_and_json() -> None:
    chunks = [
        {
            "type": "response.output_item.added",
            "output_index": 0,
            "item": {
                "type": "function_call",
                "call_id": "call_2",
                "name": "weather",
                "arguments": "",
            },
        },
        {
            "type": "response.function_call_arguments.delta",
            "output_index": 0,
            "delta": '{"city":"Chengdu"}',
        },
        {"type": "response.output_text.delta", "delta": '{"answer":"sunny"}'},
        {
            "type": "response.completed",
            "response": {
                "id": "resp_stream",
                "usage": {"input_tokens": 2, "output_tokens": 3, "total_tokens": 5},
            },
        },
    ]
    body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(
        model="test",
        base_url="https://example.invalid/v1",
        api_key="test",
        wire_api=WireAPI.RESPONSES,
        client=client,
    )
    events = [event async for event in provider.stream(request())]
    result = events[-1].response

    assert result is not None
    assert result.output_json == {"answer": "sunny"}
    assert result.tool_calls[0].call_id == "call_2"
    assert result.tool_calls[0].arguments == {"city": "Chengdu"}
    assert result.usage.total_tokens == 5
    await client.aclose()


@pytest.mark.asyncio
async def test_retry_is_bounded_and_only_for_retryable_status() -> None:
    attempts = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(500, json={"error": "temporary"})
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(
        model="test",
        base_url="https://example.invalid/v1",
        api_key="test",
        max_retries=2,
        client=client,
    )
    assert (await provider.complete(plain_request())).text == "ok"
    assert attempts == 3
    await client.aclose()


@pytest.mark.asyncio
async def test_chat_stream_requires_done_and_normalizes_tool_deltas() -> None:
    chunks = [
        {
            "id": "r1",
            "choices": [{"delta": {"content": "Hi "}}],
        },
        {
            "id": "r1",
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {"name": "weather", "arguments": '{"city":'},
                            }
                        ]
                    }
                }
            ],
        },
        {
            "id": "r1",
            "choices": [
                {"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '"Chengdu"}'}}]}}
            ],
        },
    ]
    body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(
        model="test", base_url="https://example.invalid/v1", api_key="test", client=client
    )
    events: list[ModelStreamEvent] = [
        event async for event in provider.stream(plain_request(tools=True))
    ]

    assert [event.type for event in events] == [
        ModelStreamEventType.STARTED,
        ModelStreamEventType.TEXT_DELTA,
        ModelStreamEventType.TOOL_CALL_DELTA,
        ModelStreamEventType.TOOL_CALL_DELTA,
        ModelStreamEventType.COMPLETED,
    ]
    result = events[-1].response
    assert result is not None
    assert result.text == "Hi "
    assert result.tool_calls[0].arguments == {"city": "Chengdu"}
    await client.aclose()


@pytest.mark.asyncio
async def test_incomplete_stream_is_an_error() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text='data: {"choices":[{"delta":{"content":"partial"}}]}\n\n',
            headers={"content-type": "text/event-stream"},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(
        model="test",
        base_url="https://example.invalid/v1",
        api_key="test",
        stream_max_retries=0,
        client=client,
    )
    with pytest.raises(ModelError):
        _: list[ModelStreamEvent] = [event async for event in provider.stream(plain_request())]
    await client.aclose()
