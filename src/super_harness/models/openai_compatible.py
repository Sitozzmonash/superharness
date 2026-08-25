"""OpenAI-compatible Chat Completions and Responses HTTP provider."""

from __future__ import annotations

import asyncio
import json
import os
import random
from collections.abc import AsyncIterator, Mapping
from enum import StrEnum
from typing import Any, cast

import httpx

from super_harness.exceptions import ModelError

from .types import (
    Message,
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
    ModelStreamEventType,
    ToolCall,
    ToolDefinition,
    Usage,
)


class WireAPI(StrEnum):
    CHAT_COMPLETIONS = "chat_completions"
    RESPONSES = "responses"


class OpenAICompatibleProvider:
    """Provider-neutral adapter for OpenAI-compatible HTTP APIs."""

    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        api_key: str | None = None,
        api_key_env: str | None = None,
        wire_api: WireAPI = WireAPI.CHAT_COMPLETIONS,
        timeout: float = 60.0,
        max_retries: int = 2,
        stream_max_retries: int = 1,
        client: httpx.AsyncClient | None = None,
        name: str = "openai_compatible",
        capabilities: ModelCapabilities | None = None,
    ) -> None:
        if max_retries < 0 or stream_max_retries < 0:
            raise ValueError("retry counts must be non-negative")
        self._name = name
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.wire_api = wire_api
        self.timeout = timeout
        self.max_retries = max_retries
        self.stream_max_retries = stream_max_retries
        self._api_key = api_key
        self.api_key_env = api_key_env
        self._client = client
        self._owns_client = client is None
        self._capabilities = capabilities or ModelCapabilities(wire_apis=(wire_api.value,))

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ModelCapabilities:
        return self._capabilities

    def _credential(self) -> str:
        value = self._api_key
        if value is None and self.api_key_env:
            value = os.environ.get(self.api_key_env)
        if not value or not value.strip():
            source = self.api_key_env or "api_key"
            raise ModelError(
                f"missing credential for provider {self.name}: set {source}",
                details={"provider": self.name, "credential_source": source},
            )
        return value.strip()

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    def _endpoint(self) -> str:
        path = "/chat/completions"
        if self.wire_api is WireAPI.RESPONSES:
            path = "/responses"
        return f"{self.base_url}{path}"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._credential()}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _tool(tool: ToolDefinition) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": dict(tool.parameters),
            },
        }

    @staticmethod
    def _message(message: Message) -> dict[str, Any]:
        result: dict[str, Any] = {"role": message.role.value, "content": message.content}
        if message.name is not None:
            result["name"] = message.name
        if message.tool_call_id is not None:
            result["tool_call_id"] = message.tool_call_id
        if message.tool_calls:
            result["tool_calls"] = [
                {
                    "id": call.call_id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": call.raw_arguments,
                    },
                }
                for call in message.tool_calls
            ]
        return result

    @classmethod
    def _responses_inputs(cls, messages: list[Message]) -> list[dict[str, Any]]:
        inputs: list[dict[str, Any]] = []
        for message in messages:
            if message.role.value == "tool":
                inputs.append(
                    {
                        "type": "function_call_output",
                        "call_id": message.tool_call_id,
                        "output": message.content,
                    }
                )
                continue
            if message.content:
                inputs.append(cls._message(message))
            inputs.extend(
                {
                    "type": "function_call",
                    "call_id": call.call_id,
                    "name": call.name,
                    "arguments": call.raw_arguments,
                }
                for call in message.tool_calls
            )
        return inputs

    def _payload(self, request: ModelRequest, *, stream: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {"model": self.model, "stream": stream}
        neutral_messages = list(request.messages)
        messages = [self._message(message) for message in neutral_messages]
        if self.wire_api is WireAPI.CHAT_COMPLETIONS:
            payload["messages"] = messages
            if request.output_schema is not None:
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "super_harness_output",
                        "strict": True,
                        "schema": dict(request.output_schema),
                    },
                }
        else:
            payload["input"] = self._responses_inputs(neutral_messages)
            if request.output_schema is not None:
                payload["text"] = {
                    "format": {
                        "type": "json_schema",
                        "name": "super_harness_output",
                        "strict": True,
                        "schema": dict(request.output_schema),
                    }
                }
        if request.tools:
            payload["tools"] = [self._tool(tool) for tool in request.tools]
            payload["parallel_tool_calls"] = request.parallel_tool_calls
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        payload.update(request.extra)
        return payload

    @staticmethod
    def _usage(data: Mapping[str, Any]) -> Usage:
        usage = cast(Mapping[str, Any], data.get("usage") or {})
        input_tokens = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)))
        output_tokens = int(usage.get("completion_tokens", usage.get("output_tokens", 0)))
        total_tokens = int(usage.get("total_tokens", input_tokens + output_tokens))
        return Usage(input_tokens, output_tokens, total_tokens)

    @staticmethod
    def _parse_arguments(raw: str) -> Mapping[str, Any]:
        try:
            value = json.loads(raw or "{}")
        except json.JSONDecodeError as exc:
            raise ModelError("provider returned invalid tool-call JSON") from exc
        if not isinstance(value, dict):
            raise ModelError("provider returned non-object tool-call arguments")
        return cast(dict[str, Any], value)

    @classmethod
    def _chat_response(cls, data: Mapping[str, Any]) -> ModelResponse:
        choices = cast(list[Mapping[str, Any]], data.get("choices") or [])
        if not choices:
            raise ModelError("provider response contained no choices")
        choice = choices[0]
        message = cast(Mapping[str, Any], choice.get("message") or {})
        calls: list[ToolCall] = []
        for call in cast(list[Mapping[str, Any]], message.get("tool_calls") or []):
            function = cast(Mapping[str, Any], call.get("function") or {})
            raw = str(function.get("arguments") or "{}")
            calls.append(
                ToolCall(
                    str(call.get("id") or ""),
                    str(function.get("name") or ""),
                    cls._parse_arguments(raw),
                    raw,
                )
            )
        response_id = str(data.get("id")) if data.get("id") else None
        finish_reason = choice.get("finish_reason")
        return ModelResponse(
            text=str(message.get("content") or ""),
            tool_calls=tuple(calls),
            usage=cls._usage(data),
            response_id=response_id,
            finish_reason=str(finish_reason) if finish_reason else None,
        )

    @classmethod
    def _responses_response(cls, data: Mapping[str, Any]) -> ModelResponse:
        text_parts: list[str] = []
        calls: list[ToolCall] = []
        for item in cast(list[Mapping[str, Any]], data.get("output") or []):
            if item.get("type") == "message":
                for content in cast(list[Mapping[str, Any]], item.get("content") or []):
                    if content.get("type") in {"output_text", "text"}:
                        text_parts.append(str(content.get("text") or ""))
            elif item.get("type") == "function_call":
                raw = str(item.get("arguments") or "{}")
                calls.append(
                    ToolCall(
                        str(item.get("call_id") or item.get("id") or ""),
                        str(item.get("name") or ""),
                        cls._parse_arguments(raw),
                        raw,
                    )
                )
        response_id = str(data.get("id")) if data.get("id") else None
        status = str(data.get("status")) if data.get("status") else None
        return ModelResponse(
            "".join(text_parts), tuple(calls), cls._usage(data), response_id, status
        )

    def _normalize(self, data: Mapping[str, Any]) -> ModelResponse:
        if self.wire_api is WireAPI.CHAT_COMPLETIONS:
            return self._chat_response(data)
        return self._responses_response(data)

    @classmethod
    def _structured(cls, response: ModelResponse, request: ModelRequest) -> ModelResponse:
        if request.output_schema is None:
            return response
        output = cls._parse_arguments(response.text)
        return ModelResponse(
            text=response.text,
            tool_calls=response.tool_calls,
            usage=response.usage,
            response_id=response.response_id,
            finish_reason=response.finish_reason,
            output_json=output,
        )

    @staticmethod
    def _retryable(exc: Exception) -> bool:
        if isinstance(exc, (httpx.TransportError, httpx.TimeoutException)):
            return True
        return isinstance(exc, httpx.HTTPStatusError) and (
            exc.response.status_code == 429 or exc.response.status_code >= 500
        )

    async def _backoff(self, attempt: int) -> None:
        await asyncio.sleep(min(0.25 * (2**attempt) + random.random() * 0.05, 2.0))

    def _error(self, exc: Exception) -> ModelError:
        status = None
        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
        suffix = f" with HTTP {status}" if status else ""
        return ModelError(
            f"{self.name} model request failed{suffix}",
            details={"provider": self.name, "status_code": status},
        )

    async def complete(self, request: ModelRequest) -> ModelResponse:
        for attempt in range(self.max_retries + 1):
            try:
                response = await self._http().post(
                    self._endpoint(),
                    headers=self._headers(),
                    json=self._payload(request, stream=False),
                )
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict):
                    raise ModelError("provider returned a non-object response")
                return self._structured(self._normalize(cast(dict[str, Any], data)), request)
            except ModelError:
                raise
            except (httpx.HTTPError, ValueError) as exc:
                if attempt >= self.max_retries or not self._retryable(exc):
                    raise self._error(exc) from exc
                await self._backoff(attempt)
        raise AssertionError("unreachable")

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        yield ModelStreamEvent(ModelStreamEventType.STARTED)
        for attempt in range(self.stream_max_retries + 1):
            try:
                async for event in self._stream_once(request):
                    yield event
                return
            except ModelError:
                raise
            except (httpx.HTTPError, json.JSONDecodeError) as exc:
                if attempt >= self.stream_max_retries or not self._retryable(exc):
                    raise self._error(exc) from exc
                await self._backoff(attempt)

    async def _stream_once(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        text: list[str] = []
        calls: dict[int, dict[str, str]] = {}
        usage = Usage()
        response_id: str | None = None
        completed = False
        async with self._http().stream(
            "POST",
            self._endpoint(),
            headers=self._headers(),
            json=self._payload(request, stream=True),
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if raw == "[DONE]":
                    completed = True
                    break
                if not raw:
                    continue
                decoded: object = json.loads(raw)
                if not isinstance(decoded, dict):
                    continue
                data = cast(dict[str, Any], decoded)
                response_id = str(data.get("id") or response_id or "") or None
                if data.get("usage"):
                    usage = self._usage(data)
                if self.wire_api is WireAPI.CHAT_COMPLETIONS:
                    async for event in self._chat_stream_data(data, text, calls):
                        yield event
                else:
                    event_type = data.get("type")
                    if event_type == "response.output_text.delta":
                        content = str(data.get("delta") or "")
                        text.append(content)
                        yield ModelStreamEvent(ModelStreamEventType.TEXT_DELTA, delta=content)
                    elif event_type == "response.function_call_arguments.delta":
                        yield self._responses_tool_delta(data, calls)
                    elif event_type == "response.output_item.added":
                        item = cast(Mapping[str, Any], data.get("item") or {})
                        if item.get("type") == "function_call":
                            index = int(data.get("output_index", 0))
                            calls[index] = {
                                "id": str(item.get("call_id") or item.get("id") or ""),
                                "name": str(item.get("name") or ""),
                                "arguments": str(item.get("arguments") or ""),
                            }
                    elif event_type == "response.completed":
                        completed = True
                        response_data = cast(Mapping[str, Any], data.get("response") or {})
                        response_id = str(response_data.get("id") or response_id or "") or None
                        usage = self._usage(response_data)
                        break
        if not completed:
            raise httpx.RemoteProtocolError("stream closed before terminal completion event")
        tool_calls = tuple(
            ToolCall(
                value["id"],
                value["name"],
                self._parse_arguments(value["arguments"]),
                value["arguments"],
            )
            for _, value in sorted(calls.items())
        )
        result = self._structured(
            ModelResponse("".join(text), tool_calls, usage, response_id, "completed"),
            request,
        )
        yield ModelStreamEvent(ModelStreamEventType.COMPLETED, response=result)

    async def _chat_stream_data(
        self,
        data: Mapping[str, Any],
        text: list[str],
        calls: dict[int, dict[str, str]],
    ) -> AsyncIterator[ModelStreamEvent]:
        choices = cast(list[Mapping[str, Any]], data.get("choices") or [])
        if not choices:
            return
        delta = cast(Mapping[str, Any], choices[0].get("delta") or {})
        content = str(delta.get("content") or "")
        if content:
            text.append(content)
            yield ModelStreamEvent(ModelStreamEventType.TEXT_DELTA, delta=content)
        for call in cast(list[Mapping[str, Any]], delta.get("tool_calls") or []):
            index = int(call.get("index", 0))
            state = calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
            function = cast(Mapping[str, Any], call.get("function") or {})
            state["id"] += str(call.get("id") or "")
            state["name"] += str(function.get("name") or "")
            arg_delta = str(function.get("arguments") or "")
            state["arguments"] += arg_delta
            yield ModelStreamEvent(
                ModelStreamEventType.TOOL_CALL_DELTA,
                delta=arg_delta,
                tool_call_index=index,
                tool_call_id=state["id"] or None,
                tool_name=state["name"] or None,
            )

    @staticmethod
    def _responses_tool_delta(
        data: Mapping[str, Any], calls: dict[int, dict[str, str]]
    ) -> ModelStreamEvent:
        index = int(data.get("output_index", 0))
        state = calls.setdefault(
            index,
            {
                "id": str(data.get("call_id") or ""),
                "name": str(data.get("name") or ""),
                "arguments": "",
            },
        )
        arg_delta = str(data.get("delta") or "")
        state["arguments"] += arg_delta
        return ModelStreamEvent(
            ModelStreamEventType.TOOL_CALL_DELTA,
            delta=arg_delta,
            tool_call_index=index,
            tool_call_id=state["id"] or None,
            tool_name=state["name"] or None,
        )

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
        self._client = None
