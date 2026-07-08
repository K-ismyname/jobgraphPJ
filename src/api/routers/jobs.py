# 채용공고 관련 엔드포인트 (GET /jobs, /jobs/trending-skills, /jobs/salary)
#
# 한 줄 요약: 브라우저가 "/jobs", "/jobs/trending-skills", "/jobs/salary" 같은 주소로
# 요청을 보내면, Neo4j에서 데이터를 조회해서 JSON으로 돌려주는 3개의 API를 정의한 파일.
# 우리가 지금까지 만든 그래프(Layer 1·2)와 분석 함수(Layer 4)를 실제로 "꺼내볼 수 있게" 하는 창구.

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
# APIRouter — "API 주소들을 묶어놓은 그룹". main.py가 이걸 가져다가 서버 전체에 등록함.
# Depends — deps.py에서 본 "자동으로 값을 채워주는" 기능.
# HTTPException — "이 요청은 실패했다"를 표현하는 표준적인 방법 (상태코드 + 메시지).

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
# 아직 안 본 schemas.py의 여러 클래스들 — "요청으로 들어올 데이터 모양"(Query로 끝나는 것들)과
# "응답으로 나갈 데이터 모양"(Response로 끝나는 것들)을 미리 정의해둔 것들로 추정
from src.storage.neo4j_client import Neo4jClient

router = APIRouter()
# 이 파일 전용 라우터를 하나 만듦. 아래 @router.get(...)들이 전부 이 라우터에 쌓이고,
# main.py가 app.include_router(jobs_router.router, prefix="/jobs", ...)로 통째로 서버에 등록함.
logger = logging.getLogger("jobgraph.api")

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
# 이 쿼리가 하는 일: "이 직군의, 최근 N일 안에 올라온, 아직 활성 상태인 공고들"을 가져오는데,
# 만약 사용자가 특정 스킬 목록으로 필터를 걸었으면 그 스킬을 전부 요구하는 공고만 골라줌.
# OPTIONAL MATCH → "있으면 가져오고 없어도 에러 안 남" (일반 MATCH는 없으면 그 공고 자체가 결과에서 빠짐)
# size($skills) = 0 OR ALL(...) → "필터를 아예 안 걸었거나(빈 리스트), 걸었으면 그 스킬들을 다 만족해야 함"

# 직군 내에서 공고에 요구된 빈도 순 — s.frequency(전역) 대신 직군 단위 count
TRENDING_QUERY = """
MATCH (p:JobPosting)-[:INSTANCE_OF]->(:JobFamily {name: $job_family})
MATCH (p)-[:REQUIRES]->(s:Skill)
WITH s, count(DISTINCT p) AS frequency
RETURN s.name AS name, s.category AS category, frequency
ORDER BY frequency DESC
LIMIT $top_n
"""
# 이 쿼리는 "이 직군에서 지금 제일 많이 요구되는 스킬 Top N"을 구함.
# 주석에 적힌 대로, Skill 노드 자체에 저장된 frequency(전체 직군 통틀어서 몇 번 나왔는지)가 아니라,
# "이 직군 안에서만" 다시 세는 것 — capability.py의 job_family_core_skills()와 비슷한 계산이지만
# 여기선 API가 직접 자기 쿼리로 계산함 (같은 종류의 쿼리가 여러 파일에 흩어져 있는 셈)


