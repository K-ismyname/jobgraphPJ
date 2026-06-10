# Multi-Agent LangGraph 구현 계획

## 현재 상태 요약

- **Layer 1·2 완료**: 321개 채용공고(The Muse + RemoteOK) → Neo4j(JobFamily 노드, CO_OCCURS 관계) + Chroma(669 문서) 적재 완료
- **Layer 3 부분 완료**: 단일 에이전트(`call_model → tools → generate`) 동작 확인
  - 사용 가능 툴: `gap_analysis`, `verify_skills`, `vector_search`, `skill_unlock`, `market_insights`, `graph_query`, `ask_human`
  - **미연결 모듈**: `pdf_parser.py`, `github_connector.py`, `coach.py` — 단독 함수로 존재하나 에이전트에 연결되지 않음
- **미완료**: Layer 4(Coach), Layer 5(평가), Layer 6(API 서빙)

---

## 목표: 3가지 핵심 기능을 Multi-Agent로 구현

| # | 기능 | 담당 에이전트 |
|---|------|--------------|
| 1 | PDF 이력서 업로드 → 스킬 추출 → Neo4j 저장 | **Resume Agent** |
| 2 | 직군 대비 갭 분석 + 매칭률 + 이력서 개선 제안 | **Gap Agent** + **Coach Agent** |
| 3 | GitHub 선택 연동 → confidence 레벨 상승 | **GitHub Agent** |

---

## 전체 아키텍처

```
사용자 입력 (job_family, owner, pdf_path, github_url?)
        │
        ▼
  ┌─────────────────────────────────────────────┐
  │           Supervisor (오케스트레이터)         │
  └───┬─────────────────────────────────────────┘
      │ route: "resume"
      ▼
  ┌──────────────┐
  │ Resume Agent │  PDF → 스킬 추출 → Neo4j PortfolioItem 저장
  └──────┬───────┘
         │ 완료 시 → "parallel_analysis"로 라우팅
         ▼
  ┌──────────────────────────────────────┐
  │   Send() 팬아웃 (병렬 실행)           │
  │  ┌─────────────┐  ┌───────────────┐ │
  │  │  Gap Agent  │  │ GitHub Agent  │ │
  │  │ (갭 분석)   │  │ (confidence↑) │ │
  │  └──────┬──────┘  └───────┬───────┘ │
  └─────────┼─────────────────┼─────────┘
            │ 둘 다 완료 시     │
            └────────┬─────────┘
                     ▼
              ┌─────────────┐
              │ Coach Agent │  갭 결과 → 이력서 개선 제안
              └──────┬──────┘
                     ▼
                   END (최종 리포트)
```

**패턴 선택 이유:**
- `Send()` API: Gap + GitHub는 독립적으로 실행 가능하므로 병렬 팬아웃으로 wall-clock time 단축
- Supervisor 라우팅: 각 에이전트가 앞 에이전트 결과를 받아야 하므로 단순 순차 그래프보다 명확
- 서브그래프 사용 안 함: 오버엔지니어링 방지 — 노드 함수로 충분

---

## 새로운 공유 State

**파일: `src/agent/state.py` 수정**

```python
class AppState(TypedDict):
    # ── 입력 ──────────────────────────────────────────────────────
    job_family: str          # "AI/LLM Engineer" 등 10개 직군 중 하나
    owner: str               # 지원자 이름 (Neo4j PortfolioItem owner)
    pdf_path: str | None     # PDF 이력서 경로
    github_url: str | None   # GitHub 프로필 URL (선택)

    # ── Resume Agent 결과 ──────────────────────────────────────────
    resume_skills: list[str]       # 추출된 스킬명 목록
    resume_text: str | None        # PDF 원문 (Coach Agent에서 재활용)

    # ── Gap Agent 결과 ──────────────────────────────────────────────
    gap_result: dict | None        # tools.gap_analysis() 반환값

    # ── GitHub Agent 결과 ──────────────────────────────────────────
    github_result: dict | None     # {"changed": {...}, "skipped": bool}

    # ── Coach Agent 결과 ──────────────────────────────────────────
    coaching_result: dict | None   # CoachingResult 직렬화

    # ── 최종 리포트 ───────────────────────────────────────────────
    final_report: dict | None

    # ── 내부 제어 (기존 단일 에이전트에서 유지) ─────────────────
    messages: Annotated[list[BaseMessage], add_messages]
    iteration: int
    seen_source_ids: list[str]
```

**기존 `AgentState`와 차이:**
- `job_title` → `job_family` (JobFamily 노드 기반으로 통일)
- `resume_skills`, `resume_text`, `gap_result`, `github_result`, `coaching_result` 추가

---

## Phase 1: Resume Agent 구현

**파일**: `src/agent/resume_agent.py` (신규)

