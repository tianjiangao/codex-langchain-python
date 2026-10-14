# Compatibility matrix — local alpha evidence

Status labels distinguish verified behavior from unimplemented or experimental protocol features. This matrix is not a promise of every version combination in dependency ranges.

| Capability | Offline | Real SDK | Scope / limitation |
|---|---|---|---|
| `invoke` / ordinary LangChain `BaseChatModel` | PASS | PASS | Independent package, text only; one isolated fresh ephemeral thread |
| `ainvoke` | PASS | PASS | Executor-backed synchronous SDK; not native AsyncCodex |
| Human/System/AI/Tool messages | PASS | PASS | System separated; IDs/names/results correlated; unsupported media rejected |
| `bind_tools` + actual LangGraph ToolNode | PASS | PASS / EXPERIMENTAL | Official dynamicTools protocol experimental; one pending callback/reply at a time |
| Two-agent concurrency / Thread isolation / state merge | PASS | PASS | Two local agents with distinct threads; shared hidden history absent |
| Pydantic v2 + native `outputSchema` | PASS | PASS | Original class and strict wire both validated; no fallback |
| Enum/Literal, nullable floats, `anyOf`, local `$ref`, closed objects | PASS | PASS in tested subset | Generic real fixture; original financial schemas also checked offline through integration |
| Numeric strings / invalid percentages / omissions / custom validators | PASS | Not live-injected | Original business validation runs, changes logged; wire rejects strings or omitted required fields |
| General defaults/maps/external or constrained recursive refs | BLOCKED | No attempt | Fail before SDK when lossless canonical-value mapping is unestablished |
| Usage input/output/cached/total | PASS | PASS | Cached subset; original usage retained; missing/partial tails UNKNOWN |
| Structured async wrapper cancellation | UNVERIFIED | Not attempted | RunnableLambda async cleanup is not the direct-model cancellation guarantee |
| Timeout, cancel, transport error | PASS | Not newly fault-injected | Async cancellation scoped, best effort; SDK may omit usage |
| Checkpoint integrity / duplicate ToolMessage / task lock | PASS | Prior source M5-A-R evidence only | Helpers for caller-owned checkpoint, not universal distributed transactions |
| Cross-process Checkpoint + New Thread Replay | PASS (two real processes, mock SDK) | Prior source M5-A-R only | Already executed tool not repeated by graph in tested boundary; not Native Resume |
| Native Thread Resume | UNVERIFIED / not implemented | UNVERIFIED | Adapter starts ephemeral threads; SDK support itself is not package support |
| `stream` / `astream` token streaming | UNVERIFIED / explicitly refused | Not attempted | Raise NotImplementedError; no final-message imitation of token streaming |
| Audio/images/file attachments | Unsupported | Not attempted | Text-only serializer |
| External tool exactly-once effects | UNVERIFIED | UNVERIFIED | Requires caller idempotency/transactions, not guaranteed by this adapter |
| Windows | Unsupported currently | Not attempted | fcntl-based process/checkpoint locks |
| macOS / other architectures | UNVERIFIED | Not attempted | Linux only locally verified |
| Python 3.11 / 3.12 / 3.13 | [Remote offline CI](https://github.com/tianjiangao/codex-langchain-python/actions/workflows/ci.yml) | Real SDK verified on 3.12 only | See the linked run for current matrix results; local live verification was 3.12.14 |

## Tested versions

- Independent package: Python 3.12.14, Linux x86-64; openai-codex **0.162.1** and its pinned CLI runtime dependency **openai-codex-cli-bin 0.162.1**; langchain-core **1.6.10**, pydantic **2.14.1**, jsonschema **4.26.0**, langgraph **1.2.15**, checkpoint-sqlite **3.1.2**.
- Optional original-framework offline integration: TradingAgents **v0.6.0**, existing environment langchain-core **1.6.9**, langgraph **1.2.14**, checkpoint-sqlite **3.1.1**. Original Graph and original ResearchPlan/TraderProposal/PortfolioDecision were used, with mock SDK output explicitly identified.
- Other SDK versions, alternative codex_bin executables, force/parallel tool-choice variants and account types are not certified. ChatGPT-managed local login is required by this release; API-key mode is explicitly refused.

## Schema semantic boundary

Only already-nullable default-None optional fields are promoted into required wire fields. Canonical business values remain nullable, while field-presence provenance (omitted vs explicit null) differs and is logged. A model omission is not silently repaired. Original Pydantic classes are not changed, no supplied fields are dropped, and strict raw wire validation occurs even when Pydantic could coerce a string or replace it with null. Response errors and attempted free-text fallback are separate evidence.

See [live evidence](docs/LIVE_VALIDATION.md), [original E2E context](docs/TRADINGAGENTS.md), and [official protocol documentation](https://learn.chatgpt.com/docs/app-server#dynamic-tool-calls-experimental).
