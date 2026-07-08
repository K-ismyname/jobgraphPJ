# v3 단계1 StateGraph — 평가자 병렬(이력서∥GitHub) → 합의 → Gap 루프 → Synthesizer → Critic → Coach
#
# 이 파일이 하는 일: Layer 3 전체를 하나의 실행 가능한 그래프로 조립하는 최상위 파일.
# pipeline.py가 Layer 1·2의 오케스트레이터였다면, 이 파일이 Layer 3의 오케스트레이터다.
# 지금까지 본 evaluators/, consensus.py, critic.py, gap_agent.py, (다음에 볼) coach_agent.py를
# 전부 가져다가 StateGraph 하나로 연결하고, 실행 진입점(run_supervisor, run_analysis)까지 제공한다.

from __future__ import annotations

import os
import uuid
from typing import TYPE_CHECKING, Callable

from langgraph.graph import END, START, StateGraph

from langgraph.types import Send
# Send — "이 노드를, 이런 상태로 실행해달라"는 지시를 표현하는 객체. 조건부 엣지 함수가
# 문자열 하나가 아니라 Send 객체의 리스트를 반환하면, 그 리스트에 담긴 노드들이 전부 병렬로 실행됨
# (지금까지 본 gap_agent.py의 route_gap_loop은 문자열 하나만 반환했는데, 여긴 리스트를 반환하는 게 다름)

from src.agent.state import AppState
from src.evaluation.langfuse_tracer import langfuse_callbacks
# 아직 안 본 evaluation/langfuse_tracer.py — CLAUDE.md의 "Langfuse + RAGAS 평가"에서 그 Langfuse 트레이싱

if TYPE_CHECKING:
    from openai import OpenAI
    from src.storage.neo4j_client import Neo4jClient


