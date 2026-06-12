# 채용공고 관련 엔드포인트 (GET /jobs, /jobs/trending-skills, /jobs/salary)
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from src.analysis.salary_analyzer import SalaryAnalysisResult, analyze_salary
from src.api.deps import get_neo4j
from src.api.schemas import (
    JobSummary,
    JobsQuery,
    JobsResponse,
    SalaryQuery,
    SalaryResponse,
    SkillSalaryItem,
    TrendingSkill,
    TrendingSkillsQuery,
    TrendingSkillsResponse,
)
from src.storage.neo4j_client import Neo4jClient

router = APIRouter()

# v3 스키마: 직군 노드는 JobFamily, REQUIRES/PREFERS는 JobPosting에 붙음
JOBS_QUERY = """
MATCH (p:JobPosting)-[:INSTANCE_OF]->(:JobFamily {name: $job_family})
WHERE p.is_active = true
  AND p.posted_at >= datetime() - duration({days: $days})
OPTIONAL MATCH (p)-[:REQUIRES]->(req:Skill)
OPTIONAL MATCH (p)-[:PREFERS]->(pref:Skill)
WITH p, collect(DISTINCT req.name) AS required, collect(DISTINCT pref.name) AS preferred
WHERE size($skills) = 0 OR ALL(s IN $skills WHERE s IN required)
RETURN p, required, preferred
ORDER BY p.posted_at DESC
LIMIT 50
"""

# 직군 내에서 공고에 요구된 빈도 순 — s.frequency(전역) 대신 직군 단위 count
TRENDING_QUERY = """
MATCH (p:JobPosting)-[:INSTANCE_OF]->(:JobFamily {name: $job_family})
MATCH (p)-[:REQUIRES]->(s:Skill)
WITH s, count(DISTINCT p) AS frequency
RETURN s.name AS name, s.category AS category, frequency
ORDER BY frequency DESC
LIMIT $top_n
"""


@router.get("", response_model=JobsResponse)
async def list_jobs(
    query: JobsQuery = Depends(),
    neo4j: Neo4jClient = Depends(get_neo4j),
) -> JobsResponse:
    """직무별 공고 목록. 기술 필터 가능."""
    try:
        rows = neo4j.execute_query(
            JOBS_QUERY,
            job_family=query.job_family,
            days=query.days,
            skills=query.skills or [],
        )
    except Exception as e:
        raise HTTPException(503, f"DB 연결 불가: {e}")

    jobs = [
        JobSummary(
            id=str(r["p"].get("source_id", "")),
            title=r["p"].get("title", ""),
            company=r["p"].get("company", ""),
            location=r["p"].get("location"),
            salary_min=r["p"].get("salary_min"),
            salary_max=r["p"].get("salary_max"),
            contract_type=r["p"].get("contract_type"),
            url=r["p"].get("url"),
            required_skills=r.get("required") or [],
            preferred_skills=r.get("preferred") or [],
        )
        for r in rows
    ]
    return JobsResponse(job_family=query.job_family, total=len(jobs), jobs=jobs)


@router.get("/trending-skills", response_model=TrendingSkillsResponse)
async def trending_skills(
    query: TrendingSkillsQuery = Depends(),
    neo4j: Neo4jClient = Depends(get_neo4j),
) -> TrendingSkillsResponse:
    """직무별 트렌드 기술 Top N."""
    try:
        rows = neo4j.execute_query(
            TRENDING_QUERY,
            job_family=query.job_family,
            top_n=query.top_n,
        )
    except Exception as e:
        raise HTTPException(503, f"DB 연결 불가: {e}")

    skills = [
        TrendingSkill(
            rank=i + 1,
            name=r["name"],
            category=r.get("category") or "tool",
            frequency=int(r.get("frequency") or 0),
        )
        for i, r in enumerate(rows)
    ]
    return TrendingSkillsResponse(
        job_family=query.job_family,
        skills=skills,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/salary", response_model=SalaryResponse)
async def salary_analysis(
    query: SalaryQuery = Depends(),
    neo4j: Neo4jClient = Depends(get_neo4j),
) -> SalaryResponse:
    """기술별 연봉 영향도 분석."""
    try:
        result: SalaryAnalysisResult = analyze_salary(neo4j, job_family=query.job_family)
    except Exception as e:
        raise HTTPException(503, f"연봉 분석 실패: {e}")

    return SalaryResponse(
        job_family=result.job_family,
        baseline_avg_salary=result.baseline_avg_salary,
        total_postings_with_salary=result.total_postings_with_salary,
        skill_impacts=[
            SkillSalaryItem(
                skill=s.skill,
                avg_salary=s.avg_salary,
                posting_count=s.posting_count,
                vs_baseline_pct=s.vs_baseline_pct,
            )
            for s in result.skill_impacts
        ],
        top_salary_skills=result.top_salary_skills,
    )
