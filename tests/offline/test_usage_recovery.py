# SPDX-License-Identifier: Apache-2.0
# Adapted from TradingAgents Codex Adapter offline tests; see NOTICE.
"""Mock protocol faults and real offline process restart; never live model evidence."""

import sqlite3
import threading
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, messages_to_dict

from langchain_codex_sdk.chat_models import ChatCodexSDK
from langchain_codex_sdk.recovery import (
    DuplicateRecoverySubmission,
    RecoveryIntegrityError,
    RecoveryStore,
    validate_saved_history,
)
from langchain_codex_sdk.usage import (
    CodexResourceLimit,
    CodexResources,
    DuplicateCodexTask,
)


def test_actual_usage_does_not_add_cache_and_retains_sdk(tmp_path):
    guard = CodexResources(tmp_path / "ledger.json", max_tasks=2, reserve_per_task=100)
    guard.acquire(SimpleNamespace(id="a"))
    usage = {"inputTokens": 90, "outputTokens": 10, "cachedInputTokens": 80, "totalTokens": 100}
    raw = {"last": usage, "total": usage, "modelContextWindow": 475000}
    guard.observe("a", usage, raw_usage=raw)
    guard.observe("a", usage, raw_usage=raw)
    guard.release("a")
    actual = guard.snapshot()
    assert actual["reported_breakdown"] == {
        "input": 90,
        "output": 10,
        "cached_input_subset": 80,
        "total": 100,
    }
    assert actual["planning_charge_tokens"] == 100
    assert actual["sessions"]["a"]["raw_sdk_usage"] == [raw, raw]
    assert actual["sessions"]["a"]["usage_status"] == "MEASURED"


@pytest.mark.parametrize("reason", ["cancelled", "timeout", "transport_error"])
def test_unknown_is_estimated_not_zero_and_can_continue(tmp_path, reason):
    guard = CodexResources(
        tmp_path / "ledger.json", token_limit=250, max_tasks=2, reserve_per_task=100
    )
    guard.acquire(SimpleNamespace(id="lost"))
    guard.release("lost", terminal_observed=False, reason=reason)
    data = guard.snapshot()
    assert data["sessions"]["lost"]["usage"] is None
    assert data["sessions"]["lost"]["usage_status"] == "UNKNOWN"
    assert data["actual_total_upper_bound"] is None
    assert data["planning_charge_tokens"] == 100
    guard.acquire(SimpleNamespace(id="next"))
    assert guard.snapshot()["planning_charge_tokens"] == 200
    with pytest.raises(CodexResourceLimit, match="task count"):
        guard.acquire(SimpleNamespace(id="too-many"))


def test_partial_usage_crash_holds_reservation(tmp_path):
    path = tmp_path / "ledger.json"
    guard = CodexResources(path, token_limit=250, reserve_per_task=100)
    guard.acquire(SimpleNamespace(id="lost"))
    guard.observe(
        "lost", {"inputTokens": 40, "outputTokens": 10, "cachedInputTokens": 20, "totalTokens": 50}
    )
    restored = CodexResources(path, token_limit=250, reserve_per_task=100)
    assert restored.snapshot()["planning_charge_tokens"] == 100
    assert restored.snapshot()["actual_total_lower_bound"] == 50
    assert restored.snapshot()["sessions"]["lost"]["usage_status"] == "UNKNOWN"
    restored.acquire(SimpleNamespace(id="next"))


def test_estimate_requires_assumptions_and_cannot_shrink_measured_floor(tmp_path):
    guard = CodexResources(tmp_path / "ledger.json")
    guard.acquire(SimpleNamespace(id="lost"))
    guard.observe("lost", {"totalTokens": 30})
    guard.release("lost", terminal_observed=False)
    with pytest.raises(ValueError):
        guard.estimate_unknown(
            "lost", lower_tokens=20, upper_tokens=100, assumptions="missing tail"
        )
    with pytest.raises(ValueError):
        guard.estimate_unknown("lost", lower_tokens=30, upper_tokens=100, assumptions="")
    guard.estimate_unknown(
        "lost", lower_tokens=30, upper_tokens=100, assumptions="explicit conditional tail"
    )
    guard.ensure_can_infer()


def test_reserved_budget_and_task_duplicate_reject_before_sdk(tmp_path):
    guard = CodexResources(tmp_path / "ledger.json", token_limit=150, reserve_per_task=100)
    guard.acquire(SimpleNamespace(id="a", task_key="logical-request"))
    guard.release("a", terminal_observed=False)
    with pytest.raises(DuplicateCodexTask):
        guard.acquire(SimpleNamespace(id="b", task_key="logical-request"))
    with pytest.raises(CodexResourceLimit, match="reserve"):
        guard.acquire(SimpleNamespace(id="c", task_key="another"))


def test_over_reservation_warns_and_cancels(tmp_path):
    cancelled = threading.Event()
    session = SimpleNamespace(id="a", cancel=lambda reason: cancelled.set())
    guard = CodexResources(tmp_path / "ledger.json", token_limit=150, reserve_per_task=100)
    guard.acquire(session)
    guard.observe("a", {"totalTokens": 101})
    assert cancelled.wait(1)
    assert "reservation_exceeded:a" in guard.snapshot()["warnings"]


