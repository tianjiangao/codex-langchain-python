# Optional TradingAgents integration

The core package neither imports nor installs TradingAgents. Integration files here only select the provider for original business nodes; they do not redefine financial prompts, tools, schemas or routers.

## Install and configure

Install this package into an independent environment with `pip install '.[langgraph]'`. If you want the financial example, separately install your approved TradingAgents v0.6.0 checkout in that environment (`pip install -e ../TradingAgents`). Do not alter an existing stable environment simply to try the example.

```bash
python -m integrations.tradingagents              # dry-run only; works without TradingAgents
python -m integrations.tradingagents --live \
  --ticker NVDA --as-of 2026-10-09                # deliberate real financial research
```

Default behavior performs no model calls or financial requests. The example binds original research data tools, **no broker interface**, and never executes orders. Real operation uses original TradingAgentsGraph's two-analyst configuration, official SQLite checkpoints, private cache/results/memory folders, original tool/debate defaults, and SEC EDGAR before Yahoo for historical fundamentals. It injects the package's role-local model registry only while constructing the provider. Quick and deep models remain gpt-6.1-sol; optional schema values are retained.

Completed `propagate` checkpoints follow the original framework's clearing behavior. This illustrative CLI is not an unattended scheduler: inspect saved state and usage after failure before deliberately restoring. Native cold Thread Resume is not implemented; framework checkpoint replay may create a new Thread. Tool side-effect recovery must be handled by the application.

For a quick offline smoke with your existing source checkout, set `TRADINGAGENTS_CHECKOUT` and run `tests/integrations/test_tradingagents_optional.py` in an environment containing the separately installed framework. This test uses the real original Graph and original schema classes, but synthetic SDK/vendor responses. It does not call brokers or generate a claimed new real NVDA report.

## Accepted source E2E summary (not a new package financial run)

The source Adapter baseline `194454e` passed official TradingAgents v0.6.0 **two-analyst full Graph START → END**, scope C:

- 10/10 genuine SDK tasks, separate role threads; 15 financial Tool Calling roundtrips.
- Real Market + Fundamentals concurrency; original Bull/Bear and risk conditional routing; complete merged histories.
- ResearchPlan, TraderProposal, PortfolioDecision native Pydantic validation; no free-text fallback.
- 189,849 measured Tokens (input 176,750; output 13,099; cached 36,096 already in input); 407.27 seconds.
- 168 related source Adapter tests and 1430 source offline regression tests passed.

The extraction phase separately passed four generic SDK tasks for invoke/ainvoke, real ToolNode and Pydantic, plus an offline **new-package-provider → original full Graph** smoke. It did **not** repeat financial research. Original project/environment and stable checkout remain unchanged.

## Limitations and distribution

News and Sentiment were unselected/MISSING in that two-analyst configuration. Yahoo adjusted historical publication vintage and model pretraining cutoff isolation remain UNVERIFIED; account usage may be missing on failures. Historical SEC disclosures and market cutoffs must still be audited by the financial application.

No original research report, OHLCV/SEC dataset, raw prompt, sensitive execution log or private absolute path is included here. Data redistribution rights have not been established. Public examples are arithmetic/technical summaries only. Running a research example is not authorization to redistribute a financial vendor's data or a promise of investment returns.
