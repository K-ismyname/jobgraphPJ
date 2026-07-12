# 에이전트 노드 함수 — Gap Agent(call_model, generate_report), Coach Agent(coach_call_model, finalize_coach)
#
# 이 파일이 하는 일: gap_agent.py와 (아직 안 본) coach_agent.py가 조립하는 그래프의 실제 "일꾼" 함수들을
# 전부 모아둔 곳. LLM 호출, 프롬프트, 그리고 이 프로젝트의 핵심 원칙인 "LLM 출력을 결정적 코드로
# 검증·덮어쓰기"가 이 파일에 집중돼 있다. gap_agent.py/coach_agent.py는 이 함수들을 가져다 그래프에
# 등록만 할 뿐, "무엇을 판단하고 무엇을 계산할지"는 전부 여기 있다.

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
# LangChain이 OpenAI를 감싼 래퍼 클래스 — .invoke()로 호출하면 내부적으로 OpenAI API를 호출하되,
# LangGraph의 메시지 타입(BaseMessage 등)과 자연스럽게 호환되게 만들어져 있음

from src.agent.state import AppState
from src.extraction.normalizer import normalize_skill

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool
    from src.storage.neo4j_client import Neo4jClient


@lru_cache(maxsize=1)
def _get_gap_llm() -> ChatOpenAI:
    """Gap 에이전트용 LLM (call_model·synthesizer 공유) — 팩토리 중복 호출에도 1개만 생성."""
    # @lru_cache(maxsize=1) → 이 함수는 인자가 없으므로(캐시 키가 항상 동일) 실질적으로
    # "첫 호출 때만 진짜로 실행되고, 그 뒤로는 항상 같은 객체를 즉시 반환하는 싱글턴"이 됨.
    # ChatOpenAI 객체를 매번 새로 만들면 자원 낭비이므로, gap_agent와 synthesizer가 이 함수를
    # 여러 번 호출해도 실제 LLM 클라이언트는 딱 하나만 만들어짐
    if not os.getenv("OPENAI_API_KEY"):
        raise EnvironmentError("OPENAI_API_KEY 환경변수가 필요합니다.")
    return ChatOpenAI(model="gpt-4o-mini", temperature=0, max_retries=6)
    # max_retries=6 → ChatOpenAI 자체 내장 재시도 기능. skill_extractor.py의 수동 재시도 루프와 달리,
    # 여기선 LangChain 라이브러리가 이미 제공하는 재시도 옵션을 그대로 씀

# ── Gap Agent 프롬프트 ────────────────────────────────────────────
_GAP_SYSTEM_PROMPT = """당신은 AI 커리어 분석 전문가입니다.
채용공고 요구사항과 지원자 보유 스킬을 비교해 기술 갭을 분석합니다.

분석 절차:
1. gap_analysis(job_family, portfolio_skills, owner) — owner 반드시 포함. 매칭률과 부족 스킬을 계산하세요.
2. verify_skills — missing_required 중 weight 상위 5개를 한 번에 넘기세요. 1회만 호출.
3. skill_unlock — missing_required 확정 후 상위 3개 스킬 묶음으로 1회만 호출. 개별 반복 호출 금지.
4. posting_trend — 우선순위 판단이 필요한 스킬에만 선택적으로 호출.
5. 충분한 근거가 모이면 도구 호출을 멈추세요. 이 시점의 응답 텍스트는 리포트 생성에 쓰이지
   않고 오직 "분석 종료" 신호로만 쓰이므로, 길게 쓰지 말고 "분석 완료"처럼 한 단어로 답하세요.

규칙:
- verify_skills는 단 1회. 스킬마다 반복 호출 금지.
- skip:true 또는 "없음" 메시지가 있으면 graph_only로 처리하고 넘어가세요.
- 추측으로 판단 가능하면 ask_human을 쓰지 마세요."""
# 이 프롬프트가 gap_agent.py의 ReAct 루프에서 매 턴 LLM에게 주어지는 "판단 기준" 그 자체.
# 5단계 절차가 그대로 지난번 시각화했던 5턴 예시(gap_analysis→verify_skills→skill_unlock→
# posting_trend→종료)의 근거였음

_GAP_REPORT_PROMPT = """아래는 지금까지 수집된 분석 데이터입니다.
이를 바탕으로 구조화된 갭 분석 리포트를 JSON으로 생성하세요.

{tool_results}

[합의(consensus) — 각 보유 스킬의 검증 상태]
아래는 다중 소스(이력서·GitHub) 합의 결과입니다. 형식은 "스킬명: verification" 입니다.
verification 값의 의미:
- Verified: 코드/외부 근거로 검증됨 (가장 신뢰 높음)
- Corroborated: 복수 소스가 서로 뒷받침함
- Claimed: 이력서 주장만 있고 코드 근거 없음 (신뢰 낮음)
{consensus}

분석 시 위 합의를 반드시 반영하세요:
- 각 보유 스킬의 verification 값을 그대로 skills[].verification 에 넣으세요.
- held_level 은 검증 상태를 드러내세요. 예: Claimed → "실무(주장)", Verified → "실무".
- match_rate/confidence_level/advice 는 시스템이 도구·합의 결과로 결정적으로 계산해 덮어쓰므로,
  대략의 값을 넣어도 됩니다(최종값은 코드가 산출).
- missing_required 의 posting_count/trend_delta_pct 는 도구 결과에 실제로 있는 값만 쓰고,
  근거가 없으면 0으로 두세요(임의 추정 금지).

다음 JSON 형식으로 출력하세요 (코드 펜스 없이):
{{
  "job_title": "직무명",
  "match_rate": 0.0,
  "confidence_level": "high|medium|low",
  "advice": "",
  "summary": "한 줄 요약",
  "have_required": ["보유 필수 스킬"],
  "unverified_required": ["보유하나 근거 약한 스킬 (confidence=low)"],
  "skills": [
    {{
      "skill": "스킬명",
      "required_level": "실무",
      "held_level": "실무(주장)",
      "verification": "Claimed",
      "gap": "요구 수준 대비 부족한 점 (없으면 빈 문자열)"
    }}
  ],
  "missing_required": [
    {{
      "skill": "스킬명",
      "reason": "왜 중요한지 (공고 근거 포함)",
      "priority": "high/medium/low",
      "posting_count": 0,
      "trend_delta_pct": 0.0
    }}
  ],
  "missing_preferred": ["부족한 우대 스킬"],
  "skill_unlock": {{"skills": [], "accessible_postings": 0}},
  "coaching": ["개선 제안 1", "개선 제안 2"]
}}"""
# 이 프롬프트는 "이미 도구를 다 부르고 얻은 결과 데이터"를 받아 정해진 JSON 스키마로 정리만 하는 역할.
# 프롬프트 안에 이미 "match_rate/confidence_level은 시스템이 덮어쓰니 대략 넣어도 된다"고 명시돼 있음 —
# LLM에게 "정확한 계산은 네가 안 해도 된다, 코드가 나중에 고칠 거다"라고 미리 알려주는 것

# ── Coach Agent 프롬프트 ─────────────────────────────────────────
_PROJECT_DESIGN_CONTEXT = """[이 프로젝트 설계 의사결정]
- LangGraph 선택: 조건 분기·루프·HITL 세 가지를 동시에 구현해야 해서. LangChain 체인만으로는 불가.
- Neo4j 선택: 직무-기술 관계(REQUIRES/CO_OCCURS) 표현 최적. 벡터DB는 관계 표현 불가.
- Chroma 제거: 검색 12건 중 11건이 키워드 매칭과 동일 결과 → 효과 없음을 측정하고 제거.
- 적합도 ⊥ 신뢰도 분리: "Python 잘 함(이력서 주장)" ≠ "Python 잘 함(GitHub 확인)". 점수와 근거를 분리.
- consensus/critic LLM 없음: 신뢰도 등급은 규칙 기반으로 결정적 산출. LLM은 숫자를 지어낸다.
- 4개 평가자 병렬: resume/github/portfolio/deploy 독립 평가 후 교차검증. 이력서 주장만 믿으면 과장이 안 걸러짐.
- Corrective RAG 루프: 근거 부족하면 tools 재호출 (최대 5회). 에이전트가 "증거가 충분한가"를 스스로 판단.
- RAGAS 평가: Faithfulness=0.250(공고 간접 표현 탓), AnswerRelevancy=0.876."""
# 흥미로운 지점: 이 텍스트는 코칭 LLM이 "면접에서 이 프로젝트의 설계 이유를 설명하라"는 코칭을 만들 때
# 참고하는 배경지식으로 쓰임 (아래 coach_call_model에서 시스템 프롬프트에 이어붙여짐).
# CLAUDE.md 문서 내용을 코드 상수로도 복제해둔 셈 — 두 군데를 따로 유지보수해야 한다는 뜻이기도 함

