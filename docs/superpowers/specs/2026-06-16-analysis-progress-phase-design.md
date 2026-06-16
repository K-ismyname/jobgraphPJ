# 분석 단계별 진행 표시 설계 (Analysis Progress Phase)

**작성일:** 2026-06-16
**대상:** `src/agent/supervisor.py`(run_supervisor stream), `src/api/routers/portfolio.py`(phase 갱신), `src/api/schemas.py`(phase 필드), `web/app.js`(표시) + 테스트

## 목표

분석 중 "분석 중…" 스피너만 보이던 것을, **현재 진행 단계**(① 소스 평가 → ② 교차검증 합의 → ③ 적합도 분석 → ④ 검증·코칭)로 보여준다. LangGraph 실행을 스트리밍해 실제 진행을 정직하게 노출한다.

## 범위

**포함:** `run_supervisor`를 `graph.stream` 기반으로 + 진행 콜백, `reports[id].phase` 갱신, `ReportResponse.phase` 필드, 폴링 시 단계 표시.

**제외:** 평가자별 순차 번호(실제 병렬이라 부정확). `run_supervisor`의 입력 가드·post-processing(capability_fit 등)은 그대로.

## 현재 상태

- `portfolio.py:60` `/analyze` → `reports[id] = ReportResponse(status="processing")` + 백그라운드 `_run_analysis`.
- `_run_analysis`(144) → `run_supervisor`(`graph.invoke`, supervisor.py:264) → `reports[id] = _map_final_report`(done).
- `/report/{id}`(96) → `reports[id]` 반환.
- `app.js` `pollReport`(67) → 3초 폴링, `status==="processing"`이면 재시도 + "분석 중…" 스피너.

## 설계

### 1. `run_supervisor` 스트리밍 + 진행 콜백

`graph.invoke`를 `graph.stream(stream_mode="updates")`로 바꿔, 노드 완료마다 콜백을 호출하고 최종 state를 누적한다:
```python
def run_supervisor(..., progress_cb: Callable[[str], None] | None = None) -> dict:
    ...
    final_state: dict = dict(initial)
    for chunk in graph.stream(initial, config, stream_mode="updates"):
        for node, update in chunk.items():
            if progress_cb:
                progress_cb(node)
            if isinstance(update, dict):
                final_state.update(update)
    result = final_state
    # 이후 final = result.get("final_report") ... 기존 post-processing 동일
```
- `progress_cb`가 None이면 기존과 동일하게 동작(데모·테스트 호환).

### 2. 노드 → 단계 매핑 + `reports[id].phase` 갱신

`portfolio.py`에 노드를 큰 단계로 묶는 매핑을 두고, `_run_analysis`가 콜백으로 phase를 갱신:
```python
_NODE_PHASE = {
    "resume_eval": "소스 평가 중", "github_eval": "소스 평가 중",
    "portfolio_eval": "소스 평가 중", "deploy_eval": "소스 평가 중",
    "consensus": "교차검증 합의 중",
    "call_model": "적합도 분석 중", "tools": "적합도 분석 중",
    "synthesizer": "리포트 생성 중", "critic": "검증 중",
    "coach_call_model": "코칭 생성 중", "coach_tools": "코칭 생성 중",
    "finalize_coach": "코칭 생성 중",
}
```
(정확한 노드명은 plan에서 `supervisor.add_node` 호출로 확정.)
```python
def _progress(node):
    phase = _NODE_PHASE.get(node)
    if phase and report_id in reports:
        reports[report_id].phase = phase
```
`run_supervisor(..., progress_cb=_progress)`.

### 3. `ReportResponse.phase` 필드

```python
phase: str | None = None   # 진행 중 현재 단계 (processing일 때만 의미)
```
`/analyze`의 초기 `ReportResponse(status="processing")`에 `phase="소스 평가 중"` 기본값.

### 4. 표시 (`app.js`)

`pollReport`에서 `status==="processing"`일 때 스피너 옆에 `data.phase`를 표시:
```javascript
if (data.status === "processing") {
  $("progress").innerHTML = `<span class="spinner"></span> ${esc(data.phase || "분석 중…")}`;
  setTimeout(() => pollReport(attempt + 1), 3000);
  return;
}
```

## 영향받는 테스트

- `test_input_guard`·`test_job_family_guard` 등 `run_supervisor`를 부르는 테스트: `progress_cb` 기본 None이라 무변경(스트리밍 경로는 mock 그래프에서도 동작 — `_FakeGraph`에 `stream` 필요 시 plan에서 추가).
- `phase` 매핑 단위 테스트(노드→단계).

## 검증

1. `pytest tests/unit/ -q` — 통과.
2. 서버에서 분석 실행 후, 폴링 동안 "소스 평가 중 → 교차검증 합의 중 → 적합도 분석 중 → 코칭 생성 중"으로 단계가 바뀌는지 육안.

## 비고

평가자(이력서·GitHub·배포)는 병렬이라 "1단계 이력서 → 2단계 GitHub" 순차 번호는 실제와 맞지 않는다. 그래서 "소스 평가 중"이라는 큰 단계로 묶는다 — 정직하고, 폴링 간격(3초)과도 맞는 입자도다. `_FakeGraph`가 `stream`을 지원하지 않으면 기존 테스트가 깨질 수 있으므로, plan에서 `run_supervisor`가 `stream` 미지원 그래프에 안전하도록(또는 테스트 mock에 stream 추가) 처리한다.
