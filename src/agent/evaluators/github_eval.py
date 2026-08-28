# 지정 GitHub 레포에서 대상 직군의 스킬을 코드 근거로 검증하는 평가자 (코드 modality)
#
# 이 파일이 하는 일: 4개 병렬 평가자 중 가장 복잡한 것. 사용자가 준 GitHub URL에서
# ① 언어 통계·README·의존성 파일로 빠르게 스킬을 감지(키워드 매칭)하고
# ② 실제 소스 코드 일부를 읽어 LLM(gpt-4o)에게 "이 스킬을 어느 수준으로 쓰고 있는지" 평가시킨다.
# resume_eval이 "말로 주장한 스킬"이라면, github_eval은 "코드로 실제로 확인된 스킬"이라서
# consensus 단계에서 이력서 주장을 검증하는 가장 강한 근거로 쓰인다.

from __future__ import annotations

import concurrent.futures  # 여러 파일을 GitHub API에서 동시에 읽기 위한 스레드풀
import json
import logging
import os
import re
from typing import TYPE_CHECKING, Callable

import httpx

from src.portfolio.github_connector import parse_github_repo  # URL → (owner, repo) 파싱 (아직 안 본 파일)
from src.extraction.normalizer import normalize_skill
# 텍스트 매칭 유틸은 공용 모듈에서 — tools/deploy_eval/ragas_eval도 여기서 가져다 쓴다
from src.common.text_match import word_match as _word_match, keywords_for as _keywords_for
# 아직 안 본 src/common/text_match.py — 여러 파일이 공유하는 "스킬명이 텍스트에 등장하는지" 판별 로직으로 추정

if TYPE_CHECKING:
    from src.agent.state import AppState
    from src.storage.neo4j_client import Neo4jClient

logger = logging.getLogger("jobgraph.agent")


def _get_json(url: str, headers: dict, timeout: float = 10):
    """GitHub API를 호출하고 응답을 JSON으로 반환한다. 4xx/5xx는 예외로 승격.

    GitHub은 rate limit(403)·not found(404)에도 유효한 JSON 본문
    ({"message": "API rate limit exceeded...", ...})을 반환한다. status_code를
    확인하지 않고 .json()만 호출하면 예외가 안 나서 이 에러 본문을 실제 데이터인 양
    파싱해버린다(예: languages 대신 {"message":...}.keys()로 lang_text를 만듦) —
    호출부의 except가 못 잡고 조용히 빈 결과로 이어지는 원인이었다.
    """
    # 이 함수가 왜 따로 있는가: httpx.get()만 쓰면 GitHub이 에러 메시지를 담은 JSON을
    # 200 아닌 상태코드로 주더라도 .json() 자체는 성공해버림 — 그러면 코드가 "정상 응답"으로
    # 착각하고 에러 메시지 dict를 실제 데이터처럼 파싱하려다 이상한 결과를 냄.
    # raise_for_status()로 상태코드를 먼저 검사해서 이 함정을 원천 차단
    resp = httpx.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


# package.json 패키지명 → 표준 스킬명 (생태계 매핑)
# 예: "drizzle-orm"이라는 패키지 이름 자체는 스킬이 아니지만, 그걸 쓴다는 건
# "PostgreSQL을 쓴다"는 강력한 근거이므로, 패키지명을 실제 스킬명으로 치환하는 사전
_PKG_TO_SKILL: dict[str, str] = {
    # Database ORMs / drivers → underlying DB
    "drizzle-orm": "PostgreSQL", "drizzle-kit": "PostgreSQL",
    "pg": "PostgreSQL", "@neondatabase/serverless": "PostgreSQL",
    "neon": "PostgreSQL", "postgres": "PostgreSQL",
    "@prisma/client": "Prisma", "prisma": "Prisma",
    "mongoose": "MongoDB", "mongodb": "MongoDB",
    "mysql2": "MySQL", "mysql": "MySQL",
    "@elastic/elasticsearch": "Elasticsearch",
    "redis": "Redis", "ioredis": "Redis",
    "bull": "Redis", "bullmq": "Redis",
    # Auth
    "next-auth": "NextAuth.js", "@auth/core": "NextAuth.js",
    "@auth/nextjs": "NextAuth.js", "@auth/drizzle-adapter": "NextAuth.js",
    # State / data fetching
    "@tanstack/react-query": "React Query", "react-query": "React Query",
    "zustand": "Zustand", "jotai": "Jotai", "recoil": "Recoil",
    # APIs / transport
    "graphql": "GraphQL", "@apollo/client": "GraphQL",
    "apollo-server": "GraphQL", "@apollo/server": "GraphQL",
    "socket.io": "WebSocket", "ws": "WebSocket",
    # Infra / CI
    "stripe": "Stripe",
    # Testing
    "vitest": "Vitest", "jest": "Jest",
    "@playwright/test": "Playwright", "playwright": "Playwright",
    "cypress": "Cypress",
    # AI
    "openai": "OpenAI API", "anthropic": "Claude API",
    "langchain": "LangChain", "@langchain/core": "LangChain",
    "langgraph": "LangGraph", "@langchain/langgraph": "LangGraph",
}

_PY_PKG_TO_SKILL: dict[str, str] = {
    # Web
    "fastapi": "FastAPI",
    "django": "Django",
    "flask": "Flask",
    # Database drivers / ORMs
    "psycopg": "PostgreSQL",
    "psycopg2": "PostgreSQL",
    "asyncpg": "PostgreSQL",
    "pg8000": "PostgreSQL",
    "sqlalchemy": "SQL",
    "pymongo": "MongoDB",
    "redis": "Redis",
    "elasticsearch": "Elasticsearch",
    # AI / ML
    "openai": "OpenAI API",
    "anthropic": "Claude API",
    "langchain": "LangChain",
    "langchain-core": "LangChain",
    "langgraph": "LangGraph",
    "torch": "PyTorch",
    "pytorch": "PyTorch",
    "transformers": "Hugging Face Transformers",
    "sentence-transformers": "Hugging Face Transformers",
    "scikit-learn": "Scikit-learn",
    "sklearn": "Scikit-learn",
    "pandas": "Pandas",
    "polars": "Polars",
    "numpy": "NumPy",
    "ragas": "RAGAS",
    "chromadb": "Chroma",
    "qdrant-client": "Qdrant",
    "pinecone-client": "Pinecone",
}

