# CLAUDE.md — Job Skill Analyzer

Claude Code가 이 프로젝트를 처음 열었을 때 반드시 읽어야 하는 파일입니다.
코드를 짜기 전에 이 파일을 전부 읽고 결정사항을 따르세요.

---

## 프로젝트 개요

**한 줄 정의:** 채용공고를 수집·분석하고, 이력서를 올리면 직무 대비 부족한 기술과 개선 방향을 알려주는 Agentic RAG 시스템

**핵심 기능 3가지:**

1. 직무별 채용공고 수집 + 직군별 핵심 기술·트렌드 분석 (연봉 영향도는 공고의 연봉 공개율이 낮아 보조 지표로만 산출)
2. PDF 이력서 업로드 → 공고 대비 갭 분석 + 매칭률 + 이력서 개선 제안
3. GitHub 선택 연동 → 신뢰도 보강 (없어도 동작, 있으면 confidence 레벨 상승)

**왜 Agentic RAG인가:**

- 단순 키워드 매칭이 아니라 LLM이 "증거가 충분한가?"를 판단하고 부족하면 다른 소스를 추가 검색 (Corrective RAG)
- 애매한 케이스를 위한 HITL을 interrupt 기반으로 **설계**(ask_human 툴·확장 지점 마련). 라이브 운영은 자동 모드가 기본이며, 불확실성은 confidence 등급·advice로 논블로킹 처리한다. HITL을 켜려면 checkpointer 재부착 + API resume 경로가 필요하다.
- 그래프 검색(Neo4j)과 통계 도구를 에이전트가 선택적으로 조합 (초기 도입한 Chroma 벡터검색은 효과를 측정해 제거 — 아래 "사용하지 않는 것" 참고)

**타겟 직무:** AI / LLM 애플리케이션 엔지니어 (Agentic RAG)

---

## 기술 스택

### 확정된 선택과 이유 (변경 금지)

| 역할        | 기술                                                 | 선택 이유                                             |
| ----------- | ---------------------------------------------------- | ----------------------------------------------------- |
| 데이터 소스 | The Muse / RemoteOK (주력), Adzuna (배제)            | 아래 "데이터 소스 결정" 참고 — Adzuna는 본문 결함으로 직군 분석에서 제외 |
| 그래프 DB   | Neo4j Aura (무료 티어)                               | 포트폴리오 이력서 작성 가능, 직무-기술 관계 표현 최적 |
| LLM         | OpenAI gpt-4o-mini (기본), gpt-4o (복잡한 추론)      | 비용 효율, 단일 공급자(OpenAI)로 통일                 |
| 에이전트    | LangGraph                                            | 조건 분기·루프(+HITL 확장 지점)가 필수라 LangChain만으로 불가 |
| PDF 파싱    | pdfplumber                                           | 레이아웃 보존, 표 추출 안정적                         |
| 평가        | Langfuse + RAGAS                                     | 트레이싱 + RAG 품질 지표 분리                         |
| 서빙        | FastAPI + Docker                                     | 표준, 면접 질문 대응 가능                             |
| 배포        | HF Spaces                                            | 무료, GPU 불필요, 데모 URL 공유 가능                  |
| 파인튜닝    | Unsloth + QLoRA                                      | Colab 무료(T4)에서 동작, 속도 최적                    |

### 데이터 소스 결정 (측정 기반)

한국 채용 데이터를 쓰려 했으나 API 접근이 허용되지 않았고, 직접 크롤링(사람인·잡코리아)은
약관 위반 위험이 있어 해외 채용 API를 사용한다.

| 소스 | 상태 | 근거 |
| --- | --- | --- |
| The Muse | **직군 분석 주력** | 본문(`contents`)이 충실해 스킬 추출이 정확 |
| RemoteOK | **직군 분석 주력** | 위와 동일 |
| Adzuna | **직군 분석에서 배제** | 무료 API가 `description`을 500자로 truncate → 본문이 빈약해 LLM이 인프라 스킬(Docker/K8s/Terraform 등)을 환각. 미분류 공고 2,769건의 89%가 동일 5스킬 조합이었다 |

