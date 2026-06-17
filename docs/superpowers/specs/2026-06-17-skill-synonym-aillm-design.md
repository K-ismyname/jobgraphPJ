# 스킬 동의어 통합 + AI/LLM 특화 보강 설계 (Skill Synonym + AI/LLM Boost)

**작성일:** 2026-06-17
**대상:** `src/extraction/normalizer.py`(동의어), `scripts/collect_raw.py`(검색어), 데이터 재적재

## 목표

같은 개념이 표기만 달라 분산되는 문제(`ML`/`Machine Learning`, `AI`/`Artificial Intelligence`, `LLM`/`LLMS`, `Genai`/`Generative AI`)를 `SKILL_ALIASES` 동의어 매핑으로 통합하고, AI/LLM 특화 검색어로 공고를 보강해 LangChain·RAG·LLM이 직군 핵심으로 드러나게 한다.

## 배경

직군별 핵심 스킬 점검에서 두 문제 발견:
1. **동의어 분산** — AI/LLM 직군에 `AI(11)·ML(5)·Machine Learning(5)`처럼 같은 개념이 따로 집계돼 비중이 실제보다 낮게 보임.
2. **AI/LLM 특화 약함** — 타겟 직군인데 상위가 일반 AI/ML·인프라(Python·Docker·Java·Scala) 위주, LangChain·RAG·Transformers가 안 보임(순수 LLM 공고 부족).

`normalize_skill`은 사전 미등록 시 `smart_title`로 표기만 통일할 뿐, **개념 동의어**(ML↔Machine Learning)는 합치지 못한다 — `SKILL_ALIASES`에 매핑이 필요하다.

## 범위

**포함:** `SKILL_ALIASES` 동의어 추가, AI/LLM 특화 검색어, 재수집·재적재, 검증.

**제외:** 직군 키워드(AI/LLM 키워드는 이미 해당 타이틀 포착). 추출 로직 불변.

## 현재 상태

- `normalize_skill`: `SKILL_ALIASES.get(key)` 우선, 없으면 `smart_title`. `ai`→`AI`, `ml`→`ML`, `machine learning`→`Machine Learning`, `llms`→`LLMS`, `genai`→`Genai`(제각각).
- `SKILL_ALIASES`에 ai/ml/llm/genai 동의어 매핑 없음.
- `collect_raw.py` QUERIES = 이전 Security 검색어.

## 설계

### 1. 동의어 통합 (`SKILL_ALIASES` 추가)

각 개념을 데이터 다수·명확 표기로 통일:
```python
"artificial intelligence": "AI",
"ml": "Machine Learning", "machine learning": "Machine Learning",
"llms": "LLM",
"genai": "GenAI", "generative ai": "GenAI", "gen ai": "GenAI",
"rag": "RAG", "retrieval augmented generation": "RAG",
```
- `ai`→`AI`, `llm`→`LLM`은 `smart_title`(`_KEEP_UPPER`)로 이미 처리되나, `Artificial Intelligence`/`ML`/`LLMS`/`Generative AI`/`Genai`가 합쳐진다.
- `ml`→`Machine Learning`(긴 형 — DS·ML 직군에서 이미 다수), `ai`→`AI`(짧은 형 — 다수). 각 개념의 데이터 다수 표기를 표준으로.

### 2. AI/LLM 특화 검색어 (`collect_raw.py`)
```python
QUERIES = [
    "llm engineer", "rag engineer", "langchain developer",
    "generative ai engineer", "agentic ai engineer", "prompt engineering",
    "ai engineer pytorch", "llmops",
]
```
- 쿼리당 `n=15`, country=gb. `jobs_raw.json`에 중복 제거하며 누적.

### 3. 재수집·재적재
`collect_raw` → `collect_and_merge`(동의어 통합·신규 추출 자동 적용) → `run_ingest_all(clear=True)` → `backfill_posting_text` → 검증.

## 영향받는 테스트

- `tests/unit/test_normalizer.py`: 동의어 통합 단언 추가 — `normalize_skill("ML")`·`"machine learning"`이 `"Machine Learning"`으로, `"artificial intelligence"`가 `"AI"`로, `"llms"`가 `"LLM"`으로.

## 검증

- `python -m scripts._probe_families` → AI/LLM 직군에서 ML/Machine Learning이 하나로 합쳐지고, LangChain·RAG·LLM이 상위로 올라오는지. 다른 직군의 AI/ML 표기도 통합됐는지.

## 비고

동의어 통합은 추출·매칭 전반에 영향하나, `SKILL_ALIASES` 우선이라 기존 매핑은 그대로다. AI/LLM 특화는 Adzuna 검색 품질에 의존하므로 보강 후에도 약하면 검색어를 조정한다. 재적재 시 Aura 일시 오류가 나면(이전 사례) 재실행으로 해결된다.
