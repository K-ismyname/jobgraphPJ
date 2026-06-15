# 다중 GitHub/배포 URL 입력 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** GitHub URL과 배포 URL을 "+ 추가" 버튼으로 여러 개 입력받아 각각 검증하고 스킬을 합집합으로 모은다. 단수 필드를 전 계층에서 복수로 교체한다.

**Architecture:** `github_url`/`deploy_url`(단수)을 `github_urls`/`deploy_urls`(list)로 state·schema·signature 전반에서 교체. 평가자는 노드 내부에서 URL들을 순회해 스킬을 합친다(중복 제거). 프론트는 입력칸을 동적 추가하고 배열로 전송한다.

**Tech Stack:** Python(LangGraph state·evaluators·FastAPI), 정적 JS, pytest.

---

## File Structure

- `src/agent/state.py` — `github_urls`/`deploy_urls: list[str]`.
- `src/agent/supervisor.py` — `evaluator_dispatch`, `run_supervisor` 시그니처·initial·입력가드·데모(343).
- `src/agent/evaluators/github_eval.py` — URL 순회.
- `src/agent/evaluators/deploy_eval.py` — URL 순회.
- `src/api/schemas.py` — `AnalyzeRequest` 복수.
- `src/api/routers/portfolio.py` — `_run_analysis`·`run_supervisor` 호출·`add_task`.
- `web/index.html`, `web/app.js`, `web/style.css` — 입력칸 추가 UI + 배열 전송.
- 테스트: `test_api_schemas`·`test_evaluator_dispatch`·`test_github_eval`·`test_deploy_eval`·`test_input_guard` 갱신.

**중복 제거 규칙:** 평가자 `skills`는 `[{"skill": name, ...}]` 형태이므로 `s.get("skill")`를 키로 합집합.

---

### Task 1: state + schema 복수화

**Files:**
- Modify: `src/agent/state.py`, `src/api/schemas.py`
- Test: `tests/unit/test_api_schemas.py`

- [ ] **Step 1: `test_api_schemas.py` 갱신(실패 유도)**

`tests/unit/test_api_schemas.py:6-11`을 교체:
```python
    req = AnalyzeRequest(report_id="r1", job_family="Software Engineer",
                         github_urls=["https://github.com/x/y"], deploy_urls=["https://x.com"])
    assert req.github_urls == ["https://github.com/x/y"] and req.deploy_urls == ["https://x.com"]
    req2 = AnalyzeRequest(report_id="r1", job_family="Software Engineer")
    assert req2.github_urls == [] and req2.deploy_urls == []
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/unit/test_api_schemas.py -q`
Expected: FAIL (`github_urls`는 아직 없는 필드).

- [ ] **Step 3: `schemas.py` 교체**

`src/api/schemas.py:30-31` 교체:
```python
    github_urls: list[str] = Field(default_factory=list)   # 선택 — 코드 검증 (여러 개)
    deploy_urls: list[str] = Field(default_factory=list)   # 선택 — 작동 실증 (여러 개)
```

- [ ] **Step 4: `state.py` 교체**

`src/agent/state.py:26-27` 교체:
```python
    github_urls: list[str]
    deploy_urls: list[str]       # 배포 URL 목록 (작동 실증 평가자 입력)
```

- [ ] **Step 5: 통과 확인 + 커밋**

Run: `pytest tests/unit/test_api_schemas.py -q`
Expected: PASS.
```bash
git add src/agent/state.py src/api/schemas.py tests/unit/test_api_schemas.py
git commit -m "refactor(api): github/deploy URL을 복수 필드로 — state·schema"
```

---

### Task 2: evaluator_dispatch 복수화

**Files:**
- Modify: `src/agent/supervisor.py`
- Test: `tests/unit/test_evaluator_dispatch.py`

- [ ] **Step 1: `test_evaluator_dispatch.py` 갱신(실패 유도)**

`tests/unit/test_evaluator_dispatch.py`에서 `github_url`/`deploy_url` 키를 복수로 바꾼다. 각 호출의 dict를:
- `"github_url": None` → `"github_urls": []`
- `"github_url": "https://github.com/x"` → `"github_urls": ["https://github.com/x"]`
- `"deploy_url": None` → `"deploy_urls": []`
- `"deploy_url": "https://x.com"` → `"deploy_urls": ["https://x.com"]`

