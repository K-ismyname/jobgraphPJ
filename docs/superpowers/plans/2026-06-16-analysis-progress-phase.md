# 분석 단계별 진행 표시 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 분석 중 "분석 중…" 대신 현재 단계(소스 평가 → 합의 → 적합도 → 코칭)를 폴링으로 보여준다.

**Architecture:** `run_supervisor`를 `graph.stream`으로 바꿔 노드 완료마다 `progress_cb`를 호출하고 최종 state를 누적. `_run_analysis`가 콜백으로 `reports[id].phase`를 갱신하고, `ReportResponse.phase`를 폴링이 표시한다.

**Tech Stack:** Python(LangGraph stream·FastAPI), 정적 JS, pytest.

---

## File Structure

- `src/agent/supervisor.py` — `run_supervisor` stream + `progress_cb`.
- `tests/unit/test_input_guard.py`·`test_job_family_guard.py` — `_FakeGraph`에 `stream` 추가.
- `src/api/schemas.py` — `ReportResponse.phase`.
- `src/api/routers/portfolio.py` — `_NODE_PHASE` + `_run_analysis` 콜백 + analyze 초기 phase.
- `web/app.js` — pollReport phase 표시.

---

### Task 1: `run_supervisor` 스트리밍 + 진행 콜백

**Files:**
- Modify: `src/agent/supervisor.py`, `tests/unit/test_input_guard.py`, `tests/unit/test_job_family_guard.py`

- [ ] **Step 1: `_FakeGraph`에 stream 추가 (양쪽 테스트)**

`tests/unit/test_input_guard.py`와 `tests/unit/test_job_family_guard.py`의 `_FakeGraph` 클래스에 `stream` 메서드를 추가한다(invoke와 같은 `invoked` 기록 + 최종 state를 한 chunk로 yield):
```python
    def stream(self, *args, **kwargs):
        self.invoked = True
        return iter([{"synthesizer": {"final_report": {"gap": {}}}}])
```

- [ ] **Step 2: 실패 확인 (현재 run_supervisor는 invoke를 부름)**

Run: `pytest tests/unit/test_input_guard.py tests/unit/test_job_family_guard.py -q`
Expected: PASS (아직 run_supervisor가 invoke를 쓰므로 stream 추가만으론 영향 없음 — 이 단계는 회귀 가드 준비).

- [ ] **Step 3: `run_supervisor`를 stream으로 + progress_cb**

`src/agent/supervisor.py`의 `run_supervisor` 시그니처에 `progress_cb`를 추가한다(`neo4j` 파라미터 뒤):
```python
    neo4j: "Neo4jClient | None" = None,
    progress_cb: "Callable[[str], None] | None" = None,
```
상단 import에 `Callable`이 없으면 `from typing import Callable` 추가(이미 있으면 생략).

그리고 `result = graph.invoke(initial, config)`(약 264행)를 교체:
```python
    final_state: dict = dict(initial)
    for chunk in graph.stream(initial, config, stream_mode="updates"):
        if not isinstance(chunk, dict):
            continue
        for node, update in chunk.items():
            if progress_cb:
                progress_cb(node)
            if isinstance(update, dict):
                final_state.update(update)
    result = final_state
```
(바로 다음 줄 `final = result.get("final_report") or {}` 이하 post-processing은 그대로.)

- [ ] **Step 4: 통과 확인 + 커밋**

Run: `pytest tests/unit/test_input_guard.py tests/unit/test_job_family_guard.py -q`
Expected: PASS (stream 경로로 invoked=True, final_report 추출).

```bash
git add src/agent/supervisor.py tests/unit/test_input_guard.py tests/unit/test_job_family_guard.py
git commit -m "feat(agent): run_supervisor를 graph.stream으로 — 노드 진행 콜백(progress_cb)"
```

---

### Task 2: `ReportResponse.phase` 필드

**Files:**
- Modify: `src/api/schemas.py`

- [ ] **Step 1: phase 필드 추가**

`src/api/schemas.py`의 `ReportResponse`에서 `status: ...` 줄 다음에 추가:
```python
    phase: str | None = None   # 진행 중 현재 단계 (status=processing일 때만 의미)
```

- [ ] **Step 2: 확인 + 커밋**

Run: `python -c "from src.api.schemas import ReportResponse; print(ReportResponse(report_id='r', status='processing', owner='x', job_family='y', phase='소스 평가 중').phase)"`
Expected: `소스 평가 중`.
```bash
git add src/api/schemas.py
git commit -m "feat(api): ReportResponse.phase — 진행 단계 필드"
```

