# v3 단계1 StateGraph — 평가자 병렬(이력서∥GitHub) → 합의 → Gap 루프 → Synthesizer → Critic → Coach
from __future__ import annotations

import os
import uuid
from typing import TYPE_CHECKING, Callable

from langgraph.graph import END, START, StateGraph

from langgraph.types import Send

from src.agent.state import AppState
from src.evaluation.langfuse_tracer import langfuse_callbacks

if TYPE_CHECKING:
    from openai import OpenAI
    from src.storage.neo4j_client import Neo4jClient


def evaluator_dispatch(state: AppState) -> list[Send]:
    """입력에 있는 소스의 평가자만 Send로 fan-out."""
    sends = []
    if state.get("resume_skills") or state.get("pdf_path") or state.get("resume_text"):
        sends.append(Send("resume_eval", state))
    if state.get("github_urls"):
        sends.append(Send("github_eval", state))
    if state.get("portfolio_path"):
        sends.append(Send("portfolio_eval", state))
    if state.get("deploy_urls"):
        sends.append(Send("deploy_eval", state))
    if not sends:
        sends.append(Send("resume_eval", state))   # 최소 하나 보장
    return sends


def create_supervisor_graph(neo4j, openai_client):
    """Supervisor + 서브 에이전트: 평가자 병렬 → 합의 → GapAgent → Critic → CoachAgent."""
    from src.agent.tools import create_tools, create_coach_tools
    from src.agent.evaluators.resume_eval import create_resume_evaluator
    from src.agent.evaluators.github_eval import create_github_evaluator
    from src.agent.evaluators.portfolio_eval import create_portfolio_evaluator
    from src.agent.evaluators.deploy_eval import create_deploy_evaluator
    from src.agent.consensus import create_consensus_node
    from src.agent.critic import create_critic_node
    from src.agent.gap_agent import create_gap_graph
    from src.agent.coach_agent import create_coach_graph

    from src.agent.nodes import create_synthesizer

    gap_tools   = create_tools(neo4j)
    coach_tools = create_coach_tools(neo4j)

    # 서브 에이전트 — 독립 CompiledGraph
    gap_graph   = create_gap_graph(gap_tools)
    coach_graph = create_coach_graph(coach_tools)

    # synthesizer — AppState에서 실행해야 coach_messages가 AppState에 직접 반영됨 (툴 불필요)
    synthesizer = create_synthesizer()

    resume_eval    = create_resume_evaluator(openai_client)
    github_eval    = create_github_evaluator(neo4j, openai_client)
    portfolio_eval = create_portfolio_evaluator(openai_client)
    deploy_eval    = create_deploy_evaluator(neo4j)
    consensus_node = create_consensus_node()
    critic_node    = create_critic_node(openai_client)

    def seed_gap(state: AppState) -> dict:
        """consensus + github project_contexts를 GapAgent 진입 상태로 변환 — Supervisor → GapAgent 브릿지."""
        from langchain_core.messages import HumanMessage
        consensus = state.get("consensus") or {}
        held = ", ".join(f"{s}({d['verification']})" for s, d in consensus.items()) or "없음"
        user_msg = (
            f"직무 '{state['job_family']}'에 대해 적합도 분석을 해주세요.\n"
            f"지원자: {state['owner']}\n"
            f"보유 스킬(검증상태 포함): {held}\n"
            f"각 스킬을 직무 요구 수준과 비교해 적합도와 갭을 산출하세요."
        )
        project_contexts = (state.get("github_eval") or {}).get("project_contexts") or []
        return {
            "messages": [HumanMessage(content=user_msg)],
            "iteration": 0,
            "seen_source_ids": [],
            "project_contexts": project_contexts,  # GapAgent synthesizer가 읽음
        }

    workflow = StateGraph(AppState)
    workflow.add_node("resume_eval",   resume_eval)
    workflow.add_node("github_eval",   github_eval)
    workflow.add_node("portfolio_eval", portfolio_eval)
    workflow.add_node("deploy_eval",   deploy_eval)
    workflow.add_node("consensus",     consensus_node)
    workflow.add_node("seed_gap",      seed_gap)
    workflow.add_node("gap_agent",     gap_graph)    # ← GapAgent 서브그래프
    workflow.add_node("synthesizer",   synthesizer)  # ← AppState에서 실행 (coach_messages 초기화)
    workflow.add_node("critic",        critic_node)
    workflow.add_node("coach_agent",   coach_graph)  # ← CoachAgent 서브그래프

    # 평가자 병렬 fan-out → consensus barrier
    workflow.add_conditional_edges(START, evaluator_dispatch,
                                   ["resume_eval", "github_eval", "portfolio_eval", "deploy_eval"])
    workflow.add_edge("resume_eval",   "consensus")
    workflow.add_edge("github_eval",   "consensus")
    workflow.add_edge("portfolio_eval", "consensus")
    workflow.add_edge("deploy_eval",   "consensus")
    # Supervisor → GapAgent → synthesizer → Critic → CoachAgent
    workflow.add_edge("consensus",    "seed_gap")
    workflow.add_edge("seed_gap",     "gap_agent")    # GapAgent ReAct 루프
    workflow.add_edge("gap_agent",    "synthesizer")  # AppState에서 리포트 생성
    workflow.add_edge("synthesizer",  "critic")
    workflow.add_edge("critic",       "coach_agent")  # CoachAgent에 위임
    workflow.add_edge("coach_agent",  END)

    # 체크포인터 없이 컴파일 — 현재 HITL(interrupt→resume)을 라이브로 운영하지 않으므로
    # 재개용 상태 저장이 불필요하다. MemorySaver를 붙이면 실행마다 thread_id별 체크포인트가
    # 무한 누적(누수)되고 재개 경로가 없어 읽히지도 않는다. HITL을 켜려면(ask_human interrupt)
    # 이 지점에 checkpointer를 다시 붙이고 API resume 엔드포인트를 추가해야 한다.
    return workflow.compile()


