# Code provenance and license accounting

The initial source is the verified Codex Adapter in the separate TradingAgents-Codex development checkout at `194454ec52cebb37bc2b0803e732ffedc7687567`. Base TradingAgents v0.6.0 source is `1394a3f72aa4393e1a98f51b382434c4b4c2d972`. Relative source file hashes are in [extraction_sources.json](extraction_sources.json). Neither original Git history nor local/private file paths are imported.

| Component | Source | Extraction/modification |
|---|---|---|
| `chat_models.py` | `codex_client.py` | BaseChatModel kept; application client wrapper removed; class/import names, generic tools, temporary cwd, executor async and usage metadata added |
| `runtime.py` | `codex_runtime.py` | Official SDK configuration kept; generic restrictions/client identity; bundled runtime default; managed login only |
| `tools.py` | `codex_tools.py` | Suspended SDK callback → ToolCall → ToolMessage bridge, timeout/cancel and terminal ledger ordering retained; generic explicit binding |
| `messages.py` | `codex_messages.py` | Role serialization/JSON parsing retained |
| `schema.py` | `codex_schema.py` | Strict normalization/original validation/value-change tracking and service error classification retained |
| `usage.py` | `codex_resources.py` | Original/UNKNOWN usage, cached subset, durable policies and process lock retained |
| `recovery.py` | `codex_recovery.py` | SQLite seals/history checks/submission locks retained |
| `integrations/role_context.py` | `codex_graph.py` | Original role-routing provider shell retained outside core; import/task-prefix changes |
| Offline assertions | Codex Adapter tests | Reused protocol/normalization/lifecycle assertions with new generic fixtures and independent process graph |

These copied/modified source files were in an Apache-2.0 project. **LICENSE is the original Apache-2.0 text**, SPDX headers identify changed extracted files, and NOTICE records attribution/modifications. There was no original upstream NOTICE in the inspected source tree; we do not invent one. No original official financial agent, schema class, vendor or data set is vendored. Optional integration imports those from a separately installed checkout.

The source Adapter acknowledged these design references, whose full MIT texts/copyright notices are retained under `licenses/` and included in both wheel and sdist:

- [Euan Cowie's langchain-codex](https://github.com/euan-cowie/langchain-codex/tree/a4cbfa1dc85829c8c99d46a3505b377e0a8c2b68): role-labelled history, structured parsing and tool-conversion design; Copyright (c) 2026 Euan Cowie.
- [cgaravitoq/open-langchain](https://github.com/cgaravitoq/open-langchain/tree/04b0bf47957dee57e5c8bf4486a63cf81ed88ee9): Python interface/message reference only; Copyright (c) 2026 cgaravitoq.
- [DeerFlow](https://github.com/bytedance/deer-flow/tree/1f15e0b43ca58b9601514f9f5c408fb032022833): system/tool/usage layout design only; Copyright (c) 2025 Bytedance Ltd. and/or its affiliates and (c) 2025-2026 DeerFlow Authors.

Their authentication, OAuth loader, private HTTP client and credential access code are **not reused**. These works keep their MIT licenses; no claim is made to relicense their code. The official `openai-codex` dependency is installed from its publisher and not vendored/relicensed.

## Financial-data distribution boundary

The prior E2E used Yahoo Finance/yfinance and public SEC EDGAR data. Public access and a library's code license do not establish unrestricted rights to redistribute provider data. This candidate distributes **no raw OHLCV, SEC cache, financial statements, research report, raw financial prompt or financial execution log**. Its [E2E summary](TRADINGAGENTS.md) is limited to technical acceptance/usage metrics. Financial-data redistribution rights are **UNVERIFIED** and would need a separate review/permission before publishing any report or dataset. Live examples here use only local arithmetic.
