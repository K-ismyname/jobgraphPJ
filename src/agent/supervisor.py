# 단일 평면 StateGraph — Resume → [GitHub →] Gap 루프 → Supervisor 판단 → Coach 루프
from __future__ import annotations

import json
import os
import uuid
from typing import TYPE_CHECKING

from langchain_core.messages import ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import tools_condition

from src.agent.state import COACH_MAX_ITERATIONS, MAX_ITERATIONS, AppState

if TYPE_CHECKING:
    from openai import OpenAI
    from src.storage.chroma_client import ChromaClient
    from src.storage.neo4j_client import Neo4jClient


def _make_tools_node(tools_list: list):
    """Gap Agent용 커스텀 tools 노드 — source_id dedup 포함."""
    tool_map = {t.name: t for t in tools_list}

    def tools_node(state: AppState) -> dict:
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

            if tc["name"] == "vector_search" and isinstance(result, list):
                if not any(r.get("skip") for r in result):
                    fresh = [r for r in result if r.get("source_id") not in seen]
                    new_seen.update(r["source_id"] for r in fresh if "source_id" in r)
                    result = fresh or [{"note": "이미 확인한 공고들입니다. 다음 스킬로 넘어가세요.", "skip": True}]

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
                result if isinstance(result, str)
                else json.dumps(result, ensure_ascii=False)
            )
            new_messages.append(ToolMessage(
                content=content,
                tool_call_id=tc["id"],
                name=tc["name"],
            ))

        return {"messages": new_messages, "seen_source_ids": list(new_seen)}

    return tools_node


def _make_coach_tools_node(coach_tools_list: list):
    """Coach Agent용 tools 노드 — coach_messages에 결과를 추가한다."""
    tool_map = {t.name: t for t in coach_tools_list}

    def coach_tools_node(state: AppState) -> dict:
        last_msg = list(state.get("coach_messages") or [])[-1]
        new_messages: list[ToolMessage] = []

        for tc in last_msg.tool_calls:
            fn = tool_map[tc["name"]]
            try:
                result = fn.invoke(tc["args"])
            except Exception as e:
                result = {"error": str(e)}

            content = (
                result if isinstance(result, str)
                else json.dumps(result, ensure_ascii=False)
            )
            new_messages.append(ToolMessage(
                content=content,
                tool_call_id=tc["id"],
                name=tc["name"],
            ))

        return {"coach_messages": new_messages}

    return coach_tools_node


def create_supervisor_graph(
    neo4j: "Neo4jClient",
    chroma: "ChromaClient",
    openai_client: "OpenAI",
):
    """단일 평면 StateGraph를 생성한다.

    구조:
      START → resume → [github_url?] → github → call_model (Gap 루프)
                                     → call_model (Gap 루프)
      Gap 루프: call_model ↔ tools → generate
      Supervisor 판단: match_rate ≥ 80% → END, 그 외 → Coach 루프
      Coach 루프: coach_call_model ↔ coach_tools → finalize_coach → END

    GitHub이 항상 Gap 분석 전에 실행되므로, gap_analysis 툴이 Neo4j에서
    최신 confidence를 조회할 때 GitHub 업데이트가 반영되어 있다.
    """
    from src.agent.tools import create_tools, create_coach_tools
    from src.agent.nodes import create_nodes, create_coach_nodes
    from src.agent.resume_agent import create_resume_node
    from src.agent.github_agent import create_github_node

    gap_tools = create_tools(neo4j, chroma)
    coach_tools = create_coach_tools(chroma)

    call_model, generate_report = create_nodes(gap_tools, neo4j, chroma)
    coach_call_model, finalize_coach = create_coach_nodes(coach_tools)

    tools_node = _make_tools_node(gap_tools)
    coach_tools_node = _make_coach_tools_node(coach_tools)

    resume_node = create_resume_node(neo4j, openai_client)
    github_node = create_github_node(neo4j)

    # ── 라우팅 함수 ──────────────────────────────────────────────

    def route_after_resume(state: AppState) -> str:
        """GitHub URL이 있으면 GitHub을 먼저 실행 → confidence 업데이트 후 Gap 분석."""
        return "github" if state.get("github_url") else "call_model"

    def route_gap_loop(state: AppState) -> str:
        """Gap 루프 상한(5회) 초과 시 generate로 강제 이동."""
        if state.get("iteration", 0) >= MAX_ITERATIONS:
            return "generate"
        routing = tools_condition(state)
        return "generate" if routing == END else routing

    def route_after_generate(state: AppState) -> str:
        """Supervisor 중간 판단 — match_rate 기반으로 코칭 필요 여부 결정."""
        gap = state.get("gap_result") or {}
        match_rate = gap.get("match_rate", 0.0)
        if match_rate >= 0.8:
            print(f"[supervisor] match_rate={match_rate:.0%} ≥ 80% → 코칭 불필요, 바로 종료")
            return "__end__"
        return "coach_call_model"

    def route_coach_loop(state: AppState) -> str:
        """Coach 루프 상한(3회) 초과 또는 도구 호출 없으면 finalize_coach로."""
        if state.get("coach_iteration", 0) >= COACH_MAX_ITERATIONS:
            return "finalize_coach"
        last = (list(state.get("coach_messages") or [None]))[-1]
        if last and getattr(last, "tool_calls", None):
            return "coach_tools"
        return "finalize_coach"

    # ── 그래프 조립 ──────────────────────────────────────────────
    workflow = StateGraph(AppState)

    workflow.add_node("resume",           resume_node)
    workflow.add_node("github",           github_node)
    workflow.add_node("call_model",       call_model)
    workflow.add_node("tools",            tools_node)
    workflow.add_node("generate",         generate_report)
    workflow.add_node("coach_call_model", coach_call_model)
    workflow.add_node("coach_tools",      coach_tools_node)
    workflow.add_node("finalize_coach",   finalize_coach)

    workflow.add_edge(START, "resume")
    workflow.add_conditional_edges(
        "resume",
        route_after_resume,
        {"github": "github", "call_model": "call_model"},
    )
    workflow.add_edge("github", "call_model")
    workflow.add_conditional_edges(
        "call_model",
        route_gap_loop,
        {"tools": "tools", "generate": "generate"},
    )
    workflow.add_edge("tools", "call_model")
    workflow.add_conditional_edges(
        "generate",
        route_after_generate,
        {"coach_call_model": "coach_call_model", "__end__": END},
    )
    workflow.add_conditional_edges(
        "coach_call_model",
        route_coach_loop,
        {"coach_tools": "coach_tools", "finalize_coach": "finalize_coach"},
    )
    workflow.add_edge("coach_tools", "coach_call_model")
    workflow.add_edge("finalize_coach", END)

    return workflow.compile(checkpointer=MemorySaver())


