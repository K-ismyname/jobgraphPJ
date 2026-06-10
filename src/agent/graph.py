# LangGraph StateGraph 조립 — Corrective RAG + HITL
from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING

from langchain_core.messages import ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import tools_condition

from src.agent.nodes import create_nodes
from src.agent.state import MAX_ITERATIONS, AgentState
from src.agent.tools import create_tools

if TYPE_CHECKING:
    from src.storage.chroma_client import ChromaClient
    from src.storage.neo4j_client import Neo4jClient


def _make_tools_node(tools_list: list):
    """커스텀 tools 노드 — vector_search 결과에서 이미 인용한 source_id를 dedup한다.

    빈 결과거나 dedup 후 남은 결과가 없으면 skip 메시지를 반환해
    LLM이 불필요한 iteration을 쓰지 않도록 한다.
    """
    tool_map = {t.name: t for t in tools_list}

    def tools_node(state: AgentState) -> dict:
        last_msg = state["messages"][-1]
        seen: set[str] = set(state.get("seen_source_ids") or [])
        new_seen: set[str] = set(seen)
        new_messages: list[ToolMessage] = []

        for tc in last_msg.tool_calls:
            fn = tool_map[tc["name"]]
            try:
                result = fn.invoke(tc["args"])
            except Exception as e:
                result = [{"error": str(e)}]

            # vector_search: dedup by source_id
            if tc["name"] == "vector_search" and isinstance(result, list):
                if not any(r.get("skip") for r in result):
                    fresh = [r for r in result if r.get("source_id") not in seen]
                    new_seen.update(r["source_id"] for r in fresh if "source_id" in r)
                    result = fresh or [{"note": "이미 확인한 공고들입니다. 다음 스킬로 넘어가세요.", "skip": True}]

            # verify_skills: 스킬별 evidence에서 dedup
            elif tc["name"] == "verify_skills" and isinstance(result, dict):
                for skill_data in result.values():
                    if not isinstance(skill_data, dict):
                        continue
                    evidence = skill_data.get("evidence", [])
                    if not isinstance(evidence, list):
                        continue
                    fresh = [e for e in evidence if e.get("source_id") not in seen]
                    new_seen.update(e["source_id"] for e in fresh if "source_id" in e)
                    skill_data["evidence"] = fresh

            content = (
                result
                if isinstance(result, str)
                else json.dumps(result, ensure_ascii=False)
            )
            new_messages.append(ToolMessage(
                content=content,
                tool_call_id=tc["id"],
                name=tc["name"],
            ))

        return {"messages": new_messages, "seen_source_ids": list(new_seen)}

    return tools_node


def create_graph(
    neo4j: "Neo4jClient",
    chroma: "ChromaClient",
):
    """
    StateGraph를 조립하고 컴파일된 그래프를 반환한다.

    흐름:
      START → call_model → (도구 호출 있음) → tools → call_model (루프)
                         → (도구 호출 없음 or MAX_ITERATIONS 초과) → generate → END

    HITL: ask_human 툴 내부에서 interrupt()를 호출해 일시정지.
          HITL_ENABLED=false이면 자동 패스 (백그라운드 태스크 모드).
    """
    tools = create_tools(neo4j, chroma)
    call_model, generate_report = create_nodes(tools, neo4j, chroma)
    tools_node = _make_tools_node(tools)

    # ── 조건부 라우팅 ─────────────────────────────────────────────
    def route_after_model(state: AgentState) -> str:
        """루프 상한 초과 시 강제로 generate, 그 외엔 tools_condition 위임."""
        if state.get("iteration", 0) >= MAX_ITERATIONS:
            return "generate"
        # tools_condition: 도구 호출 있으면 "tools", 없으면 END("__end__")
        routing = tools_condition(state)
        # END → generate 로 리매핑
        return "generate" if routing == END else routing

    # ── 그래프 조립 ───────────────────────────────────────────────
    workflow = StateGraph(AgentState)

    workflow.add_node("call_model",    call_model)
    workflow.add_node("tools",         tools_node)
    workflow.add_node("generate",      generate_report)

    workflow.add_edge(START,      "call_model")
    workflow.add_conditional_edges(
        "call_model",
        route_after_model,
        {"tools": "tools", "generate": "generate"},
    )
    workflow.add_edge("tools",    "call_model")
    workflow.add_edge("generate", END)

    # MemorySaver: HITL interrupt/resume에 필수
    return workflow.compile(checkpointer=MemorySaver())


def run_analysis(
    graph,
    job_title: str,
    owner: str,
    portfolio_skills: list[str] | None = None,
    github_username: str | None = None,
    thread_id: str | None = None,
) -> dict:
    """그래프를 실행하고 final_report를 반환한다.

    HITL가 발생하면 Interrupt 예외를 그대로 올린다.
    호출자가 Command(resume=answer)로 재개할 수 있다.
    """
    config = {"configurable": {"thread_id": thread_id or str(uuid.uuid4())}}

    skills_str = ", ".join(portfolio_skills) if portfolio_skills else "없음 (Neo4j 포트폴리오 사용)"
    user_msg = (
        f"직무 '{job_title}'에 대해 갭 분석을 해주세요.\n"
        f"지원자 이름: {owner}\n"
        f"보유 스킬: {skills_str}"
    )
    if github_username:
        user_msg += f"\nGitHub: {github_username}"

    initial: AgentState = {
        "job_title": job_title,
        "owner": owner,
        "messages": [{"role": "user", "content": user_msg}],
        "iteration": 0,
        "seen_source_ids": [],
        "final_report": None,
    }

    result = graph.invoke(initial, config)
    return result.get("final_report") or {}


# ── CLI 실행 ──────────────────────────────────────────────────────
if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()

    from src.storage.chroma_client import ChromaClient
    from src.storage.neo4j_client import Neo4jClient

    neo4j = Neo4jClient()
    chroma = ChromaClient()

    graph = create_graph(neo4j, chroma)

    # 그래프 구조 출력
    print("=== LangGraph 에이전트 구조 ===")
    print(graph.get_graph().draw_ascii())

    print("\n=== 분석 실행 ===")
    result = run_analysis(graph, job_title="AI Engineer", owner="김지원")
    if result.get("error"):
        print(f"오류: {result['error']}")
    elif result.get("gap_result"):
        gap = result["gap_result"]
        print(f"직무       : {gap.get('job_title')}")
        print(f"매칭률     : {gap.get('match_rate', 0):.0%}")
        print(f"보유 기술  : {len(gap.get('have', []))}개")
        print(f"부족 기술  : {len(gap.get('missing', []))}개")
    else:
        import json
        print(json.dumps(result, ensure_ascii=False, indent=2))

    neo4j.close()
