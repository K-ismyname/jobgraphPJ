# GitHub API로 이력서 기술 증거를 검증하고 confidence를 상승시키는 모듈
import os

import httpx

from src.extraction.skill_extractor import DemonstratedSkill

# 기술명 → GitHub 리포에서 찾을 키워드 매핑
_SKILL_KEYWORDS: dict[str, list[str]] = {
    "LangChain": ["langchain", "lang-chain"],
    "LangGraph": ["langgraph", "lang-graph"],
    "FastAPI": ["fastapi", "fast-api"],
    "Python": ["python"],
    "PyTorch": ["pytorch", "torch"],
    "Hugging Face Transformers": ["transformers", "huggingface"],
    "Chroma": ["chromadb", "chroma"],
    "Neo4j": ["neo4j"],
    "Docker": ["docker", "dockerfile"],
    "Kubernetes": ["kubernetes", "k8s", "helm"],
    "React": ["react", "reactjs"],
    "AWS": ["aws", "boto3", "awscli", "amazon"],
    "vLLM": ["vllm"],
    "RAGAS": ["ragas"],
    "LoRA": ["lora", "peft"],
    "QLoRA": ["qlora", "bitsandbytes"],
}

_LADDER = ["low", "medium", "high"]


def boost_confidence_from_github(
    skills: list[DemonstratedSkill],
    github_username: str,
) -> tuple[list[DemonstratedSkill], dict[str, str]]:
    """GitHub 리포 메타데이터에서 기술 발견 시 confidence 한 단계 상승.

    Returns:
        updated_skills: 갱신된 DemonstratedSkill 리스트
        changes: {"LangChain": "medium → high"} 형태
    """
    token = os.getenv("GITHUB_TOKEN")
    headers: dict[str, str] = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        resp = httpx.get(
            f"https://api.github.com/users/{github_username}/repos",
            headers=headers,
            params={"per_page": 100, "type": "owner"},
            timeout=10,
        )
        resp.raise_for_status()
        repos: list[dict] = resp.json()
    except Exception as e:
        print(f"[warn] GitHub API 실패 ({github_username}): {e}")
        return skills, {}

    repo_text = " ".join([
        f"{r.get('name', '')} "
        f"{r.get('description') or ''} "
        f"{' '.join(r.get('topics') or [])} "
        f"{r.get('language') or ''}"
        for r in repos
    ]).lower()

    changes: dict[str, str] = {}
    updated: list[DemonstratedSkill] = []

    for skill in skills:
        keywords = _SKILL_KEYWORDS.get(skill.name, [skill.name.lower()])
        if any(kw in repo_text for kw in keywords):
            current_idx = _LADDER.index(skill.confidence)
            new_idx = min(current_idx + 1, 2)
            if new_idx != current_idx:
                new_level = _LADDER[new_idx]
                changes[skill.name] = f"{skill.confidence} → {new_level}"
                updated.append(skill.model_copy(update={
                    "confidence": new_level,
                    "evidence": (
                        f"{skill.evidence} [GitHub 확인: {github_username}]"
                        if skill.evidence
                        else f"GitHub 리포에서 {skill.name} 사용 확인 ({github_username})"
                    ),
                }))
                continue
        updated.append(skill)

    return updated, changes


def parse_github_username(url: str) -> str:
    """https://github.com/username → username."""
    parts = url.rstrip("/").split("/")
    try:
        idx = parts.index("github.com")
        username = parts[idx + 1]
        if not username:
            raise ValueError
        return username
    except (ValueError, IndexError):
        raise ValueError(f"유효하지 않은 GitHub URL: {url}")
