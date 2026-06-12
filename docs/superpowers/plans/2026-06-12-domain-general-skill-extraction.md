# 직무 무관 후보 스킬 추출 (범용화) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 지원자(이력서·GitHub) 스킬을 직군 무관하게 온전히 추출해, 사용자가 고른 10개 직군 중 어느 것이든 적합도 평가가 되게 한다.

**Architecture:** (1) 이력서 추출기의 `text[:4000]` 잘림 제거 → 전체 텍스트 단일 호출. (2) GitHub 평가자를 AI 전용 하드코딩 사전에서 **직군별 스킬 집합**(Neo4j, `gap_analysis`와 공유) 단어경계+별칭 매칭으로 전환. (3) `run_supervisor` 진입에서 `job_family` 유효성 검증.

**Tech Stack:** Python, OpenAI gpt-4o-mini, Neo4j, httpx, pytest. 기존 `_word_match`·`normalizer.SKILL_ALIASES` 재사용.

**설계 문서:** `docs/superpowers/specs/2026-06-12-domain-general-skill-extraction-design.md`

---

## 사전 지식 (기존 코드)

- `src/extraction/skill_extractor.py`: `extract_skills_from_resume(text, client=None)`가 `text[:4000]`만 LLM에 보냄. 내부 `_chat(client, prompt, max_tokens=2048)`. 반환 `ResumeExtraction(candidate_name, sections=[PortfolioSection(skills=[DemonstratedSkill(name,category,evidence,confidence)])])`.
- `src/storage/neo4j_client.py`: `class Neo4jClient`. `execute_query(query, **params) -> list[dict]`, `get_portfolio_demonstrated_skills(owner)` 패턴 존재. JobFamily 라벨 속성은 `name`.
- `src/agent/evaluators/github_eval.py`: `_word_match(keyword, text)`(단어경계), `_skills_from_sources(owner, repo, lang_text, readme_text, manifest_text)`(현재 `_SKILL_KEYWORDS` 순회), `create_github_evaluator()`(인자 없음). `parse_github_repo`·`_SKILL_KEYWORDS` import.
- `src/extraction/normalizer.py`: `SKILL_ALIASES: dict[str,str]` = {별칭소문자: 정규화명}. 예 `{"postgres":"PostgreSQL"}`.
- `src/agent/supervisor.py`: `create_supervisor_graph`에서 `github_eval = create_github_evaluator()`(159줄). `run_supervisor(graph, job_family, owner, pdf_path=None, resume_text=None, github_url=None, resume_skills=None)` — 진입에 입력 가드 있음, `graph.invoke(initial, config)` 호출.
- `src/agent/tools.py`: `_JOB_SKILLS_QUERY`(JobFamily→공고→스킬, weight=공고수, LIMIT 30). `gap_analysis` 툴이 이를 사용.
- `_SKILL_KEYWORDS`는 `boost_confidence_from_github`(프로필 경로)에서도 쓰이므로 **삭제하지 않음**. github_eval에서 사용만 중단.

---

## Task 1: 이력서 추출기 — 잘림 제거

**Files:**
- Modify: `src/extraction/skill_extractor.py`
- Test: `tests/unit/test_skill_extractor_fulltext.py`

- [ ] **Step 1: 실패 테스트 작성**

Create `tests/unit/test_skill_extractor_fulltext.py`:
```python
# 이력서 추출기가 앞 4000자 너머의 텍스트도 LLM에 전달하는지 검증
from src.extraction import skill_extractor
from src.extraction.skill_extractor import extract_skills_from_resume


def test_full_text_sent_to_llm(monkeypatch):
    captured = {}

    def fake_chat(client, prompt, max_tokens=1024):
        captured["prompt"] = prompt
        captured["max_tokens"] = max_tokens
        return '{"candidate_name": "X", "sections": []}'

    monkeypatch.setattr(skill_extractor, "_chat", fake_chat)
    # 4000자 이후에 핵심 스킬을 배치
    long_text = "머리말 " + ("A" * 5000) + " Java Spring Redis " + ("B" * 1000)
    extract_skills_from_resume(long_text, client=object())

    assert "Java Spring Redis" in captured["prompt"]   # 잘리지 않고 포함
    assert captured["max_tokens"] >= 4096
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/unit/test_skill_extractor_fulltext.py -v`
Expected: FAIL (`"Java Spring Redis"`가 `text[:4000]`로 잘려 prompt에 없음).

