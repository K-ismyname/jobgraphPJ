# 기술별 연봉 영향도를 Neo4j 집계 쿼리로 분석하는 모듈
#
# 한 줄 요약: "이 직군에서 이 기술을 가지면 평균 연봉이 얼마나 더/덜 나오는지" 계산하는 파일.
# CLAUDE.md에 "공고의 연봉 공개율이 낮아 보조 지표로만 산출"이라고 적혀있던 그 기능입니다 —
# 즉 핵심 기능이 아니라 "참고로 보여주는 부가 정보" 취급입니다. 실제로는 src/api/routers/jobs.py가
# 이 파일의 analyze_salary()를 호출해서 API 응답으로 내보냅니다 (죽은 코드 아님, 실사용 중).

from __future__ import annotations

from pydantic import BaseModel
# skill_extractor.py에서 봤던 그 라이브러리. "이 데이터는 반드시 이런 모양이어야 한다"를
# 미리 정해두고, 그 모양이 아니면 에러를 내주는 검증 도구.

from src.storage.neo4j_client import Neo4jClient


class SkillSalaryImpact(BaseModel):
    # 스킬 하나에 대한 연봉 정보를 담는 상자
    skill: str
    avg_salary: float
    posting_count: int          # 이 스킬을 요구하는, 연봉 정보 있는 공고가 몇 개였는지
    vs_baseline_pct: float    # +12.3 → 직군 평균보다 12.3% 높음


class SkillComboInsight(BaseModel):
    # 스킬 "두 개를 같이" 가졌을 때의 연봉 정보를 담는 상자 (예: Python + Docker)
    skills: list[str]
    avg_salary: float
    vs_single_avg_pct: float  # 단독 기술 평균 대비 차이 %
    posting_count: int


class SalaryAnalysisResult(BaseModel):
    # 위 두 상자를 모아서, 최종적으로 API가 돌려줄 전체 결과 상자
    job_family: str
    baseline_avg_salary: float           # 이 직군의 평균 연봉 (기준선)
    total_postings_with_salary: int      # 연봉을 공개한 공고가 몇 개였는지
    skill_impacts: list[SkillSalaryImpact]   # avg_salary 내림차순
    top_salary_skills: list[str]             # vs_baseline_pct 상위 3개
    combo_insights: list[SkillComboInsight]


# v3 스키마: 직군 노드는 JobFamily, REQUIRES는 JobPosting에 붙음
#   (JobPosting)-[:INSTANCE_OF]->(JobFamily), (JobPosting)-[:REQUIRES]->(Skill)
BASELINE_QUERY = """
MATCH (p:JobPosting)-[:INSTANCE_OF]->(:JobFamily {name: $job_family})
WHERE p.salary_min IS NOT NULL AND p.salary_max IS NOT NULL AND p.salary_min > 0
RETURN
    avg((p.salary_min + p.salary_max) / 2.0) AS baseline_avg,
    count(p)                                  AS posting_count
"""
# 이 쿼리가 하는 일: "이 직군의 공고 중에서, 연봉 정보가 실제로 있는 공고들만 골라서,
# 각 공고의 (최소+최대)/2 를 평균 낸다." → 이게 "이 직군의 평균 연봉" 기준선이 됨.
# salary_min > 0 조건을 넣은 이유: 0이면 "연봉 미정"을 0으로 잘못 저장한 데이터일 수 있어서 제외.

