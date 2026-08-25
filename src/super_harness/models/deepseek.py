"""DeepSeek provider defaults."""

from __future__ import annotations

import httpx

from .openai_compatible import OpenAICompatibleProvider, WireAPI
from .types import ModelCapabilities


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
