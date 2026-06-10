# Plan-and-Execute StateGraph — Planner → Executor(병렬) → Gap 루프 → Synthesizer → Critic → Replan/Coach
from __future__ import annotations

import json
import os
import uuid
from typing import TYPE_CHECKING

from langchain_core.messages import ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import tools_condition
from langgraph.types import Send

from src.agent.state import COACH_MAX_ITERATIONS, MAX_ITERATIONS, MAX_REPLAN, AppState

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


# Plan의 병렬 가능 step(profile/retrieval/market)만 Send로 펼친다. gap은 의존성 때문에 제외.
_PARALLEL_AGENTS = ("profile", "retrieval", "market")


def executor_dispatch(state: AppState) -> list:
    """Plan에 포함된 병렬 가능 agent를 Send로 fan-out한다."""
    plan = state.get("plan") or {}
    steps = plan.get("steps") or []
    present = [s["agent"] for s in steps if s["agent"] in _PARALLEL_AGENTS]
    if not present:
        # 불변식: 최소 retrieval은 항상 실행한다(빈 fan-out으로 그래프가 무성 정지하는 것 방지).
        present = ["retrieval"]
    return [Send(agent, state) for agent in present]


def route_after_critic(state: AppState) -> str:
    """Critic 판정으로 재계획(planner) 또는 코칭(coach_call_model)으로 분기.

    상한 체크는 critic_node의 decide_replan이 이미 needs_replan에 반영했으므로,
    여기서는 needs_replan만 보고 분기한다(이중 카운트 방지).
    """
    report = state.get("critic_report") or {}
    if report.get("needs_replan"):
        print(f"[critic] 재계획 (replan_count={state.get('replan_count', 0)})")
        return "planner"
    return "coach_call_model"


def create_supervisor_graph(neo4j, chroma, openai_client):
    """Plan-and-Execute + Critic 그래프.

    START → planner → (Send)[profile ∥ retrieval ∥ market] → seed_gap → call_model↔tools
          → synthesizer → critic → (replan→planner | coach) → coach_loop → END
    """
    from src.agent.tools import create_tools, create_coach_tools
    from src.agent.nodes import create_nodes, create_coach_nodes
    from src.agent.planner import create_planner_node
    from src.agent.profile_agent import create_profile_node
    from src.agent.retrieval_agent import create_retrieval_node
    from src.agent.market_agent import create_market_node
    from src.agent.critic import create_critic_node

    gap_tools = create_tools(neo4j, chroma)
    coach_tools = create_coach_tools(chroma)
    call_model, generate_report = create_nodes(gap_tools, neo4j, chroma)
    coach_call_model, finalize_coach = create_coach_nodes(coach_tools)
    tools_node = _make_tools_node(gap_tools)
    coach_tools_node = _make_coach_tools_node(coach_tools)

    planner_node = create_planner_node(openai_client)
    profile_node = create_profile_node(neo4j, openai_client)
    retrieval_node = create_retrieval_node(neo4j, chroma)
    market_node = create_market_node(neo4j)
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

    # gap 루프 진입 전 messages 시드(기존 resume_node가 하던 역할)
    def seed_gap(state: AppState) -> dict:
        from langchain_core.messages import HumanMessage
        skills = state.get("resume_skills") or []
        skills_str = ", ".join(skills) if skills else "없음 (공고 데이터만 사용)"
        user_msg = (
            f"직무 '{state['job_family']}'에 대해 갭 분석을 해주세요.\n"
            f"지원자 이름: {state['owner']}\n보유 스킬: {skills_str}"
        )
        return {"messages": [HumanMessage(content=user_msg)], "iteration": 0, "seen_source_ids": []}

    workflow = StateGraph(AppState)
    workflow.add_node("planner",          planner_node)
    workflow.add_node("profile",          profile_node)
    workflow.add_node("retrieval",        retrieval_node)
    workflow.add_node("market",           market_node)
    workflow.add_node("seed_gap",         seed_gap)
    workflow.add_node("call_model",       call_model)
    workflow.add_node("tools",            tools_node)
    workflow.add_node("synthesizer",      generate_report)   # gap_result + coach 시드 생성
    workflow.add_node("critic",           critic_node)
    workflow.add_node("coach_call_model", coach_call_model)
    workflow.add_node("coach_tools",      coach_tools_node)
    workflow.add_node("finalize_coach",   finalize_coach)

    workflow.add_edge(START, "planner")
    # Executor: planner 이후 병렬 fan-out
    workflow.add_conditional_edges("planner", executor_dispatch,
                                   ["profile", "retrieval", "market"])
    # 병렬 노드는 모두 seed_gap으로 모인다(barrier → reduce)
    workflow.add_edge("profile",   "seed_gap")
    workflow.add_edge("retrieval", "seed_gap")
    workflow.add_edge("market",    "seed_gap")
    # Gap 루프
    workflow.add_conditional_edges("call_model", route_gap_loop,
                                   {"tools": "tools", "synthesizer": "synthesizer"})
    workflow.add_edge("seed_gap", "call_model")
    workflow.add_edge("tools", "call_model")
    # Synthesizer → Critic
    workflow.add_edge("synthesizer", "critic")
    # Critic → replan(planner) | coach
    workflow.add_conditional_edges("critic", route_after_critic,
                                   {"planner": "planner", "coach_call_model": "coach_call_model"})
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
        "plan": None,
        "replan_count": 0,
        "profile_result": None,
        "retrieved_context": [],
        "market_result": None,
        "critic_report": None,
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
        "plan": None,
        "replan_count": 0,
        "profile_result": None,
        "retrieved_context": [],
        "market_result": None,
        "critic_report": None,
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
