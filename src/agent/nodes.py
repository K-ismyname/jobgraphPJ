# 에이전트 노드 함수 — Gap Agent(call_model, generate_report), Coach Agent(coach_call_model, finalize_coach)
from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

from src.agent.state import AppState

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool
    from src.storage.neo4j_client import Neo4jClient

# ── Gap Agent 프롬프트 ────────────────────────────────────────────
_GAP_SYSTEM_PROMPT = """당신은 AI 커리어 분석 전문가입니다.
채용공고 요구사항과 지원자 보유 스킬을 비교해 기술 갭을 분석합니다.

분석 절차:
1. gap_analysis(job_family, portfolio_skills, owner) — owner 반드시 포함. 매칭률과 부족 스킬을 계산하세요.
2. verify_skills — missing_required 중 weight 상위 5개를 한 번에 넘기세요. 1회만 호출.
3. skill_unlock — missing_required 확정 후 상위 3개 스킬 묶음으로 1회만 호출. 개별 반복 호출 금지.
4. posting_trend — 우선순위 판단이 필요한 스킬에만 선택적으로 호출.
5. 충분한 근거가 모이면 도구 호출 없이 텍스트만 반환하세요 → 리포트 생성.

규칙:
- verify_skills는 단 1회. 스킬마다 반복 호출 금지.
- skip:true 또는 "없음" 메시지가 있으면 graph_only로 처리하고 넘어가세요.
- 추측으로 판단 가능하면 ask_human을 쓰지 마세요."""

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

# ── Coach Agent 프롬프트 ─────────────────────────────────────────
_PROJECT_DESIGN_CONTEXT = """[이 프로젝트 설계 의사결정]
- LangGraph 선택: 조건 분기·루프·HITL 세 가지를 동시에 구현해야 해서. LangChain 체인만으로는 불가.
- Neo4j 선택: 직무-기술 관계(REQUIRES/CO_OCCURS) 표현 최적. 벡터DB는 관계 표현 불가.
- Chroma 제거: 검색 12건 중 11건이 키워드 매칭과 동일 결과 → 효과 없음을 측정하고 제거.
- 적합도 ⊥ 신뢰도 분리: "Python 잘 함(이력서 주장)" ≠ "Python 잘 함(GitHub 확인)". 점수와 근거를 분리.
- consensus/critic LLM 없음: 신뢰도 등급은 규칙 기반으로 결정적 산출. LLM은 숫자를 지어냄.
- 4개 평가자 병렬: resume/github/portfolio/deploy 독립 평가 후 교차검증. 이력서 주장만 믿으면 과장이 안 걸러짐.
- Corrective RAG 루프: 근거 부족하면 tools 재호출 (최대 5회). 에이전트가 "증거가 충분한가"를 스스로 판단.
- RAGAS 평가: Faithfulness=0.250(공고 간접 표현 탓), AnswerRelevancy=0.876."""

_COACH_SYSTEM_PROMPT = """당신은 커리어 코치입니다. GitHub 소스코드 분석 결과와 직군 갭을 바탕으로 두 종류의 코칭을 합니다.

[GitHub 분석 데이터 읽는 법]
project_contexts 안에 skill_assessments 목록이 있습니다. 각 항목:
- current_usage: 현재 수준 (기본 사용 / 중급 패턴 / 고급 패턴)
- used_patterns: 코드에서 이미 확인된 패턴
- missing_patterns: 이 스킬의 고급 패턴 중 아직 없는 것
- how_to_add: 이 프로젝트 파일 기준 구체적 보강 방법

[프로젝트 보강 — 2단계 판단]
1단계: skill_assessments에 있는 스킬 → missing_patterns + how_to_add로 project_suggestions 작성.

2단계: 갭 분석의 missing_required 스킬마다 판단하세요.
  project_contexts(코드 구조)를 보고 이 스킬이 이 프로젝트에 자연스럽게 추가될 수 있는가?
  YES — 구체적 파일명·함수명이 보이는가? → project_suggestions에 추가
  NO  — '이 직군에 필요하다'는 이유뿐이거나 코드에 연결점이 없는가? → learning_recommendations에만

[연계 학습]
related_skills 툴에 보유 스킬을 넘겨, 자주 함께 요구되는 스킬 중 미보유를 학습 추천하세요.

규칙:
- 2단계 판단 기준: "이 프로젝트 코드 어디에 어떻게 추가하는가"가 구체적으로 보여야 YES.
  "이 직군에 중요하다", "있으면 도움된다" 수준이면 NO → learning_recommendations.
- code_anchor=false인 스킬은 project_suggestions 후보에서 즉시 제외하세요 → learning_recommendations로.
- 현재 프로젝트 주 언어·런타임과 다른 언어(Python 프로젝트에 Java·JavaScript, Node 프로젝트에 Python 등)는
  절대 project_suggestions에 넣지 마세요 → 반드시 learning_recommendations로.
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
      "how": "구체적 파일명·함수명 포함 보강 방법"}}
  ],
  "learning_recommendations": [
    {{"skill": "연계 스킬", "reason": "어떤 보유 스킬과 이어지는지"}}
  ],
  "interview_coaching": [
    {{"type": "strength", "title": "핵심 경험 제목",
      "coaching": "면접에서 이 경험을 어떻게 표현해야 하는지 구체적 조언"}}
  ]
}}"""


