# 배포 URL 평가자 — 순수 매칭 + 입력 가드 (네트워크 미호출)
from src.agent.evaluators.deploy_eval import (
    create_deploy_evaluator,
    _build_text,
    _skills_from_deploy,
)


class _FakeNeo4j:
    def __init__(self, skills):
        self._skills = skills

    def get_job_family_skills(self, job_family):
        return self._skills


def test_no_url_empty():
    node = create_deploy_evaluator(_FakeNeo4j(["React"]))
    out = node({"deploy_url": None, "job_family": "Frontend Engineer"})
    assert out["deploy_eval"]["skills"] == []


def test_build_text_combines_html_and_headers_lowercased():
    text = _build_text("<div>Built with NEXT.js</div>", {"X-Powered-By": "Next.js", "Server": "Vercel"})
    assert "next.js" in text and "vercel" in text


def test_skills_from_deploy_matches_vocab_and_marks_verified_source():
    text = _build_text("<script src='/_next/static/chunk.js'></script> uses react and tailwind", {"server": "vercel"})
    skills = _skills_from_deploy(text, vocab=["React", "Tailwind CSS", "Java"])
    by = {s["skill"]: s for s in skills}
    assert "React" in by and "Tailwind CSS" in by and "Java" not in by
    assert all(s["source"] == "deploy" for s in skills)
    assert "작동" in by["React"]["evidence"]
