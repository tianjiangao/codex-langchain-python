"""OFFLINE: real child processes, original LangGraph ToolNode, synthetic SDK."""

import os
import sqlite3
import sys
from pathlib import Path

from langchain_core.messages import HumanMessage, messages_to_dict
from langchain_core.tools import tool
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from langchain_codex_sdk import ChatCodexSDK, CheckpointStore
from langchain_codex_sdk import tools as transport
from langchain_codex_sdk.recovery import write_json
from tests.sdk_mock import ScriptedSDK

mode, folder = sys.argv[1:]
out = Path(folder)


class SDK(ScriptedSDK):
    clients = []
    reply_text = "12"

    def thread_start(self, params):
        # A cold replay has completed tool history. Explicitly scripted mock, not a live model.
        result = super().thread_start(params)
        if mode == "resume":
            self.params = {**self.params, "dynamicTools": []}
        return result


transport.CodexClient = SDK
transport.restricted_config = lambda *a: object()


@tool
def add_numbers(a: int, b: int) -> str:
    """Record one offline side effect then add two numbers."""
    with (out / "tool_runs.txt").open("a") as f:
        f.write("OFFLINE_EXECUTION\n")
    return str(a + b)


def snapshot(graph, config):
    state = graph.get_state(config)
    return {
        "values": {"messages": messages_to_dict(state.values["messages"])},
        "next": list(state.next),
        "config": state.config,
    }


with ChatCodexSDK(allow_history_replay=mode == "resume") as llm:
    workflow = StateGraph(MessagesState)
    bound = llm.bind_tools([add_numbers])
    workflow.add_node("agent", lambda s: {"messages": [bound.invoke(s["messages"])]})
    workflow.add_node("tools", ToolNode([add_numbers]))
    workflow.add_edge(START, "agent")
    workflow.add_conditional_edges("agent", tools_condition, {"tools": "tools", END: END})
    workflow.add_edge("tools", "agent")
    store = CheckpointStore(out)
    cfg = {"configurable": {"thread_id": "OFFLINE_RECOVERY"}}
    with store.lock(), sqlite3.connect(out / "source.sqlite", check_same_thread=False) as conn:
        graph = workflow.compile(
            checkpointer=SqliteSaver(conn), interrupt_after=["tools"] if mode == "prepare" else None
        )
        if mode == "prepare":
            graph.invoke({"messages": [HumanMessage("OFFLINE tool request")]}, cfg)
            store.seal(conn, snapshot(graph, cfg), {"mock": True})
        else:
            before, _ = store.verify()
            assert snapshot(graph, cfg) == before
            graph.invoke(None, cfg)
            after = snapshot(graph, cfg)
            assert not after["next"] and after["values"]["messages"][-1]["data"]["content"] == "12"
            write_json(out / "after.json", after)
        write_json(out / f"{mode}_pid.json", {"pid": os.getpid(), "mock": True})
