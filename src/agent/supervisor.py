# v3 단계1 StateGraph — 평가자 병렬(이력서∥GitHub) → 합의 → Gap 루프 → Synthesizer → Critic → Coach
from __future__ import annotations

import json
import os
import uuid
from typing import TYPE_CHECKING, Callable

from langchain_core.messages import ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import tools_condition
from langgraph.types import Send

from src.agent.state import COACH_MAX_ITERATIONS, MAX_ITERATIONS, AppState
from src.evaluation.langfuse_tracer import langfuse_callbacks

if TYPE_CHECKING:
    from openai import OpenAI
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

            if tc["name"] == "verify_skills" and isinstance(result, dict):
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
    """v3 단계1: 평가자 병렬 → 합의 → Gap 적합도 → Critic → Coach."""
    from src.agent.tools import create_tools, create_coach_tools
    from src.agent.nodes import create_nodes, create_coach_nodes
    from src.agent.evaluators.resume_eval import create_resume_evaluator
    from src.agent.evaluators.github_eval import create_github_evaluator
    from src.agent.evaluators.portfolio_eval import create_portfolio_evaluator
    from src.agent.evaluators.deploy_eval import create_deploy_evaluator
    from src.agent.consensus import create_consensus_node
    from src.agent.critic import create_critic_node

    gap_tools = create_tools(neo4j)
    coach_tools = create_coach_tools(neo4j)
    call_model, generate_report = create_nodes(gap_tools, neo4j)
    coach_call_model, finalize_coach = create_coach_nodes(coach_tools)
    tools_node = _make_tools_node(gap_tools)
    coach_tools_node = _make_coach_tools_node(coach_tools)

    resume_eval = create_resume_evaluator(openai_client)
    github_eval = create_github_evaluator(neo4j, openai_client)
    portfolio_eval = create_portfolio_evaluator(openai_client)
    deploy_eval = create_deploy_evaluator(neo4j)
    consensus_node = create_consensus_node()
    critic_node = create_critic_node(openai_client)

    def route_gap_loop(state: AppState) -> str:
        if state.get("iteration", 0) >= MAX_ITERATIONS:
            return "synthesizer"
        routing = tools_condition(state)
        return "synthesizer" if routing == END else routing

    def route_coach_loop(state: AppState) -> str:
        if state.get("coach_iteration", 0) >= COACH_MAX_ITERATIONS:
            return "finalize_coach"
        last = (list(state.get("coach_messages") or [None]))[-1]
        if last and getattr(last, "tool_calls", None):
            return "coach_tools"
        return "finalize_coach"

    # 합의 결과(보유 스킬 + 검증상태)를 Gap 루프 진입 메시지로 시드
    def seed_gap(state: AppState) -> dict:
        from langchain_core.messages import HumanMessage
        consensus = state.get("consensus") or {}
        held = ", ".join(f"{s}({d['verification']})" for s, d in consensus.items()) or "없음"
        user_msg = (
            f"직무 '{state['job_family']}'에 대해 적합도 분석을 해주세요.\n"
            f"지원자: {state['owner']}\n"
            f"보유 스킬(검증상태 포함): {held}\n"
            f"각 스킬을 직무 요구 수준과 비교해 적합도와 갭을 산출하세요."
        )
        return {"messages": [HumanMessage(content=user_msg)], "iteration": 0, "seen_source_ids": []}

    workflow = StateGraph(AppState)
    workflow.add_node("resume_eval",      resume_eval)
    workflow.add_node("github_eval",      github_eval)
    workflow.add_node("portfolio_eval",   portfolio_eval)
    workflow.add_node("deploy_eval",      deploy_eval)
    workflow.add_node("consensus",        consensus_node)
    workflow.add_node("seed_gap",         seed_gap)
    workflow.add_node("call_model",       call_model)
    workflow.add_node("tools",            tools_node)
    workflow.add_node("synthesizer",      generate_report)   # gap_result + coach 시드 생성
    workflow.add_node("critic",           critic_node)
    workflow.add_node("coach_call_model", coach_call_model)
    workflow.add_node("coach_tools",      coach_tools_node)
    workflow.add_node("finalize_coach",   finalize_coach)

    # 평가자 병렬 fan-out → 합의 barrier
    workflow.add_conditional_edges(START, evaluator_dispatch,
                                   ["resume_eval", "github_eval", "portfolio_eval", "deploy_eval"])
    workflow.add_edge("resume_eval", "consensus")
    workflow.add_edge("github_eval", "consensus")
    workflow.add_edge("portfolio_eval", "consensus")
    workflow.add_edge("deploy_eval", "consensus")
    workflow.add_edge("consensus", "seed_gap")
    workflow.add_edge("seed_gap", "call_model")
    # Gap 루프
    workflow.add_conditional_edges("call_model", route_gap_loop,
                                   {"tools": "tools", "synthesizer": "synthesizer"})
    workflow.add_edge("tools", "call_model")
    # Synthesizer → Critic → Coach (재검색 루프 없음)
    # critic은 결정적 검증기: gap_result의 보유 스킬을 consensus와 대조해
    # 합의에 없는 환각 주장을 제거하고 verification 라벨을 교정한다(LLM·replan 없음).
    workflow.add_edge("synthesizer", "critic")
    workflow.add_edge("critic", "coach_call_model")
    # Coach 루프
    workflow.add_conditional_edges("coach_call_model", route_coach_loop,
                                   {"coach_tools": "coach_tools", "finalize_coach": "finalize_coach"})
    workflow.add_edge("coach_tools", "coach_call_model")
    workflow.add_edge("finalize_coach", END)

    return workflow.compile(checkpointer=MemorySaver())


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
        common_skills = neo4j.get_common_skills(threshold=5, n=10)
        final["common_skill_fit"] = skill_fit(names, common_skills, result.get("consensus") or {})
        final["recommended_families"] = recommend_families(neo4j, names, neo4j.list_job_families())[:3]
        verified_names = [
            s["skill"] for s in (result.get("consensus") or {}).get("skills", [])
            if s.get("verification") in ("Verified", "Corroborated")
        ]
        final["recommended_postings"] = neo4j.recommend_job_postings(verified_names or names)
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