_COACH_SYSTEM_PROMPT = """당신은 커리어 코치입니다. GitHub 소스코드 분석 결과와 직군 갭을 바탕으로 두 종류의 코칭을 합니다.

[GitHub 분석 데이터 읽는 법]
project_contexts 안에 각 프로젝트의 structure_summary(프로젝트 구조 2-3문장 요약)와
skill_assessments 목록이 있습니다. 각 skill_assessments 항목:
- current_usage: 현재 수준 (기본 사용 / 중급 패턴 / 고급 패턴)
- used_patterns: 코드에서 이미 확인된 패턴
- missing_patterns: 이 스킬의 고급 패턴 중 아직 없는 것
- how_to_add: 이 프로젝트 파일 기준 구체적 보강 방법

[프로젝트 보강 — 2단계 판단]
1단계: skill_assessments 중 **how_to_add가 채워진 스킬만** project_suggestions로. how_to_add가 비어있으면(이미 고급이거나 보강 불필요) 제외 — 억지로 만들지 말 것.

2단계: 갭 분석의 missing_required 스킬마다 판단하세요.
  project_contexts(코드 구조)를 보고 이 스킬이 이 프로젝트의 기존 설계와 조화롭게 확장될 수 있는가?
  YES — project_contexts에서 실제로 본 파일·구조에 자연스럽게 얹히는가? → project_suggestions에 추가
  NO  — 코드 연결점이 없거나, 프로젝트 설계와 안 맞거나, 그냥 '직군에 필요'뿐인가? → learning_recommendations에만
  판단이 애매하면 무조건 NO(learning)로 보내세요. project_suggestions는 확실한 것만.

[② 채우면 좋을 스킬 — 학습 추천(learning_recommendations)]
직군이 요구하나 코드에 없는 스킬(2단계 NO)과, related_skills 툴로 찾은 연계 미보유 스킬을 학습 추천합니다.
각 항목은 reason(왜)과 how(어떻게)를 모두 채웁니다.

- reason(왜 필요한가): 일반론 금지. "이 직군 공고에서 어떻게 요구되는지 + 어떤 보유 스킬과 이어지는지"를 구체적으로.
- how(어떻게 학습하나): project_contexts의 structure_summary를 참조해 "당신의 [프로젝트]는 [구조]이니, 이 스킬을 이렇게 적용/개선"까지 구체화. 보유 스킬을 학습 발판으로 제시.
  structure_summary가 없으면(GitHub 미연동) "무엇부터 어떤 순서로" 학습 경로만 제시.
  주의: 이 스킬은 코드에 없으므로 파일명·함수명을 지어내지 마세요(환각 금지). 프로젝트 단위까지만.

learning 좋은 예 (structure_summary="FastAPI 단일 서비스 RAG 챗봇"일 때):
  skill: "Kubernetes"
  reason: "AI/LLM 공고 다수가 컨테이너 오케스트레이션을 요구합니다. 이미 Docker를 쓰고 있어 자연스러운 다음 단계입니다."
  how: "당신의 RAG 챗봇은 FastAPI 단일 서비스로 구성돼 있습니다. Kubernetes로 이 서비스를 Deployment로 배포하면 트래픽 증가 시 Pod를 늘려 분산할 수 있습니다. minikube로 현재 컨테이너를 올리는 것부터 시작하세요."

learning 나쁜 예 (절대 금지):
  reason: "문제 해결 및 최적화에 도움이 됩니다." → 일반론, 누구에게나 같음.
  how: "공식 문서로 기초부터 학습하세요." → 보유 스킬·프로젝트와 무관한 빈 조언.

규칙:
- 2단계 판단 기준: "이 프로젝트 코드 어디에 어떻게 추가하는가"가 구체적으로 보여야 YES.
  "이 직군에 중요하다", "있으면 도움된다" 수준이면 NO → learning_recommendations.
- code_anchor=false인 스킬은 project_suggestions 후보에서 즉시 제외하세요 → learning_recommendations로.
- 현재 프로젝트 주 언어·런타임과 다른 언어(Python 프로젝트에 Java·JavaScript, Node 프로젝트에 Python 등)는
  절대 project_suggestions에 넣지 마세요 → 반드시 learning_recommendations로.
- 프로젝트의 핵심 설계를 바꾸거나 대체하는 제안 절대 금지 (예: Neo4j를 PostgreSQL로 전환, FastAPI를 Flask로). 대체는 보강이 아니라 파괴입니다.
- 이 프로젝트가 채택하지 않은 패러다임을 억지로 넣지 마세요 (예: 규칙 기반 계산 함수에 신경망·ML 모델 추가).
- project_suggestions의 how는 structure_summary(프로젝트 전체) 관점의 제안 — 특정 파일·함수를 지어내지 말 것. **억지로 만들지 말고 이 프로젝트에 명확히 도움될 것만, 없으면 빈 배열.** 애매하면 learning으로 돌리세요.
- 갖지 않은 스킬을 이력서에 써넣으라고 하지 마세요. 프로젝트로 실증하거나 학습하라고 안내하세요.
- GitHub 소스코드가 없으면 project_suggestions는 비우고 연계 학습 위주로 작성하세요.
- 필요하면 verify_suggestion으로 공고 근거를 확인하세요.
- 모든 검토가 끝나면 도구 호출 없이 최종 JSON을 반환하세요.

[면접 코칭]
보유 스킬과 갭을 바탕으로 면접 전략을 코칭하세요. 질문 목록이 아니라 "어떻게 말해야 하는가"를 알려주는 코칭입니다.

두 가지 유형:
- strength(강점 어필): [강점 어필 대상] 목록의 스킬을 **목록 순서 그대로** 상위 3개 선택. 순서가 중요도 순이므로 절대 바꾸지 말 것. 어떤 구현을 했는지 + 왜 그 선택인지 + 면접관이 파고들 때 어떻게 답할지.
- gap(갭 대응): missing_required 스킬 — 보유 스킬에서 인접 경험을 연결. 금지: "모른다", "배우겠다", "배울 준비가 되어 있다", "기초 지식이 있다".

[좋은 코칭 예시 — 이 수준으로 작성할 것]
strength 예시 1:
  title: "LangGraph Corrective RAG 설계"
  coaching: "Send API로 4개 평가자를 병렬 fan-out하고 consensus 노드에서 합류시킨 구조를 설명하세요. '왜 LangGraph를 썼냐'는 질문엔 조건 분기·루프·HITL 세 가지를 동시에 구현해야 했기 때문이라고 답하세요. LangChain 체인만으로는 이 구조가 불가능하다는 걸 한 줄 덧붙이면 차별화됩니다."

strength 예시 2:
  title: "Docker 배포 실증"
  coaching: "단순히 Docker를 쓴 게 아니라 실제 서비스가 동작 중인 URL이 있다면 그걸 증거로 제시하세요. '컨테이너화한 이유'는 환경 차이 없이 재현 가능한 실행 환경을 만들기 위해서라고 답하고, docker-compose로 여러 서비스를 엮은 경험이 있으면 반드시 언급하세요."

gap 예시:
  title: "Kubernetes 미경험"
  coaching: "Docker로 컨테이너화한 경험이 있으니 '단일 컨테이너에서 다중 서비스로 규모가 커졌을 때 오케스트레이션이 왜 필요한지는 이해한다'고 연결하세요. 모른다고만 하면 탈락이지만 인접 경험으로 개념 이해를 보여주면 플러스입니다."

[나쁜 코칭 예시 — 절대 이렇게 쓰지 말 것]
gap 나쁜 예:
  coaching: "Python으로 데이터 분석을 해봤으니 머신러닝을 배울 준비가 되어 있다고 강조하면 좋습니다."
  → 금지 이유: "배울 준비"는 지원자가 해당 역량이 없다고 스스로 인정하는 표현. 면접관이 "그럼 지금은 못 한다는 거네요"로 역공한다.

strength 나쁜 예:
  title: "AI 모델 통합 경험"
  coaching: "AI 모델 학습 로직을 추가한 경험을 강조하세요."
  → 금지 이유: 어떤 모델인지, 왜 그 선택인지, 어떤 구조인지가 없으면 모든 지원자가 동일하게 답할 수 있어 차별화가 안 됨.

strength 최소 2개 최대 3개, gap 최대 3개. 임팩트 높은 것부터.

최종 출력 형식 (코드 펜스 없이):
{{
  "summary": "전체 코칭 방향 2-3문장",
  "project_suggestions": [
    {{"repo": "owner/repo", "add_skill": "보강 대상 스킬",
      "why": "이 스킬이 이 프로젝트에 필요한 이유",
      "how": "프로젝트 전체(structure_summary·README) 관점에서 이 프로젝트에 무엇을 추가/개선하면 좋을지. 특정 파일·함수를 지어내지 말 것"}}
  ],
  "learning_recommendations": [
    {{"skill": "스킬명",
      "reason": "왜 필요한지 — 직군 요구 근거 + 보유 스킬 연결 (일반론 금지)",
      "how": "어떻게 학습할지 — structure_summary 참조한 프로젝트 단위 학습 방향"}}
  ],
  "interview_coaching": [
    {{"type": "strength", "title": "핵심 경험 제목",
      "coaching": "면접에서 이 경험을 어떻게 표현해야 하는지 구체적 조언"}}
  ]
}}"""
# 이 프롬프트가 coach_agent(다음에 볼 파일)의 시스템 프롬프트. 좋은 예/나쁜 예를 나란히 보여주는
# few-shot 방식으로, "일반론 대신 구체적 근거"라는 이 프로젝트의 반복되는 철학을 프롬프트 레벨에서도
# 강제하고 있음 (코드 레벨의 결정적 덮어쓰기와 이중으로 방어하는 셈)


