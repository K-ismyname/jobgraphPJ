# Market 노드가 직무 분포·상위스킬·트렌드를 market_result로 모으는지 검증
from unittest.mock import MagicMock

from src.agent.market_agent import create_market_node


def test_market_collects_result():
    neo4j = MagicMock()
    neo4j.get_job_distribution.return_value = [{"title": "AI Engineer", "count": 20}]
    neo4j.get_top_skills.return_value = [{"skill": "Python", "count": 15}]
    neo4j.get_location_distribution.return_value = [{"location": "Remote", "count": 8}]
    node = create_market_node(neo4j)
    out = node({"job_family": "AI/LLM Engineer"})

    assert "market_result" in out
    mr = out["market_result"]
    assert "top_required_skills" in mr
    assert mr["top_required_skills"][0]["skill"] == "Python"


def test_market_handles_error():
    neo4j = MagicMock()
    neo4j.get_job_distribution.side_effect = RuntimeError("db down")
    node = create_market_node(neo4j)
    out = node({"job_family": "AI/LLM Engineer"})
    assert out["market_result"].get("error")
