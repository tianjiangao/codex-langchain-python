"""Actual LangGraph ToolNode executes a local arithmetic function; no financial API."""

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from langchain_codex_sdk import ChatCodexSDK


@tool
def add_numbers(a: int, b: int) -> str:
    """Add two integers without network access or side effects."""
    return str(a + b)


def build_graph(llm, checkpointer=None, interrupt_after=None):
    bound = llm.bind_tools([add_numbers])
    graph = StateGraph(MessagesState)
    graph.add_node("agent", lambda state: {"messages": [bound.invoke(state["messages"])]})
    graph.add_node("tools", ToolNode([add_numbers]))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", tools_condition, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")
    return graph.compile(checkpointer=checkpointer, interrupt_after=interrupt_after)


if __name__ == "__main__":
    with ChatCodexSDK(model="gpt-6.1-sol") as llm:
        state = build_graph(llm).invoke(
            {"messages": [HumanMessage("Use add_numbers with a=7, b=5. Return the result.")]},
            {"recursion_limit": 12},
        )
        print(state["messages"][-1].content)