def sealed_store(tmp_path):
    store = RecoveryStore(tmp_path)
    with sqlite3.connect(tmp_path / "source.sqlite") as connection:
        connection.execute("create table fixture (value text)")
        connection.commit()
        messages = [
            HumanMessage("OFFLINE"),
            AIMessage(content="", tool_calls=[{"id": "a", "name": "get_stock_data", "args": {}}]),
            ToolMessage(content="OFFLINE_TOOL", name="get_stock_data", tool_call_id="a"),
        ]
        store.seal(
            connection,
            {"values": {"messages": messages_to_dict(messages)}, "next": ["wrap_up"]},
            {"mock": True},
        )
    return store, messages


@pytest.mark.parametrize(
    "target", ["graph_state_before.json", "checkpoint.sqlite", "checkpoint_manifest.json"]
)
def test_corrupt_checkpoint_never_restarts(tmp_path, target):
    store, _ = sealed_store(tmp_path)
    (tmp_path / target).write_bytes(b"CORRUPTED")
    with pytest.raises(RecoveryIntegrityError):
        store.verify()


def test_duplicate_tool_message_and_foreign_result_reject(tmp_path):
    _, messages = sealed_store(tmp_path)
    with pytest.raises(RecoveryIntegrityError, match="Duplicate saved ToolMessage"):
        validate_saved_history(messages + [messages[-1]])
    messages[-1] = ToolMessage(content="foreign", name="get_stock_data", tool_call_id="wrong")
    with pytest.raises(RecoveryIntegrityError, match="foreign"):
        validate_saved_history(messages)


def test_adapter_replay_duplicate_reply_rejects_before_model():
    model = ChatCodexSDK(allow_history_replay=True)
    ai = AIMessage(
        content="",
        tool_calls=[{"id": "a", "name": "get_stock_data", "args": {}}],
        additional_kwargs={"codex_native_session": "lost"},
    )
    tool = ToolMessage(content="OFFLINE", name="get_stock_data", tool_call_id="a")
    with pytest.raises(ValueError, match="Duplicate saved ToolMessage"):
        model._generate_tools([HumanMessage("OFFLINE"), ai, tool, tool], "", "", [])
    assert not model.evidence


def test_duplicate_submission_lock(tmp_path):
    store = RecoveryStore(tmp_path)
    with store.lock(), pytest.raises(DuplicateRecoverySubmission), RecoveryStore(tmp_path).lock():
        pass


def test_usage_ledger_single_process_owner(tmp_path):
    path = tmp_path / "ledger.json"
    owner = CodexResources(path, process_lock=True)
    with pytest.raises(CodexResourceLimit, match="Another process owns"):
        CodexResources(path, process_lock=True)
    owner.close()
    second = CodexResources(path, process_lock=True)
    second.close()


def test_saved_policy_cannot_be_silently_relaxed(tmp_path):
    guard = CodexResources(tmp_path / "ledger.json", token_limit=100, max_tasks=1)
    guard.acquire(SimpleNamespace(id="a"))
    with pytest.raises(CodexResourceLimit, match="policy differs"):
        CodexResources(tmp_path / "ledger.json", token_limit=200, max_tasks=2)


@pytest.mark.parametrize("fault", ["cancel", "timeout", "transport"])
def test_native_sdk_mock_fault_marks_unknown_and_preserves_budget(tmp_path, monkeypatch, fault):
    import queue

    from langchain_codex_sdk import tools as codex_tools

    class SDKMock:
        def __init__(self, *args, **kwargs):
            self.events = queue.Queue()
            self.ready = threading.Event()
            self.interrupts = 0

        def start(self):
            pass

        def initialize(self):
            pass

        def account_read(self, params):
            return SimpleNamespace(model_dump=lambda **kw: {"account": {"type": "chatgpt"}})

        def thread_start(self, params):
            return SimpleNamespace(thread=SimpleNamespace(id="OFFLINE_THREAD"), model="gpt-6.1-sol")

        def turn_start(self, *args):
            return SimpleNamespace(turn=SimpleNamespace(id="OFFLINE_TURN"))

        def next_turn_notification(self, turn_id):
            self.ready.set()
            if fault == "transport":
                raise OSError("OFFLINE_TRANSPORT_ERROR")
            data = self.events.get(timeout=2)
            return SimpleNamespace(
                method="turn/completed", payload=SimpleNamespace(model_dump=lambda **kw: data)
            )

        def turn_interrupt(self, *args):
            self.interrupts += 1
            self.events.put({"turn": {"status": "interrupted"}})

        def close(self):
            pass

    monkeypatch.setattr(codex_tools, "CodexClient", SDKMock)
    monkeypatch.setattr(codex_tools, "restricted_config", lambda *args: object())
    guard = CodexResources(tmp_path / "ledger.json", reserve_per_task=100)
    session = codex_tools.NativeToolSession(
        model="gpt-6.1-sol",
        instructions="OFFLINE",
        prompt="OFFLINE",
        cwd=str(tmp_path),
        codex_bin=None,
        timeout=0.05,
        tools=[],
        digest="offline",
        resource_guard=guard,
    )
    assert session.client.ready.wait(1)
    if fault == "cancel":
        session.cancel("OFFLINE_CANCEL")
        session.cancel("OFFLINE_DUPLICATE_CANCEL")
        assert session.client.interrupts == 1
    elif fault == "timeout":
        with pytest.raises(TimeoutError):
            session.next_result()
        assert session.client.interrupts == 1
    else:
        with pytest.raises(OSError, match="OFFLINE_TRANSPORT_ERROR"):
            session.next_result()
    assert session.done.wait(1)
    data = guard.snapshot()
    assert data["sessions"][session.id]["usage_status"] == "UNKNOWN"
    assert data["sessions"][session.id]["usage"] is None
    assert data["planning_charge_tokens"] == 100
    guard.ensure_can_infer()