# 본문을 읽어 패키지명을 매칭할 의존성 파일 (소문자)
_TEXT_MANIFESTS = {
    "requirements.txt", "pyproject.toml", "pipfile", "setup.py",
    "package.json", "environment.yml",
}
# 존재만으로 의미가 있는 설정 파일 (파일명 자체를 신호로 사용)
_PRESENCE_MANIFESTS = {"dockerfile", "docker-compose.yml", "go.mod", "cargo.toml"}
# 이 둘의 차이: _TEXT_MANIFESTS는 "안의 내용까지 읽어서" 패키지명을 찾고,
# _PRESENCE_MANIFESTS는 "파일이 있다는 사실 자체"가 이미 신호 (예: Dockerfile이 있으면 = Docker 사용)
_ALL_MANIFESTS = _TEXT_MANIFESTS | _PRESENCE_MANIFESTS
# set의 | 연산자 = 합집합. 두 집합을 합쳐 "매니페스트로 취급할 파일명 전체" 집합을 만듦

# 소스 파일 읽기 설정
_SKIP_DIRS = {
    "node_modules", ".git", "dist", "build", "__pycache__",
    ".next", "venv", "env", ".venv", "vendor", "coverage", ".pytest_cache",
}
# 라이브러리·빌드 산출물 폴더는 "이 사람이 직접 짠 코드"가 아니므로 분석 대상에서 제외
_SKIP_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".woff", ".ttf",
    ".pyc", ".pdf", ".zip", ".map",
}
_SKIP_INFIXES = {".min.js", ".min.css", ".lock"}
# 압축된(minified) 파일이나 lock 파일은 사람이 읽을 수 있는 소스가 아니라서 제외
_SKIP_FILENAMES = {"__init__.py", "__init__.ts"}
_SOURCE_EXTENSIONS = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".java", ".rs",
    ".vue", ".yaml", ".yml", ".toml",
}
_MAX_FILES = 25       # LLM에게 보여줄 파일 개수 상한 — 토큰 비용·응답 시간 통제
_MAX_FILE_CHARS = 8_000   # 파일당 최대 문자 수 — 파일 하나가 너무 크면 앞부분만 자름
_MAX_CODE_CHARS = 40_000  # LLM에 넘길 총 코드 최대 문자 수 — 전체 예산
_MAX_MANIFEST_FILES = 40  # 재귀 manifest 읽기 상한 — 대형 모노레포 API 비용 통제

# 골격 파일 — 프로젝트 구조를 가장 잘 드러내는 파일을 25개 예산에서 우선 선택
_MANIFEST_FILES = {
    "requirements.txt", "package.json", "pyproject.toml", "go.mod", "cargo.toml",
    "pom.xml", "build.gradle", "gemfile", "composer.json", "setup.py", "pipfile",
}
_ENTRY_STEMS = {"main", "app", "index", "supervisor", "server", "__main__", "cli", "run"}
# 파일명 자체(확장자 뺀 부분)가 이 목록에 있으면 "이 프로젝트의 진입점"일 확률이 높다고 봄
# (이 프로젝트 자체의 src/ingestion/pipeline.py도 "run_pipeline"류 함수를 가진 진입점이었던 걸 떠올리면 이해 쉬움)


def _skills_from_pkg_json(
    pkg_json_text: str,
    vocab: list[str],
    source_path: str = "package.json",
) -> list[dict]:
    """package.json 의존성을 파싱해 _PKG_TO_SKILL로 스킬을 매핑한다."""
    if not pkg_json_text:
        return []
    try:
        pkg = json.loads(pkg_json_text)
    except Exception:
        return []
    all_deps: set[str] = set()
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        all_deps.update(pkg.get(key, {}).keys())
        # package.json의 세 가지 의존성 그룹(실제 사용/개발용/피어)을 전부 하나의 집합으로 모음

    vocab_set = {v.lower(): v for v in vocab}
    # vocab(이 직군에서 유효한 스킬 목록)을 소문자 키로 하는 dict로 변환 — 대소문자 무시 조회용
    results: list[dict] = []
    seen: set[str] = set()
    for pkg_name in all_deps:
        skill_raw = _PKG_TO_SKILL.get(pkg_name.lower())
        if not skill_raw:
            continue   # 매핑 사전에 없는 패키지는 스킬로 취급 안 함
        skill = vocab_set.get(skill_raw.lower(), skill_raw)
        # vocab에 있는 정확한 표기를 쓰되, 없으면 매핑 사전의 표기를 그대로 씀
        if skill.lower() not in vocab_set or skill in seen:
            continue
            # 이 직군의 vocab에 없는 스킬(예: 이 직군과 무관한 기술)이거나 이미 처리했으면 건너뜀
        seen.add(skill)
        results.append({
            "skill": skill,
            "evidence": f"{source_path} 의존성 {pkg_name} → {skill} 확인",
            "source": "github",
            "strength": "code",   # 의존성 선언 = 코드 근거
            "level_hint": "실무",
        })
    return results


def _skills_from_python_manifest(
    manifest_text: str,
    vocab: list[str],
    source_path: str,
) -> list[dict]:
    """Python 의존성 파일(requirements/pyproject 등)에서 패키지명을 스킬로 매핑한다."""
    if not manifest_text:
        return []
    vocab_set = {v.lower(): v for v in vocab}
    results: list[dict] = []
    seen: set[str] = set()
    text = manifest_text.lower().replace("_", "-")
    for pkg_name, skill_raw in _PY_PKG_TO_SKILL.items():
        if not _word_match(pkg_name.lower(), text):
            continue
        skill = vocab_set.get(skill_raw.lower(), skill_raw)
        if skill.lower() not in vocab_set or skill in seen:
            continue
        seen.add(skill)
        results.append({
            "skill": skill,
            "evidence": f"{source_path} 의존성 {pkg_name} → {skill} 확인",
            "source": "github",
            "strength": "code",
            "level_hint": "실무",
        })
    return results


