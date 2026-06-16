# 코치 재설계 — 프로젝트 기반 코칭 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** coach가 GitHub 프로젝트 프로필 + 직군 부족 스킬 + 연계 스킬(CO_OCCURS)을 근거로 "프로젝트 보강 제안 + 연계 학습 추천"을 생성하게 바꾼다.

**Architecture:** `neo4j`에 CO_OCCURS 조회 추가 → coach 툴(`related_skills`) → coach 시드에 GitHub 프로필 주입 + 프롬프트 재작성 → 출력 스키마(project_suggestions/learning_recommendations)·표시 변경. consensus·gap·신뢰도 흐름 무변경.

**Tech Stack:** Python(LangGraph·FastAPI·Neo4j), OpenAI, 정적 JS, pytest.

---

## File Structure

- `src/storage/neo4j_client.py` — `get_co_occurring_skills`.
- `src/agent/tools.py` — `related_skills` 툴.
- `src/agent/nodes.py` — `_COACH_SYSTEM_PROMPT` 재작성, `coach_init`에 profiles, `_build_trace` coach 개수.
- `src/api/schemas.py` — `ProjectSuggestion`·`LearningRecommendation`, ReportResponse 필드 교체.
- `src/api/routers/portfolio.py` — coaching 매핑.
- `web/app.js`·`web/observe.js` — 표시.
- `src/analysis/coach.py` — 삭제.
- 테스트: `test_coach_tools`(신규)·`test_api_mapping`·통합.

---

### Task 1: CO_OCCURS 연계 스킬 조회

**Files:**
- Modify: `src/storage/neo4j_client.py`
- Test: `tests/integration/test_neo4j_job_methods.py`

- [ ] **Step 1: 통합 테스트 추가**

`tests/integration/test_neo4j_job_methods.py` 끝에 추가(실 Neo4j 필요):
```python
def test_get_co_occurring_skills(neo4j_client):
    rel = neo4j_client.get_co_occurring_skills(["Python"], top_n=5)
    assert isinstance(rel, list)
    assert "Python" not in rel   # 입력 스킬은 제외
```
(이 파일의 기존 `neo4j_client` 픽스처/마커를 따른다. 없으면 `Neo4jClient()`를 직접 만들고 `os.getenv("NEO4J_URI")` skipif를 단다.)

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/integration/test_neo4j_job_methods.py::test_get_co_occurring_skills -q`
Expected: FAIL — `AttributeError: 'Neo4jClient' object has no attribute 'get_co_occurring_skills'` (또는 NEO4J_URI 없으면 skip).

- [ ] **Step 3: 메서드 구현**

`src/storage/neo4j_client.py`에 쿼리 상수와 메서드 추가(다른 조회 메서드 근처):
```python
GET_CO_OCCURRING = """
MATCH (s:Skill)-[r:CO_OCCURS]-(o:Skill)
WHERE s.name IN $skills AND NOT o.name IN $skills
RETURN o.name AS skill, sum(r.count) AS w
ORDER BY w DESC LIMIT $n
"""
```
```python
    def get_co_occurring_skills(self, skills: list[str], top_n: int = 8) -> list[str]:
        """주어진 스킬들과 CO_OCCURS로 함께 등장하는 스킬을 가중치 상위로(입력 제외)."""
        if not skills:
            return []
        try:
            rows = self.execute_query(GET_CO_OCCURRING, skills=skills, n=top_n)
            return [r["skill"] for r in rows]
        except Exception as e:
            print(f"[neo4j] CO_OCCURS 조회 실패: {e}")
            return []
```

- [ ] **Step 4: 통과 확인 + 커밋**

Run: `pytest tests/integration/test_neo4j_job_methods.py::test_get_co_occurring_skills -q`
Expected: PASS (또는 skip).
```bash
git add src/storage/neo4j_client.py tests/integration/test_neo4j_job_methods.py
git commit -m "feat(storage): get_co_occurring_skills — CO_OCCURS 연계 스킬 조회"
```

---

### Task 2: `related_skills` 코치 툴

**Files:**
- Modify: `src/agent/tools.py`
- Test: `tests/unit/test_coach_tools.py`(신규)

- [ ] **Step 1: 단위 테스트 작성**

`tests/unit/test_coach_tools.py`:
```python
# coach 툴 — related_skills가 neo4j 연계 스킬을 반환
from src.agent.tools import create_coach_tools


