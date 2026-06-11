# 특정 GitHub 레포(README + 언어 구성)에서 스킬 증거를 추출하는 평가자 (코드 modality)
from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, Callable

import httpx

from src.portfolio.github_connector import parse_github_repo, _SKILL_KEYWORDS

if TYPE_CHECKING:
    from src.agent.state import AppState


def _word_match(keyword: str, text: str) -> bool:
    """단어 경계 매칭. 'react'가 'reaction'에, 'aws'가 'draws'에 오탐되지 않게 한다."""
    pattern = rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])"
    return re.search(pattern, text) is not None


def create_github_evaluator() -> Callable[["AppState"], dict]:
    """GitHub 평가자 팩토리. 지정된 레포의 README·언어 구성에서 스킬 키워드를 찾아 증거로."""
    def evaluate(state: "AppState") -> dict:
        url = state.get("github_url")
        if not url:
            return {"github_eval": {"skills": []}}
        try:
            owner, repo = parse_github_repo(url)
        except ValueError as e:
            print(f"[github_eval] URL 파싱 실패: {e}")
            return {"github_eval": {"skills": []}}
        if not repo:
            print(f"[github_eval] 레포 미지정 (계정 주소만): {url}")
            return {"github_eval": {"skills": []}}

        token = os.getenv("GITHUB_TOKEN")
        headers = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        base = f"https://api.github.com/repos/{owner}/{repo}"
        try:
            lang_resp = httpx.get(f"{base}/languages", headers=headers, timeout=10)
            lang_resp.raise_for_status()
            languages = lang_resp.json()  # {"Python": 12345, ...}
        except Exception as e:
            print(f"[github_eval] GitHub API 실패: {e}")
            return {"github_eval": {"skills": []}}

        # README는 없을 수 있음 — 실패해도 언어 신호로 진행
        readme_text = ""
        try:
            rd = httpx.get(f"{base}/readme", headers={**headers, "Accept": "application/vnd.github.raw"}, timeout=10)
            if rd.status_code == 200:
                readme_text = rd.text
        except Exception as e:
            print(f"[github_eval] README 조회 실패: {e}")

        lang_text = " ".join(languages.keys()).lower()
        readme_lower = readme_text.lower()

        skills: list[dict] = []
        for skill_name, keywords in _SKILL_KEYWORDS.items():
            in_lang = any(_word_match(kw, lang_text) for kw in keywords)
            in_readme = any(_word_match(kw, readme_lower) for kw in keywords)
            if not (in_lang or in_readme):
                continue
            where = []
            if in_lang:
                where.append("주 언어")
            if in_readme:
                where.append("README")
            skills.append({
                "skill": skill_name,
                "evidence": f"{owner}/{repo} {'·'.join(where)}에서 {skill_name} 확인",
                "source": "github",
                "level_hint": "실무",
            })
        return {"github_eval": {"skills": skills}}

    return evaluate
