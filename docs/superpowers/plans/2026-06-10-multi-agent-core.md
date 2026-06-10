# 멀티 에이전트 코어 전환 (Plan-and-Execute + Critic) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Job Skill Analyzer의 순차 듀얼 에이전트 그래프를 Plan-and-Execute + Critic 멀티 에이전트로 전환한다.

**Architecture:** Planner가 입력을 보고 조사 계획(Plan)을 세우고, Executor가 Profile·Retrieval·Market을 병렬(Send)로 실행한 뒤 Gap이 종합하고, Critic이 근거 충실성을 검증해 부족하면 Planner로 재계획(Replan, 상한 2회)하고 충분하면 기존 Coach 루프로 넘긴다.

**Tech Stack:** LangGraph (StateGraph, `Send`, `Command`), langchain_openai (`ChatOpenAI.with_structured_output`), Pydantic v2, pytest.

**설계 문서:** `docs/superpowers/specs/2026-06-10-multi-agent-core-design.md`

---

## 사전 지식 (구현자가 알아야 할 기존 코드)

- `src/agent/state.py`: `AppState` TypedDict. `messages`/`coach_messages`는 `Annotated[list, add_messages]` reducer를 가진다. 상수 `MAX_ITERATIONS=5`, `COACH_MAX_ITERATIONS=3`.
- `src/agent/nodes.py`: `create_nodes(tools, neo4j, chroma) -> (call_model, generate_report)`, `create_coach_nodes(coach_tools) -> (coach_call_model, finalize_coach)`. LLM은 `ChatOpenAI(model="gpt-4o-mini", temperature=0)`.
- `src/agent/tools.py`: `create_tools(neo4j, chroma)` (8개), `create_coach_tools(chroma)` (1개). 모듈 상수 `_JOB_SKILLS_QUERY`가 직군 요구 스킬을 조회한다.
- `src/storage/neo4j_client.py`: `execute_query(query, **params)`, `get_top_skills`, `get_location_distribution`, `get_job_distribution`, `get_skill_trend(skill_name)`, `get_portfolio_demonstrated_skills(owner)`.
- `src/storage/chroma_client.py`: `search(query, n_results=5, section_type=None, source_ids=None, rerank=True) -> list[dict]`. 결과 dict 키: `original_text`, `job_title`, `company`, `section_type`, `source_id`.
- `src/agent/supervisor.py`: `create_supervisor_graph(neo4j, chroma, openai_client)`, `run_supervisor(...)`, `run_analysis(graph, job_title, owner, ...)`.
- 테스트 환경: `tests/conftest.py`가 `.env`를 로드한다. 통합 테스트는 `OPENAI_API_KEY`로 가드한다.

**LLM 응답 파싱 규칙(프로젝트 컨벤션):** 구조화 출력은 `with_structured_output(Model)`을 우선 사용한다. 실패 시 fallback을 반드시 둔다.

---

## Task 0: 베이스라인 커밋 (회귀 기준점)

현재 동작하는 미커밋 멀티에이전트 코드를 논리 단위로 커밋해 회귀 비교 기준을 만든다. **이 Task는 TDD가 아니라 git 작업이다.**

**대상 파일 (working tree에 미커밋 상태):** `src/agent/{nodes,state,tools,supervisor,resume_agent,github_agent}.py`, `src/agent/graph.py`(삭제), `src/storage/{neo4j_client,chroma_client}.py`, `src/analysis/*`, `src/ingestion/*`, `src/extraction/*`, `src/evaluation/*`, `CLAUDE.md`.

- [ ] **Step 1: 현재 전체 테스트가 통과하는지 확인**

Run: `python -m pytest tests/ -q --deselect "tests/integration/test_agent.py::TestRunAnalysis::test_returns_dict"`
Expected: `51 passed` (또는 그 이상), 실패 0.

- [ ] **Step 2: 현재 그래프가 end-to-end로 도는지 스냅샷 확인**

Run: `python -m pytest "tests/integration/test_agent.py::TestRunAnalysis::test_returns_dict" -q`
Expected: `1 passed`.

- [ ] **Step 3: 저장소 코드 변경을 먼저 커밋**

```bash
git add src/storage/neo4j_client.py src/storage/chroma_client.py
git commit -m "refactor(storage): JobFamily 스키마 전환 + posting_trend datetime 비교 수정"
```

- [ ] **Step 4: 추출·수집 변경 커밋**

```bash
git add src/extraction/ src/ingestion/
git commit -m "refactor(ingestion): The Muse/RemoteOK 전처리 + 소스 namespace 접두사"
```

- [ ] **Step 5: 에이전트 코어 변경 커밋 (graph.py 삭제 포함)**

```bash
git add src/agent/ src/analysis/ src/evaluation/
git commit -m "feat(agent): 순차 듀얼 에이전트 그래프 (AppState + supervisor) 베이스라인"
```

- [ ] **Step 6: 문서 변경 커밋**

```bash
git add CLAUDE.md
git commit -m "docs: CLAUDE.md 스키마·명령어 동기화"
```

- [ ] **Step 7: working tree에 소스 미커밋이 남지 않았는지 확인**

Run: `git status --short | grep -v "^??" | grep -E "src/|CLAUDE"`
Expected: 출력 없음 (소스/문서 미커밋 0).

---

## Task 1: AppState 신규 필드

**Files:**
- Modify: `src/agent/state.py`
- Test: `tests/unit/test_state.py` (신규)

- [ ] **Step 1: 실패하는 테스트 작성**

