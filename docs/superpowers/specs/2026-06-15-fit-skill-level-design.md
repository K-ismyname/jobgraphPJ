# 선택 직군 적합도 스킬화 설계 (Selected-Family Fit → Skill Level)

**작성일:** 2026-06-15
**대상:** `src/analysis/capability.py`(대폭 축소), `src/agent/supervisor.py`, `src/api/schemas.py`·`portfolio.py`, `web/app.js`·`observe.js` + 테스트

## 목표

선택 직군 적합도를 역량(capability) 기반에서 스킬 기반으로 바꾼다. 직군 빈도 상위 10개 스킬 중 이력서가 충족한 개수로 적합도를 매겨, 데이터가 적은 직군에서 꼬리 역량(`ml_ai`·`cloud`)이 핵심으로 오염되던 문제를 없앤다. 역량 개념을 코드에서 통째로 제거한다.

## 배경

Frontend 직군은 공고가 적어(1등 스킬도 5건) 역량 분포가 롱테일이다. 공고 1~2건에서 우연히 등장한 `ml_ai`(LLMs·"AI 도구" 언급)·`cloud`(AWS 1건)가 "핵심 역량 6개" 중 절반에 끼어, 프론트 이력서가 4/6으로 깎였다. 역량은 거친 묶음이라 데이터 양에 취약하다. 추천은 이미 스킬 레벨로 전환했고, 선택 직군도 스킬로 통일하면 단위가 맞고 오염이 사라진다.

## 범위

**포함:** 선택 직군 적합도 계산·표시를 스킬화. 역량 함수·시드 제거. 충족 스킬에 검증등급 표시(기존 "역량별 근거" 흡수).

**제외:** 추천(`recommend_families`)은 이미 스킬 레벨 — 직군 핵심 스킬 조회 함수만 공유로 추출. 다중 URL·홈페이지 등 기존 작업 무관.

## 현재 상태

- `capability.py`: `SEED_CAPABILITIES`·`load_capabilities`·`_cap_map`·`skills_to_capabilities`·`job_family_core_capabilities`·`capability_fit`(역량)·`capability_evidence`·`skill_overlap`·`recommend_families`(스킬, n=25).
- `supervisor.py:275-279`: `resume_caps = skills_to_capabilities(names)`; `core = job_family_core_capabilities(...)`; `capability_fit`(역량); `recommended_families`(스킬); `capability_evidence`.
- `schemas.py`: `ReportResponse.capability_fit: dict|None`, `capability_evidence: list[dict]`.
- `portfolio.py`: `capability_fit`·`capability_evidence` 매핑.
- `app.js:100-119` `renderCapability`: 역량 칩(met/unmet) + "역량별 근거" + 추천.
- `observe.js` `stageData('fit')`: `capability_fit.met/unmet`(역량) + 추천.

## 설계

### 1. capability.py 축소

**신규/유지:**
```python
_FAMILY_SKILLS_QUERY = """..."""   # 기존 유지

def job_family_core_skills(neo4j, job_family: str, n: int = 10) -> list[str]:
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
```
- `recommend_families`는 내부 쿼리를 `job_family_core_skills`로 호출하도록 정리(중복 제거).

**삭제:** `SEED_CAPABILITIES`, `load_capabilities`, `_cap_map`, `_skill2cap`, `_JSON_PATH`, `skills_to_capabilities`, `job_family_core_capabilities`, `capability_fit`(역량), `capability_evidence`. `skill_overlap`은 유지.

### 2. supervisor.py:275-279

```python
        names = [it["skill"] for it in owned if isinstance(it, dict) and it.get("skill")]
        core_skills = job_family_core_skills(neo4j, job_family, 10)
        final["capability_fit"] = {"job_family": job_family,
                                   **skill_fit(names, core_skills, result.get("consensus") or {})}
        final["recommended_families"] = recommend_families(neo4j, names, neo4j.list_job_families())[:3]
```
- `resume_caps`·`capability_evidence` 라인 삭제. import도 정리(`skills_to_capabilities` 등 제거, `job_family_core_skills`·`skill_fit` 추가).

### 3. API (schemas + portfolio)

- `schemas.ReportResponse`: `capability_evidence` 필드 삭제. `capability_fit: dict|None` 유지(구조만 변경).
- `portfolio.py`: `capability_evidence=` 매핑 삭제.

### 4. 표시

**`app.js` `renderCapability`** — `capability_fit`의 새 구조 사용:
- 헤드라인: `${job_family} 핵심 스킬 ${met.length}/${total} 충족`.
- 충족 칩: `met` 각 `{skill, verification}` → `<span class="cap met">스킬 ✓</span>` + 검증등급 배지(색).
- 미충족 칩: `unmet` 각 스킬 → `<span class="cap unmet">스킬 ✗</span>`.
- "역량별 근거" 섹션(`capability_evidence`) 제거. 추천(`recommended_families`) 그대로.

**`observe.js` `stageData('fit')`** — `핵심 스킬 ${met.length}/${total} 충족 (충족 스킬…)` + 추천 `matched_count`.

### 5. 시드 제거

`data/seeds/skill_capabilities.json` 삭제(역량 백필 전용, orphan).

## 영향받는 테스트

- `test_capability.py`: `skills_to_capabilities`·`capability_fit`(역량)·`capability_evidence` 테스트 삭제. `skill_overlap` 유지. `skill_fit` 단위 테스트 추가(충족/미충족/등급).
- `test_capability_fit.py`(integration): `job_family_core_capabilities` → `job_family_core_skills`로 갱신. `recommend_families` 유지.
- `test_api_mapping.py`: `capability_evidence` 입력·단언 삭제, `capability_fit` 새 구조로.

## 검증

1. `pytest tests/unit/ -q` — 갱신·신규 테스트 통과.
2. `python -m scripts._probe_frontend` 재확인은 불필요(역량 경로 삭제). 대신 `job_family_core_skills(neo4j, "Frontend Engineer", 10)`가 JS·Vue·React·HTML·CSS 등 프론트 스킬을 반환하는지 통합/수동 확인.
3. 서버 기동 후 프론트 이력서 분석: 헤드라인이 "핵심 스킬 M/10 충족", 충족 칩에 검증등급, ml_ai·cloud 같은 칸이 없는지 육안.

## 비고

역량(capability)은 "스킬을 적당히 묶어 본질을 본다"는 의도였으나, 묶음이 거칠어 데이터가 적은 직군에서 꼬리가 핵심을 오염시켰다. 스킬 레벨은 세밀해 이 문제가 없고, 추천과 단위가 통일된다. 잃는 것은 "React·Vue 중 하나만 있어도 됨" 같은 추상화인데, 미충족 스킬을 "더 필요한 스킬"로 보여주는 것으로 갈음한다(개별 스킬 갭이 더 구체적이다).
