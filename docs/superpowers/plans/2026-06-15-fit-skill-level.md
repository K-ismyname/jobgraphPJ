# 선택 직군 적합도 스킬화 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 선택 직군 적합도를 역량 기반에서 직군 핵심 스킬 10개 충족 개수로 바꾸고, 역량(capability) 개념을 코드에서 제거한다.

**Architecture:** `capability.py`를 `skill_overlap`·`job_family_core_skills`·`skill_fit`·`recommend_families`만 남기고 재작성(역량 함수·시드 삭제). 적합도는 직군 빈도 상위 10개 스킬 ∩ 이력서 스킬, 충족 스킬엔 검증등급을 붙인다. 표시는 스킬 칩.

**Tech Stack:** Python(capability·supervisor·FastAPI), 정적 JS, pytest.

---

## File Structure

- `src/analysis/capability.py` — 재작성(역량 제거, `job_family_core_skills`·`skill_fit` 신규).
- `src/agent/supervisor.py:266-279` — 스킬 기반 호출 + import 정리.
- `src/api/schemas.py` — `capability_evidence` 필드 삭제.
- `src/api/routers/portfolio.py` — `capability_evidence` 매핑 삭제.
- `web/app.js` `renderCapability` — 스킬 칩 표시.
- `web/observe.js` `stageData('fit')` — 스킬 표시.
- `data/seeds/skill_capabilities.json` — 삭제(orphan).
- 테스트: `test_capability.py`(재작성)·`test_api_mapping.py`·`test_capability_fit.py` 갱신.

---

### Task 1: capability.py 재작성 + supervisor

**Files:**
- Modify: `src/analysis/capability.py`(전면), `src/agent/supervisor.py`
- Test: `tests/unit/test_capability.py`(전면)

- [ ] **Step 1: `test_capability.py` 재작성**

`tests/unit/test_capability.py` 전체를 교체(역량 테스트 삭제, `skill_overlap` 유지 + `skill_fit` 추가):
```python
# 직군 핵심 스킬 교집합·적합도 검증
from src.analysis.capability import skill_overlap, skill_fit


def test_skill_overlap_normalizes_and_counts():
    count, matched = skill_overlap(["React.js", "Python"], ["React", "Java"])
    assert count == 1
    assert matched == ["React.js"]


def test_skill_overlap_dedup_and_empty():
    assert skill_overlap([], ["SQL"]) == (0, [])
    count, matched = skill_overlap(["SQL", "sql"], ["SQL"])
    assert count == 1
    assert matched == ["SQL"]


def test_skill_fit_counts_and_grades():
    consensus = {"React": {"verification": "Verified"}}
    r = skill_fit(["React.js", "Python"], ["React", "Vue.js", "HTML"], consensus)
    assert r["total"] == 3
    assert r["fit"] == 0.33
    assert r["met"] == [{"skill": "React.js", "verification": "Verified"}]
    assert r["unmet"] == ["Vue.js", "HTML"]


def test_skill_fit_default_grade_claimed():
    r = skill_fit(["HTML"], ["HTML", "CSS"], {})
    assert r["met"] == [{"skill": "HTML", "verification": "Claimed"}]
    assert r["unmet"] == ["CSS"]
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/unit/test_capability.py -q`
Expected: FAIL — `ImportError: cannot import name 'skill_fit'`.

- [ ] **Step 3: `capability.py` 전면 교체**