**Adzuna 배제 경위 (2026-06-30):** 미분류 공고를 직군에 연결(백필)했더니 9개 직군 중 8개의
상위 스킬이 동일한 인프라 스킬로 도배됐다. 추적 결과 그 공고의 98%가 Adzuna였고, 원문을 열어보니
본문이 한 문장뿐이거나 비어 있었다. 백필을 롤백하고 Muse/RemoteOK 604건만 직군 분석에 쓴다.

**잔존 오염 제거 (2026-07-12):** 위 롤백은 `INSTANCE_OF`만 제거해, 미분류 공고의 `REQUIRES`
관계 11,682개가 근거 검색·공고 수 집계에 그대로 섞여 있었다(Docker 근거 조회 시 97%가 미분류
공고). 관련 쿼리 3개에 `INSTANCE_OF` 조건을 추가해 분류된 공고만 집계하도록 수정했다.

> ⚠️ 재현성: 배포에 쓰인 604건을 수집한 스크립트(`collect_and_merge.py`, `remoteok_client.py`)가
> 삭제되어 현재 코드로는 이 데이터셋을 처음부터 재현할 수 없다. git 이력에서 복원 필요.

### 사용하지 않는 것과 이유

- **LangChain Expression Language (LCEL)**: LangGraph로 대체, 혼용 금지
- **Chroma / 벡터 검색**: 초기 도입했으나 검색 12건 중 11건이 키워드 매칭과 동일해 효과 없음을 측정하고 제거, Neo4j 그래프로 통합
- **pgvector**: PostgreSQL 서버 필요 + 벡터 검색 자체를 제거해 불필요
- **Pinecone / Qdrant**: 유료 또는 설치 복잡, 벡터 검색 미사용
- **vLLM**: GPU 없음, Ollama(선택) 또는 API로 대체
- **직접 크롤링 (사람인·잡코리아)**: 약관 위반 위험, 공식 API 사용

---

## 프로젝트 구조

```
job-skill-analyzer/
├── CLAUDE.md                   # 이 파일
├── README.md                   # 공개 포트폴리오 문서
├── .env.example                # 환경변수 템플릿
├── .env                        # 실제 키 (git 제외)
├── docker-compose.yml
├── requirements.txt
│
├── data/
│   └── seeds/
│       └── skill_relations.json  # PART_OF 시드 (LangChain→LangGraph 등 수동 정의)
│
├── src/
│   ├── ingestion/              # Layer 1: 데이터 수집
│   │   ├── adzuna_client.py    # Adzuna API 호출
│   │   ├── preprocessor.py     # 공고 텍스트 정제·섹션 분리
│   │   └── pipeline.py         # 수집→추출→Neo4j 적재 파이프라인
│   │
│   ├── extraction/             # 기술 추출·정규화
│   │   ├── skill_extractor.py  # LLM 기반 구조화 추출
│   │   └── normalizer.py       # 동의어 통합 (React.js → React)
│   │
│   ├── storage/                # Layer 2: 저장소
│   │   └── neo4j_client.py     # Neo4j MERGE·조회 쿼리 모음
│   │
│   ├── agent/                  # Layer 3: LangGraph 에이전트
│   │   ├── state.py            # AgentState TypedDict
│   │   ├── nodes.py            # 각 노드 함수 (Gap 루프·코칭 포함)
│   │   ├── tools.py            # 에이전트 툴 정의
│   │   ├── consensus.py        # 교차검증 신뢰도 등급 판정
│   │   ├── critic.py           # 환각 제거·라벨 교정
│   │   ├── evaluators/         # 소스별 전용 평가자 (resume·github·portfolio·deploy)
│   │   └── supervisor.py       # StateGraph 조립·실행
│   │
│   ├── portfolio/              # 포트폴리오 처리
│   │   ├── pdf_parser.py       # PDF → 텍스트 추출
│   │   └── github_connector.py # GitHub API (선택)
│   │
│   ├── analysis/               # Layer 4: 핵심 기능
│   │   ├── capability.py       # 직군 핵심 스킬 대비 적합도·역방향 추천
│   │   └── salary_analyzer.py  # 연봉 영향도 (보조 지표)
│   │   # 갭 분석·매칭률은 src/agent/tools.py의 gap_analysis 툴에서 수행
│   │
│   ├── evaluation/             # Layer 5: 평가
│   │   ├── ragas_eval.py       # RAGAS 지표 측정
│   │   └── langfuse_tracer.py  # 트레이싱 데코레이터
│   │
│   └── api/                    # Layer 6: FastAPI
│       ├── main.py             # 앱 진입점·lifespan
│       ├── deps.py             # 의존성 주입 (neo4j·openai)
│       ├── routers/
│       │   ├── jobs.py         # 공고 조회·통계 엔드포인트
│       │   ├── portfolio.py    # 이력서 업로드·갭 분석
│       │   └── system.py       # 그래프 구조 조회 (관측 페이지)
│       └── schemas.py          # Pydantic 모델
│
└── tests/
    ├── unit/
    └── integration/
```

