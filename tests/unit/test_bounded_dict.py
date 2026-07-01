# BoundedDict 축출 로직 단위 테스트
from src.api.deps import BoundedDict


def test_evicts_oldest_over_capacity():
    d = BoundedDict(2)
    d["a"] = 1
    d["b"] = 2
    d["c"] = 3           # 'a' 축출
    assert "a" not in d
    assert list(d.keys()) == ["b", "c"]


def test_reinsert_refreshes_recency():
    d = BoundedDict(2)
    d["a"] = 1
    d["b"] = 2
    d["a"] = 10          # 'a'를 최신으로 갱신
    d["c"] = 3           # 이제 'b'가 가장 오래됨 → 축출
    assert "b" not in d
    assert d["a"] == 10
    assert d["c"] == 3
