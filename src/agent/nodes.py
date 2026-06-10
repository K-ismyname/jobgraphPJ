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
    from src.storage.chroma_client import ChromaClient
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
- verify_skills는 단 1회. 스킬당 1회 vector_search 호출 금지.
- vector_search는 시장 트렌드 등 일반 질의에만 사용하세요.
- skip:true 또는 "없음" 메시지가 있으면 graph_only로 처리하고 넘어가세요.
- 추측으로 판단 가능하면 ask_human을 쓰지 마세요."""

_GAP_REPORT_PROMPT = """아래는 지금까지 수집된 분석 데이터입니다.
이를 바탕으로 구조화된 갭 분석 리포트를 JSON으로 생성하세요.

{tool_results}

다음 JSON 형식으로 출력하세요 (코드 펜스 없이):
{{
  "job_title": "직무명",
  "match_rate": 0.0,
  "summary": "한 줄 요약",
  "have_required": ["보유 필수 스킬"],
  "unverified_required": ["보유하나 근거 약한 스킬 (confidence=low)"],
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
_COACH_SYSTEM_PROMPT = """당신은 이력서 개선 전문가입니다.
갭 분석 결과를 바탕으로 각 부족 스킬에 대해 구체적인 이력서 개선 제안을 작성합니다.

작업 절차:
1. 부족 스킬별로 이력서 개선 제안을 작성하세요.
2. 각 제안에 대해 verify_suggestion 툴로 실제 공고 근거를 확인하세요.
3. 공고 근거와 제안이 잘 맞고 충분히 구체적이면 확정하세요.
4. 근거와 맞지 않거나 너무 모호하면 제안을 수정해 다시 작성하세요.
5. 모든 스킬 검토가 끝나면 도구 호출 없이 최종 제안 목록을 JSON으로 반환하세요.

규칙:
- unverified_required 스킬은 "근거 보강 필요"로 처리하세요.
- GitHub 검증 완료 스킬(confidence=high)은 재증명 제안 불필요.
- 제안은 반드시 실제 공고 텍스트에 근거해야 합니다.
- 너무 모호한 제안("경험 추가 필요")은 반드시 구체화하세요.

최종 출력 형식 (코드 펜스 없이):
{{
  "summary": "전체 개선 방향 2-3문장",
  "suggestions": [
    {{
      "target_section": "이력서 섹션명",
      "missing_skill": "스킬명",
      "original_text": "기존 이력서 문장 (없으면 null)",
      "rewritten_text": "개선된 문장",
      "expected_impact": "이 수정의 효과 (1문장)",
      "priority": "high/medium/low",
      "verified": true
    }}
  ]
}}"""


def create_nodes(
    tools: list["BaseTool"],
    neo4j: "Neo4jClient",
    chroma: "ChromaClient",
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

        prompt = _GAP_REPORT_PROMPT.format(
            tool_results=json.dumps(tool_results, ensure_ascii=False, indent=2)
        )

        response = _llm.invoke([
            SystemMessage(content="당신은 채용 시장 분석 전문가입니다. JSON만 출력하세요."),
            {"role": "user", "content": prompt},
        ])

        raw = response.content.strip().replace("```json", "").replace("```", "").strip()
        try:
            report = json.loads(raw)
        except json.JSONDecodeError:
            report = {"raw": raw, "error": "JSON 파싱 실패"}

        # Coach 루프 시작 메시지 초기화
        coach_init = (
            "아래 갭 분석 결과를 바탕으로 부족 스킬별 이력서 개선 제안을 작성하세요.\n"
            "각 제안은 verify_suggestion으로 공고 근거를 확인한 뒤 확정하세요.\n\n"
            + json.dumps(report, ensure_ascii=False, indent=2)
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
        github_raw = state.get("github_result")

        return {
            "coaching_result": coaching_dict,
            "final_report": {
                "gap": gap_raw,
                "coaching": coaching_dict,
                "github": github_raw,
            },
        }

    return coach_call_model, finalize_coach