def run_supervisor(
    graph,
    job_family: str,
    owner: str,
    pdf_path: str | None = None,
    resume_text: str | None = None,
    github_url: str | None = None,
    resume_skills: list[str] | None = None,
) -> dict:
    """Supervisor 그래프를 실행하고 final_report를 반환한다.

    입력 우선순위 (resume_agent.py 기준):
      1. resume_skills 주입 (RAGAS eval용)
      2. pdf_path — PDF 파싱 후 스킬 추출
      3. resume_text — 텍스트 직접 입력 후 스킬 추출
      4. 없음 — Neo4j 기존 포트폴리오 로드
    """
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    initial: AppState = {
        "job_family": job_family,
        "owner": owner,
        "pdf_path": pdf_path,
        "github_url": github_url,
        "resume_skills": resume_skills or [],
        "resume_text": resume_text,
        "messages": [],
        "iteration": 0,
        "seen_source_ids": [],
        "coach_messages": [],
        "coach_iteration": 0,
        "skill_trends": None,
        "gap_result": None,
        "github_result": None,
        "coaching_result": None,
        "final_report": None,
    }
    result = graph.invoke(initial, config)
    return result.get("final_report") or {}


def run_analysis(
    graph,
    job_title: str,
    owner: str,
    portfolio_skills: list[str] | None = None,
    github_username: str | None = None,
    thread_id: str | None = None,
    return_state: bool = False,
) -> "dict | tuple[dict, list]":
    """갭 분석을 실행한다. RAGAS eval 및 단독 실행용 헬퍼."""
    config = {"configurable": {"thread_id": thread_id or str(uuid.uuid4())}}
    initial: AppState = {
        "job_family": job_title,
        "owner": owner,
        "pdf_path": None,
        "github_url": None,
        "resume_skills": portfolio_skills or [],
        "resume_text": None,
        "messages": [],
        "iteration": 0,
        "seen_source_ids": [],
        "coach_messages": [],
        "coach_iteration": 0,
        "skill_trends": None,
        "gap_result": None,
        "github_result": None,
        "coaching_result": None,
        "final_report": None,
    }
    result = graph.invoke(initial, config)
    gap_result = result.get("gap_result") or {}
    if return_state:
        return gap_result, result.get("messages", [])
    return gap_result


# ── CLI 실행 ────────────────────────────────────────────────────
if __name__ == "__main__":
    from dotenv import load_dotenv
    from openai import OpenAI

    load_dotenv()

    from src.storage.chroma_client import ChromaClient
    from src.storage.neo4j_client import Neo4jClient

    neo4j = Neo4jClient()
    chroma = ChromaClient()
    openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    graph = create_supervisor_graph(neo4j, chroma, openai_client)

    g = graph.get_graph()
    print("=== 노드 ===")
    print(list(g.nodes.keys()))
    print("\n=== 엣지 ===")
    for e in g.edges:
        print(f"  {e.source} → {e.target}")

    print("\n=== Supervisor 실행 ===")
    report = run_supervisor(graph, job_family="AI/LLM Engineer", owner="김지원")

    import json as _json
    print("\n=== 최종 리포트 ===")
    print(_json.dumps(report, ensure_ascii=False, indent=2)[:2000])

    neo4j.close()
