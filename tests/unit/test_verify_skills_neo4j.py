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


def test_verify_skills_collects_multiple_sentences():
    # 한 공고에 스킬을 언급하는 문장이 여러 개면 근거에 함께 담겨야 한다 (근거 풍부화)
    neo4j = MagicMock()
    neo4j.get_postings_requiring_skill.return_value = ["job1"]
    neo4j.get_posting_sections.return_value = [
        {"source_id": "job1", "company": "Acme",
         "required_section": (
             "Strong Python programming required. "
             "Must write production Python services. "
             "Docker experience preferred."
         ),
         "preferred_section": ""}
    ]
    vs = next(t for t in create_tools(neo4j) if t.name == "verify_skills")
    text = vs.invoke({"skill_names": ["Python"]})["Python"]["evidence"][0]["text"]
    # 단편 1문장이 아니라 Python 문장 2개가 문맥으로 함께 들어와야 한다
    assert "Strong Python programming required" in text
    assert "production Python services" in text


def test_verify_skills_uses_wider_posting_limit():
    # 근거 공고 검색 폭을 넓혔는지 (3 → 5)
    neo4j = MagicMock()
    neo4j.get_postings_requiring_skill.return_value = []
    neo4j.get_posting_sections.return_value = []
    vs = next(t for t in create_tools(neo4j) if t.name == "verify_skills")
    vs.invoke({"skill_names": ["Python"]})
    neo4j.get_postings_requiring_skill.assert_called_with("Python", limit=5)


def test_vector_search_removed():
    neo4j = MagicMock()
    names = [t.name for t in create_tools(neo4j)]
    assert "vector_search" not in names
    assert "verify_skills" in names
