# LangGraph 에이전트 공유 상태 정의
from __future__ import annotations

from typing import Annotated

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

# 무한 루프 방지 — call_model 최대 호출 횟수
MAX_ITERATIONS = 5


class AgentState(TypedDict):
    # ── 분석 입력 ──────────────────────────────────────────────
    job_title: str
    owner: str

    # ── 메시지 히스토리 (add_messages: 누적 append) ────────────
    messages: Annotated[list[BaseMessage], add_messages]

    # ── Corrective RAG 루프 제어 ────────────────────────────────
    iteration: int           # call_model 호출 횟수

    # ── vector_search dedup — 이미 인용한 source_id 추적 ──────────
    seen_source_ids: list[str]

    # ── 최종 결과 (generate 노드에서 채움) ───────────────────────
    final_report: dict | None
