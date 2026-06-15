# 직군 데이터 보강·재균형 설계 (Job Data Rebalance)

**작성일:** 2026-06-15
**대상:** `src/ingestion/pipeline.py`(직군 사전), `scripts/collect_raw.py`(수집 쿼리), 데이터 재적재

## 목표

직군별 핵심 스킬이 부정확한 근본 원인(① Architect 잡탕 분류 ② 부족 직군의 표본 부족)을 해결한다. Architect를 제거하고, 부족 직군에 타겟 검색어로 공고를 보강 수집한 뒤 재적재한다.

## 배경 (데이터 진단)

- 직군별 공고 수가 불균형: SE 127·DE 35·DA 30(충분) vs AI/LLM 20·DevOps 25·DS 26·Security 15·ML 11·**Frontend 6**(부족).
- 분류가 틀린 건 **Architect 하나** — `'architect'` 키워드가 SAP·Solutions·Data·Systems Architect를 한 바구니에 모아 정체성이 없다.
- Security·AI/LLM·Frontend·ML은 **분류는 정확**하나 표본이 적어 부수 스킬(Snowflake 등)이 상위로 뜨고 특화 스킬(SIEM·LangChain 등)이 묻힌다.
- 수집 쿼리([collect_raw.py:25-34](scripts/collect_raw.py#L25-L34))가 전부 AI/LLM 중심이라, 다른 직군은 의도적으로 수집된 적이 없다.

## 범위

**포함:** Architect 제거, 직군별 타겟 검색어 정의, 부족 6개 직군 보강 수집, 재적재, 검증.

**제외:** SE·DE·DA(충분한 직군) 추가 수집. 스킬 추출 로직 자체 변경(추출은 정확). 적합도·추천 로직(이미 스킬 레벨).

## 설계

### 1. Architect 제거

[pipeline.py:30-41](src/ingestion/pipeline.py#L30-L41)의 `_JOB_FAMILIES`에서 `'Architect'` 항목을 삭제한다. `_job_family`가 Architect 타이틀에 `None`을 반환하면 `filter_by_job_family`가 그 공고를 제거한다. (재적재 시 반영)

### 2. 직군별 타겟 검색어 (`collect_raw.py` QUERIES 재구성)

부족 6개 직군에 특화어를 포함한 검색어를 준다:

| 직군 | 검색어 |
|---|---|
| Frontend | `frontend react`, `frontend vue typescript`, `react developer` |
| ML | `machine learning engineer`, `mlops engineer`, `ml engineer pytorch` |
| Security | `security engineer`, `cybersecurity siem soc`, `application security` |
| AI/LLM | `llm engineer`, `generative ai engineer`, `ai engineer rag langchain` |
| Data Scientist | `data scientist`, `data scientist machine learning`, `data scientist statistics` |
| DevOps | `devops engineer`, `site reliability engineer`, `platform engineer kubernetes` |

- 쿼리당 `n=15`, `country="gb"` 유지. `jobs_raw.json`에 id 기준 중복 제거하며 누적(기존 collect_raw 동작 그대로).

### 3. 파이프라인 재실행 (데이터 흐름)

기존 `jobs_filtered.json`(321개, 스킬 추출 완료)을 base로 신규만 더한다:

1. **수집** — `collect_raw.py` 실행 → `jobs_raw.json`에 신규 공고 누적.
2. **전처리+추출** — 신규 raw를 `preprocess` → `extract_skills`(OpenAI, **신규 공고만** — id 캐시로 기추출 스킵).
3. **병합+필터** — 기존 `jobs_filtered.json` + 신규(스킬 포함)를 id로 병합, `filter_by_job_family`로 재필터(Architect 자동 제거) → `jobs_filtered.json` 갱신.
4. **재적재** — `run_ingest_all(clear=True)` 로 Neo4j 비우고 전체 재적재.
5. **원문 백필** — `scripts/backfill_posting_text.py`로 공고 원문 속성 복원(기존 절차).

> 2~3단계를 한 번에 돌리는 통합 스크립트가 없으면 plan에서 작은 보강 스크립트(`scripts/collect_and_merge.py`)를 작성한다 — 재현 가능한 수집 파이프라인은 포트폴리오 가치도 있다.

### 4. 검증

- `scripts/_probe_families` 재실행 → 부족 직군이 ~25–30개로 늘고, **Security에 SIEM, Frontend에 Vue/React, AI/LLM에 LangChain/RAG** 등 특화 스킬이 상위로 올라오는지 확인.
- Architect 직군이 사라졌는지 확인.

## 영향받는 테스트

- `_job_family` 관련 단위 테스트가 있으면 Architect 케이스 갱신. 없으면 `_job_family("Senior Data Architect")` 가 `None`(또는 다른 직군)인지 확인하는 단위 테스트 추가.

## 비고

- **비용** — 신규 공고(~100개 예상)마다 gpt-4o-mini 스킬 추출 1회. 저렴하나 OpenAI 키 필요.
- **Adzuna 한도** — 검색어 ~18개 × 1 호출 = 무료 티어(일 250) 내.
- 수집 결과는 Adzuna 검색 품질에 의존하므로, 보강 후에도 특정 직군이 여전히 빈약하면 검색어를 조정해 재수집한다(반복 가능).
