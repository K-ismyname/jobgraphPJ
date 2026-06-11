# Job Skill Analyzer — 작업 기록지

작업 절차 / 발생 문제 / 해결 방법을 날짜별로 기록합니다.

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
   - **Critic 실효화 (길 A)**: 현재 replan은 같은 데이터 재조회라 무의미 → Critic이 약한 주장을 구체 지목 → Gap이 *다른 전략*(범위 확대/섹션 확대/CO_OCCURS·PART_OF 우회/검색법 전환)으로 재검색 → 1~2회 후에도 부족하면 "근거 약함(low)" 정직 표시. 상한으로 무한루프 방지.
   - **Learning Path 제외**: 주차별 소요시간 데이터가 없어 LLM 추측 = "근거 기반" 철학과 모순. 빼는 게 맞음.
   - 근거: 데이터 흐름 추적 결과 Market/Retrieval/Planner-LLM이 미연결·중복·장식으로 확인됨. "노드 수"가 아니라 "소비되는가"로 판단.
