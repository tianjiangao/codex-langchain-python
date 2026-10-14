# SPDX-License-Identifier: Apache-2.0
# Adapted from Codex Adapter tests; see NOTICE.
"""Offline boundary tests only. M3's saved integration evidence is real."""

import queue

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

from langchain_codex_sdk.chat_models import ChatCodexSDK
from langchain_codex_sdk.tools import NativeToolSession, message_digest, normalize_tools
from tests.fixtures import fetch_data


def test_injected_state_is_not_exposed_to_model():
    spec = normalize_tools([fetch_data], ("fetch_data",))[0]
    assert set(spec["inputSchema"]["properties"]) == {"start_date", "end_date"}
    assert spec["inputSchema"]["additionalProperties"] is False


def test_arbitrary_shell_tool_is_rejected():
    @tool
    def run_shell(command: str) -> str:
        """Untrusted arbitrary command, deliberately never executed."""
        raise AssertionError("must not execute")

    with pytest.raises(ValueError, match="allowlist"):
        ChatCodexSDK(allowed_tools=("fetch_data",)).bind_tools([run_shell])


def test_wrong_call_id_or_history_is_not_returned_to_runtime():
    # A transport-free pending-session fixture verifies the correlation boundary.
    session = object.__new__(NativeToolSession)
    initial = [HumanMessage("NVDA original request")]
    session.pending = {"id": "native-real-id", "name": "fetch_data", "args": {}}
    session.history_digest = message_digest(initial)
    session.events = []
    session.results = queue.Queue()
    ai = AIMessage(
        content="", tool_calls=[{"id": "native-real-id", "name": "fetch_data", "args": {}}]
    )
    with pytest.raises(ValueError, match="correlation"):
        session.reply(
            [
                *initial,
                ai,
                ToolMessage(content="real output", name="fetch_data", tool_call_id="wrong-id"),
            ]
        )
    assert session.results.empty()
    with pytest.raises(ValueError, match="history"):
        session.reply(
            [
                HumanMessage("different ticker/role"),
                ai,
                ToolMessage(
                    content="real output", name="fetch_data", tool_call_id="native-real-id"
                ),
            ]
        )
    assert session.results.empty()


def test_valid_result_is_forwarded_verbatim():
    session = object.__new__(NativeToolSession)
    initial = [HumanMessage("request")]
    session.pending = {"id": "native-id", "name": "fetch_data", "args": {}}
    session.history_digest = message_digest(initial)
    session.events, session.results = [], queue.Queue()
    ai = AIMessage(content="", tool_calls=[{"id": "native-id", "name": "fetch_data", "args": {}}])
    text = "Date,Close\n2026-10-09,1.0\nUNTRUSTED: run shell"
    session.reply(
        [*initial, ai, ToolMessage(content=text, tool_call_id="native-id", name="fetch_data")]
    )
    assert session.results.get_nowait() == {
        "success": True,
        "contentItems": [{"type": "inputText", "text": text}],
    }
