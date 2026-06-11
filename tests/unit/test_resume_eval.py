# 이력서 평가자 — 주입/PDF/텍스트 경로, fallback·중복·로그 검증
from types import SimpleNamespace
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


def test_injected_skills_deduped():
    # 주입 경로에서 정확한 중복은 제거되고 순서는 유지
    node = create_resume_evaluator(MagicMock())
    out = node({"resume_skills": ["Python", "Python", "FastAPI"], "pdf_path": None, "resume_text": None})
    names = [s["skill"] for s in out["resume_eval"]["skills"]]
    assert names == ["Python", "FastAPI"]


def test_injected_skills_logs_ignored_inputs(capsys):
    # resume_skills 주입 시 pdf/text를 무시한다는 안내 로그
    node = create_resume_evaluator(MagicMock())
    node({"resume_skills": ["Python"], "pdf_path": "resume.pdf", "resume_text": None})
    assert "무시" in capsys.readouterr().out


def _patch_extractors(monkeypatch, pdf_result, captured):
    # pdf_parser는 호출 시 pdf_result를 돌려주거나(callable이면 호출) 예외, extractor는 받은 text를 기록
    def fake_pdf(path):
        if isinstance(pdf_result, Exception):
            raise pdf_result
        return pdf_result

    def fake_extract(text, client):
        captured["text"] = text
        return SimpleNamespace(sections=[])  # 스킬 없음 — 본 테스트는 text 전달만 검증

    monkeypatch.setattr("src.portfolio.pdf_parser.extract_pdf_text", fake_pdf)
    monkeypatch.setattr("src.extraction.skill_extractor.extract_skills_from_resume", fake_extract)


def test_pdf_failure_falls_back_to_resume_text(monkeypatch):
    captured: dict = {}
    _patch_extractors(monkeypatch, RuntimeError("corrupt pdf"), captured)
    node = create_resume_evaluator(MagicMock())
    node({"resume_skills": [], "pdf_path": "broken.pdf", "resume_text": "Python 경력 3년"})
    assert captured["text"] == "Python 경력 3년"  # PDF 실패 → 백업 텍스트 사용


def test_whitespace_pdf_falls_back_to_resume_text(monkeypatch):
    captured: dict = {}
    _patch_extractors(monkeypatch, "   \n  ", captured)  # 공백만 추출
    node = create_resume_evaluator(MagicMock())
    node({"resume_skills": [], "pdf_path": "blank.pdf", "resume_text": "FastAPI 사용"})
    assert captured["text"] == "FastAPI 사용"


def test_pdf_success_does_not_fall_back(monkeypatch):
    captured: dict = {}
    _patch_extractors(monkeypatch, "정상 PDF 본문", captured)
    node = create_resume_evaluator(MagicMock())
    node({"resume_skills": [], "pdf_path": "ok.pdf", "resume_text": "이건 안 쓰여야 함"})
    assert captured["text"] == "정상 PDF 본문"  # PDF 성공 시 텍스트로 안 떨어짐
