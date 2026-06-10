# Retrieval 노드가 neo4j 요구스킬 + chroma 근거를 retrieved_context로 모으는지 검증
from unittest.mock import MagicMock

from src.agent.retrieval_agent import create_retrieval_node


def test_retrieval_collects_context():
    neo4j = MagicMock()
    neo4j.execute_query.return_value = [
        {"skill": "LangGraph", "importance": "REQUIRES", "weight": 12},
    ]
    chroma = MagicMock()
    chroma.search.return_value = [
        {"original_text": "LangGraph production experience required",
         "job_title": "AI Engineer", "company": "Acme",
         "section_type": "required", "source_id": "muse-1"},
    ]
    node = create_retrieval_node(neo4j, chroma)
    out = node({"job_family": "AI/LLM Engineer"})

    assert "retrieved_context" in out
    ctx = out["retrieved_context"]
    assert len(ctx) >= 1
    assert ctx[0]["source_id"] == "muse-1"
    assert "LangGraph" in [r["skill"] for r in out["retrieved_context"] if "skill" in r] or \
           any("LangGraph" in c.get("text", "") for c in ctx)


def test_retrieval_handles_empty():
    neo4j = MagicMock()
    neo4j.execute_query.return_value = []
    chroma = MagicMock()
    chroma.search.return_value = []
    node = create_retrieval_node(neo4j, chroma)
    out = node({"job_family": "Unknown"})
    assert out["retrieved_context"] == []