(6·12·18·24·31·33행의 dict 키. 단언은 그대로 — `github_eval`/`deploy_eval` 노드명은 불변.)

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/unit/test_evaluator_dispatch.py -q`
Expected: FAIL (dispatch가 아직 단수 키 `github_url`을 봄 → github 미dispatch).

- [ ] **Step 3: `evaluator_dispatch` 교체**

`src/agent/supervisor.py:101-106`의 두 분기를 교체:
```python
    if state.get("github_urls"):
        sends.append(Send("github_eval", state))
    if state.get("portfolio_path"):
        sends.append(Send("portfolio_eval", state))
    if state.get("deploy_urls"):
        sends.append(Send("deploy_eval", state))
```

- [ ] **Step 4: 통과 확인 + 커밋**

Run: `pytest tests/unit/test_evaluator_dispatch.py -q`
Expected: PASS.
```bash
git add src/agent/supervisor.py tests/unit/test_evaluator_dispatch.py
git commit -m "refactor(agent): evaluator_dispatch를 복수 URL 키로"
```

---

### Task 3: github_eval URL 순회

**Files:**
- Modify: `src/agent/evaluators/github_eval.py`
- Test: `tests/unit/test_github_eval.py`

- [ ] **Step 1: `test_github_eval.py` 갱신(실패 유도)**

22·28·34·40행의 `"github_url": X`를 `"github_urls": [...]`로:
- `"github_url": None` → `"github_urls": []`
- `"github_url": "not-a-url"` → `"github_urls": ["not-a-url"]`
- `"github_url": "https://github.com/fastapi"` → `"github_urls": ["https://github.com/fastapi"]`
- `"github_url": "https://github.com/x/y"` → `"github_urls": ["https://github.com/x/y"]`

(단언 `skills == []` 그대로.)

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/unit/test_github_eval.py -q`
Expected: 일부 FAIL (evaluate가 아직 `github_url` 단일을 봄).

- [ ] **Step 3: `create_github_evaluator` 교체**

`src/agent/evaluators/github_eval.py:89-153` 전체를 교체. 단일 URL 처리를 `_eval_one`으로 분리하고, `evaluate`가 `github_urls`를 순회해 합집합한다(vocab는 직군 단위라 한 번만 조회).

```python
def create_github_evaluator(neo4j: "Neo4jClient") -> Callable[["AppState"], dict]:
    """GitHub 평가자 팩토리. 대상 직군의 스킬 집합을 레포 코드 근거로 검증한다."""
    def _eval_one(url: str, vocab) -> list:
        try:
            owner, repo = parse_github_repo(url)
        except ValueError as e:
            print(f"[github_eval] URL 파싱 실패: {e}")
            return []
        if not repo:
            print(f"[github_eval] 레포 미지정 (계정 주소만): {url}")
            return []

        token = os.getenv("GITHUB_TOKEN")
        headers = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        raw_headers = {**headers, "Accept": "application/vnd.github.raw"}
        base = f"https://api.github.com/repos/{owner}/{repo}"

        try:
            lang_resp = httpx.get(f"{base}/languages", headers=headers, timeout=10)
            lang_resp.raise_for_status()
            languages = lang_resp.json()
        except Exception as e:
            print(f"[github_eval] GitHub API 실패: {e}")
            return []
        lang_text = " ".join(languages.keys())

        readme_text = ""
        try:
            rd = httpx.get(f"{base}/readme", headers=raw_headers, timeout=10)
            if rd.status_code == 200:
                readme_text = rd.text
        except Exception as e:
            print(f"[github_eval] README 조회 실패: {e}")

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

        return _skills_from_sources(owner, repo, lang_text, readme_text, manifest_text, vocab)

    def evaluate(state: "AppState") -> dict:
        urls = state.get("github_urls") or []
        if not urls:
            return {"github_eval": {"skills": []}}
        vocab = neo4j.get_job_family_skills(state.get("job_family") or "")
        if not vocab:
            print(f"[github_eval] 직군 스킬 어휘 없음 (job_family={state.get('job_family')!r})")
            return {"github_eval": {"skills": []}}
        merged: list = []
        seen: set = set()
        for url in urls:
            for s in _eval_one(url, vocab):
                key = s.get("skill") if isinstance(s, dict) else s
                if key not in seen:
                    seen.add(key)
                    merged.append(s)
        return {"github_eval": {"skills": merged}}

    return evaluate
```

