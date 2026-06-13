# 관측 페이지 시스템 설명서 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 관측 페이지 워크플로우 탭을 "이 Agentic RAG 시스템이 어떻게 작동하는지" 설명하는 페이지로 — Mermaid 구조도 + 6단계 설명(설계 의도) + (분석 있으면) 각 단계 실제 데이터.

**Architecture:** `GET /graph`가 실제 LangGraph 구조(Mermaid)와 6단계 설명을 분석 무관하게 제공. `_build_trace`를 확장해 각 단계 실제 데이터를 담음. observe.js가 `/graph`(항상) + `/report/{id}`(있으면)를 결합해 다이어그램 + 단계 카드를 렌더.

**Tech Stack:** FastAPI, LangGraph `draw_mermaid()`, Mermaid.js(CDN), 바닐라 JS.

**확인된 기존 구조:**
- `_build_trace(state, coaching=None)`(src/agent/nodes.py): 현재 `{executed?, evaluators:[{source,skill_count}], consensus:counts, gap_loop, critic:{removed,corrected}, coach}`. `ToolMessage` 상단 import됨, `build_verification_summary`는 함수 내 import.
- `build_verification_summary(consensus)` → `{"counts":{...}, "skills":[{skill,verification,sources}]}`.
- `state["<src>_eval"]["skills"]` = `[{skill,evidence,source,level_hint}]`. `state["critic_report"]` = `{removed_claims:[...], corrections:[...]}`.
- `get_graph(request)`(src/api/deps.py:33) → `request.app.state.graph`(없으면 None).
- main.py: `app.include_router(...)` 3개 + `_WEB_DIR` + `GET /`·`GET /observe`(FileResponse). `from fastapi import Depends`는 라우터에서.
- `web/observe.js`(86줄): `showTab`/`loadWorkflow`/`renderTrace`/`loadData`. `$`·`esc` 헬퍼 있음. observe.html은 `#workflow`·`#data` 컨테이너 + 탭.
- `graph.get_graph().draw_mermaid()` 동작 확인됨(15노드). 노드 id: resume_eval, github_eval, portfolio_eval, deploy_eval, consensus, seed_gap, call_model, tools, synthesizer, critic, coach_call_model, coach_tools, finalize_coach.

---

### Task 1: `_build_trace` 확장 (단계별 실제 데이터 + executed_nodes)

**Files:**
- Modify: `src/agent/nodes.py` (`_build_trace`)
- Test: `tests/unit/test_build_trace.py`

- [ ] **Step 1: 기존 테스트를 확장 구조로 수정**

