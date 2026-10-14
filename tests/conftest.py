"""CI has no login and never starts the real SDK. Live tests require explicit opt-in."""

import os

import pytest


def pytest_collection_modifyitems(items):
    for item in items:
        if "live" in item.keywords and os.environ.get("CODEX_RUN_LIVE_TESTS") != "1":
            item.add_marker(
                pytest.mark.skip(reason="Live integration requires CODEX_RUN_LIVE_TESTS=1")
            )


@pytest.fixture(autouse=True)
def offline_transport_guard(request, monkeypatch):
    if "live" in request.keywords:
        return

    def refuse(*args, **kwargs):
        raise AssertionError("Offline CI must not start Codex or access authentication")

    # Test-specific SDK mocks may replace these explicitly. No accidental real request survives.
    monkeypatch.setattr("langchain_codex_sdk.tools.CodexClient", refuse)
    monkeypatch.setattr("langchain_codex_sdk.runtime.CodexClient", refuse)