- [ ] **Step 4: 통과 확인 + 커밋**

Run: `pytest tests/unit/test_github_eval.py -q`
Expected: PASS.
```bash
git add src/agent/evaluators/github_eval.py tests/unit/test_github_eval.py
git commit -m "feat(agent): github_eval이 여러 레포 URL을 순회해 스킬 합집합"
```

---

### Task 4: deploy_eval URL 순회

**Files:**
- Modify: `src/agent/evaluators/deploy_eval.py`
- Test: `tests/unit/test_deploy_eval.py`

- [ ] **Step 1: `test_deploy_eval.py` 갱신(실패 유도)**

19행 `"deploy_url": None` → `"deploy_urls": []`.

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/unit/test_deploy_eval.py -q`
Expected: FAIL 또는 통과(단일 키 무시) — `evaluate`가 `deploy_url`을 봐서 None이어도 빈 반환이라 통과할 수 있음. Step 3 후 복수 키로 동작 확인이 핵심.

- [ ] **Step 3: `create_deploy_evaluator` 교체**

`src/agent/evaluators/deploy_eval.py:39-60` 전체를 교체:
```python
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
```

- [ ] **Step 4: 통과 확인 + 커밋**

Run: `pytest tests/unit/test_deploy_eval.py -q`
Expected: PASS.
```bash
git add src/agent/evaluators/deploy_eval.py tests/unit/test_deploy_eval.py
git commit -m "feat(agent): deploy_eval이 여러 배포 URL을 순회해 스킬 합집합"
```

---

### Task 5: run_supervisor 시그니처 + portfolio 라우터

**Files:**
- Modify: `src/agent/supervisor.py`, `src/api/routers/portfolio.py`
- Test: `tests/unit/test_input_guard.py`

- [ ] **Step 1: `test_input_guard.py:32` 갱신**

`github_url="https://github.com/x"` → `github_urls=["https://github.com/x"]`.

- [ ] **Step 2: `run_supervisor` 시그니처·가드·initial 교체**

`src/agent/supervisor.py`에서:
- `:212` `github_url: str | None = None,` → `github_urls: list[str] | None = None,`
- `:215` `deploy_url: str | None = None,` → `deploy_urls: list[str] | None = None,`
- `:227` 입력 가드의 `github_url ... deploy_url` →
  ```python
    if not (resume_skills or pdf_path or resume_text or github_urls or portfolio_path or deploy_urls):
  ```
- `:249-250` initial state →
  ```python
        "deploy_urls": deploy_urls or [],
        "github_urls": github_urls or [],
  ```
- `:343` 데모 호출은 github/deploy 인자 없음 → 변경 불필요(확인만).

- [ ] **Step 3: `portfolio.py` 3곳 교체**

`src/api/routers/portfolio.py`:
- `:90-91` `add_task`의 `github_url=req.github_url, deploy_url=req.deploy_url,` → `github_urls=req.github_urls, deploy_urls=req.deploy_urls,`
- `_run_analysis` 정의(약 :140)의 파라미터 `github_url: str | None, deploy_url: str | None,` → `github_urls: list[str], deploy_urls: list[str],`
- 그 본문의 `run_supervisor(..., github_url=github_url, deploy_url=deploy_url, ...)`(약 :146-148) → `github_urls=github_urls, deploy_urls=deploy_urls,`

(정확한 줄은 파일을 열어 확인 후 교체. `github_url`/`deploy_url` 문자열이 모두 사라져야 함.)

- [ ] **Step 4: 잔재 확인 + import + 단위 테스트**

Run: `grep -rn "github_url\b\|deploy_url\b" src/ | grep -v "_urls"`
Expected: (빈 출력) — 단수 참조 잔재 없음.

Run: `python -c "from src.api.main import app; print('ok')"`
Expected: `ok`.

Run: `pytest tests/unit/ -q`
Expected: 전부 PASS.

- [ ] **Step 5: 커밋**

```bash
git add src/agent/supervisor.py src/api/routers/portfolio.py tests/unit/test_input_guard.py
git commit -m "refactor(agent): run_supervisor·portfolio를 복수 URL로"
```

---

### Task 6: 프론트 입력칸 추가 UI

**Files:**
- Modify: `web/index.html`, `web/app.js`, `web/style.css`

- [ ] **Step 1: `index.html` 분석 조건의 URL 블록 교체**

`web/index.html`의 `step-analyze` 안에서 GitHub/배포 `<label>` 두 개를 아래로 교체한다. 첫 입력칸은 `id="github-url"`/`id="deploy-url"`을 **유지**한다(기존 구조 회귀 테스트 보존).

```html
      <label>GitHub URL (선택, 여러 개 가능)</label>
      <div id="github-urls">
        <div class="url-row"><input type="url" id="github-url" placeholder="https://github.com/owner/repo"></div>
      </div>
      <button type="button" id="add-github" class="add-btn">+ GitHub 추가</button>

      <label>배포 URL (선택, 여러 개 가능)</label>
      <div id="deploy-urls">
        <div class="url-row"><input type="url" id="deploy-url" placeholder="https://my-service.example.com"></div>
      </div>
      <button type="button" id="add-deploy" class="add-btn">+ 배포 추가</button>
