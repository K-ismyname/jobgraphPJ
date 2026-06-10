# 이력서(PDF/텍스트/주입)와 GitHub에서 보유 스킬·confidence를 모으는 Profile 노드
from __future__ import annotations

from typing import TYPE_CHECKING

from src.agent.state import AppState

if TYPE_CHECKING:
    from openai import OpenAI
    from src.storage.neo4j_client import Neo4jClient


def create_profile_node(neo4j: "Neo4jClient", openai_client: "OpenAI"):
    """Profile 노드 팩토리.

    입력 우선순위(기존 resume_agent와 동일):
      1. resume_skills 주입
      2. pdf_path 파싱
      3. resume_text 직접 입력
      4. Neo4j 기존 포트폴리오
    이후 github_url이 있으면 confidence를 갱신한다(순차).
    결과를 profile_result + resume_skills로 반환한다.
    """
    from src.portfolio.pdf_parser import extract_pdf_text
    from src.extraction.skill_extractor import extract_skills_from_resume
    from src.portfolio.github_connector import (
        boost_confidence_from_github, parse_github_username,
    )

    def _extract(resume_text: str, owner: str) -> list[str]:
        extraction = extract_skills_from_resume(resume_text, openai_client)
        extraction = extraction.model_copy(update={"candidate_name": owner})
        neo4j.save_portfolio(extraction)
        return [s.name for sec in extraction.sections for s in sec.skills]

    def profile_node(state: AppState) -> dict:
        owner = state["owner"]
        skills: list[str] = []

        if state.get("resume_skills"):
            skills = list(state["resume_skills"])
        elif state.get("pdf_path"):
            try:
                skills = _extract(extract_pdf_text(state["pdf_path"]), owner)
            except Exception as e:
                print(f"[profile] PDF 처리 실패: {e}")
        elif state.get("resume_text"):
            try:
                skills = _extract(state["resume_text"], owner)
            except Exception as e:
                print(f"[profile] 텍스트 처리 실패: {e}")
        else:
            existing = neo4j.get_portfolio_demonstrated_skills(owner)
            skills = [s.name for s in existing]

        github_changes: dict = {}
        if state.get("github_url"):
            try:
                username = parse_github_username(state["github_url"])
                current = neo4j.get_portfolio_demonstrated_skills(owner)
                if current:
                    _, github_changes = boost_confidence_from_github(current, username)
                    if github_changes:
                        neo4j.update_portfolio_confidence(owner, github_changes)
            except Exception as e:
                print(f"[profile] GitHub 처리 실패: {e}")

        return {
            "resume_skills": skills,
            "profile_result": {"skills": skills, "github_changes": github_changes},
        }

    return profile_node