- [ ] **Step 3: 구현 — 잘림 한도 상향 + 출력 토큰 상향**

`src/extraction/skill_extractor.py`의 `_chat` 함수 바로 위(모듈 상수 위치)에 추가:
```python
# 이력서 전체를 한 번에 처리 (gpt-4o-mini 128K 컨텍스트는 현실 이력서를 모두 수용)
_RESUME_TEXT_CAP = 100_000
```

`extract_skills_from_resume` 본문에서 prompt 생성 전에 텍스트 상한 처리:
```python
    if client is None:
        client = _get_client()

    if len(text) > _RESUME_TEXT_CAP:
        print(f"[skill_extractor] 이력서가 {len(text)}자 — 상한 {_RESUME_TEXT_CAP}자까지만 처리")
        text = text[:_RESUME_TEXT_CAP]
```

그리고 prompt 안의 `{text[:4000]}` 를 `{text}` 로 변경:
```python
이력서:
{text}
```

마지막 `_chat(client, prompt, max_tokens=2048)` 를 `max_tokens=4096` 으로 변경:
```python
    return ResumeExtraction(**json.loads(_chat(client, prompt, max_tokens=4096)))
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/unit/test_skill_extractor_fulltext.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/extraction/skill_extractor.py tests/unit/test_skill_extractor_fulltext.py
git commit -m "fix(extraction): 이력서 추출기 4000자 잘림 제거 — 전체 텍스트 처리"
```

---

## Task 2: Neo4jClient — 직군 스킬·직군 목록 메서드

**Files:**
- Modify: `src/storage/neo4j_client.py` (`get_portfolio_demonstrated_skills` 메서드 다음에 추가)
- Test: `tests/unit/test_neo4j_job_methods.py`

- [ ] **Step 1: 실패 테스트 작성**

Create `tests/unit/test_neo4j_job_methods.py`:
```python
# Neo4jClient 직군 스킬/목록 메서드 — execute_query를 가짜로 주입해 매핑 로직만 검증
from src.storage.neo4j_client import Neo4jClient


class _Fake:
    def __init__(self, rows):
        self._rows = rows

    def execute_query(self, query, **params):
        return self._rows


def test_get_job_family_skills_maps_names():
    fake = _Fake([{"skill": "Java", "weight": 20}, {"skill": "Spring", "weight": 15}])
    names = Neo4jClient.get_job_family_skills(fake, "Software Engineer")
    assert names == ["Java", "Spring"]


def test_list_job_families_filters_empty():
    fake = _Fake([{"name": "AI/LLM Engineer"}, {"name": None}, {"name": "Software Engineer"}])
    assert Neo4jClient.list_job_families(fake) == ["AI/LLM Engineer", "Software Engineer"]


def test_methods_graceful_on_error():
    class _Boom:
        def execute_query(self, query, **params):
            raise RuntimeError("db down")
    assert Neo4jClient.get_job_family_skills(_Boom(), "X") == []
    assert Neo4jClient.list_job_families(_Boom()) == []
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/unit/test_neo4j_job_methods.py -v`
Expected: FAIL (`AttributeError: ... has no attribute 'get_job_family_skills'`)

- [ ] **Step 3: 구현 — 메서드 두 개 추가**

`src/storage/neo4j_client.py`의 `get_portfolio_demonstrated_skills` 메서드 정의 직후에 추가:
```python
    def list_job_families(self) -> list[str]:
        """등록된 직군명 목록 (유효성 검증·선택지 노출용)."""
        try:
            rows = self.execute_query(
                "MATCH (j:JobFamily) RETURN j.name AS name ORDER BY j.posting_count DESC"
            )
            return [r["name"] for r in rows if r.get("name")]
        except Exception as e:
            print(f"[neo4j] 직군 목록 조회 실패: {e}")
            return []

    def get_job_family_skills(self, job_family: str) -> list[str]:
        """직군의 상위 요구/우대 스킬명 (gap_analysis와 동일 패턴, 공고수 빈도순)."""
        query = """
        MATCH (:JobFamily {name: $job_family})<-[:INSTANCE_OF]-(jp)-[r:REQUIRES|PREFERS]->(s:Skill)
        RETURN s.name AS skill, count(jp) AS weight
        ORDER BY weight DESC
        LIMIT 30
        """
        try:
            rows = self.execute_query(query, job_family=job_family)
            return [r["skill"] for r in rows if r.get("skill")]
        except Exception as e:
            print(f"[neo4j] 직군 스킬 조회 실패: {e}")
            return []
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/unit/test_neo4j_job_methods.py -v`
Expected: 3 passed