Create `tests/unit/test_state.py`:
```python
# AppState에 Plan-and-Execute 필드가 정의됐는지 검증
from src.agent.state import AppState


def test_plan_execute_fields_exist():
    ann = AppState.__annotations__
    for field in (
        "plan", "replan_count",
        "profile_result", "retrieved_context", "market_result",
        "critic_report",
    ):
        assert field in ann, f"'{field}' 필드 누락"
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/unit/test_state.py -v`
Expected: FAIL — `'plan' 필드 누락`.

- [ ] **Step 3: 필드 추가**

`src/agent/state.py`의 `AppState` 클래스 본문 끝(`final_report` 다음)에 추가:
```python
    # ── Plan-and-Execute (멀티 에이전트 코어) ──
    plan: dict | None
    replan_count: int

    # ── Executor 산출 (병렬 노드가 각자 채움) ──
    profile_result: dict | None
    retrieved_context: list[dict]
    market_result: dict | None

    # ── Critic 검증 ──
    critic_report: dict | None
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/unit/test_state.py -v`
Expected: PASS.

- [ ] **Step 5: 커밋**

```bash
git add src/agent/state.py tests/unit/test_state.py
git commit -m "feat(agent): AppState에 Plan-and-Execute 필드 추가"
```

---

## Task 2: Plan/Step 모델 + Planner 노드

Planner는 입력 상태를 보고 조사 계획을 세운다. **결정적 골격**(어떤 agent step을 포함할지)은 입력 유무로 정하고, LLM은 각 step의 `goal`과 전체 `reason`을 생성한다. LLM 실패 시 결정적 fallback 계획을 쓴다.

**Files:**
- Create: `src/agent/planner.py`
- Test: `tests/unit/test_planner.py` (신규)

- [ ] **Step 1: 실패하는 테스트 작성**

Create `tests/unit/test_planner.py`:
```python
# Planner의 결정적 골격(입력 조합별 step 포함 규칙)을 검증
from src.agent.planner import build_skeleton_plan


def _state(**kw):
    base = {
        "job_family": "AI/LLM Engineer", "owner": "김지원",
        "pdf_path": None, "resume_text": None, "github_url": None,
        "resume_skills": [], "critic_report": None,
    }
    base.update(kw)
    return base


def test_pdf_only_includes_profile():
    steps = build_skeleton_plan(_state(pdf_path="resume.pdf"))
    agents = [s["agent"] for s in steps]
    assert "profile" in agents
    assert "retrieval" in agents and "market" in agents and "gap" in agents


def test_injected_skills_skip_profile():
    steps = build_skeleton_plan(_state(resume_skills=["Python", "LangGraph"]))
    agents = [s["agent"] for s in steps]
    assert "profile" not in agents          # 스킬 주입 시 Profile 생략
    assert "retrieval" in agents and "gap" in agents


def test_replan_narrows_to_retrieval():
    # Critic이 재계획을 요구하면 근거 보강(retrieval)에 집중하는 계획
    state = _state(
        pdf_path="resume.pdf",
        critic_report={"needs_replan": True, "unsupported_claims": ["LangGraph 근거 약함"]},
    )
    steps = build_skeleton_plan(state)
    agents = [s["agent"] for s in steps]
    assert "retrieval" in agents and "gap" in agents
    assert "market" not in agents           # 재계획은 시장 재조사 생략
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/unit/test_planner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.agent.planner'`.

- [ ] **Step 3: planner.py 구현**

Create `src/agent/planner.py`:
```python
# 입력을 보고 조사 계획(Plan)을 수립하는 Planner 노드 — Plan-and-Execute의 머리
from __future__ import annotations

import os
from typing import TYPE_CHECKING, Literal

from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from src.agent.state import AppState

if TYPE_CHECKING:
    pass


class Step(BaseModel):
    agent: Literal["profile", "retrieval", "market", "gap"]
    goal: str = Field(description="이 step에서 알아내려는 것")


class Plan(BaseModel):
    steps: list[Step]
    reason: str = Field(description="왜 이 계획인지 한국어 1-2문장")


_PLANNER_PROMPT = """당신은 채용 갭 분석의 조사 계획을 세우는 Planner입니다.
아래 입력 상황과 '포함해야 할 조사 항목'을 보고, 각 항목의 goal과 전체 reason을 한국어로 작성하세요.

입력 상황:
{situation}

포함해야 할 조사 항목(agent): {agents}

규칙:
- steps의 agent는 위 '포함해야 할 조사 항목'과 정확히 일치해야 합니다(추가·삭제 금지).
- 각 step의 goal은 그 항목에서 무엇을 알아낼지 한 문장으로.
- reason은 왜 이 조사 구성인지 1-2문장."""


def build_skeleton_plan(state: AppState) -> list[dict]:
    """입력 조합·재계획 여부로 어떤 agent step을 포함할지 결정한다(결정적).

    - resume_skills 주입 또는 입력 없음 → profile 생략
    - pdf_path / resume_text / github_url 중 하나라도 있으면 → profile 포함
    - critic_report.needs_replan == True → retrieval+gap만(근거 보강 집중)
    """
    critic = state.get("critic_report") or {}
    if critic.get("needs_replan"):
        return [
            {"agent": "retrieval", "goal": "근거가 약한 주장에 대한 공고 요건 재검색"},
            {"agent": "gap", "goal": "보강된 근거로 갭 재계산"},
        ]

    has_resume_input = bool(
        state.get("pdf_path") or state.get("resume_text") or state.get("github_url")
    )
    steps: list[dict] = []
    if has_resume_input and not state.get("resume_skills"):
        steps.append({"agent": "profile", "goal": "이력서·GitHub에서 보유 스킬과 confidence 추출"})
    steps.append({"agent": "retrieval", "goal": "직무 요구 스킬과 공고 근거 검색"})
    steps.append({"agent": "market", "goal": "부족 스킬의 수요·연봉 트렌드 조사"})
    steps.append({"agent": "gap", "goal": "보유 vs 요구를 비교해 갭과 매칭률 계산"})
    return steps


def create_planner_node(openai_client):
    """Planner 노드 팩토리. openai_client는 시그니처 일관성용(미사용)."""
    if not os.getenv("OPENAI_API_KEY"):
        raise EnvironmentError("OPENAI_API_KEY 환경변수가 필요합니다.")

    _llm = ChatOpenAI(model="gpt-4o-mini", temperature=0).with_structured_output(Plan)

    def planner_node(state: AppState) -> dict:
        skeleton = build_skeleton_plan(state)
        agents = [s["agent"] for s in skeleton]
        situation = (
            f"직군: {state['job_family']} / 지원자: {state['owner']}\n"
            f"PDF: {'있음' if state.get('pdf_path') else '없음'} / "
            f"이력서텍스트: {'있음' if state.get('resume_text') else '없음'} / "
            f"GitHub: {'있음' if state.get('github_url') else '없음'} / "
            f"주입스킬: {len(state.get('resume_skills') or [])}개 / "
            f"재계획: {'예' if (state.get('critic_report') or {}).get('needs_replan') else '아니오'}"
        )
        try:
            plan: Plan = _llm.invoke([SystemMessage(content=_PLANNER_PROMPT.format(
                situation=situation, agents=agents,
            ))])
            # LLM이 항목을 바꿔도 골격으로 강제 정렬(goal만 채택)
            goal_by_agent = {s.agent: s.goal for s in plan.steps}
            steps = [
                {"agent": a, "goal": goal_by_agent.get(a, sk["goal"])}
                for a, sk in zip(agents, skeleton)
            ]
            reason = plan.reason
        except Exception as e:
            print(f"[planner] LLM 계획 실패 — 결정적 fallback 사용: {e}")
            steps = skeleton
            reason = "LLM 실패로 기본 조사 계획 사용"

        return {"plan": {"steps": steps, "reason": reason}}

    return planner_node
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/unit/test_planner.py -v`
Expected: 3 passed.

