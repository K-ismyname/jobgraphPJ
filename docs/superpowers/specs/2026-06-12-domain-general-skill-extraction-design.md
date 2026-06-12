# 직무 무관 후보 스킬 추출 (범용화) 설계

**날짜:** 2026-06-12
**상태:** 승인됨 (구현 대기)

## 목표

지원자(이력서·GitHub)의 스킬을 **직군에 상관없이 온전히** 추출해서, 사용자가 고른 10개 직군(Software Engineer / Data Engineer / Data Analyst / Data Scientist / Architect / DevOps·SRE / AI/LLM Engineer / Security Engineer / ML Engineer / Frontend Engineer) 중 어느 것이든 적합도 평가가 제대로 되게 한다.

## 배경 — 왜 필요한가

현재 시스템은 "AI/LLM 엔지니어 적합도"에 사실상 잠겨 있다. 백엔드(카카오 합격) 이력서로 검증한 결과 원인이 둘로 드러났다.

1. **이력서 추출기가 앞 4000자만 본다.** `extract_skills_from_resume`의 `text[:4000]`. F-Lab 이력서(58,455자)의 Java·Spring·Redis는 4000자 이후에 있어 전부 누락됐다(추출 결과: NAS·Ubuntu·클라우드 3개뿐). 도메인 편향이 아니라 **잘림**이 원인.
2. **GitHub 평가자의 스킬 사전이 AI 전용이다.** `_SKILL_KEYWORDS`에 LangChain·FastAPI·PyTorch만 있고 Java·Spring·MySQL이 없다. 백엔드 레포에서 Docker 하나만 잡혔다.

매칭(`gap_analysis`)과 직무→스킬 그래프는 정상이다. Neo4j에 10개 직군·공고 321개·스킬 1079개가 있고, `_JOB_SKILLS_QUERY`도 올바르다. 따라서 **후보 쪽 추출만** 고치면 된다.

## 비범위 (별도 후속)

- synthesizer의 `fit_score`/`confidence_level`이 LLM 임의값인 문제 → 결정적 계산으로 전환은 별개 작업.
- "Backend Engineer" 직군 분리(현재 Software Engineer에 포함) → 데이터/정규화 변경.
- 분야 자동 추천(역방향) → 별개 기능.

## 구성요소 1 — 이력서 추출기: 잘림 제거

**파일:** `src/extraction/skill_extractor.py`

`extract_skills_from_resume`가 이력서 전체 텍스트를 한 번의 호출로 처리한다.

- `text[:4000]` → 안전 상한(예: 100,000자)까지 전체 전송. gpt-4o-mini 컨텍스트(≈128K 토큰)는 현실의 어떤 이력서(F-Lab 58K자 ≈ 2만 토큰)도 한 번에 수용한다. 청크 분할은 하지 않는다(YAGNI — 컨텍스트 초과는 40만 자급 이력서에나 발생).
- 출력 `max_tokens`를 상향(스킬 많은 이력서가 잘리지 않게, 예: 4096).
- 상한을 초과하는 경우 로그로 투명하게 알리고 상한까지만 처리(이후 청크는 필요 시 추가).

**검증:** F-Lab 이력서에서 Java·Spring·Redis가 추출되는지 통합 스모크.

## 구성요소 2 — GitHub 평가자: 직군별 스킬 사전 매칭 (방식 B 정제)

**파일:** `src/agent/evaluators/github_eval.py`, `src/agent/supervisor.py`, `src/agent/tools.py`(또는 `neo4j_client.py`)

하드코딩 `_SKILL_KEYWORDS` 대신 **평가 대상 직군의 스킬 집합**으로 매칭한다. GitHub 평가자의 역할은 "직무 관련 스킬을 코드로 검증"이고, 검증 대상은 그 직군이 요구하는 스킬이므로 목적에 정확히 부합한다. 결정적·무료·자동확장(공고 수집 시 어휘 자동 확대).

**왜 전역(1079개)이 아니라 직군별인가:** Neo4j 스킬 1079개 중 **771개(72%)가 1회성 잡음**(`architecture`, `cloud environments`, `OneSource` 등 LLM이 과대추출한 일반 어구·고유명사)이다. 전부를 사전으로 쓰면 README 산문에 오탐이 폭발한다. 직군별 빈도 높은 스킬만 쓰면 잡음이 제거되고, `gap_analysis`가 비교하는 집합과 **완전히 일치**한다(검증 대상 = 비교 대상). 직군별 빈도≥2 기준 사전 크기: Software Engineer 96, … Frontend Engineer 14(가장 작은 직군도 충분).