**역할**: PDF 텍스트 추출 → LLM 스킬 추출 → Neo4j에 PortfolioItem으로 저장

```python
# src/agent/resume_agent.py
# PDF 이력서에서 스킬을 추출하고 Neo4j에 저장하는 Resume Agent 노드

from src.portfolio.pdf_parser import extract_pdf_text
from src.extraction.skill_extractor import extract_skills_from_resume
from src.storage.neo4j_client import Neo4jClient
from openai import OpenAI

def create_resume_node(neo4j: Neo4jClient, openai_client: OpenAI):
    def resume_node(state: AppState) -> dict:
        pdf_path = state.get("pdf_path")
        if not pdf_path:
            # PDF 없으면 이미 Neo4j에 저장된 PortfolioItem 사용
            existing = neo4j.get_portfolio_skills(state["owner"])
            return {"resume_skills": existing, "resume_text": None}

        # Step 1: PDF 텍스트 추출
        text = extract_pdf_text(pdf_path)

        # Step 2: LLM 스킬 추출 (skill_extractor.extract_skills_from_resume)
        # ResumeExtraction 반환: {name, confidence, evidence, section}
        result = extract_skills_from_resume(text, openai_client)

        # Step 3: Neo4j PortfolioItem으로 저장 (neo4j.save_portfolio)
        portfolio_data = {
            "owner": state["owner"],
            "title": f"{state['owner']} 이력서",
            "skills": result.skills,   # list[DemonstratedSkill]
        }
        neo4j.save_portfolio(portfolio_data)

        skill_names = [s.name for s in result.skills]
        return {"resume_skills": skill_names, "resume_text": text}

    return resume_node
```

**연결되는 기존 함수:**
- `src/portfolio/pdf_parser.py::extract_pdf_text()` — 이미 완성
- `src/extraction/skill_extractor.py::extract_skills_from_resume()` — 이미 완성
- `src/storage/neo4j_client.py::save_portfolio()` — 이미 완성

**수정 불필요**: 세 함수 모두 완성 상태, Resume Agent는 이를 연결하는 노드만 작성하면 됨.

---

## Phase 2: Gap Agent 리팩토링

**파일**: `src/agent/gap_agent.py` (신규) + `src/agent/nodes.py` (수정)

**현재 문제**: 기존 `call_model → tools → generate` 단일 에이전트가 Gap 분석을 담당했으나, 입력이 `job_title` + `portfolio_skills`를 따로 받는 구조. 이제 `AppState`에서 `job_family`와 `resume_skills`를 받아야 함.

**변경 방향**:
- 기존 `nodes.py`의 `call_model`과 `generate_report` 재활용
- `gap_agent.py`는 `AppState`에서 `job_family`와 `resume_skills`를 꺼내 기존 에이전트에 초기 메시지로 전달하는 래퍼

```python
# src/agent/gap_agent.py
# Gap Agent — 기존 단일 에이전트 로직을 AppState와 연결하는 래퍼

def create_gap_node(tools, neo4j, chroma):
    call_model, generate_report = create_nodes(tools, neo4j, chroma)

    def gap_node(state: AppState) -> dict:
        # AppState에서 필요한 값 추출
        job_family = state["job_family"]
        owner = state["owner"]
        skills = state.get("resume_skills") or []

        skills_str = ", ".join(skills) if skills else "없음 (Neo4j PortfolioItem 사용)"
        user_msg = (
            f"직군 '{job_family}'에 대해 갭 분석을 해주세요.\n"
            f"지원자: {owner}\n"
            f"보유 스킬: {skills_str}"
        )

        # 기존 에이전트와 같은 방식으로 실행
        inner_state = {
            "job_title": job_family,   # nodes.py _SYSTEM_PROMPT에서 job_title로 참조
            "owner": owner,
            "messages": [{"role": "user", "content": user_msg}],
            "iteration": 0,
            "seen_source_ids": [],
            "final_report": None,
        }
        # ... 기존 루프 실행 ...
        return {"gap_result": inner_result.get("final_report")}

    return gap_node
```

**실제 구현 방법**: 기존 `graph.py::create_graph()`를 서브그래프로 컴파일하거나, `run_analysis()` 함수를 그대로 호출해 결과를 `AppState`에 저장.

**권장**: `run_analysis()` 직접 호출 — 단순하고 기존 코드 재사용

```python
def gap_node(state: AppState) -> dict:
    from src.agent.graph import run_analysis
    result = run_analysis(
        gap_graph,           # 기존 create_graph()로 만든 그래프
        job_title=state["job_family"],
        owner=state["owner"],
        portfolio_skills=state.get("resume_skills"),
    )
    return {"gap_result": result}
```

---

## Phase 3: GitHub Agent 구현

