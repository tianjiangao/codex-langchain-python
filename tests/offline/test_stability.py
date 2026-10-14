# SPDX-License-Identifier: Apache-2.0
# Adapted from Codex Adapter tests; see NOTICE.
"""M4 offline protocol/lifecycle tests; these are not real-model evidence."""

import json
import queue
import threading

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from langchain_codex_sdk.chat_models import ChatCodexSDK
from langchain_codex_sdk.tools import NativeToolSession, message_digest, normalize_tools
from tests.fixtures import TOOLS


def test_continuous_callbacks_and_error_result(tmp_path):
    session = object.__new__(NativeToolSession)
    session.id = "offline-session"
    session.tools = normalize_tools(TOOLS, tuple(t.name for t in TOOLS))
    session.closed = threading.Event()
    session.outputs, session.results = queue.Queue(), queue.Queue()
    session.events, session.pending = [], None
    session.event_log_path = str(tmp_path / "events.jsonl")
    session.journal_lock = threading.Lock()
    session.timeout = 1
    messages = [HumanMessage("offline request")]
    session.history_digest = message_digest(messages)
    requests = [
        ("fetch_data", {"start_date": "2026-10-01", "end_date": "2026-10-09"}),
        ("compute_statistic", {"indicator": "rsi", "curr_date": "2026-10-09"}),
        ("verify_result", {"curr_date": "2026-10-09"}),
    ]
    replies = []

    def producer():
        for index, (name, args) in enumerate(requests):
            replies.append(
                session._request(
                    "item/tool/call", {"tool": name, "arguments": args, "callId": str(index)}
                )
            )

    worker = threading.Thread(target=producer)
    worker.start()
    for index in range(3):
        kind, call = session.outputs.get(timeout=1)
        assert kind == "tool" and call["id"] == str(index)
        messages.append(AIMessage(content="", tool_calls=[call]))
        messages.append(
            ToolMessage(
                content="OFFLINE FIXTURE",
                tool_call_id=call["id"],
                name=call["name"],
                status="error" if index == 1 else "success",
            )
        )
        session.reply(messages)
    worker.join(timeout=1)
    assert not worker.is_alive()
    assert [r["success"] for r in replies] == [True, False, True]
    persisted = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert len(persisted) == 6
    assert persisted[3]["params"]["status"] == "error"


def test_timeout_triggers_cancel():
    session = object.__new__(NativeToolSession)
    session.outputs, session.timeout = queue.Queue(), 0.001
    reasons = []
    session.cancel = reasons.append
    with pytest.raises(TimeoutError):
        session.next_result()
    assert reasons == ["timeout"]


def test_missing_session_still_fails_by_default():
    model = ChatCodexSDK()
    messages = [
        HumanMessage("query"),
        AIMessage(
            content="",
            tool_calls=[{"name": "fetch_data", "args": {}, "id": "old"}],
            additional_kwargs={"codex_native_session": "old-session"},
        ),
        ToolMessage(content="offline result", name="fetch_data", tool_call_id="old"),
    ]
    with pytest.raises(RuntimeError, match="cold checkpoint"):
        model._generate(messages, codex_tools=normalize_tools([TOOLS[0]], ("fetch_data",)))


def test_replay_rejects_missing_saved_tool_result():
    model = ChatCodexSDK(allow_history_replay=True)
    messages = [
        HumanMessage("query"),
        AIMessage(
            content="",
            tool_calls=[{"name": "fetch_data", "args": {}, "id": "old"}],
            additional_kwargs={"codex_native_session": "old-session"},
        ),
    ]
    with pytest.raises(ValueError, match="saved real tool results"):
        model._generate(messages, codex_tools=normalize_tools([TOOLS[0]], ("fetch_data",)))
