# 관측 페이지 (워크플로우 추적 + 데이터 현황) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/observe` 페이지에서 한 분석이 에이전트 그래프를 거친 과정(워크플로우 탭)과 Neo4j/Chroma 데이터 현황(데이터 탭)을 본다.

**Architecture:** `run_supervisor`가 결과 state에서 실행 흔적 `trace`를 결정적으로 조립해 `final_report`에 넣고, `ReportResponse.trace`로 노출한다(추가 LLM 호출 없음). 데이터 현황은 새 `GET /stats`(Neo4j 집계 + Chroma count). 프론트는 기존 정적 패턴(same-origin) 그대로 `web/observe.html`+`observe.js`.

**Tech Stack:** FastAPI, LangGraph state, 바닐라 JS, 기존 `web/style.css` 재사용.

**참고 — 확인된 기존 구조:**
- `finalize_coach`(src/agent/nodes.py)가 `final_report = {"gap":..., "verification":..., "coaching":...}` 반환. 여기에 `"trace"` 추가.
- 평가자 state: `resume_eval = {"skills": [...]}` (github/portfolio/deploy_eval 동일).
- `consensus = {skill: {"verification": grade, "evidences": [{"source": ...}]}}`; `build_verification_summary(consensus)` → `{"counts": {...}, "skills": [...]}`.
- `critic_report = {"verified": bool, "removed_claims": [...], "corrections": [...]}`.
- `coaching_result = {"summary":..., "suggestions": [...]}`.
- `ChromaClient.count()` 이미 존재(src/storage/chroma_client.py).
- `_map_final_report`(src/api/routers/portfolio.py)가 `final` dict를 `ReportResponse`로 매핑.

---

### Task 1: trace 조립 (`_build_trace` + finalize_coach)

**Files:**
- Modify: `src/agent/nodes.py` (`_build_trace` 추가, `finalize_coach`가 호출)
- Test: `tests/unit/test_build_trace.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/unit/test_build_trace.py`:
```python
# _build_trace가 그래프 결과 state에서 실행 흔적을 결정적으로 조립하는지 검증 (DB·LLM 불필요)
from langchain_core.messages import ToolMessage

from src.agent.nodes import _build_trace


def test_build_trace_assembles_from_state():
    state = {
        "resume_eval": {"skills": ["Python", "SQL"]},
        "github_eval": {"skills": ["Docker"]},
        "portfolio_eval": None,
        "deploy_eval": None,
        "consensus": {
            "Python": {"verification": "Verified", "evidences": [{"source": "github"}]},
            "SQL": {"verification": "Claimed", "evidences": [{"source": "resume"}]},
        },
        "messages": [
            ToolMessage(content="{}", name="gap_analysis", tool_call_id="1"),
            ToolMessage(content="{}", name="verify_skills", tool_call_id="2"),
            ToolMessage(content="{}", name="verify_skills", tool_call_id="3"),
        ],
        "iteration": 2,
        "critic_report": {"removed_claims": ["X"], "corrections": [{"skill": "Y"}]},
        "coaching_result": {"suggestions": [1, 2, 3]},
    }
    t = _build_trace(state)

    assert [e["source"] for e in t["evaluators"]] == ["resume", "github"]
    assert t["evaluators"][0]["skill_count"] == 2
    assert t["consensus"] == {"Verified": 1, "Corroborated": 0, "Claimed": 1}
    assert set(t["gap_loop"]["tool_calls"]) == {"gap_analysis", "verify_skills"}  # 중복 제거
    assert t["gap_loop"]["iterations"] == 2
    assert t["critic"] == {"removed": 1, "corrected": 1}
    assert t["coach"]["suggestion_count"] == 3


def test_build_trace_empty_state_safe():
    t = _build_trace({})
    assert t["evaluators"] == []
    assert t["consensus"] == {"Verified": 0, "Corroborated": 0, "Claimed": 0}
    assert t["gap_loop"] == {"tool_calls": [], "iterations": 0}
    assert t["critic"] == {"removed": 0, "corrected": 0}
    assert t["coach"]["suggestion_count"] == 0
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/unit/test_build_trace.py -v`
Expected: FAIL — `_build_trace` 미정의(ImportError).

- [ ] **Step 3: `_build_trace` 구현**

