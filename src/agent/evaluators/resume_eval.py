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
            if state.get("pdf_path") or state.get("resume_text"):
                print("[resume_eval] resume_skills 주입됨 — pdf_path/resume_text는 무시")
            seen: set[str] = set()
            skills = []
            for s in state["resume_skills"]:
                if s in seen:  # 정확한 중복 제거 (순서 유지)
                    continue
                seen.add(s)
                skills.append({"skill": s, "evidence": "이력서 주입 스킬", "source": "resume", "level_hint": None})
            return {"resume_eval": {"skills": skills}}

        text = None
        if state.get("pdf_path"):
            try:
                text = extract_pdf_text(state["pdf_path"])
            except Exception as e:
                print(f"[resume_eval] PDF 실패: {e}")
        # PDF가 없거나·실패·공백이면 resume_text로 fallback
        if not (text and text.strip()) and state.get("resume_text"):
            text = state["resume_text"]

        if not (text and text.strip()):
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
