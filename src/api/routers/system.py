# 시스템 설명 — LangGraph 구조(Mermaid) + 6개 논리 단계의 설계 의도
from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.deps import get_graph

router = APIRouter()

_STAGES = [
    {"key": "evaluators", "title": "1. 다중 소스 평가자",
     "nodes": ["resume_eval", "github_eval", "portfolio_eval", "deploy_eval"],
     "description": "이력서·GitHub·배포 URL을 각각 다른 평가자가 본다. 소스마다 형식(텍스트·코드·웹)이 달라 한 LLM에 합칠 수 없고, 무엇보다 '할 줄 안다는 주장(이력서)'과 '코드로 실증됨(GitHub·배포)'을 구분하려고 분리했다."},
    {"key": "consensus", "title": "2. 교차검증 합의",
     "nodes": ["consensus"],
     "description": "여러 독립 소스가 같은 스킬을 가리키면 신뢰가 올라간다(법정·저널리즘의 교차검증 원칙). GitHub/배포로 실증되면 Verified, 2개 이상 소스가 일치하면 Corroborated, 한 소스(이력서)뿐이면 Claimed로 결정적으로 판정한다."},
    {"key": "gap_loop", "title": "3. Gap 루프 (Corrective RAG)",
     "nodes": ["seed_gap", "call_model", "tools"],
     "description": "단순 키워드 매칭이 아니다. 증거가 부족하면 에이전트가 다른 소스를 추가로 검색하는 교정 루프를 돈다 — '이 답을 신뢰할 근거가 충분한가'를 스스로 판단한다."},
    {"key": "fit", "title": "4. 역량 기반 적합도",
     "nodes": ["synthesizer"],
     "description": "직군 평균 개별 스킬로 재면 전문가가 저평가된다(Java 백엔드가 웹 평균과 안 맞음). 그래서 스킬을 역량(DB·백엔드·클라우드…)으로 묶어 '핵심 역량 충족'으로 본다. 어느 직군에 맞는지 역방향으로도 추천한다."},
    {"key": "critic", "title": "5. Critic (환각 제거)",
     "nodes": ["critic"],
     "description": "LLM이 스스로 채점하면 환각이 남는다. Critic은 판단하지 않고, 리포트의 주장을 합의(사실)와 대조해 합의에 없는 환각을 제거하고 부풀린 검증 라벨을 교정한다 — 결정적으로."},
    {"key": "coach", "title": "6. Coach",
     "nodes": ["coach_call_model", "coach_tools", "finalize_coach"],
     "description": "부족한 역량과, 이력서를 어떻게 고치면 좋을지 구체적인 문장을 공고 근거에 기반해 제안한다."},
]


@router.get("")
async def graph(graph=Depends(get_graph)) -> dict:
    """LangGraph 구조(Mermaid) + 단계 설명. graph 없으면 mermaid는 None."""
    mermaid = None
    if graph is not None:
        try:
            mermaid = graph.get_graph().draw_mermaid()
        except Exception:
            mermaid = None
    return {"mermaid": mermaid, "stages": _STAGES}
