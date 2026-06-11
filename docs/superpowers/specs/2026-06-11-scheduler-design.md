# 자동 데이터 업데이트 (scheduler) 설계

> 작성일: 2026-06-11
> 대상: 채용공고를 주기적으로 자동 수집·갱신하고, 오래된 공고를 만료 처리하는 scheduler 추가
> 범위: 데이터 파이프라인 영역 (Layer 1 확장). 멀티에이전트·배포와 독립.

---

## 1. 배경과 목표

### 문제
현재 데이터 파이프라인은 **한 번 적재하고 끝인 수동 배치**다. `scheduler.py`는 CLAUDE.md에 계획됐으나 미구현. 그 결과:
- 새 공고가 API에 올라와도 자동 반영 안 됨 (수동 재실행 필요)
- 마감된 공고를 제거하는 로직이 없음 — `is_active` 필드는 있으나 항상 `true`로 죽은 플래그
- 갭 분석이 만료 여부를 무시하고 전체 공고를 사용 → 오래된 요구사항이 "현재 시장"인 척 섞임

### 목표
주기적으로 (1) 새 공고를 자동 수집·적재하고 (2) 오래된 공고를 만료 처리해, **데이터 신선도**를 유지한다. 특히 `posting_trend`(수요 증감)가 의미를 가지려면 데이터가 갱신돼야 한다.

### 확정된 결정
| 항목 | 결정 | 근거 |
|------|------|------|
| 실행 주체 | **모듈 + cron 안내** | 상시 서버 불필요, 무료 제약 회피. scheduler는 1회 실행 작업, 빈도는 cron이 결정 |
| 수집 소스 | **The Muse + RemoteOK** | The Muse가 주력 데이터(60%). The Muse 수집 클라이언트 신규 구현 |
| 빈도 | **월 1회** (`0 0 1 * *`) | 채용 시장 변화 속도 + 무료 API 한도 |
| 만료 처리 | **비활성화** (삭제 아님) | 게시 90일 경과 시 `is_active=false`. 데이터 보존으로 트렌드 분석 유지 |

---

## 2. 컴포넌트

| 파일 | 종류 | 역할 |
|------|------|------|
| `src/ingestion/muse_client.py` | 신규 | The Muse 공개 API 수집 (RemoteOK 클라이언트 패턴) |
| `src/ingestion/scheduler.py` | 신규 | 수집→전처리→추출→적재→만료 오케스트레이션 |
| `src/storage/neo4j_client.py` | 수정 | `deactivate_stale_postings()` 메서드 추가 |
| `src/agent/tools.py` | 수정 | `_JOB_SKILLS_QUERY`에 `is_active = true` 필터 추가 |

기존 `preprocessor`, `skill_extractor`, `pipeline`의 step 함수들, `remoteok_client`, `chroma_client`는 **그대로 재사용**한다. 신규 로직을 최소화한다.

### muse_client.py (RemoteOK 패턴 복제)
The Muse 공개 API는 카테고리별로 공고를 제공한다 (원본 구조: `contents`, `name`, `id`, `categories`, `levels`, `publication_date`, `company`).
```python
_CATEGORIES = ["Software Engineering", "Data Science", "Data and Analytics", ...]

def fetch_by_category(category: str) -> list[dict]:
    # GET https://api.themuse.com/api/public/jobs?category={category}&page=N
    # MUSE_API_KEY 있으면 rate limit 완화, 없어도 동작 (mock 규칙 준수)

def fetch_all(categories=_CATEGORIES) -> list[dict]:
    # 카테고리별 수집 + id 중복 제거 + _collected_category 태그

def save(jobs, path):  # data/raw/jobs_raw_muse.json
```

---

## 3. scheduler 동작 흐름

