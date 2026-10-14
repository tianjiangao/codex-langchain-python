# LangChain Codex SDK — community alpha

A standalone Python `BaseChatModel` adapter for the **official local `openai-codex` SDK**. It was extracted from a validated multi-agent integration rather than built as a new provider framework. **TradingAgents is not a dependency.**

This is an independent community project, **not an official OpenAI or LangChain provider**. Distribution name `langchain-codex-sdk`, import `langchain_codex_sdk`, and repository name `codex-langchain-python` are provisional. Nothing has been published to GitHub or PyPI.

## Install

Python 3.11+ on POSIX; locally tested on Linux x86-64 / Python 3.12. From a source checkout:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install .
# Optional real LangGraph examples/checkpoints:
python -m pip install '.[langgraph]'
```

`openai-codex==0.162.1` is deliberately pinned to the tested protocol. The SDK supplies its pinned CLI runtime; `codex_bin=` opts into a different executable whose compatibility you must verify. Dependency ranges are not a claim that every version/platform has been tested.

Sign in **locally** using the official Codex CLI (`codex login`). This release accepts only the runtime's existing ChatGPT-managed login and clears API-key environment overrides in the child process. It never reads or exports authentication files, tokens or cookies. It reads only configuration to disable inherited MCP servers, without logging config values.

## Quickstart

```python
from langchain_codex_sdk import ChatCodexSDK

with ChatCodexSDK(model="gpt-6.1-sol") as llm:
    result = llm.invoke("Hello from LangChain")
    print(result.content)
    print(result.usage_metadata)
```

A plain fresh call gets an isolated ephemeral SDK Thread. Tool replies continue their corresponding suspended Thread, without resending the full history. A supplied conversation is serialized explicitly; independent hidden Thread histories are not shared.

### Async

```python
import asyncio
from langchain_codex_sdk import ChatCodexSDK

async def main():
    with ChatCodexSDK(model="gpt-6.1-sol") as llm:
        result = await llm.ainvoke("Reply briefly.")
        print(result.content)

asyncio.run(main())
```

`ainvoke` uses a thread executor around the validated synchronous transport, **not** native `AsyncCodex`. Cancellation is best effort and scoped to direct model `ainvoke` calls. Async structured-wrapper cancellation is UNVERIFIED. Close the model to cancel any abandoned pending tool sessions. External tool side effects are controlled by the caller, not rolled back by cancellation.

### Tools

```python
from langchain_core.tools import tool
from langchain_codex_sdk import ChatCodexSDK

@tool
def add_numbers(a: int, b: int) -> str:
    """Add two integers without external services."""
    return str(a + b)

with ChatCodexSDK(model="gpt-6.1-sol") as llm:
    bound = llm.bind_tools([add_numbers])
    # Feed AIMessage.tool_calls through your own executor/ToolNode, then
    # return matching ToolMessages to bound.invoke(messages).
```

Binding a tool grants it model-call visibility. Optional `allowed_tools=("add_numbers",)` further restricts names. Only registered tools are accepted; built-in shell/file/web/agent/MCP actions are disabled/denied. **The adapter does not execute Python tools.** See the ready-to-run [ToolNode example](examples/tool_graph.py):

```bash
python -m examples.tool_graph
```

Dynamic Tool Calling is **EXPERIMENTAL upstream**, even though offline and live roundtrips passed. One callback is exposed at a time, with a single correlated ToolMessage required per pending callback. Automatic or forced `tool_choice`, parallel-call promises and tool-specific external permissions are not generalized here.

### Native structured output

```python
from pydantic import BaseModel
from langchain_codex_sdk import ChatCodexSDK

class Answer(BaseModel):
    result: int
    note: str | None = None

with ChatCodexSDK(model="gpt-6.1-sol") as llm:
    answer = llm.with_structured_output(Answer).invoke(
        "Calculate 7 + 5. Set note to null."
    )
    print(answer.model_dump())
```

The original Pydantic class defines the business value. A separate strict wire schema closes objects and requires already-nullable `default=None` fields. Local annotated references are normalized without dropping constraints. Raw JSON is validated again by the original class and wire schema; missing fields, coercions, errors and normalization changes remain inspectable. No free-text fallback or silent field deletion. Unsupported sampling/token-cap/endpoint options raise rather than silently ignoring an API-style limit. Defaults whose meaning cannot be preserved, arbitrary maps and external/constrained recursive references are explicitly blocked. See [compatibility](COMPATIBILITY.md).

### Usage and recovery

`UsageLedger(path)` optionally persists original SDK usage and UNKNOWN tasks. Input includes Cached; Total is Input + Output. Failed/cancelled tasks with missing usage are **UNKNOWN**, not zero. `resource_guard=ledger` connects it to a model. Strict admission is the default; explicit measured-only soft/hard thresholds are available. These are local experimental controls, not account quotas or a server-side billing ceiling.

`CheckpointStore(directory)` provides integrity seals and submission locks for a caller-owned SQLite/LangGraph checkpoint. `allow_history_replay=True` permits **Checkpoint + New Thread Replay** only with saved, correctly correlated tool results. This is neither Native Thread Resume nor Restart From Beginning. Exactly-once side effects across crashes require idempotent tools/application transactions; the adapter cannot guarantee them alone.

## Test and contribute

```bash
python -m pip install '.[dev]'
pytest -q                  # Offline; real SDK startup forbidden, live tests skipped
ruff check src tests examples integrations scripts
python -m build
python -m twine check dist/*
```

GitHub Actions runs offline tests/builds only, with no Codex login, API keys, authentication artifacts or live credential upload. To deliberately run the four-task local live integration (two isolated agents, real ToolNode, native Pydantic):

```bash
CODEX_RUN_LIVE_TESTS=1 pytest -q tests/live
# Or: python -m examples.live_suite --live
```

This consumes local account usage. Raw logs go to ignored `private/`; inspect them locally and never publish them automatically. [Clean live evidence summary](docs/LIVE_VALIDATION.md) and [optional TradingAgents integration](docs/TRADINGAGENTS.md) describe what was actually tested.

## Official SDK scope and account limits

The [official Python SDK](https://learn.chatgpt.com/docs/codex-sdk) drives local Codex App Server, includes a pinned runtime, and needs model access on the signed-in account. [Dynamic tools](https://learn.chatgpt.com/docs/app-server#dynamic-tool-calls-experimental) are experimental. The [authentication guidance](https://learn.chatgpt.com/docs/auth) distinguishes ChatGPT subscription access from API billing and recommends API-key authentication for programmatic CLI CI/CD workflows, while warning against exposing execution to public/untrusted environments.

This release is for **user-controlled local experiments** with managed Codex login. It is not an OAuth token loader, a private ChatGPT HTTP client, a subscription-to-API-key converter, or a hosted general OpenAI API service. It does not claim that a subscription grants unlimited automation, supported public-serving rights, precise billing visibility, or general API-provider semantics. Official account permissions, model availability, rate limits and terms continue to apply. No account limit bypasses, background batch jobs or automatic retries are implemented.

## License and limits

Apache-2.0, with retained MIT design-reference notices/texts. See [NOTICE](NOTICE), [provenance](docs/PROVENANCE.md), [security](SECURITY.md) and [compatibility](COMPATIBILITY.md).

Token `stream`/`astream` explicitly raise `NotImplementedError` (**UNVERIFIED**). Native Thread Resume, multimodal input, Windows locks/runtime, broader SDK versions and crash-atomic external side effects are not claimed. No original financial data, private research reports or raw sensitive logs are included. Publication requires a separate explicit maintainer approval; this checkout has no configured remote or publish workflow.
