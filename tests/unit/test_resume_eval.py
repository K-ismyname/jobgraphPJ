# 이력서 평가자 — 주입 스킬 경로 (LLM 미호출)
from unittest.mock import MagicMock
from src.agent.evaluators.resume_eval import create_resume_evaluator


def test_injected_skills():
    node = create_resume_evaluator(MagicMock())
    out = node({"resume_skills": ["Python", "FastAPI"], "pdf_path": None, "resume_text": None})
    skills = out["resume_eval"]["skills"]
    assert {s["skill"] for s in skills} == {"Python", "FastAPI"}
    assert all(s["source"] == "resume" for s in skills)


def test_no_input_empty():
    node = create_resume_evaluator(MagicMock())
    out = node({"resume_skills": [], "pdf_path": None, "resume_text": None})
    assert out["resume_eval"]["skills"] == []