def _load_skill_context(skills: list[str]) -> dict:
    """GAP 스킬 목록에 해당하는 면접 컨텍스트 문서를 로드한다."""
    path = os.path.join(os.path.dirname(__file__), "../../data/seeds/skill_interview_context.json")
    # os.path.dirname(__file__) → 이 파일(nodes.py)이 있는 폴더 경로. 거기서 두 단계 위(../../)로
    # 올라가 data/seeds/ 폴더의 시드 파일을 찾음 — pathlib 대신 os.path를 쓴, 다른 파일들과는
    # 조금 다른 스타일 (pipeline.py 등은 Path 객체를 씀 — 프로젝트 내 스타일 일관성 이슈)
    try:
        with open(os.path.normpath(path), encoding="utf-8") as f:
            # os.path.normpath() → "../../"처럼 상대경로 표기를 정리해서 깔끔한 절대/상대경로로 변환
            db = json.load(f)
        return {s: db[s] for s in skills if s in db}
        # 딕셔너리 컴프리헨션 — skills 리스트 중 db(시드 파일)에 실제로 있는 것만 골라 {스킬명: 컨텍스트} 형태로
    except Exception:
        return {}
        # 파일이 없거나 파싱 실패해도 빈 dict로 조용히 넘어감 — 면접 컨텍스트는 "있으면 좋은" 부가 정보라서
        # 없다고 전체 흐름이 막히면 안 됨


def _gap_missing_names(gap: dict) -> list[str]:
    """gap report의 missing_required에서 부족 스킬명 목록(dict/str 모두 허용)."""
    out: list[str] = []
    for item in (gap.get("missing_required") or []):
        if isinstance(item, dict) and item.get("skill"):
            out.append(item["skill"])
        elif isinstance(item, str):
            out.append(item)
        # missing_required의 각 항목이 {"skill": "Docker", ...} dict일 수도, 그냥 "Docker" 문자열일 수도
        # 있어서 둘 다 처리 — LLM 응답 형식이 완벽히 일관되지 않을 수 있다는 걸 전제로 한 방어적 코드
    return out[:8]
    # 최대 8개까지만 — 이후 _load_skill_context 등에서 너무 많은 스킬을 한 번에 처리하지 않게 상한을 둠


def _build_trace(state: "AppState", coaching: dict | None = None) -> dict:
    """그래프 결과 state에서 실행 흔적(관측 페이지용)을 결정적으로 조립한다.

    coaching은 호출 노드(finalize_coach)가 막 만든 결과를 직접 넘긴다 — LangGraph가
    반환 dict를 state에 머지하기 전이라 state["coaching_result"]는 아직 비어 있기 때문.
    """
    # 이 함수의 목적: 사용자에게 "이 리포트가 어떤 근거로, 어떤 노드들을 거쳐 만들어졌는지"를
    # 투명하게 보여주는 관측(observability) 데이터를 만드는 것. CLAUDE.md의 "관측 페이지" 개념

    # 왜 coaching을 매개변수로 따로 받는가 — 지난번 state.py에서 배운 개념의 실전 사례:
    # LangGraph 노드가 {"coaching_result": {...}}를 반환해도, 그 값이 실제로 state에 "병합"되는 건
    # LangGraph 내부에서 이 함수가 실행된 "다음"이다. 그래서 finalize_coach 안에서 이 함수를 부를 때는
    # 아직 state["coaching_result"]가 옛날 값(또는 없음)이라서, 방금 만든 coaching 값을 직접 넘겨줘야 함
    from src.agent.consensus import build_verification_summary
    # 아직 안 본 consensus.py의 함수 — 다음 리뷰 후보

    evaluators = []
    executed: list[str] = []
    for src in ("resume", "github", "portfolio", "deploy"):
        ev = state.get(f"{src}_eval")
        if ev:
            skills = ev.get("skills") or []
            evaluators.append({
                "source": src,
                "skill_count": len(skills),
                "skills": [
                    {"skill": s.get("skill"), "evidence": s.get("evidence"), "level_hint": s.get("level_hint")}
                    for s in skills if isinstance(s, dict)
                ],
            })
            executed.append(f"{src}_eval")
            # 4개 평가자 중 실제로 결과가 있는(즉 입력이 주어져서 실행된) 것만 "executed" 목록에 추가
            # — dispatch가 fan-out 안 한 평가자는 여기서 자동으로 제외됨

    cons = build_verification_summary(state.get("consensus") or {})
    if state.get("consensus"):
        executed.append("consensus")

    # gap_trace는 synthesizer(AppState)가 채워서 CoachState에 전달 — messages/iteration을 직접 읽지 않아도 됨
    _gt = state.get("gap_trace") or {}
    tool_calls: list[str] = _gt.get("tool_calls") or []
    gap_iterations: int = _gt.get("iterations") or 0

    executed.append("synthesizer")  # Supervisor 레벨 노드 — 항상 실행됨
    if state.get("gap_result"):
        # call_model은 gap 루프 진입 시 항상 실행되지만, tools는 실제 툴 호출이
        # 있었을 때만(gap_trace.tool_calls로 실측). 추정 대신 실행 흔적으로 판정.
        executed += ["seed_gap", "gap_agent", "call_model"]
        if tool_calls:
            executed.append("tools")
            # "call_model은 항상 실행되지만 tools는 실제 호출 여부에 달렸다"는 구분 —
            # gap_agent 그래프 구조상 call_model은 최소 1번은 반드시 실행되지만
            # (LLM이 첫 턴부터 도구 호출 없이 바로 답하면) tools 노드는 아예 안 거칠 수도 있음

    critic = state.get("critic_report") or {}
    removed = critic.get("removed_claims") or []
    corrections = critic.get("corrections") or []
    if critic:
        executed.append("critic")

    coaching = coaching if coaching is not None else (state.get("coaching_result") or {})
    # 매개변수로 coaching이 넘어왔으면 그걸 우선 쓰고, 안 넘어왔으면(다른 호출 상황) state에서 읽어봄 —
    # 이 함수가 "노드 실행 도중"과 "이미 state가 다 채워진 후" 두 상황 모두에서 재사용 가능하게 설계됨
    if coaching:
        executed += ["coach_agent", "finalize_coach"]

    return {
        "executed_nodes": executed,
        "evaluators": evaluators,
        "consensus": cons,
        "gap_loop": {"tool_calls": tool_calls, "iterations": gap_iterations},
        "critic": {
            "removed": len(removed), "corrected": len(corrections),
            "removed_skills": removed, "corrections": corrections,
        },
        "coach": {
            "project_suggestion_count": len(coaching.get("project_suggestions") or []),
            "learning_count": len(coaching.get("learning_recommendations") or []),
            "github_profiles": (state.get("github_eval") or {}).get("profiles") or [],
            "missing_skills": _gap_missing_names(state.get("gap_result") or {}),
        },
    }


