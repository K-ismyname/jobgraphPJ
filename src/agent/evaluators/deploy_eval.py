# 배포 URL을 fetch해 작동 실증 + 프론트 기술을 추출하는 평가자 (웹 modality)
from __future__ import annotations

from typing import TYPE_CHECKING, Callable

import httpx

from src.agent.evaluators.github_eval import _word_match, _keywords_for

if TYPE_CHECKING:
    from src.agent.state import AppState
    from src.storage.neo4j_client import Neo4jClient


def _build_text(html: str, headers: dict[str, str]) -> str:
    """HTML 본문 + 응답 헤더를 매칭용 소문자 텍스트로 합친다."""
    header_text = " ".join(f"{k} {v}" for k, v in headers.items())
    return f"{html} {header_text}".lower()


def _skills_from_deploy(text: str, vocab: list[str]) -> list[dict]:
    """직군 스킬 어휘를 배포 텍스트에 단어경계+별칭 매칭한다 (source=deploy → 실증).

    raw HTML은 노이즈가 많아 1~2자 키워드(go/js/ts/c/r 등)는 오탐 위험이 크므로 제외한다.
    """
    skills: list[dict] = []
    for skill in vocab:
        keywords = [kw for kw in _keywords_for(skill) if len(kw) >= 3]
        if any(_word_match(kw, text) for kw in keywords):
            skills.append({
                "skill": skill,
                "evidence": f"배포 URL 작동 확인 — {skill} 사용 흔적",
                "source": "deploy",
                "level_hint": "실무",
            })
    return skills


def create_deploy_evaluator(neo4j: "Neo4jClient") -> Callable[["AppState"], dict]:
    """배포 URL 평가자 팩토리. 작동하는 배포에서 직군 스킬을 코드 외부 근거로 확인한다."""
    def _eval_one(url: str, vocab) -> list:
        try:
            resp = httpx.get(url, timeout=10, follow_redirects=True,
                             headers={"User-Agent": "Mozilla/5.0 (job-skill-analyzer)"})
            resp.raise_for_status()
        except Exception as e:
            print(f"[deploy_eval] URL fetch 실패 (미작동/접근불가): {e}")
            return []
        text = _build_text(resp.text, dict(resp.headers))
        return _skills_from_deploy(text, vocab)

    def evaluate(state: "AppState") -> dict:
        urls = state.get("deploy_urls") or []
        if not urls:
            return {"deploy_eval": {"skills": []}}
        vocab = neo4j.get_job_family_skills(state.get("job_family") or "")
        if not vocab:
            print(f"[deploy_eval] 직군 스킬 어휘 없음 (job_family={state.get('job_family')!r})")
            return {"deploy_eval": {"skills": []}}
        merged: list = []
        seen: set = set()
        for url in urls:
            for s in _eval_one(url, vocab):
                key = s.get("skill") if isinstance(s, dict) else s
                if key not in seen:
                    seen.add(key)
                    merged.append(s)
        return {"deploy_eval": {"skills": merged}}

    return evaluate
