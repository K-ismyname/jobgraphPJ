# 관측 페이지 개선 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 관측 페이지에서 데이터 탭과 `/stats`를 제거하고, 워크플로우 탭을 흐름 요약 띠 + 강조 다이어그램 + 수치 배지 카드로 재구성한다.

**Architecture:** 정적 프론트(`observe.html`/`observe.js`/`style.css`) 재구성이 핵심. 흐름 띠·배지 수치는 프론트가 `/portfolio/report/{id}`의 `trace`·`capability_fit`에서 계산하므로 백엔드 추가는 없고, orphan이 되는 `/stats` 풀스택만 제거한다. 프론트 JS는 pytest 대상이 아니라 구조 회귀 테스트(`observe.html` 문자열 검사) + 서버 육안으로 검증한다.

**Tech Stack:** 정적 HTML/CSS/JS, Mermaid.js(CDN), FastAPI(`/stats` 제거), pytest(구조 검증).

---

## File Structure

- `src/api/routers/stats.py` — 삭제(orphan).
- `src/api/main.py` — stats import·`include_router` 2줄 제거.
- `src/api/schemas.py` — `StatsResponse`·`JobFamilyStat` 제거.
- `tests/integration/test_stats.py` — 삭제.
- `web/observe.html` — 탭 UI·`panel-data` 제거.
- `web/observe.js` — 데이터 탭 로직 제거 + 워크플로우 재구성(흐름 띠·배지·다이어그램 dim).
- `web/style.css` — 흐름 띠·배지 스타일.
- `tests/unit/test_observe_structure.py` — 신규, 탭 제거·워크플로우 단독 회귀 가드.

---

### Task 1: `/stats` 백엔드 제거

**Files:**
- Delete: `src/api/routers/stats.py`, `tests/integration/test_stats.py`
- Modify: `src/api/main.py`, `src/api/schemas.py`

- [ ] **Step 1: stats가 다른 곳에서 안 쓰이는지 재확인**

Run: `grep -rn "StatsResponse\|JobFamilyStat\|stats_router\|routers import stats\|routers.stats" src/ tests/`
Expected: `main.py`(import·include 2줄), `schemas.py`(클래스 정의), `routers/stats.py`(자기 자신), `test_stats.py`만 등장. 다른 호출처 없음.

- [ ] **Step 2: 파일 2개 삭제**

```bash
git rm src/api/routers/stats.py tests/integration/test_stats.py
```

- [ ] **Step 3: `main.py`에서 stats 라우터 제거**

`src/api/main.py:21`의 import 줄과 `:59`의 include 줄을 삭제한다.

삭제할 줄:
```python
from src.api.routers import stats as stats_router
```
```python
app.include_router(stats_router.router, prefix="/stats", tags=["stats"])
```

- [ ] **Step 4: `schemas.py`에서 stats 스키마 제거**

`src/api/schemas.py` 끝의 아래 블록(`# ── Stats Response ──` 주석 포함)을 통째로 삭제한다.

```python
# ── Stats Response ───────────────────────────────────────────────
class JobFamilyStat(BaseModel):
    name: str
    posting_count: int
    skill_count: int


class StatsResponse(BaseModel):
    job_families: list[JobFamilyStat]
    totals: dict[str, int]          # postings, skills, relations
```

- [ ] **Step 5: 서버가 import 에러 없이 뜨고 `/stats`가 404인지 확인**

Run:
```bash
python -c "from src.api.main import app; print('import ok')"
```
Expected: `import ok` (stats 참조가 모두 제거돼 ImportError 없음).

Run: `pytest tests/unit/ -q`
Expected: 전부 PASS (stats는 integration이라 unit 무관, import 깨짐 없음).

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor(api): /stats 제거 — 관측 데이터 탭 폐지로 orphan 정리"
```

---

### Task 2: 데이터 탭 제거 + 구조 회귀 가드

**Files:**
- Modify: `web/observe.html`, `web/observe.js`
- Create: `tests/unit/test_observe_structure.py`

- [ ] **Step 1: 구조 회귀 테스트 작성**

`observe.html`이 워크플로우 단독(탭 없음, 데이터 패널 없음)인지 검사한다.

```python
# observe.html이 데이터 탭 제거 후 워크플로우 단독 구조인지 검사하는 회귀 가드
from pathlib import Path