`src/agent/nodes.py` 상단(기존 import 아래, 첫 함수 위)에 추가:
```python
def _build_trace(state: "AppState") -> dict:
    """그래프 결과 state에서 실행 흔적(관측 페이지용)을 결정적으로 조립한다."""
    from langchain_core.messages import ToolMessage
    from src.agent.consensus import build_verification_summary

    evaluators = []
    for src in ("resume", "github", "portfolio", "deploy"):
        ev = state.get(f"{src}_eval")
        if ev:
            evaluators.append({"source": src, "skill_count": len(ev.get("skills") or [])})

    counts = build_verification_summary(state.get("consensus") or {})["counts"]

    tool_calls: list[str] = []
    for m in state.get("messages") or []:
        if isinstance(m, ToolMessage) and getattr(m, "name", None) and m.name not in tool_calls:
            tool_calls.append(m.name)

    critic = state.get("critic_report") or {}
    coaching = state.get("coaching_result") or {}
    return {
        "evaluators": evaluators,
        "consensus": counts,
        "gap_loop": {"tool_calls": tool_calls, "iterations": state.get("iteration") or 0},
        "critic": {
            "removed": len(critic.get("removed_claims") or []),
            "corrected": len(critic.get("corrections") or []),
        },
        "coach": {"suggestion_count": len(coaching.get("suggestions") or [])},
    }
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/unit/test_build_trace.py -v`
Expected: 2 passed

- [ ] **Step 5: finalize_coach가 trace를 final_report에 넣도록 수정**

`src/agent/nodes.py`의 `finalize_coach` 반환부 — `final_report` 딕셔너리에 `"trace"` 한 줄 추가:
```python
        return {
            "coaching_result": coaching_dict,
            "final_report": {
                "gap": gap_raw,
                "verification": verification,
                "coaching": coaching_dict,
                "trace": _build_trace(state),
            },
        }
```

- [ ] **Step 6: 전체 단위 테스트 + 커밋**

Run: `python -m pytest tests/unit/ -q`
Expected: 모두 PASS (기존 + 2)
```bash
git add src/agent/nodes.py tests/unit/test_build_trace.py
git commit -m "feat(agent): final_report에 실행 흔적 trace 조립 (관측 페이지용)"
```

---

### Task 2: ReportResponse.trace + 매핑

**Files:**
- Modify: `src/api/schemas.py` (`ReportResponse`에 `trace`)
- Modify: `src/api/routers/portfolio.py` (`_map_final_report`)
- Test: `tests/unit/test_api_mapping.py` (기존 파일에 추가)

- [ ] **Step 1: 실패하는 테스트 추가**

`tests/unit/test_api_mapping.py` 파일 끝에 추가:
```python
def test_map_final_report_passes_trace():
    from src.api.routers.portfolio import _map_final_report

    final = {
        "gap": {"match_rate": 0.5, "confidence_level": "medium"},
        "verification": {"counts": {}, "skills": []},
        "coaching": {"summary": "s", "suggestions": []},
        "trace": {"evaluators": [{"source": "resume", "skill_count": 3}]},
    }
    resp = _map_final_report("rid", "owner", "Software Engineer", final)
    assert resp.trace == {"evaluators": [{"source": "resume", "skill_count": 3}]}
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/unit/test_api_mapping.py::test_map_final_report_passes_trace -v`
Expected: FAIL — `ReportResponse`에 `trace` 없음 또는 매핑 누락.

- [ ] **Step 3: 스키마 + 매핑 구현**

`src/api/schemas.py`의 `ReportResponse`에 필드 추가(`error_detail` 위 또는 아래, 같은 들여쓰기):
```python
    trace: dict | None = None
```

`src/api/routers/portfolio.py`의 `_map_final_report` 반환 `ReportResponse(...)`에 인자 추가(`generated_at=` 위에):
```python
        trace=final.get("trace"),
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/unit/test_api_mapping.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**
```bash
git add src/api/schemas.py src/api/routers/portfolio.py tests/unit/test_api_mapping.py
git commit -m "feat(api): ReportResponse.trace 노출 — 워크플로우 추적 데이터"
```

---

### Task 3: `GET /stats` 엔드포인트

**Files:**
- Modify: `src/api/schemas.py` (`StatsResponse`)
- Create: `src/api/routers/stats.py`
- Modify: `src/api/main.py` (stats 라우터 include)
- Test: `tests/integration/test_stats.py`

- [ ] **Step 1: StatsResponse 스키마 추가**

`src/api/schemas.py` 끝에 추가:
```python
class JobFamilyStat(BaseModel):
    name: str
    posting_count: int
    skill_count: int


class StatsResponse(BaseModel):
    job_families: list[JobFamilyStat]
    totals: dict[str, int]          # postings, skills, relations
    chroma_chunks: int | None = None
```

- [ ] **Step 2: 실패하는 통합 테스트 작성**

`tests/integration/test_stats.py`:
```python
# GET /stats가 Neo4j 집계 + Chroma count를 반환하는지 — 실 Neo4j 필요
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=True)

