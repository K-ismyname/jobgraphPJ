# 역량 기반 적합도 설계 — 역량 충족 + 역방향 직군 추천 + 검증 결합

**작성일:** 2026-06-13
**목적:** "직군 평균 × 개별 스킬"로 계산하던 적합도(합격자 이력서가 30%)를, **"핵심 역량 충족"**으로 바꿔 합리적으로 만든다. 동시에 직군을 사용자가 고르는 부담을 없애 **역방향 추천**(이력서 → 맞는 직군)을 제공하고, 각 역량 충족을 **검증 등급**(실증/주장)과 결합한다.

---

## 배경 — 왜 바꾸나 (검증 완료)

진단: 카카오 합격자(Java/Spring/Android 백엔드) 이력서가 Software Engineer 적합도 **30%**. 원인 둘:
1. **직군 평균 편향** — SW Eng 핵심10이 공고 빈도 평균(Python·React·JS·TS 중심)이라, Java 백엔드 전문성과 안 겹침.
2. **계열 미매칭** — MariaDB·SQLite 보유인데 `SQL`/`PostgreSQL` 미충족 처리. 한국 스택(MariaDB·MyBatis)은 영미권 Adzuna 공고에 거의 없어 통째 누락.

수동 역량 사전으로 검증한 결과 — 같은 이력서가 역량 기준 **Software Engineer 83%**(language·database·container·cloud·backend_fw 충족, frontend만 미충족), 역방향 추천도 변별력 확인(백엔드·인프라 직군 83% 상위, AI/ML·Data Analyst 50~60% 하위). 데이터로 작동함을 확인하고 이 설계를 채택한다.

**핵심 통찰:** 역량(`database`)은 개별 스킬(`PostgreSQL`)보다 ① 표본·세분화에 강건하고 ② 직군 변별력이 살아있고 ③ 한국↔영미권 도구 차이를 흡수한다.

---

## 범위

**포함:**
1. 역량 taxonomy + 스킬→역량 매핑
2. 직군별 핵심 역량 도출
3. 적합도 = 핵심 역량 충족 맵 (정밀 % 대신)
4. 역방향 직군 추천 (이력서 → 맞는 직군 정렬)
5. 검증 결합 (역량 충족을 Verified/Claimed로)

**제외 (YAGNI / 앞서 기각):**
- 정밀 단일 적합도 % 채점 — 데이터 한계상 비현실적, 차별점도 아님.
- 자동 CO_OCCURS 클러스터링 — 데이터로 반증됨(잡탕 클러스터).
- 한국 공고 수집 — 약관/소스 제약으로 불가.

---

## 1. 역량 taxonomy + 스킬 매핑

**역량 11개(시드):** `language` `backend_fw` `frontend` `database` `cloud` `container` `cicd` `data_eng` `ml_ai` `mobile` `security`. 매핑 안 되는 스킬은 `other`(적합도 계산 제외).

**매핑 방식:**
- **시드 사전**(수동) — 검증에 쓴 주요 스킬 매핑을 코드 상수 `SKILL_CAPABILITIES: dict[capability, set[skill_lower]]`로. 명백한 것은 사전이 정답.
- **LLM 백필** — 시드에 없는 스킬을 gpt-4o-mini로 11개 역량 중 하나(또는 other)에 일괄 분류하는 1회 배치 스크립트. 결과를 사전에 병합(코드 또는 `data/seeds/skill_capabilities.json`). 사람이 한 번 검수.
- 저장: `Skill.category`(현재 전부 None)에 역량을 채우는 적재 보강 + 백필. gap 계산은 사전을 직접 써도 되고 Neo4j category를 읽어도 됨 — **MVP는 사전(JSON) 직접 사용**(DB 쓰기 의존 최소화).

`normalize_skill` 적용 후 매핑한다(React.js→React→frontend).

## 2. 직군별 핵심 역량 도출

직군 REQUIRES 스킬을 역량으로 환산해 가중 합산, 상위 N개를 "핵심 역량"으로.