```
run_scheduled_update():
  1. 수집 (API 호출, 매번 전체 최신 목록)
     ├ muse_client.fetch_all()      → data/raw/jobs_raw_muse.json 갱신
     └ remoteok_client.fetch_all()  → data/raw/jobs_remoteok.json 갱신
  2. 전처리 (기존 함수)
     ├ preprocess_file(muse)        → 직군 분류·필터·섹션 분리
     └ preprocess_remoteok_file()
  3. 추출 (기존 step_extract_skills — ★증분: 신규 id만 LLM 호출)
  4. 적재 (기존 ingest — ★멱등: MERGE/upsert, weight 누적)
     ├ neo4j.ingest_posting()
     └ chroma.ingest_posting()
  5. 만료 (★신규: deactivate_stale_postings(days=90))
  6. 로그: "신규 N개 / 비활성 M개 / 활성 K개 / T초"
```

**핵심 설계:** 수집은 매번 전체를 받지만(API가 증분 미지원), **처리는 증분**이다 — `step_extract_skills`가 이미 가진 id는 건너뛰어 LLM 비용을 안 쓴다. 적재는 멱등이라 기존 공고는 weight만 누적되고 신규만 추가된다. 몇 번 돌려도 안전하다.

---

## 4. 만료 처리 (비활성 방식)

마감일 정보가 API에 없으므로 **게시일(`posted_at`) 기반으로 추정**한다.

### ① 비활성화 (scheduler 단계)
```python
# neo4j_client.py
def deactivate_stale_postings(self, days: int = 90) -> int:
    """posted_at이 days일 지난 JobPosting을 is_active=false로 전환. 비활성화 수 반환."""
    # MATCH (jp:JobPosting) WHERE jp.posted_at < datetime() - duration({days})
    #   AND jp.is_active = true  SET jp.is_active = false
```

### ② 분석에서 제외 (갭 분석 쿼리 필터)
```python
# tools.py _JOB_SKILLS_QUERY — gap_analysis·retrieval이 쓰는 쿼리
MATCH (:JobFamily {name:$job_family})<-[:INSTANCE_OF]-(jp)-[r:REQUIRES|PREFERS]->(s:Skill)
WHERE jp.is_active = true   # ★ 활성 공고만 집계
...
```

### 트렌드는 예외
`posting_trend`(최근 30일 vs 이전 30일)는 **일부러 `is_active` 필터를 적용하지 않는다.** 과거(비활성) 공고가 있어야 수요 증감을 비교할 수 있다. 이것이 삭제 대신 비활성화를 택한 핵심 이유 — 데이터를 보존해 트렌드 분석이 살아있다.

---

## 5. 안전장치 (무인 자동 실행 대비)

| 상황 | 처리 |
|------|------|
| 소스 하나 API 실패 (RemoteOK 다운 등) | 나머지 소스는 진행 — 한쪽이 죽어도 갱신됨 |
| **전체 수집 0개** (모든 API 실패) | 적재·만료 **스킵, 기존 DB 보존** — 빈 데이터로 덮어쓰지 않음 (최우선) |
| 재실행 | 멱등 — 같은 공고 재수집해도 중복 없음, 만료도 반복 안전 |

---

## 6. 실행 방식 (모듈 + cron)

```bash
# 수동 실행
python -m src.ingestion.scheduler

# 자동화 (README에 안내) — 매월 1일 자정
0 0 1 * *  cd ~/jobgraphPJ && python -m src.ingestion.scheduler >> logs/update.log 2>&1
```
scheduler는 빈도를 모른다 — 언제 실행하든 증분 적재 + 만료만 수행한다. 빈도는 cron의 시각 패턴이 결정한다. 코드 수정 없이 cron 설정만으로 월별↔주별 전환 가능.

---

## 7. 테스트 전략

- **muse_client**: mock HTTP 응답으로 수집·파싱·중복제거 검증 (실 API 불필요)
- **deactivate_stale_postings**: posted_at 90일 경계 (89일→활성 유지, 91일→비활성)
- **_JOB_SKILLS_QUERY 필터**: 비활성 공고가 갭 분석 집계에서 제외되는지
- **scheduler**: mock 클라이언트로 전체 흐름 1회 (수집→적재→만료) + 전체 수집 0개 시 기존 보존 검증

---

## 8. 다음 단계 (이번 범위 밖)

- 실제 cron 등록·운영은 사용자 환경에서 (README 안내)
- 배포(HF Spaces) 후에는 앱 내장 스케줄러(APScheduler)로 전환 검토 가능
- The Muse/RemoteOK 무료 API 한도 모니터링
