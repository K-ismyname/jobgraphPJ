# Gap 분석 서브 에이전트 — ReAct 루프를 독립 CompiledGraph로 분리
from __future__ import annotations

from typing import TYPE_CHECKING

from langgraph.graph import END, START, StateGraph

from src.agent.state import GapState, MAX_ITERATIONS

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool


def create_gap_graph(gap_tools: list["BaseTool"]):
    """Gap ReAct 루프를 독립 서브그래프로 반환한다.

    Supervisor가 consensus 결과를 GapState로 변환해 넘기면,
    GapAgent가 Neo4j 툴로 갭을 분석하고 gap_result를 반환한다.
    """
    from src.agent.nodes import create_nodes, make_tools_node

    call_model, _ = create_nodes(gap_tools, neo4j=None)
    tools_node = make_tools_node(gap_tools)

    def route_gap_loop(state: GapState) -> str:
        if state.get("iteration", 0) >= MAX_ITERATIONS:
            return END
        last = (list(state.get("messages") or [None]))[-1]
        return "tools" if (last and getattr(last, "tool_calls", None)) else END

    workflow = StateGraph(GapState)
    workflow.add_node("call_model", call_model)
    workflow.add_node("tools",      tools_node)

    workflow.add_edge(START, "call_model")
    workflow.add_conditional_edges("call_model", route_gap_loop,
                                   {"tools": "tools", END: END})
    workflow.add_edge("tools", "call_model")

    return workflow.compile()
