# boost_confidence_from_github — 단어경계 매칭으로 오탐 방지 검증
from src.portfolio import github_connector as gc
from src.extraction.skill_extractor import DemonstratedSkill


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _skill(name, conf="medium"):
    return DemonstratedSkill(name=name, category="language", evidence="이력서", confidence=conf)


def test_no_false_positive_on_substring(monkeypatch):
    # repo 텍스트에 'micropython'만 있고 'python'은 단어로 없음 → Python confidence 상승 없어야 함
    monkeypatch.setattr(gc.httpx, "get",
                        lambda *a, **k: _Resp([{"name": "micropython-toy", "language": "C"}]))
    updated, changes = gc.boost_confidence_from_github([_skill("Python")], "someuser")
    assert "Python" not in changes
    assert updated[0].confidence == "medium"


def test_real_match_boosts(monkeypatch):
    # 'python'이 언어로 명시됨 → 상승
    monkeypatch.setattr(gc.httpx, "get",
                        lambda *a, **k: _Resp([{"name": "ml-app", "language": "Python"}]))
    updated, changes = gc.boost_confidence_from_github([_skill("Python")], "someuser")
    assert changes.get("Python") == "medium → high"
    assert updated[0].confidence == "high"
