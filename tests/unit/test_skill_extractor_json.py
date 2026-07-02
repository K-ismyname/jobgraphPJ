# _chat_json 재시도·파싱 견고화 테스트
import pytest

from src.extraction.skill_extractor import _chat_json


class _Msg:
    def __init__(self, content):
        self.message = type("M", (), {"content": content})


class _Resp:
    def __init__(self, content):
        self.choices = [_Msg(content)]


class _FakeCompletions:
    def __init__(self, contents):
        self._contents = list(contents)
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        c = self._contents.pop(0)
        if isinstance(c, Exception):
            raise c
        return _Resp(c)


class _FakeClient:
    def __init__(self, contents):
        self.chat = type("C", (), {"completions": _FakeCompletions(contents)})()


def test_parses_valid_json():
    client = _FakeClient(['{"required": ["Python"], "preferred": []}'])
    assert _chat_json(client, "prompt")["required"] == ["Python"]


def test_retries_once_on_bad_json():
    # 첫 응답은 깨진 JSON, 두 번째는 정상 → 재시도로 성공
    client = _FakeClient(["not json at all", '{"ok": true}'])
    assert _chat_json(client, "prompt") == {"ok": True}
    assert client.chat.completions.calls == 2


def test_raises_after_two_failures():
    client = _FakeClient(["broken", "still broken"])
    with pytest.raises(ValueError):
        _chat_json(client, "prompt")