**파일**: `src/agent/github_agent.py` (신규)

**역할**: GitHub API 호출 → PortfolioItem confidence 레벨 업그레이드 → Neo4j 반영

```python
# src/agent/github_agent.py
# GitHub 리포 메타데이터로 이력서 스킬 confidence를 검증·상승시키는 노드

from src.portfolio.github_connector import boost_confidence_from_github, parse_github_username
from src.storage.neo4j_client import Neo4jClient

def create_github_node(neo4j: Neo4jClient):
    def github_node(state: AppState) -> dict:
        github_url = state.get("github_url")
        if not github_url:
            return {"github_result": {"skipped": True, "reason": "GitHub URL 미제공"}}

        try:
            username = parse_github_username(github_url)
        except ValueError as e:
            return {"github_result": {"skipped": True, "reason": str(e)}}

        # Neo4j에서 현재 PortfolioItem 스킬 조회
        current_skills = neo4j.get_portfolio_demonstrated_skills(state["owner"])
        # DemonstratedSkill 리스트로 변환 후 confidence boost
        updated, changes = boost_confidence_from_github(current_skills, username)

        # 변경된 스킬을 Neo4j에 반영 (DEMONSTRATES 관계 confidence 업데이트)
        if changes:
            neo4j.update_portfolio_confidence(state["owner"], changes)

        return {"github_result": {"changed": changes, "skipped": False}}

    return github_node
```

**필요한 Neo4j 메서드 추가**: `neo4j_client.py`에 아래 2개 추가 필요
- `get_portfolio_demonstrated_skills(owner)` → `list[DemonstratedSkill]`
- `update_portfolio_confidence(owner, changes)` → confidence 업데이트 Cypher 실행

---

## Phase 4: Coach Agent 구현

**파일**: `src/agent/coach_agent.py` (신규)

**역할**: Gap Agent 결과 + 이력서 원문 → LLM 이력서 개선 제안 생성

**기존 `coach.py`와의 관계**: `coach.py`의 `generate_coaching()` 함수를 그대로 호출하되, 입력을 `AppState`에서 꺼냄. `GapAnalysisResult` 타입을 요구하는 부분만 변환 필요.

```python
# src/agent/coach_agent.py
# Gap 분석 결과를 바탕으로 이력서 개선 제안을 생성하는 Coach Agent 노드

from src.analysis.coach import generate_coaching
from src.analysis.gap_analyzer import GapAnalysisResult, SkillGap

def create_coach_node(chroma, openai_client):
    def coach_node(state: AppState) -> dict:
        gap_raw = state.get("gap_result") or {}

        # gap_result(dict)를 GapAnalysisResult(Pydantic)로 변환
        # gap_result의 키는 gap_analysis 툴 반환 + generate_report 조합
        gap_result = _dict_to_gap_result(gap_raw, state["job_family"], state["owner"])

        result = generate_coaching(gap_result, chroma, openai_client)

        return {
            "coaching_result": result.model_dump(),
            "final_report": {
                "gap": gap_raw,
                "coaching": result.model_dump(),
                "github": state.get("github_result"),
            }
        }

    return coach_node
```

**`_dict_to_gap_result()` 변환 함수**: `generate_report` 노드가 반환하는 dict 구조:
```json
{
  "job_title": "AI/LLM Engineer",
  "match_rate": 0.45,
  "have_required": ["Python", "LangGraph"],
  "missing_required": [{"skill": "RAG", "weight": 12, ...}],
  ...
}
```
→ `GapAnalysisResult`로 변환할 때 `SkillGap.job_demand = weight`로 매핑.

---

## Phase 5: Supervisor 그래프 조립

**파일**: `src/agent/supervisor.py` (신규)

```python
# src/agent/supervisor.py
# Supervisor 오케스트레이터 — 에이전트 라우팅 및 병렬 팬아웃

from langgraph.graph import StateGraph, START, END
from langgraph.types import Send

def create_supervisor_graph(neo4j, chroma, openai_client):
    resume_node = create_resume_node(neo4j, openai_client)
    gap_graph   = create_graph(neo4j, chroma)   # 기존 에이전트 그래프
    github_node = create_github_node(neo4j)
    coach_node  = create_coach_node(chroma, openai_client)

    def gap_node(state):
        result = run_analysis(gap_graph, state["job_family"], state["owner"],
                              portfolio_skills=state.get("resume_skills"))
        return {"gap_result": result}

    # ── 라우팅 함수 ───────────────────────────────────────────────
    def route_after_resume(state: AppState) -> list[Send]:
        sends = [Send("gap_agent", state)]
        if state.get("github_url"):
            sends.append(Send("github_agent", state))
        return sends

    def route_after_parallel(state: AppState) -> str:
        # gap_result가 채워졌으면 coach로
        return "coach_agent" if state.get("gap_result") else END

    # ── 그래프 조립 ───────────────────────────────────────────────
    workflow = StateGraph(AppState)
    workflow.add_node("resume_agent", resume_node)
    workflow.add_node("gap_agent",    gap_node)
    workflow.add_node("github_agent", github_node)
    workflow.add_node("coach_agent",  coach_node)

    workflow.add_edge(START, "resume_agent")
    workflow.add_conditional_edges("resume_agent", route_after_resume,
                                   ["gap_agent", "github_agent"])
    # gap + github 둘 다 완료되면 coach로 (barrier)
    workflow.add_conditional_edges("gap_agent",    route_after_parallel)
    workflow.add_conditional_edges("github_agent", route_after_parallel)
    workflow.add_edge("coach_agent", END)

    return workflow.compile(checkpointer=MemorySaver())
```

