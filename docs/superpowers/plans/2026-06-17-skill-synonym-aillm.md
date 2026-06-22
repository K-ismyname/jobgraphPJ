# 스킬 동의어 통합 + AI/LLM 특화 보강 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** AI·ML·LLM 동의어를 `SKILL_ALIASES`로 통합하고 AI/LLM 특화 검색어로 공고를 보강·재적재해, 분산되던 스킬이 합쳐지고 LangChain·RAG·LLM이 직군 핵심으로 드러나게 한다.

**Architecture:** `SKILL_ALIASES`에 동의어 매핑 추가(정규화) + `collect_raw` AI/LLM 검색어(원천), 이후 기존 파이프라인(`collect_raw`→`collect_and_merge`→재적재)을 재실행한다.

**Tech Stack:** Python(정규화), Adzuna API, OpenAI(추출), Neo4j.

---

## File Structure

- `src/extraction/normalizer.py` — `SKILL_ALIASES`에 AI/ML/LLM 동의어 추가.
- `scripts/collect_raw.py` — AI/LLM 특화 검색어.
- `tests/unit/test_normalizer.py` — 동의어 통합 회귀 테스트.

---

### Task 1: AI/ML/LLM 동의어 통합

**Files:**
- Modify: `src/extraction/normalizer.py`
- Test: `tests/unit/test_normalizer.py`

- [ ] **Step 1: 회귀 테스트 추가**

`tests/unit/test_normalizer.py` 끝에 추가:
```python
def test_normalize_skill_ai_ml_synonyms():
    # 같은 개념의 다른 표기가 하나로 통합되는지
    assert normalize_skill("ML") == "Machine Learning"
    assert normalize_skill("machine learning") == "Machine Learning"
    assert normalize_skill("Artificial Intelligence") == "AI"
    assert normalize_skill("AI") == "AI"
    assert normalize_skill("LLMs") == "LLM"
    assert normalize_skill("LLM") == "LLM"
    assert normalize_skill("GenAI") == "GenAI"
    assert normalize_skill("generative ai") == "GenAI"
    assert normalize_skill("Retrieval Augmented Generation") == "RAG"
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/unit/test_normalizer.py::test_normalize_skill_ai_ml_synonyms -q`
Expected: FAIL (예: `normalize_skill("ML")` → `"ML"`, `"machine learning"` → `"Machine Learning"`로 분산; `"Artificial Intelligence"` → `"Artificial Intelligence"`).

- [ ] **Step 3: `SKILL_ALIASES`에 동의어 추가**

`src/extraction/normalizer.py`의 `SKILL_ALIASES` 딕셔너리 닫는 `}`(약 57행) **직전**에 추가:
```python
    # AI / ML / LLM 동의어 통합
    "artificial intelligence": "AI",
    "ml": "Machine Learning", "machine learning": "Machine Learning",
    "llms": "LLM", "llm": "LLM",
    "genai": "GenAI", "generative ai": "GenAI", "gen ai": "GenAI",
    "rag": "RAG", "retrieval augmented generation": "RAG",
    "retrieval-augmented generation": "RAG",
```

- [ ] **Step 4: 통과 확인 + 기존 회귀**

Run: `pytest tests/unit/test_normalizer.py -q`
Expected: 전부 PASS (기존 케이스 포함).

- [ ] **Step 5: Commit**

```bash
git add src/extraction/normalizer.py tests/unit/test_normalizer.py
git commit -m "feat(extraction): AI/ML/LLM 동의어 통합 — ML↔Machine Learning·AI·LLM·GenAI·RAG"
```

---

### Task 2: AI/LLM 특화 검색어

**Files:**
- Modify: `scripts/collect_raw.py`

- [ ] **Step 1: QUERIES 교체**

`scripts/collect_raw.py`의 `QUERIES`를 AI/LLM 특화로 교체(`RESULTS_PER_QUERY=15` 유지):
```python
# AI/LLM 직군 특화 보강용 검색어
QUERIES = [
    "llm engineer", "rag engineer", "langchain developer",
    "generative ai engineer", "agentic ai engineer", "prompt engineering",
    "ai engineer pytorch", "llmops",
]
```

- [ ] **Step 2: Commit**

```bash
git add scripts/collect_raw.py
git commit -m "feat(ingestion): AI/LLM 특화 수집 쿼리 — llm·rag·langchain·llmops"
```

---

### Task 3: 재수집·재적재 실행 + 검증

**Files:** (없음 — 데이터 실행)

> ⚠️ 외부 API(Adzuna·OpenAI·Neo4j). `.env` 키 필요. 신규 공고마다 gpt-4o-mini 추출 비용. Aura 일시 오류 시 재적재만 재실행.

- [ ] **Step 1: 재적재 전 백업**

```bash
cp data/processed/jobs_filtered.json data/processed/jobs_filtered.bak.json
```

- [ ] **Step 2: Adzuna AI/LLM 공고 수집**

Run: `python scripts/collect_raw.py`
Expected: 8개 검색어 실행, 신규 공고가 `jobs_raw.json`에 누적("신규 N개 추가").

- [ ] **Step 3: 추출 + 병합 (동의어 자동 적용)**

Run: `python scripts/collect_and_merge.py`
Expected: 신규 공고 스킬 추출 후 "신규 N개 추가, 필터 후 총 M개". 추출 시 `normalize_skill`이 동의어 통합 적용.

- [ ] **Step 4: Neo4j 재적재 (동의어 통합 반영, 전 직군) + 원문 백필**

Run: `python -c "from src.ingestion.pipeline import run_ingest_all; run_ingest_all(clear=True)"`
Expected: "Neo4j 완료: M/M개". (일부 누락 시 Aura 일시 오류 — 같은 명령 재실행)

Run: `python -m scripts.backfill_posting_text`
Expected: 백필 완료.

- [ ] **Step 5: 검증 — 동의어 통합 + AI/LLM 특화**

Run: `python -m scripts._probe_families`
Expected:
- AI/LLM 직군에서 `ML`/`Machine Learning` 분산이 사라지고 하나로 합쳐짐.
- AI/LLM 상위 스킬에 **LangChain·RAG·LLM**이 올라오는지.
- 다른 직군(DS·ML)의 AI/ML 표기도 통합됐는지.

- [ ] **Step 6: 결과 판단**

LangChain·RAG가 충분히 잡히고 동의어가 통합됐으면 완료. 약하면 Task 2 검색어 조정해 Step 2~5 반복.
(`data/`는 비추적이라 데이터 커밋은 생략 — Neo4j 적재로 반영.)