---

## 환경변수

`.env` 파일에 아래 키가 있어야 합니다. **Neo4j는 필수**(없으면 `EnvironmentError`로 기동 실패)이고, OpenAI·Adzuna·GitHub·Langfuse는 없으면 각각 mock·캐시·비활성으로 동작합니다.

```bash
# LLM
OPENAI_API_KEY=

# 데이터 소스
ADZUNA_APP_ID=
ADZUNA_APP_KEY=

# 그래프 DB (필수 — 없으면 기동 실패)
NEO4J_URI=neo4j+s://xxxx.databases.neo4j.io
NEO4J_USER=neo4j
NEO4J_PASSWORD=

# 평가
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=https://cloud.langfuse.com

# GitHub (선택)
GITHUB_TOKEN=
```

**규칙:** 키를 코드에 하드코딩하지 마세요. 반드시 `os.getenv()`로 읽고, 없으면 mock 데이터로 fallback 하세요.

---

## Neo4j 스키마 (변경 시 여기도 업데이트)

### 노드

```cypher
(:JobFamily {name, posting_count})            # 정규화된 직군 (구 :Job)
(:Company   {name, posting_count})
(:Skill     {name, category, frequency, aliases[]})
(:JobPosting{source_id, title, company, location,
             salary_min, salary_max, contract_type,
             url, posted_at, is_active})
```

### 관계

```cypher
(JobPosting)-[:REQUIRES {weight}]->(Skill)    # 필수 기술
(JobPosting)-[:PREFERS  {weight}]->(Skill)    # 우대 기술
(JobPosting)-[:INSTANCE_OF]->(JobFamily)      # 공고 → 직군 분류
(JobPosting)-[:POSTED_BY]->(Company)          # 공고 → 회사
(Skill)-[:PART_OF  {relation}]->(Skill)       # 생태계 (LangChain→LangGraph)
(Skill)-[:CO_OCCURS{count}]   ->(Skill)       # 공고 내 동시 등장
```

### confidence 레벨 규칙

이력서·포트폴리오에서 추출한 `DemonstratedSkill.confidence` 값 — Neo4j에는 저장하지 않고
에이전트 실행 중 메모리(consensus)에서만 다룬다.

- `high`: 이력서에 기술명이 명시적으로 언급됨
- `medium`: 문맥상 사용했음이 추론됨
- `low`: 간접적으로 언급됨
- GitHub 코드 확인 시 한 단계 상승 가능

---

## LangGraph 에이전트 구조

Supervisor `StateGraph` — 입력에 있는 소스의 평가자만 병렬 fan-out(Send) → 합의 → Gap 서브그래프 → 검증 → Coach 서브그래프.

```
START
  └→ (dispatch: 입력에 있는 소스만 Send로 fan-out)
       ├→ resume_eval    이력서 (텍스트 추출)     ─┐
       ├→ github_eval    GitHub repo (코드 근거)  ─┤ (병렬)
       ├→ portfolio_eval 포트폴리오 PDF (멀티모달) ─┤
       └→ deploy_eval    배포 URL (웹)            ─┘
                              ▼
                         consensus (검증 등급 결정적 판정 — LLM 미사용)
                              ▼
                         seed_gap → gap_agent (Corrective RAG ReAct 루프, 서브그래프)
                              │        call_model ↔ tools (gap_analysis·verify_skills·
                              │        skill_unlock·posting_trend·ask_human)
                              ▼
                         synthesizer (적합도+신뢰도 리포트)
                              ▼
                         critic (consensus 대조 — 환각 제거·라벨 교정, 결정적)
                              ▼
                         coach_agent (면접 코칭·프로젝트 제안, 서브그래프) → END
```

