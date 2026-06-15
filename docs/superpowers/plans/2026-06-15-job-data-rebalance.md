# 직군 데이터 보강·재균형 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Architect 직군을 제거하고, 부족 6개 직군에 타겟 검색어로 공고를 보강 수집해 재적재함으로써 직군별 핵심 스킬 품질을 높인다.

**Architecture:** 코드 변경은 직군 사전(`_JOB_FAMILIES`)에서 Architect 제거 + 수집 쿼리(`collect_raw.py`) 재구성 2곳. 그다음 신규 수집분을 기존 파이프라인 함수로 추출하고 기존 `jobs_filtered.json`에 병합·재필터한 뒤 Neo4j에 재적재한다.

**Tech Stack:** Adzuna API, OpenAI(스킬 추출), Neo4j, Python.

---

## File Structure

- `src/ingestion/pipeline.py` — `_JOB_FAMILIES`에서 `'Architect'` 삭제.
- `scripts/collect_raw.py` — `QUERIES`를 직군별 타겟 검색어로 재구성.
- `scripts/collect_and_merge.py` — 신규 raw를 추출해 기존 `jobs_filtered.json`에 병합·재필터 (신규).
- `tests/unit/test_job_family.py` — Architect 제거 회귀 가드 (신규).

---

### Task 1: Architect 제거

**Files:**
- Modify: `src/ingestion/pipeline.py`
- Test: `tests/unit/test_job_family.py`

- [ ] **Step 1: 회귀 테스트 작성**

```python
# _job_family 직군 판별 — Architect 제거 후 미분류, 기존 직군 보존
from src.ingestion.pipeline import _job_family


def test_architect_removed():
    assert _job_family("Senior Data Architect") is None
    assert _job_family("Solutions Architect") is None
    assert _job_family("TECHNICAL ARCHITECT") is None


def test_known_families_kept():
    assert _job_family("Frontend Engineer") == "Frontend Engineer"
    assert _job_family("Senior Security Engineer") == "Security Engineer"
    assert _job_family("Machine Learning Engineer") == "ML Engineer"
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/unit/test_job_family.py -q`
Expected: `test_architect_removed` FAIL (현재 'architect' 키워드가 "Architect" 반환).

- [ ] **Step 3: `_JOB_FAMILIES`에서 Architect 삭제**

`src/ingestion/pipeline.py:40`의 아래 줄을 삭제한다:
```python
    'Architect':         ['architect','solutions architect'],
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/unit/test_job_family.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ingestion/pipeline.py tests/unit/test_job_family.py
git commit -m "fix(ingestion): Architect 직군 제거 — 잡탕 분류 정리"
```

---

### Task 2: 직군별 타겟 검색어

**Files:**
- Modify: `scripts/collect_raw.py`

- [ ] **Step 1: `QUERIES` 재구성**

`scripts/collect_raw.py:25-34`의 `QUERIES`와 `RESULTS_PER_QUERY`를 교체한다:
```python
# 부족 직군 보강용 검색어 — 직군별 특화어 포함 (SE·DE·DA는 이미 충분해 제외)
QUERIES = [
    # Frontend
    "frontend react", "frontend vue typescript", "react developer",
    # ML
    "machine learning engineer", "mlops engineer", "ml engineer pytorch",
    # Security
    "security engineer", "cybersecurity siem soc", "application security",
    # AI/LLM
    "llm engineer", "generative ai engineer", "ai engineer rag langchain",
    # Data Scientist
    "data scientist", "data scientist machine learning", "data scientist statistics",
    # DevOps
    "devops engineer", "site reliability engineer", "platform engineer kubernetes",
]

RESULTS_PER_QUERY = 15   # 쿼리당 최대 공고 수
```

- [ ] **Step 2: Commit (수집은 Task 4에서 실행)**

```bash
git add scripts/collect_raw.py
git commit -m "feat(ingestion): 부족 직군 타겟 수집 쿼리로 재구성"
```

---

### Task 3: 수집·병합 스크립트

**Files:**
- Create: `scripts/collect_and_merge.py`