- [ ] **Step 5: 커밋**

```bash
git add src/storage/neo4j_client.py tests/unit/test_neo4j_job_methods.py
git commit -m "feat(storage): Neo4jClient에 list_job_families·get_job_family_skills 추가"
```

---

## Task 3: GitHub 평가자 — 직군별 스킬 사전 매칭 + 별칭

**Files:**
- Modify: `src/agent/evaluators/github_eval.py`
- Modify: `src/agent/supervisor.py:159` (호출부)
- Test: `tests/unit/test_github_eval.py` (교체)

- [ ] **Step 1: 실패 테스트 작성 (교체)**

Replace `tests/unit/test_github_eval.py` 전체:
```python
# GitHub 평가자 — 직군 스킬 사전 매칭, 별칭, 오프라인 가드
from src.agent.evaluators.github_eval import (
    create_github_evaluator,
    _word_match,
    _keywords_for,
    _skills_from_sources,
)
from src.portfolio.github_connector import parse_github_repo


class _FakeNeo4j:
    def __init__(self, skills):
        self._skills = skills

    def get_job_family_skills(self, job_family):
        return self._skills


def test_no_url_empty():
    node = create_github_evaluator(_FakeNeo4j(["Java"]))
    out = node({"github_url": None, "job_family": "Software Engineer"})
    assert out["github_eval"]["skills"] == []


def test_invalid_url_empty():
    node = create_github_evaluator(_FakeNeo4j(["Java"]))
    out = node({"github_url": "not-a-url", "job_family": "Software Engineer"})
    assert out["github_eval"]["skills"] == []


def test_account_url_only_empty():
    node = create_github_evaluator(_FakeNeo4j(["Java"]))
    out = node({"github_url": "https://github.com/fastapi", "job_family": "Software Engineer"})
    assert out["github_eval"]["skills"] == []


def test_empty_vocab_empty():
    # 직군 스킬 어휘가 없으면(연결 실패 등) 빈 결과
    node = create_github_evaluator(_FakeNeo4j([]))
    out = node({"github_url": "https://github.com/x/y", "job_family": "Software Engineer"})
    assert out["github_eval"]["skills"] == []


def test_parse_github_repo():
    assert parse_github_repo("https://github.com/fastapi/fastapi") == ("fastapi", "fastapi")
    assert parse_github_repo("https://github.com/fastapi/fastapi/blob/master/README.md") == ("fastapi", "fastapi")
    assert parse_github_repo("https://github.com/fastapi") == ("fastapi", None)


def test_word_match_no_false_positive():
    assert _word_match("react", "this code reacts to a reaction") is False
    assert _word_match("aws", "the program draws shapes") is False
    assert _word_match("react", "built with react and vite") is True


def test_keywords_for_includes_aliases():
    # PostgreSQL의 별칭 postgres가 매칭 키워드에 포함
    kws = _keywords_for("PostgreSQL")
    assert "postgresql" in kws and "postgres" in kws


def test_skills_from_vocab_matches_alias_and_manifest():
    vocab = ["PostgreSQL", "Java", "Docker"]
    skills = _skills_from_sources(
        owner="me", repo="proj",
        lang_text="Java", readme_text="uses postgres for storage",
        manifest_text="Dockerfile", vocab=vocab,
    )
    by_name = {s["skill"]: s for s in skills}
    assert by_name.keys() == {"PostgreSQL", "Java", "Docker"}
    assert "README" in by_name["PostgreSQL"]["evidence"]      # 별칭 postgres가 README에서
    assert "주 언어" in by_name["Java"]["evidence"]
    assert "의존성/설정파일" in by_name["Docker"]["evidence"]
    assert all(s["source"] == "github" for s in skills)


def test_skills_none_when_no_match():
    skills = _skills_from_sources("me", "proj", "", "", "", vocab=["Kotlin", "Rust"])
    assert skills == []
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/unit/test_github_eval.py -v`
Expected: FAIL (`_keywords_for` 없음, `_skills_from_sources` 시그니처 불일치, `create_github_evaluator`가 인자 요구)

- [ ] **Step 3: 구현 — github_eval.py 재작성**

