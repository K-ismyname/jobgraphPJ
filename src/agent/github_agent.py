# GitHub 리포 메타데이터로 이력서 스킬 confidence를 검증·상승시키는 노드
from __future__ import annotations

from typing import TYPE_CHECKING

from src.agent.state import AppState

if TYPE_CHECKING:
    from src.storage.neo4j_client import Neo4jClient


def create_github_node(neo4j: "Neo4jClient"):
    """GitHub Agent 노드 팩토리.

    github_url이 없으면 바로 skipped 반환.
    있으면 GitHub API로 리포 목록을 조회하고 스킬 confidence를 한 단계 상승시킨다.
    """
    from src.portfolio.github_connector import boost_confidence_from_github, parse_github_username

    def github_node(state: AppState) -> dict:
        github_url = state.get("github_url")
        if not github_url:
            print("[github] GitHub URL 미제공 — 건너뜀")
            return {"github_result": {"skipped": True, "reason": "GitHub URL 미제공"}}

        try:
            username = parse_github_username(github_url)
        except ValueError as e:
            print(f"[github] URL 파싱 실패: {e}")
            return {"github_result": {"skipped": True, "reason": str(e)}}

        print(f"[github] GitHub 조회: {username}")
        current_skills = neo4j.get_portfolio_demonstrated_skills(state["owner"])
        if not current_skills:
            return {"github_result": {"skipped": True, "reason": "Neo4j PortfolioItem 없음"}}

        updated, changes = boost_confidence_from_github(current_skills, username)
        if changes:
            neo4j.update_portfolio_confidence(state["owner"], changes)
            print(f"[github] confidence 상승: {changes}")
        else:
            print("[github] confidence 변경 없음")

        return {"github_result": {"changed": changes, "skipped": False, "username": username}}

    return github_node
