"""DeepSeek provider defaults."""

from __future__ import annotations

from typing import Any

import httpx

from .openai_compatible import OpenAICompatibleProvider, WireAPI
from .types import Message, ModelCapabilities, ModelRequest


class DeepSeekProvider(OpenAICompatibleProvider):
    """DeepSeek's OpenAI-compatible text model service."""

    def __init__(
        self,
        *,
        model: str = "deepseek-v4-flash",
        api_key: str | None = None,
        base_url: str = "https://api.deepseek.com",
        wire_api: WireAPI = WireAPI.CHAT_COMPLETIONS,
        timeout: float = 60.0,
        max_retries: int = 2,
        stream_max_retries: int = 1,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(
            model=model,
            api_key=api_key,
            api_key_env="DEEPSEEK_API_KEY",
            base_url=base_url,
            wire_api=wire_api,
            timeout=timeout,
            max_retries=max_retries,
            stream_max_retries=stream_max_retries,
            client=client,
            name="deepseek",
            capabilities=ModelCapabilities(
                streaming=True,
                tools=True,
                structured_output=True,
                reasoning=True,
                parallel_tool_calls=True,
                wire_apis=(WireAPI.CHAT_COMPLETIONS.value, WireAPI.RESPONSES.value),
            ),
        )

    @staticmethod
    def _message(message: Message) -> dict[str, Any]:
        """Serialize a neutral message, mapping ``developer`` to ``system``.

        DeepSeek's native API rejects the OpenAI ``developer`` role and requires
        ``system``; OpenAI-compatible reuse otherwise stays byte-identical.
        """
        result = OpenAICompatibleProvider._message(message)
        if result.get("role") == "developer":
            result["role"] = "system"
        return result

    def _payload(self, request: ModelRequest, *, stream: bool) -> dict[str, Any]:
        payload = super()._payload(request, stream=stream)
        if request.output_schema is not None and self.wire_api is WireAPI.CHAT_COMPLETIONS:
            # DeepSeek's native API rejects `response_format: json_schema`
            # ("This response_format type is unavailable now"); it only accepts
            # `json_object`. Schema conformance is validated locally by
            # _structured after parsing, so relaxation stays safe.
            payload["response_format"] = {"type": "json_object"}
        return payload