from fastapi.testclient import TestClient  # noqa: E402

from src.api.main import app  # noqa: E402

requires_neo4j = pytest.mark.skipif(not os.getenv("NEO4J_URI"), reason="NEO4J_URI 필요")


@requires_neo4j
def test_stats_returns_aggregates():
    with TestClient(app) as client:
        r = client.get("/stats")
    assert r.status_code == 200
    body = r.json()
    assert len(body["job_families"]) >= 1
    assert body["totals"]["postings"] > 0
    fam = body["job_families"][0]
    assert "name" in fam and "posting_count" in fam and "skill_count" in fam
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `python -m pytest tests/integration/test_stats.py -v`
Expected: FAIL — `/stats` 404.

- [ ] **Step 4: stats 라우터 구현**

`src/api/routers/stats.py` (신규):
```python
# 시스템 데이터 현황 — 직군별 통계 + 전체 노드/관계/청크 수
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from src.api.deps import get_chroma, get_neo4j
from src.api.schemas import JobFamilyStat, StatsResponse
from src.storage.chroma_client import ChromaClient
from src.storage.neo4j_client import Neo4jClient

router = APIRouter()

_FAMILY_STATS = """
MATCH (f:JobFamily)
OPTIONAL MATCH (f)<-[:INSTANCE_OF]-(jp:JobPosting)
WITH f, count(DISTINCT jp) AS postings
OPTIONAL MATCH (f)<-[:INSTANCE_OF]-(:JobPosting)-[:REQUIRES]->(s:Skill)
RETURN f.name AS name, postings, count(DISTINCT s) AS skill_count
ORDER BY postings DESC
"""

_TOTALS = """
MATCH (jp:JobPosting) WITH count(jp) AS postings
MATCH (s:Skill) WITH postings, count(s) AS skills
MATCH ()-[r:REQUIRES|PREFERS]->() RETURN postings, skills, count(r) AS relations
"""


@router.get("", response_model=StatsResponse)
async def stats(
    neo4j: Neo4jClient = Depends(get_neo4j),
    chroma: ChromaClient = Depends(get_chroma),
) -> StatsResponse:
    """Neo4j 집계 + Chroma 청크 수."""
    try:
        fam_rows = neo4j.execute_query(_FAMILY_STATS)
        tot_rows = neo4j.execute_query(_TOTALS)
    except Exception as e:
        raise HTTPException(503, f"DB 집계 실패: {e}")

    tot = tot_rows[0] if tot_rows else {"postings": 0, "skills": 0, "relations": 0}
    try:
        chunks = chroma.count()
    except Exception:
        chunks = None

    return StatsResponse(
        job_families=[
            JobFamilyStat(
                name=r["name"],
                posting_count=int(r.get("postings") or 0),
                skill_count=int(r.get("skill_count") or 0),
            )
            for r in fam_rows
        ],
        totals={
            "postings": int(tot.get("postings") or 0),
            "skills": int(tot.get("skills") or 0),
            "relations": int(tot.get("relations") or 0),
        },
        chroma_chunks=chunks,
    )
```

(참고: `src/api/deps.py`에 `get_chroma`가 없으면 `get_neo4j`와 같은 패턴으로 추가:
```python
def get_chroma(request: Request) -> "ChromaClient":
    return request.app.state.chroma
```)

- [ ] **Step 5: main.py에 라우터 등록**

`src/api/main.py`의 라우터 import에 추가:
```python
from src.api.routers import stats as stats_router
```
include_router 줄들 아래에 추가:
```python
app.include_router(stats_router.router, prefix="/stats", tags=["stats"])
```

- [ ] **Step 6: 테스트 통과 확인 + 커밋**

Run: `python -m pytest tests/integration/test_stats.py -v`
Expected: PASS
```bash
git add src/api/schemas.py src/api/routers/stats.py src/api/main.py src/api/deps.py
git commit -m "feat(api): GET /stats — 직군 통계·전체 노드/관계/청크 수"
```

---

### Task 4: `GET /observe` 라우트 + observe.html 골격

**Files:**
- Create: `web/observe.html` (최소 골격)
- Modify: `src/api/main.py` (`GET /observe`)
- Test: `tests/unit/test_static_serving.py` (기존 파일에 추가)

- [ ] **Step 1: 최소 observe.html 생성**

`web/observe.html`:
```html
<!DOCTYPE html>
<html lang="ko">
<head><meta charset="utf-8"><title>관측 — Job Skill Analyzer</title></head>
<body><h1>관측 — 워크플로우 / 데이터</h1></body>
</html>
```

