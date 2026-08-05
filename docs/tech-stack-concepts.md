# 기술 스택 개념 정리 (코드 전수 검증본)

이 문서는 CLAUDE.md의 기술 스택 표를 출발점으로 하되, `requirements.txt`와 `src/`·`scripts/`의 실제 import 구문·코드를 전수 대조해 검증한 결과입니다. CLAUDE.md 표에 없지만 코드에 실재하는 것, 반대로 문서에만 있고 코드엔 없는 것을 모두 표시했습니다.

---

## 0. requirements.txt 실제 의존성 (전수)

| 패키지 | 버전 제약 | 역할 |
|---|---|---|
| `openai` | >=1.0.0 | LLM 호출 (추출·평가·생성) + 임베딩 + Vision |
| `langgraph` | >=1.0.0,<2 | 에이전트 그래프 오케스트레이션 |
| `langchain-openai` | >=1.0,<2 | LangGraph 노드에서 쓰는 `ChatOpenAI` 래퍼 |
| `langchain-core` | >=1.0,<2 | `@tool`, 메시지 타입(`HumanMessage` 등) |
| `neo4j` | >=5.0.0 | 그래프 DB 드라이버 |
| `httpx` | >=0.27.0 | 모든 외부 HTTP 호출 (공고 수집·GitHub API·배포 URL fetch) |
| `pdfplumber` | >=0.11.0 | PDF 텍스트 레이어 추출 |
| `pymupdf` | >=1.24.0 | PDF 페이지를 이미지로 렌더링 (Vision 입력용) |
| `pydantic` | >=2.0.0 | 스키마 검증 (추출 결과·API 요청/응답) |
| `python-dotenv` | >=1.0.0 | `.env` 로드 |
| `fastapi` | >=0.115.0 | REST API 서버 |
| `uvicorn[standard]` | >=0.30.0 | ASGI 서버 (FastAPI 구동) |
| `python-multipart` | >=0.0.9 | 파일 업로드(PDF) 폼 파싱 |
| `ragas` | ~=0.4.0 | RAG 품질 평가 지표 |
| `langfuse` | ~=4.0 | LLM 트레이싱 |
| `pytest` | >=8.0.0 | 테스트 |

**CLAUDE.md 표에 없던 실사용 패키지:** `httpx`, `pymupdf`, `langchain-openai`, `langchain-core`, `python-multipart`. Unsloth/QLoRA는 requirements에 **없음**(파인튜닝 미착수).

---

## 1. 데이터 수집 계층

### httpx (모든 외부 HTTP의 공통 클라이언트)
공고 수집, GitHub API, 배포 URL 확인까지 이 프로젝트의 모든 외부 HTTP 요청이 `httpx`로 이뤄집니다. `requests`와 API가 거의 같은 동기 HTTP 클라이언트지만, 타임아웃·리다이렉트 추적(`follow_redirects=True`) 같은 옵션을 명시적으로 다룹니다.

### The Muse API (실제 메인 데이터 소스)
`scripts/collect_muse.py`가 쓰는 무료 공개 API(`https://www.themuse.com/api/public/jobs`)입니다. **API 키가 필요 없고**, 공고 설명 전체 텍스트를 제공해서 스킬 추출 근거가 충실합니다. 카테고리(Software Engineering / Data and Analytics / Design and UX)별로 수집하고, 직무명 화이트리스트 + 회사당 상한으로 품질을 거릅니다.

### Adzuna API (문서엔 메인, 코드에선 이탈)
CLAUDE.md는 Adzuna를 메인 소스로 기재하지만, 실제 적재 파이프라인 `src/ingestion/pipeline.py`는 `adzuna_client`를 **import하지 않습니다.** Adzuna 응답 본문이 빈약해 LLM이 스킬을 근거 없이 지어내는 환각이 발생했기 때문입니다. `adzuna_client.py`를 호출하는 코드는 `scripts/collect_raw.py` 하나뿐입니다.

### 수집→적재 파이프라인 (`src/ingestion/pipeline.py`)
로컬 raw JSON을 읽어 3단계로 처리합니다.
1. **preprocess** (`preprocessor.py`) — HTML 태그 제거(`html` 표준 라이브러리), 공고 본문을 섹션(자격요건/우대사항 등)으로 분리.
2. **extract + normalize** — `skill_extractor.py`로 스킬 구조화 추출, `normalizer.py`로 동의어 통합.
3. **load** (`neo4j_client.py`) — Neo4j에 MERGE로 적재.