```

- [ ] **Step 2: `app.js` 수집·추가 로직**

`web/app.js`의 `startAnalysis`에서 `body`의 url 두 줄(43-44)을 교체:
```javascript
    github_urls: collectUrls("github-urls"),
    deploy_urls: collectUrls("deploy-urls"),
```

그리고 파일 끝(이벤트 바인딩부 근처)에 헬퍼와 버튼 핸들러를 추가:
```javascript
// URL 입력칸 수집·추가
function collectUrls(containerId) {
  return Array.from(document.querySelectorAll(`#${containerId} input`))
    .map((i) => i.value.trim()).filter(Boolean);
}
function addUrlField(containerId, placeholder) {
  const row = document.createElement("div");
  row.className = "url-row";
  const input = document.createElement("input");
  input.type = "url";
  input.placeholder = placeholder;
  const del = document.createElement("button");
  del.type = "button";
  del.className = "url-del";
  del.textContent = "×";
  del.addEventListener("click", () => row.remove());
  row.append(input, del);
  document.getElementById(containerId).appendChild(row);
}
$("add-github").addEventListener("click", () => addUrlField("github-urls", "https://github.com/owner/repo"));
$("add-deploy").addEventListener("click", () => addUrlField("deploy-urls", "https://my-service.example.com"));
```

- [ ] **Step 3: `style.css` 스타일 추가**

`web/style.css` 끝에 추가:
```css
/* ── 다중 URL 입력 ── */
.url-row { display:flex; gap:6px; margin-top:6px; }
.url-row input { flex:1; }
.url-del { margin-top:0; padding:0 12px; background:#fff; color:var(--muted); border:1px solid var(--line); }
.url-del:hover { color:#dc2626; border-color:#fecaca; }
.add-btn { margin-top:8px; padding:6px 12px; background:#fff; color:var(--accent);
  border:1px solid var(--accent); font-size:.85rem; }
```

- [ ] **Step 4: JS 문법 확인 + 커밋**

Run: `node --check web/app.js && echo ok`
Expected: `ok`.
```bash
git add web/index.html web/app.js web/style.css
git commit -m "feat(web): GitHub/배포 URL 다중 입력 — 추가/삭제 버튼"
```

---

### Task 7: 통합 검증

**Files:** (없음 — 검증 전용)

- [ ] **Step 1: 전체 단위 테스트**

Run: `pytest tests/unit/ -q`
Expected: 전부 PASS.

- [ ] **Step 2: 구조 회귀 (github-url/deploy-url id 보존)**

Run: `pytest tests/unit/test_homepage_structure.py -q`
Expected: PASS (첫 입력칸 id 유지).

- [ ] **Step 3: 서버 육안**

빈 포트로 서버 기동 후 `/`:
```bash
uvicorn src.api.main:app --port 8075 --log-level warning
```
- "+ GitHub 추가"/"+ 배포 추가"로 입력칸이 늘고, `×`로 삭제되는지.
- GitHub URL 2개 입력 후 분석 → 두 레포의 스킬이 결과에 합쳐 반영되는지(GITHUB_TOKEN 있으면 실검증, 없으면 빈 결과여도 흐름 정상).

- [ ] **Step 4: 서버 종료**

확인 끝나면 uvicorn 종료.