- [ ] **Step 2: 실패하는 테스트 추가**

`tests/unit/test_static_serving.py` 끝에 추가:
```python
def test_observe_served():
    client = TestClient(app)
    r = client.get("/observe")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "관측" in r.text
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `python -m pytest tests/unit/test_static_serving.py::test_observe_served -v`
Expected: FAIL — `/observe` 404.

- [ ] **Step 4: main.py에 라우트 추가**

`src/api/main.py`의 `GET /` 핸들러 아래에 추가:
```python
@app.get("/observe", include_in_schema=False)
async def observe() -> FileResponse:
    """관측 페이지 — 워크플로우 추적 + 데이터 현황."""
    return FileResponse(_WEB_DIR / "observe.html")
```

- [ ] **Step 5: 테스트 통과 + 커밋**

Run: `python -m pytest tests/unit/test_static_serving.py -v`
Expected: 모두 PASS
```bash
git add web/observe.html src/api/main.py tests/unit/test_static_serving.py
git commit -m "feat(api): GET /observe 정적 서빙 배선"
```

---

### Task 5: observe.html 마크업 + observe.js (2탭 렌더)

**Files:**
- Modify: `web/observe.html` (탭 + 컨테이너)
- Create: `web/observe.js`

UI 자동 테스트는 비용 대비 가치가 낮아 수동 확인한다.

- [ ] **Step 1: observe.html 전체 마크업**

`web/observe.html` (전체 교체):
```html
<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>관측 — Job Skill Analyzer</title>
  <link rel="stylesheet" href="/web/style.css">
</head>
<body>
  <main>
    <header>
      <h1>관측 (Observability)</h1>
      <p class="sub">분석 <b>워크플로우</b>가 어떻게 도는지와 <b>데이터</b> 현황을 봅니다. <a href="/">← 분석으로</a></p>
    </header>
    <div class="tabs">
      <button id="tab-workflow" class="tab active">워크플로우</button>
      <button id="tab-data" class="tab">데이터</button>
    </div>
    <section id="panel-workflow" class="card"><div id="workflow"></div></section>
    <section id="panel-data" class="card hidden"><div id="data"></div></section>
  </main>
  <script src="/web/observe.js"></script>
