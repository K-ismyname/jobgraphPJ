# 지정 GitHub 레포에서 대상 직군의 스킬을 코드 근거로 검증하는 평가자 (코드 modality)
from __future__ import annotations

import concurrent.futures
import json
import os
import re
from typing import TYPE_CHECKING, Callable

import httpx

from src.portfolio.github_connector import parse_github_repo
from src.extraction.normalizer import normalize_skill
# 텍스트 매칭 유틸은 공용 모듈에서 — tools/deploy_eval/ragas_eval도 여기서 가져다 쓴다
from src.common.text_match import word_match as _word_match, keywords_for as _keywords_for

if TYPE_CHECKING:
    from src.agent.state import AppState
    from src.storage.neo4j_client import Neo4jClient

# package.json 패키지명 → 표준 스킬명 (생태계 매핑)
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

# 본문을 읽어 패키지명을 매칭할 의존성 파일 (소문자)
_TEXT_MANIFESTS = {
    "requirements.txt", "pyproject.toml", "pipfile", "setup.py",
    "package.json", "environment.yml",
}
# 존재만으로 의미가 있는 설정 파일 (파일명 자체를 신호로 사용)
_PRESENCE_MANIFESTS = {"dockerfile", "docker-compose.yml", "go.mod", "cargo.toml"}
_ALL_MANIFESTS = _TEXT_MANIFESTS | _PRESENCE_MANIFESTS

# 소스 파일 읽기 설정
_SKIP_DIRS = {
    "node_modules", ".git", "dist", "build", "__pycache__",
    ".next", "venv", "env", ".venv", "vendor", "coverage", ".pytest_cache",
}
_SKIP_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".woff", ".ttf",
    ".pyc", ".pdf", ".zip", ".map",
}
_SKIP_INFIXES = {".min.js", ".min.css", ".lock"}
_SKIP_FILENAMES = {"__init__.py", "__init__.ts"}
_SOURCE_EXTENSIONS = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".java", ".rs",
    ".vue", ".yaml", ".yml", ".toml",
}
_MAX_FILES = 25
_MAX_FILE_CHARS = 8_000   # 파일당 최대 문자 수
_MAX_CODE_CHARS = 40_000  # LLM에 넘길 총 코드 최대 문자 수

# 골격 파일 — 프로젝트 구조를 가장 잘 드러내는 파일을 25개 예산에서 우선 선택
_MANIFEST_FILES = {
    "requirements.txt", "package.json", "pyproject.toml", "go.mod", "cargo.toml",
    "pom.xml", "build.gradle", "gemfile", "composer.json", "setup.py", "pipfile",
}
_ENTRY_STEMS = {"main", "app", "index", "supervisor", "server", "__main__", "cli", "run"}


def _skills_from_pkg_json(pkg_json_text: str, vocab: list[str]) -> list[dict]:
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

    vocab_set = {v.lower(): v for v in vocab}
    results: list[dict] = []
    seen: set[str] = set()
    for pkg_name in all_deps:
        skill_raw = _PKG_TO_SKILL.get(pkg_name.lower())
        if not skill_raw:
            continue
        skill = vocab_set.get(skill_raw.lower(), skill_raw)
        if skill.lower() not in vocab_set or skill in seen:
            continue
        seen.add(skill)
        results.append({
            "skill": skill,
            "evidence": f"package.json 의존성 {pkg_name} → {skill} 확인",
            "source": "github",
            "strength": "code",   # 의존성 선언 = 코드 근거
            "level_hint": "실무",
        })
    return results


def _manifest_match(keyword: str, text: str) -> bool:
    """의존성/설정 소스 매칭."""
    if _word_match(keyword, text):
        return True
    for manifest in _PRESENCE_MANIFESTS:
        first_token = re.split(r"[.\-]", manifest, maxsplit=1)[0]
        if (first_token == keyword or manifest == keyword + "file") and _word_match(manifest, text):
            return True
    return False


def _skills_from_sources(
    owner: str, repo: str, lang_text: str, readme_text: str, manifest_text: str,
    vocab: list[str],
) -> list[dict[str, str]]:
    """대상 직군 스킬(vocab)을 주 언어·README·의존성파일에서 찾아 증거로 만든다."""
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
        # 의존성 파일·주 언어(GitHub 언어 통계=실제 코드)는 코드 근거,
        # README에만 있으면 단순 언급 — 이 구분이 consensus의 Verified 판정을 좌우한다.
        strength = "code" if (in_manifest or in_lang) else "mention"
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
    for part in parts[:-1]:
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


