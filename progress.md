# Job Skill Analyzer — 작업 기록지

작업 절차 / 발생 문제 / 해결 방법을 날짜별로 기록합니다.

---

## [2026-08-05] 문서 최신화 — 코드가 3주 앞서 있고 README가 뒤처져 있던 문제

### 작업 절차

1. 진행상황 점검 요청을 받아 git 이력·문서·테스트를 전수 대조 (단위 테스트 307개 통과 확인)
2. 발견한 문서↔코드 불일치를 README → CLAUDE.md → progress.md 순으로 정정
3. 커밋 후 `jobgraphpj` 원격과 HF Spaces에 반영

### 발생 문제

- **README가 골든셋 도입(7/13) 이전 상태에서 멈춰 있었음.** "갭 목록 자체의 정확도(precision/recall)는
  **아직 측정하지 못했다** … 이것이 **다음 최우선 과제다**"라고 적혀 있었으나, 실제로는 이미 측정했고
  F1 0.713까지 올린 상태였다. 타겟 공고가 "평가 파이프라인 직접 구축"을 우대사항으로 두는데
  **README가 스스로 그걸 못 했다고 말하는 상태**였다.
- **RAGAS 표가 개선 전 baseline이었음.** 7/13에 `reason` 프롬프트 개선으로 Faithfulness가
  0.535 → 0.663으로 올랐는데, README·CLAUDE.md 둘 다 0.535를 "실제 제품 출력"으로 표기하고 있었다.
  세 프롬프트 안을 각 3회 측정한 트레이드오프 실험(강한 제약 시 AR 0.116 붕괴) 자체가
  공개 문서에 없어, 가장 설득력 있는 측정 근거가 커밋 메시지에만 묻혀 있었다.
- **README 실행 안내가 배제 결정과 어긋남.** 데이터 수집 방법으로 `python -m src.ingestion.adzuna_client`를
  안내하는데, CLAUDE.md는 Adzuna를 직군 분석에서 **배제**했다고 명시. 실제 604건은 `scripts/collect_muse.py`
  경로로 모았다. 기술 스택 표의 "데이터 | Adzuna API" 행도 같은 문제.
- **progress.md에 7/13·7/24 세션이 통째로 누락.** 최상단이 `[2026-07-12]`였다.

### 해결 방법

- README `## 평가` 섹션을 **RAGAS(근거 충실도) / 골든셋(갭 정확도)** 두 축으로 재구성하고,
  각각 "재는 것 / 못 재는 것"을 표로 명시 — 두 지표를 섞어 읽지 않게 함
- 프롬프트 3개 안 비교표(원본 / 강한 제약 / 절충)와 **"세게 조이면 다른 축이 무너진다"** 는 결론 추가
- 골든셋 서브섹션 신설 — 측정 결과, 죽은 노이즈 필터 발견, `test_wiring.py`로 재발 방지한 경위
- `정직한 한계`의 "측정 못 했다" 항목을 **"측정했으나 precision 0.511로 낮다 + 원인은 대체 관계 미인식"**
  으로 교체, 골든셋 라벨이 DRAFT라는 한계를 별도 항목으로 분리
- 실행 안내를 `collect_muse.py` → `src.ingestion.pipeline` 2단계로 정정, 기술 스택 표의 데이터 소스·평가 행 갱신
- CLAUDE.md RAGAS 섹션에 "개선 후 현재 값" 문단 추가 (위 표가 baseline임을 명시)

### 결과

- 단위 테스트 307개 통과 (3.63초) — 문서 작업이므로 코드 변경 없음
- 문서가 주장하는 상태와 코드의 실제 상태가 일치

---

## [2026-07-24] 배선 검증 장치 — "정의만 되고 미호출"이라는 반복 결함을 구조로 차단

### 작업 절차

1. 이 프로젝트에서 반복된 버그 유형을 되짚어 공통 패턴을 추출
2. AST 기반 배선 검증 테스트(`tests/unit/test_wiring.py`) 작성
3. 배선을 **일부러 끊어** 테스트가 실제로 잡는지 확인
4. 겸사겸사 `test_url_guard`의 네트워크 의존 제거

### 발생 문제

- **같은 유형의 버그가 세 번 반복됐다** — `is_noise_skill`, `_evidence_mentions_skill`, `consensus` 주입.
  전부 **"함수는 만들었는데 호출부에 연결 안 함"** 이었다. 최악인 이유는 **함수 자체가 정확해서
  단위 테스트는 통과하는데, 실제 파이프라인에서 불리지 않아 프로덕션에서는 무효**라는 점이다.
  테스트 커버리지가 아무리 높아도 이 유형은 잡히지 않는다.
- `test_url_guard`가 실제 DNS 조회(`socket.getaddrinfo`)를 해서 네트워크에 의존했고, 전체 테스트가
  37초씩 걸렸다. 오프라인·CI에서 불안정.

### 해결 방법

- **`tests/unit/test_wiring.py` 신설** — 일반 단위 테스트가 "함수가 올바른가"를 본다면,
  이건 **AST로 "그 함수가 실제로 불리는가"** 를 검증한다.
  - `_MUST_BE_WIRED`에 "반드시 실제 흐름에 연결돼야 하는" 핵심 함수를 **명시적으로 등록**.
    자동 탐지가 아니라 명시 등록을 택한 이유는, 의도적으로 안 쓰는 헬퍼와 구분해야 하고
    그 판단은 프로젝트 지식이라 레포마다 다르기 때문이다.
  - `deploy_eval`이 `safe_get`을 우회해 `httpx.get`을 직접 쓰지 않는지도 검증 — **SSRF 가드 우회 방지**
- `test_url_guard`: `socket.getaddrinfo`를 mock으로 대체. 네트워크 의존을 없애 오프라인·CI에서
  안정적으로 돌게 하고, **DNS rebinding(공개 도메인 → 내부 IP) 시나리오까지** 검증 범위에 추가

### 결과

- 전체 테스트 시간 **37초 → 3초**
- 배선을 끊어보는 방식으로 테스트의 실효성을 직접 확인함 (테스트가 통과하는 테스트가 아님을 검증)

---

## [2026-07-13] 골든셋 도입 — 처음으로 "조언이 맞는가"를 측정 (F1 0.534 → 0.713)

### 작업 절차

1. `reason` 프롬프트 개선안 3개를 각 3회 반복 측정해 트레이드오프 확인 후 절충안 채택
2. 직군별 핵심 스킬 정답 라벨(`data/golden/job_family_core_skills.json`) 작성
3. `src/evaluation/golden_eval.py`로 precision/recall/F1 측정 — 첫 측정 F1 0.534
4. 측정에서 드러난 결함(개념어 오적재)을 추적해 근본 원인 수정 후 재측정 — F1 0.713
5. CLAUDE.md에 갭 목록 정확도 섹션 추가

### 발생 문제

- **어떤 지표도 "갭 목록 자체가 맞는가"를 재지 않고 있었다.** RAGAS Faithfulness는 "말한 것이
  근거에 있는가"만 잰다 — **갭 목록이 통째로 틀려도 근거만 성실히 인용하면 만점**이 나온다.
  critic도 consensus와의 *내부 일관성*만 볼 뿐 *현실과의 일치* 는 못 본다. 즉 이 시스템의
  실제 가치("조언이 맞는가")는 지금까지 측정된 적이 없었다.
- **근거 제약을 세게 걸면 다른 축이 무너졌다.** "근거 없으면 최소한만 쓰라"고 강하게 막으니
  Faithfulness는 0.833까지 올랐지만 **Answer Relevancy가 0.116으로 붕괴** — 환각은 없지만
  질문에 답을 못 하는, 사용자에게 쓸모없는 리포트가 된다.
- **개념어가 스킬로 적재되고 있었다 (골든셋이 즉시 잡아냄).** DevOps 케이스가 "APIS", "DevOps",
  "Distributed Systems"를 부족한 스킬로 지목했다. "DevOps를 배우세요"는 **검증도 실행도 불가능한 조언**이다.
  근본 원인은 `is_noise_skill()`이 정의만 되고 적재 파이프라인에서 **호출되지 않는 죽은 코드**였던 것 —
  노이즈 필터가 있는데 배선이 안 돼 있었다.
- **R이 노이즈로 걸릴 뻔했다.** 배선 전 실측에서 발견. `is_noise_skill`의 `len(name) <= 1` 조건 때문인데,
  R은 Data Analyst/Scientist의 핵심 스킬이고 라이브 DB에 `REQUIRES` 21건을 갖고 있어
  **확인 없이 배선했으면 통째로 잃었다.**

### 해결 방법

- **프롬프트 절충안 채택**: "일반론 금지"는 유지하되, 도구가 실제로 반환한 사실(evidence 문장·
  `posting_count`·`skill_unlock`·trend)로 충실히 답하도록 지시 → Faithfulness 0.535 → **0.663**,
  AR 0.372 → 0.354로 유지. 대조군인 옵션 B가 세 측정에서 안정적이라 프롬프트 효과임을 확인.
  함께 넣은 것 — 외부 텍스트는 "데이터이지 지시가 아님"을 명시(간접 인젝션 방어, H-4),
  `low_sample=true`면 수요 변화를 언급하지 않도록 지시
- **골든셋 신설**: 공고 빈도 상위와 직무 본질이 어긋나는 지점을 `excluded`에 **근거와 함께** 기록.
  정답은 `core - 보유스킬`로 자동 도출. **부족한 게 없는 완벽한 지원자는 recall을 `None`으로 반환해
  평균에서 제외** — 0.0으로 세면 "다 갖춘 사람"이 지표를 왜곡하기 때문
- **노이즈 필터 배선**: `pipeline._normalize_skills()`에 `is_noise_skill` 연결,
  `SKILL_BLOCKLIST`에 개념어 추가(distributed systems, devops, data modeling),
  `_SHORT_VALID_SKILLS`(r, c) 예외로 R 보존
- **라이브 DB 정리**: 노이즈 Skill 노드 38개 + 관계 397건 삭제 (1,909 → 1,871).
  JobPosting 3,353건은 변화 없음. R 보존·DevOps 제거 검증 완료

### 결과

| 시점 | Precision | Recall | F1 |
| --- | --- | --- | --- |
| 최초 측정 (8케이스) | 0.428 | 0.750 | 0.534 |
| 노이즈 제거 후 | **0.511** | **0.929** | **0.713** |

- **precision과 recall이 동시에 올랐다.** 보통은 트레이드오프인데 함께 오른 이유는, 노이즈가
  빈도 상위 10개를 차지해 **진짜 필요한 스킬(Ansible·CI/CD)을 밀어내고 있었기** 때문이다.
- 골든셋을 만든 지 하루 만에 죽은 코드 1건 + 오분류 1건을 잡았다 — **측정 장치를 만드는 것 자체가
  가장 효율적인 디버깅**이었다.

### 남은 결함

- **대체 관계를 모른다.** 남은 오탐의 대부분. 클라우드 3사(AWS/Azure/GCP)를 *전부* 부족하다고
  지목하고, React를 쓰는 지원자에게 Angular·Vue를 요구한다. 핵심 스킬을 100% 보유한 케이스
  (`fe_mid`)에도 5개를 지목해 **precision 0.00**. 원인은 "빈도 상위 10개"를 무조건 채우는
  `_CORE_REQUIRED_N` 휴리스틱.
- 골든셋 라벨은 아직 **DRAFT** — 각 직군의 `core`/`excluded` 판단은 검수 필요
- 케이스가 8개뿐이고, 실제 이력서 PDF가 아니라 손으로 구성한 스킬 목록

---

## [2026-07-12] 외부 코드리뷰 대응 — 보안·데이터 오염·평가 서사 정정 (`fix/security-and-data-integrity`)

시니어 엔지니어/보안 리뷰어 관점의 전수 리뷰를 받고, Critical → High → Medium 순으로 대응.

### 작업 절차

1. **오염 규모를 추측하지 않고 먼저 실측** — 라이브 Neo4j를 직접 쿼리해 미분류 공고의 영향 범위를 수치화
2. H-3(데이터 오염) → C-1/C-2(보안) → H-1(평가 서사) 순으로 수정, 각 단계마다 실측 검증
3. 수정 중 발견한 파생 버그(근거 없는 evidence 반환)를 추가 수정
4. RAGAS 수치를 3회 반복 측정해 기존 결론 자체를 재검증

### 발생 문제

- **미분류 공고 오염이 롤백 후에도 살아있었음 (H-3)**: 2026-06-30 롤백은 `INSTANCE_OF`만 제거했고,
  미분류 공고 2,714건의 `REQUIRES` 관계 11,682개는 그대로 남아 근거 검색·공고 수 집계에 섞이고 있었음.
  실측: **Docker 근거 조회 시 2,528건 중 2,463건(97.4%)이 미분류 공고**. skill_unlock도 97.9% 오염.
- **평가와 제품 경로의 근거 필터가 불일치 (파생 발견)**: `_evidence_snippet`이 스킬 키워드를 못 찾으면
  텍스트 앞부분 450자를 그대로 근거로 반환 → Docker를 한 글자도 언급하지 않는 NVIDIA 공고가
  "Docker가 필요한 근거"로 사용자에게 제시됨. `ragas_eval`은 `_evidence_mentions_skill`로 이런 근거를
  걸러내고 채점하는데 제품 경로엔 그 필터가 없어, **평가는 깨끗한 근거로 하고 사용자는 오염된 근거를 받는 구조**였음.
- **SSRF (C-1)**: `deploy_eval`이 사용자 제출 URL을 검증 없이 fetch(`follow_redirects=True`).
  공개 배포 서버를 프록시 삼아 클라우드 메타데이터(169.254.169.254)·내부 Neo4j 접근 가능.
- **관리자 fail-open (C-2)**: `ACCESS_KEY` 미설정 시 `_is_admin`이 무조건 True → 시크릿을 깜빡하고
  배포하면 방문자 전원이 관리자가 되어 일일 상한이 무력화되고 OpenAI 과금이 무제한 열림.
- **RAGAS "0.70대" 서사가 재현되지 않음 (H-1)**: 3회 반복 측정 결과 옵션 B의 Faithfulness는
  0.533 ± 0.126. 기존 기록(0.70~0.77)은 단일 실행의 운 좋은 값이었음.
- **자기 서술이 서로를 검증하는 논리 오류 (M-3)**: resume+portfolio는 같은 사람이 쓴 문서인데
  "소스 2개 이상"이면 Corroborated를 부여 → 외부 근거 0인데도 "교차 검증됨" 라벨이 붙음.

### 해결 방법

- **오염 차단**: `QUERY_POSTINGS_FOR_SKILL` / `QUERY_SKILL_UNLOCK_COUNT` / `get_skill_trend` 3개 쿼리에
  `INSTANCE_OF` 조건 추가. 검증 결과 근거 공고 5건 전부 분류됨, skill_unlock 2,509 → 53건.
- **근거 정직성**: `_evidence_snippet`이 스킬 언급 문장이 없으면 빈 문자열 반환 → `graph_only`로 정직하게
  표시. 검증: 근거 8건 중 스킬을 실제 언급하는 것 **3/5 → 8/8 (100%)**.
- **표본 부족 가드 (M-6)**: `get_skill_trend`가 표본 10건 미만이면 `delta_pct=None` + `low_sample=True`.
  활성 공고가 직군당 수십 건이라 1건 차이가 ±100%로 튀어 무의미했음.
- **SSRF 가드**: `src/common/url_guard.py` 신설 — http/https만 허용, 호스트가 해석되는 **모든 IP**를 검사해
  사설/루프백/링크로컬 차단, 리다이렉트는 **매 hop 재검증**(302 우회 방지).
- **fail-closed**: 공개 배포(`SPACE_ID`/`ENV=production`)에서 `ACCESS_KEY` 없으면 관리자 불인정.
- **IP별 상한 (M-4)**: 전역 카운터 → IP별. 기본 1회 → 3회. 전역이면 방문자 1명이 아침에 소진하는 순간
  그날 데모가 죽음(채용담당자 포함).
- **신뢰도 등급 정정**: `_SELF_REPORTED_SOURCES`(resume/portfolio) 정의. Corroborated는 외부 관측
  (github/deploy)이 있어야만 부여. 자기 서술만 있으면 개수 무관 Claimed.

### 검증 결과

- 단위 테스트 **269개 통과** (SSRF 차단 13건, IP 격리·fail-closed, 근거 필터, 유실 감지 등 신규 추가)
- **RAGAS 3회 반복 측정 (2케이스, 평균 ± 표준편차)**

  | 평가 대상 | Faithfulness | Answer Relevancy |
  | --- | --- | --- |
  | 옵션 A — `reason` (실제 제품 출력) | 0.535 ± 0.107 | 0.372 ± 0.080 |
  | 옵션 B — 숙련도 Q&A (평가 전용) | 0.533 ± 0.126 | **0.635 ± 0.003** |

  **기존 결론을 스스로 반증함**: 두 옵션의 Faithfulness 차이(0.002)는 변동폭(±0.11~0.13)보다 작아
  근거가 없다. "그래프로 답할 수 없는 질문이라야 Faithfulness가 높다"는 결론은 틀렸다. 유의미한
  차이는 **Answer Relevancy뿐**(0.372 → 0.635, 표준편차 0.003으로 안정적) — 질문 설계의 이점은
  근거 충실도가 아니라 **"질문에 실제로 답하는가"**에 있었다.