---

### Task 3: 노드→단계 매핑 + reports.phase 갱신

**Files:**
- Modify: `src/api/routers/portfolio.py`
- Test: `tests/unit/test_progress_phase.py`(신규)

- [ ] **Step 1: 매핑 단위 테스트 작성**

`tests/unit/test_progress_phase.py`:
```python
# 노드 → 진행 단계 라벨 매핑
from src.api.routers.portfolio import _NODE_PHASE


def test_node_phase_groups():
    assert _NODE_PHASE["resume_eval"] == "소스 평가 중"
    assert _NODE_PHASE["github_eval"] == "소스 평가 중"
    assert _NODE_PHASE["consensus"] == "교차검증 합의 중"
    assert _NODE_PHASE["call_model"] == "적합도 분석 중"
    assert _NODE_PHASE["coach_call_model"] == "코칭 생성 중"
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/unit/test_progress_phase.py -q`
Expected: FAIL — `ImportError: cannot import name '_NODE_PHASE'`.

- [ ] **Step 3: `_NODE_PHASE` + 콜백 + 초기 phase**

`src/api/routers/portfolio.py`의 모듈 상수 구역(`_MAX_PDF_BYTES` 근처)에 추가:
```python
_NODE_PHASE = {
    "resume_eval": "소스 평가 중", "github_eval": "소스 평가 중",
    "portfolio_eval": "소스 평가 중", "deploy_eval": "소스 평가 중",
    "consensus": "교차검증 합의 중",
    "seed_gap": "적합도 분석 중", "call_model": "적합도 분석 중", "tools": "적합도 분석 중",
    "synthesizer": "리포트 생성 중", "critic": "검증 중",
    "coach_call_model": "코칭 생성 중", "coach_tools": "코칭 생성 중",
    "finalize_coach": "코칭 생성 중",
}
```
`_run_analysis`의 `run_supervisor(...)` 호출에 콜백을 추가한다. 호출 직전에 정의:
```python
        def _progress(node: str) -> None:
            phase = _NODE_PHASE.get(node)
            if phase and report_id in reports:
                reports[report_id].phase = phase

        out = run_supervisor(
            graph, job_family=job_family, owner=owner,
            resume_text=resume_text, github_urls=github_urls, deploy_urls=deploy_urls,
            neo4j=neo4j, progress_cb=_progress,
        )
```
그리고 `/analyze`의 초기 `ReportResponse(... status="processing", ...)`에 `phase="소스 평가 중"`을 추가한다.

- [ ] **Step 4: 통과 확인 + 커밋**

Run: `pytest tests/unit/test_progress_phase.py -q`
Expected: PASS.

Run: `python -c "from src.api.main import app; print('ok')"`
Expected: `ok`.

```bash
git add src/api/routers/portfolio.py tests/unit/test_progress_phase.py
git commit -m "feat(api): 노드→단계 매핑 + reports.phase 실시간 갱신"
```

---

### Task 4: 폴링 단계 표시 (app.js)

**Files:**
- Modify: `web/app.js`

- [ ] **Step 1: pollReport에 phase 표시**

`web/app.js`의 `pollReport`에서 `if (data.status === "processing") { ... }` 블록을 교체:
```javascript
    if (data.status === "processing") {
      $("progress").innerHTML = `<span class="spinner"></span> ${esc(data.phase || "분석 중…")}`;
      setTimeout(() => pollReport(attempt + 1), 3000);
      return;
    }
```

- [ ] **Step 2: JS 문법 + 커밋**

Run: `node --check web/app.js && echo ok`
Expected: `ok`.
```bash
git add web/app.js
git commit -m "feat(web): 분석 진행 단계를 폴링으로 표시"
```

---

### Task 5: 통합 검증

**Files:** (없음 — 검증 전용)

- [ ] **Step 1: 전체 단위 테스트**

Run: `pytest tests/unit/ -q`
Expected: 전부 PASS.

- [ ] **Step 2: 서버 육안**

서버를 빈 포트로 띄우고 분석 실행 → 결과 박스의 진행 표시가 "소스 평가 중 → 교차검증 합의 중 → 적합도 분석 중 → 코칭 생성 중"으로 바뀌는지 확인(3초 폴링 간격). 끝나면 서버 종료.