# ── 코칭 텍스트의 파일 경로 환각 차단 (결정적) ────────────────────
# 기술명 오탐 방지: '/'가 든 경로, 또는 .py 단독 파일명만 경로로 간주.
# ponytail: Node.js 류 기술명 때문에 .js 단독 파일명은 검사 제외 — 실측 환각이 전부 .py였음.
# \b는 한글을 word 문자로 봐 "main.py를"처럼 조사가 붙으면 경계 불성립 — ASCII 부정 lookahead 사용
_PATH_PATTERN = re.compile(
    r"[A-Za-z0-9_\-./]*/[A-Za-z0-9_\-.]+\.[A-Za-z]{1,4}(?![A-Za-z0-9])"   # 디렉토리 포함 경로
    r"|[A-Za-z0-9_\-]+\.py(?![A-Za-z0-9])"                                  # 단독 .py 파일명
)
# 이 정규식이 코칭 텍스트("이 기능은 src/main.py에서...") 안에서 "파일 경로처럼 보이는 부분"을 찾아냄.
# 두 가지 패턴을 |(or)로 묶음: ①폴더/파일.확장자 형태 ②확장자 없이 폴더 안 붙은 그냥 xxx.py 파일명
# \b(단어 경계) 대신 (?![A-Za-z0-9])(부정 lookahead)를 쓴 이유가 주석에 명시돼 있음 —
# 정규식의 \b는 "단어를 구성하는 문자"의 경계를 보는데, 한글도 그 기준에서 "단어 문자"로 취급되어
# "main.py를"처럼 뒤에 한글 조사가 붙으면 "py"와 "를" 사이를 경계로 인식 못 하는 문제가 있었음.
# 그래서 "바로 뒤에 영문자/숫자만 아니면 된다"는 조건으로 바꿔서 한글 조사가 붙어도 정상 매칭되게 함


def _invented_paths(text: str, valid_paths: set[str]) -> list[str]:
    """텍스트에 등장하는 파일 경로 중 실제 레포에 없는 것 목록."""
    basenames = {p.rsplit("/", 1)[-1] for p in valid_paths}
    # valid_paths(레포의 진짜 경로들)에서 각 경로의 "파일명만"(폴더 제외) 뽑아 별도 집합으로 만듦
    out = []
    for m in _PATH_PATTERN.findall(text or ""):
        if m in valid_paths or m.rsplit("/", 1)[-1] in basenames:
            continue
            # 텍스트에서 찾은 경로(m)가 valid_paths에 정확히 있거나, 파일명만이라도 실제 레포에 있으면
            # (LLM이 폴더 경로를 살짝 다르게 썼을 뿐일 수 있으므로) 환각으로 보지 않고 넘어감
        out.append(m)
        # 위 조건에 하나도 안 걸리면 = 레포 어디에도 없는 완전히 지어낸 경로 → 목록에 추가
    return out


def build_deterministic_project_reasons(project_contexts: list[dict]) -> dict[str, str]:
    """project_suggestions의 '왜'를 github_eval의 검증된 스킬 평가로 조립한다.

    project_suggestions는 "이 기능을 추가하면 강화됩니다" 같은 가정형 서술로
    후퇴하기 쉽다 — relevant_files(실제 레포 대조 완료)·current_usage(통제된
    열거값)는 이미 결정적으로 검증된 사실이므로, "왜"를 "이 파일들에서 이미
    이 수준으로 쓰고 있다"는 관측 사실로 고정한다. how(무엇을 추가할지)는
    코드가 판단할 수 없는 설계 제안이라 LLM 출력을 유지한다(scrub_invented_paths가
    거기서 파일 지어내기만 차단).

    근거(relevant_files)가 없는 스킬은 제외 — code_anchor=false라 애초에
    project_suggestions 후보에서 빠져야 하는 것들이라, 여기서도 LLM why를 유지한다.
    """
    reasons: dict[str, str] = {}
    for ctx in project_contexts or []:
        repo = ctx.get("repo", "")
        for sa in ctx.get("skill_assessments") or []:
            files = sa.get("relevant_files") or []
            name = normalize_skill(sa.get("skill") or "")
            if not files or not name:
                continue
                # relevant_files가 비어있으면(=github_eval.py가 검증할 파일 근거를 못 찾았으면)
                # 이 함수도 확정적인 "왜"를 만들 재료가 없으므로 건너뜀 (이 경우 LLM의 원래 why가 그대로 유지됨)
            usage = sa.get("current_usage") or "사용"
            file_list = ", ".join(files[:3])
            parts = [f"{repo}의 {file_list}에서 {name}을(를) {usage} 수준으로 이미 사용 중입니다."]
            patterns = [p for p in (sa.get("used_patterns") or []) if p][:2]
            if patterns:
                parts.append(f"확인된 패턴: {'; '.join(patterns)}.")
            reasons[name] = " ".join(parts)
            # gap_agent.py의 build_deterministic_reasons()와 같은 철학 — "왜 필요한가"를 LLM의
            # 창작에 맡기지 않고, 이미 검증된 사실(github_eval의 결과)을 그대로 문장 템플릿에 꽂아 만듦
    return reasons


def scrub_invented_paths(coaching: dict, valid_paths: set[str]) -> dict:
    """코칭 결과에서 지어낸 파일 경로를 결정적으로 제거한다.

    프롬프트는 "파일을 지어내지 말 것"을 지시하지만 LLM 지시만으로는 새는 지점 —
    github_eval의 relevant_files 검증(_validate_project_context)과 같은 원칙을
    코칭 텍스트에도 적용한다. valid_paths는 이미 실제 레포 트리와 대조된 경로 집합.

    - project_suggestions: how/why가 없는 경로를 언급하면 근거 자체가 환각 → 항목 제거
    - learning_recommendations: 스킬 갭 자체는 결정적 gap 분석 산출이므로 유지하되,
      지어낸 경로가 든 문장만 how에서 제거 (비면 프론트가 해당 줄 숨김)
    """
    if not isinstance(coaching, dict):
        return coaching
        # coaching이 dict가 아니면(예: JSON 파싱 실패로 {"raw": ..., "error": ...} 형태) 손댈 게 없어 그대로 반환

    kept_projects = []
    removed: list[str] = []
    for s in coaching.get("project_suggestions") or []:
        if not isinstance(s, dict):
            continue
        text = f"{s.get('why', '')} {s.get('how', '')}"
        ghost = _invented_paths(text, valid_paths)
        if ghost:
            removed.append(f"{s.get('add_skill') or s.get('skill')} → {ghost}")
            continue
            # 지어낸 경로가 하나라도 있으면 이 project_suggestion 항목 자체를 통째로 버림 —
            # "부분적으로만 걸러내기"가 아니라 "근거 자체가 오염됐으니 항목 전체를 신뢰 불가"로 판단
        kept_projects.append(s)
    if "project_suggestions" in coaching:
        coaching["project_suggestions"] = kept_projects

    for s in coaching.get("learning_recommendations") or []:
        if not isinstance(s, dict) or not s.get("how"):
            continue
        sentences = re.split(r"(?<=\.)\s+", s["how"])
        # (?<=\.)\s+ → lookbehind로 마침표 뒤 공백을 기준으로 문장을 나눔 (마침표 자체는 앞 문장에 남김)
        clean = [snt for snt in sentences if not _invented_paths(snt, valid_paths)]
        if len(clean) != len(sentences):
            removed.append(f"{s.get('skill')} → how 문장 정리")
            s["how"] = " ".join(clean).strip()
            # learning_recommendations는 project_suggestions와 다르게, 항목 전체를 버리지 않고
            # "지어낸 경로가 든 문장만" 골라서 제거 — 이 갭 분석 자체는 결정적으로 이미 검증됐으니
            # 문장 하나 잘못됐다고 통째로 버릴 필요는 없다는 판단

    if removed:
        coaching["scrubbed_paths"] = removed   # 관측용 흔적
    return coaching


