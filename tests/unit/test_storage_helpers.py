# clear_all 확인 가드 + get_skill_trend 신규급증 처리 테스트
import pytest

from src.storage.neo4j_client import Neo4jClient


# ── get_skill_trend ────────────────────────────────────────────
def _client_with_trend(rows):
    client = Neo4jClient.__new__(Neo4jClient)
    client.execute_query = lambda q, **k: rows
    return client


def test_trend_new_skill_flagged():
    # 이전 0 → 최근 등장: 신규 급증으로 표시 (delta 0.0으로 묻히면 안 됨)
    out = _client_with_trend([{"recent_count": 5, "prev_count": 0}]).get_skill_trend("X")
    assert out["delta_pct"] == 100.0
    assert out["is_new"] is True


def test_trend_growth_pct():
    out = _client_with_trend([{"recent_count": 15, "prev_count": 10}]).get_skill_trend("X")
    assert out["delta_pct"] == 50.0
    assert out["is_new"] is False


def test_trend_no_data():
    out = _client_with_trend([{"recent_count": 0, "prev_count": 0}]).get_skill_trend("X")
    assert out["delta_pct"] == 0.0
    assert out["is_new"] is False


# ── clear_all 확인 가드 ────────────────────────────────────────
class _Result:
    def __init__(self, row):
        self._row = row

    def single(self):
        return self._row


class _Session:
    def __init__(self, log):
        self._log = log

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, query, **params):
        self._log.append(query)
        return _Result({"c": 42})


class _Driver:
    def __init__(self):
        self.log = []

    def session(self):
        return _Session(self.log)


def _client_with_driver():
    client = Neo4jClient.__new__(Neo4jClient)
    client._driver = _Driver()
    return client


def test_clear_all_requires_confirm():
    client = _client_with_driver()
    with pytest.raises(ValueError):
        client.clear_all()   # confirm 없이 → 거부
    assert not any("DETACH DELETE" in q for q in client._driver.log)


def test_clear_all_runs_with_confirm():
    client = _client_with_driver()
    client.clear_all(confirm=True)
    assert any("DETACH DELETE" in q for q in client._driver.log)
