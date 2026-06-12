# Neo4jClient 직군 스킬/목록 메서드 — execute_query를 가짜로 주입해 매핑 로직만 검증
from src.storage.neo4j_client import Neo4jClient


class _Fake:
    def __init__(self, rows):
        self._rows = rows

    def execute_query(self, query, **params):
        return self._rows


def test_get_job_family_skills_maps_names():
    fake = _Fake([{"skill": "Java", "weight": 20}, {"skill": "Spring", "weight": 15}])
    names = Neo4jClient.get_job_family_skills(fake, "Software Engineer")
    assert names == ["Java", "Spring"]


def test_list_job_families_filters_empty():
    fake = _Fake([{"name": "AI/LLM Engineer"}, {"name": None}, {"name": "Software Engineer"}])
    assert Neo4jClient.list_job_families(fake) == ["AI/LLM Engineer", "Software Engineer"]


def test_methods_graceful_on_error():
    class _Boom:
        def execute_query(self, query, **params):
            raise RuntimeError("db down")
    assert Neo4jClient.get_job_family_skills(_Boom(), "X") == []
    assert Neo4jClient.list_job_families(_Boom()) == []
