# /jobs·/jobs/trending-skills가 v3(JobFamily/JobPosting) 스키마로 실제 결과를 반환하는지 검증 — 실 Neo4j 필요
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=True)

from fastapi.testclient import TestClient  # noqa: E402

from src.api.main import app  # noqa: E402

requires_neo4j = pytest.mark.skipif(
    not os.getenv("NEO4J_URI"),
    reason="NEO4J_URI 환경변수 필요",
)


@requires_neo4j
def test_list_jobs_returns_postings():
    # Software Engineer는 공고 수가 가장 많음(현재 127건)
    with TestClient(app) as client:
        r = client.get("/jobs", params={"job_family": "Software Engineer", "days": 365})
    assert r.status_code == 200
    body = r.json()
    assert body["job_family"] == "Software Engineer"
    assert body["total"] > 0, "공고가 0 — JobFamily 스키마 불일치 의심"
    # 적어도 한 공고에는 required_skills가 채워져야 함 (REQUIRES가 JobPosting에 붙음)
    assert any(j["required_skills"] for j in body["jobs"])


@requires_neo4j
def test_trending_skills_returns_ranked():
    with TestClient(app) as client:
        r = client.get("/jobs/trending-skills", params={"job_family": "Software Engineer", "top_n": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["job_family"] == "Software Engineer"
    assert len(body["skills"]) > 0, "트렌드 스킬이 0 — 스키마 불일치 의심"
    freqs = [s["frequency"] for s in body["skills"]]
    assert all(f > 0 for f in freqs)
    assert freqs == sorted(freqs, reverse=True)  # 빈도 내림차순
    assert body["skills"][0]["rank"] == 1
