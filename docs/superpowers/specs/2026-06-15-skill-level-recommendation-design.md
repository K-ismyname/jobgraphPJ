# 스킬 레벨 직군 추천 설계 (Skill-Level Family Recommendation)

**작성일:** 2026-06-15
**대상:** `src/analysis/capability.py`, `src/agent/supervisor.py`, `web/app.js`, `web/observe.js` + 관련 테스트

## 목표

"맞는 직군 추천"을 역량(capability) 단위에서 스킬(skill) 단위로 바꿔, Data Analyst와 Data Engineer처럼 역량으로 뭉치면 구분되지 않던 직군을 갈라낸다. 표시는 분수(%)가 아니라 "겹친 스킬 개수"로 한다.

## 배경

역량은 11종으로 거칠게 묶여, DA의 Tableau와 DE의 Spark가 같은 `data_eng` 역량으로 합쳐진다. 그 결과 DA 이력서가 DE로 추천됐다. Neo4j 조사 결과 DA·DE의 빈도 상위 스킬은 자카드 유사도 0.14(거의 다름)로, **스킬 레벨이면 두 직군이 명확히 갈린다**(교집합은 Python·SQL·Snowflake 3개뿐, 나머지는 BI 도구 vs 분산처리 도구로 분리).

## 범위

**포함:**
- `capability.py` — 순수 교집합 함수 추가 + `recommend_families` 스킬 기반 재작성 + 직군 스킬 풀 쿼리.
- `supervisor.py:278` — 호출을 `names`(이력서 스킬) 기반으로 변경, 상위 `[:5]`→`[:3]`.
- `web/app.js` `renderCapability` — 추천 표시를 "N개 일치"로.
- `web/observe.js` `stageData('fit')` — 추천 부분을 `matched_count` 기반으로.
- 테스트 — `test_capability.py`에 교집합 단위 테스트 추가, `test_api_mapping.py`·`integration/test_capability_fit.py`의 추천 구조 참조 갱신.

**제외:**
- **선택 직군 적합도**(`capability_fit`, `job_family_core_capabilities`, `skills_to_capabilities`, `capability_evidence`) — 변경 없음. 역량 충족(N/M) 유지.
- 역량 시드(`SEED_CAPABILITIES`)·`data_eng` 분리 — 하지 않음(스킬 레벨이 우회).

## 현재 상태

[supervisor.py:271-278](src/agent/supervisor.py#L271-L278):
```python
names = [it["skill"] for it in owned if ...]          # 이력서·GitHub·배포 스킬
resume_caps = skills_to_capabilities(names)           # 역량 환산
final["recommended_families"] = recommend_families(neo4j, resume_caps, neo4j.list_job_families())[:5]
```
`recommend_families`(capability.py:93-99)는 직군별 핵심 **역량** 충족률(`fit`)로 정렬해 `[{job_family, fit, met, unmet}]`을 반환한다.

## 설계

### 1. 순수 교집합 함수 (단위 테스트 대상)

`capability.py`에 neo4j 비의존 순수 함수 추가:

```python
def skill_overlap(resume_skills: list[str], family_skills: list[str]) -> tuple[int, list[str]]:
    """이력서 스킬과 직군 스킬 풀의 교집합(정규화 후). (개수, 일치 스킬 원형 목록)."""
```
- 양쪽을 `normalize_skill`으로 정규화해 비교, 일치한 **이력서 측 원형 스킬**을 중복 없이 반환.

### 2. 직군 스킬 풀 쿼리 + 추천 재작성

```python
_FAMILY_SKILLS = """
MATCH (:JobFamily {name: $job_family})<-[:INSTANCE_OF]-(jp)-[:REQUIRES]->(s:Skill)
RETURN s.name AS skill, count(DISTINCT jp) AS w
ORDER BY w DESC LIMIT $n
"""

def recommend_families(neo4j, resume_skills: list[str], families: list[str], n: int = 25) -> list[dict]:
    """직군별 빈도 상위 n개 스킬 풀과 이력서 스킬 교집합 → 개수 순 내림차순."""
    out = []
    for fam in families:
        rows = neo4j.execute_query(_FAMILY_SKILLS, job_family=fam, n=n)
        pool = [r["skill"] for r in rows]
        count, matched = skill_overlap(resume_skills, pool)
        out.append({"job_family": fam, "matched_count": count, "matched_skills": matched})
    return sorted(out, key=lambda x: -x["matched_count"])
```
- 시그니처 변경: `resume_caps`(set) → `resume_skills`(list), 반환 `{job_family, matched_count, matched_skills}`.

### 3. 호출부 변경 (`supervisor.py:278`)

```python
final["recommended_families"] = recommend_families(neo4j, names, neo4j.list_job_families())[:3]
```
`resume_caps`는 `capability_fit`에 계속 쓰이므로 유지.

### 4. 표시

- `app.js` `renderCapability` — "당신에게 맞는 직군" 목록을 `${r.job_family} · ${r.matched_count}개 일치` 로, 그 아래 `matched_skills`를 작게 나열. 기존 `Math.round(fit*100)+'%'` 제거.
- `observe.js` `stageData('fit')` — `recommended_families`의 `matched_count`로 `${r.job_family} ${r.matched_count}개` 표시(기존 `fit*100%` 대체).

## 영향받는 테스트

- `test_capability.py` — `skill_overlap` 단위 테스트 추가(정규화·중복제거·빈입력).
- `test_api_mapping.py` — 추천 항목이 `matched_count`를 갖는지로 단언 갱신(기존 `fit` 참조 시).
- `integration/test_capability_fit.py` — `recommended_families[*]`에서 `fit`→`matched_count` 참조 갱신.

## 검증

1. `pytest tests/unit/ -q` — `skill_overlap` 테스트 통과 + 기존 단위 테스트 무영향.
2. `python -m scripts._probe_da_de` 재실행으로 DA/DE 스킬 분리 재확인(조사용, 이미 0.14 확인).
3. 서버 기동 후 실제 분석 1회: DA 성향 이력서가 추천 1위로 DA(또는 DE보다 상위)에 오는지, 표시가 "N개 일치"인지 육안.

## 비고

선택 직군은 역량(N/M), 추천은 스킬(개수)로 단위가 다르다. 이는 의도된 것 — 선택 직군은 "충분한가"(역량 추상화가 유효), 추천은 "어디에 맞나"(직군을 가르려면 스킬 디테일 필요). `recommend_families`의 역량 버전은 추천에만 쓰였으므로 재작성이 곧 orphan 제거다.
