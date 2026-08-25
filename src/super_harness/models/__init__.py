"""Public model-provider contracts."""

from .base import ModelProvider
from .deepseek import DeepSeekProvider
from .openai_compatible import OpenAICompatibleProvider, WireAPI
from .types import (
    Message,
    MessageRole,
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
    ModelStreamEventType,
    ToolCall,
    ToolDefinition,
    Usage,
)

__all__ = [
    "DeepSeekProvider",
    "Message",
    "MessageRole",
    "ModelCapabilities",
    "ModelProvider",
    "ModelRequest",
    "ModelResponse",
    "ModelStreamEvent",
    "ModelStreamEventType",
    "OpenAICompatibleProvider",
    "ToolCall",
    "ToolDefinition",
    "Usage",
    "WireAPI",
]
