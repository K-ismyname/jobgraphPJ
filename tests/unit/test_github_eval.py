# GitHub 평가자 — 직군 스킬 사전 매칭, 별칭, 오프라인 가드
import json
from src.agent.evaluators.github_eval import (
    create_github_evaluator,
    _word_match,
    _manifest_match,
    _keywords_for,
    _skills_from_sources,
    _skills_from_pkg_json,
)
from src.portfolio.github_connector import parse_github_repo


class _FakeNeo4j:
    def __init__(self, skills):
        self._skills = skills

    def get_job_family_skills(self, job_family, **kwargs):
        return self._skills


def test_no_url_empty():
    node = create_github_evaluator(_FakeNeo4j(["Java"]), None)
    out = node({"github_urls": [], "job_family": "Software Engineer"})
    assert out["github_eval"]["skills"] == []


def test_invalid_url_empty():
    node = create_github_evaluator(_FakeNeo4j(["Java"]), None)
    out = node({"github_urls": ["not-a-url"], "job_family": "Software Engineer"})
    assert out["github_eval"]["skills"] == []


def test_account_url_only_empty():
    node = create_github_evaluator(_FakeNeo4j(["Java"]), None)
    out = node({"github_urls": ["https://github.com/fastapi"], "job_family": "Software Engineer"})
    assert out["github_eval"]["skills"] == []


def test_empty_vocab_empty():
    node = create_github_evaluator(_FakeNeo4j([]), None)
    out = node({"github_urls": ["https://github.com/x/y"], "job_family": "Software Engineer"})
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


import types
from src.agent.evaluators.github_eval import _assess_project_and_skills


def _fake_openai(content):
    resp = types.SimpleNamespace(
        choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=content))])
    return types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=lambda **k: resp)))


def test_assess_parses_llm_json():
    payload = json.dumps({
        "project_type": "FastAPI 백엔드",
        "structure_summary": "RAG 챗봇 API",
        "skill_assessments": [
            {"skill": "Python", "current_usage": "고급 패턴",
             "fit_assessment": "핵심 언어", "how_to_add": "이미 사용 중", "relevant_files": ["main.py"]}
        ]
    })
    result = _assess_project_and_skills(_fake_openai(payload), "me", "proj",
                                        {"main.py": "print('hello')"}, ["Python"], "readme")
    assert result["repo"] == "me/proj"
    assert result["project_type"] == "FastAPI 백엔드"
    assert result["skill_assessments"][0]["skill"] == "Python"


def test_skills_from_pkg_json_maps_ecosystem():
    pkg = json.dumps({"dependencies": {
        "drizzle-orm": "^0.30.0",
        "@neondatabase/serverless": "^0.9.0",
        "next-auth": "^5.0.0",
    }, "devDependencies": {"drizzle-kit": "^0.20.0"}})
    vocab = ["PostgreSQL", "NextAuth.js", "React", "Docker"]
    results = _skills_from_pkg_json(pkg, vocab)
    by_skill = {r["skill"]: r for r in results}
    assert "PostgreSQL" in by_skill
    assert "NextAuth.js" in by_skill
    pg_evidence = by_skill["PostgreSQL"]["evidence"]
    assert any(p in pg_evidence for p in ("drizzle-orm", "@neondatabase/serverless", "drizzle-kit"))
    assert by_skill["PostgreSQL"]["source"] == "github"


def test_skills_from_pkg_json_no_out_of_vocab():
    pkg = json.dumps({"dependencies": {"redis": "^4.0.0"}})
    # Redis not in vocab
    results = _skills_from_pkg_json(pkg, ["PostgreSQL", "Docker"])
    assert results == []


def test_skills_from_pkg_json_deduplicates():
    # drizzle-orm, drizzle-kit, @neondatabase/serverless all → PostgreSQL
    pkg = json.dumps({"dependencies": {
        "drizzle-orm": "^0.30.0",
        "drizzle-kit": "^0.20.0",
        "@neondatabase/serverless": "^0.9.0",
    }})
    results = _skills_from_pkg_json(pkg, ["PostgreSQL"])
    assert len([r for r in results if r["skill"] == "PostgreSQL"]) == 1


def test_skills_from_pkg_json_invalid_json_returns_empty():
    assert _skills_from_pkg_json("not json", ["PostgreSQL"]) == []


def test_assess_no_openai_returns_empty():
    result = _assess_project_and_skills(None, "me", "proj", {}, ["Python"], "")
    assert result == {}


def test_assess_bad_json_returns_empty():
    result = _assess_project_and_skills(_fake_openai("not json"), "me", "proj",
                                        {"f.py": "x=1"}, ["Python"], "")
    assert result == {}
