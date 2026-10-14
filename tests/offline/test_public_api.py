import asyncio
import threading

import pytest
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from langchain_codex_sdk import ChatCodexSDK, UsageLedger
from tests.sdk_mock import ScriptedSDK


@pytest.fixture
def sdk(monkeypatch):
    class SDK(ScriptedSDK):
        clients = []

    monkeypatch.setattr("langchain_codex_sdk.tools.CodexClient", SDK)
    monkeypatch.setattr("langchain_codex_sdk.tools.restricted_config", lambda *a: object())
    return SDK


@tool
def add_numbers(a: int, b: int) -> str:
    """Add two integers without external services or side effects."""
    return str(a + b)


def tool_graph(llm):
    graph = StateGraph(MessagesState)
    bound = llm.bind_tools([add_numbers])
    graph.add_node("agent", lambda s: {"messages": [bound.invoke(s["messages"])]})
    graph.add_node("tools", ToolNode([add_numbers]))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", tools_condition, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")
    return graph.compile()


def test_invoke_standalone_usage_and_isolation(sdk, tmp_path):
    ledger = UsageLedger(tmp_path / "usage.json")
    with ChatCodexSDK(resource_guard=ledger) as llm:
        results = [llm.invoke([SystemMessage("test"), HumanMessage("OFFLINE")]) for _ in range(2)]
        assert all(r.content == "OFFLINE_OK" for r in results)
        assert (
            results[0].response_metadata["thread_id"] != results[1].response_metadata["thread_id"]
        )
        assert results[0].usage_metadata["input_token_details"]["cache_read"] == 30
        assert results[0].response_metadata["codex_usage"]["totalTokens"] == 100
        assert ledger.snapshot()["observed_total_tokens"] == 200
    ledger.close()


def test_real_toolnode_with_mock_sdk_roundtrip(sdk):
    with ChatCodexSDK() as llm:
        state = tool_graph(llm).invoke({"messages": [HumanMessage("OFFLINE_TOOL_REQUEST")]})
        assert state["messages"][-1].content == "12"
        assert state["messages"][2].tool_call_id == state["messages"][1].tool_calls[0]["id"]
        assert len(sdk.clients) == 1
        assert llm.evidence[-1]["usage"]["totalTokens"] == 100


def test_ainvoke_runs_off_loop_and_concurrent_contexts_are_private(sdk):
    sdk.barrier = threading.Barrier(2)

    async def run():
        with ChatCodexSDK() as llm:
            responses = await asyncio.gather(
                llm.ainvoke("OFFLINE_ALPHA"), llm.ainvoke("OFFLINE_BETA")
            )
            assert len({r.response_metadata["thread_id"] for r in responses}) == 2
            assert len(sdk.clients) == 2
            assert (
                "OFFLINE_ALPHA" in sdk.clients[0].prompt or "OFFLINE_ALPHA" in sdk.clients[1].prompt
            )
            assert all(
                not ("OFFLINE_ALPHA" in c.prompt and "OFFLINE_BETA" in c.prompt)
                for c in sdk.clients
            )

    asyncio.run(run())


def test_async_cancel_targets_only_own_invocation(sdk):
    sdk.hold = True

    async def run():
        with ChatCodexSDK(timeout_seconds=4) as llm:
            first = asyncio.create_task(llm.ainvoke("OFFLINE_ONE"))
            while len(sdk.clients) < 1 or not sdk.clients[0].ready.is_set():
                await asyncio.sleep(0.005)
            second = asyncio.create_task(llm.ainvoke("OFFLINE_TWO"))
            while len(sdk.clients) < 2 or not sdk.clients[1].ready.is_set():
                await asyncio.sleep(0.005)
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            assert sdk.clients[0].interrupts == 1 and sdk.clients[1].interrupts == 0
            second.cancel()
            with pytest.raises(asyncio.CancelledError):
                await second
            assert sdk.clients[1].interrupts == 1

    asyncio.run(run())


def test_structured_failure_does_not_silently_fallback(sdk):
    from pydantic import BaseModel

    class Required(BaseModel):
        value: int

    with ChatCodexSDK() as llm:
        with pytest.raises(ValueError):
            llm.with_structured_output(Required).invoke("OFFLINE_INVALID_JSON")
        with pytest.raises(RuntimeError, match="fallback.*blocked"):
            llm.invoke("OFFLINE_INVALID_JSON")
        assert len(sdk.clients) == 1


def test_stream_methods_are_explicitly_unverified():
    llm = ChatCodexSDK()
    with pytest.raises(NotImplementedError, match="UNVERIFIED"):
        llm.stream("anything")

    async def run():
        with pytest.raises(NotImplementedError, match="UNVERIFIED"):
            async for _ in llm.astream("anything"):
                pass

    asyncio.run(run())


def test_runtime_uses_pinned_sdk_and_only_config_names(tmp_path, monkeypatch):
    from langchain_codex_sdk.runtime import restricted_config

    home = tmp_path / "config_only"
    home.mkdir()
    (home / "config.toml").write_text('[mcp_servers.local_fixture]\ncommand="unused"\n')
    monkeypatch.setenv("CODEX_HOME", str(home))
    cfg = restricted_config(str(tmp_path / "cwd"))
    assert cfg.codex_bin is None
    assert "mcp_servers.local_fixture.enabled=false" in cfg.config_overrides
    assert cfg.env == {"OPENAI_API_KEY": "", "CODEX_API_KEY": ""}


def test_api_key_auth_is_refused_without_claiming_managed_login(sdk):
    from types import SimpleNamespace

    sdk.account_read = lambda *a: SimpleNamespace(
        model_dump=lambda **k: {"account": {"type": "apiKey"}}
    )
    with ChatCodexSDK() as llm:
        with pytest.raises(RuntimeError, match="ChatGPT-managed login required"):
            llm.invoke("OFFLINE")
        assert llm.evidence[-1]["auth_kind"] is None
        assert not hasattr(sdk.clients[0], "params")


@pytest.mark.parametrize("name", ["temperature", "max_tokens", "api_key"])
def test_unsupported_options_are_never_silently_accepted(name):
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as exc:
        ChatCodexSDK(**{name: "OFFLINE_UNSUPPORTED"})
    assert "OFFLINE_UNSUPPORTED" not in str(exc.value)
    llm = ChatCodexSDK()
    with pytest.raises(ValueError, match="Unsupported Codex invocation options"):
        llm.invoke("OFFLINE", **{name: "OFFLINE_UNSUPPORTED"})
    assert not llm.evidence
