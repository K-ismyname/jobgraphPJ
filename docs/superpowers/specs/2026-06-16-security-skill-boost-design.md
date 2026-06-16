# Security 직군 특화 스킬 보강 설계 (Security Skill Boost)

**작성일:** 2026-06-16
**대상:** `src/ingestion/pipeline.py`(직군 키워드), `scripts/collect_raw.py`(검색어), 데이터 재적재

## 목표

Security 직군의 특화 스킬(SIEM·SOC·EDR·취약점·침투테스트)이 잡히도록, 보안 직무 검색어로 공고를 보강 수집하고 그 공고가 분류되게 직군 키워드를 확장한다.

## 배경

Security 36건인데 상위 스킬이 `Python·Terraform·CI/CD·SQL`로 DevSecOps 일반 스킬이고 보안 특화는 SIEM(2건)뿐이다. 원인 둘:
1. **검색어** — 지금까지 `security engineer`류만 수집해 DevSecOps 공고 위주.
2. **키워드** — `['security engineer','appsec','cybersecurity','infosec']`만 있어 `SOC Analyst`·`Penetration Tester`·`Threat Detection`·`Incident Response` 타이틀이 분류 실패(`None`)로 버려진다.

검색어가 스킬의 원천(어떤 공고 본문을 가져오나)이고, 키워드 확장은 그 공고를 Security로 담는 보조다 — 둘 다 필요.

## 범위

**포함:** Security 직군 키워드 확장, `collect_raw` 보안 특화 검색어, 파이프라인 재실행, 검증.

**제외:** 다른 직군. 스킬 추출 로직(불변). `collect_and_merge`(이미 있음, 재사용).

## 현재 상태

- `pipeline.py:39` `'Security Engineer': ['security engineer','appsec','cybersecurity','infosec']`.
- `collect_raw.py` QUERIES = 이전 부족 6직군 검색어. `jobs_raw.json`에 누적.
- `collect_and_merge.py` — Adzuna 원본 변환·추출·병합·재필터(직군 키워드 반영) 스크립트 존재.

## 설계

### 1. Security 키워드 확장

`pipeline.py:39`를 교체:
```python
    'Security Engineer': ['security engineer','appsec','application security','cybersecurity',
                          'infosec','soc analyst','security analyst','penetration test','pentest',
                          'threat detection','incident response','security operations','vulnerability'],
```
- `'security'` 단독은 넣지 않는다("Security Cleared Data Engineer" 등 오분류 방지).
- 순서: 기존 dict에서 Security가 다른 직군보다 뒤라, 복합 타이틀에서 데이터/인프라 직군이 먼저 잡힐 수 있으나, 보안 전용 타이틀(SOC·pentest 등)은 다른 키워드와 안 겹쳐 안전하다.

### 2. `collect_raw` 보안 특화 검색어

`scripts/collect_raw.py`의 QUERIES를 교체:
```python
QUERIES = [
    "security engineer siem", "soc analyst", "threat detection engineer",
    "penetration testing", "incident response security", "cloud security engineer",
    "application security appsec", "vulnerability management",
]
```
- 쿼리당 `n=15`, country=gb. `jobs_raw.json`에 id 중복 제거하며 누적(기존 공고 보존).

### 3. 파이프라인 재실행

1. `python scripts/collect_raw.py` — 보안 공고 수집.
2. `python scripts/collect_and_merge.py` — 신규만 추출 + 병합 + 재필터(확장된 키워드 반영, 기존 Security 외 공고도 재분류됨).
3. `run_ingest_all(clear=True)` 재적재 + `backfill_posting_text`.

## 영향받는 테스트

- `tests/unit/test_job_family.py`: Security 확장 키워드 단언 추가 — `_job_family("SOC Analyst")`·`_job_family("Senior Penetration Tester")`가 `"Security Engineer"`인지.

## 검증

- `python -m scripts._probe_families` → Security 공고 수 증가 + 상위 스킬에 **SIEM·SOC·EDR·threat·penetration·vulnerability** 등 보안 특화가 올라오는지.
- 여전히 약하면 검색어를 조정해 반복.

## 비고

데이터 수집은 Adzuna 검색 품질에 의존하므로, 보강 후에도 특정 보안 분야가 빈약하면 검색어를 더한다. 이전 직군 보강과 동일한 파이프라인(`collect_raw`→`collect_and_merge`→재적재)을 재사용한다.