HTML = (Path(__file__).resolve().parents[2] / "web" / "observe.html").read_text(encoding="utf-8")


def test_workflow_panel_present():
    assert 'id="workflow"' in HTML


def test_data_tab_removed():
    assert 'id="tab-data"' not in HTML
    assert 'id="panel-data"' not in HTML
    assert 'class="tabs"' not in HTML
```

- [ ] **Step 2: Run test — 실패 확인**

Run: `pytest tests/unit/test_observe_structure.py -v`
Expected: `test_data_tab_removed` FAIL (아직 탭이 있음), `test_workflow_panel_present` PASS.

- [ ] **Step 3: `observe.html` 탭 제거**

`web/observe.html`의 `<body>` 내부를 아래로 교체한다(탭 div·panel-data 삭제, 헤더 문구 수정).

```html
<body>
  <main>
    <header>
      <h1>관측 (Observability)</h1>
      <p class="sub">분석 <b>워크플로우</b>가 어떻게 도는지 봅니다. <a href="/">← 분석으로</a></p>
    </header>
    <section id="panel-workflow" class="card"><div id="workflow"></div></section>
  </main>
  <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
  <script src="/web/observe.js"></script>
</body>
```

- [ ] **Step 4: `observe.js`에서 데이터 탭 로직 제거**

`web/observe.js`의 탭 전환부와 데이터 탭 로직을 제거한다. 8~17행의 `showTab` 함수와 탭 이벤트 리스너 블록, 그리고 90~118행의 데이터 탭 블록(`let dataLoaded`부터 `showTab(initTab);`까지)을 삭제하고, 진입부를 `loadWorkflow()` 직접 호출로 바꾼다.

제거할 블록 1 (탭 전환):
```javascript
// 탭 전환
function showTab(name) {
  const wf = name === "workflow";
  $("panel-workflow").classList.toggle("hidden", !wf);
  $("panel-data").classList.toggle("hidden", wf);
  $("tab-workflow").classList.toggle("active", wf);
  $("tab-data").classList.toggle("active", !wf);
  if (wf) loadWorkflow(); else loadData();
}
$("tab-workflow").addEventListener("click", () => showTab("workflow"));
$("tab-data").addEventListener("click", () => showTab("data"));
```

제거할 블록 2 (데이터 탭 + 진입부): 파일 끝의 `// ── 데이터 탭 ──` 주석부터 `showTab(initTab);`까지 전체.

추가할 진입부(파일 끝):
```javascript
// 진입 시 워크플로우 로드
loadWorkflow();
```

- [ ] **Step 5: Run test — 통과 확인**

Run: `pytest tests/unit/test_observe_structure.py -v`
Expected: 3개 PASS.

- [ ] **Step 6: Commit**

```bash
git add web/observe.html web/observe.js tests/unit/test_observe_structure.py
git commit -m "feat(web): 관측 데이터 탭 제거 — 워크플로우 단독 화면"
```

---

### Task 3: 워크플로우 재구성 — 흐름 띠 + 배지 + 다이어그램 dim

**Files:**
- Modify: `web/observe.js`

- [ ] **Step 1: 흐름 요약·배지 계산 함수 추가**

`web/observe.js`의 `esc` 정의 다음 줄에 두 헬퍼를 추가한다. 모두 `report.trace`·`report.capability_fit`에서 계산한다.

