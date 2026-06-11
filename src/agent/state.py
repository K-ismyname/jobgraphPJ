# LangGraph 에이전트 공유 상태 정의 — 단일 AppState로 통합
from __future__ import annotations

from typing import Annotated

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

# 무한 루프 방지 상수
MAX_ITERATIONS = 5
COACH_MAX_ITERATIONS = 3
MAX_REPLAN = 2


class AppState(TypedDict):
    """Supervisor 전체 플로우의 단일 공유 상태.

    Resume → Gap 루프 → GitHub → Coach 모든 노드가 이 상태를 읽고 쓴다.
    이전의 AgentState(단일 에이전트 전용)는 이 TypedDict에 병합되었다.
    """
    # ── Supervisor 입력 ──────────────────────────────────────────
    job_family: str
    owner: str
    pdf_path: str | None
    github_url: str | None

    # ── Resume Agent ─────────────────────────────────────────────
    resume_skills: list[str]
    resume_text: str | None

    # ── Gap 분석 루프 ─────────────────────────────────────────────
    messages: Annotated[list[BaseMessage], add_messages]
    iteration: int
    seen_source_ids: list[str]

    # ── Coach 루프 (Gap 루프와 히스토리 분리) ─────────────────────
    coach_messages: Annotated[list[BaseMessage], add_messages]
    coach_iteration: int

    # ── 각 에이전트 결과 ──────────────────────────────────────────
    skill_trends: dict | None        # {"LangGraph": {"recent": 42, "delta_pct": 50.0}}
    gap_result: dict | None
    github_result: dict | None
    coaching_result: dict | None
    final_report: dict | None

    # ── Plan-and-Execute (멀티 에이전트 코어) ──
    plan: dict | None
    replan_count: int

    # ── Executor 산출 (병렬 노드가 각자 채움) ──
    profile_result: dict | None
    retrieved_context: list[dict]
    market_result: dict | None

    # ── Critic 검증 ──
    critic_report: dict | None

    # ── v3: 다중 소스 평가 ──
    resume_eval: dict | None     # {"skills": [{skill, evidence, source, level_hint}]}
    github_eval: dict | None
    consensus: dict | None       # {skill: {verification, evidences, flags?}}
    fit_result: dict | None      # 적합도 + 신뢰도 (Gap 산출)
