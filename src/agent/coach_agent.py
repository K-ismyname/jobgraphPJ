# Coach 서브 에이전트 — 면접 코칭 ReAct 루프를 독립 CompiledGraph로 분리
#
# 이 파일이 하는 일: gap_agent.py와 거의 같은 구조(call_model ↔ tools ReAct 루프)를
# 코칭용으로 다시 조립한다. 딱 하나 구조적으로 다른 점이 있는데, gap_agent는 synthesizer(리포트 생성)를
# 서브그래프 밖(supervisor.py)에 뒀지만, 여기서는 finalize_coach(최종 결과 조립)를 이 서브그래프
# 안에 노드로 포함시킨다 — 그 이유는 아래 route_coach_loop에서 설명한다.

from __future__ import annotations

from typing import TYPE_CHECKING

from langgraph.graph import END, START, StateGraph

from src.agent.state import CoachState, COACH_MAX_ITERATIONS
# state.py에서 봤던 그 상수 — MAX_ITERATIONS(5)와 별개로 코칭 루프는 3번까지만 허용.
# 코칭은 갭 분석보다 상대적으로 짧은 판단(이미 만들어진 gap_result를 코칭 문구로 바꾸는 것)이라
# 더 적은 반복으로도 충분하다고 본 것으로 추정

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool


def create_coach_graph(coach_tools: list["BaseTool"]):
    """Coach ReAct 루프를 독립 서브그래프로 반환한다.

    Supervisor가 gap_result + project_contexts를 CoachState로 변환해 넘기면,
    CoachAgent가 면접 코칭 + 프로젝트 제안을 생성하고 final_report를 반환한다.
    """
    from src.agent.nodes import create_coach_nodes, make_coach_tools_node

    coach_call_model, finalize_coach = create_coach_nodes(coach_tools)
    # nodes.py의 create_coach_nodes()가 튜플로 두 함수를 한 번에 반환 — gap_agent 쪽은
    # create_call_model()이 하나만, create_synthesizer()가 또 하나만(따로) 반환했던 것과 달리
    # 여기는 "한 팩토리가 두 노드 함수를 같이 만든다"는 점이 다름 (메모리 기록의 "create_nodes
    # Tuple Pattern Fragmentation"이 바로 이 비일관성을 가리키는 것으로 보임 — 파일 안에서도
    # 노드를 만드는 방식이 하나로 통일돼 있지 않음)
    coach_tools_node = make_coach_tools_node(coach_tools)

    def route_coach_loop(state: CoachState) -> str:
        if state.get("coach_iteration", 0) >= COACH_MAX_ITERATIONS:
            return "finalize_coach"
            # gap_agent의 route_gap_loop은 상한 도달 시 END로 바로 갔지만, 여기는 "finalize_coach"로 감 —
            # 이게 이 파일 구조의 핵심 차이. 코칭 루프는 반복이 강제 종료되더라도, 그냥 끝내지 않고
            # 반드시 finalize_coach를 거쳐서 "지금까지 나온 마지막 텍스트라도 파싱해서 결과를 만들어야" 함
        last = (list(state.get("coach_messages") or [None]))[-1]
        if last and getattr(last, "tool_calls", None):
            return "coach_tools"
        return "finalize_coach"
        # 도구 호출이 없으면(=LLM이 텍스트로 최종 코칭 결과를 냈으면) 여기서도 finalize_coach로 —
        # gap_agent가 END로 갔던 것과 달리, "이 루프의 마지막 텍스트가 실제로 쓰인다"는 사실이
        # route 함수의 목적지 차이로 드러남 (gap_agent 시각화 때 얘기했던 그 대조점의 코드 증거)

    workflow = StateGraph(CoachState)
    workflow.add_node("coach_call_model", coach_call_model)
    workflow.add_node("coach_tools",      coach_tools_node)
    workflow.add_node("finalize_coach",   finalize_coach)
    # finalize_coach가 이 서브그래프 "안"의 정식 노드로 등록됨 — gap_agent 서브그래프엔
    # synthesizer에 해당하는 노드가 아예 없었던 것과 대조적인 구조

    workflow.add_edge(START, "coach_call_model")
    workflow.add_conditional_edges("coach_call_model", route_coach_loop,
                                   {"coach_tools": "coach_tools",
                                    "finalize_coach": "finalize_coach"})
    # 매핑이 gap_agent.py의 {"tools": "tools", END: END}와 다르게 END를 아예 안 씀 —
    # 이 조건부 엣지의 두 갈래(coach_tools, finalize_coach) 다 실제 노드로 가지 END로 직접 가는 길이 없음
    workflow.add_edge("coach_tools", "coach_call_model")
    # 이 고정 엣지가 루프를 만듦 (gap_agent의 tools→call_model과 동일한 역할)
    workflow.add_edge("finalize_coach", END)
    # 그래프가 끝나는 유일한 경로 — 반드시 finalize_coach를 거쳐야 END에 도달할 수 있음.
    # 즉 "루프가 끝나는 방식(도구 없음 / 상한 도달)과 상관없이, 결과 조립(finalize_coach)은 항상 실행된다"는
    # 것이 이 그래프 구조로 보장됨 — gap_agent가 "루프 종료 후 별도로 synthesizer를 이어붙여야" 했던 것과
    # 달리, coach_agent는 자기 완결적으로 "루프 종료 = 결과 완성"까지 한 서브그래프 안에서 끝남

    return workflow.compile()