def _load_skill_context(skills: list[str]) -> dict:
    """GAP 스킬 목록에 해당하는 면접 컨텍스트 문서를 로드한다."""
    path = os.path.join(os.path.dirname(__file__), "../../data/seeds/skill_interview_context.json")
    try:
        with open(os.path.normpath(path), encoding="utf-8") as f:
            db = json.load(f)
        return {s: db[s] for s in skills if s in db}
    except Exception:
        return {}


def _gap_missing_names(gap: dict) -> list[str]:
    """gap report의 missing_required에서 부족 스킬명 목록(dict/str 모두 허용)."""
    out: list[str] = []
    for item in (gap.get("missing_required") or []):
        if isinstance(item, dict) and item.get("skill"):
            out.append(item["skill"])
        elif isinstance(item, str):
            out.append(item)
    return out[:8]


def _build_trace(state: "AppState", coaching: dict | None = None) -> dict:
    """그래프 결과 state에서 실행 흔적(관측 페이지용)을 결정적으로 조립한다.

    coaching은 호출 노드(finalize_coach)가 막 만든 결과를 직접 넘긴다 — LangGraph가
    반환 dict를 state에 머지하기 전이라 state["coaching_result"]는 아직 비어 있기 때문.
    """
    from src.agent.consensus import build_verification_summary

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

    cons = build_verification_summary(state.get("consensus") or {})
    if state.get("consensus"):
        executed.append("consensus")

    # gap_trace는 synthesizer(AppState)가 채워서 CoachState에 전달 — messages/iteration을 직접 읽지 않아도 됨
    _gt = state.get("gap_trace") or {}
    tool_calls: list[str] = _gt.get("tool_calls") or []
    gap_iterations: int = _gt.get("iterations") or 0

    executed.append("synthesizer")  # Supervisor 레벨 노드 — 항상 실행됨
    if state.get("gap_result"):
        executed += ["seed_gap", "gap_agent", "call_model", "tools"]

    critic = state.get("critic_report") or {}
    removed = critic.get("removed_claims") or []
    corrections = critic.get("corrections") or []
    if critic:
        executed.append("critic")

    coaching = coaching if coaching is not None else (state.get("coaching_result") or {})
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


# ── 결정적 수치 산출 (LLM 환각 차단) ─────────────────────────────
def _confidence_from_consensus(consensus: dict) -> str:
    """consensus 검증 분포로 신뢰도 등급을 결정적으로 산출한다.

    Verified/Corroborated 비율 >=0.6 → high, >=0.3 → medium, 그 외 → low.
    """
    if not consensus:
        return "low"
    verifs = [(d or {}).get("verification") for d in consensus.values()]
    strong = sum(1 for v in verifs if v in ("Verified", "Corroborated"))
    ratio = strong / len(verifs)
    if ratio >= 0.6:
        return "high"
    if ratio >= 0.3:
        return "medium"
    return "low"


def _match_rate_from_tools(tool_results: list[dict]) -> float | None:
    """gap_analysis 도구 결과에서 match_rate를 가져온다 (없으면 None)."""
    for r in tool_results:
        res = r.get("result")
        if r.get("tool") == "gap_analysis" and isinstance(res, dict) and "match_rate" in res:
            return res["match_rate"]
    return None


_ADVICE_BY_CONFIDENCE = {
    "low": "GitHub·포트폴리오를 추가하면 보유 스킬의 신뢰도가 올라가 더 정확한 분석이 가능합니다.",
    "medium": "일부 스킬은 코드 근거가 약합니다. GitHub 등으로 보강하면 신뢰도가 올라갑니다.",
    "high": "보유 스킬 대부분이 코드·복수 소스로 검증되었습니다.",
}


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
    report["advice"] = _ADVICE_BY_CONFIDENCE[conf]
    return report


