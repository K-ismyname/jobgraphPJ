# 입력을 보고 조사 계획(Plan)을 수립하는 Planner 노드 — Plan-and-Execute의 머리
from __future__ import annotations

import os
from typing import TYPE_CHECKING, Literal

from langchain_core.messages import RemoveMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from pydantic import BaseModel, Field

from src.agent.state import AppState

if TYPE_CHECKING:
    pass


class Step(BaseModel):
    agent: Literal["profile", "retrieval", "market", "gap"]
    goal: str = Field(description="이 step에서 알아내려는 것")


class Plan(BaseModel):
    steps: list[Step]
    reason: str = Field(description="왜 이 계획인지 한국어 1-2문장")


_PLANNER_PROMPT = """당신은 채용 갭 분석의 조사 계획을 세우는 Planner입니다.
아래 입력 상황과 '포함해야 할 조사 항목'을 보고, 각 항목의 goal과 전체 reason을 한국어로 작성하세요.

입력 상황:
{situation}

포함해야 할 조사 항목(agent): {agents}

규칙:
- steps의 agent는 위 '포함해야 할 조사 항목'과 정확히 일치해야 합니다(추가·삭제 금지).
- 각 step의 goal은 그 항목에서 무엇을 알아낼지 한 문장으로.
- reason은 왜 이 조사 구성인지 1-2문장."""


def build_skeleton_plan(state: AppState) -> list[dict]:
    """입력 조합·재계획 여부로 어떤 agent step을 포함할지 결정한다(결정적).

    - resume_skills 주입 또는 입력 없음 → profile 생략
    - pdf_path / resume_text / github_url 중 하나라도 있으면 → profile 포함
    - critic_report.needs_replan == True → retrieval+gap만(근거 보강 집중)
    """
    critic = state.get("critic_report") or {}
    if critic.get("needs_replan"):
        return [
            {"agent": "retrieval", "goal": "근거가 약한 주장에 대한 공고 요건 재검색"},
            {"agent": "gap", "goal": "보강된 근거로 갭 재계산"},
        ]

    has_resume_input = bool(
        state.get("pdf_path") or state.get("resume_text") or state.get("github_url")
    )
    steps: list[dict] = []
    if has_resume_input and not state.get("resume_skills"):
        steps.append({"agent": "profile", "goal": "이력서·GitHub에서 보유 스킬과 confidence 추출"})
    steps.append({"agent": "retrieval", "goal": "직무 요구 스킬과 공고 근거 검색"})
    steps.append({"agent": "market", "goal": "부족 스킬의 수요·연봉 트렌드 조사"})
    steps.append({"agent": "gap", "goal": "보유 vs 요구를 비교해 갭과 매칭률 계산"})
    return steps


def create_planner_node(openai_client):
    """Planner 노드 팩토리. openai_client는 시그니처 일관성용(미사용)."""
    if not os.getenv("OPENAI_API_KEY"):
        raise EnvironmentError("OPENAI_API_KEY 환경변수가 필요합니다.")

    _llm = ChatOpenAI(model="gpt-4o-mini", temperature=0).with_structured_output(Plan)

    def planner_node(state: AppState) -> dict:
        skeleton = build_skeleton_plan(state)
        agents = [s["agent"] for s in skeleton]
        situation = (
            f"직군: {state['job_family']} / 지원자: {state['owner']}\n"
            f"PDF: {'있음' if state.get('pdf_path') else '없음'} / "
            f"이력서텍스트: {'있음' if state.get('resume_text') else '없음'} / "
            f"GitHub: {'있음' if state.get('github_url') else '없음'} / "
            f"주입스킬: {len(state.get('resume_skills') or [])}개 / "
            f"재계획: {'예' if (state.get('critic_report') or {}).get('needs_replan') else '아니오'}"
        )
        try:
            plan: Plan = _llm.invoke([SystemMessage(content=_PLANNER_PROMPT.format(
                situation=situation, agents=agents,
            ))])
            # LLM이 항목을 바꿔도 골격으로 강제 정렬(goal만 채택)
            goal_by_agent = {s.agent: s.goal for s in plan.steps}
            steps = [
                {"agent": a, "goal": goal_by_agent.get(a, sk["goal"])}
                for a, sk in zip(agents, skeleton)
            ]
            reason = plan.reason
        except Exception as e:
            print(f"[planner] LLM 계획 실패 — 결정적 fallback 사용: {e}")
            steps = skeleton
            reason = "LLM 실패로 기본 조사 계획 사용"

        updates: dict = {"plan": {"steps": steps, "reason": reason}}
        # replan 진입 시 이전 라운드의 누적 메시지를 비운다.
        # messages·coach_messages는 add_messages(append-only) reducer라,
        # 클리어하지 않으면 replan마다 gap 대화·coach 시드가 쌓여 Coach 출력이 오염된다.
        if (state.get("critic_report") or {}).get("needs_replan"):
            updates["messages"] = [RemoveMessage(id=REMOVE_ALL_MESSAGES)]
            updates["coach_messages"] = [RemoveMessage(id=REMOVE_ALL_MESSAGES)]
        return updates

    return planner_node
