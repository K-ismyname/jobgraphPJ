# CLAUDE.md — Job Skill Analyzer

Claude Code가 이 프로젝트를 처음 열었을 때 반드시 읽어야 하는 파일입니다.
코드를 짜기 전에 이 파일을 전부 읽고 결정사항을 따르세요.

---

## 프로젝트 개요

**한 줄 정의:** 채용공고를 수집·분석하고, 이력서를 올리면 직무 대비 부족한 기술과 개선 방향을 알려주는 Agentic RAG 시스템

**핵심 기능 3가지:**

1. 직무별 채용공고 수집 + 기술 트렌드 / 연봉 영향도 분석
2. PDF 이력서 업로드 → 공고 대비 갭 분석 + 매칭률 + 이력서 개선 제안
3. GitHub 선택 연동 → 신뢰도 보강 (없어도 동작, 있으면 confidence 레벨 상승)

**왜 Agentic RAG인가:**

- 단순 키워드 매칭이 아니라 LLM이 "증거가 충분한가?"를 판단하고 부족하면 다른 소스를 추가 검색 (Corrective RAG)
- 애매한 케이스는 사용자에게 되묻는 HITL 구현
- 벡터 검색(Chroma) + 그래프 검색(Neo4j)을 에이전트가 선택적으로 조합

**타겟 직무:** AI / LLM 애플리케이션 엔지니어 (Agentic RAG)

---

## 기술 스택

### 확정된 선택과 이유 (변경 금지)

| 역할        | 기술                                                 | 선택 이유                                             |
| ----------- | ---------------------------------------------------- | ----------------------------------------------------- |
| 데이터 소스 | Adzuna API                                           | 무료·개인 즉시 발급, 합법, JSON 구조화                |
| 그래프 DB   | Neo4j Aura (무료 티어)                               | 포트폴리오 이력서 작성 가능, 직무-기술 관계 표현 최적 |
| 벡터 DB     | Chroma (로컬 영구저장)                               | 설치 단순, 서버 불필요, MVP 적합                      |
| LLM         | Claude Haiku (기본), claude-sonnet-4-6 (복잡한 추론) | 비용 효율                                             |
| 에이전트    | LangGraph                                            | 조건 분기·루프·HITL이 필수라 LangChain만으로 불가     |
| PDF 파싱    | pdfplumber                                           | 레이아웃 보존, 표 추출 안정적                         |
| 평가        | Langfuse + RAGAS                                     | 트레이싱 + RAG 품질 지표 분리                         |
| 서빙        | FastAPI + Docker                                     | 표준, 면접 질문 대응 가능                             |
| 배포        | HF Spaces                                            | 무료, GPU 불필요, 데모 URL 공유 가능                  |
| 파인튜닝    | Unsloth + QLoRA                                      | Colab 무료(T4)에서 동작, 속도 최적                    |

### 사용하지 않는 것과 이유

- **LangChain Expression Language (LCEL)**: LangGraph로 대체, 혼용 금지
- **pgvector**: PostgreSQL 서버 필요, Chroma로 충분
- **Pinecone / Qdrant**: 유료 또는 설치 복잡, MVP 단계 불필요
- **vLLM**: GPU 없음, Ollama(선택) 또는 API로 대체
- **직접 크롤링 (사람인·잡코리아)**: 약관 위반 위험, Adzuna API 사용

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
│   │   └── scheduler.py        # 월별 자동 업데이트
│   │
│   ├── extraction/             # 기술 추출·정규화
│   │   ├── skill_extractor.py  # LLM 기반 구조화 추출
│   │   └── normalizer.py       # 동의어 통합 (React.js → React)
│   │
│   ├── storage/                # Layer 2: 저장소
│   │   ├── neo4j_client.py     # Neo4j MERGE 쿼리 모음
│   │   └── chroma_client.py    # Chroma 청크 저장·검색
│   │
│   ├── agent/                  # Layer 3: LangGraph 에이전트
│   │   ├── state.py            # AgentState TypedDict
│   │   ├── nodes.py            # 각 노드 함수
│   │   ├── tools.py            # 에이전트 툴 정의
│   │   └── graph.py            # StateGraph 조립
│   │
│   ├── portfolio/              # 포트폴리오 처리
│   │   ├── pdf_parser.py       # PDF → 텍스트 추출
│   │   └── github_connector.py # GitHub API (선택)
│   │
│   ├── analysis/               # Layer 4: 핵심 기능
│   │   ├── gap_analyzer.py     # 갭 분석 + 매칭률
│   │   ├── salary_analyzer.py  # 연봉 영향도
│   │   └── coach.py            # 이력서 개선 제안
│   │
│   ├── evaluation/             # Layer 5: 평가
│   │   ├── ragas_eval.py       # RAGAS 지표 측정
│   │   └── langfuse_tracer.py  # 트레이싱 데코레이터
│   │
│   └── api/                    # Layer 6: FastAPI
│       ├── main.py
│       ├── routers/
│       │   ├── jobs.py         # 공고 조회 엔드포인트
│       │   └── portfolio.py    # 이력서 업로드·갭 분석
│       └── schemas.py          # Pydantic 모델
│
└── tests/
    ├── unit/
    └── integration/