def create_nodes(tools: list["BaseTool"]):
    """Gap Agent 노드 팩토리 — call_model, generate_report 반환."""
    if not os.getenv("OPENAI_API_KEY"):
        raise EnvironmentError("OPENAI_API_KEY 환경변수가 필요합니다.")

    _llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, max_retries=6)
    _llm_with_tools = _llm.bind_tools(tools)

    def call_model(state: AppState) -> dict:
        iteration = state.get("iteration", 0) + 1
        system = SystemMessage(content=_GAP_SYSTEM_PROMPT)
        response = _llm_with_tools.invoke([system] + list(state["messages"]))
        return {"messages": [response], "iteration": iteration}

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

        raw = response.content.strip().replace("```json", "").replace("```", "").strip()
        try:
            report = json.loads(raw)
            # 신뢰도·적합도 수치를 결정적 값으로 덮어쓴다 (LLM 환각 차단)
            report = _apply_deterministic_metrics(report, consensus, tool_results)
        except json.JSONDecodeError:
            report = {"raw": raw, "error": "JSON 파싱 실패"}

        # Coach 루프 시작 메시지 초기화 — 갭 분석 + GitHub 소스코드 분석 결과
        # GapState(서브그래프)에서는 project_contexts 직접, AppState에서는 github_eval 경유
        contexts = (
            state.get("project_contexts")
            or (state.get("github_eval") or {}).get("project_contexts")
            or []
        )
        # relevant_files가 없는 스킬에 code_anchor=false 표시 — Coach가 파일 없는 스킬을 project_suggestions에 넣지 않도록
        for ctx in contexts:
            for sa in (ctx.get("skill_assessments") or []):
                sa["code_anchor"] = bool(sa.get("relevant_files"))
        # GAP 스킬 면접 컨텍스트 문서 조회
        gap_skills = _gap_missing_names(report)
        skill_context = _load_skill_context(gap_skills)

        # Verified/Corroborated 스킬 — strength 코칭 대상 + 면접 컨텍스트
        # 포트폴리오 핵심 스킬을 코드에서 우선순위로 보장 (LLM에 맡기지 않음)
        # ponytail: AI/LLM Engineer 전용 우선순위 — 다직군 지원 시 Neo4j 가중치로 동적화 필요
        _STRENGTH_PRIORITY = ["LangGraph", "RAG", "LLM", "Docker", "Python", "PostgreSQL"]
        verified_skills = [
            skill for skill, info in (consensus or {}).items()
            if (info or {}).get("verification") in ("Verified", "Corroborated")
        ]
        verified_skills = sorted(
            verified_skills,
            key=lambda s: (_STRENGTH_PRIORITY.index(s) if s in _STRENGTH_PRIORITY else len(_STRENGTH_PRIORITY))
        )
        strength_context = _load_skill_context(verified_skills)
        strength_list = "\n".join(f"- {s}" for s in verified_skills) or "(없음)"

        coach_init = (
            f"[강점 어필 대상 — Verified/Corroborated 스킬]\n{strength_list}"
            + (("\n\n[강점 스킬 면접 컨텍스트]\n" + json.dumps(strength_context, ensure_ascii=False, indent=2))
               if strength_context else "")
            + (("\n\n[GAP 스킬 면접 컨텍스트]\n" + json.dumps(skill_context, ensure_ascii=False, indent=2))
               if skill_context else "")
            + "\n\n아래 갭 분석을 바탕으로 코칭하세요.\n"
            + json.dumps(report, ensure_ascii=False, indent=2)
            + (("\n\n[GitHub 프로젝트 분석]\n" + json.dumps(contexts, ensure_ascii=False, indent=2))
               if contexts else "\n\n[GitHub 프로젝트] 소스코드 없음 — 연계 학습 위주로 코칭하세요.")
        )

        # gap 루프 정보 수집 — CoachState에는 messages/iteration이 없으므로 여기서 계산해 전달
        tool_calls_seen: list[str] = []
        for msg in state.get("messages") or []:
            if isinstance(msg, ToolMessage) and getattr(msg, "name", None) and msg.name not in tool_calls_seen:
                tool_calls_seen.append(msg.name)
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

    return call_model, generate_report


def make_tools_node(tools_list: list):
    """Gap Agent용 커스텀 tools 노드 — source_id dedup 포함."""
    tool_map = {t.name: t for t in tools_list}

    def tools_node(state) -> dict:
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

    return coach_tools_node


def create_coach_nodes(coach_tools: list["BaseTool"]):
    """Coach Agent 노드 팩토리 — coach_call_model, finalize_coach 반환."""
    if not os.getenv("OPENAI_API_KEY"):
        raise EnvironmentError("OPENAI_API_KEY 환경변수가 필요합니다.")

    _coach_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, max_retries=6)
    _coach_llm_with_tools = _coach_llm.bind_tools(coach_tools)

    def coach_call_model(state: AppState) -> dict:
        iteration = state.get("coach_iteration", 0) + 1
        system = SystemMessage(content=_COACH_SYSTEM_PROMPT + "\n\n" + _PROJECT_DESIGN_CONTEXT)
        response = _coach_llm_with_tools.invoke([system] + list(state["coach_messages"]))
        return {"coach_messages": [response], "coach_iteration": iteration}

    def finalize_coach(state: AppState) -> dict:
        """Coach 루프 종료 후 최종 AIMessage를 파싱해 final_report를 조립한다."""
        # coach_messages에서 마지막 AIMessage의 텍스트 추출
        last_ai = None
        for msg in reversed(list(state.get("coach_messages") or [])):
            if hasattr(msg, "content") and not getattr(msg, "tool_calls", None):
                last_ai = msg
                break

        coaching_dict: dict = {}
        if last_ai:
            raw = (last_ai.content or "").strip().replace("```json", "").replace("```", "").strip()
            try:
                coaching_dict = json.loads(raw)
            except json.JSONDecodeError:
                coaching_dict = {"raw": raw, "error": "JSON 파싱 실패"}

        gap_raw = state.get("gap_result") or {}
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
            },
        }

    return coach_call_model, finalize_coach
