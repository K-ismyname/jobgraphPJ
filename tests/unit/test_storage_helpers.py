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
    # 표본 12건 ≥ _MIN_TREND_SAMPLE 이라 증감률까지 산출된다.
    out = _client_with_trend([{"recent_count": 12, "prev_count": 0}]).get_skill_trend("X")
    assert out["delta_pct"] == 100.0
    assert out["is_new"] is True


def test_trend_growth_pct():
    out = _client_with_trend([{"recent_count": 15, "prev_count": 10}]).get_skill_trend("X")
    assert out["delta_pct"] == 50.0
    assert out["is_new"] is False


def test_trend_low_sample_suppresses_delta():
    # 표본이 부족하면 증감률을 내지 않는다 — 1건 차이가 ±100%로 튀어 무의미하기 때문.
    # is_new(신규 등장)는 표본과 무관한 사실이라 그대로 유지한다.
    out = _client_with_trend([{"recent_count": 5, "prev_count": 0}]).get_skill_trend("X")
    assert out["delta_pct"] is None
    assert out["low_sample"] is True
    assert out["is_new"] is True


def test_trend_no_data():
    # 데이터가 전무하면 표본 부족으로 처리 — 증감률 0.0은 "변화 없음"이라는 잘못된 신호다.
    out = _client_with_trend([{"recent_count": 0, "prev_count": 0}]).get_skill_trend("X")
    assert out["delta_pct"] is None
    assert out["low_sample"] is True
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


@pytest.fixture
def local_db(monkeypatch):
    """로컬 Neo4j를 가리키는 환경 — 파괴적 작업이 허용되는 조건."""
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.delenv("ALLOW_REMOTE_DESTRUCTIVE", raising=False)


def test_clear_all_requires_confirm(local_db):
    client = _client_with_driver()
    with pytest.raises(ValueError):
        client.clear_all()   # confirm 없이 → 거부
    assert not any("DETACH DELETE" in q for q in client._driver.log)


def test_clear_all_runs_with_confirm(local_db):
    client = _client_with_driver()
    client.clear_all(confirm=True)
    assert any("DETACH DELETE" in q for q in client._driver.log)


def test_clear_all_blocked_on_remote_db(monkeypatch):
    """원격(Aura) DB에는 confirm=True여도 파괴적 작업을 거부한다.

    로컬 개발과 라이브가 같은 인스턴스를 보는 구성에서는 실수 한 번이 프로덕션 소실이다.
    실제로 백필 실험이 라이브 직군 분석을 오염시킨 전례가 있다.
    """
    monkeypatch.setenv("NEO4J_URI", "neo4j+s://abc123.databases.neo4j.io")
    monkeypatch.delenv("ALLOW_REMOTE_DESTRUCTIVE", raising=False)
    client = _client_with_driver()
    with pytest.raises(RuntimeError, match="원격"):
        client.clear_all(confirm=True)
    assert not any("DETACH DELETE" in q for q in client._driver.log)


def test_clear_all_remote_allowed_with_explicit_optin(monkeypatch):
    # 정말 의도한 경우에만 명시적 환경변수로 해제
    monkeypatch.setenv("NEO4J_URI", "neo4j+s://abc123.databases.neo4j.io")
    monkeypatch.setenv("ALLOW_REMOTE_DESTRUCTIVE", "true")
    client = _client_with_driver()
    client.clear_all(confirm=True)
    assert any("DETACH DELETE" in q for q in client._driver.log)


def test_is_remote_detects_aura_scheme(monkeypatch):
    client = Neo4jClient.__new__(Neo4jClient)
    monkeypatch.setenv("NEO4J_URI", "neo4j+s://x.databases.neo4j.io")
    assert client.is_remote() is True
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    assert client.is_remote() is False