```javascript
// report.trace에서 단계별 데이터 변화를 한 줄 요약
function flowSummary(report) {
  const t = report.trace || {};
  const extracted = new Set((t.evaluators || []).flatMap((e) => (e.skills || []).map((s) => s.skill))).size;
  const cons = (t.consensus && t.consensus.skills) || [];
  const verified = cons.filter((s) => s.verification === "Verified").length;
  const cf = report.capability_fit || {};
  const met = (cf.met || []).length, unmet = (cf.unmet || []).length;
  const corrected = (t.critic && t.critic.corrected) || 0;
  const suggestions = (t.coach && t.coach.suggestion_count) || 0;
  return `스킬 ${extracted} 추출 → 합의 ${cons.length}(Verified ${verified}) → 부족 역량 ${unmet} → 적합도 ${met}/${met + unmet} → 교정 ${corrected} → 제안 ${suggestions}`;
}

// 단계 카드 헤더용 수치 배지 목록
function stageBadges(key, report) {
  const t = report.trace || {};
  if (key === "evaluators") {
    const ev = t.evaluators || [];
    const sk = new Set(ev.flatMap((e) => (e.skills || []).map((s) => s.skill))).size;
    return [`소스 ${ev.length}`, `스킬 ${sk}`];
  }
  if (key === "consensus") {
    const c = (t.consensus && t.consensus.skills) || [];
    const cnt = (v) => c.filter((s) => s.verification === v).length;
    return [`Verified ${cnt("Verified")}`, `Corroborated ${cnt("Corroborated")}`, `Claimed ${cnt("Claimed")}`];
  }
  if (key === "gap_loop") {
    const g = t.gap_loop || {};
    return [`반복 ${g.iterations || 0}회`, `도구 ${(g.tool_calls || []).length}`];
  }
  if (key === "fit") {
    const cf = report.capability_fit || {};
    const m = (cf.met || []).length, u = (cf.unmet || []).length;
    return [`적합도 ${m}/${m + u}`];
  }
  if (key === "critic") {
    const cr = t.critic || {};
    return [`제거 ${(cr.removed_skills || []).length}`, `교정 ${cr.corrected || 0}`];
  }
  if (key === "coach") return [`제안 ${(t.coach && t.coach.suggestion_count) || 0}`];
  return [];
}
```

- [ ] **Step 2: `renderWorkflow` 교체 — 흐름 띠 + 다이어그램 dim**

기존 `renderWorkflow` 함수를 아래로 교체한다. 흐름 띠를 맨 위에 두고, 미실행 노드를 dim 처리한다(`g.stages`의 `nodes` 합집합에서 `executed_nodes`를 뺀 것).

```javascript
async function renderWorkflow(g, report) {
  // 흐름 요약 띠
  let band = "";
  if (report && report.trace) {
    band = `<div class="flow-band">${esc(flowSummary(report))}</div>`;
  } else {
    band = `<div class="flow-band muted">분석을 실행하면 실제 데이터 흐름이 채워집니다.</div>`;
  }

  // 다이어그램 (실행 경로 강조 + 미실행 dim)
  let diagram = "";
  if (g.mermaid && window.mermaid) {
    let src = g.mermaid;
    const ex = (report && report.trace && report.trace.executed_nodes) || [];
    if (ex.length) {
      const allNodes = (g.stages || []).flatMap((s) => s.nodes || []);
      const dim = allNodes.filter((n) => !ex.includes(n));
      src += "\n" + ex.map((n) => `class ${n} executed;`).join("\n");
      if (dim.length) src += "\n" + dim.map((n) => `class ${n} dimmed;`).join("\n");
      src += "\nclassDef executed fill:#4f46e5,color:#fff,stroke:#4f46e5,stroke-width:2px;";
      src += "\nclassDef dimmed fill:#f3f4f6,color:#9ca3af,stroke:#e5e7eb;";
    }
    try {
      const { svg } = await mermaid.render("wfgraph", src);
      diagram = `<div class="diagram">${svg}</div>`;
    } catch (e) {
      diagram = "<p class='prio'>다이어그램 로드 실패</p>";
    }
  }

  const cards = (g.stages || []).map((st) => renderStage(st, report)).join("");
  $("workflow").innerHTML = band + diagram + cards;
}
```