# ── 결정적 수치 산출 (LLM 환각 차단) ─────────────────────────────
def _confidence_from_consensus(consensus: dict) -> str:
    """consensus 검증 분포로 신뢰도 등급을 결정적으로 산출한다.

    Verified/Corroborated 비율 >=0.6 → high, >=0.3 → medium, 그 외 → low.
    """
    if not consensus:
        return "low"
        # 아무 교차검증 데이터가 없으면 가장 보수적인(신뢰 낮음) 등급으로 시작
    verifs = [(d or {}).get("verification") for d in consensus.values()]
    strong = sum(1 for v in verifs if v in ("Verified", "Corroborated"))
    ratio = strong / len(verifs)
    if ratio >= 0.6:
        return "high"
    if ratio >= 0.3:
        return "medium"
    return "low"
    # 이 함수가 LLM에게 "신뢰도를 판단해줘"라고 절대 묻지 않는 이유 — CLAUDE.md의
    # "consensus/critic LLM 없음" 원칙이 그대로 코드로 구현된 부분. 순전히 숫자 계산(비율)만으로 등급 결정


def _match_rate_from_tools(tool_results: list[dict]) -> float | None:
    """gap_analysis 도구 결과에서 match_rate를 가져온다 (없으면 None)."""
    for r in tool_results:
        res = r.get("result")
        if r.get("tool") == "gap_analysis" and isinstance(res, dict) and "match_rate" in res:
            return res["match_rate"]
    return None
    # 여러 도구 결과 중 "gap_analysis"라는 이름의 도구가 계산해준 진짜 match_rate를 찾아 그대로 씀 —
    # LLM이 리포트에 적어낸 match_rate는 신뢰하지 않고, 도구(코드)가 계산한 원본 숫자를 그대로 가져다 쓰는 것


_ADVICE_BY_CONFIDENCE = {
    "low": "GitHub·포트폴리오를 추가하면 보유 스킬의 신뢰도가 올라가 더 정확한 분석이 가능합니다.",
    "medium": "일부 스킬은 코드 근거가 약합니다. GitHub 등으로 보강하면 신뢰도가 올라갑니다.",
    "high": "보유 스킬 대부분이 코드·복수 소스로 검증되었습니다.",
}
# advice(조언 문구)조차 LLM이 자유롭게 쓰게 두지 않고, confidence 등급별로 미리 정해둔 3개 문장 중
# 하나를 그대로 고르게 함 — 조언 문구까지 결정적으로 고정한, 이 프로젝트에서 가장 엄격한 통제 지점


