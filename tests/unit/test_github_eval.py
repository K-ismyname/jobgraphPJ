# GitHub 평가자 — URL 없으면 빈 결과 (API 미호출)
from src.agent.evaluators.github_eval import create_github_evaluator


def test_no_url_empty():
    node = create_github_evaluator()
    out = node({"github_url": None})
    assert out["github_eval"]["skills"] == []


def test_invalid_url_empty():
    node = create_github_evaluator()
    out = node({"github_url": "not-a-url"})
    assert out["github_eval"]["skills"] == []
