# Profile 노드가 resume 스킬 추출 + (선택)GitHub confidence 갱신을 수행하는지 검증
from unittest.mock import MagicMock

from src.agent.profile_agent import create_profile_node


def test_profile_with_injected_skills():
    neo4j = MagicMock()
    neo4j.get_portfolio_demonstrated_skills.return_value = []
    openai = MagicMock()
    node = create_profile_node(neo4j, openai)
    out = node({
        "owner": "김지원", "job_family": "AI/LLM Engineer",
        "pdf_path": None, "resume_text": None, "github_url": None,
        "resume_skills": ["Python", "LangGraph"],
    })
    assert out["profile_result"]["skills"] == ["Python", "LangGraph"]
    assert out["resume_skills"] == ["Python", "LangGraph"]


def test_profile_loads_from_neo4j_when_no_input():
    from src.extraction.skill_extractor import DemonstratedSkill
    neo4j = MagicMock()
    neo4j.get_portfolio_demonstrated_skills.return_value = [
        DemonstratedSkill(name="Docker", category="tool", confidence="high", evidence="x"),
    ]
    openai = MagicMock()
    node = create_profile_node(neo4j, openai)
    out = node({
        "owner": "김지원", "job_family": "AI/LLM Engineer",
        "pdf_path": None, "resume_text": None, "github_url": None,
        "resume_skills": [],
    })
    assert "Docker" in out["profile_result"]["skills"]