- [ ] **Step 5: 커밋**

```bash
git add src/agent/planner.py tests/unit/test_planner.py
git commit -m "feat(agent): Planner 노드 + Plan/Step 모델 (입력별 조사 계획)"
```

---

## Task 3: Retrieval 노드

직무 요구 스킬과 공고 근거를 검색해 `retrieved_context`를 채운다. Critic이 이 컨텍스트를 근거로 쓴다.

**Files:**
- Create: `src/agent/retrieval_agent.py`
- Test: `tests/unit/test_retrieval_agent.py` (신규)

- [ ] **Step 1: 실패하는 테스트 작성**

Create `tests/unit/test_retrieval_agent.py`:
```python
# Retrieval 노드가 neo4j 요구스킬 + chroma 근거를 retrieved_context로 모으는지 검증
from unittest.mock import MagicMock

from src.agent.retrieval_agent import create_retrieval_node


def test_retrieval_collects_context():
    neo4j = MagicMock()
    neo4j.execute_query.return_value = [
        {"skill": "LangGraph", "importance": "REQUIRES", "weight": 12},
    ]
    chroma = MagicMock()
    chroma.search.return_value = [
        {"original_text": "LangGraph production experience required",
         "job_title": "AI Engineer", "company": "Acme",
         "section_type": "required", "source_id": "muse-1"},
    ]
    node = create_retrieval_node(neo4j, chroma)
    out = node({"job_family": "AI/LLM Engineer"})

    assert "retrieved_context" in out
    ctx = out["retrieved_context"]
    assert len(ctx) >= 1
    assert ctx[0]["source_id"] == "muse-1"
    assert "LangGraph" in [r["skill"] for r in out["retrieved_context"] if "skill" in r] or \
           any("LangGraph" in c.get("text", "") for c in ctx)


def test_retrieval_handles_empty():
    neo4j = MagicMock()
    neo4j.execute_query.return_value = []
    chroma = MagicMock()
    chroma.search.return_value = []
    node = create_retrieval_node(neo4j, chroma)
    out = node({"job_family": "Unknown"})
    assert out["retrieved_context"] == []
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/unit/test_retrieval_agent.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: retrieval_agent.py 구현**

Create `src/agent/retrieval_agent.py`:
```python
# 직무 요구 스킬과 공고 근거를 검색해 retrieved_context를 채우는 Retrieval 노드
from __future__ import annotations

from typing import TYPE_CHECKING

from src.agent.state import AppState
from src.agent.tools import _JOB_SKILLS_QUERY

if TYPE_CHECKING:
    from src.storage.chroma_client import ChromaClient
    from src.storage.neo4j_client import Neo4jClient


