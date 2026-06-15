# 스킬 레벨 직군 추천 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** "맞는 직군 추천"을 역량 단위에서 스킬 단위(직군 빈도 상위 25개 스킬 풀 ∩ 이력서 스킬, 겹친 개수)로 바꿔 DA/DE처럼 역량으로 뭉치면 안 갈리던 직군을 구분한다.

**Architecture:** 순수 교집합 함수 `skill_overlap`을 분리해 단위 테스트하고, `recommend_families`를 스킬 기반으로 재작성한다. 선택 직군 적합도(`capability_fit`)는 그대로 둔다. 표시는 분수가 아닌 "N개 일치".

**Tech Stack:** Python(capability.py·supervisor.py), Neo4j 쿼리, 정적 JS(app.js·observe.js), pytest.

---

## File Structure

- `src/analysis/capability.py` — `skill_overlap` 순수 함수 추가, `recommend_families` 스킬 기반 재작성, `_FAMILY_SKILLS` 쿼리.
- `src/agent/supervisor.py:278` — 호출을 `names`(스킬) 기반 + `[:3]`으로.
- `web/app.js:110-112` — 추천 표시 "N개 일치".
- `web/observe.js` `stageData('fit')` — 추천 `matched_count` 표시.
- `tests/unit/test_capability.py` — `skill_overlap` 단위 테스트 추가.
- `tests/unit/test_api_mapping.py:54` — 추천 입력 dict를 새 구조로.
- `tests/integration/test_capability_fit.py:29-30` — 스킬 list 전달로.

---

### Task 1: `skill_overlap` 순수 함수

**Files:**
- Modify: `src/analysis/capability.py`
- Test: `tests/unit/test_capability.py`

- [ ] **Step 1: 실패 테스트 추가**

`tests/unit/test_capability.py` 끝에 추가:

```python
from src.analysis.capability import skill_overlap


def test_skill_overlap_normalizes_and_counts():
    # React.js→React 정규화로 직군 풀의 "React"와 일치, 이력서 원형을 반환
    count, matched = skill_overlap(["React.js", "Python"], ["React", "Java"])
    assert count == 1
    assert matched == ["React.js"]


def test_skill_overlap_dedup_and_empty():
    assert skill_overlap([], ["SQL"]) == (0, [])
    # 정규화상 같은 스킬(SQL/sql)은 한 번만 집계
    count, matched = skill_overlap(["SQL", "sql"], ["SQL"])
    assert count == 1
    assert matched == ["SQL"]
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/unit/test_capability.py -q`
Expected: FAIL — `ImportError: cannot import name 'skill_overlap'`.

- [ ] **Step 3: 구현**

`src/analysis/capability.py`의 `skills_to_capabilities` 함수 정의 바로 다음에 추가:

```python
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
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/unit/test_capability.py -q`
Expected: 전부 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/analysis/capability.py tests/unit/test_capability.py
git commit -m "feat(analysis): skill_overlap — 정규화 기반 스킬 교집합 순수 함수"
```

---

### Task 2: `recommend_families` 스킬 기반 재작성 + 호출처

**Files:**
- Modify: `src/analysis/capability.py`, `src/agent/supervisor.py`, `tests/integration/test_capability_fit.py`

- [ ] **Step 1: `recommend_families` 재작성 + 쿼리 추가**

`src/analysis/capability.py`의 기존 `recommend_families`(아래)를 교체한다.

기존:
```python
def recommend_families(neo4j: "Neo4jClient", resume_caps: set[str], families: list[str]) -> list[dict]:
    """직군별 충족률을 계산해 내림차순 정렬 — 역방향 직군 추천."""
    out = []
    for fam in families:
        core = job_family_core_capabilities(neo4j, fam)
        out.append({"job_family": fam, **capability_fit(resume_caps, core)})
    return sorted(out, key=lambda x: -x["fit"])
```

교체 후 (위에 모듈 상수 `_FAMILY_SKILLS_QUERY` 추가, 함수는 스킬 기반):
```python
_FAMILY_SKILLS_QUERY = """
MATCH (:JobFamily {name: $job_family})<-[:INSTANCE_OF]-(jp)-[:REQUIRES]->(s:Skill)
RETURN s.name AS skill, count(DISTINCT jp) AS w
ORDER BY w DESC
LIMIT $n
"""


def recommend_families(neo4j: "Neo4jClient", resume_skills: list[str], families: list[str], n: int = 25) -> list[dict]:
    """직군별 빈도 상위 n개 스킬 풀과 이력서 스킬의 교집합 개수로 추천 — 내림차순."""
    out = []
    for fam in families:
        rows = neo4j.execute_query(_FAMILY_SKILLS_QUERY, job_family=fam, n=n)
        pool = [r["skill"] for r in rows]
        count, matched = skill_overlap(resume_skills, pool)
        out.append({"job_family": fam, "matched_count": count, "matched_skills": matched})
    return sorted(out, key=lambda x: -x["matched_count"])
```

- [ ] **Step 2: `supervisor.py` 호출 변경**

`src/agent/supervisor.py:278`을 교체한다.

기존:
```python
        final["recommended_families"] = recommend_families(neo4j, resume_caps, neo4j.list_job_families())[:5]
```
교체:
```python
        final["recommended_families"] = recommend_families(neo4j, names, neo4j.list_job_families())[:3]