SKILL_SALARY_QUERY = """
MATCH (p:JobPosting)-[:INSTANCE_OF]->(:JobFamily {name: $job_family})
MATCH (p)-[:REQUIRES]->(s:Skill)
WHERE p.salary_min IS NOT NULL AND p.salary_max IS NOT NULL AND p.salary_min > 0
WITH
    s.name                                    AS skill,
    avg((p.salary_min + p.salary_max) / 2.0) AS avg_salary,
    count(DISTINCT p)                         AS posting_count
ORDER BY avg_salary DESC
RETURN skill, avg_salary, posting_count
LIMIT $top_n
"""
# 위 쿼리랑 비슷한데, 이번엔 "스킬별로" 나눠서 평균 연봉을 구함.
# 예: Python 요구하는 공고들의 평균 연봉, Docker 요구하는 공고들의 평균 연봉... 이런 식으로
# 스킬마다 따로 계산해서, 평균 연봉이 높은 순서로 top_n개만 가져옴.

# 직군 공고 안에서 같은 공고에 함께 요구된 스킬 쌍 (공고 단위 공동 등장)
TOP_COOCCURS_QUERY = """
MATCH (p:JobPosting)-[:INSTANCE_OF]->(:JobFamily {name: $job_family})
MATCH (p)-[:REQUIRES]->(sa:Skill)
MATCH (p)-[:REQUIRES]->(sb:Skill)
WHERE sa.name < sb.name
WITH sa.name AS skill_a, sb.name AS skill_b, count(DISTINCT p) AS co_count
ORDER BY co_count DESC
RETURN skill_a, skill_b, co_count
LIMIT $top_n
"""
# 이 쿼리는 "어떤 스킬 두 개가 같은 공고에 자주 같이 나오는지" 찾음.
# WHERE sa.name < sb.name 이 부분이 핵심 트릭: 이게 없으면 (Python, Docker)랑 (Docker, Python)이
# 같은 쌍인데 두 번 중복으로 나옴. 이름을 알파벳 순서로 비교해서 "앞에 있는 것만" 인정하게 해서
# 중복을 원천 차단하는 것 (예: "Docker" < "Python"이니까 (Docker, Python) 조합만 나오고
# (Python, Docker)는 안 나옴).

COMBO_SALARY_QUERY = """
MATCH (p:JobPosting)-[:INSTANCE_OF]->(:JobFamily {name: $job_family})
WHERE (p)-[:REQUIRES]->(:Skill {name: $skill_a})
  AND (p)-[:REQUIRES]->(:Skill {name: $skill_b})
  AND p.salary_min IS NOT NULL AND p.salary_max IS NOT NULL AND p.salary_min > 0
RETURN
    avg((p.salary_min + p.salary_max) / 2.0) AS combo_avg_salary,
    count(DISTINCT p)                         AS posting_count
"""
# 이 쿼리는 "스킬 A와 B를 둘 다 요구하는 공고들"만 골라서 그 공고들의 평균 연봉을 구함.
# 위 TOP_COOCCURS_QUERY로 "자주 같이 나오는 스킬 쌍"을 먼저 찾고, 그 쌍마다 이 쿼리로
# "둘 다 가지면 연봉이 얼마나 되는지"를 계산하는 2단계 구조.