- [ ] **Step 1: 스크립트 작성**

신규 raw(`jobs_raw.json`)를 전처리·추출하고, 기존 `jobs_filtered.json`에 id로 병합한 뒤 `filter_by_job_family`(Architect 제거 반영)로 재필터해 저장한다.

```python
# 신규 수집분을 추출해 기존 jobs_filtered.json에 병합·재필터하는 일회성 스크립트
from __future__ import annotations

import json
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

from src.ingestion.pipeline import step_preprocess, step_extract_skills, filter_by_job_family

RAW = ROOT / "data" / "raw" / "jobs_raw.json"
PROCESSED = ROOT / "data" / "processed" / "jobs_raw_processed.json"
WITH_SKILLS = ROOT / "data" / "processed" / "jobs_raw_with_skills.json"
FILTERED = ROOT / "data" / "processed" / "jobs_filtered.json"


def main() -> None:
    # 1. 신규 raw 전처리 + 스킬 추출 (id 캐시로 기추출은 스킵)
    jobs = step_preprocess(RAW, PROCESSED, force=True)
    jobs = step_extract_skills(jobs, WITH_SKILLS)

    # 2. 기존 filtered + 신규(스킬 포함) 병합
    existing = {j["id"]: j for j in json.loads(FILTERED.read_text(encoding="utf-8"))}
    added = 0
    for j in jobs:
        if "skills" in j and j["id"] not in existing:
            added += 1
        if "skills" in j:
            existing[j["id"]] = j

    # 3. 직군 재필터 (Architect 제거 반영)
    merged = filter_by_job_family(list(existing.values()))
    FILTERED.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"신규 {added}개 추가, 필터 후 총 {len(merged)}개 → {FILTERED}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit**

```bash
git add scripts/collect_and_merge.py
git commit -m "feat(ingestion): 신규 수집분 병합·재필터 스크립트"
```

---

### Task 4: 수집·재적재 실행 + 검증

**Files:** (없음 — 데이터 실행)

> ⚠️ 외부 API 호출(Adzuna·OpenAI·Neo4j). `.env`의 `ADZUNA_*`·`OPENAI_API_KEY`·`NEO4J_*` 필요. 신규 공고마다 gpt-4o-mini 추출 비용 발생.

- [ ] **Step 1: Adzuna 수집**

Run: `python scripts/collect_raw.py`
Expected: 18개 검색어 실행, 신규 공고가 `jobs_raw.json`에 누적("신규 N개 추가" 출력).

- [ ] **Step 2: 추출 + 병합**

Run: `python scripts/collect_and_merge.py`
Expected: 신규 공고 스킬 추출(OpenAI) 후 "신규 N개 추가, 필터 후 총 M개" 출력. Architect 공고가 필터에서 빠짐.

- [ ] **Step 3: Neo4j 재적재**

Run: `python -c "from src.ingestion.pipeline import run_ingest_all; run_ingest_all(clear=True)"`
Expected: "Neo4j 완료: M/M개".

- [ ] **Step 4: 공고 원문 백필**

Run: `python scripts/backfill_posting_text.py`
Expected: 원문 속성 백필 완료.

- [ ] **Step 5: 검증 — 직군별 공고 수·핵심 스킬**

Run: `python -m scripts._probe_families`
Expected:
- Architect 직군 사라짐.
- 부족 직군(Frontend·ML·Security·AI/LLM·DS·DevOps)이 ~25–30개로 증가.
- Security 상위에 SIEM·SOC, Frontend에 Vue·React, AI/LLM에 LangChain·RAG 등 특화 스킬 등장.

- [ ] **Step 6: 결과 판단**

특정 직군이 여전히 빈약하거나 특화 스킬이 안 잡히면, Task 2의 검색어를 조정해 Step 1~5를 반복한다. 만족스러우면 완료.
```bash
git add data/raw/jobs_raw.json data/processed/jobs_filtered.json
git commit -m "data: 부족 직군 공고 보강 수집 + Architect 제거 재적재"
```