def _manifest_match(keyword: str, text: str) -> bool:
    """의존성/설정 소스 매칭."""
    if _word_match(keyword, text):
        return True
    for manifest in _PRESENCE_MANIFESTS:
        first_token = re.split(r"[.\-]", manifest, maxsplit=1)[0]
        # "docker-compose.yml" → "docker"만 추출 (첫 번째 . 또는 - 앞부분)
        if (first_token == keyword or manifest == keyword + "file") and _word_match(manifest, text):
            # keyword가 "docker"인데 manifest 목록에 "dockerfile"이 있으면(keyword+"file"과 일치) 매칭 인정
            return True
    return False


def _skills_from_sources(
    owner: str, repo: str, lang_text: str, readme_text: str, manifest_text: str,
    vocab: list[str],
) -> list[dict[str, str]]:
    """대상 직군 스킬(vocab)을 주 언어·README·의존성파일에서 찾아 증거로 만든다."""
    # 이게 LLM 호출 없이 "빠르게" 스킬을 감지하는 1차 패스 — 키워드 매칭만으로 동작
    lang_l, readme_l, manifest_l = lang_text.lower(), readme_text.lower(), manifest_text.lower()
    skills: list[dict[str, str]] = []
    for skill_name in vocab:
        kws = _keywords_for(skill_name)   # 스킬명에서 검색용 키워드 변형들을 얻음 (예: "PostgreSQL" → ["postgresql","postgres"])
        in_lang = any(_word_match(kw, lang_l) for kw in kws)
        in_readme = any(_word_match(kw, readme_l) for kw in kws)
        in_manifest = any(_manifest_match(kw, manifest_l) for kw in kws)
        if not (in_lang or in_readme or in_manifest):
            continue   # 어디에도 없으면 이 스킬은 감지 안 됨 — 다음 스킬로
        where: list[str] = []
        if in_manifest:
            where.append("의존성/설정파일")
        if in_lang:
            where.append("주 언어")
        if in_readme:
            where.append("README")
        # 의존성 파일·주 언어(GitHub 언어 통계=실제 코드)는 코드 근거,
        # README에만 있으면 단순 언급 — 이 구분이 consensus의 Verified 판정을 좌우한다.
        strength = "code" if (in_manifest or in_lang) else "mention"
        # 이 strength 값이 나중에 consensus.py가 "이건 진짜 코드로 확인된 건지, 그냥 글로 언급만 됐는지"를
        # 구분해서 신뢰도를 다르게 매기는 근거가 됨 — README에 "Docker 배웠음"이라고만 써도 실제 코드는
        # 없을 수 있으므로, 이 둘을 같은 무게로 취급하면 안 된다는 판단
        skills.append({
            "skill": skill_name,
            "evidence": f"{owner}/{repo} {'·'.join(where)}에서 {skill_name} 확인",
            "source": "github",
            "strength": strength,
            "level_hint": "실무",
        })
    return skills


def _should_include(path: str) -> bool:
    """파일 경로가 소스 분석 대상인지 판단."""
    parts = path.split("/")
    for part in parts[:-1]:   # 마지막(파일명)을 뺀 폴더 경로들만 검사
        if part in _SKIP_DIRS:
            return False
    filename = parts[-1]
    if filename in _SKIP_FILENAMES:
        return False
    for infix in _SKIP_INFIXES:
        if infix in filename:
            return False
    for suffix in _SKIP_SUFFIXES:
        if filename.endswith(suffix):
            return False
    ext = "." + filename.rsplit(".", 1)[-1] if "." in filename else ""
    return ext in _SOURCE_EXTENSIONS
    # 위 모든 제외 조건을 통과하고, 확장자가 "우리가 분석할 소스 언어" 목록에 있어야 최종 통과


def _select_files_llm(openai, owner: str, repo: str,
                      candidates: list[str], fallback: list[str]) -> list[str]:
    """파일 경로 트리를 gpt-4o-mini에 주고 읽을 핵심 파일을 직접 고르게 한다(B, pass1).

    파일 '선택'은 경로 패턴 인식 수준이라 mini로 충분(내용 분석은 pass2의 gpt-4o가 함).
    실패·빈 결과·환각 경로면 휴리스틱 fallback을 반환해 항상 안전하게 동작한다.
    """
    # 이 파일에는 LLM 호출이 두 단계(pass)로 나뉘어 있음:
    #   pass1(여기): "이 파일 트리에서 뭘 읽어야 할지" 선택만 — 저렴한 gpt-4o-mini
    #   pass2(_assess_project_and_skills): 실제 코드 내용을 분석 — 더 비싼 gpt-4o
    # 파일 선택은 상대적으로 쉬운 판단(경로 이름만 보고 고름)이라 굳이 비싼 모델을 안 씀 — 비용 최적화
    if not openai or not candidates:
        return fallback
    tree_text = "\n".join(sorted(candidates))
    prompt = (
        f"저장소 {owner}/{repo}의 소스 파일 경로 목록입니다:\n{tree_text}\n\n"
        f"이 프로젝트를 이해하려면 어떤 파일을 읽어야 하는지 최대 {_MAX_FILES}개 고르세요. "
        "엔트리포인트(main·app·supervisor 등), 핵심 로직, 설정/매니페스트를 우선하고, "
        "테스트·마이그레이션·자동생성 파일은 후순위로. "
        'JSON 객체로만 반환하세요. 예: {"files": ["src/main.py", "requirements.txt"]}'
    )
    try:
        resp = openai.chat.completions.create(
            model="gpt-4o-mini", temperature=0,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt}],
        )
        raw = (resp.choices[0].message.content or "").strip()
        picked = json.loads(raw).get("files", [])
        cand_set = set(candidates)
        chosen = [p for p in picked if isinstance(p, str) and p in cand_set][:_MAX_FILES]
        # LLM이 지어낸(실제 후보에 없는) 파일 경로는 여기서 걸러짐 — cand_set에 있는 것만 인정
        return chosen or fallback
        # LLM이 골라준 게 다 걸러져서 빈 리스트가 되면(chosen이 falsy) 안전하게 휴리스틱으로 되돌아감
    except Exception as e:
        logger.warning(f"[github_eval] LLM 파일 선택 실패, 휴리스틱 fallback: {e}")
        return fallback