def evaluator_dispatch(state: AppState) -> list[Send]:
    """입력에 있는 소스의 평가자만 Send로 fan-out."""
    # 이 함수가 CLAUDE.md 그래프의 "dispatch: 입력에 있는 소스만 Send로 fan-out" 부분의 실제 구현.
    # 지난번 개념 설명 때 "결정적 코드, LLM 미사용"이라고 했던 그 판단이 바로 이 함수
    sends = []
    if state.get("resume_skills") or state.get("pdf_path") or state.get("resume_text"):
        sends.append(Send("resume_eval", state))
        # Send("노드이름", 전달할state) — "resume_eval 노드를 지금 이 state로 실행시켜라"는 지시.
        # 조건에 안 걸리면 이 노드용 Send가 아예 안 만들어지므로, 그 평가자는 이번 실행에서 아예 안 돎
    if state.get("github_urls"):
        sends.append(Send("github_eval", state))
    if state.get("portfolio_path"):
        sends.append(Send("portfolio_eval", state))
    if state.get("deploy_urls"):
        sends.append(Send("deploy_eval", state))
    if not sends:
        sends.append(Send("resume_eval", state))   # 최소 하나 보장
        # 사용자가 아무 입력도 안 줬으면(이례적 상황), 그래도 최소 하나는 실행되게 강제 —
        # 아래로 이어지는 그래프(consensus 등)가 "아무 평가자도 안 돌았다"는 완전히 빈 상태를
        # 다루지 않아도 되게 하는 안전장치. resume_eval은 입력이 없어도 "빈 결과" 처리가
        # 이미 돼 있으므로(resume_eval.py) 이 fallback이 안전함
    return sends
    # 이 리스트에 담긴 Send들이 전부 "동시에" 실행됨 — 이게 CLAUDE.md에서 말한 "병렬 fan-out"의 정체


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
    # 함수 안에서 이렇게 많은 import를 몰아서 하는 이유 — 이 프로젝트 전체 파일들이 서로를
    # (순환적으로) 참조할 가능성이 있어서, "그래프를 실제로 조립하는 시점"까지 import를 늦춰
    # 순환 import 문제를 피하려는 의도로 보임

    gap_tools   = create_tools(neo4j)
    coach_tools = create_coach_tools(neo4j)
    # tools.py의 두 팩토리 함수 — 여기서 딱 한 번 호출되어, neo4j를 캡처한 도구 리스트가 만들어짐

    # 서브 에이전트 — 독립 CompiledGraph
    gap_graph   = create_gap_graph(gap_tools)
    coach_graph = create_coach_graph(coach_tools)
    # gap_agent.py, coach_agent.py가 만드는 "이미 컴파일된" 서브그래프 객체 — 아래에서 이 자체를
    # 하나의 노드처럼 워크플로우에 등록함 (그래프 안에 그래프를 넣는 서브그래프 패턴)

    # synthesizer — AppState에서 실행해야 coach_messages가 AppState에 직접 반영됨
    synthesizer = create_synthesizer(neo4j)   # 결정적 reason 조립에 CO_OCCURS 조회 사용
    # 지난번 gap_agent.py 리뷰 때 "synthesizer는 gap_agent 서브그래프 밖, Supervisor 레벨에서 실행된다"고
    # 봤던 게 바로 여기서 확인됨 — synthesizer가 gap_graph 안이 아니라 이 최상위 workflow에 직접 등록될 예정

    resume_eval    = create_resume_evaluator(openai_client)
    github_eval    = create_github_evaluator(neo4j, openai_client)
    portfolio_eval = create_portfolio_evaluator(openai_client)
    deploy_eval    = create_deploy_evaluator(neo4j)
    consensus_node = create_consensus_node(neo4j)   # PART_OF 간접 실증 활성화
    critic_node    = create_critic_node(openai_client)
    # 지금까지 각각 따로 리뷰했던 8개 파일의 팩토리 함수들이 전부 여기 한자리에 모여 호출됨 —
    # 이 함수(create_supervisor_graph)가 정말로 "모든 부품을 조립하는 곳"이라는 게 실감나는 지점

    def seed_gap(state: AppState) -> dict:
        """consensus + github project_contexts를 GapAgent 진입 상태로 변환 — Supervisor → GapAgent 브릿지."""
        # CLAUDE.md 그래프의 "seed_gap" 노드 — consensus의 결과를 gap_agent가 이해할 수 있는
        # 첫 메시지(HumanMessage) 형태로 "번역"해주는 다리 역할. gap_agent 서브그래프 자신은
        # "지원자가 어떤 스킬을 검증받았는지"를 모르니, 이 노드가 그 정보를 자연어 메시지로 만들어 전달
        from langchain_core.messages import HumanMessage
        consensus = state.get("consensus") or {}
        held = ", ".join(f"{s}({d['verification']})" for s, d in consensus.items()) or "없음"
        # "React(Verified), Docker(Claimed), ..." 형태의 문자열로 요약 — consensus dict를
        # gap_agent의 LLM이 프롬프트로 읽을 수 있는 평문으로 변환
        user_msg = (
            f"직무 '{state['job_family']}'에 대해 적합도 분석을 해주세요.\n"
            f"지원자: {state['owner']}\n"
            f"보유 스킬(검증상태 포함): {held}\n"
            f"각 스킬을 직무 요구 수준과 비교해 적합도와 갭을 산출하세요."
        )
        project_contexts = (state.get("github_eval") or {}).get("project_contexts") or []
        return {
            "messages": [HumanMessage(content=user_msg)],
            # 이 메시지 하나가 gap_agent 서브그래프의 messages 리스트 첫 항목이 됨 —
            # gap_agent.py의 call_model이 첫 턴에 보게 되는 바로 그 입력
            "iteration": 0,
            "seen_source_ids": [],
            "project_contexts": project_contexts,  # GapAgent synthesizer가 읽음
        }
        # 이 반환값의 필드들(messages, iteration, seen_source_ids, project_contexts)이 정확히
        # state.py의 GapState 필드들과 일치 — Supervisor(AppState)에서 GapAgent(GapState)로
        # "넘어가는 다리"에서 실제로 필요한 최소한의 초기값을 채워주는 게 이 노드의 역할

    workflow = StateGraph(AppState)
    # 여기는 GapState/CoachState가 아니라 최상위 AppState를 씀 — 이 workflow가 Supervisor 전체 그래프이기 때문
    workflow.add_node("resume_eval",   resume_eval)
    workflow.add_node("github_eval",   github_eval)
    workflow.add_node("portfolio_eval", portfolio_eval)
    workflow.add_node("deploy_eval",   deploy_eval)
    workflow.add_node("consensus",     consensus_node)
    workflow.add_node("seed_gap",      seed_gap)
    workflow.add_node("gap_agent",     gap_graph)    # ← GapAgent 서브그래프
    # 컴파일된 서브그래프(gap_graph)를 마치 노드 함수인 것처럼 그대로 add_node에 넘길 수 있음 —
    # LangGraph는 CompiledGraph 객체도 노드로 등록 가능하게 지원함. 이게 "서브그래프 패턴"의 핵심 메커니즘
    workflow.add_node("synthesizer",   synthesizer)  # ← AppState에서 실행 (coach_messages 초기화)
    workflow.add_node("critic",        critic_node)
    workflow.add_node("coach_agent",   coach_graph)  # ← CoachAgent 서브그래프

    # 평가자 병렬 fan-out → consensus barrier
    workflow.add_conditional_edges(START, evaluator_dispatch,
                                   ["resume_eval", "github_eval", "portfolio_eval", "deploy_eval"])
    # add_conditional_edges의 세 번째 인자가 지금까지완 다르게 "리스트"임 — gap_agent.py에서 본
    # {"tools": "tools", END: END}라는 dict 매핑과 달리, evaluator_dispatch는 Send 객체의 리스트를
    # 반환하는 함수라서, 여기서는 "이 함수가 반환할 수 있는 노드 후보들"을 리스트로 미리 알려주는 형태
    workflow.add_edge("resume_eval",   "consensus")
    workflow.add_edge("github_eval",   "consensus")
    workflow.add_edge("portfolio_eval", "consensus")
    workflow.add_edge("deploy_eval",   "consensus")
    # 4개 평가자 모두 "consensus"로 가는 고정 엣지 — 이게 "barrier"(합류 지점)를 만듦.
    # 실제로 몇 개가 실행됐든(dispatch가 몇 개를 Send했든), 실행된 평가자들이 전부 끝나야만
    # LangGraph가 consensus 노드를 실행함 — 즉 "병렬로 갈라졌다가 다시 하나로 합류하는" 구조

    # Supervisor → GapAgent → synthesizer → Critic → CoachAgent
    workflow.add_edge("consensus",    "seed_gap")
    workflow.add_edge("seed_gap",     "gap_agent")    # GapAgent ReAct 루프
    workflow.add_edge("gap_agent",    "synthesizer")  # AppState에서 리포트 생성
    workflow.add_edge("synthesizer",  "critic")
    workflow.add_edge("critic",       "coach_agent")  # CoachAgent에 위임
    workflow.add_edge("coach_agent",  END)
    # 여기부터는 전부 고정 순서 — CLAUDE.md 그래프 다이어그램에 그려진 그 순서(consensus→seed_gap→
    # gap_agent→synthesizer→critic→coach_agent→END)가 코드로 정확히 한 줄씩 대응됨

    # 체크포인터 없이 컴파일 — 현재 HITL(interrupt→resume)을 라이브로 운영하지 않으므로
    # 재개용 상태 저장이 불필요하다. MemorySaver를 붙이면 실행마다 thread_id별 체크포인트가
    # 무한 누적(누수)되고 재개 경로가 없어 읽히지도 않는다. HITL을 켜려면(ask_human interrupt)
    # 이 지점에 checkpointer를 다시 붙이고 API resume 엔드포인트를 추가해야 한다.
    return workflow.compile()
    # tools.py의 ask_human()에서 본 그 HITL 설계 지점과 정확히 이어지는 설명 — interrupt가 실제로
    # 그래프를 멈췄다 재개하려면 "체크포인터"(중단 시점 상태 저장소)가 필요한데, 지금은 안 붙어있어서
    # HITL_ENABLED=true로 켜봤자 interrupt가 재개될 방법이 없다는 뜻


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
    # 이 함수가 실제로 API(아직 안 본 src/api/)가 호출할 것으로 예상되는 "그래프 실행 진입점"
    # 입력 가드: 분석 재료가 하나도 없으면 그래프를 돌리지 않고 안내 반환
    if not (resume_skills or pdf_path or resume_text or github_urls or portfolio_path or deploy_urls):
        return {
            "error": "no_input",
            "message": "분석하려면 이력서 스킬·PDF·이력서 텍스트·GitHub 중 최소 하나가 필요합니다.",
        }
        # 그래프를 아예 실행하지 않고 여기서 조기 반환 — evaluator_dispatch의 "최소 하나 보장" fallback과
        # 별개로, "애초에 사용자가 아무것도 안 줬으면 비용 들여 그래프를 돌릴 필요조차 없다"는 앞단 방어

    # 직군 검증: 유효하지 않은 job_family면 그래프 실행 없이 안내 (LLM 환각 방지)
    if neo4j is not None:
        valid = neo4j.list_job_families()
        # neo4j_client.py에서 본 그 메서드 — Neo4j에 실제로 등록된 직군명 목록을 조회
        if valid and job_family not in valid:
            return {
                "error": "invalid_job_family",
                "message": f"유효하지 않은 직군 '{job_family}'. 가능: {', '.join(valid)}",
                "valid_job_families": valid,
            }
            # 오타난 직군명("AI/LLM Enginner" 등)을 그대로 그래프에 흘려보내면, gap_analysis 도구가
            # Neo4j에서 아무 결과도 못 찾고, LLM이 그 상황에서 뭔가 그럴듯한 걸 지어낼 위험이 있음 —
            # 그래서 그래프 실행 전에 미리 걸러내는 "환각 방지" 조치

    config = {"configurable": {"thread_id": str(uuid.uuid4())}, "callbacks": langfuse_callbacks()}
    # thread_id — LangGraph가 이 실행을 식별하는 고유 ID (uuid로 매번 새로 생성 = 매번 독립된 새 실행).
    # 체크포인터가 없어서 이 thread_id로 나중에 재개할 방법은 없지만, 형식상 필수로 넘겨야 하는 값
    # callbacks — langfuse_callbacks()가 반환하는, 이 실행 과정을 Langfuse로 트레이싱하는 콜백들
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
    # AppState의 모든 필드를 여기서 명시적으로 초기화 — TypedDict는 pydantic과 달리 "필드 기본값"을
    # 자동으로 채워주지 않으므로, 그래프 실행 전에 이렇게 전부 초기값을 채운 dict를 직접 만들어야 함
    final_state: dict = dict(initial)
    for chunk in graph.stream(initial, config, stream_mode="updates"):
        # graph.invoke()(gap_agent.py 관련 다른 곳에서 볼 수 있듯 결과를 한 번에 받는 방식)와 달리,
        # .stream()은 그래프가 진행되는 "과정"을 노드 하나 끝날 때마다 조금씩(chunk) 받을 수 있게 해줌.
        # stream_mode="updates" → 각 chunk가 "이번에 어느 노드가 실행됐고, 무엇이 바뀌었는지"만 담음
        # (전체 state를 매번 다 주는 게 아니라 "업데이트분만" — 그래서 이름이 updates)
        if not isinstance(chunk, dict):
            continue
        for node, update in chunk.items():
            # chunk는 {"노드이름": {바뀐필드들}} 형태 — 병렬 노드가 동시에 끝나면 여러 키가 한 chunk에 있을 수 있음
            if progress_cb:
                progress_cb(node)
                # 호출한 쪽(아마 API 레이어)이 "지금 어느 노드가 실행 중/완료됐는지"를 실시간으로
                # 알림받고 싶으면 이 콜백 함수를 넘길 수 있음 — 프론트엔드 진행 상황 표시에 쓰일 것으로 추정
            if isinstance(update, dict):
                final_state.update(update)
                # dict.update() — 매 chunk마다 바뀐 필드들을 final_state에 계속 누적 병합.
                # 그래프가 끝날 때쯤엔 final_state가 최종 완성된 전체 state와 같아짐
    result = final_state
    final = result.get("final_report") or {}
    if neo4j and final and not final.get("error"):
        # 그래프 실행이 성공적으로 final_report를 만들었을 때만, 아래에서 추가 분석을 더 붙임
        from src.analysis.capability import (
            job_family_core_skills, recommend_families, skill_fit,
        )
        # 아직 안 본 src/analysis/capability.py — CLAUDE.md Layer 4(분석)의 핵심 파일, 다음 리뷰 후보
        owned: list[dict] = []
        for k in ("resume_eval", "github_eval", "portfolio_eval", "deploy_eval"):
            owned += (result.get(k) or {}).get("skills", [])
        names = [it["skill"] for it in owned if isinstance(it, dict) and it.get("skill")]
        # 4개 평가자가 각각 찾아낸 스킬을 전부 합쳐서(중복 제거 없이) 이름만 뽑음 —
        # consensus.py의 정교한 중복 제거·정규화와 달리, 여기는 단순 취합
        core_skills = job_family_core_skills(neo4j, job_family, 10)
        final["capability_fit"] = {"job_family": job_family,
                                   **skill_fit(names, core_skills, result.get("consensus") or {})}
        # threshold=7: 9개 직군 중 7개 이상에 등장하는 스킬만 '공통'으로 — 5는 6직군이라
        # ML/AI 같은 데이터 직군 편향 스킬이 섞임(측정 확인). 7이면 범용 인프라 스킬만 남음.
        common_skills = neo4j.get_common_skills(threshold=7, n=10)
        # 메모리 기록(6/30 "Common Skills Threshold Raised from 5 to 7")과 정확히 일치하는 부분 —
        # 실제로 threshold를 바꿔가며 측정해서 최종값(7)을 정한 튜닝 이력이 주석에 남아있음
        final["common_skill_fit"] = skill_fit(names, common_skills, result.get("consensus") or {})
        final["recommended_families"] = recommend_families(neo4j, names, neo4j.list_job_families())[:3]
        # 지원한 직군 하나에 대한 분석 외에도, "이 스킬셋으로 다른 어느 직군에 더 잘 맞는지"까지 부가로 계산
        # consensus는 build_consensus()가 만든 {스킬명: {verification, evidences}} 형태의 dict라서
        # 딕셔너리를 직접 순회해야 함 (과거엔 .get("skills", [])를 호출해 항상 빈 리스트였던 버그가 있었음)
        consensus_dict = result.get("consensus") or {}
        verified_names = [
            skill for skill, info in consensus_dict.items()
            if (info or {}).get("verification") in ("Verified", "Corroborated")
        ]
        final["recommended_postings"] = neo4j.recommend_job_postings(
            verified_names or names, job_family=job_family)
            # verified_names가 비어있으면(검증된 스킬이 하나도 없으면) 전체 names로 fallback
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
    # run_supervisor()와 달리 이건 gap_result만 반환하는 더 가벼운 버전 — 함수 docstring대로
    # RAGAS(CLAUDE.md의 평가 파이프라인)가 이 함수를 호출해서 gap_result 품질을 채점하는 용도로 추정.
    # 이상한 점: 매개변수로 github_username을 받지만 아래 initial dict 어디서도 실제로 안 씀 (미사용 매개변수)
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
    # 여기는 .stream() 대신 .invoke() — 중간 진행 상황이 필요 없고, 최종 결과만 한 번에 받으면 되는
    # 단독 실행/평가 용도라서 더 단순한 API를 씀
    gap_result = result.get("gap_result") or {}
    if return_state:
        return gap_result, result.get("messages", [])
        # return_state=True면 gap_result뿐 아니라 gap_agent 루프의 전체 대화 기록(messages)도 함께 반환 —
        # RAGAS 평가가 "어떤 과정을 거쳐 이 답이 나왔는지"까지 봐야 할 때 쓰는 옵션으로 추정
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
    # .get_graph() — 컴파일된 그래프의 구조(노드·엣지 목록)를 조회용 객체로 꺼냄. 그래프를 실제로
    # 실행하지 않고도 "이 그래프가 어떻게 생겼는지"를 확인할 수 있는 디버깅/문서화용 API
    print("=== 노드 ===")
    print(list(g.nodes.keys()))
    print("\n=== 엣지 ===")
    for e in g.edges:
        print(f"  {e.source} → {e.target}")
        # 이 CLI를 그냥 실행해보면 우리가 지금까지 말로 그려온 그래프 다이어그램이 실제로 코드에서
        # 뽑혀 콘솔에 출력됨 — "설계도가 코드와 일치하는지" 눈으로 바로 확인할 수 있는 좋은 디버깅 수단

    print("\n=== Supervisor 실행 ===")
    report = run_supervisor(graph, job_family="AI/LLM Engineer", owner="김지원", neo4j=neo4j)
    # 이 파일을 직접 실행하면 실제로 예시 지원자("김지원")로 전체 파이프라인을 한 번 돌려봄 —
    # 로컬 개발/디버깅 시 "이 그래프가 진짜로 작동하는지"를 빠르게 확인하는 스모크 테스트 역할

    import json as _json
    print("\n=== 최종 리포트 ===")
    print(_json.dumps(report, ensure_ascii=False, indent=2)[:2000])
    # 리포트가 매우 길 수 있어서 앞 2000자까지만 잘라 출력 — 콘솔이 로그로 도배되는 걸 방지

    neo4j.close()
    # pipeline.py의 step_ingest()와 같은 습관 — 프로그램이 끝나기 전에 DB 연결을 명시적으로 정리
