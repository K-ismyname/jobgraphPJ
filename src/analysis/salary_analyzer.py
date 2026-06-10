# 기술별 연봉 영향도를 Neo4j 집계 쿼리로 분석하는 모듈
from __future__ import annotations

from pydantic import BaseModel

from src.storage.neo4j_client import Neo4jClient


class SkillSalaryImpact(BaseModel):
    skill: str
    avg_salary: float
    posting_count: int
    vs_baseline_pct: float    # +12.3 → 전체 평균보다 12.3% 높음


class SkillComboInsight(BaseModel):
    skills: list[str]
    avg_salary: float
    vs_single_avg_pct: float  # 단독 기술 평균 대비 차이 %
    posting_count: int


class SalaryAnalysisResult(BaseModel):
    job_title: str
    baseline_avg_salary: float
    total_postings_with_salary: int
    skill_impacts: list[SkillSalaryImpact]   # avg_salary 내림차순
    top_salary_skills: list[str]             # vs_baseline_pct 상위 3개
    combo_insights: list[SkillComboInsight]


BASELINE_QUERY = """
MATCH (j:Job {normalized_title: $job_title})<-[:INSTANCE_OF]-(p:JobPosting)
WHERE p.salary_min IS NOT NULL AND p.salary_max IS NOT NULL AND p.salary_min > 0
RETURN
    avg((p.salary_min + p.salary_max) / 2.0) AS baseline_avg,
    count(p)                                  AS posting_count
"""

SKILL_SALARY_QUERY = """
MATCH (j:Job {normalized_title: $job_title})-[:REQUIRES]->(s:Skill)
MATCH (s)<-[:REQUIRES]-(any_job:Job)<-[:INSTANCE_OF]-(p:JobPosting)
WHERE p.salary_min IS NOT NULL AND p.salary_max IS NOT NULL AND p.salary_min > 0
WITH
    s.name                                    AS skill,
    avg((p.salary_min + p.salary_max) / 2.0) AS avg_salary,
    count(DISTINCT p)                         AS posting_count
ORDER BY avg_salary DESC
RETURN skill, avg_salary, posting_count
LIMIT $top_n
"""

TOP_COOCCURS_QUERY = """
MATCH (j:Job {normalized_title: $job_title})-[:REQUIRES]->(sa:Skill)
MATCH (sa)-[co:CO_OCCURS]-(sb:Skill)
WHERE sa.name < sb.name
RETURN sa.name AS skill_a, sb.name AS skill_b, co.count AS co_count
ORDER BY co_count DESC
LIMIT $top_n
"""

COMBO_SALARY_QUERY = """
MATCH (p:JobPosting)-[:INSTANCE_OF]->(j:Job)
WHERE (j)-[:REQUIRES]->(:Skill {name: $skill_a})
  AND (j)-[:REQUIRES]->(:Skill {name: $skill_b})
  AND p.salary_min IS NOT NULL AND p.salary_max IS NOT NULL AND p.salary_min > 0
RETURN
    avg((p.salary_min + p.salary_max) / 2.0) AS combo_avg_salary,
    count(DISTINCT p)                         AS posting_count
"""


def analyze_salary(
    neo4j: Neo4jClient,
    job_title: str = "AI Engineer",
    top_n: int = 10,
    combo_top_n: int = 3,
) -> SalaryAnalysisResult:
    """기술별 연봉 영향도 계산. salary 없는 공고는 집계에서 제외."""
    baseline_rows = neo4j.execute_query(BASELINE_QUERY, job_title=job_title)
    baseline_avg = 0.0
    total_postings = 0
    if baseline_rows:
        baseline_avg = float(baseline_rows[0].get("baseline_avg") or 0)
        total_postings = int(baseline_rows[0].get("posting_count") or 0)

    skill_rows = neo4j.execute_query(SKILL_SALARY_QUERY, job_title=job_title, top_n=top_n)
    impacts: list[SkillSalaryImpact] = []
    for row in skill_rows:
        avg = float(row.get("avg_salary") or 0)
        vs_pct = ((avg - baseline_avg) / baseline_avg * 100) if baseline_avg > 0 else 0.0
        impacts.append(SkillSalaryImpact(
            skill=row["skill"],
            avg_salary=round(avg),
            posting_count=int(row.get("posting_count") or 0),
            vs_baseline_pct=round(vs_pct, 1),
        ))

    top_salary = sorted(impacts, key=lambda x: x.vs_baseline_pct, reverse=True)[:3]

    # CO_OCCURS 상위 쌍의 조합 연봉
    co_rows = neo4j.execute_query(TOP_COOCCURS_QUERY, job_title=job_title, top_n=combo_top_n)
    single_avgs = {s.skill: s.avg_salary for s in impacts}
    combos: list[SkillComboInsight] = []

    for row in co_rows:
        skill_a, skill_b = row["skill_a"], row["skill_b"]
        combo_rows = neo4j.execute_query(COMBO_SALARY_QUERY, skill_a=skill_a, skill_b=skill_b)
        if not combo_rows:
            continue
        combo_avg = float(combo_rows[0].get("combo_avg_salary") or 0)
        count = int(combo_rows[0].get("posting_count") or 0)
        if count == 0:
            continue
        single_avg = (
            single_avgs.get(skill_a, baseline_avg) + single_avgs.get(skill_b, baseline_avg)
        ) / 2
        vs_single = ((combo_avg - single_avg) / single_avg * 100) if single_avg > 0 else 0.0
        combos.append(SkillComboInsight(
            skills=[skill_a, skill_b],
            avg_salary=round(combo_avg),
            vs_single_avg_pct=round(vs_single, 1),
            posting_count=count,
        ))

    return SalaryAnalysisResult(
        job_title=job_title,
        baseline_avg_salary=round(baseline_avg),
        total_postings_with_salary=total_postings,
        skill_impacts=impacts,
        top_salary_skills=[s.skill for s in top_salary],
        combo_insights=combos,
    )