`src/analysis/capability.py` 전체를 교체:
```python
# 직군 핵심 스킬 대비 이력서 충족(적합도)과 역방향 직군 추천을 따지는 모듈
from __future__ import annotations

from typing import TYPE_CHECKING

from src.extraction.normalizer import normalize_skill

if TYPE_CHECKING:
    from src.storage.neo4j_client import Neo4jClient


def skill_overlap(resume_skills: list[str], family_skills: list[str]) -> tuple[int, list[str]]:
    """이력서 스킬과 직군 스킬 풀의 교집합(정규화 후). (개수, 일치한 이력서 원형 목록)."""
    fam_norm = {normalize_skill(s).lower() for s in family_skills}
    matched: list[str] = []
    seen: set[str] = set()
    for s in resume_skills:
        key = normalize_skill(s).lower()
        if key in fam_norm and key not in seen:
            seen.add(key)
            matched.append(s)
    return len(matched), matched


_FAMILY_SKILLS_QUERY = """
MATCH (:JobFamily {name: $job_family})<-[:INSTANCE_OF]-(jp)-[:REQUIRES]->(s:Skill)
RETURN s.name AS skill, count(DISTINCT jp) AS w
ORDER BY w DESC
LIMIT $n
"""


def job_family_core_skills(neo4j: "Neo4jClient", job_family: str, n: int = 10) -> list[str]:
    """직군 REQUIRES 스킬을 공고 수 가중 상위 n개로."""
    rows = neo4j.execute_query(_FAMILY_SKILLS_QUERY, job_family=job_family, n=n)
    return [r["skill"] for r in rows]


def skill_fit(resume_skills: list[str], core_skills: list[str], consensus: dict) -> dict:
    """직군 핵심 스킬 중 이력서 충족 비율 + 충족(검증등급)/미충족."""
    count, met = skill_overlap(resume_skills, core_skills)
    met_norm = {normalize_skill(s).lower() for s in met}
    unmet = [s for s in core_skills if normalize_skill(s).lower() not in met_norm]
    met_graded = [
        {"skill": s, "verification": (consensus.get(normalize_skill(s)) or {}).get("verification", "Claimed")}
        for s in met
    ]
    return {"fit": round(count / len(core_skills), 2) if core_skills else 0.0,
            "total": len(core_skills), "met": met_graded, "unmet": unmet}


def recommend_families(neo4j: "Neo4jClient", resume_skills: list[str], families: list[str], n: int = 25) -> list[dict]:
    """직군별 빈도 상위 n개 스킬 풀과 이력서 스킬의 교집합 개수로 추천 — 내림차순."""
    out = []
    for fam in families:
        count, matched = skill_overlap(resume_skills, job_family_core_skills(neo4j, fam, n))
        out.append({"job_family": fam, "matched_count": count, "matched_skills": matched})
    return sorted(out, key=lambda x: -x["matched_count"])
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/unit/test_capability.py -q`
Expected: 4개 PASS.

- [ ] **Step 5: `supervisor.py` 호출·import 교체**

`src/agent/supervisor.py`의 import 블록(267-270)을 교체:
```python
        from src.analysis.capability import (
            job_family_core_skills, recommend_families, skill_fit,
        )
```
그리고 `:271-279` 블록을 교체:
```python
        owned: list[dict] = []
        for k in ("resume_eval", "github_eval", "portfolio_eval", "deploy_eval"):
            owned += (result.get(k) or {}).get("skills", [])
        names = [it["skill"] for it in owned if isinstance(it, dict) and it.get("skill")]
        core_skills = job_family_core_skills(neo4j, job_family, 10)
        final["capability_fit"] = {"job_family": job_family,
                                   **skill_fit(names, core_skills, result.get("consensus") or {})}
        final["recommended_families"] = recommend_families(neo4j, names, neo4j.list_job_families())[:3]
```
(`resume_caps`·`capability_evidence` 라인 삭제.)

- [ ] **Step 6: import 정합 + 전체 단위 테스트**

Run: `python -c "from src.api.main import app; print('ok')"`
Expected: `ok`.

Run: `pytest tests/unit/ -q`
Expected: 전부 PASS(단, `test_api_mapping`은 Task 2에서 갱신 — 이 시점엔 capability_evidence 참조로 실패할 수 있음. 그 경우 Task 2까지 진행 후 재확인).

- [ ] **Step 7: Commit**

