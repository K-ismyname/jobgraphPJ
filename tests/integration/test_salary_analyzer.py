# salary_analyzer가 v3(JobFamily/JobPosting) 스키마로 실제 연봉을 집계하는지 검증 — 실 Neo4j 필요
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=True)

from src.analysis.salary_analyzer import analyze_salary
from src.storage.neo4j_client import Neo4jClient

requires_neo4j = pytest.mark.skipif(
    not os.getenv("NEO4J_URI"),
    reason="NEO4J_URI 환경변수 필요",
)


@requires_neo4j
def test_analyze_salary_software_engineer():
    # Software Engineer 직군에 salary 있는 공고가 가장 많음(현재 15개)
    neo4j = Neo4jClient()
    result = analyze_salary(neo4j, job_family="Software Engineer")

    assert result.total_postings_with_salary > 0, "salary 공고가 0 — JobFamily 스키마 불일치 의심"
    assert result.baseline_avg_salary > 0
    assert len(result.skill_impacts) > 0, "스킬별 연봉 집계가 비어있음"
    for s in result.skill_impacts:
        assert s.avg_salary > 0
