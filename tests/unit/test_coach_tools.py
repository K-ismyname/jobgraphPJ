# coach 툴 — related_skills가 neo4j 연계 스킬을 반환
from src.agent.tools import create_coach_tools


class _FakeNeo4j:
    def get_co_occurring_skills(self, skills, top_n=8):
        return ["TypeScript", "Docker"]

    def get_postings_requiring_skill(self, skill, limit=2):
        return []


def test_related_skills_tool():
    tools = {t.name: t for t in create_coach_tools(_FakeNeo4j())}
    assert "related_skills" in tools
    out = tools["related_skills"].invoke({"skills": ["React", "Python"]})
    assert out["related"] == ["TypeScript", "Docker"]