`tests/unit/test_build_trace.py`의 `test_build_trace_assembles_from_state`를 다음으로 교체(consensus가 counts→{counts,skills}로 바뀌고 evaluators.skills·critic.removed_skills·executed_nodes 추가):
```python
def test_build_trace_assembles_from_state():
    state = {
        "resume_eval": {"skills": [{"skill": "Python", "evidence": "ev1", "source": "resume", "level_hint": "high"}]},
        "github_eval": {"skills": [{"skill": "Docker", "evidence": "ev2", "source": "github", "level_hint": None}]},
        "portfolio_eval": None,
        "deploy_eval": None,
        "consensus": {
            "Python": {"verification": "Verified", "evidences": [{"source": "github"}]},
            "SQL": {"verification": "Claimed", "evidences": [{"source": "resume"}]},
        },
        "messages": [
            ToolMessage(content="{}", name="gap_analysis", tool_call_id="1"),
            ToolMessage(content="{}", name="verify_skills", tool_call_id="2"),
        ],
        "iteration": 2,
        "critic_report": {"removed_claims": ["X"], "corrections": [{"skill": "Y"}]},
        "coaching_result": {"suggestions": [1, 2, 3]},
    }
    t = _build_trace(state)

    # 평가자: 스킬 목록까지
    assert t["evaluators"][0]["source"] == "resume"
    assert t["evaluators"][0]["skills"][0]["skill"] == "Python"
    assert t["evaluators"][0]["skills"][0]["evidence"] == "ev1"
    # 합의: counts + skills
    assert t["consensus"]["counts"] == {"Verified": 1, "Corroborated": 0, "Claimed": 1}
    assert any(s["skill"] == "Python" and s["verification"] == "Verified" for s in t["consensus"]["skills"])
    # gap 루프
    assert set(t["gap_loop"]["tool_calls"]) == {"gap_analysis", "verify_skills"}
    # critic: 항목까지
    assert t["critic"]["removed_skills"] == ["X"]
    assert t["critic"]["corrected"] == 1
    # 실행 노드
    assert "resume_eval" in t["executed_nodes"] and "github_eval" in t["executed_nodes"]
    assert "consensus" in t["executed_nodes"] and "critic" in t["executed_nodes"]
    assert t["coach"]["suggestion_count"] == 3
```
그리고 `test_build_trace_empty_state_safe`를 다음으로 교체(consensus 구조 변경 반영):
```python
def test_build_trace_empty_state_safe():
    t = _build_trace({})
    assert t["evaluators"] == []
    assert t["consensus"]["counts"] == {"Verified": 0, "Corroborated": 0, "Claimed": 0}
    assert t["gap_loop"] == {"tool_calls": [], "iterations": 0}
    assert t["critic"]["removed_skills"] == []
    assert t["executed_nodes"] == ["synthesizer"]
    assert t["coach"]["suggestion_count"] == 0
```
(`test_build_trace_prefers_passed_coaching`는 그대로 둠.)

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/unit/test_build_trace.py -v`
Expected: FAIL — consensus가 dict(counts)라 `["counts"]` KeyError 또는 evaluators[].skills 없음.

- [ ] **Step 3: `_build_trace` 교체**

`src/agent/nodes.py`의 `_build_trace` 함수 본문(docstring 아래, return까지)을 다음으로 교체:
```python
    from src.agent.consensus import build_verification_summary

    evaluators = []
    executed: list[str] = []
    for src in ("resume", "github", "portfolio", "deploy"):
        ev = state.get(f"{src}_eval")
        if ev:
            skills = ev.get("skills") or []
            evaluators.append({
                "source": src,
                "skill_count": len(skills),
                "skills": [
                    {"skill": s.get("skill"), "evidence": s.get("evidence"), "level_hint": s.get("level_hint")}
                    for s in skills if isinstance(s, dict)
                ],
            })
            executed.append(f"{src}_eval")

    cons = build_verification_summary(state.get("consensus") or {})
    if state.get("consensus"):
        executed.append("consensus")

    tool_calls: list[str] = []
    for m in state.get("messages") or []:
        if isinstance(m, ToolMessage) and getattr(m, "name", None) and m.name not in tool_calls:
            tool_calls.append(m.name)
    if state.get("messages"):
        executed += ["seed_gap", "call_model", "tools"]
    executed.append("synthesizer")

    critic = state.get("critic_report") or {}
    removed = critic.get("removed_claims") or []
    corrections = critic.get("corrections") or []
    if critic:
        executed.append("critic")

    coaching = coaching if coaching is not None else (state.get("coaching_result") or {})
    if state.get("coaching_result"):
        executed += ["coach_call_model", "finalize_coach"]

    return {
        "executed_nodes": executed,
        "evaluators": evaluators,
        "consensus": cons,
        "gap_loop": {"tool_calls": tool_calls, "iterations": state.get("iteration") or 0},
        "critic": {
            "removed": len(removed), "corrected": len(corrections),
            "removed_skills": removed, "corrections": corrections,
        },
        "coach": {"suggestion_count": len(coaching.get("suggestions") or [])},
    }
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/unit/test_build_trace.py -v`
Expected: 3 passed

- [ ] **Step 5: 전체 단위 + 커밋**

Run: `python -m pytest tests/unit/ -q`
Expected: 모두 PASS
```bash
git add src/agent/nodes.py tests/unit/test_build_trace.py
git commit -m "feat(agent): trace 확장 — 단계별 실제 데이터 + executed_nodes"
```

---

### Task 2: `GET /graph` — 구조 + 6단계 설명

**Files:**
- Create: `src/api/routers/system.py`
- Modify: `src/api/main.py` (라우터 등록)
- Test: `tests/unit/test_graph_endpoint.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/unit/test_graph_endpoint.py`:
```python
# GET /graph — 구조(Mermaid)+6단계 설명. graph None이어도 stages는 제공
from fastapi.testclient import TestClient

