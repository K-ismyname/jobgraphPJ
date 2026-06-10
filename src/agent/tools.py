# 에이전트가 사용하는 툴 정의 — Neo4j/Chroma 클라이언트를 클로저로 캡처
from __future__ import annotations

import os
from typing import TYPE_CHECKING, Annotated

from langchain_core.tools import tool
from langgraph.types import interrupt

if TYPE_CHECKING:
    from src.storage.chroma_client import ChromaClient
    from src.storage.neo4j_client import Neo4jClient

# ── Cypher 쿼리 ──────────────────────────────────────────────────
_JOB_SKILLS_QUERY = """
MATCH (j:Job {normalized_title: $job_title})-[r:REQUIRES|PREFERS]->(s:Skill)
RETURN s.name AS skill, type(r) AS importance, r.weight AS weight, s.category AS category
ORDER BY r.weight DESC
LIMIT 30
"""

_PORTFOLIO_SKILLS_QUERY = """
MATCH (pi:PortfolioItem {owner: $owner})-[r:DEMONSTRATES]->(s:Skill)
RETURN s.name AS skill, r.confidence AS confidence, r.evidence AS evidence
"""


def create_tools(neo4j: "Neo4jClient", chroma: "ChromaClient") -> list:
    """클라이언트를 클로저로 받아 툴 목록을 생성한다."""

    @tool
    def gap_analysis(
        job_title: Annotated[str, "분석할 직무명 (예: AI Engineer, Backend Engineer)"],
        portfolio_skills: Annotated[list[str], "보유 기술 목록 (이력서에서 추출된 스킬명)"],
    ) -> dict:
        """직무 요구 스킬과 보유 스킬을 비교해 갭과 매칭률을 계산한다."""
        try:
            rows = neo4j.execute_query(_JOB_SKILLS_QUERY, job_title=job_title)
            if not rows:
                return {"error": f"'{job_title}' 직무 데이터 없음"}

            required = [r for r in rows if r["importance"] == "REQUIRES"]
            preferred = [r for r in rows if r["importance"] == "PREFERS"]
            portfolio_lower = {s.lower() for s in portfolio_skills}

            have_req = [r for r in required if r["skill"].lower() in portfolio_lower]
            missing_req = [r for r in required if r["skill"].lower() not in portfolio_lower]
            have_pref = [r for r in preferred if r["skill"].lower() in portfolio_lower]
            missing_pref = [r for r in preferred if r["skill"].lower() not in portfolio_lower]

            match_rate = len(have_req) / len(required) if required else 0.0

            return {
                "job_title": job_title,
                "match_rate": round(match_rate, 2),
                "required_total": len(required),
                "have_required": [r["skill"] for r in have_req],
                # weight 내림차순 정렬 유지 — 상위가 verify_skills 우선 대상
                "missing_required": [
                    {"skill": r["skill"], "weight": r.get("weight") or 1}
                    for r in missing_req
                ],
                "have_preferred": [r["skill"] for r in have_pref],
                "missing_preferred": [r["skill"] for r in missing_pref],
            }
        except Exception as e:
            return {"error": str(e)}

    @tool
    def vector_search(
        query: Annotated[str, "검색할 내용 (예: 'LangGraph production RAG experience')"],
        section_type: Annotated[str, "검색 범위: 'required', 'preferred', 'bullet', 또는 빈 문자열(전체)"],
    ) -> list[dict]:
        """Chroma에서 실제 공고 텍스트를 검색해 스킬 요구 수준·맥락의 근거를 가져온다."""
        try:
            results = chroma.search(
                query=query,
                n_results=3,
                section_type=section_type if section_type else None,
            )
            if not results:
                return [{"note": f"'{query}' 관련 공고 텍스트 없음. 다음 스킬로 넘어가세요.", "skip": True}]
            return [
                {
                    "source_id": r["source_id"],
                    "job_title": r["job_title"],
                    "company": r["company"],
                    "section_type": r["section_type"],
                    "text": r["original_text"][:400],
                }
                for r in results
            ]
        except Exception as e:
            return [{"error": str(e)}]

    @tool
    def verify_skills(
        skill_names: Annotated[list[str], "근거를 확인할 부족 스킬 목록 (최대 5개)"],
    ) -> dict:
        """여러 부족 스킬의 공고 근거를 한 번에 조회한다.

        각 스킬에 대해:
        1. Neo4j에서 해당 스킬을 REQUIRES하는 공고 ID를 조회
        2. Chroma에서 해당 공고의 요건 텍스트를 직접 fetch (유사도 검색 아님)
        3. Chroma에 청크가 없으면 BM25 키워드 exact match로 fallback

        vector_search를 반복 호출하는 것보다 정확하고 빠르다.
        """
        results: dict = {}
        try:
            for skill in skill_names[:5]:  # 최대 5개
                # Step 1: Neo4j → 이 스킬을 REQUIRES하는 공고 source_id
                posting_ids = neo4j.get_postings_requiring_skill(skill, limit=3)

                if posting_ids:
                    # Step 2: Neo4j-guided hybrid — source_id + section_type 메타 필터
                    # BM25(exact keyword) + Dense 모두 해당 공고 안에서만 검색
                    chunks = chroma.search(
                        skill,
                        n_results=2,
                        source_ids=posting_ids,
                        section_type="required",
                    )
                    # required 섹션 없으면 섹션 제한 없이 재시도
                    if not chunks:
                        chunks = chroma.search(skill, n_results=2, source_ids=posting_ids)
                    if chunks:
                        results[skill] = {
                            "method": "neo4j_guided",
                            "posting_count": len(posting_ids),
                            "evidence": [
                                {
                                    "source_id": c["source_id"],
                                    "company": c["company"],
                                    "text": c["original_text"][:300],
                                }
                                for c in chunks
                            ],
                        }
                        continue

                # Step 3: fallback — Neo4j 미등록, section_type 필터만 적용
                chunks = chroma.search(skill, n_results=2, section_type="required")
                if chunks:
                    results[skill] = {
                        "method": "keyword_fallback",
                        "posting_count": len(chunks),
                        "evidence": [
                            {
                                "source_id": c["source_id"],
                                "company": c["company"],
                                "text": c["original_text"][:300],
                            }
                            for c in chunks
                        ],
                    }
                else:
                    results[skill] = {
                        "method": "graph_only",
                        "posting_count": 0,
                        "evidence": [],
                    }
        except Exception as e:
            return {"error": str(e)}
        return results

    @tool
    def skill_unlock(
        skill_names: Annotated[list[str], "추가 보유 시 효과를 계산할 스킬 목록"],
    ) -> dict:
        """해당 스킬들을 모두 보유했을 때 지원 가능한 공고 수를 반환한다."""
        try:
            count = neo4j.get_skill_unlock_count(skill_names)
            return {"skills": skill_names, "accessible_postings": count}
        except Exception as e:
            return {"error": str(e)}

    @tool
    def market_insights(
        job_title: Annotated[str, "시장 인사이트를 조회할 직무명"],
    ) -> dict:
        """직무별 공고 수 분포, 상위 요구 스킬, 지역 분포를 반환한다."""
        try:
            distribution = neo4j.get_job_distribution()
            top_skills = neo4j.get_top_skills(job_title, limit=10)
            location = neo4j.get_location_distribution(job_title, limit=5)
            return {
                "job_distribution": distribution,
                "top_required_skills": top_skills,
                "location_distribution": location,
            }
        except Exception as e:
            return {"error": str(e)}

    @tool
    def graph_query(
        job_title: Annotated[str, "직무명 (정규화된 형태, 예: AI Engineer)"],
    ) -> list[dict]:
        """Neo4j에서 직무별 필수·우대 기술과 가중치를 조회한다."""
        try:
            rows = neo4j.execute_query(_JOB_SKILLS_QUERY, job_title=job_title)
            if not rows:
                return [{"note": f"'{job_title}' 직무 데이터 없음"}]
            return rows
        except Exception as e:
            return [{"error": str(e)}]

    @tool
    def ask_human(
        question: Annotated[str, "사용자에게 물어볼 구체적인 질문"],
    ) -> str:
        """이력서 내용이 불명확하거나 핵심 정보가 누락된 경우 사용자에게 질문한다."""
        if os.getenv("HITL_ENABLED", "true").lower() != "true":
            return "[자동 모드] 사용자 확인 없이 진행합니다."
        answer: str = interrupt({"question": question})
        return answer

    return [gap_analysis, verify_skills, vector_search, skill_unlock, market_insights, graph_query, ask_human]