def _read_source_tree(owner: str, repo: str, headers: dict, openai=None) -> tuple[dict[str, str], set[str]]:
    """레포 전체 파일 트리에서 핵심 소스 파일을 선택해 병렬로 읽는다.

    반환: (읽은 파일 내용 dict, 레포 전체 파일 경로 집합)
    전체 경로 집합은 relevant_files 환각 검증에 사용한다.
    """
    base = f"https://api.github.com/repos/{owner}/{repo}"

    # 기본 브랜치 확인
    try:
        default_branch = _get_json(base, headers).get("default_branch", "main")
    except Exception as e:
        logger.warning(f"[github_eval] 기본 브랜치 조회 실패, main으로 진행: {e}")
        default_branch = "main"

    # 재귀 파일 트리
    try:
        tree = _get_json(f"{base}/git/trees/{default_branch}?recursive=1", headers, timeout=15).get("tree", [])
        # ?recursive=1 → 하위 폴더까지 전부 재귀적으로 한 번에 받아옴 (폴더마다 API를 따로 안 불러도 됨)
    except Exception as e:
        logger.warning(f"[github_eval] 파일 트리 조회 실패: {e}")
        return {}, set()

    # 레포 전체 파일 경로 집합 (환각 검증용) + 파일 크기 (큰 파일=핵심 로직 우선용)
    all_paths: set[str] = {it["path"] for it in tree if it.get("type") == "blob"}
    # type == "blob" → Git 용어로 "파일"을 뜻함 (폴더는 "tree" 타입) — 파일만 골라냄
    sizes: dict[str, int] = {it["path"]: it.get("size", 0) for it in tree if it.get("type") == "blob"}

    # 소스 파일 필터링
    candidates = [p for p in all_paths if _should_include(p)]

    # 골격 우선순위(낮을수록 우선): 매니페스트 > 엔트리포인트 > 핵심경로(얕은 깊이) > 기타
    def _priority(path: str) -> int:
        name = path.rsplit("/", 1)[-1].lower()
        if name in _MANIFEST_FILES:
            return 0
        stem = name.rsplit(".", 1)[0] if "." in name else name
        if stem in _ENTRY_STEMS:
            return 1
        base = 2 if path.startswith(("src/", "app/", "lib/", "api/", "pkg/")) else 4
        return base + path.count("/")        # 얕은 파일 우선
        # path.count("/") → 경로 깊이. 폴더가 깊을수록(하위 세부 구현일수록) 우선순위를 낮춤

    # 매니페스트·엔트리포인트는 무조건 포함. 나머지는 디렉토리별 라운드로빈으로
    # 한 디렉토리가 25개를 독식하지 않게 골고루 — 프로젝트 골격을 넓게 보여준다.
    candidates.sort(key=lambda p: (_priority(p), -sizes.get(p, 0)))
    # 정렬 기준 튜플: (우선순위 숫자, -파일크기) → 우선순위가 같으면 파일이 큰 것부터
    # (-size로 부호를 뒤집어서 "오름차순 정렬"인 sort가 실질적으로 "큰 것 먼저"가 되게 함)
    must = [p for p in candidates if _priority(p) <= 1][:_MAX_FILES]
    # 매니페스트·엔트리포인트(우선순위 0,1)는 무조건 포함
    rest = [p for p in candidates if _priority(p) > 1]
    by_dir: dict[str, list[str]] = {}
    for p in rest:
        by_dir.setdefault("/".join(p.split("/")[:-1]), []).append(p)
        # 파일을 자기가 속한 디렉토리별로 묶음 (예: "src/agent"라는 키 아래 그 폴더의 파일들)
    heuristic_selected = list(must)
    queues = [q for q in by_dir.values()]
    while len(heuristic_selected) < _MAX_FILES and queues:
        queues = [q for q in queues if q]   # 이미 다 뽑힌(빈) 큐는 제거
        for q in queues:
            if len(heuristic_selected) >= _MAX_FILES:
                break
            heuristic_selected.append(q.pop(0))
            # 각 디렉토리 큐에서 한 개씩 돌아가며 뽑음(라운드로빈) — 특정 폴더 파일이
            # 25개 예산을 독점해서 "이 프로젝트는 이 폴더밖에 없나?" 하는 왜곡된 그림을 막음

    # B(pass1): LLM이 트리를 보고 핵심 파일을 직접 선택 — 실패 시 휴리스틱 fallback
    selected = _select_files_llm(openai, owner, repo, candidates, heuristic_selected)

    # 병렬 파일 읽기
    raw_headers = {**headers, "Accept": "application/vnd.github.raw"}
    # {**headers, "키": 값} → 기존 headers dict를 복사하면서 Accept 값만 덮어씀 (원본 headers는 안 바뀜)
    # "application/vnd.github.raw" → GitHub API에게 "JSON 메타데이터 말고 파일 원문 그대로 달라"고 요청하는 헤더

    def _fetch(path: str) -> tuple[str, str | None]:
        try:
            resp = httpx.get(f"{base}/contents/{path}", headers=raw_headers, timeout=10)
            if resp.status_code == 200:
                return path, resp.text[:_MAX_FILE_CHARS]
        except Exception:
            pass
        return path, None
        # 실패하면 (경로, None) 반환 — 이 파일 하나 실패해도 나머지 파일 읽기는 계속됨

    contents: dict[str, str] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        for path, text in ex.map(_fetch, selected):
            # ex.map(함수, 리스트) → 리스트의 각 항목에 함수를 적용하되, 최대 8개를 동시에(병렬로) 실행
            # 파일 25개를 순서대로 하나씩 받으면 느리지만, 8개씩 동시에 요청하면 훨씬 빠름
            if text:
                contents[path] = text

    return contents, all_paths


def _manifest_name(path: str) -> str:
    return path.rsplit("/", 1)[-1].lower()


def _manifest_priority(path: str) -> tuple[int, int, str]:
    depth = path.count("/")
    name = _manifest_name(path)
    if depth == 0:
        return (0, depth, path)
    if name == "package.json":
        return (1, depth, path)
    if name in _TEXT_MANIFESTS:
        return (2, depth, path)
    return (3, depth, path)