# 동기 Neo4j 드라이버를 쓰므로 def로 정의 — FastAPI가 스레드풀에서 실행해
# 이벤트 루프를 막지 않는다 (async def면 DB 왕복 동안 서버 전체가 멈춤).
@router.get("", response_model=JobsResponse)
def list_jobs(
    query: JobsQuery = Depends(),
    neo4j: Neo4jClient = Depends(get_neo4j),
) -> JobsResponse:
    """직무별 공고 목록. 기술 필터 가능."""
    # 여기서부터 이 파일의 핵심 개념 하나를 짚고 갑니다: **`def`냐 `async def`냐**.
    # FastAPI는 보통 `async def`(비동기 함수)를 권장하는데, 이 함수는 그냥 `def`(동기 함수)입니다.
    # 이유는 위 주석에 있음: Neo4j 드라이버가 "동기"(하나씩 순서대로 기다리는) 방식이라서,
    # 만약 이 함수를 async def로 만들면 DB 응답을 기다리는 동안 서버 전체가 다른 요청도 처리 못 하고
    # 멈춰버림. def로 두면 FastAPI가 알아서 별도의 작업자(스레드)에게 맡겨서, 이 요청이 DB를
    # 기다리는 동안에도 서버는 다른 요청을 계속 처리할 수 있음.

    # query: JobsQuery = Depends() → "URL의 ?job_family=...&days=...&skills=... 같은 쿼리
    # 파라미터들을 JobsQuery라는 정해진 모양으로 자동 정리해서 넣어줘"라는 뜻.
    # neo4j: Neo4jClient = Depends(get_neo4j) → deps.py에서 본 그 함수로 Neo4j 연결을 자동으로 받음.
    try:
        rows = neo4j.execute_query(
            JOBS_QUERY,
            job_family=query.job_family,
            days=query.days,
            skills=query.skills or [],
        )
    except Exception:
        logger.exception("jobs 조회 실패 (job_family=%s)", query.job_family)
        raise HTTPException(503, "데이터베이스에 연결할 수 없습니다.")
        # main.py의 generic_exception_handler와 같은 원칙 — 진짜 에러 내용(스택 등)은 로그에만 남기고,
        # 사용자에겐 503(서비스 이용 불가)이라는 표준적인 상태코드 + 짧은 메시지만 보여줌

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
    # Neo4j가 돌려준 딱딱한 행(row) 하나하나를, schemas.py에 정의된 JobSummary라는
    # 정해진 모양으로 바꿔서 리스트를 만듦 — pydantic 모델이라 모양이 안 맞으면 여기서 바로 에러가 남
    return JobsResponse(job_family=query.job_family, total=len(jobs), jobs=jobs)
    # response_model=JobsResponse라고 위에 적어뒀으니, FastAPI가 이 반환값을 그 모양에 맞게
    # 자동으로 JSON으로 변환해서 브라우저에 보내줌


@router.get("/trending-skills", response_model=TrendingSkillsResponse)
def trending_skills(
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
    except Exception:
        logger.exception("trending-skills 조회 실패 (job_family=%s)", query.job_family)
        raise HTTPException(503, "데이터베이스에 연결할 수 없습니다.")

    skills = [
        TrendingSkill(
            rank=i + 1,
            name=r["name"],
            category=r.get("category") or "tool",
            frequency=int(r.get("frequency") or 0),
        )
        for i, r in enumerate(rows)
        # enumerate(rows) → 순서(i)와 내용(r)을 같이 꺼냄. i+1을 등수(rank)로 씀
        # (쿼리에서 이미 빈도 내림차순 정렬을 해뒀으니, 등장 순서가 곧 등수가 됨)
    ]
    return TrendingSkillsResponse(
        job_family=query.job_family,
        skills=skills,
        generated_at=datetime.now(timezone.utc).isoformat(),
        # "이 응답이 언제 만들어졌는지" 현재 시각(UTC 기준)을 문자열로 남겨둠 —
        # 프론트에서 "몇 분 전 데이터"라고 보여주거나, 캐싱 판단에 쓸 수 있음
    )


@router.get("/salary", response_model=SalaryResponse)
def salary_analysis(
    query: SalaryQuery = Depends(),
    neo4j: Neo4jClient = Depends(get_neo4j),
) -> SalaryResponse:
    """기술별 연봉 영향도 분석."""
    try:
        result: SalaryAnalysisResult = analyze_salary(neo4j, job_family=query.job_family)
        # salary_analyzer.py에서 이미 본 그 함수 — 계산 로직은 전부 거기 있고, 여긴 그냥 불러다
        # 결과를 API 응답 모양(SalaryResponse)으로 옮겨 담기만 함
    except Exception:
        logger.exception("연봉 분석 실패 (job_family=%s)", query.job_family)
        raise HTTPException(503, "연봉 분석에 실패했습니다.")

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
        # salary_analyzer.py의 SkillSalaryImpact(내부용 모델)를, API 응답용 SkillSalaryItem으로
        # 하나씩 옮겨 담음. 이름이 비슷해서 헷갈리기 쉬운데, "내부 계산용 모델"과 "API 응답용 모델"이
        # 서로 다른 클래스로 분리돼 있다는 걸 눈여겨볼 것 (레이어 간 결합을 느슨하게 하려는 설계)
        top_salary_skills=result.top_salary_skills,
    )
