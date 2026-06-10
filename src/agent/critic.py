# gap_result 주장을 retrieved_context와 대조해 근거 충실성을 판정하는 Critic 노드
from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from src.agent.state import AppState, MAX_REPLAN

if TYPE_CHECKING:
    pass


class CriticReport(BaseModel):
    faithful: bool = Field(description="갭 주장들이 검색 근거에 충실한가")
    unsupported_claims: list[str] = Field(
        default_factory=list, description="근거가 부족한 주장 목록(한국어)"
    )


_CRITIC_PROMPT = """당신은 RAG 답변의 근거 충실성(faithfulness)을 검증하는 Critic입니다.
아래 '갭 분석 주장'들이 '검색된 공고 근거'에 의해 실제로 뒷받침되는지 판정하세요.

[갭 분석 주장]
{claims}

[검색된 공고 근거]
{evidence}

판정 규칙:
- 각 주장이 근거 텍스트로 뒷받침되면 faithful=true.
- 근거가 없거나 모순되는 주장이 하나라도 있으면 faithful=false, 그 주장을 unsupported_claims에 한국어로 기록.
- 근거가 비어 있으면 검증 불가이므로 faithful=false 처리."""


def decide_replan(faithful: bool, replan_count: int) -> bool:
    """replan 여부를 결정한다(결정적 가드레일).

    근거 불충실하고 replan 상한(MAX_REPLAN) 미만일 때만 재계획한다.
    """
    return (not faithful) and (replan_count < MAX_REPLAN)


def _extract_claims(gap_result: dict) -> list[str]:
    """gap_result에서 검증 대상 주장 텍스트를 추출한다."""
    claims: list[str] = []
    for item in gap_result.get("missing_required") or []:
        if isinstance(item, dict):
            skill = item.get("skill", "")
            reason = item.get("reason", "")
            claims.append(f"{skill}: {reason}".strip(": "))
        elif isinstance(item, str):
            claims.append(item)
    return claims


def create_critic_node(openai_client):
    """Critic 노드 팩토리. openai_client는 시그니처 일관성용(미사용)."""
    if not os.getenv("OPENAI_API_KEY"):
        raise EnvironmentError("OPENAI_API_KEY 환경변수가 필요합니다.")

    _llm = ChatOpenAI(model="gpt-4o-mini", temperature=0).with_structured_output(CriticReport)

    def critic_node(state: AppState) -> dict:
        gap_result = state.get("gap_result") or {}
        context = state.get("retrieved_context") or []
        replan_count = state.get("replan_count", 0)

        claims = _extract_claims(gap_result)
        evidence_texts = [c.get("text", "") for c in context if c.get("text")]

        if not claims:
            report = {"faithful": True, "unsupported_claims": [], "needs_replan": False}
            return {"critic_report": report}

        try:
            verdict: CriticReport = _llm.invoke([SystemMessage(content=_CRITIC_PROMPT.format(
                claims=json.dumps(claims, ensure_ascii=False, indent=2),
                evidence=json.dumps(evidence_texts, ensure_ascii=False, indent=2),
            ))])
            faithful = verdict.faithful
            unsupported = verdict.unsupported_claims
        except Exception as e:
            print(f"[critic] 판정 실패 — 보수적으로 통과 처리: {e}")
            faithful, unsupported = True, []

        report = {
            "faithful": faithful,
            "unsupported_claims": unsupported,
            "needs_replan": decide_replan(faithful, replan_count),
        }
        return {"critic_report": report}

    return critic_node