from src.api.main import app


def test_graph_returns_stages():
    client = TestClient(app)  # with 없이 → lifespan 미실행(graph None)
    r = client.get("/graph")
    assert r.status_code == 200
    body = r.json()
    keys = [s["key"] for s in body["stages"]]
    assert keys == ["evaluators", "consensus", "gap_loop", "fit", "critic", "coach"]
    assert all(s.get("title") and s.get("description") for s in body["stages"])
    # lifespan 미실행이라 app.state.graph 없음 → mermaid None (예외 없이)
    assert "mermaid" in body
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/unit/test_graph_endpoint.py -v`
Expected: FAIL — `/graph` 404.

- [ ] **Step 3: system 라우터 구현**

`src/api/routers/system.py` (신규):
```python
# 시스템 설명 — LangGraph 구조(Mermaid) + 6개 논리 단계의 설계 의도
from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.deps import get_graph

router = APIRouter()

_STAGES = [
    {"key": "evaluators", "title": "1. 다중 소스 평가자",
     "nodes": ["resume_eval", "github_eval", "portfolio_eval", "deploy_eval"],
     "description": "이력서·GitHub·배포 URL을 각각 다른 평가자가 본다. 소스마다 형식(텍스트·코드·웹)이 달라 한 LLM에 합칠 수 없고, 무엇보다 '할 줄 안다는 주장(이력서)'과 '코드로 실증됨(GitHub·배포)'을 구분하려고 분리했다."},
    {"key": "consensus", "title": "2. 교차검증 합의",
     "nodes": ["consensus"],
     "description": "여러 독립 소스가 같은 스킬을 가리키면 신뢰가 올라간다(법정·저널리즘의 교차검증 원칙). GitHub/배포로 실증되면 Verified, 2개 이상 소스가 일치하면 Corroborated, 한 소스(이력서)뿐이면 Claimed로 결정적으로 판정한다."},
    {"key": "gap_loop", "title": "3. Gap 루프 (Corrective RAG)",
     "nodes": ["seed_gap", "call_model", "tools"],
     "description": "단순 키워드 매칭이 아니다. 증거가 부족하면 에이전트가 다른 소스를 추가로 검색하는 교정 루프를 돈다 — '이 답을 신뢰할 근거가 충분한가'를 스스로 판단한다."},
    {"key": "fit", "title": "4. 역량 기반 적합도",
     "nodes": ["synthesizer"],
     "description": "직군 평균 개별 스킬로 재면 전문가가 저평가된다(Java 백엔드가 웹 평균과 안 맞음). 그래서 스킬을 역량(DB·백엔드·클라우드…)으로 묶어 '핵심 역량 충족'으로 본다. 어느 직군에 맞는지 역방향으로도 추천한다."},
    {"key": "critic", "title": "5. Critic (환각 제거)",
     "nodes": ["critic"],
     "description": "LLM이 스스로 채점하면 환각이 남는다. Critic은 판단하지 않고, 리포트의 주장을 합의(사실)와 대조해 합의에 없는 환각을 제거하고 부풀린 검증 라벨을 교정한다 — 결정적으로."},
    {"key": "coach", "title": "6. Coach",
     "nodes": ["coach_call_model", "coach_tools", "finalize_coach"],
     "description": "부족한 역량과, 이력서를 어떻게 고치면 좋을지 구체적인 문장을 공고 근거에 기반해 제안한다."},
]