ask_human(HITL)은 설계된 확장 지점 — 기본은 자동 모드이며, 라이브 활성화하려면 `HITL_ENABLED=true` + 그래프 checkpointer 재부착 + API resume 경로가 필요하다.

**규칙:**

- State는 `src/agent/state.py`의 `AppState`(Supervisor) / `GapState` / `CoachState` TypedDict 사용
- Gap 툴은 `src/agent/tools.py`, Coach 툴은 같은 파일의 `create_coach_tools`에 `@tool`로 정의
- 노드 함수는 `State → dict`(부분 업데이트) 시그니처 유지

---

## 코드 컨벤션

### 네이밍

```python
# 파일명: snake_case
skill_extractor.py
neo4j_client.py

# 클래스: PascalCase
class SkillExtractor:
class Neo4jClient:

# 함수·변수: snake_case
def extract_skills(text: str) -> JobSkills:
normalized_title = "AI Engineer"

# 상수: UPPER_SNAKE_CASE
DEFAULT_CHUNK_SIZE = 500
SKILL_ALIASES = {...}

# Neo4j 쿼리 변수: UPPER_SNAKE_CASE
UPSERT_JOB_FAMILY = """MERGE (jf:JobFamily ..."""

# Pydantic 모델: PascalCase
class ExtractedSkill(BaseModel):
class GapAnalysisResult(BaseModel):
```

### 타입 힌트

모든 함수에 타입 힌트 필수입니다. `Any` 사용을 최대한 피하세요.

```python
# Good
def normalize_skill(raw: str) -> str:
def extract_skills(job: dict, client: OpenAI) -> JobSkills:

# Bad
def normalize_skill(raw):
def extract_skills(job, client):
```

### 에러 처리

API 호출·DB 연결은 반드시 try/except 처리하고, 실패 시 mock으로 fallback 합니다.

```python
# Good
try:
    result = neo4j_session.run(query, **params)
except Exception as e:
    logger.error(f"Neo4j 쿼리 실패: {e}")
    return []

# Bad: 에러 그냥 올리기
result = neo4j_session.run(query)
```

### LLM 응답 파싱

LLM 출력은 항상 JSON 펜스 제거 후 파싱합니다.

````python
raw = response.content[0].text.strip()
raw = raw.replace("```json", "").replace("```", "").strip()
data = json.loads(raw)
````

### mock 모드

환경변수 없어도 반드시 동작해야 합니다.

```python
def fetch_jobs(query: str) -> list[dict]:
    if not os.getenv("ADZUNA_APP_ID"):
        print("[mock] ADZUNA 키 없음 — 샘플 데이터 사용")
        return MOCK_JOBS
    # 실 API 호출
```

---

## 커밋 메시지 규칙

```
<type>(<scope>): <subject>

type:
  feat     새 기능
  fix      버그 수정
  refactor 기능 변경 없는 코드 개선
  test     테스트 추가·수정
  docs     문서 수정 (README, CLAUDE.md 등)
  chore    빌드·설정 변경

scope:
  ingestion | extraction | storage | agent | portfolio
  analysis  | evaluation | api     | infra

예시:
  feat(agent): LangGraph Corrective RAG 루프 구현
  feat(storage): Neo4j CO_OCCURS 관계 자동 생성 추가
  fix(extraction): LLM JSON 파싱 실패 시 fallback 처리
  feat(evaluation): RAGAS faithfulness 지표 측정 추가
  docs: CLAUDE.md 스키마 섹션 업데이트
```

---

## 테스트 규칙

### 구조

```
tests/
├── unit/
│   ├── test_normalizer.py      # normalize_skill() 동의어 테스트
│   ├── test_pdf_parser.py      # PDF 텍스트 추출 테스트
│   ├── test_consensus.py       # 합의 검증 등급 판정 테스트
│   └── test_critic.py          # 환각 제거·라벨 교정 테스트
└── integration/
    ├── test_neo4j.py           # Neo4j MERGE 쿼리 (실 DB)
    └── test_agent.py           # LangGraph 전체 흐름 (mock LLM)
```