```bash
git add src/analysis/capability.py src/agent/supervisor.py tests/unit/test_capability.py
git commit -m "feat(analysis): 선택 직군 적합도를 스킬 레벨로 — 역량 함수 제거"
```

---

### Task 2: API 정리 (capability_evidence 제거)

**Files:**
- Modify: `src/api/schemas.py`, `src/api/routers/portfolio.py`
- Test: `tests/unit/test_api_mapping.py`

- [ ] **Step 1: `test_api_mapping.py` 갱신**

`tests/unit/test_api_mapping.py:49-60`의 `final` dict와 단언을 교체한다. `capability_fit`을 새 구조로, `capability_evidence` 입력·단언을 삭제:
```python
    final = {
        "gap": {"match_rate": 0.5},
        "verification": {"counts": {}, "skills": []},
        "coaching": {"summary": "s", "suggestions": []},
        "capability_fit": {"job_family": "Software Engineer", "fit": 0.5, "total": 2,
                           "met": [{"skill": "Java", "verification": "Verified"}], "unmet": ["SQL"]},
        "recommended_families": [{"job_family": "Software Engineer", "matched_count": 5, "matched_skills": ["Java", "Spring"]}],
    }
    resp = _map_final_report("rid", "owner", "Software Engineer", final)
    assert resp.capability_fit["fit"] == 0.5
    assert resp.recommended_families[0]["job_family"] == "Software Engineer"
```
(`capability_evidence` 줄과 그 단언 삭제.)

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/unit/test_api_mapping.py -q`
Expected: 통과 또는 실패 — schema에 `capability_evidence`가 남아있어도 dict 매핑이라 통과할 수 있음. Step 3~4 후 필드 제거가 핵심.

- [ ] **Step 3: `schemas.py`에서 `capability_evidence` 필드 삭제**

`src/api/schemas.py`의 `ReportResponse`에서 아래 줄을 삭제:
```python
    capability_evidence: list[dict] = Field(default_factory=list)
```

- [ ] **Step 4: `portfolio.py`에서 매핑 삭제**

`src/api/routers/portfolio.py`의 `_map_final_report` 안에서 아래 줄을 삭제:
```python
        capability_evidence=final.get("capability_evidence") or [],
```

- [ ] **Step 5: 통과 확인 + 커밋**

Run: `pytest tests/unit/test_api_mapping.py tests/unit/test_api_schemas.py -q`
Expected: PASS.
```bash
git add src/api/schemas.py src/api/routers/portfolio.py tests/unit/test_api_mapping.py
git commit -m "refactor(api): capability_evidence 제거 — 적합도 스킬화"
```

---

### Task 3: 표시 (app.js + observe.js)

**Files:**
- Modify: `web/app.js`, `web/observe.js`

- [ ] **Step 1: `app.js` `renderCapability` 교체**

`web/app.js`의 `renderCapability`(100-119)를 교체한다. `capability_fit`의 새 구조(`{job_family, fit, total, met:[{skill,verification}], unmet:[skill]}`)를 쓰고, 충족 칩에 검증등급 배지를 붙이며 "역량별 근거" 섹션은 제거한다:
```javascript
function renderCapability(d) {
  const cf = d.capability_fit;
  if (!cf) return "";
  const metN = (cf.met || []).length;
  const met = (cf.met || []).map((m) =>
    `<span class="cap met">${esc(m.skill)} ✓ <span class="badge ${m.verification}">${esc(m.verification)}</span></span>`).join("");
  const unmet = (cf.unmet || []).map((s) => `<span class="cap unmet">${esc(s)} ✗</span>`).join("");
  const rec = (d.recommended_families || [])
    .map((r) => `<div class="fam-row"><span>${esc(r.job_family)}</span><span>${r.matched_count}개 일치</span></div>`
      + ((r.matched_skills || []).length ? `<div class="cap-ev">${(r.matched_skills || []).map(esc).join(", ")}</div>` : ""))
    .join("");
  return `
    <h3>${esc(cf.job_family || "")} 핵심 스킬 ${metN}/${cf.total || 0} 충족</h3>
    <div>${met}${unmet}</div>
    ${rec ? `<h3>당신에게 맞는 직군</h3>${rec}` : ""}
  `;
}
```

- [ ] **Step 2: `observe.js` `stageData('fit')` 교체**

`web/observe.js`의 `stageData` 중 `key === "fit"` 블록을 교체:
```javascript
  if (key === "fit") {
    const cf = report.capability_fit;
    if (!cf) return "적합도 정보 없음";
    const rec = (report.recommended_families || []).slice(0, 3).map((r) => `${esc(r.job_family)} ${r.matched_count}개`).join(" · ");
    const metNames = (cf.met || []).map((m) => esc(m.skill)).join(", ");
    return `핵심 스킬 ${(cf.met || []).length}/${cf.total || 0} 충족 (${metNames})<br>맞는 직군: ${rec}`;
  }
