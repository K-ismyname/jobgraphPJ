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
_COACH_SYSTEM_PROMPT = """당신은 커리어 코치입니다. 지원자의 GitHub 프로젝트와 직군 부족 스킬을 보고 두 종류의 코칭을 합니다.

1. 프로젝트 보강: 각 GitHub 프로젝트 프로필(summary·tech_stack·observations)과 직군 부족 스킬을 보고, "이 프로젝트에 무엇을 추가/발전시키면 부족 스킬이 코드로 실증되는가"를 제안하세요. observations(예: Dockerfile 없음·테스트 없음)를 우선 활용하세요.
2. 연계 학습: related_skills 툴에 보유 스킬을 넘겨, 자주 함께 요구되는 스킬 중 미보유를 학습 추천하세요.

규칙:
- 갖지 않은 스킬을 이력서에 써넣으라고 하지 마세요. 프로젝트로 실증하거나 학습하라고 안내하세요.
- GitHub 프로젝트가 없으면 project_suggestions는 비우고 연계 학습 위주로 작성하세요.
- 필요하면 verify_suggestion으로 공고 근거를 확인하세요.
- 모든 검토가 끝나면 도구 호출 없이 최종 JSON을 반환하세요.

최종 출력 형식 (코드 펜스 없이):
{{
  "summary": "전체 코칭 방향 2-3문장",
  "project_suggestions": [
    {{"repo": "owner/repo (일반 제안이면 빈 문자열)", "add_skill": "추가하면 좋은 스킬",
      "why": "직군/실증 관점 이유", "how": "이 프로젝트에 어떻게 적용하는지"}}
  ],
  "learning_recommendations": [
    {{"skill": "연계 스킬", "reason": "어떤 보유 스킬과 이어지는지"}}
  ]
}}"""


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

    tool_calls: list[str] = []
    for m in state.get("messages") or []:
        if isinstance(m, ToolMessage) and getattr(m, "name", None) and m.name not in tool_calls:
            tool_calls.append(m.name)
    if state.get("messages"):
        executed += ["seed_gap", "call_model", "tools"]
    executed.append("synthesizer")

    critic = state.get("critic_report") or {}
    removed = critic.get("removed_claims") or []
    corrections = critic.get("corrections") or []
    if critic:
        executed.append("critic")

    coaching = coaching if coaching is not None else (state.get("coaching_result") or {})
    if state.get("coaching_result"):
        executed += ["coach_call_model", "finalize_coach"]

    return {
        "executed_nodes": executed,
        "evaluators": evaluators,
        "consensus": cons,
        "gap_loop": {"tool_calls": tool_calls, "iterations": state.get("iteration") or 0},
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


def create_nodes(
    tools: list["BaseTool"],
    neo4j: "Neo4jClient",
):
    """Gap Agent 노드 팩토리 — call_model, generate_report 반환."""
    if not os.getenv("OPENAI_API_KEY"):
        raise EnvironmentError("OPENAI_API_KEY 환경변수가 필요합니다.")

    _llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
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

        # Coach 루프 시작 메시지 초기화 — 갭 분석 + GitHub 프로젝트 프로필
        profiles = (state.get("github_eval") or {}).get("profiles") or []
        coach_init = (
            "아래 갭 분석을 바탕으로 코칭하세요.\n"
            + json.dumps(report, ensure_ascii=False, indent=2)
            + (("\n\n[GitHub 프로젝트 프로필]\n" + json.dumps(profiles, ensure_ascii=False, indent=2))
               if profiles else "\n\n[GitHub 프로젝트] 없음 — 연계 학습 위주로 코칭하세요.")
        )

        return {
            "gap_result": report,
            "coach_messages": [HumanMessage(content=coach_init)],
            "coach_iteration": 0,
        }

    return call_model, generate_report


def create_coach_nodes(coach_tools: list["BaseTool"]):
    """Coach Agent 노드 팩토리 — coach_call_model, finalize_coach 반환."""
    if not os.getenv("OPENAI_API_KEY"):
        raise EnvironmentError("OPENAI_API_KEY 환경변수가 필요합니다.")

    _coach_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    _coach_llm_with_tools = _coach_llm.bind_tools(coach_tools)

    def coach_call_model(state: AppState) -> dict:
        iteration = state.get("coach_iteration", 0) + 1
        system = SystemMessage(content=_COACH_SYSTEM_PROMPT)
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
