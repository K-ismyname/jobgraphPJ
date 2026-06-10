# 에이전트 노드 함수 — call_model, generate_report
from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

from src.agent.state import AgentState

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool
    from src.storage.chroma_client import ChromaClient
    from src.storage.neo4j_client import Neo4jClient

_SYSTEM_PROMPT = """당신은 AI 커리어 분석 전문가입니다.
채용공고 요구사항과 지원자 보유 스킬을 비교해 기술 갭을 분석합니다.

분석 절차:
1. gap_analysis — 매칭률과 부족 스킬(weight 포함)을 계산하세요.
2. verify_skills — missing_required 중 weight 상위 5개를 한 번에 넘기세요.
   이 툴은 Neo4j에서 각 스킬을 REQUIRES하는 공고 ID를 찾고 Chroma에서 직접
   요건 텍스트를 fetch합니다 (유사도 검색 아님). 스킬별 루프 금지.
3. skill_unlock — 상위 부족 스킬 목록으로 지원 가능 공고 증가를 계산하세요.
4. market_insights — 필요하면 시장 현황을 파악하세요.
5. 충분한 근거가 모이면 도구 호출 없이 텍스트만 반환하세요 → 리포트 생성.

규칙:
- verify_skills는 단 1회만 호출하세요. 스킬당 1회 vector_search 호출 금지.
- vector_search는 스킬 증거 수집이 아닌 일반 질의(시장 트렌드 등)에만 사용하세요.
- skip:true 또는 "없음" 메시지가 있으면 해당 스킬을 graph_only로 처리하고 넘어가세요.
- 추측으로 판단 가능하면 ask_human을 쓰지 마세요."""

_REPORT_PROMPT = """아래는 지금까지 수집된 분석 데이터입니다.
이를 바탕으로 구조화된 갭 분석 리포트를 JSON으로 생성하세요.

{tool_results}

다음 JSON 형식으로 출력하세요 (코드 펜스 없이):
{{
  "job_title": "직무명",
  "match_rate": 0.0,
  "summary": "한 줄 요약",
  "have_required": ["보유 필수 스킬"],
  "missing_required": [{{"skill": "스킬명", "reason": "왜 중요한지 (공고 근거 포함)", "priority": "high/medium/low"}}],
  "missing_preferred": ["부족한 우대 스킬"],
  "skill_unlock": {{"skills": [], "accessible_postings": 0}},
  "coaching": ["개선 제안 1", "개선 제안 2"]
}}"""


def create_nodes(
    tools: list["BaseTool"],
    neo4j: "Neo4jClient",
    chroma: "ChromaClient",
):
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise EnvironmentError("OPENAI_API_KEY 환경변수가 필요합니다.")

    _llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    _llm_with_tools = _llm.bind_tools(tools)

    def call_model(state: AgentState) -> dict:
        iteration = state.get("iteration", 0) + 1
        system = SystemMessage(content=_SYSTEM_PROMPT)
        response = _llm_with_tools.invoke([system] + list(state["messages"]))
        return {"messages": [response], "iteration": iteration}

    def generate_report(state: AgentState) -> dict:
        """툴 실행 결과를 수집해 최종 갭 분석 리포트를 생성한다."""
        # 메시지 히스토리에서 ToolMessage 결과만 추출
        tool_results = []
        for msg in state["messages"]:
            if isinstance(msg, ToolMessage):
                try:
                    content = json.loads(msg.content) if isinstance(msg.content, str) else msg.content
                except Exception:
                    content = msg.content
                tool_results.append({"tool": msg.name, "result": content})

        prompt = _REPORT_PROMPT.format(
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

        return {"final_report": report}

    return call_model, generate_report
