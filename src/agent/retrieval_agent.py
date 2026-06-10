# 직무 요구 스킬과 공고 근거를 검색해 retrieved_context를 채우는 Retrieval 노드
from __future__ import annotations

from typing import TYPE_CHECKING

from src.agent.state import AppState
from src.agent.tools import _JOB_SKILLS_QUERY

if TYPE_CHECKING:
    from src.storage.chroma_client import ChromaClient
    from src.storage.neo4j_client import Neo4jClient


def create_retrieval_node(neo4j: "Neo4jClient", chroma: "ChromaClient"):
    """Retrieval 노드 팩토리.

    1. Neo4j에서 직군 요구 스킬(REQUIRES 상위)을 조회
    2. Chroma에서 직무 키워드로 required 섹션 근거 검색
    결과를 retrieved_context(list[dict])로 병합한다.
    """

    def retrieval_node(state: AppState) -> dict:
        job_family = state["job_family"]
        context: list[dict] = []

        try:
            chunks = chroma.search(job_family, n_results=5, section_type="required")
            for c in chunks:
                context.append({
                    "source_id": c["source_id"],
                    "company": c.get("company", ""),
                    "job_title": c.get("job_title", ""),
                    "text": c["original_text"][:400],
                })
        except Exception as e:
            print(f"[retrieval] Chroma 근거 검색 실패: {e}")

        try:
            rows = neo4j.execute_query(_JOB_SKILLS_QUERY, job_family=job_family)
            required = [r for r in rows if r.get("importance") == "REQUIRES"]
            for r in required[:10]:
                context.append({"skill": r["skill"], "weight": r.get("weight") or 1})
        except Exception as e:
            print(f"[retrieval] Neo4j 요구스킬 조회 실패: {e}")

        return {"retrieved_context": context}

    return retrieval_node