class _FakeNeo4j:
    def get_co_occurring_skills(self, skills, top_n=8):
        return ["TypeScript", "Docker"]
    def get_postings_requiring_skill(self, skill, limit=2):
        return []


def test_related_skills_tool():
    tools = {t.name: t for t in create_coach_tools(_FakeNeo4j())}
    assert "related_skills" in tools
    out = tools["related_skills"].invoke({"skills": ["React", "Python"]})
    assert out["related"] == ["TypeScript", "Docker"]
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/unit/test_coach_tools.py -q`
Expected: FAIL — `related_skills` 툴 없음(KeyError).

- [ ] **Step 3: 툴 추가**

`src/agent/tools.py`의 `create_coach_tools`에서 `verify_suggestion` 정의 뒤, `return [verify_suggestion]` 직전에 추가하고 return을 갱신:
```python
    @tool
    def related_skills(
        skills: Annotated[list[str], "보유 스킬 목록"],
    ) -> dict:
        """보유 스킬과 공고에서 자주 함께 요구되는(CO_OCCURS) 연계 스킬을 반환한다."""
        try:
            return {"related": neo4j.get_co_occurring_skills(skills, top_n=8)}
        except Exception as e:
            return {"related": [], "error": str(e)}

    return [verify_suggestion, related_skills]
```

- [ ] **Step 4: 통과 확인 + 커밋**

Run: `pytest tests/unit/test_coach_tools.py -q`
Expected: PASS.
```bash
git add src/agent/tools.py tests/unit/test_coach_tools.py
git commit -m "feat(agent): related_skills 코치 툴 — CO_OCCURS 연계 스킬"
```

---

### Task 3: 코치 프롬프트·시드 재작성

**Files:**
- Modify: `src/agent/nodes.py`

- [ ] **Step 1: `_COACH_SYSTEM_PROMPT` 교체**

`src/agent/nodes.py`의 `_COACH_SYSTEM_PROMPT = """..."""` 전체를 교체:
```python
_COACH_SYSTEM_PROMPT = """당신은 커리어 코치입니다. 지원자의 GitHub 프로젝트와 직군 부족 스킬을 보고 두 종류의 코칭을 합니다.

1. 프로젝트 보강: 각 GitHub 프로젝트 프로필(summary·tech_stack·observations)과 직군 부족 스킬을 보고, "이 프로젝트에 무엇을 추가/발전시키면 부족 스킬이 코드로 실증되는가"를 제안하세요. observations(예: Dockerfile 없음·테스트 없음)를 우선 활용하세요.
2. 연계 학습: related_skills 툴에 보유 스킬을 넘겨, 자주 함께 요구되는 스킬 중 미보유를 학습 추천하세요.

규칙:
- 갖지 않은 스킬을 이력서에 써넣으라고 하지 마세요. 프로젝트로 실증하거나 학습하라고 안내하세요.
- GitHub 프로젝트가 없으면 project_suggestions는 비우고 연계 학습 위주로 작성하세요.
- 필요하면 verify_suggestion으로 공고 근거를 확인하세요.
- 모든 검토가 끝나면 도구 호출 없이 최종 JSON을 반환하세요.

최종 출력 형식 (코드 펜스 없이):
{{
  "summary": "전체 코칭 방향 2-3문장",
  "project_suggestions": [
    {{"repo": "owner/repo (일반 제안이면 빈 문자열)", "add_skill": "추가하면 좋은 스킬",
      "why": "직군/실증 관점 이유", "how": "이 프로젝트에 어떻게 적용하는지"}}
  ],
  "learning_recommendations": [
    {{"skill": "연계 스킬", "reason": "어떤 보유 스킬과 이어지는지"}}
  ]
}}"""
```

- [ ] **Step 2: `coach_init`에 GitHub 프로필 주입**

`src/agent/nodes.py`의 `coach_init = (...)`(약 288-292행)을 교체:
```python
        profiles = (state.get("github_eval") or {}).get("profiles") or []
        coach_init = (
            "아래 갭 분석을 바탕으로 코칭하세요.\n"
            + json.dumps(report, ensure_ascii=False, indent=2)
            + (("\n\n[GitHub 프로젝트 프로필]\n" + json.dumps(profiles, ensure_ascii=False, indent=2))
               if profiles else "\n\n[GitHub 프로젝트] 없음 — 연계 학습 위주로 코칭하세요.")
        )