### 원칙

- 외부 API (OpenAI, Adzuna, Neo4j)는 mock으로 테스트합니다
- `normalize_skill()` 같은 순수 함수는 반드시 단위 테스트를 작성합니다
- LangGraph 에이전트 테스트는 `langchain_core.messages`의 mock 메시지로 합니다

```python
# 단위 테스트 예시
def test_normalize_skill():
    assert normalize_skill("React.js") == "React"
    assert normalize_skill("리액트")   == "React"
    assert normalize_skill("langgraph") == "LangGraph"

# mock 모드 테스트 예시
def test_fetch_jobs_mock():
    # 환경변수 없을 때 mock 반환 확인
    jobs = fetch_jobs("ai engineer")
    assert len(jobs) > 0
    assert "title" in jobs[0]
    assert "skills" in jobs[0]
```

---

## 주요 명령어

```bash
# 환경 설정
cp .env.example .env          # 환경변수 파일 생성
pip install -r requirements.txt

# 데이터 수집 (Adzuna → Neo4j)
python -m src.ingestion.adzuna_client

# 이력서 처리
python -m src.portfolio.pdf_parser resume.pdf

# 에이전트 실행 (갭 분석)
python -m src.agent.supervisor

# FastAPI 서버
uvicorn src.api.main:app --reload --port 8000

# Docker
docker-compose up --build

# 테스트
pytest tests/unit/
pytest tests/integration/    # Neo4j 연결 필요

# RAGAS 평가
python -m src.evaluation.ragas_eval
```

---

## 개발 순서 (Build Order)

1단계 완료: Layer 1·2 (수집·저장) — module1, module2, module3
2단계 진행: Layer 3 (LangGraph 에이전트 오케스트레이션)
3단계 예정: Layer 4 (갭 분석·연봉·이력서 코치)
4단계 예정: Layer 5 (Langfuse + RAGAS 평가)
5단계 예정: Layer 6 (FastAPI + Docker + 배포)
6단계 예정: 파인튜닝 (Unsloth QLoRA) + 블로그

**원칙: 뒤 레이어를 앞 레이어보다 먼저 짜지 않습니다.**
API 서버는 에이전트가 완성된 후에, 평가는 기능이 완성된 후에 붙입니다.

---

## RAGAS 평가 — 측정 결과와 한계 (정직하게)

`python -m src.evaluation.ragas_eval` (기본 3회 반복, `RAGAS_RUNS`로 조정)

**실측 (2026-07-12, 2케이스 × 3회, 평균 ± 표준편차)**

| 평가 대상 | Faithfulness | Answer Relevancy |
| --- | --- | --- |
| 옵션 A — gap_agent의 `reason` (**실제 제품 출력**) | 0.535 ± 0.107 | 0.372 ± 0.080 |
| 옵션 B — 스킬 숙련도 Q&A (평가 전용 경로) | 0.533 ± 0.126 | **0.635 ± 0.003** |

**이 표에서 반드시 알아야 할 것**

1. **과거에 기록했던 "옵션 B는 Faithfulness 0.70대"는 재현되지 않았다.** 단일 실행 결과였고,
   3회 반복하니 0.533 ± 0.126으로 내려앉았다. RAGAS는 LLM이 채점하므로 표본 5개 규모에서는
   실행마다 metric이 0/1로 튄다 — **단일 실행 수치로 결론을 내면 안 된다.**
2. **두 옵션의 Faithfulness 차이는 근거가 없다** (0.535 vs 0.533, 변동폭 ±0.11~0.13이 그 차이보다 크다).
   "그래프로 답할 수 없는 질문이라야 Faithfulness가 높다"던 기존 결론은 **스스로 반증했다.**
3. 유의미한 차이는 **Answer Relevancy**뿐이다 (0.372 → 0.635, 옵션 B의 표준편차 0.003으로 안정적).
   즉 질문 설계의 이점은 "근거 충실도"가 아니라 **"질문에 실제로 답하는가"**에 있었다.