def analyze_salary(
    neo4j: Neo4jClient,
    job_family: str = "AI/LLM Engineer",
    top_n: int = 10,
    combo_top_n: int = 3,
) -> SalaryAnalysisResult:
    """직군 내 기술별 연봉 영향도 계산. salary 없는 공고는 집계에서 제외."""

    # ── 1단계: 이 직군의 평균 연봉(기준선) 구하기 ──
    baseline_rows = neo4j.execute_query(BASELINE_QUERY, job_family=job_family)
    baseline_avg = 0.0
    total_postings = 0
    if baseline_rows:
        baseline_avg = float(baseline_rows[0].get("baseline_avg") or 0)
        total_postings = int(baseline_rows[0].get("posting_count") or 0)
        # baseline_rows가 비어있을 수도 있어서(연봉 정보 있는 공고가 하나도 없으면) if로 방어.
        # or 0 → 값이 None이면 0으로 대체 (나눗셈 등에서 에러 안 나게)

    # ── 2단계: 스킬별 평균 연봉 구하기 ──
    skill_rows = neo4j.execute_query(SKILL_SALARY_QUERY, job_family=job_family, top_n=top_n)
    impacts: list[SkillSalaryImpact] = []
    for row in skill_rows:
        avg = float(row.get("avg_salary") or 0)
        vs_pct = ((avg - baseline_avg) / baseline_avg * 100) if baseline_avg > 0 else 0.0
        # 이 스킬의 평균 연봉이, 직군 전체 평균(baseline_avg)보다 몇 % 높은지/낮은지 계산.
        # 예: 직군 평균이 5000이고 이 스킬 평균이 5600이면 → (5600-5000)/5000*100 = 12.0%
        # baseline_avg가 0이면 나눗셈 에러가 나니까 그럴 땐 그냥 0.0으로 처리
        impacts.append(SkillSalaryImpact(
            skill=row["skill"],
            avg_salary=round(avg),
            posting_count=int(row.get("posting_count") or 0),
            vs_baseline_pct=round(vs_pct, 1),
        ))

    top_salary = sorted(impacts, key=lambda x: x.vs_baseline_pct, reverse=True)[:3]
    # vs_baseline_pct(직군 평균 대비 %)가 높은 순서로 정렬해서 상위 3개만 뽑음 —
    # "이 스킬을 가지면 연봉이 제일 많이 오르는 top 3"

    # ── 3단계: 스킬 조합(2개씩)의 연봉 구하기 ──
    co_rows = neo4j.execute_query(TOP_COOCCURS_QUERY, job_family=job_family, top_n=combo_top_n)
    single_avgs = {s.skill: s.avg_salary for s in impacts}
    # 위에서 이미 구해둔 "스킬 하나짜리 평균 연봉"을 {스킬명: 평균연봉} 딕셔너리로 정리해둠
    # (조합 연봉과 비교할 때 다시 쿼리 안 날리고 이미 가진 값을 재사용하려는 것)
    combos: list[SkillComboInsight] = []

    for row in co_rows:
        skill_a, skill_b = row["skill_a"], row["skill_b"]
        combo_rows = neo4j.execute_query(
            COMBO_SALARY_QUERY, job_family=job_family, skill_a=skill_a, skill_b=skill_b
        )
        if not combo_rows:
            continue
            # 이 스킬 조합을 요구하면서 연봉 정보도 있는 공고가 아예 없으면 건너뜀
        combo_avg = float(combo_rows[0].get("combo_avg_salary") or 0)
        count = int(combo_rows[0].get("posting_count") or 0)
        if count == 0:
            continue
        single_avg = (
            single_avgs.get(skill_a, baseline_avg) + single_avgs.get(skill_b, baseline_avg)
        ) / 2
        # "이 두 스킬을 따로따로 가졌을 때의 평균"을 계산 (둘의 평균의 평균).
        # single_avgs에 그 스킬이 없으면(위 skill_rows의 top_n 밖으로 밀려서 못 구했으면)
        # baseline_avg(직군 전체 평균)로 대신 씀 — 값이 없다고 에러 내지 않고 그럴듯한 값으로 대체
        vs_single = ((combo_avg - single_avg) / single_avg * 100) if single_avg > 0 else 0.0
        # "둘을 같이 가지면, 따로 가졌을 때보다 연봉이 몇 % 더/덜 나오는지" — 이게 이 조합 분석의 핵심 질문
        combos.append(SkillComboInsight(
            skills=[skill_a, skill_b],
            avg_salary=round(combo_avg),
            vs_single_avg_pct=round(vs_single, 1),
            posting_count=count,
        ))

    # ── 4단계: 전부 모아서 하나의 결과로 반환 ──
    return SalaryAnalysisResult(
        job_family=job_family,
        baseline_avg_salary=round(baseline_avg),
        total_postings_with_salary=total_postings,
        skill_impacts=impacts,
        top_salary_skills=[s.skill for s in top_salary],
        combo_insights=combos,
    )
