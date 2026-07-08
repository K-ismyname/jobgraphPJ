# Gap 분석 서브 에이전트 — ReAct 루프를 독립 CompiledGraph로 분리
#
# 이 파일이 하는 일: "call_model ↔ tools" ReAct 루프를 하나의 독립된 서브그래프로 조립한다.
# 실제 판단(LLM 호출)과 도구 실행 로직은 여기 없고 전부 nodes.py, tools.py에서 가져와 조립만 한다.
# 이 서브그래프는 리포트 생성(synthesizer)을 포함하지 않는다 — 그건 supervisor.py 레벨에서
# 이 서브그래프 실행이 끝난 뒤 별도로 이어붙는 노드다.

from __future__ import annotations

from typing import TYPE_CHECKING

from langgraph.graph import END, START, StateGraph
# START, END는 LangGraph가 미리 정의해둔 특수 노드 이름 — "그래프의 시작점", "그래프의 끝점"을 뜻하는 상수

from src.agent.state import GapState, MAX_ITERATIONS

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool


def create_gap_graph(gap_tools: list["BaseTool"]):
    """Gap ReAct 루프를 독립 서브그래프로 반환한다.

    Supervisor가 consensus 결과를 GapState로 변환해 넘기면,
    GapAgent가 Neo4j 툴로 갭을 분석하고 gap_result를 반환한다.
    """
    from src.agent.nodes import create_call_model, make_tools_node
    # 함수 안에서 import — nodes.py도 이 파일을 다시 참조할 가능성(순환 import)을 피하려는 관용적 방식

    call_model = create_call_model(gap_tools)
    # nodes.py의 팩토리 함수를 호출해서 실제 노드 함수(state를 받아 dict를 반환하는 함수)를 얻음.
    # 이 시점에 gap_tools가 LLM에 바인딩됨 (nodes.py의 bind_tools 호출 부분)
    tools_node = make_tools_node(gap_tools)
    # 같은 gap_tools 목록으로, 이번엔 "LLM이 요청한 도구를 실제로 실행하는" 노드 함수를 만듦

    def route_gap_loop(state: GapState) -> str:
        # 조건부 엣지 함수 — "다음에 어느 노드로 갈지"를 문자열로 반환. 반환값은 아래
        # add_conditional_edges에 등록된 매핑({"tools": "tools", END: END})에서 실제 노드로 해석됨
        if state.get("iteration", 0) >= MAX_ITERATIONS:
            return END
            # state.py에서 본 안전장치 상수 — 아무리 LLM이 계속 도구를 부르고 싶어해도
            # 5턴이 지나면 강제로 루프를 끊음 (무한 루프 방지)
        last = (list(state.get("messages") or [None]))[-1]
        # state.get("messages")가 None이거나 빈 리스트일 가능성을 방어하려고 "or [None]"으로
        # 최소 1개짜리 리스트를 보장한 뒤 마지막 원소([-1])를 꺼냄 — messages가 비어도 에러 없이 None을 얻음
        return "tools" if (last and getattr(last, "tool_calls", None)) else END
        # getattr(last, "tool_calls", None) → last 객체에 tool_calls라는 속성이 있으면 그 값을,
        # 없으면(속성 자체가 없는 경우까지 대비) None을 반환하는 안전한 속성 접근
        # last가 None이 아니고 tool_calls가 채워져 있으면(LLM이 도구를 부르고 싶어함) "tools"로,
        # 그게 아니면(텍스트로만 답했거나 메시지가 없음) END로

    workflow = StateGraph(GapState)
    # 지난번 state.py에서 배운 그 메커니즘 — GapState를 넘겨야 LangGraph가 "messages는 add_messages로
    # 병합하라"는 규칙표를 만들 수 있음. 이 인자가 없으면 이 줄 자체가 정상 동작하지 않음
    workflow.add_node("call_model", call_model)
    workflow.add_node("tools",      tools_node)
    # add_node("이름", 함수) — 그래프에 노드를 등록. 문자열 이름이 나중에 엣지를 연결할 때 참조하는 식별자

    workflow.add_edge(START, "call_model")
    # 그래프가 시작되면 무조건 call_model부터 실행 — 고정 엣지(조건 없음)
    workflow.add_conditional_edges("call_model", route_gap_loop,
                                   {"tools": "tools", END: END})
    # add_conditional_edges(노드이름, 판단함수, 매핑) —
    # "call_model 노드가 끝나면, route_gap_loop 함수를 실행해서 그 반환값으로 다음 노드를 결정해라.
    #  반환값이 'tools'면 tools 노드로, END면 그래프를 끝내라"는 뜻
    workflow.add_edge("tools", "call_model")
    # tools 노드가 끝나면 무조건 다시 call_model로 — 이 고정 엣지가 "루프"를 만드는 부분.
    # (tools → call_model → route_gap_loop 판단 → 다시 tools 또는 END, 이 과정이 반복됨)

    return workflow.compile()
    # .compile() — 지금까지 add_node/add_edge로 그린 그래프 설계도를 실제로 실행 가능한
    # CompiledGraph 객체로 변환. 이 반환값이 supervisor.py에서 서브그래프 노드로 등록되어 쓰일 것