def _select_files_llm(openai, owner: str, repo: str,
                      candidates: list[str], fallback: list[str]) -> list[str]:
    """파일 경로 트리를 gpt-4o-mini에 주고 읽을 핵심 파일을 직접 고르게 한다(B, pass1).

    파일 '선택'은 경로 패턴 인식 수준이라 mini로 충분(내용 분석은 pass2의 gpt-4o가 함).
    실패·빈 결과·환각 경로면 휴리스틱 fallback을 반환해 항상 안전하게 동작한다.
    """
    if not openai or not candidates:
        return fallback
    tree_text = "\n".join(sorted(candidates))
    prompt = (
        f"저장소 {owner}/{repo}의 소스 파일 경로 목록입니다:\n{tree_text}\n\n"
        f"이 프로젝트를 이해하려면 어떤 파일을 읽어야 하는지 최대 {_MAX_FILES}개 고르세요. "
        "엔트리포인트(main·app·supervisor 등), 핵심 로직, 설정/매니페스트를 우선하고, "
        "테스트·마이그레이션·자동생성 파일은 후순위로. "
        'JSON 배열로 경로만 반환하세요(코드펜스 없이). 예: ["src/main.py", "requirements.txt"]'
    )
    try:
        resp = openai.chat.completions.create(
            model="gpt-4o-mini", temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.choices[0].message.content.strip().replace("```json", "").replace("```", "").strip()
        picked = json.loads(raw)
        cand_set = set(candidates)
        chosen = [p for p in picked if isinstance(p, str) and p in cand_set][:_MAX_FILES]
        return chosen or fallback
    except Exception as e:
        print(f"[github_eval] LLM 파일 선택 실패, 휴리스틱 fallback: {e}")
        return fallback


def _read_source_tree(owner: str, repo: str, headers: dict, openai=None) -> tuple[dict[str, str], set[str]]:
    """레포 전체 파일 트리에서 핵심 소스 파일을 선택해 병렬로 읽는다.

    반환: (읽은 파일 내용 dict, 레포 전체 파일 경로 집합)
    전체 경로 집합은 relevant_files 환각 검증에 사용한다.
    """
    base = f"https://api.github.com/repos/{owner}/{repo}"

    # 기본 브랜치 확인
    try:
        default_branch = httpx.get(base, headers=headers, timeout=10).json().get("default_branch", "main")
    except Exception:
        default_branch = "main"

    # 재귀 파일 트리
    try:
        tree = httpx.get(
            f"{base}/git/trees/{default_branch}?recursive=1",
            headers=headers, timeout=15
        ).json().get("tree", [])
    except Exception as e:
        print(f"[github_eval] 파일 트리 조회 실패: {e}")
        return {}, set()

    # 레포 전체 파일 경로 집합 (환각 검증용) + 파일 크기 (큰 파일=핵심 로직 우선용)
    all_paths: set[str] = {it["path"] for it in tree if it.get("type") == "blob"}
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

    # 매니페스트·엔트리포인트는 무조건 포함. 나머지는 디렉토리별 라운드로빈으로
    # 한 디렉토리가 25개를 독식하지 않게 골고루 — 프로젝트 골격을 넓게 보여준다.
    candidates.sort(key=lambda p: (_priority(p), -sizes.get(p, 0)))
    must = [p for p in candidates if _priority(p) <= 1][:_MAX_FILES]
    rest = [p for p in candidates if _priority(p) > 1]
    by_dir: dict[str, list[str]] = {}
    for p in rest:
        by_dir.setdefault("/".join(p.split("/")[:-1]), []).append(p)
    heuristic_selected = list(must)
    queues = [q for q in by_dir.values()]
    while len(heuristic_selected) < _MAX_FILES and queues:
        queues = [q for q in queues if q]
        for q in queues:
            if len(heuristic_selected) >= _MAX_FILES:
                break
            heuristic_selected.append(q.pop(0))

    # B(pass1): LLM이 트리를 보고 핵심 파일을 직접 선택 — 실패 시 휴리스틱 fallback
    selected = _select_files_llm(openai, owner, repo, candidates, heuristic_selected)

    # 병렬 파일 읽기
    raw_headers = {**headers, "Accept": "application/vnd.github.raw"}

    def _fetch(path: str) -> tuple[str, str | None]:
        try:
            resp = httpx.get(f"{base}/contents/{path}", headers=raw_headers, timeout=10)
            if resp.status_code == 200:
                return path, resp.text[:_MAX_FILE_CHARS]
        except Exception:
            pass
        return path, None

    contents: dict[str, str] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        for path, text in ex.map(_fetch, selected):
            if text:
                contents[path] = text

    return contents, all_paths


def _validate_project_context(ctx: dict, all_paths: set[str]) -> dict:
    """relevant_files를 실제 레포 파일 목록과 대조해 존재하지 않는 경로를 제거한다 (LLM 없이 결정적)."""
    if not ctx or not all_paths:
        return ctx
    cleaned = []
    for sa in ctx.get("skill_assessments", []):
        real = [f for f in sa.get("relevant_files", []) if f in all_paths]
        ghost = [f for f in sa.get("relevant_files", []) if f not in all_paths]
        if ghost:
            print(f"[github_eval] 환각 파일 제거 ({sa.get('skill')}): {ghost}")
        cleaned.append({**sa, "relevant_files": real})

    return {**ctx, "skill_assessments": cleaned}


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
    if not openai or not file_contents:
        return {}

    code_block = "\n\n".join(
        f"### {path}\n{content}" for path, content in file_contents.items()
    )[:_MAX_CODE_CHARS]

    valid_paths = sorted(file_contents.keys())
    detected_hint = (
        f"\n이미 확인된 스킬 (반드시 포함): {', '.join(detected_skills)}"
        if detected_skills else ""
    )
    neighbor_hint = ""
    if skill_neighbors:
        lines = [f"  {s} ↔ {', '.join(ns)}" for s, ns in skill_neighbors.items() if ns]
        if lines:
            neighbor_hint = "\n\n스킬 연관 관계 (함께 쓰이는 스킬 — 보강은 이 방향으로만):\n" + "\n".join(lines)
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
            model="gpt-4o",
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
        for sa in skill_assessments:
            if "skill" in sa:
                sa["skill"] = normalize_skill(sa["skill"])
            # 결정적 환각 방어(모든 분야) — 이미 고급이면 억지 보강 제거.
            # LLM이 고급 스킬에도 missing을 지어내는 '보강점 강박'을 코드로 차단.
            if sa.get("current_usage") == "고급 패턴":
                sa["missing_patterns"] = []
                sa["how_to_add"] = ""
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
        return {
            "repo": f"{owner}/{repo}",
            "project_type": data.get("project_type", ""),
            "structure_summary": data.get("structure_summary", ""),
            "skill_assessments": skill_assessments,
        }
    except Exception as e:
        print(f"[github_eval] 프로젝트 분석 실패: {e}")
        return {}


def create_github_evaluator(neo4j: "Neo4jClient", openai=None) -> Callable[["AppState"], dict]:
    """GitHub 평가자 팩토리. 소스 코드를 읽어 스킬 현황과 코칭 컨텍스트를 산출한다."""

    def _eval_one(url: str, vocab: list[str]) -> tuple[list, dict | None, dict | None]:
        try:
            owner, repo = parse_github_repo(url)
        except ValueError as e:
            print(f"[github_eval] URL 파싱 실패: {e}")
            return [], None, None
        if not repo:
            print(f"[github_eval] 레포 미지정 (계정 주소만): {url}")
            return [], None, None

        token = os.getenv("GITHUB_TOKEN")
        headers = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        raw_headers = {**headers, "Accept": "application/vnd.github.raw"}
        base = f"https://api.github.com/repos/{owner}/{repo}"

        # 주 언어
        try:
            languages = httpx.get(f"{base}/languages", headers=headers, timeout=10).json()
        except Exception as e:
            print(f"[github_eval] GitHub API 실패: {e}")
            return [], None, None
        lang_text = " ".join(languages.keys()) if isinstance(languages, dict) else ""

        # repo 메타
        description, topics = "", []
        try:
            meta = httpx.get(base, headers=headers, timeout=10).json()
            if isinstance(meta, dict):
                description = meta.get("description") or ""
                topics = meta.get("topics") or []
        except Exception as e:
            print(f"[github_eval] repo 메타 조회 실패: {e}")

        # README
        readme_text = ""
        try:
            rd = httpx.get(f"{base}/readme", headers=raw_headers, timeout=10)
            if rd.status_code == 200:
                readme_text = rd.text
        except Exception as e:
            print(f"[github_eval] README 조회 실패: {e}")

        # 루트 의존성/설정 파일 (기존 키워드 매칭용)
        file_names: list = []
        manifest_parts: list[str] = []
        pkg_json_text = ""
        try:
            root = httpx.get(f"{base}/contents", headers=headers, timeout=10).json()
            if isinstance(root, list):
                file_names = [it["name"] for it in root]
                for it in root:
                    name = it["name"]
                    if name.lower() in _ALL_MANIFESTS:
                        manifest_parts.append(name)
                        if name.lower() in _TEXT_MANIFESTS:
                            body = httpx.get(f"{base}/contents/{name}", headers=raw_headers, timeout=10)
                            if body.status_code == 200:
                                manifest_parts.append(body.text)
                                if name.lower() == "package.json":
                                    pkg_json_text = body.text
        except Exception as e:
            print(f"[github_eval] 의존성 파일 조회 실패: {e}")
        manifest_text = " ".join(manifest_parts)

        # 소스 파일 읽기 (새로 추가)
        file_contents, all_paths = _read_source_tree(owner, repo, headers, openai)

        # 스킬 키워드 매칭 (빠른 presence 감지)
        skills = _skills_from_sources(owner, repo, lang_text, readme_text, manifest_text, vocab)

        # package.json 생태계 매핑 (drizzle-orm → PostgreSQL 등)
        pkg_skills = _skills_from_pkg_json(pkg_json_text, vocab)
        existing_skills = {s["skill"] for s in skills}
        for s in pkg_skills:
            if s["skill"] not in existing_skills:
                skills.append(s)
                existing_skills.add(s["skill"])

        # 프로젝트 심층 분석 (소스 코드 기반) — 키워드 매칭 결과를 힌트로 전달
        detected = [s["skill"] for s in skills]
        # CO_OCCURS 이웃 — 보강 방향을 연관 스킬로 제약(환각 도약 차단)
        skill_neighbors = neo4j.get_skill_neighbors(vocab) if neo4j else {}
        project_context = _assess_project_and_skills(
            openai, owner, repo, file_contents, vocab, readme_text,
            detected_skills=detected, all_paths=all_paths, skill_neighbors=skill_neighbors,
        )

        # relevant_files 환각 제거 (결정적, LLM 없이)
        project_context = _validate_project_context(project_context, all_paths)

        # category='soft'(자격증·방법론·순수역량) 스킬은 ③ 코드 보강 제외 → ②학습으로 (결정적)
        _sas = project_context.get("skill_assessments") or []
        if _sas and neo4j:
            _cats = neo4j.get_skill_categories([sa.get("skill") for sa in _sas])
            for sa in _sas:
                if _cats.get(sa.get("skill")) == "soft":
                    sa["missing_patterns"] = []
                    sa["how_to_add"] = ""

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
        vocab = neo4j.get_job_family_skills(state.get("job_family") or "", exclude_common_threshold=None)
        if not vocab:
            print(f"[github_eval] 직군 스킬 어휘 없음 (job_family={state.get('job_family')!r})")
            return {"github_eval": {"skills": [], "profiles": [], "project_contexts": []}}
        # 이력서 스킬도 vocab에 포함 — 직군 밖 스킬도 GitHub에서 검증 가능해야 함
        resume_skills = state.get("resume_skills") or []
        vocab = vocab + [s for s in resume_skills if s not in vocab]

        merged_skills: list = []
        seen: set = set()
        profiles: list = []
        project_contexts: list = []

        for url in urls:
            skills, profile, context = _eval_one(url, vocab)
            for s in skills:
                key = s.get("skill") if isinstance(s, dict) else s
                if key not in seen:
                    seen.add(key)
                    merged_skills.append(s)
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