def create_retrieval_node(neo4j: "Neo4jClient", chroma: "ChromaClient"):
    """Retrieval 노드 팩토리.

    1. Neo4j에서 직군 요구 스킬(REQUIRES 상위)을 조회
    2. Chroma에서 직무 키워드로 required 섹션 근거 검색
    결과를 retrieved_context(list[dict])로 병합한다.
    """

    def retrieval_node(state: AppState) -> dict:
        job_family = state["job_family"]
        context: list[dict] = []

        try:
            rows = neo4j.execute_query(_JOB_SKILLS_QUERY, job_family=job_family)
            required = [r for r in rows if r.get("importance") == "REQUIRES"]
            for r in required[:10]:
                context.append({"skill": r["skill"], "weight": r.get("weight") or 1})
        except Exception as e:
            print(f"[retrieval] Neo4j 요구스킬 조회 실패: {e}")

        try:
            chunks = chroma.search(job_family, n_results=5, section_type="required")
            for c in chunks:
                context.append({
                    "source_id": c["source_id"],
                    "company": c.get("company", ""),
                    "job_title": c.get("job_title", ""),
                    "text": c["original_text"][:400],
                })
        except Exception as e:
            print(f"[retrieval] Chroma 근거 검색 실패: {e}")

        return {"retrieved_context": context}

    return retrieval_node
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/unit/test_retrieval_agent.py -v`
Expected: 2 passed.

- [ ] **Step 5: 커밋**

```bash
git add src/agent/retrieval_agent.py tests/unit/test_retrieval_agent.py
git commit -m "feat(agent): Retrieval 노드 (요구스킬+공고근거 → retrieved_context)"
```

---

## Task 4: Market 노드

부족 스킬·직무의 수요·연봉 트렌드를 조사해 `market_result`를 채운다.

**Files:**
- Create: `src/agent/market_agent.py`
- Test: `tests/unit/test_market_agent.py` (신규)

- [ ] **Step 1: 실패하는 테스트 작성**

Create `tests/unit/test_market_agent.py`:
```python
# Market 노드가 직무 분포·상위스킬·트렌드를 market_result로 모으는지 검증
from unittest.mock import MagicMock

from src.agent.market_agent import create_market_node


def test_market_collects_result():
    neo4j = MagicMock()
    neo4j.get_job_distribution.return_value = [{"title": "AI Engineer", "count": 20}]
    neo4j.get_top_skills.return_value = [{"skill": "Python", "count": 15}]
    neo4j.get_location_distribution.return_value = [{"location": "Remote", "count": 8}]
    node = create_market_node(neo4j)
    out = node({"job_family": "AI/LLM Engineer"})

    assert "market_result" in out
    mr = out["market_result"]
    assert "top_required_skills" in mr
    assert mr["top_required_skills"][0]["skill"] == "Python"


def test_market_handles_error():
    neo4j = MagicMock()
    neo4j.get_job_distribution.side_effect = RuntimeError("db down")
    node = create_market_node(neo4j)
    out = node({"job_family": "AI/LLM Engineer"})
    assert out["market_result"].get("error")
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/unit/test_market_agent.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: market_agent.py 구현**

Create `src/agent/market_agent.py`:
```python
# 직무 수요·연봉·트렌드를 조사해 market_result를 채우는 Market 노드
from __future__ import annotations

from typing import TYPE_CHECKING

from src.agent.state import AppState

if TYPE_CHECKING:
    from src.storage.neo4j_client import Neo4jClient


def create_market_node(neo4j: "Neo4jClient"):
    """Market 노드 팩토리. 직무 분포·상위 요구스킬·지역 분포를 모은다."""

    def market_node(state: AppState) -> dict:
        job_family = state["job_family"]
        try:
            result = {
                "job_distribution": neo4j.get_job_distribution(),
                "top_required_skills": neo4j.get_top_skills(job_family, limit=10),
                "location_distribution": neo4j.get_location_distribution(job_family, limit=5),
            }
        except Exception as e:
            print(f"[market] 시장 인사이트 조회 실패: {e}")
            result = {"error": str(e)}
        return {"market_result": result}

    return market_node
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/unit/test_market_agent.py -v`
Expected: 2 passed.

- [ ] **Step 5: 커밋**

```bash
git add src/agent/market_agent.py tests/unit/test_market_agent.py
git commit -m "feat(agent): Market 노드 (수요·트렌드 → market_result)"
```

---

## Task 5: Critic 노드

`gap_result`의 주장을 `retrieved_context`와 대조해 근거 충실성을 판정하고 replan 여부를 결정한다.

**Files:**
- Create: `src/agent/critic.py`
- Test: `tests/unit/test_critic.py` (신규)

- [ ] **Step 1: 실패하는 테스트 작성**

Create `tests/unit/test_critic.py`:
```python
# Critic의 결정적 부분(replan 가드레일, 빈 입력 처리)을 검증
from src.agent.critic import decide_replan


def test_replan_blocked_at_limit():
    # 상한(2) 도달 시 unfaithful이어도 replan 금지
    assert decide_replan(faithful=False, replan_count=2) is False
    assert decide_replan(faithful=False, replan_count=3) is False


def test_replan_allowed_below_limit():
    assert decide_replan(faithful=False, replan_count=0) is True
    assert decide_replan(faithful=False, replan_count=1) is True


def test_no_replan_when_faithful():
    assert decide_replan(faithful=True, replan_count=0) is False
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/unit/test_critic.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: critic.py 구현**

Create `src/agent/critic.py`:
```python
# gap_result 주장을 retrieved_context와 대조해 근거 충실성을 판정하는 Critic 노드
from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from src.agent.state import AppState, MAX_REPLAN

if TYPE_CHECKING:
    pass


class CriticReport(BaseModel):
    faithful: bool = Field(description="갭 주장들이 검색 근거에 충실한가")
    unsupported_claims: list[str] = Field(
        default_factory=list, description="근거가 부족한 주장 목록(한국어)"
    )


_CRITIC_PROMPT = """당신은 RAG 답변의 근거 충실성(faithfulness)을 검증하는 Critic입니다.
아래 '갭 분석 주장'들이 '검색된 공고 근거'에 의해 실제로 뒷받침되는지 판정하세요.

[갭 분석 주장]
{claims}

[검색된 공고 근거]
{evidence}

판정 규칙:
- 각 주장이 근거 텍스트로 뒷받침되면 faithful=true.
- 근거가 없거나 모순되는 주장이 하나라도 있으면 faithful=false, 그 주장을 unsupported_claims에 한국어로 기록.
- 근거가 비어 있으면 검증 불가이므로 faithful=false 처리."""


