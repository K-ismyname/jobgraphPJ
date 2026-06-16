# 관측 코칭 세부화 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 관측 coach 단계를 "개수"에서 "본 것(GitHub 프로필 observations + 부족 스킬) → 만든 것(프로젝트 보강·연계 학습 제안)"으로 펼친다.

**Architecture:** `_build_trace`의 coach 블록에 입력 근거(github_profiles·missing_skills)를 추가하고, observe coach 단계가 trace(입력) + report(출력)를 두 묶음으로 표시한다. 출력 제안은 report에 이미 있어 trace에 중복 저장하지 않는다.

**Tech Stack:** Python(LangGraph trace), 정적 JS, pytest.

---

## File Structure

- `src/agent/nodes.py` — `_gap_missing_names` 헬퍼 + `_build_trace` coach 블록 확장.
- `web/observe.js` — `stageData('coach')` 표시.
- `tests/unit/test_build_trace.py` — coach 입력 근거 키 단언.

---

### Task 1: `_build_trace` coach에 입력 근거 추가

**Files:**
- Modify: `src/agent/nodes.py`
- Test: `tests/unit/test_build_trace.py`

- [ ] **Step 1: 테스트 추가**

`tests/unit/test_build_trace.py` 끝에 추가:
```python
def test_build_trace_coach_includes_inputs():
    state = {
        "coaching_result": {"project_suggestions": [1], "learning_recommendations": [1, 2]},
        "github_eval": {"profiles": [{"repo": "me/app", "observations": ["Docker 없음"]}]},
        "gap_result": {"missing_required": [{"skill": "K8s"}, "Helm"]},
    }
    t = _build_trace(state)
    assert t["coach"]["project_suggestion_count"] == 1
    assert t["coach"]["github_profiles"][0]["repo"] == "me/app"
    assert t["coach"]["missing_skills"] == ["K8s", "Helm"]
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/unit/test_build_trace.py::test_build_trace_coach_includes_inputs -q`
Expected: FAIL — `KeyError: 'github_profiles'`.

- [ ] **Step 3: 헬퍼 + coach 블록 확장**

`src/agent/nodes.py`의 `_build_trace` 함수 **앞**에 헬퍼 추가:
```python
def _gap_missing_names(gap: dict) -> list[str]:
    """gap report의 missing_required에서 부족 스킬명 목록(dict/str 모두 허용)."""
    out: list[str] = []
    for item in (gap.get("missing_required") or []):
        if isinstance(item, dict) and item.get("skill"):
            out.append(item["skill"])
        elif isinstance(item, str):
            out.append(item)
    return out[:8]
```
그리고 `_build_trace`의 `return {...}`에서 coach 블록을 교체:
```python
        "coach": {
            "project_suggestion_count": len(coaching.get("project_suggestions") or []),
            "learning_count": len(coaching.get("learning_recommendations") or []),
            "github_profiles": (state.get("github_eval") or {}).get("profiles") or [],
            "missing_skills": _gap_missing_names(state.get("gap_result") or {}),
        },
```

- [ ] **Step 4: 통과 확인 + 커밋**

Run: `pytest tests/unit/test_build_trace.py -q`
Expected: 전부 PASS.
```bash
git add src/agent/nodes.py tests/unit/test_build_trace.py
git commit -m "feat(agent): trace coach에 입력 근거(github_profiles·missing_skills) 추가"
```

---

### Task 2: observe coach 단계 표시 펼침

**Files:**
- Modify: `web/observe.js`

- [ ] **Step 1: `stageData('coach')` 교체**

`web/observe.js`의 `stageData`에서 coach 블록(`if (key === "coach") return ...개`)을 교체:
```javascript
  if (key === "coach") {
    const c = t.coach || {};
    const profiles = (c.github_profiles || [])
      .map((p) => `${esc(p.repo)}: ${(p.observations || []).map(esc).join(", ") || "—"}`).join("<br>");
    const missing = (c.missing_skills || []).map(esc).join(", ");
    const projects = (report.project_suggestions || [])
      .map((s) => `${esc(s.add_skill)}${s.repo ? ` (${esc(s.repo)})` : ""} — ${esc(s.how)}`).join("<br>");
    const learnings = (report.learning_recommendations || [])
      .map((s) => `${esc(s.skill)} — ${esc(s.reason)}`).join("<br>");
    return `<b>본 것</b><br>GitHub: ${profiles || "없음"}<br>부족 스킬: ${missing || "없음"}<br><br>`
      + `<b>만든 것</b><br>프로젝트 보강: ${projects || "없음"}<br>연계 학습: ${learnings || "없음"}`;
  }
```
(`stageData(key, t, report)`는 이미 `report`를 인자로 받으므로 추가 변경 불필요. 개수 배지 `stageBadges`는 그대로.)

- [ ] **Step 2: JS 문법 + 커밋**

Run: `node --check web/observe.js && echo ok`
Expected: `ok`.
```bash
git add web/observe.js
git commit -m "feat(web): 관측 coach 단계를 입력 근거 + 출력 제안으로 펼침"
```

---

### Task 3: 통합 검증

**Files:** (없음 — 검증 전용)

- [ ] **Step 1: 전체 단위 테스트**

Run: `pytest tests/unit/ -q`
Expected: 전부 PASS.

- [ ] **Step 2: 서버 육안**

서버를 빈 포트로 띄우고 GitHub URL 포함 분석 → `/observe?report_id=…`의 coach 단계가:
- **본 것**: GitHub repo별 observations("Docker 없음" 등) + 부족 스킬
- **만든 것**: 프로젝트 보강(add_skill·repo·how) + 연계 학습(skill·reason)

으로 펼쳐지는지 확인. 끝나면 서버 종료.