- CLI를 기본 3회 반복 + 표준편차 출력으로 전환(`RAGAS_RUNS`) — 단일 실행으로 결론 내는 함정을 코드로 차단.

### 남은 과제 (우선순위)

1. **골든셋 precision/recall (H-2, 최우선)** — Faithfulness는 "말한 게 근거에 있는가"만 잰다.
   **갭 목록 자체가 맞는가**는 어떤 지표도 재지 않는다. 이력서 × 직군 20~30건을 사람이 라벨링해
   end-task 정확도를 재야 한다. 이게 없으면 "평가 파이프라인 구축"이라는 주장이 공허하다.
2. **로컬=라이브 동일 DB (C-3)** — 개발 실험이 곧 프로덕션 변경. 실제로 Adzuna 백필 사고의 원인.
   별도 인스턴스 또는 로컬 Docker Neo4j로 분리 필요.
3. **데이터 재현성 (M-5)** — 604건을 수집한 스크립트가 삭제되어 현 코드로 재현 불가. git 이력에서 복원.
4. gap_agent가 프롬프트로 도구 순서를 지시하고 있어 "에이전트가 스스로 판단"이라는 서사와 실체가
   어긋남 (M-1). "재현성·비용을 위해 탐색 여지를 좁혔다"고 정직하게 문서화하는 편이 낫다.

---

## [2026-07-07]

### 작업 절차
1. `scripts/collect_muse.py` → `src/ingestion/preprocessor.py` → `src/ingestion/pipeline.py` →
   `src/extraction/skill_extractor.py`/`normalizer.py` → `src/storage/neo4j_client.py` 순으로
   Layer 1·2(수집·저장) 전체 코드 리뷰 및 상세 주석 추가
2. `src/agent/` 전체(Layer 3, 12개 파일) 코드 리뷰 및 상세 주석 추가 —
   state.py, evaluators/(resume·github·portfolio·deploy), consensus.py, critic.py,
   gap_agent.py, nodes.py, tools.py, coach_agent.py, supervisor.py
3. 리뷰 중 발견한 문제 6건을 TODO.md에 기록 후 순서대로 수정
4. Layer 4(`src/analysis/`, `src/portfolio/pdf_parser.py`)·Layer 5(`src/evaluation/`) 코드 리뷰 및
   상세 주석 추가 — capability.py, salary_analyzer.py, pdf_parser.py, langfuse_tracer.py, ragas_eval.py
5. Layer 6(`src/api/`) 코드 리뷰 및 상세 주석 추가 — main.py, deps.py, routers/jobs.py,
   routers/portfolio.py, schemas.py, routers/system.py (전체 6개 파일 완료, Layer 1~6 리뷰 종료)
6. 리뷰 완료 후 재점검하며 portfolio.py에서 동시성 버그 2건 추가 발견 후 수정

### 발생 문제
- `scripts/collect_muse.py`의 `is_relevant()`가 제목에 "engineer"만 있으면 통과시켜
  배관공·기계 엔지니어·IT 헬프데스크 같은 무관한 직군이 섞여 들어옴
- `src/agent/supervisor.py`의 `run_supervisor()` — `verified_names` 계산이
  `consensus.get("skills", [])`를 호출하는데 consensus는 `{스킬명: {...}}` 형태라 "skills" 키가
  없어 항상 빈 리스트 → `recommend_job_postings`의 "검증된 스킬 우선" 로직이 항상 무력화됨
- `src/agent/nodes.py`의 gap_agent ReAct 루프 마지막 턴 — LLM이 생성한 텍스트가 어디서도 안 읽히는데
  생성 비용(토큰)은 매번 실제로 발생
- `src/portfolio/github_connector.py` — `parse_github_username()`(죽은 코드), `_SKILL_KEYWORDS`가
  `normalizer.py`의 `SKILL_ALIASES`와 통합 안 된 별도 시스템, `logger` 대신 `print()` 사용
- `src/agent/tools.py`의 `_PORTFOLIO_SKILLS_QUERY` — 정의만 되고 어디서도 실행 안 되는 죽은 상수
- `src/evaluation/ragas_eval.py`의 `_report_to_natural_text()` — 정의만 되고 어디서도 호출 안 되는
  죽은 코드 (리포트 전체를 통째로 평가하던 옛 방식의 흔적으로 추정)
- `src/api/schemas.py`의 `ErrorResponse` — 죽은 코드, `VerificationItem.verification`이 `str`이라
  값 제한 없이 아무 문자열이나 받을 수 있었음 (`InterviewCoaching.type`은 Literal인데 스타일 불일치)
- `src/api/routers/portfolio.py`의 `_demo_usage` 일일 한도 카운터 — "확인 후 증가"가 원자적이지
  않아, `def`(동기) 핸들러가 여러 스레드에서 동시 실행될 때 하루 한도(기본 1회)를 넘길 수 있는
  경쟁 조건(race condition)
- 같은 파일에서 포트폴리오 임시 PDF 재사용 문제 — 같은 `portfolio_report_id`로 두 번째 분석을
  요청하면, 첫 분석 종료 시 이미 삭제된 파일 경로를 조용히 참조해 에러 없이 빈 결과만 나옴

### 해결 방법
- `preprocessor.py`의 `_NON_TECH_TITLE_KEYWORDS`에 `field engineer`/`support engineer`/`it support` 추가
- `supervisor.py`: `.get("skills", [])` 대신 `consensus_dict.items()`를 직접 순회하도록 수정
- `nodes.py`의 `_GAP_SYSTEM_PROMPT` 5번 규칙에 "마지막 턴은 '분석 완료'처럼 한 단어로 답하라" 명시
  (ponytail: 코드 강제가 아닌 프롬프트 지시 — max_tokens 강제 시 도구 호출 인자가 잘릴 위험이 있어 보류)
- `github_connector.py`: `parse_github_username()` 삭제, `_SKILL_KEYWORDS`와 `keywords_for()`를
  합집합으로 통합(단순 교체 시 9개 스킬에서 키워드 유실 확인해 합집합 방식 선택), `print()` → `logger`
- `tools.py`: `_PORTFOLIO_SKILLS_QUERY` 삭제
- `boost_confidence_from_github()`(테스트는 있으나 프로덕션 미연결)는 State 스키마 확장이 필요한
  별도 기능 추가 사안이라 "그대로 두기"로 결정 (사용자 확인)
- `ragas_eval.py`: `_report_to_natural_text()` 삭제
- `schemas.py`: `ErrorResponse` 삭제, `VerificationItem.verification`을
  `Literal["Verified", "Corroborated", "Claimed"]`로 좁힘 (consensus.py가 이 세 값만 만드는 걸 확인 후)
- `portfolio.py`: `threading.Lock`으로 `_demo_usage` 확인+증가를 원자적으로 묶음
- `portfolio.py`: `analyze_portfolio`에서 포트폴리오 경로가 없거나 파일이 실존하지 않으면 404로
  명확히 거절하도록 추가, `_run_analysis` 완료 후 `uploads`에서 해당 항목도 함께 제거

### 결과
- 수정 전부 `py_compile` 문법 검증 통과
- `test_preprocessor.py`(27) / `test_github_boost.py`(2) / `test_job_family_guard.py`(3) /
  `test_supervisor_graph_builds.py`(1) / `test_ragas_eval.py`(4) / `test_api_schemas.py`(2) /
  `test_api_mapping.py`+`test_consensus.py`+`test_umbrella_skills.py`(25) /
  `test_demo_limit.py`+`test_progress_phase.py`+`test_upload_validation.py`(포함 14) 전부 통과
- TODO.md "고칠 부분" 11건 전부 처리(수정 9건 + 정책 결정 2건: 보류·통합)
- 남은 항목: `levels`/`publication_date` 필드 미활용(버그 아닌 기능 아이디어)

---

## [2026-07-08]

### 작업 절차
1. 데이터 흐름 심화 학습 — `preprocessor.py`의 3단계 요건 텍스트 추출(`extract_sections` →
   `extract_bullet_section` → `extract_requirement_sentences`) 각각 실측 구제율 확인,
   `skill_extractor.py`로 넘어가는 실제 데이터 예시 확인, `normalizer.py` → Neo4j 적재까지
   전체 흐름을 실제 데이터로 끝까지 추적
2. 배포 상태 실측 점검 — 사용자가 Neo4j Aura를 켠 뒤 직접 접속해 직군별 공고 수(총 604건),
   스킬 노드 수(1,909개), 직군별 핵심 스킬 Top 10 조회로 데이터 품질 확인
3. `data/raw/` 원본 파일들과 `.gitignore` 이력을 조사해 데이터 수집 스크립트의 재현성 확인 —
   `collect_and_merge.py`(직군별 병합 스크립트), `remoteok_client.py`(RemoteOK 수집)가 삭제되어
   지금 코드로는 배포에 쓰인 9개 직군 데이터를 처음부터 재현할 수 없음을 확인
4. `neo4j_client.py`의 전체 노드·관계 스키마 정리, `PortfolioItem`/`DEMONSTRATES`가 설계는
   됐지만 실제로 쓰이는지 확인하다가 `save_portfolio()`가 죽은 코드임을 발견 → `gap_analysis()`
   도구의 `unverified_required` 버그로 이어져 수정
5. `save_portfolio()`가 유일한 쓰기 경로였다는 걸 확인한 김에, 연결된 죽은 코드
   (`get_portfolio_demonstrated_skills()`, `update_portfolio_confidence()`, 관련 Cypher 상수,
   `portfolio_item_id` 제약)까지 코드·라이브 DB·CLAUDE.md 문서 세 곳 모두에서 정리
6. `supervisor.py`(`evaluator_dispatch`/`create_supervisor_graph`/`run_supervisor`/`run_analysis`)
   학습 중 `ragas_eval.py`의 평가 설계 자체를 재검토 — `_build_evidence_samples()`가 "Is Docker
   required?"처럼 Neo4j로 이미 답 가능한 질문을 채점하고 있어 RAGAS를 쓰는 의미가 약함을 확인
7. `_build_evidence_samples()`를 gap_agent의 실제 LLM reason(`gap_result["missing_required"][].reason`)
   채점으로 재설계, 한국어 원본/영어 번역/`deterministic_reasons` 3가지를 실제로 RAGAS 채점해 비교
8. 그래프에 전혀 없는 순수 텍스트 정보(스킬별 숙련도·연차 표현)를 원문에서 찾아 RAG로 답하게
   하는 `_build_skill_proficiency_samples()`를 신설, `run_ragas_eval()`에 옵션 B로 통합
9. `github_eval.py` 리뷰 중 "프로젝트 이해가 실제로 정확한가?" 검증을 위해 사용자의 실제 레포
   (K-ismyname/jobgraphPJ)로 직접 실행 — `project_type`/`structure_summary`/대부분의
   `skill_assessments`는 정확했으나, `PostgreSQL` 스킬이 잘못 평가되는 환각 사례 발견

### 발생 문제
- `preferred_section`은 `required_section`과 달리 fallback이 없어(1차 실패 시 그냥 빈 문자열),
  실측 결과 필수 텍스트 확보 323건(100%) 대비 우대 텍스트 확보는 121건(37%)에 그침
- `remoteok_client.py`(RemoteOK 수집 코드)가 "수집 데이터도 없는 죽은 코드"라는 근거로 삭제됐는데,
  실제로는 `jobs_remoteok.json`(2.1MB)이 로컬에 존재 — 삭제 당시 판단 근거가 실제와 달랐음
- `data/raw/by_family/*.json`(9개 직군별 분리 파일)를 만든 스크립트(`collect_and_merge.py`)가
  git 이력에 한 번 추가된 뒤 지금은 코드베이스에서 사라짐 — 재현 불가능한 데이터 수집 이력
- `gap_analysis()` 도구가 `neo4j.get_portfolio_demonstrated_skills(owner)`로 confidence를
  조회했는데, 이 데이터를 쓰는 `save_portfolio()`가 실제 흐름에서 한 번도 호출되지 않아
  (배포 Neo4j 확인 결과 `PortfolioItem` 노드 0개) 항상 빈 dict → `unverified_required`가
  구조적으로 절대 채워지지 않는 버그