def _read_repo_manifests(
    owner: str,
    repo: str,
    headers: dict,
    all_paths: set[str],
) -> tuple[str, list[tuple[str, str]], list[tuple[str, str]]]:
    """레포 전체 경로에서 의존성/설정 manifest를 재귀적으로 읽는다."""
    if not all_paths:
        return "", [], []
    manifest_paths = [
        p for p in all_paths
        if _manifest_name(p) in _ALL_MANIFESTS
    ]
    manifest_paths = sorted(manifest_paths, key=_manifest_priority)[:_MAX_MANIFEST_FILES]
    if not manifest_paths:
        return "", []

    base = f"https://api.github.com/repos/{owner}/{repo}"
    raw_headers = {**headers, "Accept": "application/vnd.github.raw"}
    manifest_parts: list[str] = []
    package_jsons: list[tuple[str, str]] = []
    python_manifests: list[tuple[str, str]] = []

    def _fetch(path: str) -> tuple[str, str | None]:
        name = _manifest_name(path)
        if name not in _TEXT_MANIFESTS:
            return path, None
        try:
            resp = httpx.get(f"{base}/contents/{path}", headers=raw_headers, timeout=10)
            if resp.status_code == 200:
                return path, resp.text[:_MAX_FILE_CHARS]
        except Exception as e:
            logger.warning(f"[github_eval] manifest 읽기 실패 ({path}): {e}")
        return path, None

    fetched: dict[str, str | None] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        for path, text in ex.map(_fetch, manifest_paths):
            fetched[path] = text

    for path in manifest_paths:
        name = _manifest_name(path)
        manifest_parts.append(path)  # 파일 존재 자체가 Dockerfile/go.mod 등 신호가 될 수 있다.
        text = fetched.get(path)
        if text:
            manifest_parts.append(text)
            if name == "package.json":
                package_jsons.append((path, text))
            elif name in _TEXT_MANIFESTS:
                python_manifests.append((path, text))

    return " ".join(manifest_parts), package_jsons, python_manifests


_SKILL_EXTENSION_HINTS: dict[str, set[str]] = {
    "python": {".py"},
    "javascript": {".js", ".jsx"},
    "typescript": {".ts", ".tsx"},
    "go": {".go"},
    "java": {".java"},
    "rust": {".rs"},
}


def _path_extension(path: str) -> str:
    filename = path.rsplit("/", 1)[-1]
    return "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _file_supports_skill(skill: str, path: str, text: str | None) -> bool:
    """파일 내용 또는 언어 확장자가 해당 스킬을 실제로 뒷받침하는지 확인한다."""
    skill_norm = normalize_skill(skill).lower()
    if _path_extension(path) in _SKILL_EXTENSION_HINTS.get(skill_norm, set()):
        return True
    haystack = (text or "").lower()
    if not haystack:
        return False
    return any(_word_match(kw, haystack) for kw in _keywords_for(skill))


def _validate_project_context(
    ctx: dict,
    all_paths: set[str],
    file_contents: dict[str, str] | None = None,
) -> dict:
    """relevant_files를 실제 레포 파일 목록·파일 내용과 대조해 환각 근거를 제거한다."""
    # LLM(pass2)이 "이 스킬은 src/foo.py에서 확인됨"이라고 답했는데, 실제로 src/foo.py가 레포에
    # 없으면(지어낸 경로) 그건 환각 — 이 함수가 그걸 코드로 걸러낸다 (LLM을 다시 안 부르고 그냥 대조)
    if not ctx or not all_paths:
        return ctx
    file_contents = file_contents or {}
    cleaned = []
    for sa in ctx.get("skill_assessments", []):
        files = sa.get("relevant_files", []) or []
        existing = [f for f in files if f in all_paths]
        ghost = [f for f in files if f not in all_paths]
        if ghost:
            logger.warning(f"[github_eval] 환각 파일 제거 ({sa.get('skill')}): {ghost}")
        real = [
            f for f in existing
            if not file_contents or _file_supports_skill(sa.get("skill", ""), f, file_contents.get(f))
        ]
        unsupported = [f for f in existing if f not in real]
        if unsupported:
            logger.warning(f"[github_eval] 내용 불일치 파일 제거 ({sa.get('skill')}): {unsupported}")
        if files and not real:
            logger.warning(f"[github_eval] 근거 파일 없는 skill_assessment 제거: {sa.get('skill')}")
            continue
        cleaned.append({**sa, "relevant_files": real})
        # {**sa, "relevant_files": real} → sa 딕셔너리를 복사하면서 relevant_files 키만 검증된 값으로 교체

    return {**ctx, "skill_assessments": cleaned}


def _code_detected_skills(skills: list[dict]) -> list[str]:
    """README 언급은 제외하고, 코드·의존성·언어로 감지된 스킬만 LLM 강제 포함 힌트로 사용한다."""
    return [
        s["skill"] for s in skills
        if isinstance(s, dict) and s.get("skill") and s.get("strength") == "code"
    ]


def _readme_summary(readme_text: str, limit: int = 420) -> str:
    """README에서 제목/배지보다 설명 문단을 우선 뽑아 프로젝트 이해 근거로 쓴다."""
    lines = []
    for raw in (readme_text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith(("---", "title:", "emoji:", "color", "sdk:", "app_port:", "pinned:")):
            continue
        if line.startswith(("#", "!", "[!", "<")):
            continue
        line = line.lstrip("> ").strip()
        lower = line.lower().strip("* ")
        if "http" in lower and lower.startswith(("live", "backend", "frontend", "demo", "deploy", "deployment")):
            continue
        line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)
        line = re.sub(r"(?:🔗\s*)?라이브\s*데모\s*:\s*\S*(?:\s*·\s*관측\s*:\s*\S+)?", "", line)
        line = re.sub(r"https?://\S+", "", line)
        line = re.sub(r"\s*·\s*(?:관측|observe)\s*:\s*\S+", "", line, flags=re.IGNORECASE)
        line = re.sub(r"[*_`]+", "", line).strip()
        if not line or re.fullmatch(r"[-| :]+", line):
            continue
        lines.append(line)
        if len(" ".join(lines)) >= limit:
            break
    return " ".join(lines)[:limit].strip()