@router.get("")
async def graph(graph=Depends(get_graph)) -> dict:
    """LangGraph 구조(Mermaid) + 단계 설명. graph 없으면 mermaid는 None."""
    mermaid = None
    if graph is not None:
        try:
            mermaid = graph.get_graph().draw_mermaid()
        except Exception:
            mermaid = None
    return {"mermaid": mermaid, "stages": _STAGES}
```

- [ ] **Step 4: main.py에 등록**

`src/api/main.py`의 라우터 import에 추가:
```python
from src.api.routers import system as system_router
```
include_router 줄들 아래에 추가:
```python
app.include_router(system_router.router, prefix="/graph", tags=["system"])
```

- [ ] **Step 5: 통과 + 커밋**

Run: `python -m pytest tests/unit/test_graph_endpoint.py -v` → PASS
Run: `python -m pytest tests/unit/ -q` → 전체 PASS
```bash
git add src/api/routers/system.py src/api/main.py tests/unit/test_graph_endpoint.py
git commit -m "feat(api): GET /graph — LangGraph 구조(Mermaid) + 단계 설명"
```

---

### Task 3: 워크플로우 탭 재구성 (Mermaid + 단계 카드)

**Files:**
- Modify: `web/observe.html` (Mermaid CDN)
- Modify: `web/observe.js` (loadWorkflow/renderTrace 재작성)
- Modify: `web/style.css` (다이어그램 영역)

UI는 수동 확인. 정적 서빙 회귀만 자동.

- [ ] **Step 1: observe.html에 Mermaid CDN 추가**

`web/observe.html`의 `<script src="/web/observe.js"></script>` **위**에 추가:
```html
  <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
