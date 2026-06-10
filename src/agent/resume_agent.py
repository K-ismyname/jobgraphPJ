# PDF 이력서에서 스킬을 추출하고 Neo4j에 저장하는 Resume Agent 노드
from __future__ import annotations

from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage

from src.agent.state import AppState

if TYPE_CHECKING:
    from openai import OpenAI
    from src.storage.neo4j_client import Neo4jClient


def create_resume_node(neo4j: "Neo4jClient", openai_client: "OpenAI"):
    """Resume Agent 노드 팩토리.

    pdf_path가 있으면 PDF 파싱 → LLM 스킬 추출 → Neo4j 저장.
    없으면 resume_skills가 이미 제공된 경우 그대로 사용하고,
    아무것도 없으면 Neo4j 기존 PortfolioItem 스킬을 로드한다.

    Gap 루프 시작에 필요한 초기 상태(messages, iteration, seen_source_ids)도
    이 노드에서 설정한다.
    """
    from src.portfolio.pdf_parser import extract_pdf_text
    from src.extraction.skill_extractor import extract_skills_from_resume

    def resume_node(state: AppState) -> dict:
        pdf_path = state.get("pdf_path")
        owner = state["owner"]
        resume_text = None

        # 1순위: 이미 skills가 주입된 경우 (run_analysis() 직접 호출, RAGAS eval 등)
        if state.get("resume_skills"):
            skill_names = list(state["resume_skills"])
            print(f"[resume] 주입된 스킬 {len(skill_names)}개 사용")

        # 2순위: PDF 파싱
        elif pdf_path:
            print(f"[resume] PDF 파싱: {pdf_path}")
            try:
                resume_text = extract_pdf_text(pdf_path)
            except ValueError as e:
                print(f"[resume] PDF 파싱 실패: {e}")
                skill_names = []
            else:
                print("[resume] LLM 스킬 추출 중...")
                extraction = extract_skills_from_resume(resume_text, openai_client)
                extraction_with_name = extraction.model_copy(update={"candidate_name": owner})
                neo4j.save_portfolio(extraction_with_name)
                skill_names = [
                    skill.name
                    for section in extraction.sections
                    for skill in section.skills
                ]
                print(f"[resume] 추출 완료: {len(skill_names)}개 스킬 → Neo4j 저장")

        # 3순위: 이력서 텍스트 직접 입력
        elif state.get("resume_text"):
            resume_text = state["resume_text"]
            print(f"[resume] 텍스트 입력 ({len(resume_text)}자) → LLM 스킬 추출 중...")
            try:
                extraction = extract_skills_from_resume(resume_text, openai_client)
                extraction_with_name = extraction.model_copy(update={"candidate_name": owner})
                neo4j.save_portfolio(extraction_with_name)
                skill_names = [
                    skill.name
                    for section in extraction.sections
                    for skill in section.skills
                ]
                print(f"[resume] 추출 완료: {len(skill_names)}개 스킬 → Neo4j 저장")
            except Exception as e:
                print(f"[resume] 텍스트 스킬 추출 실패: {e}")
                skill_names = []

        # 4순위: Neo4j 기존 데이터
        else:
            existing = neo4j.get_portfolio_demonstrated_skills(owner)
            skill_names = [s.name for s in existing]
            print(f"[resume] PDF 없음 — Neo4j 기존 스킬 {len(skill_names)}개 사용")

        # Gap 루프의 시작 메시지 구성
        skills_str = ", ".join(skill_names) if skill_names else "없음 (공고 데이터만 사용)"
        user_msg = (
            f"직무 '{state['job_family']}'에 대해 갭 분석을 해주세요.\n"
            f"지원자 이름: {owner}\n"
            f"보유 스킬: {skills_str}"
        )

        return {
            "resume_skills": skill_names,
            "resume_text": resume_text,
            "messages": [HumanMessage(content=user_msg)],
            "iteration": 0,
            "seen_source_ids": [],
            "coach_messages": [],
            "coach_iteration": 0,
            "skill_trends": None,
        }

    return resume_node
