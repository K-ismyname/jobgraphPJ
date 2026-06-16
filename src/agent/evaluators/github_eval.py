# 지정 GitHub 레포에서 대상 직군의 스킬을 코드 근거로 검증하는 평가자 (코드 modality)
from __future__ import annotations

import json
import os
import re
from typing import TYPE_CHECKING, Callable

import httpx

from src.portfolio.github_connector import parse_github_repo
from src.extraction.normalizer import SKILL_ALIASES

if TYPE_CHECKING:
    from src.agent.state import AppState
    from src.storage.neo4j_client import Neo4jClient

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


def _manifest_match(keyword: str, text: str) -> bool:
    """의존성/설정 소스 매칭. 단어 경계 매칭에 더해, 알려진 설정파일 파일명을 신호로 잡는다
    ('docker'가 'Dockerfile' 파일명에 붙어 있어도 인식하도록).

    파일명을 '.'/'-'로 나눈 첫 토큰이 keyword와 같을 때만 매칭한다('go'→go.mod 등).
    'dockerfile'처럼 구분자 없는 합성어는 keyword+'file'로 따로 허용한다.
    이로써 'c'→cargo.toml, 'do'→dockerfile 같은 prefix 오탐을 막는다."""
    if _word_match(keyword, text):
        return True
    for manifest in _PRESENCE_MANIFESTS:
        first_token = re.split(r"[.\-]", manifest, maxsplit=1)[0]
        if (first_token == keyword or manifest == keyword + "file") and _word_match(manifest, text):
            return True
    return False


def _keywords_for(skill: str) -> list[str]:
    """스킬명 + 같은 정규화명을 갖는 별칭들을 매칭 키워드로 (예: PostgreSQL → postgres)."""
    canon = skill.lower()
    kws = {canon}
    for alias, mapped in SKILL_ALIASES.items():
        if mapped.lower() == canon:
            kws.add(alias.lower())
    return list(kws)


def _skills_from_sources(
    owner: str, repo: str, lang_text: str, readme_text: str, manifest_text: str,
    vocab: list[str],
) -> list[dict[str, str]]:
    """대상 직군 스킬(vocab)을 주 언어·README·의존성파일에서 찾아 출처를 명시한 증거로 만든다."""
    lang_l, readme_l, manifest_l = lang_text.lower(), readme_text.lower(), manifest_text.lower()
    skills: list[dict[str, str]] = []
    for skill_name in vocab:
        kws = _keywords_for(skill_name)
        in_lang = any(_word_match(kw, lang_l) for kw in kws)
        in_readme = any(_word_match(kw, readme_l) for kw in kws)
        in_manifest = any(_manifest_match(kw, manifest_l) for kw in kws)
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


def _profile_one(openai, owner: str, repo: str, readme: str, description: str,
                 topics: list, file_names: list, manifest_text: str) -> dict:
    """repo 정보(README·설명·구조·의존성)를 LLM으로 읽어 프로젝트 프로필 생성."""
    empty = {"repo": f"{owner}/{repo}", "summary": "", "tech_stack": [], "observations": []}
    if not openai:
        return empty
    prompt = (
        "다음 GitHub 저장소 정보를 보고 프로젝트를 파악해 JSON으로만 답하세요.\n"
        f"저장소: {owner}/{repo}\n"
        f"설명: {description}\n"
        f"topics: {', '.join(topics)}\n"
        f"README:\n{readme[:3000]}\n"
        f"파일 구조: {', '.join(file_names[:50])}\n"
        f"의존성: {manifest_text[:1000]}\n\n"
        '형식(코드펜스 없이): {"summary": "이 프로젝트가 무엇을 하는지 한두 문장", '
        '"tech_stack": ["핵심 기술명만, 버전 없이 5~8개. 의존성 목록을 그대로 복사하지 말 것"], '
        '"observations": ["눈에 띄는 점·빠진 것, 예: Dockerfile 없음·테스트 없음·CI 없음"]}'
    )
    try:
        resp = openai.chat.completions.create(
            model="gpt-4o-mini", max_tokens=512,
            messages=[{"role": "user", "content": prompt}])
        raw = (resp.choices[0].message.content or "").strip().replace("```json", "").replace("```", "").strip()
        data = json.loads(raw)
        return {"repo": f"{owner}/{repo}",
                "summary": data.get("summary", ""),
                "tech_stack": list(data.get("tech_stack") or []),
                "observations": list(data.get("observations") or [])}
    except Exception as e:
        print(f"[github_eval] 프로필 생성 실패: {e}")
        return empty


