# 정적 프론트 서빙 라우트 스모크 — lifespan 없이 라우트만 검증(Neo4j 키 불필요)
from fastapi.testclient import TestClient

from src.api.main import app


def test_index_served():
    # with 없이 TestClient를 쓰면 lifespan(=Neo4j 연결)을 돌리지 않는다
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Job Skill Analyzer" in r.text
