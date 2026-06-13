# GET /stats가 Neo4j 집계 + Chroma count를 반환하는지 — 실 Neo4j 필요
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=True)

from fastapi.testclient import TestClient  # noqa: E402

from src.api.main import app  # noqa: E402

requires_neo4j = pytest.mark.skipif(not os.getenv("NEO4J_URI"), reason="NEO4J_URI 필요")


@requires_neo4j
def test_stats_returns_aggregates():
    with TestClient(app) as client:
        r = client.get("/stats")
    assert r.status_code == 200
    body = r.json()
    assert len(body["job_families"]) >= 1
    assert body["totals"]["postings"] > 0
    fam = body["job_families"][0]
    assert "name" in fam and "posting_count" in fam and "skill_count" in fam