**주의**: `Send()` 팬아웃 후 barrier는 LangGraph가 자동 처리 — 두 Send 대상이 모두 END/다음 노드에 도달해야 route 함수가 실행됨.

---

## 수정해야 할 기존 파일들

### `src/analysis/gap_analyzer.py`

현재 `GAP_QUERY`가 substring 매칭을 사용:
```cypher
WHERE toLower(jp.title) CONTAINS toLower($job_title)
```

→ JobFamily 노드 기반으로 교체 필요:
```cypher
MATCH (:JobFamily {name: $job_family})<-[:INSTANCE_OF]-(jp:JobPosting)
-[:REQUIRES]->(required:Skill)
```

함수 시그니처도 변경: `job_title: str` → `job_family: str`

### `src/analysis/coach.py`

`chroma.search_evidence()` 호출 — `ChromaClient`에 해당 메서드 없으면 `chroma.search()` 로 교체:
```python
# Before
snippets = chroma.search_evidence(skill_gap.skill, n=1)
# After
results = chroma.search(skill_gap.skill, n_results=1, section_type="required")
snippets = [r["original_text"] for r in results]
```

### `src/storage/neo4j_client.py`

Phase 3 GitHub Agent에서 필요한 메서드 추가:
```python
def get_portfolio_demonstrated_skills(self, owner: str) -> list[DemonstratedSkill]:
    """Neo4j PortfolioItem → DemonstratedSkill 목록 반환."""

def update_portfolio_confidence(self, owner: str, changes: dict[str, str]) -> None:
    """confidence 레벨 업데이트 — {"LangChain": "medium → high"}."""
```

---

## 구현 순서

```
Phase 1: Resume Agent
  1. src/agent/resume_agent.py 작성
  2. AppState로 state.py 확장
  3. 단독 실행 테스트: python -m src.agent.resume_agent

Phase 2: gap_analyzer.py JobFamily 쿼리로 교체
  1. GAP_QUERY 수정
  2. run_gap_analysis() 시그니처 변경
  3. coach.py search_evidence() → search() 교체
  4. 테스트: pytest tests/unit/test_gap_analyzer.py

Phase 3: GitHub Agent
  1. neo4j_client.py에 메서드 2개 추가
  2. src/agent/github_agent.py 작성
  3. 단독 실행 테스트

Phase 4: Coach Agent
  1. src/agent/coach_agent.py 작성
  2. _dict_to_gap_result() 변환 함수 구현
  3. 단독 실행 테스트

Phase 5: Supervisor 조립
  1. src/agent/supervisor.py 작성
  2. 전체 플로우 통합 테스트
  3. tests/integration/test_agent.py 작성
```

---

## 검증 기준

| 단계 | 검증 방법 |
|------|-----------|
| Resume Agent | `sample_resume.pdf` 파싱 → Neo4j에 PortfolioItem 노드 생성 확인 |
| Gap Agent | job_family="AI/LLM Engineer" → match_rate 반환 확인 |
| GitHub Agent | github_url 제공 시 DEMONSTRATES.confidence 한 단계 상승 확인 |
| Coach Agent | gap_result → ResumeSuggestion 목록 반환 확인 |
| Supervisor | PDF + job_family → final_report에 gap+coaching+github 모두 포함 확인 |

---

## 향후 연결 (Layer 5·6)

- **Langfuse 트레이싱**: 각 에이전트 노드를 `langfuse_tracer.py`의 `@trace` 데코레이터로 래핑
- **RAGAS 평가**: `gap_result`의 근거 텍스트를 faithfulness/answer_relevancy 지표로 측정
- **FastAPI**: `POST /analyze` 엔드포인트 → `supervisor.py::run_supervisor()` 호출
- **파인튜닝**: 현재 gpt-4o-mini → 갭 분석에 특화된 Claude fine-tuned 모델로 교체 가능