def _excerpt_around_keyword(skill: str, text: str, window: int = 90) -> str:
    """공고 원문에서 스킬 키워드 주변 window자를 잘라 발췌한다.

    단순히 앞에서 90자를 자르면 키워드가 문장 뒷부분에 있을 때 발췌에서 잘려나가
    "왜 이게 근거인지" 확인이 안 되는 문제가 있었다 (예: Docker 발췌인데 정작
    'Docker'가 안 보임). 키워드 위치를 찾아 그 주변으로 창을 잡는다.
    """
    from src.common.text_match import keywords_for, word_match
    # 지난번 본 그 공용 유틸리티가 여기서도 재사용됨 — 프로젝트 전역에서 몇 번째 재사용인지 셀 수 없을 정도

    if not text:
        return ""
    for kw in keywords_for(skill):
        if word_match(kw, text.lower()):
            idx = text.lower().find(kw)
            if idx >= 0:
                start = max(0, idx - window // 2)
                end = min(len(text), idx + len(kw) + window // 2)
                # 키워드가 발견된 위치(idx)를 기준으로 앞뒤로 window//2씩 잘라서 "키워드가 중앙 근처에 오는" 발췌 생성
                # max(0, ...)와 min(len(text), ...)로 문자열 범위를 벗어나지 않게 방어
                snippet = text[start:end].strip()
                prefix = "…" if start > 0 else ""
                suffix = "…" if end < len(text) else ""
                # 잘린 부분이 있으면 말줄임표(…)를 붙여서 "이건 전체 문장의 일부를 발췌한 것"이라고 시각적으로 표시
                return f"{prefix}{snippet}{suffix}"
    return text[:window].strip() + ("…" if len(text) > window else "")
    # 어떤 키워드도 못 찾으면(이례적 상황) 그냥 맨 앞 90자를 fallback으로 반환


def build_deterministic_reasons(
    missing_required: list[dict],
    verify_results: dict,
    consensus: dict,
    neighbors: dict[str, list[str]],
) -> dict[str, str]:
    """부족 스킬별 '왜 필요한가'를 그래프 데이터만으로 조립한다 → {정규화 스킬명: reason}.

    코칭 LLM의 reason이 "복잡한 문제 해결에 필요합니다" 같은 일반론으로 후퇴하는
    근본 원인은 인용할 사실이 없다는 것 — match_rate를 코드가 덮어쓰는 것과 같은
    원칙으로, reason도 공고 발췌·요구 건수·보유 스킬 연결(전부 검증된 사실)로
    결정적으로 만든다. 템플릿이므로 거짓말이 구조적으로 불가능하다.

    재료가 하나도 없는 스킬은 맵에서 제외 — 그 경우만 LLM reason이 유지된다.
    """
    consensus = consensus or {}
    held_norm = {normalize_skill(k): (v or {}).get("verification") for k, v in consensus.items()}
    reasons: dict[str, str] = {}

    for item in missing_required or []:
        raw = item.get("skill") if isinstance(item, dict) else str(item)
        if not raw:
            continue
        name = normalize_skill(raw)
        parts: list[str] = []

        # ① 요구 건수 (gap_analysis의 weight = 해당 스킬을 필수로 건 공고 수)
        weight = item.get("weight") if isinstance(item, dict) else None
        if weight:
            parts.append(f"이 직군 공고 {weight}건이 필수로 요구합니다.")

        # ② 공고 원문 발췌 (verify_skills가 이미 가져온 증거 — 회사명 + 요건 문장)
        vr = verify_results.get(raw) or verify_results.get(name) or {}
        for ev in (vr.get("evidence") or [])[:1]:
            company = (ev.get("company") or "").strip()
            text = _excerpt_around_keyword(name, " ".join((ev.get("text") or "").split()))
            # " ".join(text.split()) → 연속 공백/개행을 전부 단일 공백으로 정리하는 관용적 트릭
            if text:
                prefix = f"{company} 공고" if company else "실제 공고"
                parts.append(f'{prefix}: "{text}"')

        # ③ 보유 스킬과의 연결 (CO_OCCURS 이웃 ∩ consensus 보유)
        for nb in neighbors.get(raw, neighbors.get(name, [])):
            nb_norm = normalize_skill(nb)
            grade = held_norm.get(nb_norm)
            if grade:
                grade_ko = {"Verified": "검증됨", "Corroborated": "교차확인"}.get(grade, "보유")
                parts.append(f"보유한 {nb_norm}({grade_ko})와 공고에서 자주 함께 요구되는 인접 스킬입니다.")
                break
                # 첫 번째로 매칭되는 이웃 스킬 하나만 언급하고 멈춤(break) — 여러 개를 다 나열하지 않음

        if parts:
            reasons[name] = " ".join(parts)
            # ①②③ 중 하나라도 재료가 있으면 그것들을 이어붙여 reason으로 확정.
            # 셋 다 없으면 reasons dict에 이 스킬 항목 자체가 안 생기고, 그럴 때만 LLM이 쓴 원래 reason이 남음
    return reasons


def _apply_deterministic_metrics(report: dict, consensus: dict, tool_results: list[dict]) -> dict:
    """LLM이 생성한 신뢰도·적합도 수치를 결정적 값으로 덮어쓴다.

    confidence_level: consensus 분포로 코드 산출.
    match_rate: gap_analysis 도구 결과가 있으면 그 값으로(없으면 기존 유지).
    fit_score: match_rate와 중복이라 제거.
    advice: confidence 등급에 따라 결정적으로.
    """
    conf = _confidence_from_consensus(consensus)
    report["confidence_level"] = conf
    mr = _match_rate_from_tools(tool_results)
    if mr is not None:
        report["match_rate"] = mr
    report.pop("fit_score", None)
    # .pop(키, None) → 그 키가 있으면 제거, 없어도 에러 안 남(기본값 None을 반환하고 조용히 넘어감)
    # LLM이 혹시 fit_score라는 중복 필드를 만들어냈을 경우를 대비한 정리
    report["advice"] = _ADVICE_BY_CONFIDENCE[conf]
    return report
    # 이 함수 하나에 이 프로젝트의 "LLM 생성 → 결정적 코드로 덮어쓰기" 철학이 압축되어 있음.
    # generate_report()가 LLM 호출 직후 반드시 이 함수를 거치게 되어 있어서, 최종 사용자가 보는
    # match_rate·confidence_level·advice는 전부 100% 코드가 계산한 값이지 LLM이 지어낸 값이 아님


def create_call_model(tools: list["BaseTool"]):
    """Gap ReAct 루프의 call_model 노드 팩토리 (툴 바인딩 필요)."""
    _llm_with_tools = _get_gap_llm().bind_tools(tools)
    # 팩토리가 실행되는 시점(그래프 조립 시)에 딱 한 번만 bind_tools를 호출 — 매 턴마다 다시 바인딩하지 않음

    def call_model(state: AppState) -> dict:
        iteration = state.get("iteration", 0) + 1
        system = SystemMessage(content=_GAP_SYSTEM_PROMPT)
        response = _llm_with_tools.invoke([system] + list(state["messages"]))
        # [system] + list(state["messages"]) → 시스템 프롬프트를 맨 앞에 붙이고, 그 뒤에 지금까지의
        # 대화 기록 전체를 이어붙여 LLM에 전달. 매 턴마다 전체 히스토리를 다시 보내는 방식(무상태 API 호출)
        return {"messages": [response], "iteration": iteration}
        # 여기서 반환하는 {"messages": [response]}가 state.py의 add_messages 리듀서를 거쳐
        # 기존 messages 리스트 뒤에 "이어붙여"진다 — 절대 덮어쓰기가 아님 (지난번 그 개념의 실전 사례)

    return call_model


def create_synthesizer(neo4j=None):
    """Gap 루프 결과 → gap_result 리포트 생성 노드 팩토리 (기본 LLM 사용).

    neo4j가 주어지면 부족 스킬 reason을 그래프 데이터로 결정적 조립해
    gap_result["deterministic_reasons"]에 저장한다 (finalize_coach가 덮어쓰기에 사용).
    """
    _llm = _get_gap_llm()

    def generate_report(state: AppState) -> dict:
        """Gap 루프 툴 결과를 수집해 gap_result JSON을 생성하고 Coach 초기 메시지를 세팅한다."""
        tool_results = []
        for msg in state["messages"]:
            if isinstance(msg, ToolMessage):
                try:
                    content = json.loads(msg.content) if isinstance(msg.content, str) else msg.content
                except Exception:
                    content = msg.content
                tool_results.append({"tool": msg.name, "result": content})
                # gap_agent.py 시각화 때 설명했던 그 지점 — 루프의 마지막 텍스트는 안 읽고,
                # 루프 내내 쌓인 ToolMessage들만 여기서 다시 모음

        # 합의(consensus)를 읽어 각 보유 스킬의 verification 상태를 프롬프트에 노출한다.
        consensus = state.get("consensus") or {}
        if consensus:
            consensus_lines = "\n".join(
                f"- {skill}: {(info or {}).get('verification', 'Claimed')}"
                for skill, info in consensus.items()
            )
        else:
            consensus_lines = "(합의 데이터 없음 — verification 은 모두 Claimed 로 간주)"

        prompt = _GAP_REPORT_PROMPT.format(
            tool_results=json.dumps(tool_results, ensure_ascii=False, indent=2),
            consensus=consensus_lines,
        )

        response = _llm.invoke([
            SystemMessage(content="당신은 채용 시장 분석 전문가입니다. JSON만 출력하세요."),
            {"role": "user", "content": prompt},
        ])
        # 리스트 안에 SystemMessage 객체와 평범한 dict({"role": "user", ...})가 섞여 있음 —
        # LangChain의 invoke()는 이 두 형태를 모두 받아들이도록 유연하게 설계돼 있음

        raw = response.content.strip().replace("```json", "").replace("```", "").strip()
        try:
            report = json.loads(raw)
            # 신뢰도·적합도 수치를 결정적 값으로 덮어쓴다 (LLM 환각 차단)
            report = _apply_deterministic_metrics(report, consensus, tool_results)
        except json.JSONDecodeError:
            report = {"raw": raw, "error": "JSON 파싱 실패"}

        # 부족 스킬 reason 결정적 조립 — 공고 발췌(verify_skills)·요구 건수(gap_analysis)·
        # CO_OCCURS 보유 스킬 연결로. finalize_coach가 LLM reason을 이 값으로 덮어쓴다.
        if not report.get("error"):
            verify_results: dict = {}
            missing_with_weight: list[dict] = []
            for r in tool_results:
                res = r.get("result")
                if r.get("tool") == "verify_skills" and isinstance(res, dict):
                    verify_results.update({k: v for k, v in res.items() if isinstance(v, dict)})
                if r.get("tool") == "gap_analysis" and isinstance(res, dict):
                    missing_with_weight = [m for m in res.get("missing_required") or [] if isinstance(m, dict)]
                    # gap_analysis 결과 안의 missing_required(weight 정보 포함)를 별도로 확보 —
                    # LLM이 최종 리포트에 옮겨 적으며 weight를 빠뜨렸을 수도 있어서, 원본 도구 결과를 우선 신뢰
            missing_items = missing_with_weight or [
                m for m in (report.get("missing_required") or []) if isinstance(m, dict)
            ]
            neighbor_map: dict = {}
            if neo4j is not None and missing_items:
                names = [m.get("skill") for m in missing_items if m.get("skill")]
                neighbor_map = neo4j.get_skill_neighbors(names) or {}
            report["deterministic_reasons"] = build_deterministic_reasons(
                missing_items, verify_results, consensus, neighbor_map,
            )

        # Coach 루프 시작 메시지 초기화 — 갭 분석 + GitHub 소스코드 분석 결과
        # GapState(서브그래프)에서는 project_contexts 직접, AppState에서는 github_eval 경유
        contexts = (
            state.get("project_contexts")
            or (state.get("github_eval") or {}).get("project_contexts")
            or []
        )
        # 이 함수가 GapState(gap_agent 서브그래프 내부)에서 호출될 수도, AppState(Supervisor 레벨)에서
        # 호출될 수도 있어서 — 두 경우 모두 대응하는 이중 경로. state.py에서 본 "이 함수가 두
        # State 타입 모두와 호환되게 설계됐다"는 메모리 기록(state-agnostic)과 일치하는 부분

        # relevant_files가 없는 스킬에 code_anchor=false 표시 — Coach가 파일 없는 스킬을 project_suggestions에 넣지 않도록
        for ctx in contexts:
            for sa in (ctx.get("skill_assessments") or []):
                sa["code_anchor"] = bool(sa.get("relevant_files"))
                # relevant_files 리스트가 비어있지 않으면 True, 비어있으면 False —
                # coach_call_model의 프롬프트 규칙("code_anchor=false면 project_suggestions 제외")이
                # 참조하는 그 플래그가 여기서 만들어짐
        # GAP 스킬 면접 컨텍스트 문서 조회
        gap_skills = _gap_missing_names(report)
        skill_context = _load_skill_context(gap_skills)

        # Verified/Corroborated 스킬 — strength 코칭 대상 + 면접 컨텍스트
        # 포트폴리오 핵심 스킬을 코드에서 우선순위로 보장 (LLM에 맡기지 않음)
        # ponytail: AI/LLM Engineer 전용 우선순위 — 다직군 지원 시 Neo4j 가중치로 동적화 필요
        _STRENGTH_PRIORITY = ["LangGraph", "RAG", "LLM", "Docker", "Python", "PostgreSQL"]
        # 이 리스트 안의 "ponytail:" 주석은 CLAUDE.md에도 나온 ponytail 스킬의 관례 —
        # "지금은 하드코딩된 단순화지만, 한계가 뭔지와 다음에 뭘 해야 할지"를 명시하는 코멘트
        verified_skills = [
            skill for skill, info in (consensus or {}).items()
            if (info or {}).get("verification") in ("Verified", "Corroborated")
        ]
        verified_skills = sorted(
            verified_skills,
            key=lambda s: (_STRENGTH_PRIORITY.index(s) if s in _STRENGTH_PRIORITY else len(_STRENGTH_PRIORITY))
        )
        # 정렬 키: _STRENGTH_PRIORITY 리스트에 있으면 그 인덱스(작을수록 앞), 없으면 리스트 길이(=제일 뒤로 밀림)
        # 즉 "미리 정해둔 핵심 스킬 순서대로 앞에 오고, 나머지는 뒤에 임의 순서로" 정렬됨
        strength_context = _load_skill_context(verified_skills)
        strength_list = "\n".join(f"- {s}" for s in verified_skills) or "(없음)"

        # repo_paths(레포 전체 경로 목록)는 환각 검증용 메타데이터 — 프롬프트에서 제외 (토큰 폭발 방지)
        contexts_for_prompt = [
            {k: v for k, v in ctx.items() if k != "repo_paths"} for ctx in contexts
        ]
        # 딕셔너리 컴프리헨션으로 "repo_paths를 뺀 나머지 전부"를 복사 — github_eval.py에서
        # "repo_paths를 검증용으로만 심어뒀다"고 봤던 그 필드가 여기서 실제로 걸러짐
        coach_init = (
            f"[강점 어필 대상 — Verified/Corroborated 스킬]\n{strength_list}"
            + (("\n\n[강점 스킬 면접 컨텍스트]\n" + json.dumps(strength_context, ensure_ascii=False, indent=2))
               if strength_context else "")
            + (("\n\n[GAP 스킬 면접 컨텍스트]\n" + json.dumps(skill_context, ensure_ascii=False, indent=2))
               if skill_context else "")
            + "\n\n아래 갭 분석을 바탕으로 코칭하세요.\n"
            + json.dumps(report, ensure_ascii=False, indent=2)
            + (("\n\n[GitHub 프로젝트 분석]\n" + json.dumps(contexts_for_prompt, ensure_ascii=False, indent=2))
               if contexts else "\n\n[GitHub 프로젝트] 소스코드 없음 — 연계 학습 위주로 코칭하세요.")
        )
        # 여러 조각(문자열 + 조건부 문자열)을 +로 이어붙여 coach_agent의 첫 메시지를 조립.
        # 조건부 부분은 "그 데이터가 있을 때만" 섹션을 추가하는 삼항 표현식 패턴이 반복됨

        # gap 루프 정보 수집 — CoachState에는 messages/iteration이 없으므로 여기서 계산해 전달
        tool_calls_seen: list[str] = []
        for msg in state.get("messages") or []:
            if isinstance(msg, ToolMessage) and getattr(msg, "name", None) and msg.name not in tool_calls_seen:
                tool_calls_seen.append(msg.name)
                # 실제 호출된 도구 "이름"들을 중복 없이 순서대로 수집 (몇 번 호출됐는지가 아니라 "어떤 도구들"이었는지)
        gap_trace = {
            "tool_calls": tool_calls_seen,
            "iterations": state.get("iteration") or 0,
        }

        return {
            "gap_result": report,
            "project_contexts": contexts,
            "gap_trace": gap_trace,             # _build_trace가 CoachState에서 읽을 수 있도록 저장
            "coach_messages": [HumanMessage(content=coach_init)],
            "coach_iteration": 0,
        }
        # 이 반환값이 gap_agent 서브그래프의 결과를 CoachState로 넘겨주는 다리 역할 —
        # coach_messages를 여기서 처음 만들어서 coach_agent의 ReAct 루프가 시작될 재료를 준비함

    return generate_report


def make_tools_node(tools_list: list):
    """Gap Agent용 커스텀 tools 노드 — source_id dedup 포함."""
    tool_map = {t.name: t for t in tools_list}
    # 도구 리스트를 {"gap_analysis": <도구객체>, "verify_skills": <도구객체>, ...} 형태의 dict로 변환 —
    # LLM이 tool_calls에서 "이름"으로 어떤 도구를 부를지 지정하면, 이 dict에서 이름으로 즉시 찾아 실행하기 위함

    def tools_node(state) -> dict:
        last_msg = state["messages"][-1]
        # LLM의 방금 응답(도구 호출 요청이 담긴 그 메시지)
        seen: set[str] = set(state.get("seen_source_ids") or [])
        new_seen: set[str] = set(seen)
        new_messages: list[ToolMessage] = []

        for tc in last_msg.tool_calls:
            # 한 번의 LLM 응답에 여러 도구 호출이 동시에 들어있을 수 있어서(예: verify_skills를
            # 한 번에 여러 인자로) for문으로 하나씩 처리
            fn = tool_map[tc["name"]]
            args = tc["args"]
            if tc["name"] == "gap_analysis":
                # tools.py의 gap_analysis(consensus=...)는 LLM이 채우는 인자가 아니라, 이번 요청의
                # 실제 consensus(state["consensus"])를 여기서 직접 주입함 — LLM이 자연어 문맥에서
                # 검증 등급을 다시 파싱해 넘기게 하는 것보다 훨씬 정확하고, Neo4j 왕복도 필요 없음
                args = {**args, "consensus": state.get("consensus") or {}}
            try:
                result = fn.invoke(args)
                # @tool로 감싸진 함수는 .invoke(인자dict)로 호출 — 일반 함수 호출(fn(**args))과
                # 다르게 LangChain 도구 인터페이스를 통해 실행됨
            except Exception as e:
                result = [{"error": str(e)}]
                # 도구 실행 자체가 실패해도(Neo4j 연결 오류 등) 에러 정보를 담은 결과로 처리 —
                # 전체 그래프가 죽지 않고, 이 에러 메시지가 LLM에게 다음 턴에 전달되어
                # "이 도구는 실패했으니 다른 방법을 시도하자"고 스스로 판단할 여지를 줌

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
                    # verify_skills 도구만 특별 취급: 이미 이전 턴에서 근거로 인용한 공고(source_id)를
                    # seen_source_ids로 기억해뒀다가, 같은 공고가 또 근거로 나오면 걸러냄.
                    # 왜 필요한가 — LLM이 매번 verify_skills를 부를 때마다 같은 공고를 반복 인용하면
                    # 리포트에 "다양한 근거"인 것처럼 보이지만 실제로는 한두 개 공고만 계속 우려먹는
                    # 착시가 생기므로, 이미 쓴 근거는 새로 안 세도록 관리

            content = (
                result if isinstance(result, str)
                else json.dumps(result, ensure_ascii=False)
            )
            new_messages.append(ToolMessage(
                content=content,
                tool_call_id=tc["id"],
                # tool_call_id — 이 결과가 "어떤 도구 호출 요청에 대한 응답인지"를 짝지어주는 식별자.
                # LLM이 한 번에 여러 도구를 불렀을 때, 각 결과가 어느 요청의 응답인지 구분하는 데 필요
                name=tc["name"],
            ))

        return {"messages": new_messages, "seen_source_ids": list(new_seen)}
        # messages는 add_messages 리듀서로 이어붙여지고, seen_source_ids는 (리듀서가 없으니) 그냥
        # 새 값으로 완전히 교체됨 — 그래서 new_seen이 "기존 seen을 포함한" 전체 집합이어야 정보가 안 사라짐

    return tools_node


def make_coach_tools_node(coach_tools_list: list):
    """Coach Agent용 tools 노드 — coach_messages에 결과를 추가한다."""
    tool_map = {t.name: t for t in coach_tools_list}

    def coach_tools_node(state) -> dict:
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
        # make_tools_node와 거의 동일한 구조지만, source_id dedup 로직이 없고 채널도 coach_messages —
        # Coach 툴(verify_suggestion, related_skills)은 같은 근거를 반복 인용하는 문제가 덜 중요하다고 판단된 듯

    return coach_tools_node


def create_coach_nodes(coach_tools: list["BaseTool"]):
    """Coach Agent 노드 팩토리 — coach_call_model, finalize_coach 반환."""
    if not os.getenv("OPENAI_API_KEY"):
        raise EnvironmentError("OPENAI_API_KEY 환경변수가 필요합니다.")

    _coach_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, max_retries=6)
    # 여기는 _get_gap_llm()의 캐시된 인스턴스를 재사용하지 않고 별도로 새 ChatOpenAI를 만듦 —
    # Gap용과 Coach용 LLM 클라이언트가 분리돼 있음(둘 다 같은 모델이지만 인스턴스는 다름)
    _coach_llm_with_tools = _coach_llm.bind_tools(coach_tools)

    def coach_call_model(state: AppState) -> dict:
        iteration = state.get("coach_iteration", 0) + 1
        system = SystemMessage(content=_COACH_SYSTEM_PROMPT + "\n\n" + _PROJECT_DESIGN_CONTEXT)
        # 코칭 시스템 프롬프트 뒤에 "이 프로젝트 설계 의사결정" 배경지식을 이어붙임 — 면접 코칭이
        # "이 프로젝트를 왜 이렇게 설계했는지" 설명하는 법을 알려줄 수 있으려면 그 배경지식이 필요하기 때문
        response = _coach_llm_with_tools.invoke([system] + list(state["coach_messages"]))
        return {"coach_messages": [response], "coach_iteration": iteration}
        # gap_agent의 call_model과 완전히 같은 구조 — 채널만 messages→coach_messages, iteration→coach_iteration으로 바뀜

    def finalize_coach(state: AppState) -> dict:
        """Coach 루프 종료 후 최종 AIMessage를 파싱해 final_report를 조립한다."""
        # coach_messages에서 마지막 AIMessage의 텍스트 추출
        last_ai = None
        for msg in reversed(list(state.get("coach_messages") or [])):
            # reversed() — 리스트를 뒤에서부터 순회. 가장 최근 메시지부터 확인하려는 것
            if hasattr(msg, "content") and not getattr(msg, "tool_calls", None):
                last_ai = msg
                break
                # "content 속성이 있고 tool_calls는 비어있는" 메시지 = 도구 호출이 아니라 순수 텍스트로 답한
                # 마지막 AI 메시지. 뒤에서부터 찾아서 처음 만나는 게 바로 그 "최종 답변"
        # gap_agent의 generate_report와 달리, coach_agent는 이 루프의 "최종 텍스트"를 실제로 씀 —
        # gap_agent는 ToolMessage만 모아 별도 LLM으로 리포트를 다시 만들었지만, coach_agent는
        # 마지막 AI 응답 자체가 곧 최종 코칭 결과라서 별도의 synthesizer가 없음

        coaching_dict: dict = {}
        if last_ai:
            raw = (last_ai.content or "").strip().replace("```json", "").replace("```", "").strip()
            try:
                coaching_dict = json.loads(raw)
            except json.JSONDecodeError:
                coaching_dict = {"raw": raw, "error": "JSON 파싱 실패"}

        # 지어낸 파일 경로 결정적 제거 — 유효 경로 = 레포 전체 경로(repo_paths) ∪ 검증된 relevant_files
        # (relevant_files만 쓰면 실존하지만 언급 안 된 파일까지 환각으로 오판)
        contexts_all = state.get("project_contexts") or []
        valid_paths: set[str] = set()
        for ctx in contexts_all:
            valid_paths.update(ctx.get("repo_paths") or [])
            for sa in (ctx.get("skill_assessments") or []):
                valid_paths.update(sa.get("relevant_files") or [])
            # repo_paths(레포 전체 경로)까지 유효 경로에 포함시키는 이유가 주석에 명시됨 —
            # relevant_files는 "이 스킬과 관련해 언급된 파일"만 담고 있어서, 코칭 LLM이 그 외의
            # (하지만 실제로 존재하는) 다른 파일을 언급하면 relevant_files만으로는 오탐(가짜 환각 판정)이 남
        coaching_dict = scrub_invented_paths(coaching_dict, valid_paths)

        gap_raw = state.get("gap_result") or {}

        # 학습 추천 reason을 결정적 조립값으로 덮어쓴다 — LLM의 일반론("~에 필수적입니다")을
        # 공고 발췌·요구 건수·보유 스킬 연결(검증된 사실)로 교체. match_rate 덮어쓰기와 같은 원칙.
        det_reasons = gap_raw.get("deterministic_reasons") or {}
        if det_reasons and isinstance(coaching_dict, dict):
            for rec in coaching_dict.get("learning_recommendations") or []:
                if not isinstance(rec, dict):
                    continue
                key = normalize_skill(rec.get("skill") or "")
                if key in det_reasons:
                    rec["reason"] = det_reasons[key]
                    # generate_report()가 이미 만들어둔 deterministic_reasons를 여기서 다시 꺼내와
                    # coach_agent가 LLM으로 새로 만든 reason을 덮어씀 — 같은 데이터를 두 노드가
                    # 다른 시점에 나눠서 활용하는 구조 (계산은 한 번만, 사용은 두 곳에서)

        # project_suggestions의 why도 같은 원칙으로 — "추가하면 강화됩니다" 가정형 서술을
        # relevant_files·current_usage(검증된 코드 관측 사실)로 교체.
        det_project_reasons = build_deterministic_project_reasons(contexts_all)
        if det_project_reasons and isinstance(coaching_dict, dict):
            for rec in coaching_dict.get("project_suggestions") or []:
                if not isinstance(rec, dict):
                    continue
                key = normalize_skill(rec.get("add_skill") or rec.get("skill") or "")
                if key in det_project_reasons:
                    rec["why"] = det_project_reasons[key]
        # 4개 소스(이력서·포폴·GitHub·배포) 교차검증 결과를 신뢰도 축 산출물로 surface한다.
        from src.agent.consensus import build_verification_summary
        verification = build_verification_summary(state.get("consensus") or {})

        return {
            "coaching_result": coaching_dict,
            "final_report": {
                "gap": gap_raw,            # 적합도 축 (match_rate) + 신뢰도(confidence) + advice + skills
                "verification": verification,  # 신뢰도 축 — 스킬별 검증 등급 + 뒷받침 소스
                "coaching": coaching_dict,
                "trace": _build_trace(state, coaching=coaching_dict),
                # 여기서 coaching=coaching_dict를 명시적으로 넘기는 이유가 _build_trace()의 docstring에
                # 설명된 그 이유 — 이 함수(finalize_coach)의 반환값이 아직 state에 병합되기 전이라
                # state["coaching_result"]로는 지금 막 만든 coaching_dict를 못 읽기 때문
            },
        }

    return coach_call_model, finalize_coach
