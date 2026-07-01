# 시스템 설명 — LangGraph 구조(Mermaid) + 6개 논리 단계의 설계 의도
from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.deps import get_graph

router = APIRouter()

_STAGES = [
    {"key": "evaluators", "title": "1. 다중 소스 평가자",
     "nodes": ["resume_eval", "github_eval", "portfolio_eval", "deploy_eval"],
     "description": "입력한 소스만 각각 다른 평가자가 본다. 소스마다 형식(텍스트·코드·웹)이 달라 한 LLM에 합칠 수 없고, 무엇보다 '할 줄 안다는 주장(이력서)'과 '코드로 실증됨(GitHub·배포)'을 구분하려고 분리했다.",
     "sources": [
         {"name": "이력서 (PDF)", "sees": "텍스트를 읽어 보유 스킬을 추출", "verdict": "주장 (Claimed)"},
         {"name": "포트폴리오 (PDF)", "sees": "텍스트 + 이미지(vision)로 프로젝트 규모·성과 파악", "verdict": "주장 보강"},
         {"name": "GitHub", "sees": "레포 코드·README·의존성을 읽어 실제 사용을 확인", "verdict": "실증 (Verified)"},
         {"name": "배포 URL", "sees": "작동하는 웹(HTML·헤더)을 확인", "verdict": "작동 실증 (Verified)"},
     ]},
    {"key": "consensus", "title": "2. 교차검증 합의",
     "nodes": ["consensus"],
     "description": "여러 독립 소스가 같은 스킬을 가리키면 신뢰가 올라간다(법정·저널리즘의 교차검증 원칙). GitHub/배포로 실증되면 Verified, 2개 이상 소스가 일치하면 Corroborated, 한 소스(이력서)뿐이면 Claimed로 결정적으로 판정한다."},
    {"key": "gap_loop", "title": "3. Gap 루프 (Corrective RAG)",
     "nodes": ["seed_gap", "gap_agent"],
     "description": "단순 키워드 매칭이 아니다. 증거가 부족하면 에이전트가 다른 소스를 추가로 검색하는 교정 루프를 돈다 — '이 답을 신뢰할 근거가 충분한가'를 스스로 판단한다. (gap_agent는 내부에 call_model↔tools 루프를 가진 서브그래프)"},
    {"key": "fit", "title": "4. 스킬 기반 적합도",
     "nodes": ["synthesizer"],
     "description": "직군 핵심 스킬(빈도 상위 10개)과 이력서 스킬을 개별 비교해 적합도를 낸다. 역량 묶음으로 뭉뚱그리면 직군이 구분되지 않아(Data Analyst와 Data Engineer가 동일해짐), 스킬 단위로 비교해 변별력을 확보했다. 어느 직군에 맞는지 역방향으로도 추천한다."},
    {"key": "critic", "title": "5. Critic (환각 제거)",
     "nodes": ["critic"],
     "description": "LLM이 스스로 채점하면 환각이 남는다. Critic은 판단하지 않고, 리포트의 주장을 합의(사실)와 대조해 합의에 없는 환각을 제거하고 부풀린 검증 라벨을 교정한다 — 결정적으로."},
    {"key": "coach", "title": "6. Coach",
     "nodes": ["coach_agent"],
     "description": "부족한 스킬과, 이력서·코드를 어떻게 보강하면 좋을지 구체적인 문장을 공고 근거와 GitHub 코드에 기반해 제안한다. (coach_agent는 내부 코칭 루프 서브그래프)"},
]


_OVERVIEW = (
    "입력한 소스(이력서·GitHub·포트폴리오·배포)만 골라 병렬로 평가한 뒤, 합의 노드가 여러 소스를 "
    "교차검증해 스킬별 검증등급(Verified/Corroborated/Claimed)을 결정적으로 판정합니다. "
    "Gap 에이전트는 근거가 부족하면 추가 검색을 스스로 결정하는 Corrective RAG 루프를 돌고, "
    "리포트는 Critic이 합의와 대조해 환각을 제거합니다. 마지막으로 Coach가 부족 스킬 보강·이력서 개선을 "
    "공고 근거와 GitHub 코드에 기반해 제안합니다. 파란 노드는 이번 분석에서 실제 실행된 경로입니다."
)

# 실제 LangGraph 구조를 반영한 상세 다이어그램. draw_mermaid()는 서브그래프 내부 루프를
# 접어 밋밋하므로, Gap·Coach 서브그래프의 내부 루프까지 손으로 표현한다.
# 최상위 노드 id는 실제 노드명과 일치시켜 executed_nodes 하이라이트가 붙게 한다.
_WORKFLOW_MERMAID = """flowchart TD
  START([이력서·GitHub·포트폴리오·배포 URL]) --> DISP{입력 소스 확인}
  DISP -->|이력서| resume_eval["이력서 평가자<br/>텍스트 → 스킬 추출"]
  DISP -->|GitHub| github_eval["GitHub 평가자<br/>레포 코드 분석"]
  DISP -->|포트폴리오| portfolio_eval["포트폴리오 평가자<br/>텍스트 + vision"]
  DISP -->|배포 URL| deploy_eval["배포 평가자<br/>작동 실증"]
  resume_eval --> consensus
  github_eval --> consensus
  portfolio_eval --> consensus
  deploy_eval --> consensus
  consensus["합의<br/>검증등급 결정적 판정"] --> seed_gap["seed_gap<br/>Gap 진입 상태 변환"]
  seed_gap --> gap_agent
  subgraph gap_agent["Gap 에이전트 — Corrective RAG 루프"]
    direction LR
    gcm["call_model<br/>증거 충분한가?"] -->|부족하면 재검색| gtl["tools<br/>gap_analysis · verify_skills · skill_unlock"]
    gtl --> gcm
  end
  gap_agent --> synthesizer["synthesizer<br/>적합도 + 신뢰도 리포트"]
  synthesizer --> critic["critic<br/>합의 대조 · 환각 제거"]
  critic --> coach_agent
  subgraph coach_agent["Coach 에이전트 — 코칭 루프"]
    direction LR
    ccm["coach_call_model"] -->|근거 확인| ctl["coach_tools<br/>verify_suggestion · related_skills"]
    ctl --> ccm
    ccm --> fc["finalize_coach<br/>코칭 확정"]
  end
  coach_agent --> DONE([최종 리포트<br/>충족·채울것·보강·회사추천])
"""


@router.get("")
async def graph(graph=Depends(get_graph)) -> dict:
    """LangGraph 구조(Mermaid) + 개요 + 단계 설명. graph 없으면 mermaid는 None."""
    mermaid = _WORKFLOW_MERMAID if graph is not None else None
    return {"mermaid": mermaid, "overview": _OVERVIEW, "stages": _STAGES}
