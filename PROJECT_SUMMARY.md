# Job Skill Analyzer — 프로젝트 현황 요약

> 새 대화 세션에서 컨텍스트 복원용으로 사용하는 문서입니다.
> 코드·설계 세부사항은 `CLAUDE.md`, 작업 이력은 `progress.md`를 참고하세요.

---

## 한 줄 정의

채용공고를 수집·분석하고, 이력서(PDF/텍스트/GitHub)를 받으면 직무 대비 부족 기술과 이력서 개선 방향을 알려주는 **Agentic RAG 시스템**.

---

## 현재 빌드 상태

| Layer | 내용 | 상태 |
|-------|------|------|
| Layer 1 | 데이터 수집 (The Muse, RemoteOK) | ✅ 완료 |
| Layer 2 | 전처리·스킬 추출·Neo4j/Chroma 적재 | ✅ 완료 |
| Layer 3 | LangGraph 에이전트 (단일 → 듀얼 에이전트) | ✅ 완료 |
| Layer 3.5 | 검색 고도화 (BM25+Dense+RRF+CrossEncoder) | ✅ 완료 |
| Layer 4 | 갭 분석·이력서 코치 | ✅ 완료 |
| Layer 5 | RAGAS + Langfuse 평가 | ✅ 완료 |
| Layer 6 | FastAPI + Docker + HF Spaces 배포 | ⬜ 미착수 |

**현재 진행 위치: Layer 6 진입 전, 에이전트 아키텍처 정리 완료 단계.**

---

## 수집 데이터 현황

### 원본 (`data/raw/`)
- The Muse API: `jobs_raw_muse.json`, `jobs_muse_dev.json`, `jobs_data_analytics.json`, `jobs_software_engineering.json`
- RemoteOK API: `jobs_remoteok.json`
- Adzuna API (초기 수집): `jobs_raw.json`

### 가공 데이터 (`data/processed/jobs_filtered.json`)
- **총 321개 공고** (443개 수집 → 직군 필터링)
- 소스: The Muse 192개 + RemoteOK 129개

#### job_family 분포
| 직군 | 공고 수 |
|------|---------|
| Software Engineer | 127 |
| Data Engineer | 35 |
| Data Analyst | 30 |
| Architect | 26 |
| Data Scientist | 26 |
| DevOps/SRE | 25 |
| AI/LLM Engineer | 20 |
| Security Engineer | 15 |
| ML Engineer | 11 |
| Frontend Engineer | 6 |

#### 공고 구조 (1건)
```json
{
  "id": "muse-20079477",
  "title": "Senior Data Scientist - Agentic AI",
  "company": "Walmart",
  "location": "San Leandro, CA",
  "salary_min": null, "salary_max": null,
  "source": "themuse",
  "job_family": "Data Scientist",
  "text_clean": "...",
  "required_section": "...",
  "preferred_section": "...",
  "bullet_section": "...",
  "skills": {
    "required": ["Python", "Statistics", ...],
    "preferred": ["PyTorch", "Spark", ...]
  }
}
```

### 벡터 DB (`data/chroma/`)
- 컬렉션: `job_sections` (dimension=1536, OpenAI text-embedding-3-small)
- **임베딩 416개** (required 269 + preferred 182 + bullet 164 + full_text 54)
- 각 청크 메타데이터: `source_id`, `job_title`, `company`, `section_type`, `original_text`
- Contextual Chunking 적용: LLM이 각 청크의 역할을 자연어로 설명한 document 포함
- 검색 파이프라인: BM25 + Dense (RRF 합산) → CrossEncoder 재정렬

### 그래프 DB (Neo4j Aura 무료 티어)
- JobPosting 321 / Skill 1,079 / Company 200 / JobFamily 10
- REQUIRES 2,025 / PREFERS 665 / CO_OCCURS 13,605 / INSTANCE_OF 321 / POSTED_BY 320

### 시드 데이터 (`data/seeds/skill_relations.json`)
- 15개 수동 정의 PART_OF 관계 (LangGraph→LangChain, QLoRA→LoRA 등)

---

## LLM 사용 현황

- **노드 추론**: OpenAI GPT-4o-mini (`ChatOpenAI`)
- **임베딩**: OpenAI `text-embedding-3-small`
- **스킬 추출**: GPT-4o-mini (ingestion 시 1회성)

> CLAUDE.md에는 Claude Haiku/Sonnet 사용 예정으로 적혀 있으나,
> 실제 구현은 OpenAI로 진행됨. 환경변수는 `OPENAI_API_KEY`.

---

## 현재 에이전트 아키텍처 (Flat Graph)

```
START → resume → [github_url?] ─Yes─→ github ─┐
                 └─No──────────────────────────┘
                                               ↓
                        call_model ↔ tools   (Gap Agent 루프, MAX=5)
                                               ↓
                                           generate
                                               ↓
                       [match_rate ≥ 80%?] ──Yes──→ END
                              ↓ No
               coach_call_model ↔ coach_tools  (Coach Agent 루프, MAX=3)
                              ↓
                        finalize_coach → END
```

