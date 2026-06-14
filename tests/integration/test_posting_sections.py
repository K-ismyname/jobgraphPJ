# JobPosting 원문 속성 백필·조회 — 실 Neo4j 필요
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=True)

from src.storage.neo4j_client import Neo4jClient  # noqa: E402

requires_neo4j = pytest.mark.skipif(not os.getenv("NEO4J_URI"), reason="NEO4J_URI 필요")


@requires_neo4j
def test_posting_sections_present():
    neo4j = Neo4jClient()
    rows = neo4j.execute_query(
        "MATCH (p:JobPosting) WHERE p.required_section IS NOT NULL RETURN count(p) AS c"
    )
    assert rows[0]["c"] > 0  # 백필됨
    sample = neo4j.execute_query("MATCH (p:JobPosting) RETURN p.source_id AS sid LIMIT 1")[0]["sid"]
    secs = neo4j.get_posting_sections([sample])
    assert secs and "required_section" in secs[0]
    neo4j.close()