- [ ] **Step 3: `renderStage` 교체 — 수치 배지 헤더**

기존 `renderStage`를 아래로 교체한다. report가 있으면 헤더에 배지를 붙인다.

```javascript
function renderStage(st, report) {
  const t = report && report.trace;
  const badges = (report && t)
    ? stageBadges(st.key, report).map((b) => `<span class="badge-num">${esc(b)}</span>`).join("")
    : "";
  let data = "<div class='cap-ev'>분석하면 이 단계의 실제 처리 결과가 표시됩니다.</div>";
  if (report && t) data = `<div class="stage-data">${stageData(st.key, t, report)}</div>`;
  return `<div class="step"><h4>${esc(st.title)} ${badges}</h4><p class="cap-ev">${esc(st.description)}</p>${data}</div>`;
}
```

- [ ] **Step 4: 서버로 동작 확인 (수동)**

비어있는 포트로 서버를 띄우고 `/observe` 및 `/observe?report_id=<있으면>`를 연다.

```bash
uvicorn src.api.main:app --port 8073 --log-level warning
```
Expected: report 없이는 흐름 띠 자리에 "분석을 실행하면…" 안내 + 다이어그램 + 설명 카드. report 있으면 흐름 띠 채워지고, 다이어그램에서 미실행 노드가 흐리게, 카드 헤더에 배지 표시.

- [ ] **Step 5: Commit**

```bash
git add web/observe.js
git commit -m "feat(web): 관측 워크플로우 — 흐름 요약 띠 + 수치 배지 + 미실행 노드 dim"
```

---

### Task 4: 흐름 띠·배지 스타일

**Files:**
- Modify: `web/style.css`

- [ ] **Step 1: 파일 끝에 스타일 추가**

`web/style.css` 맨 끝에 아래를 덧붙인다.

```css
/* ── 관측 흐름 띠·배지 ── */
.flow-band { background:var(--bg-accent); border:1px solid var(--line); border-radius:10px;
  padding:12px 14px; margin-bottom:16px; font-size:.9rem; font-weight:600; color:var(--accent);
  overflow-x:auto; white-space:nowrap; }
.flow-band.muted { background:#fff; color:var(--muted); font-weight:400; }
.badge-num { display:inline-block; margin-left:6px; padding:1px 8px; border-radius:999px;
  background:#eef2ff; color:var(--accent); font-size:.72rem; font-weight:600; vertical-align:middle; }
```

- [ ] **Step 2: 스타일 적용 육안 확인**

Task 3 Step 4의 서버에서 하드 리프레시(`Cmd+Shift+R`) 후: 흐름 띠가 연보라 박스로, 카드 헤더 배지가 둥근 연보라 칩으로 보이는지 확인.

- [ ] **Step 3: Commit**

```bash
git add web/style.css
git commit -m "feat(web): 관측 흐름 띠·수치 배지 스타일"
```

---

### Task 5: 통합 검증

**Files:** (없음 — 검증 전용)

- [ ] **Step 1: 전체 단위 테스트**

Run: `pytest tests/unit/ -q`
Expected: 전부 PASS (홈페이지 구조 + observe 구조 테스트 포함).

- [ ] **Step 2: 서버 라우트 확인**

서버 기동 후:
```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8073/stats
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8073/observe
```
Expected: `/stats` → 404, `/observe` → 200.

- [ ] **Step 3: 육안 — 분석 전/후 두 상태**

- report 없이 `/observe`: 탭 없음, 흐름 띠 안내 문구, 다이어그램 + 설명 카드.
- 실제 분석을 한 번 돌려 `/observe?report_id=<id>`: 흐름 띠 수치, 미실행 노드 dim, 배지 카드. (분석은 `/` 에서 PDF 업로드→분석으로 생성)

- [ ] **Step 4: 서버 종료**

확인 끝나면 uvicorn 종료.