---

## 2. 저장 계층 — Neo4j

### 그래프 데이터베이스
RDB가 테이블과 외래키로 관계를 표현하는 것과 달리, Neo4j는 "노드(개체)"와 "관계(엣지)"를 1급 시민으로 저장합니다. "이 기술을 배우면 연결된 다른 기술까지 요구하는 공고가 몇 개인가"처럼 다단계 관계 탐색이 핵심인 이 프로젝트에는 SQL의 JOIN보다 그래프 쿼리(Cypher)가 간결하고 빠릅니다. 드라이버는 `neo4j.GraphDatabase`, 쿼리 언어는 Cypher입니다.

### MERGE 패턴 (멱등성)
"있으면 매칭, 없으면 생성"하는 UPSERT 연산입니다. 파이프라인을 여러 번 재실행해도 같은 노드가 중복 생성되지 않도록 멱등성(idempotency)을 보장합니다.

### 배포 환경별 Neo4j
- 운영: Neo4j Aura(완전관리형 클라우드, 무료 티어), `neo4j+s://` 보안 연결.
- 로컬: `docker-compose.yml`이 `neo4j:5.24-community` 컨테이너를 함께 띄움(`bolt://neo4j:7687`).

---

## 3. LLM — OpenAI

### 모델 티어링 (gpt-4o-mini / gpt-4o)
gpt-4o-mini는 저비용·저추론, gpt-4o는 고비용·고추론입니다. 작업 난이도별로 나눠 써서 비용을 관리합니다. 단일 공급자(OpenAI)로 통일한 이유는 공급자 간 API 스펙 차이(함수 호출 포맷·토큰 계산) 관리 복잡도를 없애기 위함입니다.