Replace `src/agent/evaluators/github_eval.py` 전체:
```python
# 지정 GitHub 레포에서 대상 직군의 스킬을 코드 근거로 검증하는 평가자 (코드 modality)
from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, Callable

import httpx

from src.portfolio.github_connector import parse_github_repo
from src.extraction.normalizer import SKILL_ALIASES

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
        in_manifest = any(_word_match(kw, manifest_l) for kw in kws)
        if not (in_lang or in_readme or in_manifest):
            continue
        where = []
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


def create_github_evaluator(neo4j) -> Callable[["AppState"], dict]:
    """GitHub 평가자 팩토리. 대상 직군의 스킬 집합을 레포 코드 근거로 검증한다."""
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

        vocab = neo4j.get_job_family_skills(state.get("job_family") or "")
        if not vocab:
            print(f"[github_eval] 직군 스킬 어휘 없음 (job_family={state.get('job_family')!r})")
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

        # 의존성/설정 파일 (루트만 확인)
        manifest_parts: list[str] = []
        try:
            root = httpx.get(f"{base}/contents", headers=headers, timeout=10).json()
            if not isinstance(root, list):
                root = []
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
        return {"github_eval": {"skills": skills}}

    return evaluate
```

- [ ] **Step 4: 호출부 수정**

`src/agent/supervisor.py` 159줄을 변경:
```python
    github_eval = create_github_evaluator(neo4j)
```

- [ ] **Step 5: 통과 확인**

Run: `python -m pytest tests/unit/test_github_eval.py -v`
Expected: 9 passed

- [ ] **Step 6: 회귀 확인 (그래프 컴파일)**

Run: `python -m pytest tests/ -q -k "not test_returns_dict"`
Expected: 전부 통과 (구조 테스트 포함)

- [ ] **Step 7: 커밋**

```bash
git add src/agent/evaluators/github_eval.py src/agent/supervisor.py tests/unit/test_github_eval.py
git commit -m "feat(agent): GitHub 평가자를 직군별 스킬 사전 매칭으로 — AI 전용 사전 제거"
```

---

## Task 4: run_supervisor — 직군명 검증 (진입 fail-fast)

**Files:**
- Modify: `src/agent/supervisor.py` (`run_supervisor` 시그니처·본문)
- Test: `tests/unit/test_job_family_guard.py`

- [ ] **Step 1: 실패 테스트 작성**

Create `tests/unit/test_job_family_guard.py`:
```python
# run_supervisor 직군 검증 — 유효하지 않은 직군이면 그래프 실행 없이 에러
from src.agent.supervisor import run_supervisor


class _FakeGraph:
    def __init__(self):
        self.invoked = False

    def invoke(self, *args, **kwargs):
        self.invoked = True
        return {"final_report": {"gap": {}}}


class _FakeNeo4j:
    def list_job_families(self):
        return ["AI/LLM Engineer", "Software Engineer"]


def test_invalid_job_family_blocks():
    g = _FakeGraph()
    out = run_supervisor(g, job_family="AI Engineer", owner="X",
                         resume_skills=["Python"], neo4j=_FakeNeo4j())
    assert out["error"] == "invalid_job_family"
    assert "Software Engineer" in out["message"]
    assert g.invoked is False


def test_valid_job_family_runs():
    g = _FakeGraph()
    run_supervisor(g, job_family="Software Engineer", owner="X",
                   resume_skills=["Python"], neo4j=_FakeNeo4j())
    assert g.invoked is True


def test_no_neo4j_skips_validation():
    # neo4j 미제공 시 검증 스킵 (gap_analysis 백스톱에 위임)
    g = _FakeGraph()
    run_supervisor(g, job_family="아무직군", owner="X", resume_skills=["Python"])
    assert g.invoked is True
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/unit/test_job_family_guard.py -v`
Expected: FAIL (`run_supervisor`에 `neo4j` 인자 없음 → TypeError)

- [ ] **Step 3: 구현 — neo4j 파라미터 + 검증**

`src/agent/supervisor.py`의 `run_supervisor` 시그니처에 `neo4j` 추가:
```python
def run_supervisor(
    graph,
    job_family: str,
    owner: str,
    pdf_path: str | None = None,
    resume_text: str | None = None,
    github_url: str | None = None,
    resume_skills: list[str] | None = None,
    neo4j=None,
) -> dict:
```