```

- [ ] **Step 3: `_build_trace`의 coach 개수 갱신**

`src/agent/nodes.py`의 `_build_trace`에서 coach 관련 부분을 찾아(`suggestion_count`), 새 출력 키 기준으로 교체한다. coaching dict에서:
```python
    coach_block = {
        "project_suggestion_count": len((coaching or {}).get("project_suggestions") or []),
        "learning_count": len((coaching or {}).get("learning_recommendations") or []),
    }
```
기존 `"coach": {"suggestion_count": ...}` 를 `"coach": coach_block` 로 바꾼다. (정확한 위치는 `_build_trace` 내 `coaching` 사용부를 열어 확인 후 교체)

- [ ] **Step 4: import·전체 단위 확인 + 커밋**

Run: `python -c "from src.agent.supervisor import create_supervisor_graph; print('ok')"`
Expected: `ok`.

Run: `pytest tests/unit/ -q`
Expected: PASS (coach 출력 구조 참조 테스트가 있으면 Task 4에서 갱신 — 이 시점 실패 시 Task 4까지 후 재확인).

```bash
git add src/agent/nodes.py
git commit -m "feat(agent): 코치 프롬프트·시드 재작성 — 프로젝트 보강 + 연계 학습"
```

---

### Task 4: 출력 스키마 + portfolio 매핑

**Files:**
- Modify: `src/api/schemas.py`, `src/api/routers/portfolio.py`
- Test: `tests/unit/test_api_mapping.py`

- [ ] **Step 1: `test_api_mapping.py` 갱신**

`final` dict의 coaching과 단언을 새 구조로 교체. 기존 `"coaching": {...suggestions...}` 부분을:
```python
        "coaching": {
            "summary": "전반 방향",
            "project_suggestions": [{"repo": "me/app", "add_skill": "Docker", "why": "DevOps 실증", "how": "Dockerfile 추가"}],
            "learning_recommendations": [{"skill": "TypeScript", "reason": "React와 함께 요구"}],
        },
```
로 바꾸고, 단언에 추가:
```python
    assert resp.project_suggestions[0].add_skill == "Docker"
    assert resp.learning_recommendations[0].skill == "TypeScript"
```
(기존 `suggestions` 단언은 삭제.)

- [ ] **Step 2: `schemas.py` 교체**

`src/api/schemas.py`의 `SuggestionItem` 클래스를 아래 두 클래스로 교체:
```python
class ProjectSuggestion(BaseModel):
    repo: str = ""
    add_skill: str
    why: str
    how: str


class LearningRecommendation(BaseModel):
    skill: str
    reason: str
```
`ReportResponse`에서 `suggestions: list[SuggestionItem] = ...` 줄을 교체:
```python
    project_suggestions: list[ProjectSuggestion] = Field(default_factory=list)
    learning_recommendations: list[LearningRecommendation] = Field(default_factory=list)
```

- [ ] **Step 3: `portfolio.py` 매핑 교체**

`src/api/routers/portfolio.py`의 coaching→suggestions 매핑(114-128 근처)을 교체:
```python
    coaching = final.get("coaching") if isinstance(final.get("coaching"), dict) else {}
    project_suggestions = [
        ProjectSuggestion(repo=s.get("repo", ""), add_skill=s.get("add_skill", ""),
                          why=s.get("why", ""), how=s.get("how", ""))
        for s in (coaching.get("project_suggestions") or []) if s.get("add_skill")
    ]
    learning_recommendations = [
        LearningRecommendation(skill=s.get("skill", ""), reason=s.get("reason", ""))
        for s in (coaching.get("learning_recommendations") or []) if s.get("skill")
    ]
```
그리고 `ReportResponse(...)` 생성부에서 `suggestions=suggestions,`를 교체:
```python
        coaching_summary=coaching.get("summary"),
        project_suggestions=project_suggestions,
        learning_recommendations=learning_recommendations,
