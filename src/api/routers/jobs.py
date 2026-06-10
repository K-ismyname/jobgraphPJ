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

JOBS_QUERY = """
MATCH (p:JobPosting)-[:INSTANCE_OF]->(j:Job {normalized_title: $job_title})
WHERE p.is_active = true
  AND p.posted_at >= datetime() - duration({days: $days})
OPTIONAL MATCH (j)-[:REQUIRES]->(req:Skill)
OPTIONAL MATCH (j)-[:PREFERS]->(pref:Skill)
WITH p, j, collect(DISTINCT req.name) AS required, collect(DISTINCT pref.name) AS preferred
WHERE size($skills) = 0 OR ALL(s IN $skills WHERE s IN required)
RETURN p, required, preferred
ORDER BY p.posted_at DESC
LIMIT 50
"""

TRENDING_QUERY = """
MATCH (j:Job {normalized_title: $job_title})-[:REQUIRES]->(s:Skill)
RETURN s.name AS name, s.category AS category, s.frequency AS frequency
ORDER BY s.frequency DESC
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
            job_title=query.job_title,
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
    return JobsResponse(job_title=query.job_title, total=len(jobs), jobs=jobs)


@router.get("/trending-skills", response_model=TrendingSkillsResponse)
async def trending_skills(
    query: TrendingSkillsQuery = Depends(),
    neo4j: Neo4jClient = Depends(get_neo4j),
) -> TrendingSkillsResponse:
    """직무별 트렌드 기술 Top N."""
    try:
        rows = neo4j.execute_query(
            TRENDING_QUERY,
            job_title=query.job_title,
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
        job_title=query.job_title,
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
        result: SalaryAnalysisResult = analyze_salary(neo4j, job_title=query.job_title)
    except Exception as e:
        raise HTTPException(503, f"연봉 분석 실패: {e}")

    return SalaryResponse(
        job_title=result.job_title,
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
