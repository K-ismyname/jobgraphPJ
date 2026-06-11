# 특정 GitHub 레포(README + 언어 + 의존성/설정 파일)에서 스킬 증거를 추출하는 평가자 (코드 modality)
from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, Callable

import httpx

from src.portfolio.github_connector import parse_github_repo, _SKILL_KEYWORDS

if TYPE_CHECKING:
    from src.agent.state import AppState

# 본문을 읽어 패키지명을 매칭할 의존성 파일 (소문자)
_TEXT_MANIFESTS = {
    "requirements.txt", "pyproject.toml", "pipfile", "setup.py",
    "package.json", "environment.yml",
}
# 존재만으로 의미가 있는 설정 파일 (파일명 자체를 신호로 사용)
_PRESENCE_MANIFESTS = {"dockerfile", "docker-compose.yml", "go.mod", "cargo.toml"}
_ALL_MANIFESTS = _TEXT_MANIFESTS | _PRESENCE_MANIFESTS


def _word_match(keyword: str, text: str) -> bool:
    """단어 경계 매칭. 'react'가 'reaction'에, 'aws'가 'draws'에 오탐되지 않게 한다."""
    pattern = rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])"
    return re.search(pattern, text) is not None


def _skills_from_sources(
    owner: str, repo: str, lang_text: str, readme_text: str, manifest_text: str,
) -> list[dict[str, str]]:
    """세 소스(주 언어·README·의존성/설정파일)에서 스킬을 찾아 출처를 명시한 증거로 만든다."""
    lang_l, readme_l, manifest_l = lang_text.lower(), readme_text.lower(), manifest_text.lower()
    skills: list[dict[str, str]] = []
    for skill_name, keywords in _SKILL_KEYWORDS.items():
        in_lang = any(_word_match(kw, lang_l) for kw in keywords)
        in_readme = any(_word_match(kw, readme_l) for kw in keywords)
        in_manifest = any(_word_match(kw, manifest_l) for kw in keywords)
        if not (in_lang or in_readme or in_manifest):
            continue
        where: list[str] = []
        if in_manifest:
            where.append("의존성/설정파일")
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
    return skills


def create_github_evaluator() -> Callable[["AppState"], dict]:
    """GitHub 평가자 팩토리. 지정된 레포의 언어·README·의존성 파일에서 스킬을 추출한다."""
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
        raw_headers = {**headers, "Accept": "application/vnd.github.raw"}
        base = f"https://api.github.com/repos/{owner}/{repo}"

        # 주 언어 (레포 없으면 여기서 실패 → 빈 결과)
        try:
            lang_resp = httpx.get(f"{base}/languages", headers=headers, timeout=10)
            lang_resp.raise_for_status()
            languages = lang_resp.json()
        except Exception as e:
            print(f"[github_eval] GitHub API 실패: {e}")
            return {"github_eval": {"skills": []}}
        lang_text = " ".join(languages.keys())

        # README (없을 수 있음)
        readme_text = ""
        try:
            rd = httpx.get(f"{base}/readme", headers=raw_headers, timeout=10)
            if rd.status_code == 200:
                readme_text = rd.text
        except Exception as e:
            print(f"[github_eval] README 조회 실패: {e}")

        # 의존성/설정 파일 (루트만 확인 — 하위 폴더는 범위 밖)
        manifest_parts: list[str] = []
        try:
            root = httpx.get(f"{base}/contents", headers=headers, timeout=10).json()
            if not isinstance(root, list):
                root = []
            present = [it["name"] for it in root if it["name"].lower() in _ALL_MANIFESTS]
            for name in present:
                manifest_parts.append(name)  # 파일명 자체가 신호 (Dockerfile → Docker)
                if name.lower() in _TEXT_MANIFESTS:
                    body = httpx.get(f"{base}/contents/{name}", headers=raw_headers, timeout=10)
                    if body.status_code == 200:
                        manifest_parts.append(body.text)
        except Exception as e:
            print(f"[github_eval] 의존성 파일 조회 실패: {e}")
        manifest_text = " ".join(manifest_parts)

        skills = _skills_from_sources(owner, repo, lang_text, readme_text, manifest_text)
        return {"github_eval": {"skills": skills}}

    return evaluate
