# verify_skills가 Neo4j 텍스트에서 스킬 근거 문장을 뽑는지 (DB mock)
from unittest.mock import MagicMock

from src.agent.tools import create_tools


def _gap_tool(name):
    neo4j = MagicMock()
    neo4j.get_postings_requiring_skill.return_value = ["job1"]
    neo4j.get_posting_sections.return_value = [
        {"source_id": "job1", "company": "Acme",
         "required_section": "Strong Python skills required. Docker experience preferred.",
         "preferred_section": ""}
    ]
    tools = create_tools(neo4j)
    return next(t for t in tools if t.name == name)


def test_verify_skills_pulls_sentence():
    vs = _gap_tool("verify_skills")
    res = vs.invoke({"skill_names": ["Python"]})
    ev = res["Python"]["evidence"]
    assert ev and "Python" in ev[0]["text"]
    assert ev[0]["company"] == "Acme"


def test_vector_search_removed():
    neo4j = MagicMock()
    names = [t.name for t in create_tools(neo4j)]
    assert "vector_search" not in names
    assert "verify_skills" in names