```
(`resume_caps`는 바로 위 `capability_fit` 계산에 계속 쓰이므로 그대로 둔다.)

- [ ] **Step 3: 통합 테스트 갱신**

`tests/integration/test_capability_fit.py:27-33`의 `test_backend_resume_ranks_se_above_ai`를 스킬 list 전달로 교체한다.

기존:
```python
    caps = skills_to_capabilities(["Java", "Spring", "MariaDB", "Docker", "AWS", "Jenkins"])
    rec = recommend_families(neo4j, caps, neo4j.list_job_families())
```
교체:
```python
    skills = ["Java", "Spring", "MariaDB", "Docker", "AWS", "Jenkins"]
    rec = recommend_families(neo4j, skills, neo4j.list_job_families())
```
(나머지 `rank` 검증은 그대로 — `matched_count` 순 정렬이므로 SE가 AI보다 위. import 줄의 `skills_to_capabilities`는 이 파일에서 더 안 쓰이면 그대로 둬도 무방하나, 사용처가 없어지면 import에서 제거.)

- [ ] **Step 4: import 정합성·단위 테스트 확인**

Run: `python -c "from src.agent.supervisor import create_supervisor_graph; from src.analysis.capability import recommend_families; print('ok')"`
Expected: `ok`.

Run: `pytest tests/unit/ -q`
Expected: 전부 PASS (단위 테스트는 neo4j 무관, import 깨짐 없음).

- [ ] **Step 5: Commit**

```bash
git add src/analysis/capability.py src/agent/supervisor.py tests/integration/test_capability_fit.py
git commit -m "feat(analysis): 직군 추천을 스킬 레벨로 — 빈도 상위 25 풀 ∩ 이력서 스킬 개수"
```

---

### Task 3: 표시 변경 (app.js + observe.js)

**Files:**
- Modify: `web/app.js`, `web/observe.js`

- [ ] **Step 1: `app.js` 추천 표시 교체**

`web/app.js:110-112`의 `rec` 블록을 교체한다.

기존:
```javascript
  const rec = (d.recommended_families || [])
    .map((r) => `<div class="fam-row"><span>${esc(r.job_family)}</span><span>${Math.round((r.fit || 0) * 100)}%</span></div>`)
    .join("");
```
교체:
```javascript
  const rec = (d.recommended_families || [])
    .map((r) => `<div class="fam-row"><span>${esc(r.job_family)}</span><span>${r.matched_count}개 일치</span></div>`
      + ((r.matched_skills || []).length ? `<div class="cap-ev">${(r.matched_skills || []).map(esc).join(", ")}</div>` : ""))
    .join("");
```

- [ ] **Step 2: `observe.js` fit 단계 추천 교체**

`web/observe.js`의 `stageData` 중 `key === "fit"` 블록에서 `rec` 줄을 교체한다.

기존:
```javascript
    const rec = (report.recommended_families || []).slice(0, 3).map((r) => `${esc(r.job_family)} ${Math.round((r.fit || 0) * 100)}%`).join(" · ");
```
교체:
```javascript
    const rec = (report.recommended_families || []).slice(0, 3).map((r) => `${esc(r.job_family)} ${r.matched_count}개`).join(" · ");
```

- [ ] **Step 3: JS 문법 확인**

Run: `node --check web/app.js && node --check web/observe.js && echo ok`
Expected: `ok` (node 없으면 이 단계 건너뜀).

- [ ] **Step 4: Commit**

```bash
git add web/app.js web/observe.js
git commit -m "feat(web): 추천 직군 표시를 'N개 일치'(스킬 개수)로 — % 제거"
```

---

### Task 4: API 매핑 테스트 갱신

**Files:**
- Modify: `tests/unit/test_api_mapping.py`

- [ ] **Step 1: 추천 입력 dict를 새 구조로**

`tests/unit/test_api_mapping.py:54`의 `recommended_families` 입력을 새 구조로 교체한다.

기존:
```python
        "recommended_families": [{"job_family": "Software Engineer", "fit": 1.0, "met": ["backend_fw"], "unmet": []}],
```
교체:
```python
        "recommended_families": [{"job_family": "Software Engineer", "matched_count": 5, "matched_skills": ["Java", "Spring"]}],
```
(`:59`의 `assert ...recommended_families[0]["job_family"] == "Software Engineer"`는 그대로 유효.)

- [ ] **Step 2: 통과 확인**

Run: `pytest tests/unit/test_api_mapping.py -q`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_api_mapping.py
git commit -m "test(api): 추천 매핑 테스트를 matched_count 구조로 갱신"
```

---

### Task 5: 통합 검증

**Files:** (없음 — 검증 전용)

- [ ] **Step 1: 전체 단위 테스트**

Run: `pytest tests/unit/ -q`
Expected: 전부 PASS.

- [ ] **Step 2: 통합 테스트 (Neo4j 연결 시)**

Run: `pytest tests/integration/test_capability_fit.py -q`
Expected: PASS (`NEO4J_URI` 있으면 SE>AI 순위 확인, 없으면 skip).

- [ ] **Step 3: 실제 분석 육안 확인**

서버를 빈 포트로 띄우고 `/`에서 DA 성향 이력서(Tableau·SQL·Python 등)로 분석한 뒤 결과 확인:
```bash
uvicorn src.api.main:app --port 8074 --log-level warning
```
Expected: "당신에게 맞는 직군"이 `Data Analyst · 5개 일치` 식으로 뜨고, DA가 DE보다 상위(또는 1위). `/observe?report_id=<id>`의 fit 단계 추천도 "N개" 표시.

- [ ] **Step 4: 서버 종료**

확인 끝나면 uvicorn 종료.
