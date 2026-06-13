# 직군 핵심 역량·역방향 추천 — 실 Neo4j 필요
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=True)

from src.analysis.capability import (  # noqa: E402
    job_family_core_capabilities, recommend_families, skills_to_capabilities,
)
from src.storage.neo4j_client import Neo4jClient  # noqa: E402

requires_neo4j = pytest.mark.skipif(not os.getenv("NEO4J_URI"), reason="NEO4J_URI 필요")


@requires_neo4j
def test_se_core_has_backend_and_db():
    neo4j = Neo4jClient()
    core = job_family_core_capabilities(neo4j, "Software Engineer")
    assert "backend_fw" in core and "database" in core
    neo4j.close()


@requires_neo4j
def test_backend_resume_ranks_se_above_ai():
    neo4j = Neo4jClient()
    caps = skills_to_capabilities(["Java", "Spring", "MariaDB", "Docker", "AWS", "Jenkins"])
    rec = recommend_families(neo4j, caps, neo4j.list_job_families())
    rank = {r["job_family"]: i for i, r in enumerate(rec)}
    assert rank["Software Engineer"] < rank["AI/LLM Engineer"]
    neo4j.close()
