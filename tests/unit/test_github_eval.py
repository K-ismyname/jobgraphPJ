# GitHub 평가자 — 오프라인 경로(URL 파싱·가드)와 단어 경계 매칭 검증
from src.agent.evaluators.github_eval import create_github_evaluator, _word_match
from src.portfolio.github_connector import parse_github_repo


def test_no_url_empty():
    node = create_github_evaluator()
    out = node({"github_url": None})
    assert out["github_eval"]["skills"] == []


def test_invalid_url_empty():
    node = create_github_evaluator()
    out = node({"github_url": "not-a-url"})
    assert out["github_eval"]["skills"] == []


def test_account_url_only_empty():
    # 레포가 지정되지 않은 계정 주소 → API 호출 없이 빈 결과
    node = create_github_evaluator()
    out = node({"github_url": "https://github.com/fastapi"})
    assert out["github_eval"]["skills"] == []


def test_parse_github_repo():
    assert parse_github_repo("https://github.com/fastapi/fastapi") == ("fastapi", "fastapi")
    # 파일(blob) 주소를 줘도 owner/repo만 뽑는다
    assert parse_github_repo("https://github.com/fastapi/fastapi/blob/master/README.md") == ("fastapi", "fastapi")
    # 계정 주소만 → repo는 None
    assert parse_github_repo("https://github.com/fastapi") == ("fastapi", None)


def test_word_match_no_false_positive():
    # 짧은 키워드가 더 긴 단어 안에서 오탐되지 않아야 함
    assert _word_match("react", "this code reacts to a reaction") is False
    assert _word_match("aws", "the program draws shapes") is False
    assert _word_match("react", "built with react and vite") is True
    assert _word_match("python", "written in python") is True
