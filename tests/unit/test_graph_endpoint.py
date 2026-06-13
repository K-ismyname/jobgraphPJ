# GET /graph — 구조(Mermaid)+6단계 설명. graph None이어도 stages는 제공
from fastapi.testclient import TestClient

from src.api.main import app


def test_graph_returns_stages():
    client = TestClient(app)  # with 없이 → lifespan 미실행(graph None)
    r = client.get("/graph")
    assert r.status_code == 200
    body = r.json()
    keys = [s["key"] for s in body["stages"]]
    assert keys == ["evaluators", "consensus", "gap_loop", "fit", "critic", "coach"]
    assert all(s.get("title") and s.get("description") for s in body["stages"])
    # lifespan 미실행이라 app.state.graph 없음 → mermaid None (예외 없이)
    assert "mermaid" in body