```
import 줄에서 `SuggestionItem`을 `ProjectSuggestion, LearningRecommendation`으로 교체하고, `_SUGGESTION_FIELDS` 상수가 더 안 쓰이면 제거.

- [ ] **Step 4: 통과 확인 + 커밋**

Run: `pytest tests/unit/test_api_mapping.py tests/unit/test_api_schemas.py -q`
Expected: PASS.

Run: `python -c "from src.api.main import app; print('ok')"`
Expected: `ok`.

```bash
git add src/api/schemas.py src/api/routers/portfolio.py tests/unit/test_api_mapping.py
git commit -m "refactor(api): 코칭 출력을 project_suggestions·learning_recommendations로"
```

---

### Task 5: 표시 (app.js + observe.js)

**Files:**
- Modify: `web/app.js`, `web/observe.js`

- [ ] **Step 1: `app.js` 코칭 표시 교체**

`web/app.js`의 `const suggestions = (d.suggestions || [])...`(126-136 근처)와 `renderReport`의 코칭 출력부를 교체. `suggestions` 블록을 아래로:
```javascript
  const projects = (d.project_suggestions || [])
    .map((s) => `<div class="suggestion"><div class="head">${esc(s.add_skill)}${s.repo ? ` <span class="prio">(${esc(s.repo)})</span>` : ""}</div>
      <div class="rew">${esc(s.how)}</div>
      <div class="prio">왜: ${esc(s.why)}</div></div>`)
    .join("");
  const learnings = (d.learning_recommendations || [])
    .map((s) => `<div class="suggestion"><div class="head">${esc(s.skill)}</div>
      <div class="prio">${esc(s.reason)}</div></div>`)
    .join("");
```
그리고 `renderReport`의 출력 템플릿에서 `<h3>코칭</h3> ... ${suggestions || ...}` 부분을 교체:
```javascript
    <h3>코칭</h3>
    ${d.coaching_summary ? `<p>${esc(d.coaching_summary)}</p>` : ""}
    <h4>프로젝트 보강</h4>${projects || "<p class='prio'>제안 없음</p>"}
    <h4>배우면 좋은 연계 스킬</h4>${learnings || "<p class='prio'>추천 없음</p>"}
```

- [ ] **Step 2: `observe.js` coach 단계 표시 교체**

`web/observe.js`의 coach 관련 3곳을 새 trace 키로 교체.
- `stageBadges`의 coach(46행 근처): `return [\`제안 ${(t.coach && t.coach.suggestion_count) || 0}\`];` →
```javascript
  if (key === "coach") return [`프로젝트 ${(t.coach && t.coach.project_suggestion_count) || 0}`, `학습 ${(t.coach && t.coach.learning_count) || 0}`];
```
- `stageData`의 coach(134-135행 근처): `개선 제안 N개` →
```javascript
  if (key === "coach")
    return `프로젝트 보강 ${(t.coach && t.coach.project_suggestion_count) || 0}개 · 연계 학습 ${(t.coach && t.coach.learning_count) || 0}개`;
```
- `flowSummary`의 `suggestions`(16행 근처): `const suggestions = (t.coach && t.coach.suggestion_count) || 0;` →
```javascript
  const suggestions = ((t.coach && t.coach.project_suggestion_count) || 0) + ((t.coach && t.coach.learning_count) || 0);
```

- [ ] **Step 3: JS 문법 + 커밋**

Run: `node --check web/app.js && node --check web/observe.js && echo ok`
Expected: `ok`.
```bash
git add web/app.js web/observe.js
git commit -m "feat(web): 코칭 표시를 프로젝트 보강 + 연계 학습 두 블록으로"
```

---

### Task 6: 정리 + 통합 검증

**Files:**
- Delete: `src/analysis/coach.py`

- [ ] **Step 1: 미사용 coach.py 확인 후 삭제**

Run: `grep -rn "from src.analysis.coach\|analysis.coach\|generate_coaching" src/ tests/`
Expected: (빈 출력) — 참조 없음.
```bash
git rm src/analysis/coach.py
```

- [ ] **Step 2: 전체 단위 테스트**

Run: `pytest tests/unit/ -q`
Expected: 전부 PASS.

- [ ] **Step 3: 잔재 확인**

Run: `grep -rn "suggestion_count\|SuggestionItem\|\\bsuggestions\\b" src/ web/ | grep -v "project_suggestion\|_suggestions"`
Expected: 코칭 관련 옛 키 잔재 없음(다른 맥락의 일치는 무시).

- [ ] **Step 4: 서버 육안**

서버를 빈 포트로 띄우고 GitHub URL 포함 분석 → 결과의 "프로젝트 보강"(repo·add_skill·how·why)과 "연계 스킬"(skill·reason)이 채워지는지, observe coach 단계가 "프로젝트 N · 학습 M"으로 뜨는지 확인. 끝나면 서버 종료.
