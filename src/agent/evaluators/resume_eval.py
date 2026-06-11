# 이력서에서 스킬 증거를 추출하는 평가자 (텍스트 modality)
from __future__ import annotations

from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from src.agent.state import AppState


def create_resume_evaluator(openai_client) -> Callable[["AppState"], dict]:
    """이력서 평가자 팩토리. resume_skills 주입 > pdf > resume_text 순."""
    from src.portfolio.pdf_parser import extract_pdf_text
    from src.extraction.skill_extractor import extract_skills_from_resume

    def evaluate(state: "AppState") -> dict:
        if state.get("resume_skills"):
            skills = [
                {"skill": s, "evidence": "이력서 주입 스킬", "source": "resume", "level_hint": None}
                for s in state["resume_skills"]
            ]
            return {"resume_eval": {"skills": skills}}

        text = None
        if state.get("pdf_path"):
            try:
                text = extract_pdf_text(state["pdf_path"])
            except Exception as e:
                print(f"[resume_eval] PDF 실패: {e}")
        elif state.get("resume_text"):
            text = state["resume_text"]

        if not text:
            return {"resume_eval": {"skills": []}}

        try:
            extraction = extract_skills_from_resume(text, openai_client)
            skills = [
                {"skill": sk.name, "evidence": sk.evidence, "source": "resume", "level_hint": sk.confidence}
                for sec in extraction.sections for sk in sec.skills
            ]
        except Exception as e:
            print(f"[resume_eval] 추출 실패: {e}")
            skills = []
        return {"resume_eval": {"skills": skills}}

    return evaluate