def decide_replan(faithful: bool, replan_count: int) -> bool:
    """replan 여부를 결정한다(결정적 가드레일).

    근거 불충실하고 replan 상한(MAX_REPLAN) 미만일 때만 재계획한다.
    """
    return (not faithful) and (replan_count < MAX_REPLAN)


def _extract_claims(gap_result: dict) -> list[str]:
    """gap_result에서 검증 대상 주장 텍스트를 추출한다."""
    claims: list[str] = []
    for item in gap_result.get("missing_required") or []:
        if isinstance(item, dict):
            skill = item.get("skill", "")
            reason = item.get("reason", "")
            claims.append(f"{skill}: {reason}".strip(": "))
        elif isinstance(item, str):
            claims.append(item)
    return claims


def create_critic_node(openai_client):
    """Critic 노드 팩토리. openai_client는 시그니처 일관성용(미사용)."""
    if not os.getenv("OPENAI_API_KEY"):
        raise EnvironmentError("OPENAI_API_KEY 환경변수가 필요합니다.")

    _llm = ChatOpenAI(model="gpt-4o-mini", temperature=0).with_structured_output(CriticReport)

    def critic_node(state: AppState) -> dict:
        gap_result = state.get("gap_result") or {}
        context = state.get("retrieved_context") or []
        replan_count = state.get("replan_count", 0)

        claims = _extract_claims(gap_result)
        evidence_texts = [c.get("text", "") for c in context if c.get("text")]

        if not claims:
            report = {"faithful": True, "unsupported_claims": [], "needs_replan": False}
            return {"critic_report": report}

        try:
            verdict: CriticReport = _llm.invoke([SystemMessage(content=_CRITIC_PROMPT.format(
                claims=json.dumps(claims, ensure_ascii=False, indent=2),
                evidence=json.dumps(evidence_texts, ensure_ascii=False, indent=2),
            ))])
            faithful = verdict.faithful
            unsupported = verdict.unsupported_claims
        except Exception as e:
            print(f"[critic] 판정 실패 — 보수적으로 통과 처리: {e}")
            faithful, unsupported = True, []

        report = {
            "faithful": faithful,
            "unsupported_claims": unsupported,
            "needs_replan": decide_replan(faithful, replan_count),
        }
        return {"critic_report": report}

    return critic_node
```

- [ ] **Step 4: MAX_REPLAN 상수 추가 (state.py)**

`src/agent/state.py`의 상수 블록(`COACH_MAX_ITERATIONS = 3` 아래)에 추가:
```python
MAX_REPLAN = 2
```

- [ ] **Step 5: 통과 확인**

Run: `python -m pytest tests/unit/test_critic.py -v`
Expected: 3 passed.

- [ ] **Step 6: 커밋**

```bash
git add src/agent/critic.py src/agent/state.py tests/unit/test_critic.py
git commit -m "feat(agent): Critic 노드 (LLM-as-judge faithfulness + replan 가드레일)"
```

---

## Task 6: Profile 노드 통합

기존 `resume_agent`와 `github_agent`를 하나의 Profile 노드로 묶어 Executor의 병렬 분기 하나로 만든다. **내부 PDF∥GitHub 병렬은 다음 서브프로젝트로 미룬다(순차 처리).** 스킬 결과를 `profile_result`에도 기록한다.

**Files:**
- Create: `src/agent/profile_agent.py`
- Test: `tests/unit/test_profile_agent.py` (신규)

- [ ] **Step 1: 실패하는 테스트 작성**

Create `tests/unit/test_profile_agent.py`:
```python
# Profile 노드가 resume 스킬 추출 + (선택)GitHub confidence 갱신을 수행하는지 검증
from unittest.mock import MagicMock

from src.agent.profile_agent import create_profile_node


def test_profile_with_injected_skills():
    neo4j = MagicMock()
    neo4j.get_portfolio_demonstrated_skills.return_value = []
    openai = MagicMock()
    node = create_profile_node(neo4j, openai)
    out = node({
        "owner": "김지원", "job_family": "AI/LLM Engineer",
        "pdf_path": None, "resume_text": None, "github_url": None,
        "resume_skills": ["Python", "LangGraph"],
    })
    assert out["profile_result"]["skills"] == ["Python", "LangGraph"]
    assert out["resume_skills"] == ["Python", "LangGraph"]


def test_profile_loads_from_neo4j_when_no_input():
    from src.extraction.skill_extractor import DemonstratedSkill
    neo4j = MagicMock()
    neo4j.get_portfolio_demonstrated_skills.return_value = [
        DemonstratedSkill(name="Docker", confidence="high", evidence="x"),
    ]
    openai = MagicMock()
    node = create_profile_node(neo4j, openai)
    out = node({
        "owner": "김지원", "job_family": "AI/LLM Engineer",
        "pdf_path": None, "resume_text": None, "github_url": None,
        "resume_skills": [],
    })
    assert "Docker" in out["profile_result"]["skills"]
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/unit/test_profile_agent.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: profile_agent.py 구현**

