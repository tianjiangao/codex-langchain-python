"""Optional original TradingAgents provider injection. Dry-run by default."""

import argparse
import copy
import json
from pathlib import Path
from unittest.mock import patch

from integrations.role_context import CodexGraphModel
from langchain_codex_sdk import UsageLedger


class Client:
    def __init__(self, model):
        self.model = model

    def get_llm(self):
        return self.model


def install_provider(config, adapter):
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    with patch(
        "tradingagents.graph.trading_graph.create_tier_client", return_value=Client(adapter)
    ):
        return TradingAgentsGraph(selected_analysts=["market", "fundamentals"], config=config)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--live",
        action="store_true",
        help="Start real original financial research (no broker execution)",
    )
    parser.add_argument("--ticker", default="NVDA")
    parser.add_argument("--as-of", default="2026-10-09")
    parser.add_argument("--directory", default="private/tradingagents-example")
    args = parser.parse_args()
    if not args.live:
        print(
            json.dumps(
                {
                    "mode": "DRY RUN — no SDK or financial tool calls",
                    "analysts": ["market", "fundamentals"],
                    "model": "gpt-6.1-sol",
                    "ticker": args.ticker,
                    "as_of": args.as_of,
                    "framework": "Separately install your TradingAgents v0.6.0 checkout; not a package dependency",
                    "live_command": "python -m integrations.tradingagents --live",
                }
            )
        )
        return
    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.graph.analyst_execution import build_analyst_execution_plan

    directory = Path(args.directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg.update(
        llm_provider="codex",
        quick_think_llm="gpt-6.1-sol",
        deep_think_llm="gpt-6.1-sol",
        llm_max_retries=0,
        checkpoint_enabled=True,
        data_cache_dir=str(directory / "cache"),
        results_dir=str(directory / "results"),
        memory_log_path=str(directory / "memory.md"),
    )
    cfg["data_vendors"]["fundamental_data"] = "sec_edgar,yfinance"
    names = tuple(
        t.name
        for spec in build_analyst_execution_plan(["market", "fundamentals"]).specs
        for t in spec.tools
    )
    with_guard = UsageLedger(
        directory / "usage.json",
        token_limit=2_000_000,
        measured_only=True,
        soft_warning_tokens=1_000_000,
        process_lock=True,
    )
    adapter = CodexGraphModel(
        directory=directory, guard=with_guard, attempt="manual", allowed_tools=names, resume=True
    )
    try:
        graph = install_provider(cfg, adapter)
        state, rating = graph.propagate(args.ticker, args.as_of)
        graph.save_reports(state, args.ticker, directory / "reports")
        print(rating)
    finally:
        adapter.close()
        with_guard.close()


if __name__ == "__main__":
    main()
