"""Optional OFFLINE original-framework integration; source checkout required."""

import importlib.util
import json
import os
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from integrations.role_context import ROLES, CodexGraphModel
from integrations.tradingagents import install_provider
from langchain_codex_sdk import ChatCodexSDK


@pytest.mark.tradingagents
def test_original_full_graph_and_schemas_with_extracted_provider(monkeypatch, tmp_path):
    checkout = os.environ.get("TRADINGAGENTS_CHECKOUT")
    if not checkout:
        pytest.skip("Optional TradingAgents checkout not provided")
    from tradingagents.agents.schemas import PortfolioDecision, ResearchPlan, TraderProposal
    from tradingagents.default_config import DEFAULT_CONFIG

    spec = importlib.util.spec_from_file_location(
        "upstream_graph_fixtures", Path(checkout) / "tests/test_graph_end_to_end.py"
    )
    fixture_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture_module)
    fixture_module.offline.__wrapped__(monkeypatch, tmp_path)
    payloads = {
        ResearchPlan.__name__: {
            "recommendation": "Hold",
            "rationale": "OFFLINE",
            "strategic_actions": "OFFLINE",
        },
        TraderProposal.__name__: {
            "action": "Hold",
            "reasoning": "OFFLINE",
            "entry_price": None,
            "stop_loss": None,
            "position_sizing": None,
        },
        PortfolioDecision.__name__: {
            "rating": "Hold",
            "executive_summary": "OFFLINE",
            "investment_thesis": "OFFLINE",
            "price_target": None,
            "time_horizon": None,
        },
    }

    class OfflineCodex(ChatCodexSDK):
        def _generate(self, messages, **kwargs):
            schema = kwargs.get("codex_output_schema")
            if schema:
                msg = AIMessage(content=json.dumps(payloads[schema["title"]]))
            elif kwargs.get("codex_tools") and not isinstance(messages[-1], ToolMessage):
                calls = [
                    {
                        "name": t["name"],
                        "id": "OFFLINE_" + t["name"],
                        "args": {
                            k: v
                            for k, v in fixture_module.ARGS.items()
                            if k in t["inputSchema"]["properties"]
                        },
                    }
                    for t in kwargs["codex_tools"]
                ]
                msg = AIMessage(content="", tool_calls=calls)
            else:
                msg = AIMessage(content="OFFLINE_REPORT. FINAL TRANSACTION PROPOSAL: HOLD")
            return ChatResult(generations=[ChatGeneration(message=msg)])

    from tradingagents.graph.analyst_execution import build_analyst_execution_plan

    allowed = tuple(
        t.name
        for spec in build_analyst_execution_plan(["market", "fundamentals"]).specs
        for t in spec.tools
    )
    adapter = CodexGraphModel(
        directory=tmp_path,
        guard=None,
        attempt="OFFLINE",
        allowed_tools=allowed,
        model_factory=OfflineCodex,
    )
    cfg = {
        **DEFAULT_CONFIG,
        "data_cache_dir": str(tmp_path / "cache"),
        "results_dir": str(tmp_path / "results"),
        "memory_log_path": str(tmp_path / "memory.md"),
        "checkpoint_enabled": True,
    }
    state, rating = install_provider(cfg, adapter).propagate("NVDA", fixture_module.TRADE_DATE)
    assert rating == "Hold" and set(adapter.models) == set(ROLES)
    assert (
        state["investment_debate_state"]["count"] == 2 and state["risk_debate_state"]["count"] == 3
    )
    for role in ["Research Manager", "Trader", "Portfolio Manager"]:
        assert adapter.models[role].structured_evidence[0]["status"] == "PASS"
        assert not adapter.models[role].fallback_evidence