### AppState 주요 필드
```python
job_family: str          # 분석 직군
owner: str               # 지원자 이름
pdf_path: str | None     # PDF 이력서 경로
github_url: str | None   # GitHub 프로필 URL
resume_skills: list[str] # 보유 스킬 직접 주입 (RAGAS eval용)
resume_text: str | None  # PDF 파싱 결과 저장용 (출력)
messages: ...            # Gap 루프 히스토리 (add_messages)
coach_messages: ...      # Coach 루프 히스토리 (별도 분리)
gap_result: dict | None
github_result: dict | None
final_report: dict | None
```

### 에이전트별 역할
| 에이전트 | 노드 | 툴 | 루프 상한 |
|---------|------|-----|---------|
| Gap Agent | call_model ↔ tools | gap_analysis, verify_skills, vector_search, skill_unlock, posting_trend, market_insights, graph_query, ask_human | MAX_ITERATIONS=5 |
| Coach Agent | coach_call_model ↔ coach_tools | verify_suggestion | COACH_MAX_ITERATIONS=3 |

### 핵심 설계 결정
1. **GitHub-first 라우팅**: GitHub이 Gap 분석 전 실행 → Neo4j confidence 업데이트 후 gap_analysis가 최신 값 조회
2. **confidence 3단 분류**: high/medium → `have_required`, low → `unverified_required`, 없음 → `missing_required`
3. **메시지 히스토리 분리**: `messages`(Gap)와 `coach_messages`(Coach)를 독립 필드로 관리
4. **Supervisor 판단**: match_rate ≥ 80% → Coach 건너뛰고 END
5. **dedup**: `seen_source_ids`로 동일 공고 중복 인용 방지

---

## 사용자 입력 현황

현재 지원하는 입력 조합:

| 입력 | 필드 | 상태 |
|------|------|------|
| PDF 이력서 | `pdf_path` | ✅ 지원 |
| GitHub URL | `github_url` | ✅ 지원 (선택) |
| 스킬 목록 직접 주입 | `resume_skills` | ✅ RAGAS eval용 |
| 이력서 텍스트 직접 입력 | — | ❌ 미지원 (추가 예정) |

> `resume_text` 필드는 현재 PDF 파싱 **출력용**으로만 사용됨.
> 사용자가 텍스트를 직접 붙여넣기 할 수 있는 **입력 경로** 추가 필요.

---

## 주요 파일 목록

```
src/
  agent/
    state.py          — AppState TypedDict (단일 공유 상태)
    nodes.py          — Gap/Coach 노드 팩토리 (call_model, generate_report, coach_call_model, finalize_coach)
    tools.py          — Gap 툴 8개 + Coach 툴 1개 (verify_suggestion)
    supervisor.py     — 단일 평면 StateGraph 조립 + 라우팅 함수
    resume_agent.py   — PDF 파싱 → 스킬 추출 → Neo4j 저장
    github_agent.py   — GitHub API → confidence 업데이트
  ingestion/
    pipeline.py       — 수집 → 전처리 → 스킬 추출 → 저장 전체 파이프라인
    preprocessor.py   — 섹션 분리 (required/preferred/bullet), RemoteOK 노이즈 제거
    adzuna_client.py  — Adzuna API 클라이언트
    remoteok_client.py — RemoteOK API 클라이언트
  extraction/
    skill_extractor.py — LLM 기반 스킬 추출 (required/preferred 리스트 반환)
    normalizer.py      — 동의어 통합 (React.js → React 등)
  storage/
    neo4j_client.py   — Neo4j MERGE 쿼리 모음
    chroma_client.py  — BM25+Dense+RRF+CrossEncoder 하이브리드 검색
  evaluation/
    ragas_eval.py     — RAGAS Answer Relevancy 평가
    langfuse_tracer.py — Langfuse 트레이싱 데코레이터
```

---

## 다음 작업 (우선순위 순)

1. **resume_text 입력 경로 추가** — resume_node에 텍스트 직접 입력 경로 추가
2. **Layer 6: FastAPI** — `POST /analyze` SSE 스트리밍 엔드포인트
3. **Docker Compose** — Neo4j(로컬 테스트용) + API 서버
4. **HF Spaces 배포** — 데모 URL 공유
5. **멀티 에이전트 고도화** — 현재는 순차 듀얼 에이전트. Option B(LangGraph `Send()` 병렬) 또는 Option A(LLM Supervisor) 검토 중

---

## 평가 결과 (참고)

- **RAGAS Answer Relevancy**: 0.44–0.48
- **RAGAS Faithfulness**: 0.000–0.293 (구조적 한계 — 갭 추론은 컨텍스트 직접 명시가 아닌 비교에서 나옴)
- 자세한 내용: `docs/retrieval-eval.md`

---

## 환경변수 체크리스트

```bash
OPENAI_API_KEY=        # 필수 (LLM + 임베딩)
NEO4J_URI=             # 필수 (neo4j+s://xxxx.databases.neo4j.io)
NEO4J_USER=neo4j
NEO4J_PASSWORD=
GITHUB_TOKEN=          # 선택 (github_agent 사용 시)
LANGFUSE_PUBLIC_KEY=   # 선택 (트레이싱)
LANGFUSE_SECRET_KEY=
```

> CLAUDE.md의 `ANTHROPIC_API_KEY`는 현재 미사용. 실제 코드는 `OPENAI_API_KEY`로 동작.
