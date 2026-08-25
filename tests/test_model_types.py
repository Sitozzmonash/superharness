from dataclasses import FrozenInstanceError
from typing import Any

import pytest

from super_harness.models import Message, MessageRole, ModelRequest, ToolDefinition


def test_request_defensively_freezes_inputs() -> None:
    schema: dict[str, Any] = {"type": "object"}
    tool_schema: dict[str, Any] = {"type": "object", "properties": {}}
    request = ModelRequest(
        [Message(MessageRole.USER, "hello")],
        tools=[ToolDefinition("lookup", "Look something up", tool_schema)],
        output_schema=schema,
    )
    schema["type"] = "string"
    tool_schema["type"] = "array"

    assert request.output_schema == {"type": "object"}
    assert request.tools[0].parameters["type"] == "object"
    with pytest.raises(TypeError):
        request.tools[0].parameters["type"] = "array"  # type: ignore[index]


def test_messages_are_immutable() -> None:
    message = Message(MessageRole.USER, "hello")
    with pytest.raises(FrozenInstanceError):
        message.content = "changed"  # type: ignore[misc]


def test_tool_name_must_be_non_empty() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        ToolDefinition(" ", "invalid", {})