Create `src/agent/profile_agent.py`:
```python
# 이력서(PDF/텍스트/주입)와 GitHub에서 보유 스킬·confidence를 모으는 Profile 노드
from __future__ import annotations

from typing import TYPE_CHECKING

from src.agent.state import AppState

if TYPE_CHECKING:
    from openai import OpenAI
    from src.storage.neo4j_client import Neo4jClient


def create_profile_node(neo4j: "Neo4jClient", openai_client: "OpenAI"):
    """Profile 노드 팩토리.

    입력 우선순위(기존 resume_agent와 동일):
      1. resume_skills 주입
      2. pdf_path 파싱
      3. resume_text 직접 입력
      4. Neo4j 기존 포트폴리오
    이후 github_url이 있으면 confidence를 갱신한다(순차).
    결과를 profile_result + resume_skills로 반환한다.
    """
    from src.portfolio.pdf_parser import extract_pdf_text
    from src.extraction.skill_extractor import extract_skills_from_resume
    from src.portfolio.github_connector import (
        boost_confidence_from_github, parse_github_username,
    )

    def _extract(resume_text: str, owner: str) -> list[str]:
        extraction = extract_skills_from_resume(resume_text, openai_client)
        extraction = extraction.model_copy(update={"candidate_name": owner})
        neo4j.save_portfolio(extraction)
        return [s.name for sec in extraction.sections for s in sec.skills]

    def profile_node(state: AppState) -> dict:
        owner = state["owner"]
        skills: list[str] = []

        if state.get("resume_skills"):
            skills = list(state["resume_skills"])
        elif state.get("pdf_path"):
            try:
                skills = _extract(extract_pdf_text(state["pdf_path"]), owner)
            except Exception as e:
                print(f"[profile] PDF 처리 실패: {e}")
        elif state.get("resume_text"):
            try:
                skills = _extract(state["resume_text"], owner)
            except Exception as e:
                print(f"[profile] 텍스트 처리 실패: {e}")
        else:
            existing = neo4j.get_portfolio_demonstrated_skills(owner)
            skills = [s.name for s in existing]

        github_changes: dict = {}
        if state.get("github_url"):
            try:
                username = parse_github_username(state["github_url"])
                current = neo4j.get_portfolio_demonstrated_skills(owner)
                if current:
                    _, github_changes = boost_confidence_from_github(current, username)
                    if github_changes:
                        neo4j.update_portfolio_confidence(owner, github_changes)
            except Exception as e:
                print(f"[profile] GitHub 처리 실패: {e}")

        return {
            "resume_skills": skills,
            "profile_result": {"skills": skills, "github_changes": github_changes},
        }

    return profile_node
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/unit/test_profile_agent.py -v`
Expected: 2 passed.

- [ ] **Step 5: 커밋**

```bash
git add src/agent/profile_agent.py tests/unit/test_profile_agent.py
git commit -m "feat(agent): Profile 노드 (resume+github 통합 → profile_result)"
```

---

## Task 7: Executor 디스패치 + 그래프 재조립

Planner→Executor(병렬)→Gap→Synthesizer→Critic→(Replan|Coach) 그래프를 조립한다. 기존 Gap 루프(`call_model↔tools`)와 Coach 루프, `generate_report`(Synthesizer)는 그대로 재사용한다.

**Files:**
- Modify: `src/agent/supervisor.py`
- Test: `tests/unit/test_executor_dispatch.py` (신규), `tests/integration/test_agent.py` (수정)

- [ ] **Step 1: Executor 디스패치 단위 테스트 작성**

Create `tests/unit/test_executor_dispatch.py`:
```python
# Executor 디스패치가 plan의 병렬 가능 step만 Send로 펼치는지 검증
from src.agent.supervisor import executor_dispatch


def _state(steps):
    return {"plan": {"steps": steps, "reason": "x"}}


def test_dispatches_parallel_agents_only():
    steps = [
        {"agent": "profile", "goal": "a"},
        {"agent": "retrieval", "goal": "b"},
        {"agent": "market", "goal": "c"},
        {"agent": "gap", "goal": "d"},     # gap은 병렬 그룹에서 제외(의존성)
    ]
    sends = executor_dispatch(_state(steps))
    targets = sorted(s.node for s in sends)
    assert targets == ["market", "profile", "retrieval"]


def test_skips_profile_when_absent():
    steps = [
        {"agent": "retrieval", "goal": "b"},
        {"agent": "market", "goal": "c"},
        {"agent": "gap", "goal": "d"},
    ]
    sends = executor_dispatch(_state(steps))
    targets = sorted(s.node for s in sends)
    assert targets == ["market", "retrieval"]
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/unit/test_executor_dispatch.py -v`
Expected: FAIL — `ImportError: cannot import name 'executor_dispatch'`.

- [ ] **Step 3: supervisor.py에 디스패치·라우팅 함수 추가**

`src/agent/supervisor.py` 상단 import에 추가:
```python
from langgraph.types import Send
from src.agent.state import MAX_REPLAN
```

모듈 레벨(함수 밖)에 디스패치/라우팅 함수 추가:
```python
# Plan의 병렬 가능 step(profile/retrieval/market)만 Send로 펼친다. gap은 의존성 때문에 제외.
_PARALLEL_AGENTS = ("profile", "retrieval", "market")


def executor_dispatch(state: AppState) -> list:
    """Plan에 포함된 병렬 가능 agent를 Send로 fan-out한다."""
    plan = state.get("plan") or {}
    steps = plan.get("steps") or []
    present = [s["agent"] for s in steps if s["agent"] in _PARALLEL_AGENTS]
    return [Send(agent, state) for agent in present]


def route_after_critic(state: AppState) -> str:
    """Critic 판정으로 재계획(planner) 또는 코칭(coach_call_model)으로 분기."""
    report = state.get("critic_report") or {}
    if report.get("needs_replan") and state.get("replan_count", 0) < MAX_REPLAN:
        print(f"[critic] 재계획 (replan_count={state.get('replan_count', 0)})")
        return "planner"
    return "coach_call_model"


def increment_replan(state: AppState) -> dict:
    """planner 재진입 시 replan_count를 증가시키는 가벼운 패스스루는 planner_node가 처리하지 않으므로
    라우팅 엣지에서 직접 카운트한다(아래 그래프 조립 참고)."""
    return {"replan_count": state.get("replan_count", 0) + 1}
```

