# GitHub 평가자 — 직군 스킬 사전 매칭, 별칭, 오프라인 가드
from src.agent.evaluators.github_eval import (
    create_github_evaluator,
    _word_match,
    _manifest_match,
    _keywords_for,
    _skills_from_sources,
)
from src.portfolio.github_connector import parse_github_repo


class _FakeNeo4j:
    def __init__(self, skills):
        self._skills = skills

    def get_job_family_skills(self, job_family):
        return self._skills


def test_no_url_empty():
    node = create_github_evaluator(_FakeNeo4j(["Java"]))
    out = node({"github_url": None, "job_family": "Software Engineer"})
    assert out["github_eval"]["skills"] == []


def test_invalid_url_empty():
    node = create_github_evaluator(_FakeNeo4j(["Java"]))
    out = node({"github_url": "not-a-url", "job_family": "Software Engineer"})
    assert out["github_eval"]["skills"] == []


def test_account_url_only_empty():
    node = create_github_evaluator(_FakeNeo4j(["Java"]))
    out = node({"github_url": "https://github.com/fastapi", "job_family": "Software Engineer"})
    assert out["github_eval"]["skills"] == []


def test_empty_vocab_empty():
    node = create_github_evaluator(_FakeNeo4j([]))
    out = node({"github_url": "https://github.com/x/y", "job_family": "Software Engineer"})
    assert out["github_eval"]["skills"] == []


def test_parse_github_repo():
    assert parse_github_repo("https://github.com/fastapi/fastapi") == ("fastapi", "fastapi")
    assert parse_github_repo("https://github.com/fastapi/fastapi/blob/master/README.md") == ("fastapi", "fastapi")
    assert parse_github_repo("https://github.com/fastapi") == ("fastapi", None)


def test_word_match_no_false_positive():
    assert _word_match("react", "this code reacts to a reaction") is False
    assert _word_match("aws", "the program draws shapes") is False
    assert _word_match("react", "built with react and vite") is True


def test_manifest_match_intended_cases():
    # 의도된 4개 케이스 — 모두 True
    assert _manifest_match("docker", "dockerfile") is True
    assert _manifest_match("docker", "docker-compose.yml") is True
    assert _manifest_match("go", "go.mod") is True
    assert _manifest_match("cargo", "cargo.toml") is True


def test_manifest_match_no_prefix_false_positive():
    # 짧은 prefix 오탐 방지 — 모두 False
    assert _manifest_match("c", "cargo.toml") is False
    assert _manifest_match("do", "dockerfile") is False


def test_keywords_for_includes_aliases():
    kws = _keywords_for("PostgreSQL")
    assert "postgresql" in kws and "postgres" in kws


def test_skills_from_vocab_matches_alias_and_manifest():
    vocab = ["PostgreSQL", "Java", "Docker"]
    skills = _skills_from_sources(
        owner="me", repo="proj",
        lang_text="Java", readme_text="uses postgres for storage",
        manifest_text="Dockerfile", vocab=vocab,
    )
    by_name = {s["skill"]: s for s in skills}
    assert by_name.keys() == {"PostgreSQL", "Java", "Docker"}
    assert "README" in by_name["PostgreSQL"]["evidence"]
    assert "주 언어" in by_name["Java"]["evidence"]
    assert "의존성/설정파일" in by_name["Docker"]["evidence"]
    assert all(s["source"] == "github" for s in skills)


def test_skills_none_when_no_match():
    skills = _skills_from_sources("me", "proj", "", "", "", vocab=["Kotlin", "Rust"])
    assert skills == []
