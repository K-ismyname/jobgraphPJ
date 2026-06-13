# 시스템 데이터 현황 — 직군별 통계 + 전체 노드/관계/청크 수
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from src.api.deps import get_chroma, get_neo4j
from src.api.schemas import JobFamilyStat, StatsResponse
from src.storage.chroma_client import ChromaClient
from src.storage.neo4j_client import Neo4jClient

router = APIRouter()

_FAMILY_STATS = """
MATCH (f:JobFamily)
OPTIONAL MATCH (f)<-[:INSTANCE_OF]-(jp:JobPosting)
WITH f, count(DISTINCT jp) AS postings
OPTIONAL MATCH (f)<-[:INSTANCE_OF]-(:JobPosting)-[:REQUIRES]->(s:Skill)
RETURN f.name AS name, postings, count(DISTINCT s) AS skill_count
ORDER BY postings DESC
"""

# skill_count는 REQUIRES 기준(우대 PREFERS 제외). 각 집계는 WITH로 단일 행 collapse 후
# 다음 MATCH로 넘겨 cartesian product·경고를 피한다.
_TOTALS = """
MATCH (jp:JobPosting)
WITH count(jp) AS postings
MATCH (s:Skill)
WITH postings, count(s) AS skills
MATCH ()-[r:REQUIRES|PREFERS]->()
WITH postings, skills, count(r) AS relations
RETURN postings, skills, relations
"""


@router.get("", response_model=StatsResponse)
async def stats(
    neo4j: Neo4jClient = Depends(get_neo4j),
    chroma: ChromaClient = Depends(get_chroma),
) -> StatsResponse:
    """Neo4j 집계 + Chroma 청크 수."""
    try:
        fam_rows = neo4j.execute_query(_FAMILY_STATS)
        tot_rows = neo4j.execute_query(_TOTALS)
    except Exception as e:
        raise HTTPException(503, f"DB 집계 실패: {e}")

    tot = tot_rows[0] if tot_rows else {"postings": 0, "skills": 0, "relations": 0}
    try:
        chunks = chroma.count()
    except Exception:
        chunks = None

    return StatsResponse(
        job_families=[
            JobFamilyStat(
                name=r["name"],
                posting_count=int(r.get("postings") or 0),
                skill_count=int(r.get("skill_count") or 0),
            )
            for r in fam_rows
        ],
        totals={
            "postings": int(tot.get("postings") or 0),
            "skills": int(tot.get("skills") or 0),
            "relations": int(tot.get("relations") or 0),
        },
        chroma_chunks=chunks,
    )