```

---

## 환경변수

`.env` 파일에 아래 키가 있어야 합니다. 없으면 mock 모드로 동작합니다.

```bash
# LLM
ANTHROPIC_API_KEY=

# 데이터 소스
ADZUNA_APP_ID=
ADZUNA_APP_KEY=

# 그래프 DB
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
(:Job       {normalized_title, aliases[], posting_count, updated_at})
(:Skill     {name, category, frequency, aliases[]})
(:JobPosting{source_id, title, company, location,
             salary_min, salary_max, contract_type,
             url, posted_at, is_active})
(:PortfolioItem {item_id, title, type, owner, created_at})
```

### 관계

```cypher
(Job)-[:REQUIRES   {weight}]  ->(Skill)       # 필수 기술
(Job)-[:PREFERS    {weight}]  ->(Skill)       # 우대 기술
(Job)-[:SAME_AS    {similarity_score}]->(Job) # 직무 정규화
(Skill)-[:PART_OF  {relation}]->(Skill)       # 생태계 (LangChain→LangGraph)
(Skill)-[:CO_OCCURS{count}]   ->(Skill)       # 공고 내 동시 등장
(PortfolioItem)-[:DEMONSTRATES{evidence, confidence}]->(Skill)
(JobPosting)-[:INSTANCE_OF]  ->(Job)
```

### confidence 레벨 규칙

- `high`: 이력서에 기술명이 명시적으로 언급됨
- `medium`: 문맥상 사용했음이 추론됨
- `low`: 간접적으로 언급됨
- GitHub 코드 확인 시 한 단계 상승 가능

---

## LangGraph 에이전트 구조

```
START
  └→ call_model (LLM 판단: 어떤 툴 쓸까?)
       ├→ [tool] resume_search    벡터 RAG (Chroma)
       ├→ [tool] graph_query      Neo4j Cypher
       ├→ [tool] job_db_query     공고 통계·연봉
       └→ [tool] github_check     GitHub API (선택)
            └→ call_model (증거 충분한가? Corrective 판단)
                 ├→ 부족하면 → 다시 tool 호출 (루프)
                 ├→ 애매하면 → HITL (interrupt → 사용자 입력 → resume)
                 └→ 충분하면 → END (갭 분석 리포트)
```

**규칙:**

- State는 `src/agent/state.py`의 `AgentState` TypedDict만 사용
- 새 툴 추가 시 `src/agent/tools.py`에 `@tool` 데코레이터로 정의
- 노드 함수는 반드시 `AgentState → AgentState` 시그니처 유지

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
UPSERT_JOB = """MERGE (j:Job ..."""

# Pydantic 모델: PascalCase
class ExtractedSkill(BaseModel):
class GapAnalysisResult(BaseModel):
```

### 타입 힌트

모든 함수에 타입 힌트 필수입니다. `Any` 사용을 최대한 피하세요.

```python
# Good
def normalize_skill(raw: str) -> str:
def extract_skills(job: dict, client: Anthropic) -> JobSkills:

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
│   └── test_gap_analyzer.py    # 갭 분석 로직 테스트
└── integration/
    ├── test_neo4j.py           # Neo4j MERGE 쿼리 (실 DB)
    └── test_agent.py           # LangGraph 전체 흐름 (mock LLM)
```

### 원칙

- 외부 API (Anthropic, Adzuna, Neo4j)는 mock으로 테스트합니다
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