def _fallback_project_context(
    owner: str,
    repo: str,
    languages: dict,
    skills: list[dict],
    readme_text: str,
) -> dict:
    """심층 LLM 분석이 실패해도 1차 GitHub 감지 결과로 최소 코칭 컨텍스트를 만든다."""
    lang_names = list(languages.keys()) if isinstance(languages, dict) else []
    readme_line = _readme_summary(readme_text, limit=240)
    summary_parts = []
    if lang_names:
        summary_parts.append(f"주요 언어는 {', '.join(lang_names[:4])}입니다.")
    if readme_line:
        summary_parts.append(f"README 기준 프로젝트 설명: {readme_line}")

    assessments = []
    for item in skills:
        if not isinstance(item, dict) or not item.get("skill"):
            continue
        skill = normalize_skill(item["skill"])
        strength = item.get("strength")
        current_usage = "기본 사용" if strength == "code" else "언급 확인"
        assessments.append({
            "skill": skill,
            "current_usage": current_usage,
            "used_patterns": [item.get("evidence", "")],
            "missing_patterns": [],
            "how_to_add": "",
            "relevant_files": [],
        })
    if not summary_parts and not assessments:
        return {}
    return {
        "repo": f"{owner}/{repo}",
        "project_type": "GitHub 분석 기반 프로젝트",
        "readme_summary": readme_line,
        "structure_summary": " ".join(summary_parts) or f"{owner}/{repo}에서 감지된 기술 스택 기반 프로젝트입니다.",
        "skill_assessments": assessments[:12],
    }


def _assess_project_and_skills(
    openai,
    owner: str,
    repo: str,
    file_contents: dict[str, str],
    vocab: list[str],
    readme: str,
    detected_skills: list[str] | None = None,
    all_paths: set[str] | None = None,
    skill_neighbors: dict[str, list[str]] | None = None,
) -> dict:
    """소스 코드를 읽고 프로젝트 이해 + 직군 스킬별 현황 + 코칭 컨텍스트를 산출한다.

    반환 형식:
    {
      "repo": "owner/repo",
      "project_type": "React SPA / FastAPI 백엔드 / ...",
      "structure_summary": "...",
      "skill_assessments": [
        {
          "skill": "TypeScript",
          "current_usage": "없음 | 기본 사용 | 중급 패턴 | 고급 패턴",
          "fit_assessment": "이 프로젝트에 이 스킬이 왜 필요한지",
          "how_to_add": "이 프로젝트 구조에서 구체적으로 어떻게 추가/보강하면 되는지",
          "relevant_files": ["src/App.js"]
        }
      ]
    }
    """
    # 이게 pass2 — 실제 코드 내용을 gpt-4o(더 비싼 모델)에게 보여주고 깊이 있는 평가를 시킴
    if not openai or not file_contents:
        return {}

    code_block = "\n\n".join(
        f"### {path}\n{content}" for path, content in file_contents.items()
    )[:_MAX_CODE_CHARS]
    # 여러 파일의 (경로, 내용)을 "### 경로\n내용" 형태로 이어붙여 하나의 큰 텍스트로 만듦.
    # 마지막에 [:_MAX_CODE_CHARS]로 총량을 다시 한번 강제 제한 (파일당 상한을 지켜도 전체 합은 넘을 수 있어서)

    valid_paths = sorted(file_contents.keys())
    detected_hint = (
        f"\n이미 확인된 스킬 (반드시 포함): {', '.join(detected_skills)}"
        if detected_skills else ""
    )
    # pass1 이전에 이미 키워드 매칭(_skills_from_sources)으로 찾은 스킬이 있으면,
    # LLM에게 "이건 이미 확실하니 놓치지 말고 포함해라"고 힌트로 줌
    neighbor_hint = ""
    if skill_neighbors:
        lines = [f"  {s} ↔ {', '.join(ns)}" for s, ns in skill_neighbors.items() if ns]
        if lines:
            neighbor_hint = "\n\n스킬 연관 관계 (함께 쓰이는 스킬 — 보강은 이 방향으로만):\n" + "\n".join(lines)
    # neo4j의 CO_OCCURS 데이터를 프롬프트에 미리 보여줘서, LLM이 "이 스킬 다음엔 뭘 배우면 좋을지"
    # 제안할 때 아무 기술이나 자유롭게 도약하지 못하게 제약 — gap_agent.py에서 본 환각 방지 원칙과 동일
    tree_block = ""
    if all_paths:
        tree_block = (
            "전체 파일 구조 (먼저 이 프로젝트가 무엇인지·어떤 레이어로 구성됐는지 파악):\n"
            + "\n".join(f"  {p}" for p in sorted(all_paths)[:200]) + "\n\n"
        )
    prompt = (
        f"저장소: {owner}/{repo}\n"
        f"README:\n{readme[:2000]}\n\n"
        f"{tree_block}"
        f"아래는 위 구조 중 핵심 파일들의 실제 내용입니다.\n소스 파일:\n{code_block}\n\n"
        f"직군 핵심 스킬 목록: {', '.join(vocab)}{detected_hint}{neighbor_hint}\n\n"
        f"유효한 파일 경로 목록 (relevant_files는 반드시 이 목록에서만 선택):\n"
        + "\n".join(f"  {p}" for p in valid_paths) + "\n\n"
        "위 코드를 분석해 JSON으로만 답하세요 (코드펜스 없이). 모든 문자열 값은 한국어로.\n"
        "{\n"
        '  "project_type": "FastAPI + LangGraph 기반 Agentic RAG 백엔드",\n'
        '  "structure_summary": "프로젝트 구조 2-3문장",\n'
        '  "skill_assessments": [\n'
        "    {\n"
        '      "skill": "스킬명 (핵심 스킬 목록에서만)",\n'
        '      "current_usage": "기본 사용 | 중급 패턴 | 고급 패턴",\n'
        '      "used_patterns": ["코드에서 실제 사용 중인 구체적 패턴"],\n'
        '      "missing_patterns": ["이 프로젝트에 명확히 도움될 보강만. 없으면 빈 배열"],\n'
        '      "how_to_add": "structure_summary(프로젝트 전체)를 바탕으로 이 프로젝트에 무엇을 추가/개선하면 좋을지 프로젝트 레벨로. 명확하지 않으면 빈 문자열.",\n'
        '      "relevant_files": ["위 유효한 파일 경로 목록에서만 선택, 최대 3개"]\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "규칙:\n"
        "- '이미 확인된 스킬'은 반드시 skill_assessments에 포함할 것.\n"
        "- 코드나 의존성 파일에서 실제로 확인된 스킬만 포함. 추측 금지.\n"
        "- current_usage '없음'인 스킬은 제외.\n"
        "- relevant_files는 반드시 '유효한 파일 경로 목록'에 있는 경로만 사용. 없으면 빈 배열.\n"
        "- how_to_add는 프로젝트 전체(structure_summary·README) 관점의 제안. 특정 파일·함수를 지어내지 말 것.\n"
        "- **used_patterns와 다른 기술 범주로 도약 금지** (예: used가 'API 모델 호출'인데 missing에 '딥러닝 최적화'). 지금 하는 것의 자연스러운 다음 단계만.\n"
        "- **'스킬 연관 관계'에 있는 연관 스킬 방향으로만 보강.** 연관 목록에 없는 새 기술·패러다임 도입 금지 (예: AI의 연관에 강화학습이 없으면 강화학습 제안 금지).\n"
        "- **억지로 만들지 말 것.** 이 프로젝트에 실제로 도움될 명확한 보강만. 애매하거나 이미 충분하면 missing_patterns·how_to_add를 비울 것(빈 배열/빈 문자열).\n"
        "- 특히 current_usage가 '고급 패턴'이면 대개 보강 불필요 — 비울 것."
    )

    try:
        resp = openai.chat.completions.create(
            model="gpt-4o",     # pass1(파일 선택)은 mini, pass2(코드 분석)는 더 강력한 gpt-4o
            max_tokens=3000,
            response_format={"type": "json_object"},   # 빈/비JSON 응답 방지 (파싱 실패 char0 방어)
            messages=[{"role": "user", "content": prompt}],
        )
        raw = (resp.choices[0].message.content or "").strip().replace("```json", "").replace("```", "").strip()
        data = json.loads(raw)
        skill_assessments = [
            sa for sa in data.get("skill_assessments", [])
            if sa.get("current_usage", "없음") != "없음"
        ]
        # LLM이 실수로 "current_usage: 없음"인 항목까지 넣었으면, 여기서 한 번 더 걸러냄 (이중 방어)
        for sa in skill_assessments:
            if "skill" in sa:
                sa["skill"] = normalize_skill(sa["skill"])
            # 결정적 환각 방어(모든 분야) — 이미 고급이면 억지 보강 제거.
            # LLM이 고급 스킬에도 missing을 지어내는 '보강점 강박'을 코드로 차단.
            if sa.get("current_usage") == "고급 패턴":
                sa["missing_patterns"] = []
                sa["how_to_add"] = ""
                # 프롬프트에 이미 "고급 패턴이면 비우라"고 지시했지만, LLM이 지시를 어길 수 있으므로
                # 코드에서 한 번 더 강제로 덮어씀 — 프롬프트 지시만 믿지 않는 이 프로젝트의 반복되는 패턴
        # detected_skills(pkg_json·키워드 감지)가 LLM 필터에서 탈락한 경우 기본 assessment로 보장
        if detected_skills:
            assessed_lower = {sa["skill"].lower() for sa in skill_assessments}
            for skill in detected_skills:
                if skill.lower() not in assessed_lower:
                    skill_assessments.append({
                        "skill": normalize_skill(skill),
                        "current_usage": "기본 사용",
                        "fit_assessment": "패키지·설정파일에서 감지됨",
                        "how_to_add": "",
                        "relevant_files": [],
                    })
                    # LLM이 놓친(응답에서 빠뜨린) 스킬이라도, 키워드 매칭으로 이미 확실히 감지된 거라면
                    # 최소한의 기본값으로 강제 포함시킴 — LLM 응답 누락에 대한 안전망
        return {
            "repo": f"{owner}/{repo}",
            "project_type": data.get("project_type", ""),
            "structure_summary": data.get("structure_summary", ""),
            "skill_assessments": skill_assessments,
        }
    except Exception as e:
        logger.warning(f"[github_eval] 프로젝트 분석 실패: {e}")
        return {}