- **공유 헬퍼:** `get_job_family_skills(neo4j, job_family) -> list[str]` — `_JOB_SKILLS_QUERY`(가중치=공고수 순)로 직군별 상위 요구/우대 스킬을 조회. `gap_analysis`와 `github_eval`이 같은 소스를 쓴다(단일 진실 공급원).
- `create_github_evaluator()` → `create_github_evaluator(neo4j)`로 시그니처 변경. `evaluate`가 `state["job_family"]`로 대상 직군 스킬을 가져온다(직군별 결과는 캐시 가능).
- 각 스킬명 + 별칭을 README·의존성파일·언어 텍스트에 **단어경계 매칭**(기존 `_word_match` 재사용).
  - 별칭: `normalizer.SKILL_ALIASES`를 역인덱싱해, 정규화명이 같은 모든 표기(예: `postgres`→`PostgreSQL`)를 후보 키워드로 포함. README가 `postgres`라 적어도 `PostgreSQL`로 매칭.
- 출력 형식·`source:"github"`·출처 라벨(의존성/설정파일·주 언어·README)은 유지.
- `supervisor.py`의 `create_supervisor_graph`에서 `create_github_evaluator(neo4j)`로 호출 수정.
- 직군 스킬 조회 실패(연결 실패·빈 결과)면 빈 결과를 반환하고 로그를 남긴다(graceful).

**트레이드오프:** github_eval이 `job_family`에 묶인다(현재 입력으로 알고 있으니 무방). 향후 "여러 직군 동시 평가"로 확장 시 직군별로 재매칭한다.

**검증:** `_skills_from_sources`를 mock 직군 스킬 리스트로 단위 테스트(별칭 매칭 포함). food-delivery 레포 + `Software Engineer`로 통합 스모크(Java·Spring 등 백엔드 스킬 검증).

## 구성요소 3 — 직군명 검증 + 유효 목록 노출

**파일:** `src/storage/neo4j_client.py` 또는 `src/agent/supervisor.py`

- `list_job_families(neo4j) -> list[str]` 헬퍼 추가 — `MATCH (j:JobFamily) RETURN j.name`으로 유효 직군명 조회.
- `run_supervisor` 진입에서 그래프 실행 **전에** `job_family`가 유효 목록에 있는지 검증. 없으면 유효 목록을 담은 명확한 에러를 즉시 반환(앞서 넣은 입력 가드와 동일 패턴). LLM 호출 0 → 환각 사슬 차단.
- Neo4j가 죽어 있어 목록을 못 가져오면 검증을 건너뛰고 `gap_analysis`의 기존 에러 반환에 맡긴다(graceful). `gap_analysis`의 에러 반환은 2차 방어선으로 유지.

**검증:** `"AI Engineer"`(오타) → 에러+유효목록, `"AI/LLM Engineer"` → 통과.

## 데이터 흐름 (변경 후)

```
이력서 PDF/텍스트 ──(전체 텍스트)──→ extract_skills_from_resume(LLM 자유추출) ─┐
                                                                          ├→ consensus → seed_gap → gap_analysis(job_family 검증됨)
GitHub 레포 ──(README·manifest·언어)──→ 직군 스킬 사전 단어경계 매칭 ─────────┘
                                          (get_job_family_skills, gap_analysis와 공유)
```

- 이력서 = LLM 자유 추출(주장하는 스킬을 폭넓게, Claimed)
- GitHub = 직군 스킬 사전 매칭(그 직군이 요구하는 스킬을 코드로 검증, Verified 승격)
- consensus가 둘을 합쳐 검증 등급 산출 → gap_analysis가 선택된 직군과 비교

## 에러 처리

- 이력서: PDF/추출 실패 시 빈 결과(기존 try/except 유지). 상한 초과 시 로그.
- GitHub: 직군 스킬 조회 실패·레포 조회 실패 시 빈 결과 + 로그.
- 직군 검증: Neo4j 조회 실패 시 검증 스킵(백스톱에 위임).

## 테스트 전략

- **단위:** 이력서 전체 텍스트 전달 확인(잘림 제거), GitHub `_skills_from_sources` 직군 스킬 매칭·별칭(mock vocab), `get_job_family_skills`/`list_job_families`/직군 검증(mock).
- **통합:** F-Lab 이력서+food-delivery → Software Engineer 적합도 산출 스모크(Neo4j 필요).
- 기존 테스트(98개) 회귀 없음 확인.
