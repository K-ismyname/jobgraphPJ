# Coach 서브 에이전트 — 면접 코칭 ReAct 루프를 독립 CompiledGraph로 분리
from __future__ import annotations

from typing import TYPE_CHECKING

from langgraph.graph import END, START, StateGraph

from src.agent.state import CoachState, COACH_MAX_ITERATIONS

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool


def create_coach_graph(coach_tools: list["BaseTool"]):
    """Coach ReAct 루프를 독립 서브그래프로 반환한다.

    Supervisor가 gap_result + project_contexts를 CoachState로 변환해 넘기면,
    CoachAgent가 면접 코칭 + 프로젝트 제안을 생성하고 final_report를 반환한다.
    """
    from src.agent.nodes import create_coach_nodes, make_coach_tools_node

    coach_call_model, finalize_coach = create_coach_nodes(coach_tools)
    coach_tools_node = make_coach_tools_node(coach_tools)

    def route_coach_loop(state: CoachState) -> str:
        if state.get("coach_iteration", 0) >= COACH_MAX_ITERATIONS:
            return "finalize_coach"
        last = (list(state.get("coach_messages") or [None]))[-1]
        if last and getattr(last, "tool_calls", None):
            return "coach_tools"
        return "finalize_coach"

    workflow = StateGraph(CoachState)
    workflow.add_node("coach_call_model", coach_call_model)
    workflow.add_node("coach_tools",      coach_tools_node)
    workflow.add_node("finalize_coach",   finalize_coach)

    workflow.add_edge(START, "coach_call_model")
    workflow.add_conditional_edges("coach_call_model", route_coach_loop,
                                   {"coach_tools": "coach_tools",
                                    "finalize_coach": "finalize_coach"})
    workflow.add_edge("coach_tools", "coach_call_model")
    workflow.add_edge("finalize_coach", END)

    return workflow.compile()