기존 입력 가드(`if not (resume_skills or pdf_path or resume_text or github_url):` 블록) **직후**에 직군 검증 추가:
```python
    # 직군 검증: 유효하지 않은 job_family면 그래프 실행 없이 안내 (LLM 환각 방지)
    if neo4j is not None:
        valid = neo4j.list_job_families()
        if valid and job_family not in valid:
            return {
                "error": "invalid_job_family",
                "message": f"유효하지 않은 직군 '{job_family}'. 가능: {', '.join(valid)}",
                "valid_job_families": valid,
            }
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/unit/test_job_family_guard.py -v`
Expected: 3 passed

- [ ] **Step 5: 커밋**

```bash
git add src/agent/supervisor.py tests/unit/test_job_family_guard.py
git commit -m "feat(agent): run_supervisor 직군명 검증 — 유효목록 대조 fail-fast"
```

---

## Task 5: 통합 스모크 + progress

- [ ] **Step 1: 전체 단위 테스트**

Run: `python -m pytest tests/ -q -k "not test_returns_dict"`
Expected: 전부 통과 (기존 98 + 신규 테스트).

- [ ] **Step 2: 실제 데이터 스모크 (Neo4j Resume 필요)**

Neo4j Aura가 켜져 있어야 함. Run:
```bash
python -c "
from dotenv import load_dotenv
load_dotenv('/Users/leegahee/workspace/pj1/.env', override=True)
import os
from openai import OpenAI
from src.storage.neo4j_client import Neo4jClient
from src.agent.evaluators.resume_eval import create_resume_evaluator
from src.agent.evaluators.github_eval import create_github_evaluator
from src.agent.consensus import build_consensus
neo4j = Neo4jClient()
resume = create_resume_evaluator(OpenAI(api_key=os.getenv('OPENAI_API_KEY')))
gh = create_github_evaluator(neo4j)
state = {'resume_skills': [], 'pdf_path': '1_F-Lab_수료생_카카오합격자_이력서.pdf',
         'resume_text': None, 'github_url': 'https://github.com/f-lab-edu/food-delivery',
         'job_family': 'Software Engineer'}
r = resume(state); g = gh(state)
print('RESUME:', sorted({s['skill'] for s in r['resume_eval']['skills']}))
print('GITHUB:', sorted({s['skill'] for s in g['github_eval']['skills']}))
con = build_consensus([r['resume_eval'], g['github_eval']])
print('CONSENSUS:', {k: v['verification'] for k, v in con.items()})
"
```
Expected: 예외 없이 완료. RESUME에 Java·Spring·Redis 등 백엔드 스킬 포함(잘림 제거 효과). GITHUB에 Software Engineer 직군 스킬 중 레포에서 확인된 것(예: Java, Docker) 포함. CONSENSUS에 일부 Verified.

- [ ] **Step 3: progress.md 갱신 + 커밋**

`progress.md`에 `## [2026-06-12] 직무 무관 스킬 추출 범용화` 섹션 추가 (작업 절차 / 발생 문제 / 해결·검증 3단). 그 후:
```bash
git add progress.md
git commit -m "docs: 직무 무관 스킬 추출 범용화 진행 기록"
```

---

## Self-Review

**Spec coverage:** 설계 구성요소1(이력서 잘림)→Task 1, 구성요소2(GitHub 직군 사전)→Task 2·3, 구성요소3(직군 검증)→Task 2(list_job_families)·Task 4. 데이터흐름·테스트 전략 반영. ✅

**Placeholder scan:** 각 코드 step에 완전 코드. "적절히/등등" 없음. ✅

**Type consistency:** `_skills_from_sources(owner,repo,lang_text,readme_text,manifest_text,vocab)` 시그니처가 Task 3 구현·테스트에서 일치. `get_job_family_skills(job_family)->list[str]`·`list_job_families()->list[str]`가 Task 2 정의·Task 3·4 사용에서 일치. `create_github_evaluator(neo4j)`가 Task 3·supervisor 호출부에서 일치. `run_supervisor(..., neo4j=None)`가 Task 4 정의·테스트에서 일치. ✅

**알려진 의존:** Task 5 스모크는 Neo4j Aura 가동 필요. `_SKILL_KEYWORDS`는 `boost_confidence_from_github`가 계속 쓰므로 미삭제(github_eval에서 import만 제거). 비범위(synthesizer 결정성·Backend 직군 분리·분야 추천)는 이 계획에 없음.