```
직군 핵심 역량 = 
  MATCH (직군)<-[:INSTANCE_OF]-(공고)-[:REQUIRES]->(스킬)
  스킬→역량 매핑, 역량별 Σ(요구 공고 수)
  상위 N개 (기본 N=6)
```

검증값: SW Eng 핵심 역량 = [language, frontend, database, container, cloud, backend_fw]. (N은 구현 중 조정 가능 — 6이 검증에서 합리적.)

## 3. 적합도 = 핵심 역량 충족 맵

- 보유 스킬 → 역량 집합(`resume_caps`).
- 직군 핵심 역량 각각에 대해 **충족(보유 역량에 있음) / 미충족**.
- `fit = 충족 핵심 역량 수 / 핵심 역량 수`.
- 충족한 역량은 **어떤 도구로 충족했는지** 함께(예: `database ✓ (MariaDB, SQLite)`).
- 단일 % 대신 **역량별 충족 맵**이 주 산출물.

## 4. 역방향 직군 추천

- 10개 직군 전체에 대해 3의 `fit`을 계산, 내림차순 정렬.
- "당신에게 맞는 직군 top N + 각 충족/미충족 역량".
- 사용자는 직군을 고를 수도 있고(기존), 안 골라도 추천을 받는다.

## 5. 검증 결합 (이 프로젝트 고유)

- 각 충족 역량의 대표 도구가 `consensus`에서 어떤 등급인지 붙임:
  - 도구가 github/deploy로 실증되면 `Verified`, 이력서만이면 `Claimed`.
  - 표시: `backend_fw ✓ Spring (Verified — GitHub)` vs `cloud ✓ AWS (Claimed — 주장만)`.
- 즉 "역량을 갖췄나(적합도)" ⊗ "그게 검증됐나(신뢰도)"를 한 화면에. 채용 사이트가 못 하는 조합.

---

## 데이터 흐름·영향 범위

- 신규: `src/analysis/capability.py` — 역량 taxonomy 상수, `skills_to_capabilities()`, `job_family_core_capabilities(neo4j, fam)`, `capability_fit(resume_caps, core_caps)`.
- 신규: `data/seeds/skill_capabilities.json` (시드 + LLM 백필 병합) + 백필 스크립트 `scripts/backfill_capabilities.py`.
- 수정: `gap_analysis`(tools.py) 또는 신규 노드 — 적합도를 역량 충족 맵으로. `_apply_deterministic_metrics`가 역량 fit 사용.
- 수정: `final_report` / `ReportResponse` — `capability_fit`(맵), `recommended_families`(역방향), 각 역량의 검증 등급.
- 수정: 프론트(`web/app.js` renderReport) — 역량 충족 맵 + 역방향 추천 표시.
- 계열매칭은 이 설계에 **자동 포함**(같은 역량 = 호환).

## 에러 처리

| 상황 | 처리 |
|------|------|
| 스킬이 어느 역량에도 없음 | `other`로 분류, 적합도 계산 제외(로그) |
| 직군 핵심 역량 도출 0개(데이터 없음) | 적합도 N/A, 안내 |
| consensus 없음(검증 소스 0) | 역량 충족은 표시, 검증 등급은 "미검증" |

## 테스트

- `skills_to_capabilities` 단위: MariaDB→database, React.js→frontend, 미지→other.
- `capability_fit` 단위: 핵심 역량 6개 중 5개 충족 → 0.83.
- `job_family_core_capabilities` 통합(실 Neo4j): SW Eng 상위 역량에 backend_fw·database 포함.
- 역방향 추천 통합: 백엔드 스킬셋 → SW Eng/DevOps가 AI/LLM보다 상위.

---

## 비결정 사항(구현 중 확정)

- 핵심 역량 수 N (기본 6, 직군별 가변 가능).
- LLM 백필을 코드 사전에 병합 vs Neo4j category 저장 — MVP는 JSON 사전.
- 공통 역량(language·cloud)이 거의 모든 직군 핵심이라 점수 범위가 좁음 — 필요 시 특화 역량 가중을 높여 변별력 강화(2차).