</body>
</html>
```

- [ ] **Step 2: style.css에 탭 스타일 추가**

`web/style.css` 끝에 추가:
```css
.tabs { display:flex; gap:8px; margin-bottom:16px; }
.tab { background:#fff; color:var(--fg); border:1px solid var(--line); }
.tab.active { background:var(--accent); color:#fff; }
.step { border-left:3px solid var(--accent); padding:8px 12px; margin:10px 0; background:#fff; }
.step h4 { margin:0 0 4px; font-size:.92rem; }
.stat-row { display:flex; justify-content:space-between; padding:6px 0; border-bottom:1px solid var(--line); font-size:.9rem; }
```

- [ ] **Step 3: observe.js 작성**

`web/observe.js`:
```javascript
// 관측 페이지 — 워크플로우 추적(report_id의 trace) + 데이터 현황(/stats)
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;")
  .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");

// 탭 전환
function showTab(name) {
  const wf = name === "workflow";
  $("panel-workflow").classList.toggle("hidden", !wf);
  $("panel-data").classList.toggle("hidden", wf);
  $("tab-workflow").classList.toggle("active", wf);
  $("tab-data").classList.toggle("active", !wf);
  if (!wf) loadData();
}
$("tab-workflow").addEventListener("click", () => showTab("workflow"));
$("tab-data").addEventListener("click", () => showTab("data"));

// ── 워크플로우 탭 ──
async function loadWorkflow() {
  const params = new URLSearchParams(location.search);
  const reportId = params.get("report_id");
  if (!reportId) {
    $("workflow").innerHTML = "<p class='prio'>분석을 먼저 실행하세요. 분석 결과 화면의 '실행 과정 보기'로 들어오면 그 분석의 흐름이 표시됩니다.</p>";
    return;
  }
  try {
    const res = await fetch(`/portfolio/report/${reportId}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const d = await res.json();
    if (!d.trace) {
      $("workflow").innerHTML = "<p class='prio'>이 분석에는 실행 추적 정보가 없습니다.</p>";
      return;
    }
    renderTrace(d.trace);
  } catch (e) {
    $("workflow").innerHTML = `<p class='msg error'>불러오기 실패: ${esc(e.message)}</p>`;
  }
}

function renderTrace(t) {
  const ev = (t.evaluators || []).map((e) => `${esc(e.source)} ${e.skill_count}개`).join(" · ") || "없음";
  const c = t.consensus || {};
  const tools = (t.gap_loop?.tool_calls || []).map(esc).join(", ") || "없음";
  const cr = t.critic || {};
  $("workflow").innerHTML = `
    <div class="step"><h4>1. 평가자 (소스별 스킬 추출)</h4>${ev}</div>
    <div class="step"><h4>2. 합의 — 검증 등급 분포</h4>
      Verified ${c.Verified || 0} · Corroborated ${c.Corroborated || 0} · Claimed ${c.Claimed || 0}</div>
    <div class="step"><h4>3. Gap 루프 (Corrective RAG)</h4>
      도구: ${tools} · 반복 ${t.gap_loop?.iterations || 0}회</div>
    <div class="step"><h4>4. Critic (결정적 검증)</h4>
      환각 제거 ${cr.removed || 0} · 검증 라벨 교정 ${cr.corrected || 0}</div>
    <div class="step"><h4>5. Coach</h4>제안 ${t.coach?.suggestion_count || 0}개</div>
  `;
}

// ── 데이터 탭 ──
let dataLoaded = false;
async function loadData() {
  if (dataLoaded) return;
  dataLoaded = true;
  try {
    const res = await fetch("/stats");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const d = await res.json();
    const fams = (d.job_families || [])
      .map((f) => `<div class="stat-row"><span>${esc(f.name)}</span>
        <span>공고 ${f.posting_count} · 스킬 ${f.skill_count}</span></div>`).join("");
    const tot = d.totals || {};
    $("data").innerHTML = `
      <h3>전체</h3>
      <div class="stat-row"><span>공고</span><span>${tot.postings || 0}</span></div>
      <div class="stat-row"><span>스킬</span><span>${tot.skills || 0}</span></div>
      <div class="stat-row"><span>요구/우대 관계</span><span>${tot.relations || 0}</span></div>
      <div class="stat-row"><span>벡터 청크</span><span>${d.chroma_chunks ?? "—"}</span></div>
      <h3>직군별</h3>${fams}
    `;
  } catch (e) {
    dataLoaded = false;
    $("data").innerHTML = `<p class='msg error'>데이터 현황 불러오기 실패: ${esc(e.message)}</p>`;
  }
}

// 진입 시: report_id 있으면 워크플로우, 없으면 워크플로우 안내. tab 쿼리로 데이터 직행 가능.
const initTab = new URLSearchParams(location.search).get("tab") === "data" ? "data" : "workflow";
showTab(initTab);
loadWorkflow();
```

- [ ] **Step 4: 정적 서빙 회귀 + 수동 확인**

Run: `python -m pytest tests/unit/test_static_serving.py -q`
Expected: PASS
수동: `uvicorn src.api.main:app --port 8055` 후 `http://localhost:8055/observe` — 탭 2개 보이고, 데이터 탭 클릭 시 직군 통계 표시. (워크플로우 탭은 report_id 없으면 안내 문구.)

- [ ] **Step 5: 커밋**
```bash
git add web/observe.html web/observe.js web/style.css
git commit -m "feat(web): 관측 페이지 — 워크플로우/데이터 2탭 렌더"
```

---

### Task 6: 메인 분석 결과에 "실행 과정 보기" 링크

**Files:**
- Modify: `web/app.js` (`renderReport`)

- [ ] **Step 1: renderReport에 링크 추가**

`web/app.js`의 `renderReport` 함수에서, `$("result").innerHTML = \`` 템플릿의 맨 끝(마지막 `${suggestions ...}` 다음, 닫는 백틱 직전)에 한 줄 추가:
```javascript
    <p style="margin-top:16px"><a href="/observe?report_id=${encodeURIComponent(state.reportId)}&tab=workflow">→ 이 분석의 실행 과정 보기</a></p>
```

- [ ] **Step 2: 문법 체크 + 수동 확인**

Run: `node --check web/app.js`
Expected: 출력 없음(통과)
수동: 분석 완료 후 결과 하단 "실행 과정 보기" 클릭 → `/observe?report_id=...`로 이동, 워크플로우 탭에 trace 표시.

- [ ] **Step 3: 커밋**
```bash
git add web/app.js
git commit -m "feat(web): 분석 결과에 '실행 과정 보기' 링크 — 관측 페이지 연동"
```

---

## 비결정 사항(구현 중 확정)

- `src/api/deps.py`에 `get_chroma`가 이미 있으면 그대로 사용, 없으면 Task 3 Step 4 참고로 추가.
- 타임라인 시각화는 세로 `.step` 카드 목록(단순). 화살표 연결선은 생략.