```

- [ ] **Step 3: JS 문법 + 커밋**

Run: `node --check web/app.js && node --check web/observe.js && echo ok`
Expected: `ok`.
```bash
git add web/app.js web/observe.js
git commit -m "feat(web): 적합도 표시를 핵심 스킬 충족(검증등급)으로"
```

---

### Task 4: 통합 테스트 갱신 + 시드 삭제 + 검증

**Files:**
- Modify: `tests/integration/test_capability_fit.py`
- Delete: `data/seeds/skill_capabilities.json`(있으면)

- [ ] **Step 1: `test_capability_fit.py` 갱신**

`tests/integration/test_capability_fit.py`의 import와 첫 테스트를 스킬 기반으로 교체.

import(10-12):
```python
from src.analysis.capability import (  # noqa: E402
    job_family_core_skills, recommend_families,
)
```
`test_se_core_has_backend_and_db`(19-23) 교체:
```python
@requires_neo4j
def test_se_core_skills_nonempty():
    neo4j = Neo4jClient()
    core = job_family_core_skills(neo4j, "Software Engineer", 10)
    assert len(core) > 0 and all(isinstance(s, str) for s in core)
    neo4j.close()
```
(`test_backend_resume_ranks_se_above_ai`는 `recommend_families`를 쓰므로 그대로 둔다.)

- [ ] **Step 2: 시드 파일 삭제(있으면)**

Run: `git rm --ignore-unmatch data/seeds/skill_capabilities.json`
(추적되지 않으면 `rm -f data/seeds/skill_capabilities.json`. 없으면 건너뜀.)

- [ ] **Step 3: 잔재 확인**

Run: `grep -rn "capability_evidence\|skills_to_capabilities\|job_family_core_capabilities\|SEED_CAPABILITIES" src/ tests/`
Expected: (빈 출력) — 역량 함수 참조 잔재 없음.

- [ ] **Step 4: 전체 단위 테스트**

Run: `pytest tests/unit/ -q`
Expected: 전부 PASS.

- [ ] **Step 5: 통합 테스트 (Neo4j 연결 시)**

Run: `pytest tests/integration/test_capability_fit.py -q`
Expected: PASS 또는 skip(NEO4J_URI 없으면).

- [ ] **Step 6: 서버 육안**

```bash
uvicorn src.api.main:app --port 8076 --log-level warning
```
프론트 이력서로 분석 → 헤드라인 "핵심 스킬 M/10 충족", 충족 칩에 검증등급, `ml_ai`·`cloud` 같은 역량 칸 없음 확인. 끝나면 서버 종료.

- [ ] **Step 7: Commit**

```bash
git add tests/integration/test_capability_fit.py data/seeds/skill_capabilities.json
git commit -m "test(analysis): 적합도 스킬화 — 통합 테스트 갱신 + 역량 시드 삭제"
```
(시드 파일이 git에 없었으면 `data/seeds/skill_capabilities.json`는 add에서 제외.)
