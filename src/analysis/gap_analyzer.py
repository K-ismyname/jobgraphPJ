# 직무 요구 기술 대비 보유 기술 갭을 분석하는 모듈
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from src.storage.chroma_client import ChromaClient
from src.storage.neo4j_client import Neo4jClient


class SkillGap(BaseModel):
    skill: str
    have_it: bool
    confidence: Literal["high", "medium", "low"] | None  # have_it=False면 None
    evidence: str | None
    related_skills: list[str]
    difficulty: Literal["학습 장벽 낮음", "신규 학습 필요"] | None  # have_it=True면 None
    job_demand: int


class GapAnalysisResult(BaseModel):
    job_title: str
    owner: str
    match_rate: float         # 0.0 ~ 1.0
    have: list[SkillGap]
    missing: list[SkillGap]
    top_missing: list[str]    # job_demand 상위 3개 기술명


GAP_QUERY = """
MATCH (:JobFamily {name: $job_family})<-[:INSTANCE_OF]-(jp:JobPosting)-[:REQUIRES]->(required:Skill)

WITH required, count(jp) AS job_demand

OPTIONAL MATCH (me:PortfolioItem {owner: $owner})-[d:DEMONSTRATES]->(required)

OPTIONAL MATCH (related:Skill)-[:CO_OCCURS]-(required)
WHERE EXISTS {
    MATCH (:PortfolioItem {owner: $owner})-[:DEMONSTRATES]->(related)
}

WITH required, job_demand, d, collect(DISTINCT related.name) AS related_i_have
RETURN
    required.name         AS skill,
    d IS NOT NULL         AS i_have_it,
    d.confidence          AS confidence,
    d.evidence            AS evidence,
    related_i_have        AS related_skills,
    job_demand
ORDER BY i_have_it ASC, job_demand DESC
"""


def run_gap_analysis(
    neo4j: Neo4jClient,
    chroma: ChromaClient | None = None,
    job_family: str = "AI/LLM Engineer",
    owner: str = "",
) -> GapAnalysisResult:
    """GAP_QUERY 실행 → Pydantic 변환 → Chroma evidence로 보강."""
    rows = neo4j.execute_query(GAP_QUERY, job_family=job_family, owner=owner)

    have: list[SkillGap] = []
    missing: list[SkillGap] = []

    for row in rows:
        related: list[str] = row.get("related_skills") or []
        have_it = bool(row.get("i_have_it"))
        evidence: str | None = row.get("evidence")

        # missing 기술에 Neo4j evidence 없으면 Chroma에서 보강
        if not have_it and not evidence and chroma:
            results = chroma.search(row["skill"], n_results=1, section_type="required")
            if results:
                evidence = results[0]["original_text"][:200]

        gap = SkillGap(
            skill=row["skill"],
            have_it=have_it,
            confidence=row.get("confidence") if have_it else None,
            evidence=evidence,
            related_skills=related,
            difficulty=None if have_it else ("학습 장벽 낮음" if related else "신규 학습 필요"),
            job_demand=int(row.get("job_demand") or 1),
        )
        (have if have_it else missing).append(gap)

    total = len(have) + len(missing)
    match_rate = round(len(have) / total, 2) if total > 0 else 0.0
    top_missing = sorted(missing, key=lambda s: s.job_demand, reverse=True)[:3]

    return GapAnalysisResult(
        job_title=job_family,
        owner=owner,
        match_rate=match_rate,
        have=have,
        missing=missing,
        top_missing=[s.skill for s in top_missing],
    )
