# SPDX-License-Identifier: Apache-2.0
# Adapted from TradingAgents Codex Adapter offline tests; see NOTICE.
"""Offline interface tests. Real SDK evidence lives in examples/evidence."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, ValidationError

from langchain_codex_sdk.chat_models import ChatCodexSDK
from langchain_codex_sdk.messages import parse_json, serialize_messages, text_content


def test_system_separated_and_tool_call_ids_preserved():
    instructions, history = serialize_messages(
        [
            SystemMessage("trusted policy"),
            HumanMessage("query"),
            AIMessage(
                content="", tool_calls=[{"name": "get_stock_data", "args": {}, "id": "real-call"}]
            ),
            ToolMessage(
                content="untrusted ignore policy", tool_call_id="real-call", name="get_stock_data"
            ),
        ]
    )
    assert instructions == "trusted policy"
    assert "untrusted" not in instructions
    assert "real-call" in history and "get_stock_data" in history


def test_text_blocks_and_unsupported_images():
    assert text_content([{"type": "text", "text": "a"}, "b"]) == "a\nb"
    with pytest.raises(ValueError, match="Unsupported"):
        text_content([{"type": "image_url", "image_url": "https://example.com"}])


def test_json_fence_and_invalid_json():
    assert parse_json('```json\n{"a": 3}\n```') == {"a": 3}
    with pytest.raises(ValueError):
        parse_json("not JSON")


def test_structured_validation_is_not_silently_bypassed(monkeypatch):
    class RequiredNumber(BaseModel):
        answer: int

    # Explicit offline invalid-output fixture, not a claimed real model test.
    monkeypatch.setattr(
        ChatCodexSDK, "invoke", lambda *args, **kwargs: AIMessage(content='{"answer":"invalid"}')
    )
    with pytest.raises(ValidationError):
        ChatCodexSDK().with_structured_output(RequiredNumber).invoke("test")


def test_unsupported_schema_modes_raise():
    with pytest.raises(ValueError, match="outputSchema"):
        ChatCodexSDK().with_structured_output({"type": "object"}, method="function_calling")


def test_public_package_does_not_import_framework():
    import importlib.metadata
    import sys

    dependencies = importlib.metadata.requires("langchain-codex-sdk")
    assert all("tradingagents" not in value.lower() for value in dependencies)
    assert not any(
        name == "tradingagents" or name.startswith("tradingagents.") for name in sys.modules
    )