def create_github_evaluator(neo4j: "Neo4jClient", openai=None) -> Callable[["AppState"], dict]:
    """GitHub 평가자 팩토리. 대상 직군의 스킬 집합을 레포 코드 근거로 검증한다."""
    def _eval_one(url: str, vocab) -> tuple[list, dict | None]:
        try:
            owner, repo = parse_github_repo(url)
        except ValueError as e:
            print(f"[github_eval] URL 파싱 실패: {e}")
            return [], None
        if not repo:
            print(f"[github_eval] 레포 미지정 (계정 주소만): {url}")
            return [], None

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
            return [], None
        lang_text = " ".join(languages.keys())

        # repo 메타 (description·topics)
        description, topics = "", []
        try:
            meta = httpx.get(base, headers=headers, timeout=10).json()
            if isinstance(meta, dict):
                description = meta.get("description") or ""
                topics = meta.get("topics") or []
        except Exception as e:
            print(f"[github_eval] repo 메타 조회 실패: {e}")

        # README (없을 수 있음)
        readme_text = ""
        try:
            rd = httpx.get(f"{base}/readme", headers=raw_headers, timeout=10)
            if rd.status_code == 200:
                readme_text = rd.text
        except Exception as e:
            print(f"[github_eval] README 조회 실패: {e}")

        # 루트 파일 구조 + 의존성/설정 파일
        file_names: list = []
        manifest_parts: list[str] = []
        try:
            root = httpx.get(f"{base}/contents", headers=headers, timeout=10).json()
            if not isinstance(root, list):
                root = []
            file_names = [it["name"] for it in root]
            present = [it["name"] for it in root if it["name"].lower() in _ALL_MANIFESTS]
            for name in present:
                manifest_parts.append(name)
                if name.lower() in _TEXT_MANIFESTS:
                    body = httpx.get(f"{base}/contents/{name}", headers=raw_headers, timeout=10)
                    if body.status_code == 200:
                        manifest_parts.append(body.text)
        except Exception as e:
            print(f"[github_eval] 의존성 파일 조회 실패: {e}")
        manifest_text = " ".join(manifest_parts)

        skills = _skills_from_sources(owner, repo, lang_text, readme_text, manifest_text, vocab)
        profile = _profile_one(openai, owner, repo, readme_text, description, topics, file_names, manifest_text)
        return skills, profile

    def evaluate(state: "AppState") -> dict:
        urls = state.get("github_urls") or []
        if not urls:
            return {"github_eval": {"skills": [], "profiles": []}}
        vocab = neo4j.get_job_family_skills(state.get("job_family") or "")
        if not vocab:
            print(f"[github_eval] 직군 스킬 어휘 없음 (job_family={state.get('job_family')!r})")
            return {"github_eval": {"skills": [], "profiles": []}}
        merged: list = []
        seen: set = set()
        profiles: list = []
        for url in urls:
            skills, profile = _eval_one(url, vocab)
            for s in skills:
                key = s.get("skill") if isinstance(s, dict) else s
                if key not in seen:
                    seen.add(key)
                    merged.append(s)
            if profile:
                profiles.append(profile)
        return {"github_eval": {"skills": merged, "profiles": profiles}}

    return evaluate

    return evaluate
