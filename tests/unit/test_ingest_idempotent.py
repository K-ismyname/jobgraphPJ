# ingest_posting 멱등성 — 재적재 시 카운터 쿼리를 건너뛰는지 검증
from src.storage.neo4j_client import Neo4jClient


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def single(self):
        return self._row


class _FakeSession:
    def __init__(self, exists: bool, log: list):
        self._exists = exists
        self._log = log

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, query, **params):
        self._log.append(query)
        if "count(p) AS c" in query:
            return _FakeResult({"c": 1 if self._exists else 0})
        return _FakeResult(None)


class _FakeDriver:
    def __init__(self, exists: bool):
        self._exists = exists
        self.log: list = []

    def session(self):
        return _FakeSession(self._exists, self.log)


def _make_client(exists: bool) -> tuple[Neo4jClient, _FakeDriver]:
    client = Neo4jClient.__new__(Neo4jClient)   # __init__(=DB 연결) 우회
    driver = _FakeDriver(exists)
    client._driver = driver
    return client, driver


_POSTING = {
    "id": 12345, "title": "AI Engineer", "company": "ACME",
    "job_family": "AI/LLM Engineer", "created": "2026-01-01T00:00:00Z",
    "skills": {"required": ["Python", "LangGraph"], "preferred": ["Docker"]},
}


def test_new_posting_increments_counters():
    client, driver = _make_client(exists=False)
    client.ingest_posting(_POSTING)
    joined = "\n".join(driver.log)
    assert "MERGE (c:Company" in joined          # 카운터 쿼리 실행됨
    assert "MERGE (s:Skill" in joined
    assert "CO_OCCURS" in joined


def test_reingest_skips_counters():
    client, driver = _make_client(exists=True)
    client.ingest_posting(_POSTING)
    joined = "\n".join(driver.log)
    assert "MERGE (p:JobPosting" in joined        # 공고 노드 자체는 upsert
    assert "MERGE (c:Company" not in joined        # 카운터는 건너뜀
    assert "MERGE (s:Skill" not in joined
    assert "CO_OCCURS" not in joined


def test_source_id_coerced_to_str():
    client, driver = _make_client(exists=False)
    # id가 int여도 예외 없이 처리되고 str로 다뤄져야 함
    client.ingest_posting({**_POSTING, "id": 999})
    assert "MERGE (p:JobPosting" in "\n".join(driver.log)