- `ragas_eval.py`의 `_build_evidence_samples()`가 만드는 `user_input`("Is Docker required for
  the AI/LLM Engineer role?")이 애초에 스킬을 검증 대상으로 고른 이유 자체가 Neo4j `REQUIRES`
  관계라서, 답이 이미 정해진 질문 — 근거 텍스트가 한 단어("Docker")만 있어도 사실 관계상
  틀리지 않아, 30자 미만 근거를 거르는 필터가 "질문 설계 결함"을 근거 길이로 땜질하던 것으로 확인
- 실측 결과 `deterministic_reasons`(사실 조각을 " ".join으로 이어붙인 템플릿)를 RAGAS로 채점하면
  Answer Relevancy가 0에 가깝게 나옴 — "통계+인용" 형식이 RAGAS가 가정하는 자연어 QA 형태와 안 맞음
- `pyarrow` 17.0.0이 설치돼 있어 `ragas`/`datasets` import 시 `AttributeError: module 'pyarrow'
  has no attribute 'json_'` 발생 — `datasets`가 요구하는 `pa.json_()`이 pyarrow 19.0+에서 추가된
  것이라 버전 불일치로 RAGAS 실행 자체가 안 되던 환경 문제
- RAGAS 실측 중 Walmart 공고의 학위 요건 문구("Bachelor's degree in ... Mathematics, Computer
  Science, Information Technology")가 `Mathematics`/`Computer Science`/`Information Technology`
  라는 "스킬"로 잘못 추출되어 그래프에 들어가 있음을 발견 (기존 "Adzuna 데이터 결함"의 구체 사례)
- `github_eval.py`의 `_validate_project_context()`가 `relevant_files` 경로의 "존재 여부"만
  검증하고 "내용이 실제로 그 스킬을 뒷받침하는지"는 검증하지 않아, PostgreSQL 미사용 프로젝트에
  PostgreSQL을 "중급 패턴으로 사용 중"이라 잘못 평가하는 환각이 그대로 통과됨 — 원인은 README가
  환각 방지 예시로 든 문장("Neo4j를 PostgreSQL로 전환" 같은 나쁜 제안의 예)의 키워드를
  `_skills_from_sources()`가 그대로 주웠고, LLM이 이를 근거로 가짜 평가를 만들어낸 것

### 해결 방법
- `preferred_section` fallback 부재는 보류로 결정 — `match_rate`는 `required`만 쓰고, 우대
  신호 패턴 fallback을 만들면 필수 문장과 겹쳐 오탐 위험이 더 크다고 판단 (실측 수치와 함께 기록)
- RemoteOK/병합 스크립트 삭제 건은 코드 수정 없이 TODO.md에 재현성 문제로만 기록
- `gap_analysis()`: `consensus: dict | None = None` 매개변수 추가(LLM 노출 안 함, 기본값 None),
  `nodes.py`의 `make_tools_node()`가 `gap_analysis` 호출 시 `state["consensus"]`를 직접 주입하도록
  수정. Neo4j 왕복(`get_portfolio_demonstrated_skills`) 제거, consensus의 실제 verification
  등급(Verified/Corroborated/Claimed)으로 `unverified_required` 판정. 직접 검증: React(Verified)→
  have_required, Docker(Claimed)→unverified_required로 정확히 분리 확인.
- `neo4j_client.py`: `save_portfolio()`/`get_portfolio_demonstrated_skills()`/
  `update_portfolio_confidence()`와 `UPSERT_PORTFOLIO_ITEM`/`UPSERT_DEMONSTRATES` 상수 삭제,
  `CREATE_CONSTRAINTS`에서 `portfolio_item_id` 제거 + 라이브 Neo4j Aura에서 `DROP CONSTRAINT`
  실행(사전에 `PortfolioItem` 노드 0개 확인), CLAUDE.md 스키마 문서에서도 해당 노드/관계 제거
- `pyarrow`를 17.0.0 → 24.0.0으로 업그레이드해 `ragas`/`datasets` import 오류 해결
  (프로젝트 코드는 pyarrow를 직접 쓰지 않아 안전한 업그레이드로 판단)
- `_build_evidence_samples()`: `user_input`을 "Is X required?"에서 "이 직군에서 X이 부족한
  이유는 무엇인가?"로, `response`를 코드로 지어낸 템플릿에서 `gap_result["missing_required"][].reason`
  (gap_agent가 실제로 생성한 자유 텍스트)으로 교체. 스킬명 매칭은 `normalize_skill()`로 정규화
- `_find_skill_proficiency_excerpts()`/`_answer_from_excerpt()`/`_build_skill_proficiency_samples()`
  신설 — Neo4j 원문(`required_section`)에서 스킬명 근처(80자 이내)에 숙련도/연차 표현(정규식
  `_PROFICIENCY_PATTERN`)이 있는 발췌만 선별해, 그 원문만 근거로 LLM이 숙련도를 답하게 함.
  `run_ragas_eval()`에 `neo4j`/`openai_client` 선택 인자를 추가해 옵션 A(reason)/B(숙련도)를
  함께 실행하고 `RagasScore.kind`로 구분해 종류별 평균을 비교 출력하도록 CLI까지 통합

### 결과
- 배포 데이터 품질 확인: 직군별 604건 공고, 1,909개 스킬 노드, 직군별 핵심 스킬이 직군마다
  뚜렷하게 구분되고 정확함 (Security Engineer→SIEM/Pentest, Data Engineer→Snowflake/Kafka 등)
- `test_gap_core_required.py`/`test_synthesizer_deterministic.py`/`test_deterministic_reasons.py`/
  `test_build_trace.py`(27개) 전부 통과, `test_agent.py` 통합테스트 8개 중 7개 통과
  (1개는 OpenAI API 크레딧 소진으로 실패 — 코드 문제 아님)
- TODO.md에 "고칠 부분" 1건 추가 수정, "보류 결정" 1건 추가 기록
- `neo4j_client.py` 정리 후 단위테스트 241개 전부 통과
- RAGAS 실측 비교: reason(A, LLM 자유생성) Faithfulness 0.33~0.56 / Answer Relevancy 0.31~0.42,
  `deterministic_reasons` Faithfulness 0.33 / Answer Relevancy 0.00, proficiency(B, 그래프에
  없는 텍스트 정보) Faithfulness 0.70~0.77 / Answer Relevancy 0.59~0.64 — "그래프로 대체 불가능한
  질문 + 자연어 답변" 조합이라야 RAGAS가 의미 있는 지표를 낸다는 결론. `python -m
  src.evaluation.ragas_eval` 실제 실행으로 통합 확인 완료
- TODO.md에 "고칠 부분" 2건 추가 수정(neo4j_client 정리, RAGAS 재설계), "기능 아이디어" 1건
  (스킬 추출 오탐 — 학위 요건이 스킬로 잘못 추출됨) 추가 기록
- `github_eval.py`를 실제 레포로 실행 검증: 전체 프로젝트 이해(project_type/structure_summary)와
  대부분의 skill_assessments는 정확했음. PostgreSQL 환각 사례는 미수정 상태로 TODO.md에 기록만 함

---

## [2026-06-29]

### 작업 절차
1. gap_trace 버그 수정 커밋 (`_build_trace`가 CoachState에서 `iteration`을 못 읽던 문제)
2. 전체 프로젝트 진단 — 설계·워크플로·코드품질·테스트·환경 5개 축
3. 진단 결과 체크리스트화 (`docs/checklist_diagnosis.md`)
4. 🔴 C-1a·C-1b + 🟠 H-1 묶어서 처리
5. 🟠 H-2 `gap_analyzer.py` 삭제
6. 🟡 M-1·M-2·M-3 묶어서 처리

### 발생 문제
- `gap_trace` 커밋 후 테스트 4개 미확인 상태로 "검증 완료" 보고 → 진단 시 발견
  - `test_build_trace` 2개: `_build_trace`가 이제 `gap_trace`에서 읽는데 테스트는 `messages` 주입 방식 유지
  - `test_agent` 2개: `call_model`·`coach_call_model`이 서브그래프 내부로 이동했는데 최상위 노드로 기대
- `gap_analyzer.py`가 `src/`에서 import 없이 테스트에서만 살아있던 데드코드 발견
- `market_insights`·`graph_query` 툴이 프롬프트 안내 없이 바인딩만 된 상태 (토큰 낭비)

### 해결 방법
- H-1: `synthesizer`를 `gap_result` 가드 밖으로 이동 → 항상 executed_nodes에 포함
- C-1a: `test_build_trace` — `gap_trace` 계약으로 갱신 (messages → gap_trace 주입)
- C-1b: `test_agent` — 서브그래프 내부 노드 대신 부모 노드(`gap_agent`, `coach_agent`) 검증으로 변경
- H-2: `gap_analyzer.py` + `test_gap_analyzer.py` 삭제 (실제 갭 분석은 `tools.py gap_analysis`가 담당)
- M-1: `create_nodes()` 미사용 `neo4j` 파라미터 제거 (호출부 2곳 동시)
- M-2: `market_insights`·`graph_query` 툴 목록에서 제거
- M-3: `_STRENGTH_PRIORITY` ponytail 주석 추가

### 결과
- 186 passed (단위) / 통합 12 passed
- 남은 항목: 🟢 L-1(iterations 라벨링), L-2(서브그래프 messages 전파 테스트) — 급하지 않음

---

## [2026-06-27]

### 작업 절차

1. **Coach 이종 언어 버그 수정**: Java가 Python 프로젝트에 `project_suggestions`로 들어가는 문제. `nodes.py`의 `_COACH_SYSTEM_PROMPT`에 두 규칙 추가 — `code_anchor=false`인 스킬은 제외, 이종 언어는 `learning_recommendations`로만. `generate_report`에서 `skill_assessment`마다 `code_anchor` 필드 계산(`bool(relevant_files)`).

2. **RAGAS 평가 인프라 구축**: `faithfulness` / `answer_relevancy` 측정을 위한 근거 텍스트(required_section) 파이프라인 전체 구축.
   - `neo4j_client.py`: `ingest_posting()` 끝에 `set_posting_sections()` 연동, `QUERY_POSTINGS_FOR_SKILL`에 required_section 있는 공고 우선 정렬 추가.
   - `preprocessor.py`: `_REQ_SIGNALS` 패턴 확장 — Adzuna 평문 스타일("must have", "looking for" 등) 추가로 추출률 2% → 40%.
   - `collect.py`: `_normalize_adzuna()`에 description → required/preferred 섹션 파싱 3단계 fallback 추가.
   - `ragas_eval.py`: 테스트 케이스를 AI/LLM Engineer 중심으로 업데이트.

3. **수동 backfill**: 기존 3,294개 공고에는 required_section 없음 → 직군 3개(AI/LLM Engineer, Software Engineer, Data Engineer) 재수집 (pages=3) → Neo4j에 총 1,026개 공고 저장.

4. **RAGAS 측정 결과**: Faithfulness=0.250, AnswerRelevancy=0.876.

5. **커밋**: `feat(evaluation): RAGAS 평가 인프라 구축 + 공고 텍스트 저장` (78f0b227)

### 발생 문제

- **required_section 0개 저장**: `extract_sections()`가 HTML 없는 Adzuna 평문에서 실패 → `if req or pref:` 조건이 False → `set_posting_sections()` 미호출. 해결: description 전체를 text[:2000]으로 직접 저장하는 스크립트 실행 (1,026개 처리).
- **source_id 불일치**: `QUERY_POSTINGS_FOR_SKILL`이 구공고(`remoteok-*`, `muse-*`)를 먼저 반환 → required_section 없는 공고가 근거로 사용됨. 해결: ORDER BY priority 추가 (required_section 있는 공고 우선).
- **Adzuna 평문 패턴 미매칭**: `_REQ_SIGNALS`에 "must have", "you should have" 등 Adzuna 스타일 패턴 누락 → 추출률 2%. 해결: 패턴 10개 추가 → 40%.
- **Coach Java 포함**: `relevant_files` 없는 skill_assessment에 LLM이 새 파일 경로를 만들어 project_suggestions에 Java를 추가. 해결: `code_anchor` 필드 + 이종 언어 규칙 추가.

### 해결 방법

- Faithfulness=0.250으로 낮은 이유: Adzuna 공고가 "required" 명시 없이 간접 표현("familiarity with X is a plus") 사용 → NLI 매칭 어려움. 구조적 한계이므로 개선 방향은 RAGAS용 영문 자연어 answer 생성 또는 추가 공고 수집으로 커버리지 확보.

---

## 2026-06-09

### 작업 절차

#### Phase 1 — 프로젝트 뼈대 초기화
- CLAUDE.md 작성 (기술 스택, 네이밍 컨벤션, 개발 순서 확정)
- `src/`, `tests/`, `data/` 폴더 구조 생성
- `requirements.txt`, `.env.example` 작성

#### Phase 2 — Layer 1·2 구현 (데이터 수집·저장)
- `src/ingestion/adzuna_client.py` — Adzuna API 호출 + mock fallback
- `src/extraction/skill_extractor.py` — LLM 기반 기술 추출
- `src/extraction/normalizer.py` — 동의어 통합 (React.js → React 등)
- `src/storage/neo4j_client.py` — Neo4j MERGE 쿼리 (NetworkX fallback)
- `src/storage/chroma_client.py` — Chroma 벡터 저장·검색

#### Phase 3 — Layer 3 구현 (LangGraph 에이전트)
- `src/agent/state.py` — AgentState TypedDict (MAX_ITERATIONS=5)
- `src/agent/tools.py` — resume_search, graph_query, job_db_query, github_check, ask_human (HITL)
- `src/agent/nodes.py` — call_model, generate_report 노드
- `src/agent/graph.py` — StateGraph 조립, Corrective RAG 루프, HITL interrupt

#### Phase 4 — Layer 5 구현 (평가)
- `src/evaluation/langfuse_tracer.py` — Langfuse 4.x `@observe` 래퍼 + LocalTraceRecord
- `src/evaluation/ragas_eval.py` — RAGAS 0.4.x SingleTurnSample 기반 평가

#### Phase 5 — 테스트 작성
- `tests/unit/test_normalizer.py` — normalize_skill() 5개 케이스
- `tests/unit/test_gap_analyzer.py` — match_rate, top_missing, mock run_gap_analysis
- `tests/unit/test_pdf_parser.py` — 잘못된 파일 예외 처리
- `tests/integration/test_agent.py` — graph compile, state fields, MAX_ITERATIONS 검증

#### Phase 6 — 파인튜닝 노트북 작성
- `finetune/01_generate_dataset.ipynb` — Adzuna 수집 + GPT-4o-mini 레이블링
- `finetune/02_finetune.ipynb` — Unsloth + QLoRA, Qwen2.5-1.5B-Instruct
- `finetune/03_evaluate.ipynb` — 베이스 vs 파인튜닝 모델 비교

#### Phase 7 — 데이터셋 품질 개선
1차 수집: Adzuna 323개 → GPT-4o-mini 레이블 → 271개 샘플 생성

**품질 문제 발견 및 해결:**

| 문제 | 원인 | 해결 |
|------|------|------|
| concept 카테고리 54.8% | GPT가 "Machine Learning", "AI" 등 직무 도메인어를 기술로 추출 | ABSTRACT_CONCEPTS 필터 적용 → 39.2% |
| 대소문자 중복 | "Machine Learning" 106회 + "machine learning" 69회 별도 집계 | ALIASES 사전 + smart_title() 정규화 후 dedup |
| concept 중 비기술 항목 | "Leadership", "STEM", "SC Clearance" 등 여전히 존재 | GPT-4o-mini 재판단: 271개 → keep 150 / remove 121 |
| LLM 5종 중복 | "LLM", "LLMs", "Large Language Models (llms)" 등 분산 | LLM_VARIANTS 집합으로 "LLM" 통합 |

**최종 카테고리 분포 (1차 정제 완료):**
- concept: 54.8% → 27.7%
- framework: 14.8% → 23.6%
- language: 12.5% → 20.0%
- 샘플: 271개 → 249개 (train 215 / test 34)

#### Phase 8 — 데이터셋 보강 (진행 중)
**문제:** 타겟 스택 등장 빈도 부족
- LangGraph 2회, LangChain 0회, RAG 1회, Chroma/Neo4j/RAGAS/Langfuse 0회

**해결:** Adzuna 타겟 쿼리 12개 추가
```
langchain langgraph agent, rag retrieval augmented generation,
vector database llm, agentic ai engineer, langfuse evaluation llm,
neo4j graph database engineer, chroma weaviate vector search 등
```
수집: 445개 → 레이블링 + 후처리 → 기존 249개에 병합 (진행 중)

---

### 발생 문제 및 해결 요약

| 문제 | 해결 |
|------|------|
| nvidia-smi FileNotFoundError (Mac) | subprocess try/except (FileNotFoundError, CalledProcessError) |
| VS Code CWD = `finetune/` 인데 `finetune/dataset` 경로 사용 | `Path('finetune/dataset')` → `Path('dataset')` |
| SkillGap ValidationError (difficulty int, job_demand float) | `difficulty="학습 장벽 낮음"`, `demand=9` (Literal/int 타입 준수) |
| normalize_skill 테스트 실패 | SKILL_ALIASES에 실제로 있는 alias만 테스트 케이스 사용 |
| LangGraph 버전 불일치 (요구: ~=0.2.0, 설치: 1.1.6) | requirements.txt → `langgraph>=1.0.0` |
| Langfuse 4.x import 경로 변경 | `from langfuse.decorators` → `from langfuse import observe` |
| RAGAS 0.4.x API 변경 | `Dataset.from_dict` → `EvaluationDataset` + `SingleTurnSample` |
| GPT JSON 파싱 오류 (2개 skip) | 기존 `try/except + None 반환` 처리로 자동 제외 |

---

#### Phase 9 — mock 코드 전면 제거

**배경:** "앞으로 가짜 데이터 쓰는 일은 없어" 지시에 따라 5개 파일의 모든 mock/fallback 코드를 제거하고, 환경변수 없으면 EnvironmentError가 발생하도록 변경.

**변경 파일 및 내용:**

| 파일 | 제거 내용 | 변경 결과 |
|------|-----------|-----------|
| `src/ingestion/adzuna_client.py` | MOCK_JOBS 상수, `jobs.json` fallback | `ADZUNA_APP_ID/KEY` 없으면 EnvironmentError |
| `src/extraction/skill_extractor.py` | `_mock_extract_job_skills()`, `_mock_resume_extraction()`, USE_LOCAL_MODEL 분기 | `ANTHROPIC_API_KEY` 없으면 EnvironmentError |
| `src/storage/neo4j_client.py` | NetworkX fallback, `_is_mock()`, `_mock_store`, mock 분기 전체 | `NEO4J_URI` 없으면 EnvironmentError |
| `src/agent/nodes.py` | `anthropic_client` 파라미터, mock LLM 분기 | 환경변수에서 직접 읽고 없으면 EnvironmentError |
| `src/analysis/coach.py` | `_mock_coaching()` 함수, fallback 분기 | `Anthropic` 클라이언트 직접 주입 필수 |

**추가 정리:**

- `src/agent/graph.py`: `create_graph()` 시그니처에서 `anthropic_client` 파라미터 제거, `__main__` 블록의 "mock 분석 실행" 주석 제거
- `tests/integration/test_agent.py`: `anthropic_client=None` 인자 제거, ANTHROPIC_API_KEY 없으면 테스트 skip (`pytest.mark.skipif`), 키 없을 때 EnvironmentError 발생 검증 테스트 추가

---

### 발생 문제 및 해결 요약

| 문제 | 해결 |
|------|------|
| nvidia-smi FileNotFoundError (Mac) | subprocess try/except (FileNotFoundError, CalledProcessError) |
| VS Code CWD = `finetune/` 인데 `finetune/dataset` 경로 사용 | `Path('finetune/dataset')` → `Path('dataset')` |
| SkillGap ValidationError (difficulty int, job_demand float) | `difficulty="학습 장벽 낮음"`, `demand=9` (Literal/int 타입 준수) |
| normalize_skill 테스트 실패 | SKILL_ALIASES에 실제로 있는 alias만 테스트 케이스 사용 |
| LangGraph 버전 불일치 (요구: ~=0.2.0, 설치: 1.1.6) | requirements.txt → `langgraph>=1.0.0` |
| Langfuse 4.x import 경로 변경 | `from langfuse.decorators` → `from langfuse import observe` |
| RAGAS 0.4.x API 변경 | `Dataset.from_dict` → `EvaluationDataset` + `SingleTurnSample` |
| GPT JSON 파싱 오류 (2개 skip) | 기존 `try/except + None 반환` 처리로 자동 제외 |
| `create_nodes()` 시그니처 변경 후 `graph.py` 불일치 | `anthropic_client` 파라미터 제거 + CLI 블록 정리 |

---

### 다음 작업
- [ ] `.env`에 NEO4J_URI 연결 (Neo4j Aura 무료 티어 계정 발급)
- [ ] 데이터셋 보강 완료 확인 (타겟 스택 등장 빈도 재검증)
- [ ] `concept_decisions.json` 신규 항목 LLM 재판단 실행
- [ ] Colab T4에서 `02_finetune.ipynb` 실행
- [ ] `03_evaluate.ipynb`로 베이스 vs 파인튜닝 비교

---

## 2026-06-10

### 작업 절차

#### Phase 10 — Agentic RAG 에이전트 3대 구조 문제 해결

**문제 1: 스킬명을 시맨틱 검색으로 찾으면 노이즈 많음**
- 해결: `verify_skills` 배치 툴 추가 (tools.py)
  - Neo4j → 해당 스킬을 REQUIRES하는 공고 source_id 조회
  - Chroma에서 source_ids 필터로 해당 공고만 검색 (유사도 검색 아님)
  - section_type="required" 우선 → 없으면 전체 fallback

**문제 2: 스킬 5개를 순차 호출 → 반복 iteration 낭비**
- 해결: `verify_skills(skill_names: list[str])` 단일 호출로 5개 처리
- 시스템 프롬프트에 "verify_skills는 단 1회만 호출" 명시 (nodes.py)

**문제 3: Chroma가 Neo4j 지식을 무시하고 전체 컬렉션 검색**
- 해결: Chroma `search()` 메서드에 `source_ids` 파라미터 추가 (chroma_client.py)
  - Dense 검색: Chroma `where={"$and": [{"section_type": ...}, {"source_id": {"$in": ...}}]}` 적용
  - BM25 검색: `_filter_by_metadata(ids, section_type, source_ids)` post-filter
  - RRF로 합산
- Neo4j가 찾은 공고 ID 내에서만 Chroma가 검색하는 Neo4j-guided hybrid 완성

**문제 4: 동일 공고 반복 참조 (dedup)**
- 해결: `_make_tools_node()`에서 `seen_source_ids` 추적 (graph.py)
  - `vector_search` 결과에서 이미 인용한 source_id 제거
  - `verify_skills` evidence에서도 동일 dedup 적용
  - AgentState에 `seen_source_ids: list[str]` 필드 추가 (state.py)

**문제 5: Neo4j에서 REQUIRES 관계로 공고 source_id 조회 기능 없음**
- 해결: `get_postings_requiring_skill(skill_name, limit=3)` 추가 (neo4j_client.py)
  - `MATCH (jp:JobPosting)-[:INSTANCE_OF]->(j:Job)-[:REQUIRES]->(s:Skill)` Cypher 쿼리

### 발생 문제 및 해결

| 문제 | 원인 | 해결 |
|------|------|------|
| DoorDash required_section에 복지/보상 텍스트 포함 | `<b>` 태그가 콘텐츠 블록 전체를 감싸고, 블록 뒤 body가 보상 텍스트 | `_MAX_HEADER_LEN=100`: 긴 헤더는 헤더 텍스트 자체를 섹션 본문으로 사용 + `_NOISE_SIGNALS > _REQ_SIGNALS` 이면 skip |
| 보상 텍스트 블록 내 "qualifications" 단어로 required 오분류 | "based on job-related factors including... qualifications..." 문구 | 노이즈 신호가 요건 신호보다 많으면 필터링 |

### 결과 검증
- SE 공고 170개 전처리: required 섹션 73%, preferred 46%, 심각한 노이즈 0개
- DoorDash 21557051: "flexible paid time off..." → "Experience in building physical models..." 교체 확인
- Chroma SE 재적재: 193개 문서 upsert (컬렉션 총 253개)

---

## 2026-06-10 (2차)

### 작업 절차

#### Phase 11 — 데이터 수집·전처리·스킬추출·적재 전면 재구축

**RemoteOK 데이터 품질 3대 문제 수정** (`preprocessor.py`)

| 문제 | 원인 | 해결 |
|------|------|------|
| 비개발 공고 포함 | 태그 기반 수집이라 회계사·의료 공고 혼입 | `_DEV_TITLE_KEYWORDS` allowlist로 타이틀 필터 |
| LinkedIn 스팸 설명 | "similar jobs on LinkedIn" 리디렉션 텍스트 | `_SPAM_PATTERNS` 정규식으로 필터 |
| 인코딩 깨짐 | UTF-8을 latin-1로 읽어 `â\x80\x99`→`'` 변환 필요 | `_fix_encoding()` — latin-1 encode → utf-8 decode |

**스킬 추출 방식 변경** (`skill_extractor.py`)
- 구버전: `{"raw": "Python", "name": "Python", "category": "language"}` (카테고리 분류)
- 신버전: `{"required": ["Python", "LangGraph"], "preferred": ["Docker"]}` (이름만)
- 이유: 카테고리(language/framework/tool)를 임의로 정해놓는 것이 데이터 오염. Neo4j에서 직군-스킬 관계만 있으면 충분

**Neo4j 스키마 재설계** (`neo4j_client.py`)
- 제거: `Job` 노드, `UPSERT_JOB`, `LINK_POSTING_JOB` 쿼리
- 추가: `(JobPosting)-[:REQUIRES|PREFERS]->(Skill)` 직접 연결
- 추가: `Company` 노드 + `(JobPosting)-[:POSTED_BY]->(Company)`
- 추가: `JobFamily` 노드 + `(JobPosting)-[:INSTANCE_OF]->(JobFamily)`
- 이유: Job 노드 정규화는 LLM이 임의로 직무명을 묶어 데이터 왜곡 가능. 직군은 우리가 10개로 명시 분류

**데이터 통합 및 직군 필터링** (`pipeline.py`)
- 3개 소스(SE/DA/RemoteOK) → 443개 공고 → `filter_by_job_family()` → 321개
- 10개 직군 분류: Software Engineer 127, Data Engineer 35, Data Analyst 30, Data Scientist 26, Architect 26, DevOps/SRE 25, AI/LLM Engineer 20, Security Engineer 15, ML Engineer 11, Frontend Engineer 6
- 출력: `data/processed/jobs_filtered.json` 하나로 통합

**ID prefix 추가** (`preprocessor.py`)
- The Muse: `21820571` → `muse-21820571`
- RemoteOK: `1133041` → `remoteok-1133041`
- 이유: 두 소스의 숫자 ID가 우연히 겹칠 수 있어 Neo4j에서 덮어쓰기 발생 방지

#### Phase 12 — 스킬 추출 실행 및 Neo4j/Chroma 적재

- DA 143개 + RemoteOK 165개 스킬 추출 (GPT-4o-mini)
- 구버전 SE 134개 skills 형식 변환 (dict → 문자열 리스트)
- Neo4j 적재 결과: JobPosting 321 / Skill 1,079 / Company 200 / JobFamily 10
- 관계: REQUIRES 2,025 / PREFERS 665 / CO_OCCURS 13,605 / INSTANCE_OF 321 / POSTED_BY 320
- Chroma 적재 결과: 669개 문서 (required 269 / preferred 182 / bullet 164 / full_text 54)

#### Phase 13 — 툴 검증 및 gap_analysis JobFamily 기반으로 수정

- 전체 7개 툴 동작 확인: gap_analysis / verify_skills / vector_search / skill_unlock / market_insights / graph_query / ask_human
- gap_analysis 문제 발견: 타이틀 substring 검색 → "Software Engineer"가 102개만 잡힘 (JobFamily는 127개)
- 해결: `_JOB_SKILLS_QUERY`를 `MATCH (:JobFamily {name: $job_family})<-[:INSTANCE_OF]-(jp)` 로 변경
- gap_analysis, graph_query 파라미터명 `job_title` → `job_family` 로 통일

### 발생 문제 및 해결

| 문제 | 원인 | 해결 |
|------|------|------|
| `_SPAM_PATTERNS`이 전체 391개 공고에 매칭 | `RMTQuNTIuMTA2LjI0` 봇 탐지 코드가 모든 RemoteOK 공고에 포함 | 해당 패턴 제거, LinkedIn 리디렉션 패턴만 유지 |
| SE skills dict 형식으로 Neo4j 적재 불가 | 구버전 `extract_skills()`로 추출된 데이터가 파일에 남아있었음 | 일회성 변환 스크립트로 문자열 리스트로 통일 |
| bash `-c "..."` 안에서 `$fam`이 사라짐 | 이중 따옴표 안에서 bash가 `$fam`을 환경변수로 해석해 빈 문자열로 치환 | heredoc(`<< 'EOF'`) 방식으로 변경 |
| `gap_analysis` 결과에 Java, Scala, C# 등 이상 스킬 | "AI Engineer" substring이 다른 직군 공고까지 포함 | JobFamily 노드 기반 정확한 매칭으로 교체 |
| Chroma `source` 메타데이터 None | 인덱싱 시 source 필드를 메타데이터에 넣지 않음 | 기능 영향 없음 (미수정) |

### 현재 상태
- Layer 1 (수집) ✅
- Layer 2 (전처리·추출·저장) ✅
- Layer 3 (LangGraph 에이전트 — 코드 구조) ✅ / end-to-end 실행 검증 ⬜
- Layer 4 (갭 분석) — gap_analyzer.py GAP_QUERY 아직 JobFamily 미반영 ⬜
- Layer 5 (평가) ⬜
- Layer 6 (API·배포) ⬜

---

## 2026-06-10 (3차)

### 작업 절차

#### Phase 14 — 검색 파이프라인 고도화

**Cross-encoder 재정렬 추가** (`chroma_client.py`)

기존: `BM25 + Dense → RRF → 상위 n개 반환`
변경: `BM25 + Dense → RRF (후보 4× 확보) → CrossEncoder 재정렬 → 상위 n개 반환`

- 모델: `cross-encoder/ms-marco-MiniLM-L-6-v2` (~80MB, 로컬 무료)
- Lazy load: 첫 `rerank=True` 호출 시에만 모델 초기화
- 후보 풀: `rerank=False` 시 `n×3`, `rerank=True` 시 `n×4`로 확장 후 압축
- `search()` 파라미터에 `rerank: bool = True` 추가 (속도 우선 시 False로 비활성화 가능)
- `requirements.txt`에 `sentence-transformers>=3.0.0` 추가

**동작 원리:**
- Dense(의미 유사도) + BM25(키워드 정확도)를 RRF로 합산 → 1차 후보
- CrossEncoder가 (쿼리, 문서) 쌍 전체를 읽고 실제 관련도 재채점 → 최종 순서 결정
- "LangGraph"처럼 정확한 기술명은 BM25가, "RAG 파이프라인 경험" 같은 의미 질의는 Dense가 강점 → 두 방식 모두 필요

**검증:** 669개 문서에서 `"LangGraph RAG pipeline"` 질의 시 결과 순서 변화 확인

---

### 설계 논의 및 결정사항

#### Multi-Agent 아키텍처 확정

단일 에이전트(`call_model → tools → generate`)를 4개 전문 에이전트로 분리.

```
Resume Agent  →  [Gap Agent ‖ GitHub Agent]  →  Coach Agent
```

- **Resume Agent**: PDF 파싱 + LLM 스킬 추출 + Neo4j PortfolioItem 저장
- **Gap Agent**: 기존 단일 에이전트를 그대로 래핑, `run_analysis()` 재활용
- **GitHub Agent**: GitHub API로 README 파일 내용까지 읽어 실제 구현 여부 LLM 판단 (기존 메타데이터 방식 업그레이드)
- **Coach Agent**: 갭 분석 결과 + Chroma 근거 → 이력서 개선 제안
- **Supervisor**: LangGraph `Send()` API로 Gap + GitHub 병렬 실행

**라우팅 방식 결정:** LLM 라우팅(Supervisor LLM)이 아닌 결정적(deterministic) 라우팅 채택
- 이유: 흐름이 항상 Resume→Gap+GitHub→Coach로 고정. LLM이 라우팅 결정할 필요 없음.
- `Send()` + 조건부 엣지로 구현

**GitHub Agent 업그레이드 결정:**
- 기존: 리포 메타데이터(이름, 설명, 토픽, 언어)만 키워드 매칭
- 변경: `GET /repos/{username}/{repo}/readme` API로 README 전문 읽기 → LLM이 실제 구현 여부 판단
- 법적 문제 없음: 공개 리포는 GitHub ToS에서 API 접근 명시적 허용

#### 서빙 방식 결정: MCP → 웹페이지

**MCP 서버 대신 FastAPI 웹페이지로 결정**

이유:
- MCP는 Claude Desktop에서만 접근 가능 → 데모 공유 불가
- 웹페이지(FastAPI + Docker)가 FastAPI, REST API 설계, Docker 기술까지 포트폴리오에 추가됨
- HF Spaces 배포 시 URL 하나로 누구나 접근 가능

MCP는 FastAPI 엔드포인트를 10줄 wrapper로 감싸서 나중에 보너스로 추가 가능.

#### 추가 기술 기능 논의

| 기능 | 결정 | 이유 |
|------|------|------|
| Hybrid Search (BM25+Dense) | 이미 완성 | 이전 세션에서 구현됨 |
| Cross-encoder Reranking | 구현 완료 | `sentence-transformers` 무료, 검색 정확도 향상 |
| Contextual Chunking (완전판) | 구현 예정 | 현재 헤더 방식은 절반만 된 상태. LLM이 각 청크의 문맥 설명을 생성하는 Anthropic 방식으로 업그레이드 필요 |
| Knowledge Graph 학습 로드맵 | 구현 예정 | Neo4j CO_OCCURS·PART_OF 관계 활용, Coach Agent에 통합 |
| FastAPI + SSE 스트리밍 | 구현 예정 | 에이전트 진행 상황 실시간 표시 |
| Docker + HF Spaces | 구현 예정 | Layer 6 |

#### Contextual Chunking 현황 파악

**현재 (절반):** 정적 메타데이터 헤더만 prepend
```
[Senior AI Engineer @ Anthropic | required] + 원문
```

**목표 (완전판):** LLM이 각 청크의 역할을 자연어로 설명
```
"이 구절은 Anthropic의 시니어 AI Engineer 공고 필수 요건으로,
 LangGraph를 활용한 프로덕션 RAG 경험을 명시적으로 요구한다."
+ 원문
```

비용: 669청크 × ~200토큰 = ~33만 토큰 → gpt-4o-mini 기준 약 $0.05

---

### 다음 구현 순서

1. **Contextual Chunking 완성** — LLM 문맥 생성 후 Chroma 재인덱싱
2. **Multi-Agent 구현** — state.py 확장 → resume/gap/github/coach/supervisor
3. **Knowledge Graph 학습 로드맵** — Cypher 그래프 탐색 + Coach Agent 통합
4. **FastAPI + SSE** — `POST /analyze` + 실시간 진행 상황 스트리밍
5. **Docker + HF Spaces 배포**

### 현재 상태
- Layer 1 (수집) ✅
- Layer 2 (전처리·추출·저장) ✅
- Layer 3 (LangGraph 에이전트) ✅ / Multi-Agent 업그레이드 ⬜
- Layer 3.5 (검색 고도화) — BM25+Dense+RRF ✅ / Cross-encoder ✅ / Contextual Chunking ⬜
- Layer 4 (갭 분석·코치) — gap_analyzer.py JobFamily 미반영 ⬜ / Knowledge Graph 로드맵 ⬜
- Layer 5 (평가) ⬜
- Layer 6 (API·배포) ⬜

---

## 2026-06-10 (속)

### 작업 절차

#### Phase 15 — RAGAS 평가 수정 (ToolMessage 기반 컨텍스트)

**문제:**
- 이전 세션의 RAGAS 평가가 `final_report` dict에서 텍스트를 추출하는 방식이었음
- `_extract_evidence()`는 `final_report`의 `reason`, `evidence` 필드를 파싱했지만 실제 에이전트가 사용한 공고 텍스트(ToolMessage)를 놓침
- 결과: Faithfulness 0.389 (아직 낮음)

**수정:**
- `run_analysis()` — `return_state: bool = False` 파라미터 추가. `True`이면 `(final_report, messages)` 튜플 반환
- `_collect_contexts_from_agent()` 완전 재작성:
  - `return_state=True`로 메시지 히스토리 수집
  - ToolMessage 순회: `vector_search` → `item["text"]`, `verify_skills` → `evidence[]["text"]` 추출
  - 컨텍스트에 회사명 prefix 추가 (`[Autodesk] ...`)
- `_report_to_natural_text()` 함수 추가: JSON → 자연어 변환으로 RAGAS claim 추출 개선

**결과 및 한계 발견:**
- Faithfulness 0.000–0.293으로 여전히 낮음
- 근본 원인 파악: RAGAS Faithfulness는 "응답 주장이 컨텍스트에 직접 명시"를 측정하나
  갭 분석의 핵심 주장("ML이 부족하다")은 컨텍스트("ML이 요구된다")에서 직접 나오지 않음
- 이 갭 추론은 Neo4j 구조 데이터 + 사용자 프로필 비교에서 나오는 것이라 구조적 한계
- Answer Relevancy 0.44–0.48은 에이전트가 갭 분석에 올바르게 답한다는 의미

**문서화:**
- `docs/retrieval-eval.md` 갱신: 한계 설명, 더 적합한 평가 방식 제안

#### Phase 16 — Multi-Agent 구현 (AppState + Supervisor 그래프)

**선행 수정:**
- `src/analysis/coach.py` — `chroma.search_evidence()` → `chroma.search()`
- `src/analysis/gap_analyzer.py` — `search_evidence()` → `search()` + `GAP_QUERY` JobFamily 노드 기반으로 교체
  - Before: `WHERE toLower(jp.title) CONTAINS toLower($job_title)`
  - After: `MATCH (:JobFamily {name: $job_family})<-[:INSTANCE_OF]-(jp:JobPosting)`

**Neo4j 메서드 추가 (neo4j_client.py):**
- `get_portfolio_demonstrated_skills(owner)` — PortfolioItem → DemonstratedSkill 목록
- `update_portfolio_confidence(owner, changes)` — DEMONSTRATES.confidence 업데이트

**새 파일:**
- `src/agent/state.py` — `AppState` TypedDict 추가 (AgentState는 유지)
  - 필드: job_family, owner, pdf_path, github_url, resume_skills, resume_text, gap_result, github_result, coaching_result, final_report
- `src/agent/resume_agent.py` — PDF → LLM 스킬 추출 → Neo4j 저장 노드
- `src/agent/gap_agent.py` — 기존 run_analysis() 래퍼 노드
- `src/agent/github_agent.py` — GitHub API confidence boost 노드
- `src/agent/coach_agent.py` — GapAnalysisResult dict 변환 + 이력서 개선 제안 노드
- `src/agent/supervisor.py` — Send() 팬아웃 Supervisor 그래프

**아키텍처:**
```
START → resume_agent → Send()[gap_agent ‖ github_agent] → coach_agent → END
```
- gap_agent와 github_agent는 병렬 실행 (Send() API)
- LangGraph가 barrier 자동 해제: 둘 다 완료되면 coach_agent 실행

**검증:**
- `python -c "from src.agent.supervisor import ..."` — 모든 import 성공
- Supervisor 실행: resume_skills=['Python','FastAPI','Docker','LangChain'...] → match_rate=6% → 제안 5개 생성

### 발생 문제 및 해결

1. **RAGAS Faithfulness 구조적 한계** — 갭 분석 use case에 맞지 않는 지표. Answer Relevancy가 더 적합.
2. **coach.py `search_evidence()` 없음** — `chroma.search()` + `results[0]["original_text"]`로 교체
3. **gap_analyzer.py JobFamily 미반영** — GAP_QUERY Cypher를 INSTANCE_OF 관계 기반으로 교체

### 현재 상태

- Layer 1 (수집) ✅
- Layer 2 (전처리·추출·저장) ✅
- Layer 3 (LangGraph 에이전트 + Multi-Agent) ✅
  - 단일 에이전트 (AgentState + graph.py) ✅
  - Multi-Agent Supervisor (AppState + supervisor.py) ✅
  - Send() 팬아웃 (Gap ‖ GitHub 병렬) ✅
- Layer 3.5 (검색 고도화) ✅
  - BM25+Dense+RRF ✅ / Cross-encoder ✅ / Contextual Chunking ✅
- Layer 4 (갭 분석·코치) ✅
- Layer 5 (평가 — RAGAS Answer Relevancy 0.44–0.48) ✅
- Layer 6 (FastAPI + Docker + HF Spaces) ⬜

### 다음 단계

1. FastAPI + SSE 스트리밍 (`POST /analyze`)
2. Docker Compose 설정
3. HF Spaces 배포

---

## [2026-06-10] 멀티 에이전트 코어 전환 (Plan-and-Execute + Critic)

### 작업 절차

1. **버그 수정 (선행)** — 깨진 통합 테스트 복구(`graph.py`/`AgentState` 참조 → `supervisor`/`AppState`), `posting_trend` datetime 비교 버그(Neo4j datetime ↔ Python str), `test_preprocessor` 소스 접두사, `conftest.py`로 `.env` 로드. 테스트 스위트를 git에 처음 등록.
2. **brainstorming** — 멀티에이전트 패턴 선택. Supervisor 동적 라우팅 vs Plan-and-Execute 비교 → 도메인 특성(경로 결정적·입력 다양·Faithfulness 약점)상 **Plan-and-Execute + Critic** 채택.
3. **설계·계획 문서화** — `docs/superpowers/specs/2026-06-10-multi-agent-core-design.md`, `docs/superpowers/plans/2026-06-10-multi-agent-core.md`.
4. **subagent-driven 구현 (feat/multi-agent-core 브랜치)** — Task 0(베이스라인 커밋)~Task 8.
   - 신규 노드: Planner(입력별 조사 계획), Profile(resume+github 통합), Retrieval, Market, Critic(LLM-as-judge faithfulness).
   - 그래프: `START → planner → (Send)[profile ∥ retrieval ∥ market] → seed_gap → call_model↔tools → synthesizer → critic → (replan→planner | coach) → END`.

### 발생 문제

1. **계획서 테스트-구현 모순 2건** — (a) Retrieval 테스트는 `ctx[0].source_id`(chroma 결과)를 기대하나 구현은 neo4j(skill, source_id 없음)를 먼저 넣어 KeyError. (b) `DemonstratedSkill`의 필수 필드 `category` 누락.
2. **route_after_critic 이중 카운트** — critic_node가 replan_count를 +1한 뒤 route가 `replan_count < MAX_REPLAN`를 또 검사해 재계획이 2회 대신 1회만 발동.
3. **replan 시 add_messages 누적** — replan이 돌면 `seed_gap`/`synthesizer`가 재실행되며 `messages`·`coach_messages`(append-only reducer)에 시드가 쌓여 Coach JSON 파싱 실패(`{raw, error}`).

### 해결 방법

1. (a) Retrieval을 chroma→neo4j 순으로 변경(근거 우선이 의미상도 자연). (b) 테스트에 `category="tool"` 추가.
2. `route_after_critic`은 `needs_replan`만 보고 분기 — 상한 체크는 `decide_replan`이 critic_node 안에서 이미 처리(이중 카운트 제거).
3. **Planner가 replan 진입(`critic_report.needs_replan`) 시 `RemoveMessage(REMOVE_ALL_MESSAGES)`로 두 메시지 필드를 클리어.** 스모크 재검증에서 coaching이 `{summary, suggestions}` 정상 출력(제안 5개) 확인.

### 검증 결과

- 전체 67 테스트 통과, end-to-end 정상 종료.
- Send 병렬 fan-in이 `seed_gap` 1회 실행으로 확정(stream 카운트).
- Replan 루프 `replan_count=1→2→상한 정지` 동작 확인 — Critic faithfulness 검증 작동.

### 다음 단계 (코어 직후)

1. Layer 6 배포 (FastAPI SSE + Docker + HF Spaces) — 데모 URL 확보
2. 전문화 고도화 (에이전트 프롬프트 정교화, Market 스킬별 병렬)
3. 평가 강화 (배포 이후) — 골든 데이터셋(쿼리→정답 공고/스킬) 구축 후:
   - **검색 ablation**: BM25/Dense/RRF/CrossEncoder를 하나씩 빼며 Hit Rate·MRR·Context Precision/Recall 측정 → 작은 데이터셋(416청크)에서 실제 기여 검증, 효과 없는 단계는 비용(지연) 대비 제거
   - **RAGAS 재측정**: Critic 도입 전후 Faithfulness before/after
   - Langfuse에 plan·critic·라우팅 트레이스
4. 대화형 코칭 (배포 이후) — 두 패턴을 역할 분리해 구현:
   - **HITL(interrupt)**: 이력서 파싱 시 핵심 정보가 결정적으로 모호할 때만 좁게 사용 (남용 금지)
   - **분석 후 멀티턴 코칭 채팅**: 리포트를 컨텍스트로, 사용자가 프로젝트를 던지고 부족한 부분을 대화로 보충·논의 → 갭 재계산·어필 코칭. interrupt가 아니라 별도 대화 세션으로 설계.
5. 에이전트 v2 재구성 (배포 이후) — "판단하는 것만 에이전트, 조회·검색은 도구" 원칙으로 슬림화:
   - **노드 정리**: Market(데드 노드)·Retrieval(Gap 검색과 중복)을 Gap의 도구로 강등, Planner의 LLM 제거(결정적 분기로 충분). 핵심 4: **Profile·Gap·Critic·Coach**.
   - **Critic 실효화 (길 B — 등급화)**: replan 루프 제거. Critic이 한 번 검증해 각 주장에 근거 등급(high/low) 부착 + 환각(근거 없는 주장) 제거. 이유: 재검색은 '검색 miss'에만 효과인데 데이터가 적어(321공고) '데이터 부족·환각'이 우세 → 재검색으로 없는 근거를 못 만듦. 따라서 "정직한 등급 표시"가 본질. needs_replan/route_after_critic/planner 재진입 제거 → v1보다 단순. (생성자 Gap ↔ 검증자 Critic 분리는 유지 = 멀티에이전트)
   - **Learning Path 제외**: 주차별 소요시간 데이터가 없어 LLM 추측 = "근거 기반" 철학과 모순. 빼는 게 맞음.
   - 근거: 데이터 흐름 추적 결과 Market/Retrieval/Planner-LLM이 미연결·중복·장식으로 확인됨. "노드 수"가 아니라 "소비되는가"로 판단.

---

## [2026-06-11] 에이전트 v3 단계1 — 다중 소스 적합도 평가 (텍스트 MVP)

`feat/agent-v3` 브랜치. 설계 문서(`docs/superpowers/specs/2026-06-11-agent-v3-fit-assessment-design.md`)와 플랜(`docs/superpowers/plans/2026-06-11-agent-v3-stage1-text-mvp.md`)을 subagent-driven으로 Task 0~7 실행.

### 작업 절차

1. **합의 노드(`src/agent/consensus.py`)** — 여러 평가자의 스킬 증거를 결정적으로 종합. `Verified`(github/deploy 실증) > `Corroborated`(2개 이상 소스) > `Claimed`(단일 소스, 코드 미확인 시 flag). `normalize_skill`로 별칭 병합. ("서기" 역할, LLM 없음)
2. **이력서 평가자(`src/agent/evaluators/resume_eval.py`)** — `resume_skills` 주입 > pdf > resume_text 순. `{skill, evidence, source:"resume", level_hint}` 형식 출력.
3. **GitHub 평가자(`src/agent/evaluators/github_eval.py`)** — 레포 메타데이터(name/description/topics/language)에서 `_SKILL_KEYWORDS` 매칭 → `source:"github"`(합의에서 Verified 승격). URL 없거나 파싱 실패 시 빈 결과.
4. **디스패처 + 그래프 재조립(`src/agent/supervisor.py`)** — `evaluator_dispatch`가 입력에 있는 소스의 평가자만 `Send`로 fan-out. v1 planner/profile/retrieval/market 제거, `START→(dispatch)→resume_eval∥github_eval→consensus→seed_gap→call_model↔tools→synthesizer→critic→coach→END`. `seed_gap`이 consensus의 보유 스킬(검증상태 포함)을 메시지로 시드.
5. **Gap 적합도 출력(`src/agent/nodes.py`)** — `_GAP_REPORT_PROMPT`에 적합도(`fit_score`)⊥신뢰도(`confidence_level`) 2축 + `advice` + per-skill `verification`/`held_level` 추가. `generate_report`가 consensus를 프롬프트에 노출.

### 발생 문제

- **스모크에서 `consensus`가 빈 것처럼 보임** — `run_supervisor`가 전체 state가 아니라 `final_report`만 반환하기 때문이었음. 그래프를 직접 `invoke`해 전체 state를 확인하니 `resume_eval`·`consensus` 모두 정상 산출(버그 아님).

### 해결 방법 / 검증 결과

- 그래프 직접 invoke로 검증: `resume_skills=['Python','FastAPI']` → consensus에 둘 다 `Claimed`(코드 미확인 플래그) 산출. `fit_score`/`confidence_level=low`(전부 Claimed라 정상)/`advice`/`skills[]` 키 모두 출력.
- 각 Task TDD(실패→구현→통과) + 2단계 리뷰(스펙 준수 → 코드 품질) 통과. 전체 81 테스트 통과, end-to-end 예외 없이 완료.

### 다음 단계 (v3 단계2~3, 범위 밖)

- 멀티모달 포트폴리오 평가자 (이미지/문서 modality)
- 배포 URL 평가자 (`source:"deploy"` → Verified)
- Critic 길 B 등급화로 재작성 (현재 단계1은 critic→coach 직결, needs_replan 무시)
- v1 잔존 데드코드 정리 (`route_after_critic`, `executor_dispatch`, `_PARALLEL_AGENTS`, `MAX_REPLAN` import)

---

## [2026-06-12] 직무 무관 후보 스킬 추출 범용화

AI/LLM 전용으로 잠겨 있던 후보 스킬 추출을 10개 직군 어디든 평가 가능하게 범용화. subagent-driven으로 Task 1~5 실행.
설계: `docs/superpowers/specs/2026-06-12-domain-general-skill-extraction-design.md`

### 작업 절차

1. **이력서 추출기 잘림 제거** — `extract_skills_from_resume`가 `text[:4000]`로 앞 7%만 LLM에 보내던 것을 전체 텍스트 단일 호출(상한 100K자)로. 출력 토큰 2048→4096.
2. **Neo4jClient 직군 메서드** — `list_job_families()`(유효성 검증·선택지), `get_job_family_skills(job_family)`(직군별 상위 스킬, gap_analysis와 동일 패턴) 추가.
3. **GitHub 평가자 직군별 사전 매칭** — 하드코딩 `_SKILL_KEYWORDS`(AI 전용) 제거, 대상 직군의 스킬 집합(Neo4j)으로 README·의존성파일·언어를 단어경계+별칭 매칭. `create_github_evaluator(neo4j)`. Dockerfile 등 파일명 신호는 `_manifest_match`로 처리.
4. **run_supervisor 직군명 검증** — 진입에서 유효 직군 목록 대조, 불일치 시 유효목록 담은 에러 반환(LLM 환각 차단). neo4j 미제공 시 스킵(백스톱).

### 발생 문제

- **전역 스킬 1079개 중 72%(771개)가 1회성 잡음**(`architecture`·`cloud environments`·고유명사). 전부를 사전으로 쓰면 README 산문에 오탐 폭발 → **직군별 빈도 높은 스킬만** 사전화하기로(gap_analysis가 쓰는 집합과 동일).
- 계획의 `_keywords_for`만으로는 `docker`→`Dockerfile` 파일명을 못 잡음(단어경계 규칙) → `_manifest_match`로 `_PRESENCE_MANIFESTS` 파일명에 한해 보강(오탐 방지 테스트 포함).

### 해결·검증 결과

- 단위 107 + 신규 테스트 통과. 각 Task TDD + 2단계 리뷰(스펙→품질).
- **실데이터 스모크(F-Lab 카카오 백엔드 이력서 + food-delivery GitHub + Software Engineer):**
  - 이전: 이력서 NAS·Ubuntu·클라우드 3개 / GitHub Docker 1개 (AI 전용 한계)
  - 지금: 이력서 18개(Java·Spring Boot·Redis·MariaDB·Jenkins·Docker…) / GitHub 8개(Java·Spring Boot·Docker·Jenkins·CI/CD·Git·REST·HTML)
  - 합의: 교차 검증된 8개가 **Verified**, 나머지 Claimed → 백엔드 지원자 정상 분석. 도메인 잠금 해소.

### 비범위 (후속)

- synthesizer의 fit_score/confidence_level이 LLM 임의값 — 결정적 계산으로 전환은 별도 작업.
- "Backend Engineer" 직군 분리(현재 Software Engineer 포함), 분야 자동 추천(역방향).
- run_supervisor 호출부(CLI·API)에 neo4j 실제 배선 — 필요 시 연결.

---

## [2026-06-12] 포트폴리오 멀티모달 평가자 (v3 단계 2)

이력서·GitHub 텍스트 평가자에 더해 **포트폴리오 PDF를 vision으로 분석하는 평가자**를 추가. 4개 소스 설계(이력서·포폴·GitHub·배포)의 세 번째 소스. subagent-driven으로 Task 1~4 실행.
설계: `docs/superpowers/specs/2026-06-11-agent-v3-fit-assessment-design.md` §4-1

### 작업 절차

1. **의존성·기반** — PyMuPDF(fitz) 설치+requirements, AppState에 `portfolio_path`(입력)·`portfolio_eval`(평가) 필드, 합의 노드가 `portfolio_eval`도 모으도록.
2. **포트폴리오 평가자**(`evaluators/portfolio_eval.py`) — PyMuPDF로 PDF 앞 8페이지를 PNG 렌더(dpi=220) → gpt-4o-mini vision(detail=high)으로 페이지별 스킬 추출(다이어그램·스크린샷·텍스트 근거) → 정규화 중복제거. 출력 `source:"portfolio"`. 순수함수(`_skills_from_vision`/`_merge_skills`)와 가드만 단위 테스트, vision은 스모크.
3. **그래프 배선** — 디스패처(portfolio_path 있으면 Send)·노드·consensus 엣지·`run_supervisor` 파라미터. 기존 두 평가자와 대칭.

### 발생 문제

- 단위 테스트 작성 시 `_render_pdf_pages`가 렌더 예외 시 `doc.close()`를 못 해 fitz 문서 누수 → 리뷰 지적으로 `try/finally` 보강.
- Task 3 subagent가 로그인 오류로 커밋 직전 중단 → 컨트롤러가 변경 검증 후 직접 커밋.

### 해결·검증 결과

- 단위 114 통과(신규 4개). 각 Task TDD + 2단계 리뷰.
- **실데이터 스모크(이가희 포트폴리오 PDF):** vision으로 37개 스킬 추출(Python·PyTorch·React·Next.js·Supabase 등, source=portfolio·where=text/diagram).
- 합의 노드가 portfolio를 비검증 소스로 처리 → 이력서와 겹치면 Corroborated(교차검증)로 신뢰도 상승.

### 비범위 (v3 단계 3)

- 배포 URL 평가자(`deploy_eval.py`) — 웹 분석(HTML+스크린샷), source="deploy"(Verified 승격).

### [업데이트] 포트폴리오 평가자 — 전체 커버리지 하이브리드

실제 포트폴리오(이가희, 30페이지·전부 이미지 PDF)로 검증하다 8페이지 상한의 한계 발견.
- **문제**: 앞 8페이지만 보고(73% 누락) + 텍스트 페이지도 vision으로 봄(비효율). 실측 8페이지 9개 vs 전체 30페이지 41개(4.5배).
- **해결**: 전체 페이지 순회 → 텍스트 충분한 페이지는 텍스트 1콜로 묶고, 이미지 페이지(텍스트 빈약)만 페이지별 vision(상한 25장). `_partition_pages` 순수 함수로 분류.
- 효과: 전체 커버리지 + 비용 적응형(텍스트 페이지 vision 비용 절약). 전부 이미지인 포폴은 모든 페이지 vision(상한 내), 혼합 포폴은 텍스트 페이지 절약.

---

## [2026-06-12] 배포 URL 평가자 (v3 단계3) — 4개 소스 설계 완성

이력서·GitHub·포트폴리오에 더해 **배포 URL 평가자**를 추가. 4개 소스(이력서·포폴·GitHub·배포) 설계 완성. subagent-driven Task 1~4.
설계: `docs/superpowers/specs/2026-06-11-agent-v3-fit-assessment-design.md` §4-2

### 작업 절차

1. **기반** — AppState `deploy_url`(입력)·`deploy_eval`(평가) 필드, 합의 노드가 deploy_eval 포함. consensus의 `_VERIFIABLE_SOURCES`에 deploy가 이미 있어 **deploy 스킬은 자동 Verified**.
2. **배포 평가자**(`evaluators/deploy_eval.py`) — httpx로 URL fetch(200=작동 실증), HTML+응답헤더에서 대상 직군 스킬을 단어경계+별칭 매칭(github 매처 재사용). source="deploy".
3. **그래프 배선** — 디스패처(deploy_url 있으면 Send)·노드·consensus 엣지·run_supervisor 파라미터. 기존 평가자와 대칭.

### 발생 문제

- 계획 테스트가 "tailwind"(HTML)→"Tailwind CSS"(vocab) 매칭을 요구 → normalizer에 tailwind 별칭 추가(github·deploy 일관). 처음엔 단어분리(_deploy_keywords)로 풀었으나 Spring/Boot 오탐 위험으로 별칭 방식으로 교체.
- raw HTML 노이즈에 1~2자 키워드(go/js/ts/c/r) 오탐 위험 → deploy 매칭에서 **3자 미만 키워드 제외**(deploy=실증 소스라 오탐 비용 큼).

### 해결·검증 결과

- 단위 120 통과. 각 Task TDD + 리뷰.
- **실데이터 스모크:** nextjs.org → React·Next.js·Tailwind·TypeScript, vuejs.org → Vue.js·TypeScript 정확 검출. 미작동 URL → 빈 결과+로그. deploy 단독 → Verified 확인.

### 한계 (설계대로 수용)

- 프론트·작동·완성도는 보이나 백엔드·AI 기술(LangGraph 등)은 외부에서 안 보임. 주 가치는 "작동 실증 + 배포 경험"(GitHub 코드와 교차 시 강한 검증).
- vision 스크린샷 UI 평가는 다음 단계(headless 브라우저 의존성).

---

## [2026-06-12] end-to-end 검증 — 4개 소스 설계·구현순서 1~5 완료

4개 소스(이력서·포폴·GitHub·배포) 평가자 + 합의 + 두 축 Gap + Critic + Coach + 검증요약이 통합 동작함을 확인.

### 검증 결과 (3소스 라이트 스모크: 주입이력서+github+deploy)

- `final_report = {gap, verification, coaching}` 구조 정상.
- gap: match_rate(적합도)·confidence(신뢰도) 결정적, fit_score 제거됨.
- verification: 스킬별 검증등급 + 뒷받침 소스(예: Spring Boot=Verified[github,resume], React=Verified[deploy,resume]).
- coaching: summary + suggestions.

### 발생 문제 / 한계

- **4개 전부(포폴 vision 포함) 한 프로세스 동시 실행 → 리소스로 종료.** 포폴 vision 25장 렌더+호출 + CrossEncoder + 전체 gap/coach 루프가 메모리·시간 부담. 각 소스는 개별 검증 완료. 운영 시 포폴 단독/조합 실행 권장. 코드 버그 아님.

### 남은 (구현순서 외)

- 포트폴리오 서사 문서화(README/블로그), 평가 강화(RAGAS), orphan state 필드 정리.

---

## [2026-06-12] API를 v3 에이전트로 재배선

FastAPI `/portfolio`가 구 직접 파이프라인(run_gap_analysis/generate_coaching) 대신 **v3 그래프(run_supervisor)** 를 호출하도록 재배선. 이번 세션의 v3 작업이 비로소 API로 노출됨.

### 작업 절차

1. **스키마 v3 교체** — AnalyzeRequest(job_family·github_url·deploy_url), VerificationItem, 2축·검증 ReportResponse. 구 GitHubRequest·GitHubUpdateResponse·GapSkillItem 삭제.
2. **lifespan 그래프 주입** — create_supervisor_graph를 1회 빌드해 app.state.graph(openai 키 없으면 None), deps.get_graph.
3. **라우터 재배선** — /analyze가 업로드 이력서 텍스트+github_url+deploy_url로 run_supervisor 실행(백그라운드), final_report→ReportResponse 매핑(_map_final_report 순수함수). 가드 404→503→422→409. 구 /github 엔드포인트 제거.

### 발생 문제

- Task 1·2 후 portfolio 라우터가 삭제된 GapSkillItem을 import해 `import src.api.main`이 일시적으로 깨짐 → Task 3 라우터 재작성으로 해소(계획상 예상됨).

### 해결·검증 결과

- 단위 126 통과(_map_final_report·스키마 테스트 신규). TestClient 스모크: /health 200, 미존재 404, ReportResponse v3 필드(match_rate·confidence_level·verification_counts·verified_skills·coaching_summary) 노출, /github 제거 확인.
- 범위: 이력서+github+deploy. 포트폴리오 vision은 리소스 부담으로 API 제외(별도). get_chroma 래퍼는 orphan(선재, 정리 대상).

---

## [2026-06-12] salary_analyzer를 v3 JobFamily 스키마로 재배선

연봉 영향도 엔드포인트(`/jobs/salary`)가 죽어 있던 것을 살림.

### 발견한 문제

- `salary_analyzer`의 모든 Cypher가 v1 스키마 `(:Job {normalized_title})` + `(Job)-[:REQUIRES]->(Skill)`를 가정.
- 실제 v3 그래프는 `Job` 노드 0개. 직군은 `JobFamily`, 관계는 `(JobPosting)-[:INSTANCE_OF]->(JobFamily)` 와 `(JobPosting)-[:REQUIRES]->(Skill)`(2025개)에 붙음.
- 결과: 모든 쿼리가 빈 결과 → baseline 0·skill_impacts [] 반환하는 죽은 엔드포인트. 기본값 `"AI Engineer"`도 JobFamily엔 없는 이름(실제 "AI/LLM Engineer").

### 작업 절차 (TDD)

1. 통합 테스트(`tests/integration/test_salary_analyzer.py`)로 죽음을 회귀 고정 — Software Engineer(salary 공고 15건)로 실 Neo4j 검증. 현재 코드는 `job_family` 인자 미지원으로 빨강.
2. 4개 쿼리(BASELINE/SKILL_SALARY/TOP_COOCCURS/COMBO)를 `JobFamily` + `JobPosting-[:REQUIRES]` 기준으로 재작성. 파라미터·결과 필드 `job_title` → `job_family` 통일.
3. `schemas.py`(SalaryQuery/SalaryResponse), `jobs.py`(엔드포인트 매핑) 정합. 기본값 `"AI/LLM Engineer"`.
4. 단위 테스트(`tests/unit/test_salary_analyzer.py`) — vs_baseline_pct 계산·정렬·combo·빈 DB를 mock으로 검증.

### 검증 결과

- 단위 122 통과(salary 3개 신규). 통합 1 통과. `/jobs/salary` API 200 — Software Engineer baseline £163,602(15건)·skill_impacts 10개, 기본 직군 200.
- `coach.py`는 `salary_result.skill_impacts`만 참조(job_title 미사용)라 영향 없음. 단, 에이전트 코칭 흐름은 아직 `analyze_salary`를 호출하지 않음(연봉 주입 미배선 — 별도).

### 남은 백로그(같은 불일치)

- `jobs.py`의 `JOBS_QUERY`·`TRENDING_QUERY`도 동일하게 `(:Job {normalized_title})`를 써서 죽어 있음. 이번 범위(salary) 밖이라 미수정 — 다음 작업 후보.

---

## [2026-06-13] /jobs·/jobs/trending-skills도 v3 JobFamily 스키마로 재배선

salary와 동일한 v1 스키마 불일치로 죽어 있던 나머지 두 공고 엔드포인트를 살림.

### 문제

- `JOBS_QUERY`·`TRENDING_QUERY`가 `(:Job {normalized_title})`와 `(Job)-[:REQUIRES]`를 가정 → 빈 결과.
- 실제는 `JobFamily` + `(JobPosting)-[:REQUIRES|PREFERS]->(Skill)`. 기본값도 `"AI Engineer"`(없는 직군).

### 작업 (TDD)

1. 통합 테스트(`tests/integration/test_jobs_router.py`) — TestClient+실 Neo4j로 Software Engineer 공고/트렌드 검증, 현재 빨강.
2. `JOBS_QUERY`: `JobFamily` 매칭 + `(p)-[:REQUIRES|PREFERS]` 로 재작성.
3. `TRENDING_QUERY`: 전역 `s.frequency` 대신 **직군 내 공고 count**(`count(DISTINCT p)`)로 빈도 산출 — 직군별 트렌드 의미에 맞게.
4. `schemas.py`(JobsQuery/JobsResponse/TrendingSkillsQuery/TrendingSkillsResponse) `job_title`→`job_family`, 기본값 `"AI/LLM Engineer"`.

### 검증

- 통합 2 통과, 단위 122 유지. `/jobs` 200(50건)·기술필터 동작, `/jobs/trending-skills` 200(Python 34·PostgreSQL 28·Docker 26…), OpenAPI에 `job_title` 잔재 없음.

이로써 jobs 라우터 3개 엔드포인트(`/jobs`·`/jobs/trending-skills`·`/jobs/salary`) 전부 v3 스키마로 정합 완료.

---

## [2026-06-13] RAGAS 평가 품질 개선 — faithfulness 측정 복구

### 진단

RAGAS 파이프라인은 v3에서 실행됐으나(`run_analysis`가 반환하는 `gap_result` 평면 구조와 호환) **faithfulness가 5샘플 전부 0.000**. 샘플을 덤프해 원인 3겹 확인:
1. evidence(retrieved_contexts)가 정작 그 스킬을 언급조차 안 함 — 예: PostgreSQL을 물었는데 Docker/Java만 보이는 공고. (RAG 근거-스킬 무관)
2. response가 **한국어 일반론**("Docker는 컨테이너화에 필수") — 영어 근거와 언어 불일치.
3. response가 특정 공고가 말한 게 아닌 일반 지식이라 어떤 근거로도 지지 불가.

→ RAGAS가 측정 버그가 아니라 에이전트 약점(근거 미인용)을 정확히 잡은 것.

### 개선 (평가 레이어만, 에이전트 불변)

1. `_evidence_mentions_skill` 추가 — github_eval의 `_word_match`/`_keywords_for`(별칭 포함) 재사용. evidence 텍스트가 그 스킬을 실제 언급할 때만 컨텍스트로 채택(무관 근거 제거).
2. response를 한국어 reason 대신 **영어 사실 진술**(`"{skill} is a required skill for the {job_family} role"`)로. 에이전트의 핵심 판정(부족 필수 스킬)을 공고 근거로 검증 = 환각 측정. 한국어 reason 수집 코드 제거.

### 결과 (Software Engineer 1케이스 재측정)

| 지표 | 개선 전 | 개선 후 |
|---|---|---|
| Answer Relevancy | 0.36 | **0.90** |
| Faithfulness | 0.000 | 0.167 |

- relevancy 0.9: response가 질문에 명확히 답함.
- faithfulness 0→0.167: 측정 복구. 여전히 낮은 건 `ctx=1`(스킬당 근거 1개) — verify_skills가 evidence를 `[:300]`로 짧게 자르고 적게 검색하는 게 병목. **근거 검색 풍부화가 다음 과제**(에이전트 verify_skills 변경 영역).
- 단위 테스트 4개 추가(`test_ragas_eval.py`: 스킬 매칭·집계), 전체 126 통과.

---

## [2026-06-13] Langfuse 트레이싱 배선 + 배포 차단 요소 점검

### Langfuse (배선 0 → CallbackHandler 주입)

- 데코레이터(`langfuse_tracer.py`)는 있었으나 어디에도 적용 안 됨(`@trace` 사용처 0).
- `langfuse_callbacks()` 헬퍼 추가 — `LANGFUSE_PUBLIC_KEY` 있으면 LangChain `CallbackHandler` 반환(LangGraph 전체 자동 트레이싱), 없으면 빈 목록(no-op, 인증 경고 없음).
- `run_supervisor`·`run_analysis` 두 invoke의 config에 `callbacks` 주입.
- 키 없는 환경에서 invoke 정상(회귀 없음), 단위 2개 추가, 전체 128 통과. (커밋 4a24550)

### 배포 점검

- 자산 양호: `app.py`(HF Spaces 진입점, FastAPI 노출), `Dockerfile`(slim+uvicorn), `docker-compose.yml`(api+로컬 neo4j).
- **차단 요소 발견·수정**: `requirements.txt`가 `ragas~=0.2.0`/`langfuse~=2.0.0`로 낡아 Docker 빌드 시 옛 버전 설치 → 코드(0.4.x/4.x API) import 깨짐. 설치본에 맞춰 `ragas~=0.4.0`/`langfuse~=4.0`으로 정합.
- 남은 배포 과제(사용자 환경 필요): HF Spaces 실제 배포(Space 생성·Aura/OpenAI 시크릿 등록·app_port), 로컬 Docker 빌드+기동 검증.

---

## [2026-06-13] 로컬 Docker 빌드·기동 검증

- `.dockerignore` 추가 — `data`(23M)·`chroma_db`·`__pycache__`·`.venv`·`tests`·`docs` 등 빌드 컨텍스트에서 제외.
- `docker build` 성공(exit 0): **requirements 정합이 실제 빌드에서 검증됨** — ragas-0.4.3·langfuse-4.7.1 정상 설치, 전체 의존성 import 깨짐 없음. 이미지 `job-skill-analyzer:latest` 생성(torch+CUDA로 빌드 14분).
- 기동 검증: 첫 시도는 포트 8000이 다른 앱(ClaBi)에 점유돼 무효(curl이 그 앱 응답을 잡음) → 8123 포트로 재검증, 우리 앱 `/health` = `{"status":"ok","has_openai":true}` 정상.

---

## [2026-06-22] 전체 점검 — 문서↔코드 정합·죽은 코드 제거·근거 풍부화·통합 테스트 복구

### 작업 절차

프로젝트 전반의 "고쳐야 할 것"을 코드 기준으로 훑고 하나씩 처리했다.

1. **문서 ↔ 코드 정합 (Chroma·연봉·구조 트리)**: CLAUDE.md가 Chroma를 "확정 기술"·구조(`chroma_client.py`)로 박아뒀으나 실제 제거됨(README는 이미 정확) → "사용하지 않는 것"에 측정 후 제거 사유로 이동. 핵심 기능 #1의 "연봉 영향도 분석"을 보조 지표로 정정. 구조 트리의 없는 파일(`scheduler.py`·`graph.py`·`coach.py`)을 실재 파일(`consensus.py`·`critic.py`·`evaluators/`·`capability.py`·`supervisor.py` 등)로 갱신.
2. **RemoteOK 죽은 코드 제거**: 라이브·스크립트·테스트 어디서도 호출 안 됨, 수집 데이터 파일도 없음 → `remoteok_client.py` 삭제 + `pipeline.py`·`preprocessor.py`의 RemoteOK 경로 제거.
3. **verify_skills 근거 풍부화**: `_evidence_sentence`(300자 단문 1개) → `_evidence_snippet`(키워드 문장 최대 2개·450자), 공고 검색 `limit 3→5`.
4. **Architect 유령 직군 제거**: `_job_family`가 의도적으로 미분류(테스트로 보장)인데 gap_analysis·graph_query 툴 안내와 웹 드롭다운이 "Architect"를 유효 직군으로 제시 → 선택 시 "데이터 없음" 오류. 툴 2곳·웹에서 제거.
5. **환경변수·브리프 정합**: Neo4j 필수(없으면 `EnvironmentError`) 명시, `.env.example` USE_LOCAL_MODEL "예정/미구현" 정정, 테스트 수 179→182.
6. **통합 테스트 복구 + normalize_job_title 죽은 코드 제거**.

### 발생 문제

- **연봉 기능의 정체**: 데이터를 직접 확인하니 560개 공고 중 연봉 보유 21개(3%), 타겟 AI/LLM Engineer는 88개 중 1개. baseline이 표본 1개라 통계적으로 무의미 → "되살릴 기능"이 아니라 "데이터가 못 받쳐주는 기능". 미노출 유지로 결론.
- **RAGAS faithfulness가 안 오름**: 근거 풍부화 후 0.167→0.200(미미). 샘플 분해상 컨텍스트를 늘린 샘플도 대부분 0 → 양이 병목이 아니었음. 진짜 원인은 response의 과일반화("직군 전체의 필수 스킬") ↔ 특정 공고 근거의 층위 불일치.
- **통합 테스트 1건 실패**: `test_returns_dict`가 coach_tools 단계에서 `get_co_occurring_skills()`의 미설정 MagicMock을 `json.dumps`하다 TypeError. 코치 학습 추천(CO_OCCURS) 기능 추가 시 fixture 미갱신.

### 해결 방법

- **RAGAS response reframe 가설을 측정으로 기각**: response를 "이 공고들이 required로 명시한다"로 바꿔보니 오히려 faithfulness 0.200→0.000, answer_relevancy 0.87→0.54로 악화(yes/no 질문에 간접 답변이 됨) → 직감 대신 측정을 따라 복원. 풍부화만 유지(라이브 에이전트에도 이득). 합성 단문 평가에서 faithfulness는 0/1로 튀어 metric 추격은 비추.
- **통합 테스트 fixture 보강**: LLM의 툴 선택이 비결정적이므로 에이전트가 호출 가능한 neo4j 메서드(`get_co_occurring_skills`·`get_posting_sections`·`get_postings_requiring_skill`·`get_skill_unlock_count`·`get_skill_trend`)를 모두 직렬화 가능한 값으로 mock → 단위 182 + 통합 14 전부 통과.
- **죽은 코드 일괄 정리**: RemoteOK + `normalize_job_title`(LLM 직무 정규화, 미연결·미테스트) 제거, 고아 import(os·OpenAI) 정리.

## 2026-06-27

### 작업 절차

**코칭 품질 개선 (github_eval + Coach 구조 개선)**

1. **Coach 2단계 판단 구조 도입**: `applicable_gaps`를 github_eval에서 제거하고, Coach agent가 `missing_required` 스킬을 프로젝트 코드 컨텍스트로 직접 판단하도록 재설계. project_suggestions(코드 연결 가능) vs learning_recommendations(코드 연결 불가) 분리.

2. **ecosystem mapping 추가** (`github_eval.py`): `_PKG_TO_SKILL` 딕셔너리로 package.json 패키지 → 표준 스킬명 매핑 (drizzle-orm → PostgreSQL 등 35개). `_skills_from_pkg_json()` 함수 구현.

3. **vocab 확장** (`github_eval.evaluate()`): `exclude_common_threshold=None`으로 Docker·AWS·CI/CD 등 공통 스킬도 코칭 vocab에 포함. resume_skills도 vocab에 추가해 직군 외 스킬도 GitHub에서 검증 가능하게.

4. **detected_skills fallback**: LLM이 pkg_json 감지 스킬을 `current_usage: "없음"`으로 처리하면 기본 "기본 사용" assessment로 보장.

5. **정규화 수정**: `missing_preferred`에 `normalize_skill()` 적용 (CI/CD Pipelines → CI/CD). `normalize_skill()`을 LLM 출력 후 적용해 대소문자 오류 제거.

6. **추천 공고 Top5 추가** (`neo4j_client.recommend_job_postings()`): Verified 스킬 기준으로 매칭률 상위 채용공고 5개 반환. `min_required=4` 조건으로 3개짜리 고정 추출 노이즈 공고 제거.

### 발생 문제

- **applicable_gaps 오탐**: Git·Java 등 프로젝트와 무관한 스킬이 코칭에 포함됨. 원인: github_eval이 gap 분석 컨텍스트 없이 "이 스킬이 이 프로젝트에 맞냐"를 판단해서. 해결: applicable_gaps 제거, Coach가 두 컨텍스트를 모두 보고 판단.
- **PostgreSQL Claimed 유지**: Frontend Engineer vocab에 PostgreSQL이 없어서 pkg_json 감지도 skip됨. 해결: resume_skills를 vocab에 추가.
- **3개짜리 공고 노이즈**: 요구 스킬 3개 공고가 1,507개로 압도적 다수(LLM 고정 추출 패턴). 100% 매칭이지만 의미 없음. 해결: `min_required=4` 조건 추가.

### 해결 방법

- Coach 2단계 프롬프트: "project_contexts에서 구체적 파일명·함수명이 보이는가? YES → project_suggestions, NO → learning_recommendations"
- vocab = job_family_skills + resume_skills 합집합으로 검증 범위 확장
- Neo4j 데이터 분포 확인 후 min_required 값 결정 (4개 이상이 적정)

### 최종 상태 (192/192 테스트 통과)

- Frontend Engineer + the_formula 기준: 매칭률 60%, Verified 10개, Claimed 1개 (Docker)
- PostgreSQL Verified (drizzle-orm 감지), missing_preferred 정규화, 추천 공고 Top5 포함

---

## [2026-06-30] 미분류 JobPosting 백필 시도 → 롤백 (Adzuna 데이터 품질 결함 발견)

### 작업 절차

1. **미분류 공고 발견**: 총 JobPosting 3,329건 중 `INSTANCE_OF`로 직군 연결된 건 560건뿐(분류율 17%). 나머지 2,769건(전부 Adzuna, source_id 순수 숫자)이 미분류.
2. **백필 시도**: 미분류 2,769건을 `_job_family()`로 100% 재분류 가능 확인 후, INSTANCE_OF만 추가하는 백필 실행. 9개 직군 5~17배 증가(AI/LLM 88→390 등).
3. **순도 점검에서 오염 발각**: 백필 후 9개 직군 중 8개의 상위 5개 스킬이 동일한 인프라 스킬(Docker/Python/Kubernetes/PostgreSQL/Terraform)로 도배됨. Frontend만 정상(React/JS/TS).
4. **원인 규명**: 5개 인프라 동시 보유 공고 2,500건 중 2,458건(98%)이 Adzuna. Adzuna 공고 본문(required_section)을 직접 대조하니 "About the role We are looking for..." 한 문장뿐이거나 빈 값(63% empty) → 스킬 추출 LLM이 본문 없이 인프라 5종을 **환각**. Adzuna 2,769건의 89%가 동일 5스킬.
5. **롤백**: Adzuna INSTANCE_OF 2,769개 전부 제거 → 백필 전 깨끗한 560건(muse+remoteok)으로 복귀. AI/LLM 상위 스킬 Python·LLM·AI·ML로 정상화 확인.

### 발생 문제

- **Adzuna 데이터는 본문 빈약 → 추출 환각**: 원본 description이 빈약해 재추출해도 환각 반복. 살릴 수 없는 데이터. 그동안 INSTANCE_OF 없이 떠 있던 게 (의도 무관) 오염 차단막 역할을 하고 있었음. 백필이 그 막을 걷어 직군 분석을 오염시킴.
- **verify_skills 근거 결손(별개 문제)**: `required_section`이 muse·remoteok 100%, adzuna 63% 비어있음. verify_skills가 이걸 근거로 쓰는데 대부분 빈 값 → RAGAS Faithfulness 저하의 진짜 원인. 백필과 무관.
- **RAGAS 재측정값(백필 상태)**: 평균 0.603, AnswerRelevancy ≈0.85, Faithfulness ≈0.37. metric이 0/1로 튀어 추격 비추(2026-06-13 결론 재확인).

### 해결 방법 / 결론

- **백필 롤백이 정답**: Adzuna는 본문 빈약으로 추출이 환각이라 직군 분석에 쓸 수 없음. 깨끗한 muse/remoteok 560건만 유지.
- **데이터 보강이 필요하면 Adzuna가 아니라 본문 충실한 소스(The Muse/RemoteOK 등)로** 수집해야 함. Adzuna는 source로서 description 결함.
- 미해결 과제: verify_skills 근거(required_section) 결손 → 전처리 섹션 분리 점검 필요.

### 후속: 파이프라인 INSTANCE_OF 버그 수정 + Frontend 보충

- **근본 버그 발견**: `collect.py`가 `filter_by_job_family`로 거르기만 하고 분류 결과(직군명)를 공고 dict에 안 써줌. `ingest_posting`은 `posting["job_family"]`가 있을 때만 INSTANCE_OF를 연결하므로, 수집해도 직군 연결이 누락됨. **옛 Adzuna가 미분류로 떠 있던 두 번째 원인**(첫째는 description 추출 환각).
- **수정**: `collect_and_ingest`에서 filter 후 `j["job_family"] = _job_family(j["title"])` 부여(수집 family가 아닌 title 실분류 — 'react developer' 쿼리의 풀스택 공고가 Frontend로 오분류되는 것 방지).
- **Adzuna 재평가**: 옛 적재본 오염은 Adzuna 결함이 아니라 옛 코드 버그였음. 현재 collect.py로 Frontend 시범 수집 시 React/TS/JS 정상 추출, 환각 없음. 단 Adzuna 무료 API는 description 500자 truncate → 수율 ~50%(앞 500자에 스킬 없으면 빈 추출).
- **Frontend 보충 결과**: 18 → 59건. 순도 완벽(React 45·TypeScript 30·JavaScript 30·CSS 24·HTML 21..., 인프라 환각 0). 추출 데이터 재사용으로 재적재(OpenAI 비용 0).
- 남은 여지: Frontend 59건은 갭 분석 임계(~100) 약간 미달 → `--pages 10`/`--country us`로 추가 보강 가능. 다른 직군도 동일 방식 적용 가능.

---

## [2026-07-01] 결과 화면 5개 구조 재설계 + 코칭 환각 제거

### 작업 절차

1. **5개 구조 재설계**(brainstorming→설계문서→구현): 적합도 점수(N/100) 제거. ①충족 ②채울것(학습) ③보강(코드) + 각 항목 설명·코칭. `LearningRecommendation`에 `how`(학습 코칭) 신설, Coach 프롬프트에 structure_summary 기반 how 생성. `renderReport` 재작성(면접코칭·추천직군·공통스킬은 화면 제거, 백엔드 데이터·/observe는 유지).
2. **github_eval A**: 파일 선택을 골격 우선(매니페스트·엔트리·디렉토리 다양성)으로 재작성 + 전체 트리를 프롬프트에 추가 + how_to_add 형식 강제 완화.
3. **github_eval B**: pass1에서 gpt-4o-mini가 트리 보고 핵심 파일 직접 선택(실패 시 A 휴리스틱 fallback). pass2를 파일레벨로 조임(실제 본 파일·함수만).
4. **Coach 조이기**: ③ project_suggestions 환각 차단 — 설계 대체·패러다임 강요 금지.
5. **두 레포 e2e 검증**: jobgraphPJ(커스텀 멀티에이전트), the_formula(Next.js 표준).

### 발생 문제

- **적합도 점수 무의미**: "10개 중 4개=40점"이 스킬 중요도 무시 + actionable하지 않음.
- **③ 코칭 환각(치명적)**: "강화학습을 gap_analysis에", "Neo4j를 PostgreSQL로 전환", "규칙함수에 신경망" — 실재 파일명+환각 내용. 면접에서 망신급.
- **근원 오진 위험**: github_eval의 how_to_add와 화면의 ③ project_suggestions는 다른 함수(Coach)가 생성. github_eval만 고쳐선 최종 ③ 환각 안 잡힘.
- **직군 노이즈**: AI/LLM 핵심에 Java(6건). 진단 결과 경계선(Software Engineer의 Java는 정당).
- **github_eval 일시 파싱 실패**: gpt-4o 빈 응답으로 project_context 빈 결과 → 코칭 degraded. 재시도로 대개 커버.

### 해결 방법

- **환각의 두 근원 분리 대응**: (A/B) github_eval의 GitHub 파악을 골격+LLM선택으로 정확화, (Coach) project_suggestions 생성 규칙을 같은 원칙(설계 대체 금지·본 코드만·애매하면 learning)으로 조임.
- **측정으로 검증**: the_formula에서 "src/lib/queries.ts에 제네릭 Fetch 타입", "getArticles 반환 타입 제네릭 개선" 등 파일레벨 디테일 달성, 환각 0. jobgraphPJ는 커스텀 구조라 추상 스킬(AI·RAG)이 밋밋(파일은 맞음) — "완벽한 파악 불가"의 실제 모습.
- **직군 노이즈는 수용**: 경계선이라 하드코딩/데이터작업 실익 없음. 롤백으로 인프라 도배는 이미 해결됨.

### 커밋 (feat/multi-agent)

`94d9b8a3` 5개 구조 · `79780126` github_eval A+B · `a3391017` Coach 조이기 · `f2b5ee39` threshold · `a1c55e63` collect.py INSTANCE_OF 버그.

### 남은 과제

- jobgraphPJ 같은 커스텀 레포의 추상 스킬 코칭은 밋밋 — 근본 개선은 어려움(LLM 한계).

---

## [2026-07-01 오후] 회사 추천 + 배포 갱신 + github_eval 안정화 + verify_skills 근거 복구

### 작업 절차

1. **회사 추천 추가**(`b1a8bda2`): ①충족(검증) 스킬로 '지원 가능한 회사 Top5'를 화면에 추가. `recommend_job_postings`에 url 필터(지원 링크 보장)·job_family 필터. RecommendedPosting 스키마 + portfolio 매핑 + app.js 섹션. 검증: AI/LLM→QuantumLoopAI·fastino.ai, Software→Disney·Merge 등 실제 회사+링크+직군 정확.
2. **배포 갱신**: `git subtree split --prefix=pj1 -b hf-deploy` → HF Space main에 force push. 60초 만에 라이브 반영(app.js에 신규 코드 확인). 오늘 개선(5개 구조·코칭 환각 제거·회사 추천) 전부 라이브 반영.
3. **github_eval 안정화**(`c63cacba`): 간헐 파싱 실패('Expecting value: char 0') 방어 — `response_format={"type":"json_object"}` + max_tokens 2000→3000.
4. **verify_skills 근거 복구**(DB 보정, 코드 변경 없음): required_section이 muse 0%·remoteok 0%로 비어 verify_skills가 근거를 못 가져오던 문제. 원본 data/raw(muse `contents` 5256자, remoteok `description`)를 preprocessor로 파싱해 `set_posting_sections`로 채움(source_id `muse-{id}`/`remoteok-{id}` 매칭). 결과: remoteok 122/122, muse 112/438 → verify_skills가 실제 공고 원문 반환(NVIDIA LangChain, Foresters React 등).

### 발생 문제

- **Neo4j에 공고 원문 텍스트가 거의 없음**: required_section adzuna 37%·muse/remoteok 0%, description/text_clean 전 소스 0. verify_skills 근거 원천 부재.
- **muse 매칭율 26%**: 원본 JSON id와 Neo4j source_id 매칭이 절반 이하(원본 데이터 불완전). 234건으로 흔한 스킬은 충분 커버.

### 해결 방법 / 참고

- verify_skills 근거 복구는 **로컬=라이브 같은 Aura DB라 재배포 없이 즉시 반영**.
- required_section 재채움 스크립트는 일회성(muse/remoteok 재수집 경로 제거됨, 유지됨). 재현 필요 시 data/raw JSON → preprocessor extract_sections → set_posting_sections.
- adzuna는 원문 500자 truncate라 근거 빈약 → 제외.

### 남은 과제

- 직군 데이터 보충: 대부분 직군 충분(30+), 실익 작아 후순위/스킵.
- muse 매칭율 개선 여지(원본 id 매칭), adzuna 미분류 2769건 처리(방치 중).

### 후속: 라이브 QA + 비용 보호

- **라이브 브라우저 QA**(gstack): 이력서 30쪽 업로드 → 분석 → 결과 화면 검증. 5개 구조(신뢰도·충족·채울것·보강·회사추천) 정상 렌더, 회사 추천 지원 링크(adzuna/remoteok) 작동. Docker 보강은 파일레벨("docker-compose.yml 멀티스테이지") 정확. PASS. 관찰: ② Java/PostgreSQL 직군 노이즈는 화면상 보이나 학습 추천이라 치명적 아님(수용).
- **비용 보호**(`fa6881b9`, 배포 `8ef99a66`): Public Space 방문자 과금 차단. env `ACCESS_KEY` 설정 시 맞는 키만 분석(OpenAI 호출) 허용 — 방문자 403(결과 화면 열람만), 관리자 비번 무제한(localStorage). `AnalyzeRequest.access_key` + `_enforce_access` + 프론트 403→prompt 재시도. HF Secret ACCESS_KEY 설정 완료 → 보호 활성.

---

## [2026-07-01 저녁] 코칭 환각 4중 방어 + 9직군 검증 + 마무리

### 작업 절차

1. **환각 근본 진단**: ③ 코칭 환각("강화학습을 capability.py에")이 조여도 재발. 재현 결과 원인 3가지 — LLM의 '보강점 강박'(고급 스킬도 missing 억지 생성), 추상 스킬(AI/ML)의 의미 공백(코드에 형태 없어 도약), anchor 검증 한계(파일명은 실재·내용은 환각).
2. **환각 4중 방어 구축**:
   - **프로젝트 레벨 전환**: 파일·함수 짚기 금지 → structure_summary(main·README) 기반 프로젝트 레벨 제안. 파일 환각 근원 제거.
   - **CO_OCCURS 관계 제약**: 스킬의 실제 연관 스킬(함께 쓰이는)로 방향 제약. AI 이웃에 강화학습 없음 → 도약 차단. `get_skill_neighbors` 추가, 프롬프트에 연관 제공.
   - **category soft 제외**: 핵심 스킬 153개(공통+9직군)를 6종(language/framework/tool/database/concept/soft) LLM 분류 → Skill.category. soft(CISSP·Agile·ISO 등 자격증·방법론·표준)는 ③ 제외. `scripts/classify_skills.py`, `get_skill_categories`.
   - **고급 필터**: current_usage=고급이면 코드로 missing·how 비움.
3. **9직군 e2e 검증**: 각 직군 실제 포트폴리오 레포로 테스트. 환각 0, Data 직군은 ③ 없음(억지 안 함), ② 프로젝트 참조 정확("MongoDB 쓰니 PostgreSQL").
4. **빈 코칭 섹션 숨김**: ②③ 없으면 헤더까지 미표시.

### 발생 문제

- **조여도 환각 재발**: 프롬프트 조이기는 LLM에 부탁이라 비결정적. 확률만 낮추고 0은 안 됨.
- **하드코딩 리스트 한계**: AI/LLM만 막으면 근시안. 모든 분야(Security 자격증 등) 환각 필요.
- **Data Scientist 미분류 우회**: ③에 "하이퍼파라미터 튜닝"(미분류 기법명)이 category·CO_OCCURS 제약 우회. "미분류=codable 기본"의 구멍. → 미분류 ③ 제외로 해결 가능(보류).

### 해결 방법 / 결론

- **결정적 방어 우선**: LLM 프롬프트가 아니라 코드/데이터로 차단(category soft, CO_OCCURS 이웃, 고급 필터). 프로젝트의 "신뢰값은 코드가 판정" 철학과 일치.
- **역할 분담**: category=순수역량(soft) 제외, CO_OCCURS=기술 도약 차단, 고급필터=이미 잘하는 것. 겹침 없이 상호보완.
- **트레이드오프 인정**: 파일 레벨→프로젝트 레벨로 환각은 막았으나 표준 레포(the_formula)의 구체적 파일 코칭("getArticles 제네릭")은 밋밋해짐. 환각 안전 > 구체성.
- **검증**: jobgraphPJ·the_formula·bulletproof-react + 9직군 = 12개 레포에서 환각 0 확인.

### 커밋 (feat/multi-agent)

프로젝트레벨 전환 · CO_OCCURS 제약 · category 분류·soft 제외 · 빈 섹션 숨김. (배포 8264b145 이후 app.js 빈섹션 커밋 추가)

### 남은 과제

- Data Scientist 미분류 기법명 ③ 우회 → 미분류 스킬 ③ 제외(한 줄) 필요 시.
- 표준 레포 파일 레벨 구체성 회복(환각과 트레이드오프).

---

## [2026-07-02] 전체 리뷰 대응 — 데이터 정합성·핵심 서사·API 안정성 (28개 커밋)

### 작업 절차

1. **전체 코드 리뷰 요청**: 설계·코드품질·기술선택·전반 4개 축으로 병렬 서브에이전트 2개(수집/저장 계층, API/분석/웹 계층) + 직접 정독(에이전트 계층)으로 리뷰. 6.5/10, "생각의 품질은 상위권, 배관의 품질은 그에 못 미침"으로 결론.
2. **빠른 확실 수정 5건**: supervisor.py 죽은 tools 노드 삭제, href XSS 차단, 업로드 임시파일·인메모리 누수 정리, chroma_db 잔해 삭제, CLAUDE.md 드리프트 동기화.
3. **테스트 스위트 복구**: langchain 1.2.15 ↔ langchain-core 0.3.0 버전 불일치로 `AttributeError: module 'langchain' has no attribute 'debug'` — 9개 테스트 실패 원인. 0.3.x/0.2.x 세대로 상한 고정. 낡은 mock 2건(`_FakeNeo4j.recommend_job_postings` 시그니처, demo_limit 전제) 갱신. 10 fail → 188 pass.
4. **데이터 정합성**: `ingest_posting` 재적재 시 카운터(posting_count/frequency/weight/CO_OCCURS) 이중 집계 — source_id 존재 여부 선판정 후 신규일 때만 증가로 멱등화. `step_extract_skills` 캐시 파일 전체 반환 버그(limit 무력화) 수정. Adzuna 이중 수집 경로(collect.py·collect_and_merge.py) 삭제 — muse/remoteok 정책과 코드 일치.
5. **핵심 서사 방어 — Verified 등급 재설계**: source가 github/deploy이기만 하면 Verified이던 것을, 증거에 `strength`(code/mention) 필드를 부여해 코드 근거가 있을 때만 Verified로 재설계. github_eval(의존성/언어=code, README만=mention), deploy_eval(HTML 키워드=mention 전량), consensus.build_consensus 판정 로직 변경. README 서술도 갱신.
6. **API 안정성**: async 라우트의 동기 Neo4j·pdfplumber 직접 호출 → `def` 전환/`run_in_threadpool`. 예외 상세(str(exc)) 노출 차단 → logger + 일반 메시지. ACCESS_KEY 타이밍세이프 비교. 업로드 검증 스트리밍화 + magic bytes(%PDF) 확인.
7. **저장소 계층**: `load_skill_seeds` 절대경로, `clear_all` confirm 가드, `get_skill_trend` 신규급증(prev=0→recent>0) delta 0.0 버그 수정.
8. **정리**: text_match 유틸(`_word_match`/`_keywords_for`) `src/common/`으로 승격, normalizer 사전 결함 4건(salesForce 죽은키·리액트 중복·open-source 중복·spring 의미왜곡), preprocessor ZeroDivisionError 가드.
9. **리뷰 잔여 항목 2라운드**: `_map_final_report`의 InterviewCoaching.type 검증 폴백, RAGAS 측정 경로 정합성 확인(버그 아님 — 실서비스와 동일 그래프 측정), 업로드 검증 강화, github_connector 부분문자열 오탐(micropython 등) → word_match로 교체, web class 속성 esc() 일관 적용, pdf_parser 중복 통합·langfuse functools.wraps·normalizer CamelCase 보존.
10. **"바로 처리 가능한 것" 4묶음**: 평가자 4개 print→logger, neo4j_client 조회 메서드 에러 삼킴→logger, response_format 잔여 적용(github_eval 파일선택, portfolio_eval), create_nodes 튜플분리+ChatOpenAI 중복제거+_build_trace 하드코딩 제거(gap_trace 실측 기반).
11. **판단 필요 2건 결정**: (a) MemorySaver — HITL 완성(A) vs 제거+문서정직화(B) vs CLI시연(C) 세 선택지 설명 후, "코칭 제품이지 면접 데모가 아니다" 판단으로 B 선택 → 체크포인터 제거(재개 경로 없어 무한 누적만 하던 상태), ask_human을 "설계된 확장 지점(기본 비활성)"으로 문서화. (b) normalize_jobs.py — 참조 없는 legacy 스크립트, 삭제 확정.

### 발생 문제

- **langchain 버전 드리프트**: `requirements.txt`가 `langgraph>=1.0.0`으로 하한만 걸려 있어 fresh install 시 1.x 전체 스택을 끌어오는데, 로컬 환경엔 langchain-core만 0.3.0이 남아있어 부분 업그레이드 불일치 발생. 코드는 0.3.x/0.2.x API로 작성됨.
- **`git add -A` 오작동**: 이 프로젝트는 `/Users/leegahee/workspace`가 git 루트이고 pj1은 하위 디렉토리 — `-A`가 부모의 다른 프로젝트·임베디드 repo까지 스테이징하려다 타임아웃. 이후 파일 경로 명시로 전환.
- **의도 재설계로 인한 테스트 계약 변경**: Verified 재설계·spring 정규화 수정 등이 기존 테스트의 "구현 검증"을 깨뜨림 — 각각 원인이 버그 재현인지 의도된 동작 변경인지 확인 후 테스트 갱신.

### 해결 방법 / 결론

- **버그 재현 우선, 조기 수정 금지**: 리뷰 지적을 그대로 고치기 전에 실제 코드로 재현·확인(예: RAGAS 경로는 재확인 결과 버그 아님 — 코드 변경 없이 검증만 하고 종료).
- **증거 강도 ≠ 소스**: "Verified"의 신뢰를 지키려면 판정 기준을 소스 종류가 아니라 증거의 실제 강도(코드 vs 언급)로 옮겨야 한다는 게 이번 세션의 핵심 설계 교훈.
- **제품 맥락이 아키텍처 판단을 바꾼다**: MemorySaver/HITL 결정에서 "면접용 재료로서의 가치"와 "코칭 제품으로서의 UX"가 상충 — 후자를 우선해 중간에 끊는 HITL 대신 confidence 등급 기반 논블로킹 안내를 유지.
- **회귀 검증 매 커밋 필수화**: 28개 커밋 전부 `pytest tests/unit/`로 확인 후 개별 커밋. 10 fail → 210 pass.

### 커밋 (feat/multi-agent, 28개)

죽은코드 삭제 · XSS 차단 · 리소스 누수 정리 · CLAUDE.md 동기화 · langchain 버전고정 · 적재 멱등성 · Adzuna 경로삭제 · LLM JSON견고화 · Verified 재설계 · async 블로킹해소 · 예외노출차단 · 저장소 에러처리 · text_match 승격 · normalizer 정리 · 코칭type 검증 · 업로드 검증강화 · github_connector 오탐수정 · web esc 일관화 · pdf_parser 통합 · 평가자 로깅전환 · neo4j 로깅승격 · response_format 일관화 · create_nodes 분리 · MemorySaver 제거 · normalize_jobs.py 삭제.

### 남은 과제

- HF Spaces 재배포 필요 — 이번 수정사항 전부 아직 라이브 반영 안 됨.
- 데이터 정합성 개선(멱등 적재)은 코드만 고쳤을 뿐, 기존에 이미 부풀려진 Neo4j 프로덕션 카운터 자체를 재계산/백필하지는 않음(필요 시 별도 작업).

---

## [2026-07-03] 코칭 신뢰성 실사용 검증 — 오탐·환각 근절 + GitHub API 근본 버그 (7개 커밋)

### 작업 절차

1. **실사용자 리포트로 시작**: 라이브 데모에서 실제 코칭 결과를 사용자가 직접 리뷰 요청. "이 결과 어때?" 질문에 코드 대조 없이 답하지 않고, 매번 GitHub API·Neo4j로 직접 검증 후 답변.
2. **langgraph 0.x→1.x 재고정**: HF 재배포 직후 `ValueError: 'resume_eval' is already being used as a state key`로 RUNTIME_ERROR. AppState 필드명과 노드명이 같은 설계가 langgraph 0.x 전 버전(0.1.19~0.2.76 직접 설치해 재현 확인)의 add_node 검증에 걸림 — 1.2.7부터 통과. 이전 세션에 langchain 버전 드리프트를 "0.3.x 세대가 맞다"로 오진단했던 게 원인 — 실제로는 원래 `langgraph>=1.0.0`(무상한)이 맞았고, core만 구버전으로 남은 부분 업그레이드 불일치가 진짜 문제였음. 실제 그래프 컴파일을 실행하는 회귀 테스트 추가(기존 테스트는 전부 mock이라 이 버그를 못 잡았음).
3. **PART_OF 간접 실증**: "LangGraph로 멀티에이전트 RAG를 짰는데 'LLM 경험 부족' 코칭"이라는 사용자 실사례 재현. 스킬 매칭이 리터럴 이름 비교인 게 원인 — PART_OF 시드에 LangChain/OpenAI API/RAG→LLM→GenAI→AI 카테고리 체인 추가, consensus에 `expand_umbrella_skills`로 검증된 구체 스킬이 상위 스킬을 간접 실증하게 함.
4. **코칭 텍스트 파일 경로 환각 차단**: project_suggestions.how가 실존하지 않는 `src/agent/supervisor.py` 등을 지목. github_eval의 relevant_files 검증과 같은 원칙을 코칭 텍스트에도 적용(`scrub_invented_paths`) — 레포 전체 경로와 대조해 없는 파일 언급 시 project_suggestions는 항목 제거, learning은 해당 문장만 제거.
5. **reason 결정적 조립 (근본 해결)**: "일반론(생각 없이 쓴 문장)·환각(파일 지어내기)·맥락 단절(BigQuery 쓰는데 PostgreSQL 학습하라)"이 각각의 버그가 아니라 "코칭 텍스트만 이 시스템의 증거→생성→검증 루프 밖에 있다"는 한 가지 근본 원인의 증상이라고 진단. `build_deterministic_reasons`(learning) + `build_deterministic_project_reasons`(project_suggestions)로 reason을 공고 발췌·요구 건수·CO_OCCURS 보유 스킬 연결·relevant_files·current_usage 같은 **그래프 사실만으로 조립** — LLM은 문장만 다듬고 사실은 코드가 공급.
6. **약한 직접 증거가 강한 간접 실증을 막던 버그**: "AI(보유)"가 실제 배포에서 재현됨. `expand_umbrella_skills`가 `name in consensus`면 등급 상관없이 건너뛰어, 이력서에 "AI" 한 단어만 있어도(Claimed) LangGraph(Verified) 기반 간접 실증이 막힘. 등급 순위 비교로 교체.
7. **발췌 절단이 키워드를 잘라먹던 문제**: "Docker 발췌인데 Docker가 안 보임" 재현. 앞에서 90자 자르던 걸 키워드 위치 중심으로 창을 잡는 `_excerpt_around_keyword`로 교체.
8. **GitHub API 403 오탐 근본 버그 (가장 큰 발견)**: GITHUB_TOKEN 연동해도 계속 "Python(보유)"만 나옴. HF Space 실시간 로그를 직접 조회(`/api/spaces/.../logs/run`)해 사용자의 실제 분석 요청(payload 확인 포함)을 추적 — github_eval 로그가 단 한 줄도 없다는 게 단서. 원인: GitHub이 rate limit(403)에도 `{"message": "API rate limit exceeded"}` 같은 **유효한 JSON**을 반환하는데, `httpx.get(...).json()`만 호출하고 status_code를 확인 안 해 예외가 안 남 — 이 에러 dict를 실제 언어 통계인 양 파싱해버림(`lang_text = "message documentation_url"`). "실패"가 아니라 "성공적으로 틀린 데이터 사용"이라 로그도 안 남았던 것. `_get_json()` 헬퍼(raise_for_status 포함)로 5개 호출 지점 통일. 사용자가 HF Secrets에 GITHUB_TOKEN 추가(60/시간 → 5000/시간)로 재발 확률도 낮춤.
9. **"how" 필드 사실 왜곡 발견 후 전략적 중단**: 재검증에서 Python이 마침내 "검증됨"으로 나오고 project_suggestions가 실제 파일·패턴을 정확히 인용하는 것 확인. 그런데 PostgreSQL의 "how"가 "현재 프로젝트에서 데이터 저장소로 PostgreSQL을 활용하여"라고 사실과 다르게 서술(실제는 BigQuery). 사용자가 "하나씩 고치는 게 안 끝나지 않을까?"라고 질문 — 데이터 부재가 아니라 "같은 응답 안에서 ③번이 이미 알아낸 사실을 ②번 쓸 때 참조 안 하는" 일관성 문제로 진단. 자유 서술문 내부 일관성은 결정적 검증이 안 되는(문장이 무한히 변형 가능) 유형이라고 판단해 여기서 중단 결정.

### 발생 문제

- **모노레포 커밋 오염**: `/Users/leegahee/workspace`가 git 루트라 `git log -- progress.md`가 병렬로 진행 중인 다른 프로젝트(da_agent)의 커밋까지 섞어 보여줌 — `-- pj1/progress.md`로 전체 경로 지정해야 정확.
- **로그만으로는 확정 불가능한 지점들**: HF Space 로그 스트림이 SSE 버퍼라 오래된 구간이 유실될 수 있어, "GitHub URL이 전송 안 됐다" vs "전송됐지만 처리 실패"를 로그만으로 못 가름 — 사용자에게 브라우저 Network 탭 확인을 요청해 payload를 직접 받아 확정.
- **얕은 스캔과 깊은 스캔의 비대칭**: `_skills_from_sources`(빠른 키워드 매칭)는 레포 루트만 스캔하는데 `_read_source_tree`(LLM 심층 분석)는 레포 전체를 재귀로 훑음 — da_agent의 `agent_backend/requirements.txt`(중첩 경로)가 전자에는 안 잡혀 LangGraph가 Verified 대신 Corroborated로 판정됨(부분 개선, 미해결로 기록만).

### 해결 방법 / 결론

- **"실제로 확인 후 답하라"는 이번 세션 전체의 태도**: 사용자가 보여준 코칭 결과·재배포 상태를 코드 읽기만으로 판단하지 않고, 매번 Neo4j 직접 쿼리·GitHub API 직접 호출·HF Space 실시간 로그 조회로 가설을 검증한 뒤 답변. "AI(보유)"·"GitHub URL 반영 안 됨"·"Python 검증 안 됨" 전부 이 방식으로 실제 원인을 찾음(추측으로 답했다면 최소 2개는 틀렸을 것).
- **결정적 방어의 적용 범위를 알아야 함**: 구조화된 값(등급·경로·건수)은 결정적으로 완전히 막을 수 있지만, 자유 서술문의 내부 일관성은 근본적으로 다른 문제 — 이 경계를 인식하고 후자에서 전략적으로 멈추는 것도 올바른 엔지니어링 판단.
- **거짓 음성(false negative)도 거짓 양성만큼 중요**: "LLM 부족"(가진 걸 없다고 함)은 "이 파일에 이 기능이 있다"(없는 걸 있다고 함)는 고전적 환각과 반대 방향이지만 신뢰 서사에 동일하게 치명적 — 두 방향 모두 이번에 방어됨.

### 커밋 (feat/multi-agent, 7개 — pj1 경로만)

langgraph 1.x 재고정 · PART_OF 간접 실증 · 파일경로 환각 차단 · reason 결정적 조립(learning) · 약한직접증거 버그수정 · project_suggestions 근거화+발췌절단수정 · GitHub API 403 근본버그수정.

### 남은 과제

- learning_recommendations의 "how" 필드 사실 왜곡(예: 실제 스택과 다른 기술을 "현재 사용 중"이라 서술) — 전략적으로 미해결 유지. 재발 시 "이미 확인된 기술 스택" 한 줄 요약을 코칭 프롬프트 최상단에 주입하는 일반화된 가드 고려.
- `_skills_from_sources`의 매니페스트 스캔이 레포 루트만 확인 — 중첩된 requirements.txt/package.json을 놓쳐 일부 스킬이 Verified 대신 Corroborated로 저평가될 수 있음.
