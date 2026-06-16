# 관측 코칭 세부화 설계 (Observe Coach Detail)

**작성일:** 2026-06-16
**대상:** `src/agent/nodes.py`(_build_trace), `web/observe.js`(coach 단계 표시) + 테스트

## 목표

관측 페이지의 coach 단계를 "개수"(프로젝트 보강 N · 연계 학습 M)에서, **"무엇을 보고(입력 근거) → 무엇을 만들었나(출력 제안)"** 로 펼쳐, 코칭이 뭘 어디서 가져왔는지 보이게 한다.

## 범위

**포함:** `_build_trace`의 coach 블록에 입력 근거(GitHub 프로필·부족 스킬) 추가, observe coach 단계 표시 확장.

**제외:** coach 로직·출력 구조 변경(2단계에서 완료). A(결과 화면 단계별 진행)는 별도.

## 현재 상태

- `_build_trace`(nodes.py)의 coach 블록 = `{project_suggestion_count, learning_count}` 개수만.
- `observe.js` `stageData('coach')` = "프로젝트 보강 N개 · 연계 학습 M개".
- 출력 제안(`project_suggestions`·`learning_recommendations`)은 `/portfolio/report`의 응답(ReportResponse)에 이미 있음 — observe가 `report`로 받는다.
- GitHub 프로필은 `state["github_eval"]["profiles"]`, 부족 스킬은 `state["gap_result"]`에 있으나 trace엔 없다.

## 설계

### 1. `_build_trace` coach 블록 확장

입력 근거를 추가(개수는 유지 — stageBadges가 씀):
```python
"coach": {
    "project_suggestion_count": len(coaching.get("project_suggestions") or []),
    "learning_count": len(coaching.get("learning_recommendations") or []),
    "github_profiles": (state.get("github_eval") or {}).get("profiles") or [],
    "missing_skills": _gap_missing_names(state.get("gap_result") or {}),
},
```
- `_gap_missing_names`: gap_result에서 부족 스킬명 목록을 뽑는 작은 헬퍼(gap 구조에 맞춰 plan에서 확정).

### 2. observe coach 단계 표시 (`stageData('coach')`)

`t.coach`(입력 근거) + `report`(출력 제안)를 두 묶음으로:
- **본 것**:
  - GitHub 프로필: 각 repo의 `repo` + `observations`(예: "Dockerfile 없음")
  - 부족 스킬: `missing_skills`
- **만든 것**:
  - 프로젝트 보강: `report.project_suggestions`의 각 `add_skill` (repo) — `how` / `why`
  - 연계 학습: `report.learning_recommendations`의 각 `skill` — `reason`

연계 스킬의 원천은 각 추천의 `reason`("React와 함께 요구됨")으로 갈음한다(별도 related_skills 결과 표시는 하지 않음).

### 3. stageBadges coach

개수 배지(`프로젝트 N` `학습 M`)는 그대로 유지.

## 영향받는 테스트

- `test_build_trace.py`: coach 블록에 `github_profiles`·`missing_skills` 키가 들어가는지 단언 추가(기존 개수 단언 유지).

## 검증

1. `pytest tests/unit/ -q` — 통과.
2. 서버에서 GitHub URL 포함 분석 후 `/observe?report_id=…`의 coach 단계가 "본 것(프로필 observations + 부족 스킬) → 만든 것(제안 add_skill·how·why / 학습 skill·reason)"으로 펼쳐지는지 육안.

## 비고

출력 제안은 report에 이미 있어 trace에 중복 저장하지 않는다(observe가 report에서 직접 읽음). trace에는 입력 근거만 더한다 — 관측은 "판단 근거 추적"이 목적이므로 입력이 핵심이다.
