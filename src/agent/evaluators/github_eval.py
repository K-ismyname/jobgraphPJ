# GitHub 레포에서 스킬 증거를 추출하는 평가자 (코드 modality)
from __future__ import annotations

import os
from typing import TYPE_CHECKING, Callable

import httpx

from src.portfolio.github_connector import parse_github_username, _SKILL_KEYWORDS

if TYPE_CHECKING:
    from src.agent.state import AppState


def create_github_evaluator() -> Callable[["AppState"], dict]:
    """GitHub 평가자 팩토리. 레포 메타데이터에서 스킬 키워드를 찾아 증거로."""
    def evaluate(state: "AppState") -> dict:
        url = state.get("github_url")
        if not url:
            return {"github_eval": {"skills": []}}
        try:
            username = parse_github_username(url)
        except ValueError as e:
            print(f"[github_eval] URL 파싱 실패: {e}")
            return {"github_eval": {"skills": []}}

        token = os.getenv("GITHUB_TOKEN")
        headers = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            resp = httpx.get(
                f"https://api.github.com/users/{username}/repos",
                headers=headers, params={"per_page": 100, "type": "owner"}, timeout=10,
            )
            resp.raise_for_status()
            repos = resp.json()
        except Exception as e:
            print(f"[github_eval] GitHub API 실패: {e}")
            return {"github_eval": {"skills": []}}

        repo_text = " ".join(
            f"{r.get('name','')} {r.get('description') or ''} "
            f"{' '.join(r.get('topics') or [])} {r.get('language') or ''}"
            for r in repos
        ).lower()

        skills: list[dict] = []
        for skill_name, keywords in _SKILL_KEYWORDS.items():
            if any(kw in repo_text for kw in keywords):
                skills.append({
                    "skill": skill_name,
                    "evidence": f"GitHub 레포에서 {skill_name} 사용 확인 ({username})",
                    "source": "github",
                    "level_hint": "실무",
                })
        return {"github_eval": {"skills": skills}}

    return evaluate
