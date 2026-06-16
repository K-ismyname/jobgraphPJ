# Security 직군 특화 스킬 보강 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Security 직군 키워드를 확장하고 보안 특화 검색어로 공고를 보강 수집·재적재해, SIEM·SOC·threat 등 보안 특화 스킬이 잡히게 한다.

**Architecture:** `_JOB_FAMILIES`의 Security 키워드 확장(분류) + `collect_raw` 보안 검색어(원천), 이후 기존 파이프라인(`collect_raw`→`collect_and_merge`→재적재)을 재실행한다.

**Tech Stack:** Adzuna API, OpenAI(추출), Neo4j, Python.

---

## File Structure

- `src/ingestion/pipeline.py` — Security 키워드 확장.
- `scripts/collect_raw.py` — 보안 특화 검색어.
- `tests/unit/test_job_family.py` — Security 확장 회귀 테스트.

---

### Task 1: Security 키워드 확장

**Files:**
- Modify: `src/ingestion/pipeline.py`
- Test: `tests/unit/test_job_family.py`

- [ ] **Step 1: 회귀 테스트 추가**

`tests/unit/test_job_family.py` 끝에 추가:
```python
def test_security_titles_classified():
    assert _job_family("SOC Analyst") == "Security Engineer"
    assert _job_family("Senior Penetration Tester") == "Security Engineer"
    assert _job_family("Threat Detection Engineer") == "Security Engineer"
    assert _job_family("Incident Response Specialist") == "Security Engineer"
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/unit/test_job_family.py::test_security_titles_classified -q`
Expected: FAIL (현재 키워드가 SOC·penetration 등을 못 잡아 `None`).

- [ ] **Step 3: `_JOB_FAMILIES` Security 키워드 교체**

`src/ingestion/pipeline.py:39`을 교체:
```python
    'Security Engineer': ['security engineer','appsec','application security','cybersecurity',
                          'infosec','soc analyst','security analyst','penetration test','pentest',
                          'threat detection','incident response','security operations','vulnerability'],
```

- [ ] **Step 4: 통과 확인 + 기존 직군 회귀**

Run: `pytest tests/unit/test_job_family.py -q`
Expected: 전부 PASS (기존 `test_known_families_kept`·`test_architect_removed` 포함).

- [ ] **Step 5: Commit**

```bash
git add src/ingestion/pipeline.py tests/unit/test_job_family.py
git commit -m "feat(ingestion): Security 직군 키워드 확장 — SOC·pentest·threat·incident response"
```

---

### Task 2: 보안 특화 검색어

**Files:**
- Modify: `scripts/collect_raw.py`

- [ ] **Step 1: QUERIES 교체**

`scripts/collect_raw.py`의 `QUERIES`를 보안 특화로 교체(`RESULTS_PER_QUERY`는 15 유지):
```python
# Security 직군 특화 보강용 검색어
QUERIES = [
    "security engineer siem", "soc analyst", "threat detection engineer",
    "penetration testing", "incident response security", "cloud security engineer",
    "application security appsec", "vulnerability management",
]
```

- [ ] **Step 2: Commit (수집은 Task 3에서 실행)**

```bash
git add scripts/collect_raw.py
git commit -m "feat(ingestion): 보안 특화 수집 쿼리 — siem·soc·threat·pentest"
```

---

### Task 3: 수집·재적재 실행 + 검증

**Files:** (없음 — 데이터 실행)

> ⚠️ 외부 API(Adzuna·OpenAI·Neo4j). `.env` 키 필요. 신규 공고마다 gpt-4o-mini 추출 비용.

- [ ] **Step 1: 재적재 전 백업**

```bash
cp data/processed/jobs_filtered.json data/processed/jobs_filtered.bak.json
```

- [ ] **Step 2: Adzuna 보안 공고 수집**

Run: `python scripts/collect_raw.py`
Expected: 8개 보안 검색어 실행, 신규 공고가 `jobs_raw.json`에 누적("신규 N개 추가").

- [ ] **Step 3: 추출 + 병합**

Run: `python scripts/collect_and_merge.py`
Expected: 신규 보안 공고 스킬 추출 후 "신규 N개 추가, 필터 후 총 M개". 확장 키워드로 SOC·pentest 공고가 Security로 분류됨.

- [ ] **Step 4: Neo4j 재적재 + 원문 백필**

Run: `python -c "from src.ingestion.pipeline import run_ingest_all; run_ingest_all(clear=True)"`
Expected: "Neo4j 완료: M/M개".

Run: `python -m scripts.backfill_posting_text`
Expected: 백필 완료.

- [ ] **Step 5: 검증 — Security 특화 스킬**

Run: `python -m scripts._probe_families`
Expected:
- Security 공고 수 증가(36 → 더 늘어남).
- Security 상위 스킬에 **SIEM·SOC·threat·penetration·vulnerability·EDR** 등 보안 특화가 올라오는지.

- [ ] **Step 6: 결과 판단**

Security 특화 스킬이 충분히 잡히면 완료. 여전히 약하면 Task 2 검색어를 조정해 Step 2~5 반복.
```bash
git add data/processed/jobs_filtered.json data/raw/jobs_raw.json 2>/dev/null || true
git commit -m "data: Security 보안 특화 공고 보강 수집 + 재적재" || echo "(데이터 비추적 — 커밋 생략)"
```
(`data/`는 비추적이므로 커밋이 무시될 수 있음 — Neo4j 적재로 반영되고 코드/스크립트만 git에 남는다.)
