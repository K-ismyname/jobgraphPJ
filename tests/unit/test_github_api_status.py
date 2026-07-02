# GitHub API 실패(rate limit 등)가 에러 JSON을 정상 데이터인 양 삼키지 않는지 검증
import httpx
import pytest

from src.agent.evaluators import github_eval as ge


class _FakeResp:
    """GitHub의 rate-limit 응답 재현 — 403이지만 .json()은 정상 파싱되는 본문."""

    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = ""

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"{self.status_code} error", request=None, response=self
            )


def test_get_json_raises_on_rate_limit(monkeypatch):
    # GitHub rate limit 응답: 403이지만 body는 유효한 JSON — status 체크 없이는 예외가 안 남
    monkeypatch.setattr(
        ge.httpx, "get",
        lambda *a, **k: _FakeResp(403, {"message": "API rate limit exceeded for x.x.x.x"}),
    )
    with pytest.raises(Exception):
        ge._get_json("https://api.github.com/repos/x/y/languages", {})


def test_get_json_succeeds_on_200(monkeypatch):
    monkeypatch.setattr(
        ge.httpx, "get",
        lambda *a, **k: _FakeResp(200, {"Python": 41234, "TypeScript": 35248}),
    )
    out = ge._get_json("https://api.github.com/repos/x/y/languages", {})
    assert out == {"Python": 41234, "TypeScript": 35248}


def test_eval_one_returns_empty_on_rate_limited_languages(monkeypatch):
    # 실제 재현: languages 호출이 rate limit(403)이면 lang_text가 에러 메시지로
    # 오염되는 대신 _eval_one이 빈 결과를 반환하고 로그를 남겨야 한다.
    def fake_get(url, headers=None, timeout=None):
        if url.endswith("/languages"):
            return _FakeResp(403, {"message": "API rate limit exceeded"})
        return _FakeResp(200, {})

    monkeypatch.setattr(ge.httpx, "get", fake_get)
    # _eval_one은 create_github_evaluator 내부 클로저라 evaluate()를 통해 검증
    node = ge.create_github_evaluator(
        neo4j=_FakeNeo4jWithVocab(["Python"]), openai=None,
    )
    out = node({"github_urls": ["https://github.com/K-ismyname/da_agent"], "job_family": "AI/LLM Engineer"})
    assert out["github_eval"]["skills"] == []   # 오염된 lang_text로 Python이 잘못 감지되지 않음


class _FakeNeo4jWithVocab:
    def __init__(self, vocab):
        self._vocab = vocab

    def get_job_family_skills(self, job_family, **kwargs):
        return self._vocab

    def get_skill_neighbors(self, vocab):
        return {}

    def get_skill_categories(self, skills):
        return {}
