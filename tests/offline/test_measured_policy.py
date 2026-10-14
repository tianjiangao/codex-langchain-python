import threading
from types import SimpleNamespace

import pytest

from langchain_codex_sdk import CodexResourceLimit, UsageLedger


def test_soft_warning_and_measured_hard_pause_do_not_charge_unknown(tmp_path):
    policy = {"token_limit": 200, "measured_only": True, "soft_warning_tokens": 100}
    guard = UsageLedger(tmp_path / "usage.json", **policy)
    guard.acquire(SimpleNamespace(id="unknown"))
    guard.release("unknown", terminal_observed=False)
    cancelled = threading.Event()
    guard.acquire(SimpleNamespace(id="active", cancel=lambda r: cancelled.set()))
    guard.observe(
        "active",
        {"totalTokens": 100, "inputTokens": 90, "outputTokens": 10, "cachedInputTokens": 80},
    )
    assert "measured_soft_warning" in guard.warnings and not cancelled.wait(0.01)
    guard.ensure_can_infer()
    guard.observe("active", {"totalTokens": 200})
    assert cancelled.wait(1)
    with pytest.raises(CodexResourceLimit):
        guard.ensure_can_infer()
    assert guard.snapshot()["actual_total_upper_bound"] is None
