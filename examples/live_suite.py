"""User-invoked four-task live integration, private logs; no CI authentication.

Two isolated real agents (invoke/ainvoke) -> original LangGraph ToolNode agent,
then one strict Pydantic call. No financial data, account tools or broker APIs.
"""

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage, messages_to_dict
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from pydantic import BaseModel

from examples.tool_graph import add_numbers
from langchain_codex_sdk import ChatCodexSDK, UsageLedger
from langchain_codex_sdk.recovery import write_json


class LiveState(MessagesState):
    alpha: str
    beta: str


class LiveAnswer(BaseModel):
    result: int
    quality: Literal["exact"]
    optional_value: float | None = None
    note: str | None = None


async def run(directory):
    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)
    if (out / "completed.json").exists():
        return json.loads((out / "completed.json").read_text())
    if (out / "usage_ledger.json").exists():
        raise RuntimeError(
            "Prior unfinished live experiment preserved; inspect it instead of blindly restarting"
        )
    guard = UsageLedger(
        out / "usage_ledger.json",
        max_active=2,
        token_limit=60_000,
        max_tasks=4,
        reserve_per_task=15_000,
        process_lock=True,
    )
    models = {
        name: ChatCodexSDK(
            model="gpt-6.1-sol",
            working_directory=str(out / "runtime" / name),
            event_log_path=str(out / f"{name}.jsonl"),
            resource_guard=guard,
            task_key_prefix="EXTRACTION_LIVE:" + name,
            timeout_seconds=120,
        )
        for name in ["alpha", "beta", "tools", "schema"]
    }
    workflow = StateGraph(LiveState)
    observations = []

    def alpha(state):
        started = time.monotonic()
        result = models["alpha"].invoke(
            [
                SystemMessage("You are isolated agent alpha. Return exactly ALPHA_OK."),
                HumanMessage("Reply ALPHA_OK only."),
            ]
        )
        observations.append(
            {
                "role": "alpha",
                "metadata": result.response_metadata,
                "started": started,
                "ended": time.monotonic(),
            }
        )
        return {"alpha": result.content}

    async def beta(state):
        started = time.monotonic()
        result = await models["beta"].ainvoke(
            [
                SystemMessage("You are isolated agent beta. Return exactly BETA_OK."),
                HumanMessage("Reply BETA_OK only."),
            ]
        )
        observations.append(
            {
                "role": "beta",
                "metadata": result.response_metadata,
                "started": started,
                "ended": time.monotonic(),
            }
        )
        return {"beta": result.content}

    bound = models["tools"].bind_tools([add_numbers])

    def tool_agent(state):
        assert state["alpha"].strip() == "ALPHA_OK" and state["beta"].strip() == "BETA_OK"
        return {"messages": [bound.invoke(state["messages"])]}

    workflow.add_node("alpha", alpha)
    workflow.add_node("beta", beta)
    workflow.add_node("tool_agent", tool_agent)
    workflow.add_node("tools", ToolNode([add_numbers]))
    workflow.add_edge(START, "alpha")
    workflow.add_edge(START, "beta")
    workflow.add_edge(["alpha", "beta"], "tool_agent")
    workflow.add_conditional_edges("tool_agent", tools_condition, {"tools": "tools", END: END})
    workflow.add_edge("tools", "tool_agent")
    graph = workflow.compile()
    started = time.monotonic()
    result = {
        "status": "RUNNING",
        "model": "gpt-6.1-sol",
        "sdk_task_target": 4,
        "scope": "generic two-agent merge + original ToolNode + strict Pydantic; not a financial study",
    }
    write_json(out / "result.json", result)
    try:
        state = await graph.ainvoke(
            {
                "messages": [
                    HumanMessage(
                        "Use the add_numbers tool exactly once with a=7, b=5, then return 12."
                    )
                ]
            },
            {"max_concurrency": 2, "recursion_limit": 12},
        )
        write_json(
            out / "graph_state.json", {**state, "messages": messages_to_dict(state["messages"])}
        )
        tool_messages = [m for m in state["messages"] if m.type == "tool"]
        assert len(tool_messages) == 1 and tool_messages[0].content == "12"
        assert "12" in state["messages"][-1].content
        parsed = (
            models["schema"]
            .with_structured_output(LiveAnswer)
            .invoke(
                'SCHEMA_TEST_ONLY: result=12, quality="exact", optional_value=null, note=null. Return the JSON object.'
            )
        )
        assert parsed == LiveAnswer(result=12, quality="exact")
        write_json(out / "structured.json", models["schema"].structured_evidence)
        assert len({o["metadata"]["thread_id"] for o in observations}) == 2
        overlap = min(o["ended"] for o in observations) - max(o["started"] for o in observations)
        assert overlap > 0
        result.update(
            status="PASS",
            thread_isolation="PASS",
            graph_merge="PASS",
            invoke="PASS",
            ainvoke="PASS",
            toolnode="PASS",
            pydantic="PASS",
            concurrent_overlap_seconds=overlap,
        )
    except Exception as exc:
        result.update(status="STOPPED", error_type=type(exc).__name__, error=str(exc))
        raise
    finally:
        for name, model in models.items():
            model.close()
            write_json(out / f"{name}_adapter.json", model.evidence)
            write_json(out / f"{name}_structured.json", model.structured_evidence)
            write_json(out / f"{name}_fallback.json", model.fallback_evidence)
        result.update(
            elapsed_seconds=time.monotonic() - started,
            usage=guard.snapshot()["reported_breakdown"],
            sdk_tasks=len(guard.sessions),
            unknown_tasks=guard.snapshot()["unknown_tasks"],
        )
        write_json(out / "observations.json", observations)
        write_json(out / "result.json", result)
        guard.close()
    if result["status"] == "PASS":
        write_json(out / "completed.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--live", action="store_true", help="Explicitly start four real local SDK tasks"
    )
    parser.add_argument("--output", default="private/live-extraction")
    args = parser.parse_args()
    if not args.live:
        parser.error("No model calls started. Pass --live to opt in locally.")
    print(json.dumps(asyncio.run(run(args.output)), indent=2))