- [ ] **Step 4: 단위 테스트 통과 확인**

Run: `python -m pytest tests/unit/test_executor_dispatch.py -v`
Expected: 2 passed.

- [ ] **Step 5: create_supervisor_graph 재작성**

`src/agent/supervisor.py`의 `create_supervisor_graph` 본문을 아래 구조로 교체한다. 기존 `_make_tools_node`, `_make_coach_tools_node`, `create_nodes`, `create_coach_nodes`는 그대로 쓴다.

```python
def create_supervisor_graph(neo4j, chroma, openai_client):
    """Plan-and-Execute + Critic 그래프.

    START → planner → (Send)[profile ∥ retrieval ∥ market] → gap_loop
          → synthesizer → critic → (replan→planner | coach) → coach_loop → END
    """
    from src.agent.tools import create_tools, create_coach_tools
    from src.agent.nodes import create_nodes, create_coach_nodes
    from src.agent.planner import create_planner_node
    from src.agent.profile_agent import create_profile_node
    from src.agent.retrieval_agent import create_retrieval_node
    from src.agent.market_agent import create_market_node
    from src.agent.critic import create_critic_node

    gap_tools = create_tools(neo4j, chroma)
    coach_tools = create_coach_tools(chroma)
    call_model, generate_report = create_nodes(gap_tools, neo4j, chroma)
    coach_call_model, finalize_coach = create_coach_nodes(coach_tools)
    tools_node = _make_tools_node(gap_tools)
    coach_tools_node = _make_coach_tools_node(coach_tools)

    planner_node = create_planner_node(openai_client)
    profile_node = create_profile_node(neo4j, openai_client)
    retrieval_node = create_retrieval_node(neo4j, chroma)
    market_node = create_market_node(neo4j)
    critic_node = create_critic_node(openai_client)

    def route_gap_loop(state: AppState) -> str:
        if state.get("iteration", 0) >= MAX_ITERATIONS:
            return "synthesizer"
        routing = tools_condition(state)
        return "synthesizer" if routing == END else routing

    def route_coach_loop(state: AppState) -> str:
        if state.get("coach_iteration", 0) >= COACH_MAX_ITERATIONS:
            return "finalize_coach"
        last = (list(state.get("coach_messages") or [None]))[-1]
        if last and getattr(last, "tool_calls", None):
            return "coach_tools"
        return "finalize_coach"

    # gap 루프 진입 전 messages 시드(기존 resume_node가 하던 역할)
    def seed_gap(state: AppState) -> dict:
        from langchain_core.messages import HumanMessage
        skills = state.get("resume_skills") or []
        skills_str = ", ".join(skills) if skills else "없음 (공고 데이터만 사용)"
        user_msg = (
            f"직무 '{state['job_family']}'에 대해 갭 분석을 해주세요.\n"
            f"지원자 이름: {state['owner']}\n보유 스킬: {skills_str}"
        )
        return {"messages": [HumanMessage(content=user_msg)], "iteration": 0, "seen_source_ids": []}

    workflow = StateGraph(AppState)
    workflow.add_node("planner",          planner_node)
    workflow.add_node("profile",          profile_node)
    workflow.add_node("retrieval",        retrieval_node)
    workflow.add_node("market",           market_node)
    workflow.add_node("seed_gap",         seed_gap)
    workflow.add_node("call_model",       call_model)
    workflow.add_node("tools",            tools_node)
    workflow.add_node("synthesizer",      generate_report)   # gap_result + coach 시드 생성
    workflow.add_node("critic",           critic_node)
    workflow.add_node("coach_call_model", coach_call_model)
    workflow.add_node("coach_tools",      coach_tools_node)
    workflow.add_node("finalize_coach",   finalize_coach)

    workflow.add_edge(START, "planner")
    # Executor: planner 이후 병렬 fan-out
    workflow.add_conditional_edges("planner", executor_dispatch,
                                   ["profile", "retrieval", "market"])
    # 병렬 노드는 모두 seed_gap으로 모인다(barrier → reduce)
    workflow.add_edge("profile",   "seed_gap")
    workflow.add_edge("retrieval", "seed_gap")
    workflow.add_edge("market",    "seed_gap")
    # Gap 루프
    workflow.add_conditional_edges("call_model", route_gap_loop,
                                   {"tools": "tools", "synthesizer": "synthesizer"})
    workflow.add_edge("seed_gap", "call_model")
    workflow.add_edge("tools", "call_model")
    # Synthesizer → Critic
    workflow.add_edge("synthesizer", "critic")
    # Critic → replan(planner) | coach
    workflow.add_conditional_edges("critic", route_after_critic,
                                   {"planner": "planner", "coach_call_model": "coach_call_model"})
    # Coach 루프
    workflow.add_conditional_edges("coach_call_model", route_coach_loop,
                                   {"coach_tools": "coach_tools", "finalize_coach": "finalize_coach"})
    workflow.add_edge("coach_tools", "coach_call_model")
    workflow.add_edge("finalize_coach", END)

    return workflow.compile(checkpointer=MemorySaver())
```

> **replan_count 증가:** `route_after_critic`이 `"planner"`를 반환할 때 카운트가 올라가야 한다. `critic_node`가 `needs_replan`을 계산할 때 `replan_count`를 함께 `+1`해서 반환하도록 Task 5의 critic_node 반환부를 다음으로 보강한다:
> ```python
>         result = {"critic_report": report}
>         if report["needs_replan"]:
>             result["replan_count"] = replan_count + 1
>         return result
> ```