def create_github_evaluator(neo4j: "Neo4jClient", openai=None) -> Callable[["AppState"], dict]:
    """GitHub 평가자 팩토리. 소스 코드를 읽어 스킬 현황과 코칭 컨텍스트를 산출한다."""

    def _eval_one(url: str, vocab: list[str]) -> tuple[list, dict | None, dict | None]:
        # 레포 하나를 통째로 분석하는 내부 헬퍼 — evaluate()가 github_urls 리스트를 순회하며 이걸 호출
        try:
            owner, repo = parse_github_repo(url)
        except ValueError as e:
            logger.warning(f"[github_eval] URL 파싱 실패: {e}")
            return [], None, None
        if not repo:
            logger.warning(f"[github_eval] 레포 미지정 (계정 주소만): {url}")
            return [], None, None
            # 사용자가 "github.com/owner"처럼 레포 없이 계정 주소만 줬을 때 방어

        token = os.getenv("GITHUB_TOKEN")
        headers = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
            # 토큰이 있으면 인증된 요청(더 높은 rate limit)을, 없어도 공개 레포는 조회 가능 (mock 없이도 동작)
        raw_headers = {**headers, "Accept": "application/vnd.github.raw"}
        base = f"https://api.github.com/repos/{owner}/{repo}"

        # 주 언어
        try:
            languages = _get_json(f"{base}/languages", headers)
        except Exception as e:
            logger.warning(f"[github_eval] GitHub API 실패 (languages, {owner}/{repo}): {e}")
            return [], None, None
            # 언어 조회가 실패하면(레포 없음 등) 이 레포 전체를 포기 — 나머지 정보 조회 자체가 무의미해서
        lang_text = " ".join(languages.keys()) if isinstance(languages, dict) else ""

        # repo 메타
        description, topics = "", []
        try:
            meta = _get_json(base, headers)
            if isinstance(meta, dict):
                description = meta.get("description") or ""
                topics = meta.get("topics") or []
        except Exception as e:
            logger.warning(f"[github_eval] repo 메타 조회 실패: {e}")
            # 이건 실패해도 위와 달리 return 안 하고 계속 진행 — 메타 정보는 부가적이라 없어도 분석 가능

        # README
        readme_text = ""
        try:
            rd = httpx.get(f"{base}/readme", headers=raw_headers, timeout=10)
            if rd.status_code == 200:
                readme_text = rd.text
        except Exception as e:
            logger.warning(f"[github_eval] README 조회 실패: {e}")

        # 소스 파일 읽기 (새로 추가)
        file_contents, all_paths = _read_source_tree(owner, repo, headers, openai)
        manifest_text, package_jsons, python_manifests = _read_repo_manifests(owner, repo, headers, all_paths)

        # 스킬 키워드 매칭 (빠른 presence 감지)
        skills = _skills_from_sources(owner, repo, lang_text, readme_text, manifest_text, vocab)

        # package.json 생태계 매핑 (drizzle-orm → PostgreSQL 등)
        existing_skills = {s["skill"] for s in skills}
        for path, text in package_jsons:
            for s in _skills_from_pkg_json(text, vocab, source_path=path):
                if s["skill"] not in existing_skills:
                    skills.append(s)
                    existing_skills.add(s["skill"])
                    # 두 방식(키워드 매칭, package.json 매핑)에서 중복 발견된 스킬은 한 번만 남김
        for path, text in python_manifests:
            for s in _skills_from_python_manifest(text, vocab, source_path=path):
                if s["skill"] not in existing_skills:
                    skills.append(s)
                    existing_skills.add(s["skill"])

        # 프로젝트 심층 분석 (소스 코드 기반) — README mention은 강제 포함하지 않는다.
        # README는 반례·금지사항에도 기술명이 등장하므로, 코드/의존성/언어 근거만 "이미 확인"으로 넘긴다.
        detected = _code_detected_skills(skills)
        # CO_OCCURS 이웃 — 보강 방향을 연관 스킬로 제약(환각 도약 차단)
        skill_neighbors = neo4j.get_skill_neighbors(vocab) if neo4j else {}
        project_context = _assess_project_and_skills(
            openai, owner, repo, file_contents, vocab, readme_text,
            detected_skills=detected, all_paths=all_paths, skill_neighbors=skill_neighbors,
        )

        # relevant_files 환각 제거 (결정적, LLM 없이)
        project_context = _validate_project_context(project_context, all_paths, file_contents)
        if not project_context or not project_context.get("skill_assessments"):
            project_context = _fallback_project_context(owner, repo, languages, skills, readme_text)
        if project_context:
            project_context["readme_summary"] = project_context.get("readme_summary") or _readme_summary(readme_text)
            project_context["confirmed_stack"] = _code_detected_skills(skills)[:12]
            project_context["key_files"] = list(file_contents.keys())[:10]

        # 레포 전체 경로를 context에 실어 보냄 — finalize_coach가 코칭 텍스트의
        # 파일 경로 환각을 대조·제거하는 데 사용. LLM 프롬프트 직렬화 시에는 제외됨.
        if project_context:
            project_context["repo_paths"] = sorted(all_paths)
            # 지난번 nodes.py의 finalize_coach()에서 "contexts_for_prompt = {k:v for k,v ... if k != 'repo_paths'}"로
            # 이 필드를 프롬프트에서는 빼고 검증용으로만 쓰던 게 바로 여기서 채워진 값

        # category='soft'(자격증·방법론·순수역량) 스킬은 ③ 코드 보강 제외 → ②학습으로 (결정적)
        _sas = project_context.get("skill_assessments") or []
        if _sas and neo4j:
            _cats = neo4j.get_skill_categories([sa.get("skill") for sa in _sas])
            for sa in _sas:
                if _cats.get(sa.get("skill")) == "soft":
                    sa["missing_patterns"] = []
                    sa["how_to_add"] = ""
                    # "Agile" 같은 소프트 스킬은 코드로 보강할 수 있는 게 아니므로, 코드 제안 필드를 강제로 비움

        # 기존 profile (하위 호환)
        profile = {
            "repo": f"{owner}/{repo}",
            "summary": description,
            "tech_stack": list(languages.keys()) if isinstance(languages, dict) else [],
            "observations": topics,
        }

        return skills, profile, project_context

    def evaluate(state: "AppState") -> dict:
        urls = state.get("github_urls") or []
        if not urls:
            return {"github_eval": {"skills": [], "profiles": [], "project_contexts": []}}
            # GitHub URL을 아예 안 줬으면 조기 반환 — resume_eval의 "입력 없으면 빈 결과" 패턴과 동일
        vocab = neo4j.get_job_family_skills(state.get("job_family") or "", exclude_common_threshold=None)
        # 지난번 neo4j_client.py에서 본 그 메서드 — 이 직군의 상위 30개 스킬을 vocab(검색 대상 단어장)으로 씀
        if not vocab:
            logger.warning(f"[github_eval] 직군 스킬 어휘 없음 (job_family={state.get('job_family')!r})")
            return {"github_eval": {"skills": [], "profiles": [], "project_contexts": []}}
        # 이력서 스킬도 vocab에 포함 — 직군 밖 스킬도 GitHub에서 검증 가능해야 함
        resume_skills = state.get("resume_skills") or []
        vocab = vocab + [s for s in resume_skills if s not in vocab]
        # 예: 이력서에 "Rust"라고 써있는데 직군 상위 30개엔 Rust가 없어도, GitHub에서 Rust 사용을
        # 검증할 수 있어야 이력서 주장의 신뢰도를 판단할 수 있으므로 vocab에 추가

        merged_skills: list = []
        seen: set = set()
        profiles: list = []
        project_contexts: list = []

        for url in urls:
            # 사용자가 GitHub 레포를 여러 개 줬을 수 있어서 하나씩 순회 (병렬 처리는 안 함 — 순차 실행)
            skills, profile, context = _eval_one(url, vocab)
            for s in skills:
                key = s.get("skill") if isinstance(s, dict) else s
                if key not in seen:
                    seen.add(key)
                    merged_skills.append(s)
                    # 레포 여러 개에서 같은 스킬이 중복 발견돼도 결과엔 한 번만 남김
            if profile:
                profiles.append(profile)
            if context:
                project_contexts.append(context)

        return {"github_eval": {
            "skills": merged_skills,
            "profiles": profiles,
            "project_contexts": project_contexts,  # 코칭 컨텍스트 (신규)
        }}

    return evaluate