def run_supervisor(
    graph,
    job_family: str,
    owner: str,
    pdf_path: str | None = None,
    resume_text: str | None = None,
    github_urls: list[str] | None = None,
    resume_skills: list[str] | None = None,
    portfolio_path: str | None = None,
    deploy_urls: list[str] | None = None,
    neo4j: "Neo4jClient | None" = None,
    progress_cb: "Callable[[str], None] | None" = None,
) -> dict:
    """Supervisor 그래프를 실행하고 final_report를 반환한다.

    입력 우선순위 (resume_agent.py 기준):
      1. resume_skills 주입 (RAGAS eval용)
      2. pdf_path — PDF 파싱 후 스킬 추출
      3. resume_text — 텍스트 직접 입력 후 스킬 추출
      4. 없음 — 입력 가드가 차단 (분석할 소스 없음)
    """
    # 입력 가드: 분석 재료가 하나도 없으면 그래프를 돌리지 않고 안내 반환
    if not (resume_skills or pdf_path or resume_text or github_urls or portfolio_path or deploy_urls):
        return {
            "error": "no_input",
            "message": "분석하려면 이력서 스킬·PDF·이력서 텍스트·GitHub 중 최소 하나가 필요합니다.",
        }

    # 직군 검증: 유효하지 않은 job_family면 그래프 실행 없이 안내 (LLM 환각 방지)
    if neo4j is not None:
        valid = neo4j.list_job_families()
        if valid and job_family not in valid:
            return {
                "error": "invalid_job_family",
                "message": f"유효하지 않은 직군 '{job_family}'. 가능: {', '.join(valid)}",
                "valid_job_families": valid,
            }

    config = {"configurable": {"thread_id": str(uuid.uuid4())}, "callbacks": langfuse_callbacks()}
    initial: AppState = {
        "job_family": job_family,
        "owner": owner,
        "pdf_path": pdf_path,
        "portfolio_path": portfolio_path,
        "deploy_urls": deploy_urls or [],
        "github_urls": github_urls or [],
        "resume_skills": resume_skills or [],
        "resume_text": resume_text,
        "messages": [],
        "iteration": 0,
        "seen_source_ids": [],
        "coach_messages": [],
        "coach_iteration": 0,
        "gap_result": None,
        "coaching_result": None,
        "final_report": None,
        "critic_report": None,
        "resume_eval": None, "github_eval": None, "portfolio_eval": None, "deploy_eval": None, "consensus": None,
        "gap_trace": None,
    }
    final_state: dict = dict(initial)
    for chunk in graph.stream(initial, config, stream_mode="updates"):
        if not isinstance(chunk, dict):
            continue
        for node, update in chunk.items():
            if progress_cb:
                progress_cb(node)
            if isinstance(update, dict):
                final_state.update(update)
    result = final_state
    final = result.get("final_report") or {}
    if neo4j and final and not final.get("error"):
        from src.analysis.capability import (
            job_family_core_skills, recommend_families, skill_fit,
        )
        owned: list[dict] = []
        for k in ("resume_eval", "github_eval", "portfolio_eval", "deploy_eval"):
            owned += (result.get(k) or {}).get("skills", [])
        names = [it["skill"] for it in owned if isinstance(it, dict) and it.get("skill")]
        core_skills = job_family_core_skills(neo4j, job_family, 10)
        final["capability_fit"] = {"job_family": job_family,
                                   **skill_fit(names, core_skills, result.get("consensus") or {})}
        # threshold=7: 9개 직군 중 7개 이상에 등장하는 스킬만 '공통'으로 — 5는 6직군이라
        # ML/AI 같은 데이터 직군 편향 스킬이 섞임(측정 확인). 7이면 범용 인프라 스킬만 남음.
        common_skills = neo4j.get_common_skills(threshold=7, n=10)
        final["common_skill_fit"] = skill_fit(names, common_skills, result.get("consensus") or {})
        final["recommended_families"] = recommend_families(neo4j, names, neo4j.list_job_families())[:3]
        verified_names = [
            s["skill"] for s in (result.get("consensus") or {}).get("skills", [])
            if s.get("verification") in ("Verified", "Corroborated")
        ]
        final["recommended_postings"] = neo4j.recommend_job_postings(
            verified_names or names, job_family=job_family)
    return final


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
    config = {"configurable": {"thread_id": thread_id or str(uuid.uuid4())}, "callbacks": langfuse_callbacks()}
    initial: AppState = {
        "job_family": job_title,
        "owner": owner,
        "pdf_path": None,
        "portfolio_path": None,
        "deploy_urls": [],
        "github_urls": [],
        "resume_skills": portfolio_skills or [],
        "resume_text": None,
        "messages": [],
        "iteration": 0,
        "seen_source_ids": [],
        "coach_messages": [],
        "coach_iteration": 0,
        "gap_result": None,
        "coaching_result": None,
        "final_report": None,
        "critic_report": None,
        "resume_eval": None, "github_eval": None, "portfolio_eval": None, "deploy_eval": None, "consensus": None,
        "gap_trace": None,
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

    from src.storage.neo4j_client import Neo4jClient

    neo4j = Neo4jClient()
    openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    graph = create_supervisor_graph(neo4j, openai_client)

    g = graph.get_graph()
    print("=== 노드 ===")
    print(list(g.nodes.keys()))
    print("\n=== 엣지 ===")
    for e in g.edges:
        print(f"  {e.source} → {e.target}")

    print("\n=== Supervisor 실행 ===")
    report = run_supervisor(graph, job_family="AI/LLM Engineer", owner="김지원", neo4j=neo4j)

    import json as _json
    print("\n=== 최종 리포트 ===")
    print(_json.dumps(report, ensure_ascii=False, indent=2)[:2000])

    neo4j.close()