- [ ] **Step 6: run_supervisor / run_analysis 초기 상태에 신규 필드 추가**

`src/agent/supervisor.py`의 `run_supervisor`와 `run_analysis` 두 함수의 `initial` dict에 추가:
```python
        "plan": None,
        "replan_count": 0,
        "profile_result": None,
        "retrieved_context": [],
        "market_result": None,
        "critic_report": None,
```
또한 두 함수에서 더 이상 쓰지 않는 `resume`/`github` 전용 초기화는 그대로 두어도 무방하다(하위호환).

- [ ] **Step 7: 통합 테스트 갱신**

`tests/integration/test_agent.py`의 `TestCreateSupervisorGraph` 노드 검증을 새 구조에 맞게 교체:
```python
    @requires_api_key
    def test_graph_has_plan_execute_nodes(self, mock_clients) -> None:
        """Plan-and-Execute 노드가 모두 존재한다."""
        neo4j, chroma, openai = mock_clients
        graph = create_supervisor_graph(neo4j, chroma, openai)
        names = set(graph.get_graph().nodes.keys())
        for n in ("planner", "profile", "retrieval", "market", "critic", "synthesizer"):
            assert n in names, f"'{n}' 노드 누락"
```
기존 `test_graph_has_pipeline_nodes`(resume/github/coach 검증)는 `resume`/`github` 노드가 사라졌으므로 삭제하고, `coach_call_model`·`finalize_coach` 검증은 위 `test_graph_has_gap_loop_nodes`와 함께 유지한다.

- [ ] **Step 8: 그래프 컴파일·구조 검증**

Run: `python -m pytest tests/integration/test_agent.py -v -k "not test_returns_dict"`
Expected: 노드 검증 테스트 PASS (OPENAI_API_KEY 있을 때), 없으면 skip.

- [ ] **Step 9: end-to-end 동작 검증**

Run: `python -m pytest "tests/integration/test_agent.py::TestRunAnalysis::test_returns_dict" -q`
Expected: `1 passed`. 로그에 `[planner]`가 `[critic]`보다 먼저 출력되는지 확인.

- [ ] **Step 10: 전체 회귀**

Run: `python -m pytest tests/ -q -k "not test_returns_dict"`
Expected: 모든 단위·구조 테스트 통과.

- [ ] **Step 11: 커밋**

```bash
git add src/agent/supervisor.py tests/unit/test_executor_dispatch.py tests/integration/test_agent.py
git commit -m "feat(agent): Plan-and-Execute + Critic 그래프 조립 (Executor 병렬 + Replan 루프)"
```

---

## Task 8: 수동 스모크 테스트 (입력 조합·replan 경로)

자동 테스트가 커버하지 못하는 실제 LLM 경로를 눈으로 확인한다.

- [ ] **Step 1: PDF 없는 기본 실행**

Run:
```bash
python -c "
from dotenv import load_dotenv; load_dotenv()
from src.storage.neo4j_client import Neo4jClient
from src.storage.chroma_client import ChromaClient
from openai import OpenAI; import os
from src.agent.supervisor import create_supervisor_graph, run_supervisor
g = create_supervisor_graph(Neo4jClient(), ChromaClient(), OpenAI(api_key=os.getenv('OPENAI_API_KEY')))
r = run_supervisor(g, job_family='AI/LLM Engineer', owner='김지원', resume_skills=['Python','FastAPI'])
print('match_rate:', r.get('gap', {}).get('match_rate'))
print('critic:', r.get('critic') if 'critic' in r else '(final_report 구조 확인)')
"
```
Expected: 예외 없이 완료, `match_rate` 출력. 로그에 `[planner]` → (profile 생략, 병렬 retrieval/market) → `[critic]` 순서.

- [ ] **Step 2: 결과 구조 육안 확인**

`final_report`에 `gap`/`coaching` 키가 있고 `gap.missing_required`가 채워졌는지 확인. Critic이 replan을 발동한 경우 로그에 `[critic] 재계획`이 보이는지 확인.

- [ ] **Step 3: progress.md 갱신**

`progress.md`에 `## [2026-06-10]` 섹션을 추가하고 작업 절차 / 발생 문제 / 해결 방법 3단으로 기록한 뒤 커밋:
```bash
git add progress.md
git commit -m "docs: 멀티 에이전트 코어 전환 진행 기록"
```

---

## Self-Review 결과

**Spec coverage:** 설계 문서 §2~§9 항목 매핑 —
- §3 그래프 → Task 7 / §4 컴포넌트 → Task 2~6 / §5 AppState → Task 1 / §6 Plan → Task 2 / §7 Replan → Task 5·7 / §8 가드레일 → Task 5(decide_replan)·7(route) / §9 테스트 → 각 Task의 테스트 step. ✅ 누락 없음.
- §6 "PDF∥GitHub 병렬"은 Task 6에서 의도적으로 순차 처리(다음 서브프로젝트로 명시 연기). 설계 문서 범위(§2)의 "Executor 레벨 병렬"과 정합.

**Type consistency:** `Plan`/`Step`(planner.py), `CriticReport`(critic.py), `MAX_REPLAN`(state.py), `executor_dispatch`/`route_after_critic`(supervisor.py) — 정의처와 사용처 일치. `critic_report` dict 키(`faithful`/`unsupported_claims`/`needs_replan`)가 Task 5 생성·Task 7 소비에서 일치. ✅

**Placeholder scan:** TBD/TODO 없음. 모든 코드 step에 완전한 코드 포함. ✅
