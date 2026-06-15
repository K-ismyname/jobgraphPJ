# GitHub 평가자 프로젝트 이해 강화 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** github_eval이 repo별로 README·설명·구조·의존성을 LLM으로 읽어 프로젝트 프로필(summary·tech_stack·observations)을 생성하고, 반환에 `profiles`를 추가한다.

**Architecture:** 프로필 생성은 모듈 함수 `_profile_one`(openai 주입, 단위 테스트 가능)으로 분리. `_eval_one`은 데이터를 수집해 검증용 스킬(기존 vocab 매칭)과 프로필을 함께 반환. `evaluate`가 repo별로 모아 `{skills, profiles}` 반환. consensus는 `skills`만 쓰므로 무변경.

**Tech Stack:** Python, GitHub API(httpx), OpenAI(gpt-4o-mini), pytest.

---

## File Structure

- `src/agent/evaluators/github_eval.py` — `_profile_one`(신규 모듈 함수), `_eval_one`·`evaluate`·`create_github_evaluator` 수정(openai 주입, profiles 반환).
- `src/agent/supervisor.py:131` — `create_github_evaluator`에 openai 전달.
- `tests/unit/test_github_eval.py` — `_profile_one` 단위 테스트 추가 + `create_github_evaluator` 호출에 openai 인자.

---

### Task 1: `_profile_one` 프로필 생성 함수

**Files:**
- Modify: `src/agent/evaluators/github_eval.py`
- Test: `tests/unit/test_github_eval.py`

- [ ] **Step 1: 단위 테스트 추가**

`tests/unit/test_github_eval.py` 끝에 추가:
```python
import types
from src.agent.evaluators.github_eval import _profile_one


def _fake_openai(content):
    resp = types.SimpleNamespace(
        choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=content))])
    return types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=lambda **k: resp)))


def test_profile_one_parses_llm_json():
    oa = _fake_openai('{"summary":"RAG 챗봇","tech_stack":["Python","FastAPI"],"observations":["Dockerfile 없음"]}')
    p = _profile_one(oa, "me", "proj", "readme", "desc", ["llm"], ["main.py"], "fastapi")
    assert p["repo"] == "me/proj"
    assert p["summary"] == "RAG 챗봇"
    assert p["tech_stack"] == ["Python", "FastAPI"]
    assert p["observations"] == ["Dockerfile 없음"]


def test_profile_one_no_openai_returns_empty():
    p = _profile_one(None, "me", "proj", "", "", [], [], "")
    assert p == {"repo": "me/proj", "summary": "", "tech_stack": [], "observations": []}


def test_profile_one_bad_json_returns_empty():
    p = _profile_one(_fake_openai("not json"), "me", "proj", "r", "d", [], [], "")
    assert p == {"repo": "me/proj", "summary": "", "tech_stack": [], "observations": []}
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/unit/test_github_eval.py -q`
Expected: FAIL — `ImportError: cannot import name '_profile_one'`.

- [ ] **Step 3: `_profile_one` 구현**

`src/agent/evaluators/github_eval.py` 상단에 `import json` 추가(없으면). `create_github_evaluator` 정의 **앞**(모듈 레벨)에 추가:
```python
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
        '"tech_stack": ["사용 기술"], '
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
```

- [ ] **Step 4: 통과 확인 + 커밋**

Run: `pytest tests/unit/test_github_eval.py::test_profile_one_parses_llm_json tests/unit/test_github_eval.py::test_profile_one_no_openai_returns_empty tests/unit/test_github_eval.py::test_profile_one_bad_json_returns_empty -q`
Expected: 3개 PASS.
```bash
git add src/agent/evaluators/github_eval.py tests/unit/test_github_eval.py
git commit -m "feat(agent): github_eval _profile_one — repo 정보로 프로젝트 프로필 LLM 생성"
```

---

### Task 2: `_eval_one`·`evaluate`·factory에 프로필 통합

**Files:**
- Modify: `src/agent/evaluators/github_eval.py`, `src/agent/supervisor.py`
- Test: `tests/unit/test_github_eval.py`

- [ ] **Step 1: 기존 테스트의 factory 호출에 openai 인자 추가**

`tests/unit/test_github_eval.py`의 `create_github_evaluator(_FakeNeo4j(...))` 4곳을 `create_github_evaluator(_FakeNeo4j(...), None)`로 바꾼다(20·26·32·38행 근처). 단언(`skills == []`)은 그대로.

- [ ] **Step 2: `create_github_evaluator` 교체 (openai 주입 + 데이터 수집 확장 + profiles 반환)**

`src/agent/evaluators/github_eval.py:89-163`을 교체:
```python
def create_github_evaluator(neo4j: "Neo4jClient", openai=None) -> Callable[["AppState"], dict]:
    """GitHub 평가자 팩토리. 검증용 스킬(vocab 매칭) + repo별 프로젝트 프로필(LLM)."""
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
```

- [ ] **Step 3: `supervisor.py`에서 openai 전달**

`src/agent/supervisor.py:131`을 교체:
```python
    github_eval = create_github_evaluator(neo4j, openai_client)
```

- [ ] **Step 4: 전체 github_eval 테스트 + import 확인**

Run: `pytest tests/unit/test_github_eval.py -q`
Expected: 전부 PASS (기존 스킬 가드 + 프로필 단위 테스트).

Run: `python -c "from src.agent.supervisor import create_supervisor_graph; print('ok')"`
Expected: `ok`.

- [ ] **Step 5: 커밋**

```bash
git add src/agent/evaluators/github_eval.py src/agent/supervisor.py tests/unit/test_github_eval.py
git commit -m "feat(agent): github_eval이 repo별 프로젝트 프로필 반환 — README·설명·구조 종합"
```

---

### Task 3: 통합 검증

**Files:** (없음 — 검증 전용)

- [ ] **Step 1: 전체 단위 테스트**

Run: `pytest tests/unit/ -q`
Expected: 전부 PASS.

- [ ] **Step 2: 실제 repo로 프로필 생성 확인 (수동)**

서버를 빈 포트로 띄우고, 분석 시 GitHub URL을 넣어 실행한 뒤 trace/state에서 `github_eval.profiles`를 확인하거나, 아래 스니펫으로 직접 확인:
```bash
python -c "
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path('.env').resolve(), override=True)
from openai import OpenAI
from src.storage.neo4j_client import Neo4jClient
from src.agent.evaluators.github_eval import create_github_evaluator
ev = create_github_evaluator(Neo4jClient(), OpenAI())
out = ev({'github_urls': ['https://github.com/K-ismyname/jobgraphPJ'], 'job_family': 'AI/LLM Engineer'})
import json; print(json.dumps(out['github_eval']['profiles'], ensure_ascii=False, indent=2))
"
```
Expected: repo의 `summary`·`tech_stack`·`observations`가 채워진 프로필 출력.

- [ ] **Step 3: 결과 판단**

프로필이 프로젝트를 제대로 파악하면(요약·기술·빠진 것) 완료. 부실하면 `_profile_one` 프롬프트를 조정한다. 이후 2단계(coach 재설계)로 진행.