### Structured Output (JSON 모드)
스킬 추출(`skill_extractor.py`)은 `response_format={"type": "json_object"}` + `temperature=0`으로 호출합니다. 이러면 LLM이 JSON 펜스(```json)나 잡담을 섞지 못하고 순수 JSON만 반환하도록 **API 레벨에서 강제**되어, 파싱 실패가 원천 차단됩니다. 반환된 JSON은 Pydantic `BaseModel`(`ResumeExtraction`, `DemonstratedSkill` 등)로 검증합니다.

### Vision (멀티모달)
포트폴리오 평가(`portfolio_eval.py`)는 텍스트 PDF는 텍스트로, **이미지 페이지는 vision으로** 처리합니다. 구체적으로 `pymupdf`(fitz)로 PDF 페이지를 이미지로 렌더링 → `base64`로 인코딩 → gpt-4o Vision 입력으로 전달합니다. CLAUDE.md 아키텍처의 "포트폴리오 PDF (멀티모달)"이 코드에서 이렇게 구현돼 있습니다.

### 임베딩 (검색용 아님 — RAGAS 평가용)
`ragas_eval.py`가 `OpenAIEmbeddings(model="text-embedding-3-small")`를 씁니다. **주의:** 이건 검색(retrieval)용이 아니라 RAGAS의 `answer_relevancy` 지표를 계산하기 위한 것입니다. "벡터 검색을 제거했다"는 서술은 여전히 유효합니다 — 임베딩은 평가 파이프라인에서만 등장합니다.

---

## 4. 에이전트 오케스트레이션 — LangGraph

### 그래프 기반 흐름 제어
LLM 호출 흐름을 그래프로 정의합니다. 순차 실행만 되는 일반 체인과 달리, 조건 분기(consensus 낮으면 재검색)와 반복(gap_agent가 증거 부족 시 tool 반복 호출)을 표현할 수 있습니다. 사용 심볼: `StateGraph`, `START`/`END`, `Send`, `add_messages`.

### 버전 고정 이유 (requirements.txt 주석 근거)
langgraph 0.x는 `add_node`에서 "노드명이 State TypedDict 필드명과 같으면 안 된다"는 검증이 있어, `AppState.resume_eval`과 이름이 겹치는 노드 등록 시 `ValueError`로 빌드가 실패합니다. 0.1.19~0.2.76 재현, 1.2.7부터 통과 → `>=1.0.0,<2`로 고정. `langchain-core`/`langchain-openai`도 같은 1.x 세대로 통일.

### State 스키마 (TypedDict)
각 노드는 "현재 상태(dict)를 받아 갱신할 부분만 반환"합니다. `AppState`(Supervisor)·`GapState`·`CoachState`가 `typing_extensions.TypedDict`로 스키마를 정의합니다. `messages` 필드는 `add_messages` 리듀서로 append 병합되어, 병렬 노드가 충돌 없이 대화 이력을 누적합니다.

### Send 기반 동적 fan-out
입력에 존재하는 소스의 평가자만 실행 시점에 골라 병렬 전송합니다. 이력서만 있으면 `resume_eval`만, GitHub 링크까지 있으면 `github_eval`도 동시에.

### 서브그래프
`gap_agent`, `coach_agent`는 각각 독립된 작은 `StateGraph`입니다. 메인 그래프 안에 중첩시켜 복잡한 ReAct 반복 로직을 하나의 노드처럼 캡슐화합니다.

### checkpointer 없이 컴파일 (의도된 선택)
그래프는 checkpointer(상태 저장소) 없이 컴파일됩니다. HITL(interrupt→resume)을 라이브로 안 쓰기 때문입니다. `MemorySaver`를 붙이면 실행마다 thread_id별 체크포인트가 무한 누적(메모리 누수)되고 읽히지도 않으므로, HITL을 켤 때만 checkpointer 재부착 + API resume 엔드포인트를 추가하도록 설계했습니다.

---

## 5. 핵심 아키텍처 패턴

### Agentic RAG
일반 RAG는 "질문→검색→검색 문서를 근거로 답변"으로 끝나는 고정 파이프라인입니다. Agentic RAG는 LLM이 "지금 근거로 충분한가?"를 스스로 판단해, 부족하면 다른 도구를 골라 추가 호출합니다. `gap_agent`가 아래 tool들 중 필요한 것을 선택·반복 호출하는 것이 이것입니다.

### gap_agent가 쓰는 실제 tool (`tools.py`)
`create_tools()`가 5개를 반환합니다.
- `gap_analysis` — 이력서 스킬 vs 직군 요구 스킬 갭·매칭률 산출.
- `verify_skills` — 특정 스킬을 실제로 요구하는 공고 근거 확인.
- `skill_unlock` — 이 스킬을 배우면 추가로 열리는 공고(그래프 확장 탐색).
- `posting_trend` — 공고 트렌드 통계.
- `ask_human` — HITL 확장 지점(`langgraph.types.interrupt`, 기본 비활성).

coach_agent 툴(`create_coach_tools`): `verify_suggestion`, `related_skills`.

### Corrective RAG
검색 근거가 부실하면 계획에 없던 보정(재검색·쿼리 재작성)을 수행하는 패턴. gap_agent의 ReAct 루프가 이 보정 사이클입니다.

### ReAct 루프
Reasoning + Acting. LLM이 (1)추론 (2)도구 호출 (3)결과 관찰을 반복. `call_model ↔ tools` 왕복 구조. 무한 루프 방지를 위해 MAX_ITERATIONS 상한이 걸려 있습니다.

### Consensus (교차검증, 결정적)
resume/github/portfolio/deploy 평가자의 독립 결과를 **LLM 없이** 규칙 코드로 종합해 confidence 등급을 매깁니다. "근거가 일치하는가"는 규칙 비교로 충분히 신뢰성 있게 판정되고, 여기 LLM을 쓰면 판정 자체가 불확실해지므로 의도적으로 배제.

### Critic (환각 제거, 결정적)
gap_agent 리포트를 consensus의 사실 결과와 대조해, LLM이 지어낸 주장을 걸러내거나 confidence 라벨을 교정합니다. **"생성은 LLM, 검증은 결정적 코드"** 역할 분담이 이 아키텍처의 핵심 신뢰성 장치입니다.

### 4개 평가자 (modality별)
- `resume_eval` — 이력서 텍스트(text modality).
- `github_eval` — GitHub REST API(`api.github.com/repos/...`)로 README·매니페스트·파일을 fetch, `ThreadPoolExecutor(max_workers=8)`로 병렬 조회해 코드 근거 검증(code modality). `GITHUB_TOKEN` 있으면 Bearer 인증.
- `portfolio_eval` — PDF 멀티모달(text + Vision).
- `deploy_eval` — 배포 URL을 `httpx.get`으로 fetch해 작동 실증 + 프론트 기술 추출(web modality).

### Confidence 레벨 (high/medium/low)
포트폴리오가 기술을 "증명(DEMONSTRATES)"하는 정도의 신뢰도 등급. 이력서 명시=high, 문맥 추론=medium, 간접 언급=low, GitHub 코드 확인 시 한 단계 상승.

### HITL / interrupt
`langgraph.types.interrupt`로 그래프를 특정 지점에서 멈추고 사람 입력을 기다렸다 재개하는 설계. `ask_human` 툴로 확장 지점만 만들어두고 운영은 기본 자동 모드.

### 단어 경계 키워드 매칭 (`common/text_match.py`) — 벡터 검색의 대체물
벡터 검색을 제거한 뒤, 스킬 매칭은 정규식 **단어 경계 매칭**으로 합니다. `word_match()`는 `(?<![a-z0-9])keyword(?![a-z0-9])` 패턴으로 'react'가 'reaction'에, 'aws'가 'draws'에 오탐되지 않게 막습니다. `keywords_for()`는 정규화명이 같은 별칭들(예: React ← React.js, 리액트)까지 매칭 키워드로 확장합니다. 여러 평가자·툴·평가 모듈이 이 공통 모듈을 공유합니다.

---

## 6. 문서 처리

### pdfplumber
PDF 텍스트 레이어를 표·레이아웃 보존하며 추출. 이력서 파싱(`pdf_parser.py`)에 사용.

### PyMuPDF (fitz)
PDF 페이지를 이미지로 렌더링. `portfolio_eval.py`에서 이미지 페이지를 Vision에 넘기기 위해 사용. **CLAUDE.md 표엔 없지만 requirements·코드에 실재.**

---

## 7. 평가

### RAGAS (faithfulness + answer_relevancy)
갭 분석 리포트 품질을 두 지표로 측정합니다.
- **faithfulness** — 리포트의 각 주장이 공고 근거에 실제로 지지되는가(= 환각 탐지).
- **answer_relevancy** — 답변이 질문과 관련 있는가(임베딩 기반, 그래서 `text-embedding-3-small` 사용).

context_precision/recall은 쓰지 않습니다 — 갭 분석 특성상 faithfulness 중심이 적합하다는 판단.

### Langfuse 4.x (트레이싱)
LLM 호출을 추적. 두 가지 방식으로 연결됩니다.
- `@observe` 데코레이터(`langfuse_tracer.py`의 `trace`가 감쌈) — **키가 없으면 자동 no-op**이라 미설정 환경에서도 안전.
- LangChain `CallbackHandler` — LangGraph 노드 실행을 콜백으로 추적. `langfuse_callbacks()`가 키 있을 때만 핸들러를 반환.

RAGAS가 "품질이 얼마나 좋은가"라면 Langfuse는 "무슨 일이 일어났는가"를 기록합니다.

### 검색 파이프라인 실험 (RRF + CrossEncoder) — 과거 실험, 현재 코드엔 없음
`docs/retrieval-eval.md`에 RRF vs RRF+CrossEncoder 리랭킹을 LLM-as-judge로 비교한 기록이 있습니다(전체 평균 4.08→4.25). 채용공고의 "우대: Hybrid Search(BM25+dense)" 요건에 대응한 실험이었으나, 벡터 검색(Chroma) 자체의 기여가 미미하다고 측정되어(검색 12건 중 11건이 키워드 매칭과 동일) 제거되었습니다. 즉 리랭킹은 **측정 후 폐기된 실험**이고, 현재 운영 검색은 6장의 단어 경계 매칭 + Neo4j 그래프입니다.

---

## 8. 서빙 / API / 배포

### FastAPI + uvicorn
`uvicorn`(ASGI 서버)이 FastAPI 앱을 구동. Pydantic 스키마 검증 + OpenAPI 자동 문서. `python-multipart`로 PDF 업로드 폼을 파싱.

### 동기 에이전트를 async에 얹기 (`run_in_threadpool`)
LangGraph 에이전트는 동기 함수인데 FastAPI는 async입니다. `fastapi.concurrency.run_in_threadpool`로 동기 실행을 스레드풀에 넘겨 이벤트 루프를 막지 않습니다. `BackgroundTasks`로 무거운 분석을 백그라운드에서 처리.

### 메모리 누수 방지 (`BoundedDict`)
업로드된 PDF 텍스트와 진행 중 리포트를 in-memory에 보관하는데, 무한 증가를 막기 위해 `BoundedDict(_MAX_INFLIGHT)`(`deps.py`, `OrderedDict` 기반 상한 딕셔너리)로 오래된 항목을 자동 축출합니다.

### 데모 레이트 리밋 (`DEMO_DAILY_LIMIT`)
`_enforce_daily_limit()`이 비관리자 요청에 하루 분석 횟수 상한(기본 1회)을 적용. `_is_admin(access_key)`면 우회. 미들웨어가 아닌 라우터 내부 커스텀 로직입니다.

### 프론트엔드 (순수 HTML/JS, 프레임워크 없음)
`app.mount("/web", StaticFiles(...))`로 `web/index.html`(분석 UI)과 `web/observe.html`(그래프 구조 관측 페이지)을 서빙. React 등 프레임워크 없이 정적 HTML/JS입니다.

### Docker / 배포
- `Dockerfile`: `python:3.11-slim` 베이스, HF Spaces 기본 포트 `7860` 노출.
- `docker-compose.yml`: 로컬은 API(8000, `--reload`)와 `neo4j:5.24-community`를 함께 띄우고 healthcheck로 DB 준비를 대기.
- 배포: Hugging Face Spaces(무료, GPU 불필요, 데모 URL 공유).

---

## 9. 파인튜닝 (예정 단계, 미착수)

### Unsloth + QLoRA (개념만, 코드 없음)
LoRA는 거대 모델 전체 가중치 대신 작은 저랭크 행렬만 학습해 파인튜닝 비용을 줄이는 기법. QLoRA는 여기에 양자화(4비트 등 압축)를 더해 메모리를 더 절약. Unsloth는 이 학습을 빠르고 메모리 효율적으로 돌려 Colab 무료 T4에서도 실행 가능하게 함.

**확인:** requirements·코드 모두 없음 — CLAUDE.md "6단계 예정" 그대로 미착수.

---

## 10. 의도적으로 배제한 기술

| 기술 | 배제 이유 |
|---|---|
| LangChain Expression Language (LCEL) | LangGraph로 대체, 혼용 금지 |
| Chroma / 벡터 검색 | 검색 12건 중 11건이 키워드 매칭과 동일 → 효과 측정 후 제거, Neo4j 그래프로 통합 |
| pgvector | PostgreSQL 서버 필요 + 벡터 검색 자체 제거로 불필요 |
| Pinecone / Qdrant | 유료·설치 복잡, 벡터 검색 미사용 |
| vLLM | GPU 없음, API로 대체 |
| bare `langchain` 패키지 | 코드에서 직접 import하지 않아 제거(langchain-core/openai만 사용) |
| 직접 크롤링 (사람인·잡코리아) | 약관 위반 위험, API 기반 소스 사용 |

---

## 11. CLAUDE.md 문서 ↔ 실제 코드 불일치 (갱신 후보)

1. **데이터 소스** — CLAUDE.md는 Adzuna를 메인으로 기재하나, 파이프라인은 The Muse API로 전환됨. Adzuna는 `scripts/collect_raw.py`에만 잔존.
2. **PyMuPDF 누락** — 기술 스택 표에 pdfplumber만 있으나, 멀티모달 평가에 `pymupdf`(fitz)도 실사용.
3. **langchain-core / langchain-openai 누락** — 표엔 "LangGraph"만 있으나 이 두 패키지도 직접 의존(버전 고정 이유까지 requirements 주석에 존재).
4. **임베딩** — "벡터 검색 미사용"은 맞지만, `text-embedding-3-small`이 RAGAS `answer_relevancy` 계산에는 쓰임(검색 아님).
5. **프론트엔드** — 구조 문서에 `web/` 정적 프론트(index.html·observe.html) 언급 없음.

이 문서는 위 불일치를 반영한 "코드 실태 기준" 정리입니다. CLAUDE.md 자체를 이에 맞춰 갱신할지는 별도 결정 사항입니다.
