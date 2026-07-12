# GitHub API로 이력서 기술 증거를 검증하고 confidence를 상승시키는 모듈
#
# 이 파일이 하는 일: 두 가지 완전히 다른 기능이 한 파일에 섞여 있다.
# ① boost_confidence_from_github — 사용자명(username) 하나로 그 사람의 "모든 레포 메타데이터"를
#    훑어서 이력서 스킬의 confidence를 올리는, github_eval.py와는 별개의 더 오래된 방식.
#    프로덕션 흐름에서는 아직 안 쓰이지만 tests/unit/test_github_boost.py에 전용 테스트가 있어 보존.
# ② parse_github_repo — GitHub URL 문자열을 파싱하는 순수 유틸 함수.
#    github_eval.py에서 실제로 import돼 쓰인다. (parse_github_username은 미사용 죽은 코드라 제거함)

import logging
import os
import re

import httpx

from src.common.text_match import keywords_for, word_match
from src.extraction.skill_extractor import DemonstratedSkill

# GitHub owner/repo에 허용되는 문자 — API 경로에 삽입되므로 ".."나 "/" 같은 조각을 막는다.
# 점은 repo명에 실제로 쓰이므로(예: my.repo) 허용하되, 영숫자를 최소 하나 요구해
# "." / ".." 처럼 경로 조작에 쓰이는 세그먼트는 거부한다.
_SAFE_SEGMENT = re.compile(r"(?=.*[A-Za-z0-9])[A-Za-z0-9._-]+")
# skill_extractor.py의 pydantic 모델 — 이력서에서 추출된 "확인된 스킬" 하나를 표현하는 그 모델

logger = logging.getLogger("jobgraph.portfolio")
# 다른 파일들과 로깅 방식을 통일 — 이 파일만 print()를 쓰던 걸 logger로 교체

# 기술명 → GitHub 리포에서 찾을 키워드 매핑 (수동 튜닝된 추가 키워드)
# normalizer.py의 SKILL_ALIASES/keywords_for()에는 없는, GitHub 검색에 특화된 변형 표기
# (dockerfile, k8s, boto3, peft 등)만 여기 남겨두고, 아래 boost_confidence_from_github()에서
# keywords_for()의 정규화 기반 별칭과 합집합으로 합쳐서 쓴다 — 두 시스템 중 하나를 버리는 대신
# "정규화 사전(정답 표기 관리) + 이 사전(검색 특화 변형)"으로 역할을 나눠 통합
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
# confidence 등급의 순서를 리스트로 표현 — "한 단계 올린다"는 걸 인덱스 +1로 계산하기 위한 사다리


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
        # github_eval.py는 특정 레포 하나(owner/repo)를 깊게 분석하는 반면,
        # 이 함수는 사용자명 하나로 그 사람의 "레포 목록 전체"(최대 100개)를 얕게 훑음 —
        # 코드 내용은 안 읽고, 레포 이름·설명·토픽·주 언어 같은 메타데이터만 봄
        resp.raise_for_status()
        repos: list[dict] = resp.json()
    except Exception as e:
        logger.warning(f"[github_connector] GitHub API 실패 ({github_username}): {e}")
        return skills, {}

    repo_text = " ".join([
        f"{r.get('name', '')} "
        f"{r.get('description') or ''} "
        f"{' '.join(r.get('topics') or [])} "
        f"{r.get('language') or ''}"
        for r in repos
    ]).lower()
    # 모든 레포의 이름+설명+토픽+주 언어를 전부 하나의 거대한 텍스트로 이어붙임.
    # 이렇게 하면 "어느 레포에서 발견됐는지"는 알 수 없고, "이 사람의 레포 전체에 이 단어가 있는가"만 판단 가능
    # (github_eval.py가 레포별로 세밀하게 분석하는 것과 달리, 이 방식은 훨씬 거칠고 단순함)

    changes: dict[str, str] = {}
    updated: list[DemonstratedSkill] = []

    for skill in skills:
        keywords = set(_SKILL_KEYWORDS.get(skill.name, ())) | set(keywords_for(skill.name))
        # 수동 튜닝 키워드(dockerfile, k8s, boto3 등)와 normalizer.py 기반 정규화 별칭(react.js,
        # 리액트 등)을 합집합으로 합침 — 어느 한쪽에만 있던 키워드도 안 놓치게 됨
        # 단어경계 매칭 — 'python'이 'micropython'에, 'aws'가 'draws'에 오탐되지 않게
        if any(word_match(kw, repo_text) for kw in keywords):
            # text_match.py에서 본 그 함수 — 여기서 실제로 재사용되는 걸 확인
            current_idx = _LADDER.index(skill.confidence)
            new_idx = min(current_idx + 1, 2)
            # min(현재+1, 2) → 최대 인덱스 2("high")를 넘지 않게 상한을 둠. 이미 high면 +1 해도 2로 고정
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
                # model_copy(update={...}) → pydantic 모델의 메서드. 원본 객체를 직접 수정하지 않고,
                # 지정한 필드만 바꾼 "새로운 복사본"을 만들어 반환 (원본 skill 객체는 그대로 보존됨)
                continue
                # 갱신된 버전을 이미 updated에 추가했으니, 아래의 "원본 그대로 추가" 줄은 건너뜀
        updated.append(skill)
        # 매칭 안 됐거나 이미 이미 최고 등급(high)이라 올릴 데가 없으면, 원본 스킬을 변경 없이 그대로 추가

    return updated, changes


def parse_github_repo(url: str) -> tuple[str, str | None]:
    """github.com/owner/repo[/blob/...] → (owner, repo). 레포 조각 없으면 (owner, None)."""
    # 이 함수가 github_eval.py의 _eval_one()에서 실제로 호출되는 그 함수
    parts = url.rstrip("/").split("/")
    try:
        idx = parts.index("github.com")
        owner = parts[idx + 1]
        if not owner:
            raise ValueError
    except (ValueError, IndexError):
        raise ValueError(f"유효하지 않은 GitHub URL: {url}")
    repo = parts[idx + 2] if len(parts) > idx + 2 and parts[idx + 2] else None

    # 이 값들은 https://api.github.com/repos/{owner}/{repo} 경로에 그대로 삽입되므로,
    # ".." 같은 조각이 들어가면 의도치 않은 GitHub API 엔드포인트를 호출할 수 있다.
    # GitHub이 실제로 허용하는 문자(영숫자·하이픈·언더스코어·점)만 통과시킨다.
    if not _SAFE_SEGMENT.fullmatch(owner):
        raise ValueError(f"유효하지 않은 GitHub owner: {owner!r}")
    if repo is not None and not _SAFE_SEGMENT.fullmatch(repo):
        raise ValueError(f"유효하지 않은 GitHub repo: {repo!r}")
    # owner 다음 조각까지 있으면(len 체크) 그리고 그 조각이 빈 문자열이 아니면 repo로 인정,
    # 아니면 None — 즉 "github.com/owner"까지만 준 경우와 "github.com/owner/repo"를 구분해서 처리
    return owner, repo
    # username 파싱 함수와 달리 여기서는 repo가 없어도 에러를 안 내고 None으로 반환 —
    # 호출부(github_eval.py)가 "레포 미지정"을 별도로 판단해서 처리할 수 있게 유연하게 설계됨