**개선 후 현재 값 (2026-07-13)** — 위 표의 옵션 A는 개선 전 baseline이다. `reason` 프롬프트에
근거 제약을 넣어 **0.535 → 0.663 (AR 0.372 → 0.354로 유지)**. 이때 "근거 없으면 최소한만 쓰라"는
강한 제약안도 측정했는데 Faithfulness 0.833까지 올랐으나 **AR이 0.116으로 붕괴**했다 — 환각은
없지만 질문에 답을 못 하는 리포트가 된다. 두 축은 트레이드오프 관계이므로 **한쪽만 보고 조이면 안 된다.**

---

## 갭 목록 정확도 — 골든셋 기반 precision / recall

`python -m src.evaluation.golden_eval`

RAGAS Faithfulness는 "말한 것이 근거에 있는가"만 잰다 — **갭 목록 자체가 틀려도 근거만 성실히
인용하면 만점**이 나온다. critic도 consensus와의 *내부 일관성*만 볼 뿐 *현실과의 일치*는 못 본다.
이 시스템의 실제 가치("조언이 맞는가")를 재는 유일한 지표가 이것이다.

**정답 라벨**: `data/golden/job_family_core_skills.json` — 직군별 핵심 스킬을 사람이 확정.
케이스별 정답은 `core - 보유스킬`로 자동 도출된다.

**측정 결과 (8케이스)**

| 시점 | Precision | Recall | F1 |
| --- | --- | --- | --- |
| 최초 측정 | 0.428 | 0.750 | 0.534 |
| 노이즈 스킬 제거 후 | **0.511** | **0.929** | **0.713** |

**골든셋을 만들자마자 드러난 결함**

1. **개념어가 스킬로 적재되고 있었다.** "APIS", "DevOps", "Distributed Systems"가 :Skill 노드로
   존재해 "DevOps가 부족합니다" 같은 실행 불가능한 조언이 나갔다. 원인은 `is_noise_skill()`이
   정의만 되고 적재 파이프라인에서 **호출되지 않는 죽은 코드**였던 것. 배선 후 라이브 DB에서
   노이즈 38개(관계 397건)를 제거하니 **precision·recall이 동시에 올랐다** — 노이즈가 빈도 상위
   10개를 차지해 진짜 필요한 스킬(Ansible, CI/CD)을 밀어내고 있었기 때문이다.
2. **R이 노이즈로 걸릴 뻔했다.** `len(name) <= 1` 조건 때문. R은 Data Analyst의 핵심 스킬이고
   REQUIRES 21건을 갖고 있어, 확인 없이 배선했으면 통째로 잃었다. → `_SHORT_VALID_SKILLS` 예외.

**남은 결함 (다음 과제)**

- **대체 관계를 모른다.** 남은 오탐의 대부분이 이것이다 — 클라우드 3사(AWS/Azure/GCP)를 *전부*
  부족하다고 지목하고, React를 쓰는 지원자에게 Angular·Vue를 요구한다. 핵심 스킬을 100% 보유한
  지원자(`fe_mid`)에게도 5개를 지목해 **precision 0.00**이 나온다. "빈도 상위 10개"를 무조건 채우는
  `_CORE_REQUIRED_N` 휴리스틱이 원인이다.
- 골든셋 라벨은 아직 **DRAFT**다. 각 직군의 `core`/`excluded` 판단은 검수가 필요하다.
- 케이스가 8개뿐이고 실제 이력서 PDF가 아니라 손으로 구성한 스킬 목록이다.

---

## 이 공고를 타겟으로 개발 중

```
필수: LangGraph AI 시스템 구축 경험
필수: PoC → MVP → 배포 경험
핵심: "왜 이 답을 신뢰할 수 있는지" → confidence + evidence + RAGAS
핵심: "RAG 구조를 다시 설계" → 설계 의사결정을 README·블로그에 문서화
우대: Hybrid Search (BM25 + dense)
우대: 평가 파이프라인 직접 구축
```

코드를 짤 때 이 키워드들이 코드와 README에 자연스럽게 반영되어야 합니다.

---

## /log-update

대화 종료 전 항상 실행:
- `progress.md` 열기
- `## [날짜]` 섹션 추가
- 작업 절차 / 발생 문제 / 해결 방법 3단 구조로 기록