```

- [ ] **Step 2: style.css에 다이어그램 스타일 추가 (파일 끝)**

`web/style.css` 끝에 추가:
```css
.diagram { overflow-x:auto; padding:12px; background:#fff; border:1px solid var(--line); border-radius:10px; margin-bottom:16px; }
.diagram svg { max-width:100%; height:auto; }
.stage-data { margin-top:8px; padding-left:8px; border-left:2px solid var(--line); }
```

- [ ] **Step 3: observe.js의 워크플로우 로직 재작성**

`web/observe.js`에서 `loadWorkflow`와 `renderTrace` 두 함수를 **삭제하고**, 그 자리에 아래를 넣는다(showTab·loadData·esc·$·진입로직은 그대로 둠). 단 파일 상단(`const esc = ...` 다음)에 Mermaid 초기화 한 줄 추가:
```javascript
if (window.mermaid) mermaid.initialize({ startOnLoad: false });
```
그리고 `loadWorkflow`/`renderTrace` 대체:
```javascript
// ── 워크플로우 탭 = 시스템 설명 + (분석 있으면) 실제 예시 ──
async function loadWorkflow() {
  let g;
  try {
    const res = await fetch("/graph");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    g = await res.json();
  } catch (e) {
    $("workflow").innerHTML = `<p class='msg error'>구조 불러오기 실패: ${esc(e.message)}</p>`;
    return;
  }
  const reportId = new URLSearchParams(location.search).get("report_id");
  let report = null;
  if (reportId) {
    try {
      const r = await fetch(`/portfolio/report/${reportId}`);
      if (r.ok) report = await r.json();
    } catch (e) { /* report 없이 설명만 */ }
  }
  await renderWorkflow(g, report);
}

async function renderWorkflow(g, report) {
  let diagram = "";
  if (g.mermaid && window.mermaid) {
    let src = g.mermaid;
    const ex = report && report.trace && report.trace.executed_nodes;
    if (ex && ex.length) {
      src += "\n" + ex.map((n) => `class ${n} executed;`).join("\n");
      src += "\nclassDef executed fill:#eef2ff,stroke:#4f46e5,stroke-width:2px;";
    }
    try {
      const { svg } = await mermaid.render("wfgraph", src);
      diagram = `<div class="diagram">${svg}</div>`;
    } catch (e) {
      diagram = "<p class='prio'>다이어그램 로드 실패</p>";
    }
  }
  const cards = (g.stages || []).map((st) => renderStage(st, report)).join("");
  $("workflow").innerHTML = diagram + cards;
}

function renderStage(st, report) {
  const t = report && report.trace;
  let data = "<div class='cap-ev'>분석하면 이 단계의 실제 처리 결과가 표시됩니다.</div>";
  if (report && t) data = `<div class="stage-data">${stageData(st.key, t, report)}</div>`;
  return `<div class="step"><h4>${esc(st.title)}</h4><p class="cap-ev">${esc(st.description)}</p>${data}</div>`;
}

function stageData(key, t, report) {
  if (key === "evaluators")
    return (t.evaluators || []).map((e) =>
      `<div><b>${esc(e.source)}</b> (${e.skill_count}): ${(e.skills || []).map((s) => esc(s.skill)).join(", ")}</div>`).join("") || "없음";
  if (key === "consensus")
    return ((t.consensus && t.consensus.skills) || []).map((s) =>
      `<div class="skill-row"><span>${esc(s.skill)}</span><span class="badge ${s.verification}">${esc(s.verification)}</span><span class="src">${(s.sources || []).map(esc).join(", ")}</span></div>`).join("") || "없음";
  if (key === "gap_loop")
    return `도구: ${(t.gap_loop && t.gap_loop.tool_calls || []).map(esc).join(", ") || "없음"} · 반복 ${(t.gap_loop && t.gap_loop.iterations) || 0}회`;
  if (key === "fit") {
    const cf = report.capability_fit;
    if (!cf) return "역량 정보 없음";
    const rec = (report.recommended_families || []).slice(0, 3).map((r) => `${esc(r.job_family)} ${Math.round((r.fit || 0) * 100)}%`).join(" · ");
    return `핵심 역량 충족 ${Math.round((cf.fit || 0) * 100)}% (${(cf.met || []).map(esc).join(", ")})<br>맞는 직군: ${rec}`;
  }
  if (key === "critic")
    return `제거된 주장: ${(t.critic && t.critic.removed_skills || []).map(esc).join(", ") || "없음"} · 교정 ${(t.critic && t.critic.corrected) || 0}건`;
  if (key === "coach")
    return `개선 제안 ${(t.coach && t.coach.suggestion_count) || 0}개`;
  return "";
}
```

- [ ] **Step 4: 문법·회귀 + 수동 확인**

Run: `node --check web/observe.js` → 출력 없음
Run: `python -m pytest tests/unit/test_static_serving.py -q` → PASS
수동: `uvicorn src.api.main:app --port 8060` → `http://localhost:8060/observe` — 워크플로우 탭에 Mermaid 다이어그램 + 6단계 설명 카드(분석 전엔 설명만). 분석 후 `/observe?report_id=...` → 거친 노드 강조 + 각 단계 실제 데이터.

- [ ] **Step 5: 커밋**
```bash
git add web/observe.html web/observe.js web/style.css
git commit -m "feat(web): 관측 워크플로우를 시스템 설명서로 — Mermaid + 단계 설명 + 실제 예시"
```

---

## 비결정 사항(구현 중 확정)

- Mermaid CDN 버전 `mermaid@10`. 오프라인이면 `g.mermaid && window.mermaid` 가드로 다이어그램만 생략, 설명 카드는 표시.
- executed_nodes 강조는 mermaid `class` 주입(노드 id가 draw_mermaid 출력과 일치). 일부 노드 id 불일치 시 강조만 누락되고 다이어그램은 정상.
