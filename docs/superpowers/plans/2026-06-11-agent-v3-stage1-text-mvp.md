# 에이전트 v3 단계 1 (텍스트 MVP) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** v1 그래프를 다중 소스 적합도 평가의 **텍스트 MVP**(이력서·GitHub 평가자 → 결정적 합의 → Gap 적합도)로 전환한다.

**Architecture:** 디스패처가 입력에 있는 소스의 평가자만 Send로 병렬 실행 → 합의 노드가 검증 상태(Verified/Corroborated/Claimed)로 결정적 종합 → 기존 Gap 루프가 합의된 보유 스킬을 직무 요구와 비교해 적합도+신뢰도 산출. 멀티모달(포폴)·웹(배포URL)은 다음 단계.

**Tech Stack:** LangGraph(StateGraph, Send), langchain_openai, httpx(GitHub), 기존 skill_extractor·github_connector·normalizer 재사용.

**설계 문서:** `docs/superpowers/specs/2026-06-11-agent-v3-fit-assessment-design.md`

---

## 사전 지식 (기존 코드)

- `src/agent/state.py`: `AppState` TypedDict. `messages`는 `add_messages` reducer. 상수 `MAX_ITERATIONS=5`.
- `src/agent/supervisor.py`: 현재 v1 그래프 `START→planner→(Send)[profile∥retrieval∥market]→seed_gap→call_model↔tools→synthesizer→critic→coach`. `create_supervisor_graph(neo4j, chroma, openai_client)`, `seed_gap`, `_make_tools_node`, `run_supervisor`.
- `src/agent/nodes.py`: `create_nodes(tools,neo4j,chroma)→(call_model, generate_report)`. `generate_report`(=synthesizer)가 `messages`의 ToolMessage를 종합해 `gap_result` JSON 생성.
- `src/extraction/skill_extractor.py`: `extract_skills_from_resume(text, client)→ResumeExtraction`. `.sections[].skills[]` 각 skill은 `.name/.evidence/.confidence(high|medium|low)`.
- `src/portfolio/github_connector.py`: `parse_github_username(url)`, `_SKILL_KEYWORDS`(스킬→키워드 dict).
- `src/extraction/normalizer.py`: `normalize_skill(raw)→표준명`.
- `tests/conftest.py`가 `.env` 로드. 통합 테스트는 `OPENAI_API_KEY` 가드.

**v1에서 제거/대체:** planner·profile·retrieval·market 노드 → 디스패처+평가자+합의로 대체. Gap 루프·Critic·Coach는 유지.

---

## Task 0: feat/agent-v3 브랜치

- [ ] **Step 1: 현재 테스트 통과 확인**

Run: `python -m pytest tests/ -q -k "not test_returns_dict"`
Expected: 전부 통과.

- [ ] **Step 2: 브랜치 생성**

```bash
git checkout -b feat/agent-v3
```

---

## Task 1: AppState 신규 필드

**Files:** Modify `src/agent/state.py` / Test `tests/unit/test_state_v3.py`

- [ ] **Step 1: 실패 테스트**

Create `tests/unit/test_state_v3.py`:
```python
# v3 평가자/합의/적합도 필드 검증
from src.agent.state import AppState


def test_v3_fields_exist():
    ann = AppState.__annotations__
    for f in ("resume_eval", "github_eval", "consensus", "fit_result"):
        assert f in ann, f"'{f}' 누락"
```

- [ ] **Step 2: 실패 확인** — Run: `python -m pytest tests/unit/test_state_v3.py -v` → FAIL

- [ ] **Step 3: 필드 추가** — `src/agent/state.py`의 `critic_report` 다음에:
```python
    # ── v3: 다중 소스 평가 ──
    resume_eval: dict | None     # {"skills": [{skill, evidence, source, level_hint}]}
    github_eval: dict | None
    consensus: dict | None       # {skill: {verification, evidences, flags?}}
    fit_result: dict | None      # 적합도 + 신뢰도 (Gap 산출)
```

- [ ] **Step 4: 통과 확인** — Run: `python -m pytest tests/unit/test_state_v3.py -v` → PASS

- [ ] **Step 5: 커밋**
```bash
git add src/agent/state.py tests/unit/test_state_v3.py
git commit -m "feat(agent): AppState에 v3 평가자/합의/적합도 필드 추가"
```

---

## Task 2: 합의 노드 (결정적)

**Files:** Create `src/agent/consensus.py` / Test `tests/unit/test_consensus.py`

- [ ] **Step 1: 실패 테스트**

Create `tests/unit/test_consensus.py`:
```python
# 합의 노드 — 검증 상태 판정(결정적)
from src.agent.consensus import build_consensus


def test_verified_when_github():
    out = build_consensus([
        {"skills": [{"skill": "LangGraph", "evidence": "코드", "source": "github", "level_hint": "실무"}]},
    ])
    assert out["LangGraph"]["verification"] == "Verified"


def test_corroborated_when_two_sources():
    out = build_consensus([
        {"skills": [{"skill": "Docker", "evidence": "a", "source": "resume", "level_hint": None}]},
        {"skills": [{"skill": "Docker", "evidence": "b", "source": "portfolio", "level_hint": None}]},
    ])
    assert out["Docker"]["verification"] == "Corroborated"


def test_claimed_single_source_has_flag():
    out = build_consensus([
        {"skills": [{"skill": "AWS", "evidence": "a", "source": "resume", "level_hint": None}]},
    ])
    assert out["AWS"]["verification"] == "Claimed"
    assert "flags" in out["AWS"]


def test_normalize_merges_aliases():
    out = build_consensus([
        {"skills": [{"skill": "react.js", "evidence": "a", "source": "resume", "level_hint": None}]},
        {"skills": [{"skill": "React", "evidence": "b", "source": "portfolio", "level_hint": None}]},
    ])
    assert "React" in out
    assert out["React"]["verification"] == "Corroborated"
```

- [ ] **Step 2: 실패 확인** — Run: `python -m pytest tests/unit/test_consensus.py -v` → FAIL (ModuleNotFound)

- [ ] **Step 3: 구현**

Create `src/agent/consensus.py`:
```python
# 여러 평가자의 스킬 증거를 검증 상태로 종합하는 결정적 합의 노드 ("서기" 역할)
from __future__ import annotations

from typing import TYPE_CHECKING

from src.extraction.normalizer import normalize_skill

if TYPE_CHECKING:
    from src.agent.state import AppState

# 실증 가능한 소스 (코드·배포로 검증)
_VERIFIABLE_SOURCES = {"github", "deploy"}


def build_consensus(evaluator_outputs: list[dict]) -> dict:
    """평가자별 [{skill, evidence, source, level_hint}]를 스킬별 검증 상태로 합친다.

    Verified     : github/deploy 등 실증 소스에 증거
    Corroborated : 2개 이상 소스가 일치
    Claimed      : 1개 소스만 (코드 미확인 시 flag)
    """
    by_skill: dict[str, list[dict]] = {}
    for out in evaluator_outputs:
        for item in out.get("skills", []):
            name = normalize_skill(item["skill"])
            by_skill.setdefault(name, []).append({**item, "skill": name})

    consensus: dict[str, dict] = {}
    for skill, evidences in by_skill.items():
        sources = {e["source"] for e in evidences}
        if sources & _VERIFIABLE_SOURCES:
            status = "Verified"
        elif len(sources) >= 2:
            status = "Corroborated"
        else:
            status = "Claimed"
        result: dict = {"verification": status, "evidences": evidences}
        if status == "Claimed" and "github" not in sources:
            result["flags"] = ["코드 미확인 — 주장만"]
        consensus[skill] = result
    return consensus


def create_consensus_node():
    """합의 노드 팩토리. 평가자 결과를 합쳐 consensus에 쓴다."""
    def consensus_node(state: "AppState") -> dict:
        outputs = [state[k] for k in ("resume_eval", "github_eval") if state.get(k)]
        return {"consensus": build_consensus(outputs)}
    return consensus_node
```

- [ ] **Step 4: 통과 확인** — Run: `python -m pytest tests/unit/test_consensus.py -v` → 4 passed

- [ ] **Step 5: 커밋**
```bash
git add src/agent/consensus.py tests/unit/test_consensus.py
git commit -m "feat(agent): 결정적 합의 노드 (검증 상태 Verified/Corroborated/Claimed)"
```

---

## Task 3: 이력서 평가자

**Files:** Create `src/agent/evaluators/__init__.py`, `src/agent/evaluators/resume_eval.py` / Test `tests/unit/test_resume_eval.py`

- [ ] **Step 1: 실패 테스트**

Create `tests/unit/test_resume_eval.py`:
```python
# 이력서 평가자 — 주입 스킬 경로 (LLM 미호출)
from unittest.mock import MagicMock
from src.agent.evaluators.resume_eval import create_resume_evaluator


def test_injected_skills():
    node = create_resume_evaluator(MagicMock())
    out = node({"resume_skills": ["Python", "FastAPI"], "pdf_path": None, "resume_text": None})
    skills = out["resume_eval"]["skills"]
    assert {s["skill"] for s in skills} == {"Python", "FastAPI"}
    assert all(s["source"] == "resume" for s in skills)


def test_no_input_empty():
    node = create_resume_evaluator(MagicMock())
    out = node({"resume_skills": [], "pdf_path": None, "resume_text": None})
    assert out["resume_eval"]["skills"] == []
```

- [ ] **Step 2: 실패 확인** — Run: `python -m pytest tests/unit/test_resume_eval.py -v` → FAIL

- [ ] **Step 3: 구현**

Create `src/agent/evaluators/__init__.py` (빈 파일).

Create `src/agent/evaluators/resume_eval.py`:
```python
# 이력서에서 스킬 증거를 추출하는 평가자 (텍스트 modality)
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.agent.state import AppState


def create_resume_evaluator(openai_client):
    """이력서 평가자 팩토리. resume_skills 주입 > pdf > resume_text 순."""
    from src.portfolio.pdf_parser import extract_pdf_text
    from src.extraction.skill_extractor import extract_skills_from_resume

    def evaluate(state: "AppState") -> dict:
        if state.get("resume_skills"):
            skills = [
                {"skill": s, "evidence": "이력서 주입 스킬", "source": "resume", "level_hint": None}
                for s in state["resume_skills"]
            ]
            return {"resume_eval": {"skills": skills}}

        text = None
        if state.get("pdf_path"):
            try:
                text = extract_pdf_text(state["pdf_path"])
            except Exception as e:
                print(f"[resume_eval] PDF 실패: {e}")
        elif state.get("resume_text"):
            text = state["resume_text"]

        if not text:
            return {"resume_eval": {"skills": []}}

        try:
            extraction = extract_skills_from_resume(text, openai_client)
            skills = [
                {"skill": sk.name, "evidence": sk.evidence, "source": "resume", "level_hint": sk.confidence}
                for sec in extraction.sections for sk in sec.skills
            ]
        except Exception as e:
            print(f"[resume_eval] 추출 실패: {e}")
            skills = []
        return {"resume_eval": {"skills": skills}}

    return evaluate
```

- [ ] **Step 4: 통과 확인** — Run: `python -m pytest tests/unit/test_resume_eval.py -v` → 2 passed

- [ ] **Step 5: 커밋**
```bash
git add src/agent/evaluators/__init__.py src/agent/evaluators/resume_eval.py tests/unit/test_resume_eval.py
git commit -m "feat(agent): 이력서 평가자 (텍스트 → 스킬 증거)"
```

---

## Task 4: GitHub 평가자

**Files:** Create `src/agent/evaluators/github_eval.py` / Test `tests/unit/test_github_eval.py`

- [ ] **Step 1: 실패 테스트**

Create `tests/unit/test_github_eval.py`:
```python
# GitHub 평가자 — URL 없으면 빈 결과 (API 미호출)
from src.agent.evaluators.github_eval import create_github_evaluator


def test_no_url_empty():
    node = create_github_evaluator()
    out = node({"github_url": None})
    assert out["github_eval"]["skills"] == []


def test_invalid_url_empty():
    node = create_github_evaluator()
    out = node({"github_url": "not-a-url"})
    assert out["github_eval"]["skills"] == []
```

- [ ] **Step 2: 실패 확인** — Run: `python -m pytest tests/unit/test_github_eval.py -v` → FAIL

- [ ] **Step 3: 구현**

Create `src/agent/evaluators/github_eval.py`:
```python
# GitHub 레포에서 스킬 증거를 추출하는 평가자 (코드 modality)
from __future__ import annotations

import os
from typing import TYPE_CHECKING

import httpx

from src.portfolio.github_connector import parse_github_username, _SKILL_KEYWORDS

if TYPE_CHECKING:
    from src.agent.state import AppState


def create_github_evaluator():
    """GitHub 평가자 팩토리. 레포 메타데이터에서 스킬 키워드를 찾아 증거로."""
    def evaluate(state: "AppState") -> dict:
        url = state.get("github_url")
        if not url:
            return {"github_eval": {"skills": []}}
        try:
            username = parse_github_username(url)
        except ValueError as e:
            print(f"[github_eval] URL 파싱 실패: {e}")
            return {"github_eval": {"skills": []}}

        token = os.getenv("GITHUB_TOKEN")
        headers = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            resp = httpx.get(
                f"https://api.github.com/users/{username}/repos",
                headers=headers, params={"per_page": 100, "type": "owner"}, timeout=10,
            )
            resp.raise_for_status()
            repos = resp.json()
        except Exception as e:
            print(f"[github_eval] GitHub API 실패: {e}")
            return {"github_eval": {"skills": []}}

        repo_text = " ".join(
            f"{r.get('name','')} {r.get('description') or ''} "
            f"{' '.join(r.get('topics') or [])} {r.get('language') or ''}"
            for r in repos
        ).lower()

        skills = []
        for skill_name, keywords in _SKILL_KEYWORDS.items():
            if any(kw in repo_text for kw in keywords):
                skills.append({
                    "skill": skill_name,
                    "evidence": f"GitHub 레포에서 {skill_name} 사용 확인 ({username})",
                    "source": "github",
                    "level_hint": "실무",
                })
        return {"github_eval": {"skills": skills}}

    return evaluate
```

- [ ] **Step 4: 통과 확인** — Run: `python -m pytest tests/unit/test_github_eval.py -v` → 2 passed

- [ ] **Step 5: 커밋**
```bash
git add src/agent/evaluators/github_eval.py tests/unit/test_github_eval.py
git commit -m "feat(agent): GitHub 평가자 (레포 키워드 → 스킬 증거)"
```

---

## Task 5: 디스패처 + 그래프 재조립

**Files:** Modify `src/agent/supervisor.py` / Test `tests/unit/test_evaluator_dispatch.py`, `tests/integration/test_agent.py`

- [ ] **Step 1: 디스패처 단위 테스트**

Create `tests/unit/test_evaluator_dispatch.py`:
```python
# 디스패처 — 입력에 있는 소스의 평가자만 Send
from src.agent.supervisor import evaluator_dispatch


def test_resume_only():
    sends = evaluator_dispatch({"resume_skills": ["Python"], "github_url": None,
                                "pdf_path": None, "resume_text": None})
    assert sorted(s.node for s in sends) == ["resume_eval"]


def test_resume_and_github():
    sends = evaluator_dispatch({"resume_skills": ["Python"], "github_url": "https://github.com/x",
                                "pdf_path": None, "resume_text": None})
    assert sorted(s.node for s in sends) == ["github_eval", "resume_eval"]


def test_empty_defaults_resume():
    sends = evaluator_dispatch({"resume_skills": [], "github_url": None,
                                "pdf_path": None, "resume_text": None})
    assert [s.node for s in sends] == ["resume_eval"]
```

- [ ] **Step 2: 실패 확인** — Run: `python -m pytest tests/unit/test_evaluator_dispatch.py -v` → FAIL (ImportError)

- [ ] **Step 3: 디스패처 + seed_gap 보강 + 그래프 재조립**

`src/agent/supervisor.py` 모듈 레벨에 추가:
```python
def evaluator_dispatch(state: AppState) -> list:
    """입력에 있는 소스의 평가자만 Send로 fan-out."""
    sends = []
    if state.get("resume_skills") or state.get("pdf_path") or state.get("resume_text"):
        sends.append(Send("resume_eval", state))
    if state.get("github_url"):
        sends.append(Send("github_eval", state))
    if not sends:
        sends.append(Send("resume_eval", state))   # 최소 하나 보장
    return sends
```

`create_supervisor_graph` 본문을 v3 단계1 구조로 교체 (planner/profile/retrieval/market 제거, 평가자+합의 추가). seed_gap이 consensus의 보유 스킬을 메시지로 시드:
```python
def create_supervisor_graph(neo4j, chroma, openai_client):
    """v3 단계1: 평가자 병렬 → 합의 → Gap 적합도 → Critic → Coach."""
    from src.agent.tools import create_tools, create_coach_tools
    from src.agent.nodes import create_nodes, create_coach_nodes
    from src.agent.evaluators.resume_eval import create_resume_evaluator
    from src.agent.evaluators.github_eval import create_github_evaluator
    from src.agent.consensus import create_consensus_node
    from src.agent.critic import create_critic_node

    gap_tools = create_tools(neo4j, chroma)
    coach_tools = create_coach_tools(chroma)
    call_model, generate_report = create_nodes(gap_tools, neo4j, chroma)
    coach_call_model, finalize_coach = create_coach_nodes(coach_tools)
    tools_node = _make_tools_node(gap_tools)
    coach_tools_node = _make_coach_tools_node(coach_tools)

    resume_eval = create_resume_evaluator(openai_client)
    github_eval = create_github_evaluator()
    consensus_node = create_consensus_node()
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

    def seed_gap(state: AppState) -> dict:
        from langchain_core.messages import HumanMessage
        consensus = state.get("consensus") or {}
        held = ", ".join(f"{s}({d['verification']})" for s, d in consensus.items()) or "없음"
        user_msg = (
            f"직무 '{state['job_family']}'에 대해 적합도 분석을 해주세요.\n"
            f"지원자: {state['owner']}\n"
            f"보유 스킬(검증상태 포함): {held}\n"
            f"각 스킬을 직무 요구 수준과 비교해 적합도와 갭을 산출하세요."
        )
        return {"messages": [HumanMessage(content=user_msg)], "iteration": 0, "seen_source_ids": []}

    workflow = StateGraph(AppState)
    workflow.add_node("resume_eval",      resume_eval)
    workflow.add_node("github_eval",      github_eval)
    workflow.add_node("consensus",        consensus_node)
    workflow.add_node("seed_gap",         seed_gap)
    workflow.add_node("call_model",       call_model)
    workflow.add_node("tools",            tools_node)
    workflow.add_node("synthesizer",      generate_report)
    workflow.add_node("critic",           critic_node)
    workflow.add_node("coach_call_model", coach_call_model)
    workflow.add_node("coach_tools",      coach_tools_node)
    workflow.add_node("finalize_coach",   finalize_coach)

    workflow.add_conditional_edges(START, evaluator_dispatch, ["resume_eval", "github_eval"])
    workflow.add_edge("resume_eval", "consensus")
    workflow.add_edge("github_eval", "consensus")
    workflow.add_edge("consensus", "seed_gap")
    workflow.add_edge("seed_gap", "call_model")
    workflow.add_conditional_edges("call_model", route_gap_loop,
                                   {"tools": "tools", "synthesizer": "synthesizer"})
    workflow.add_edge("tools", "call_model")
    workflow.add_edge("synthesizer", "critic")
    from src.agent.supervisor import route_after_critic  # 기존 재사용 (needs_replan 시 planner 없으니 coach로만)
    def route_after_critic_v3(state: AppState) -> str:
        return "coach_call_model"   # v3 단계1: replan 없음, 항상 coach
    workflow.add_edge("critic", "coach_call_model")
    workflow.add_conditional_edges("coach_call_model", route_coach_loop,
                                   {"coach_tools": "coach_tools", "finalize_coach": "finalize_coach"})
    workflow.add_edge("coach_tools", "coach_call_model")
    workflow.add_edge("finalize_coach", END)

    return workflow.compile(checkpointer=MemorySaver())
```
> 주의: v3 단계1은 replan 없음 → critic 다음 coach 직결(`add_edge("critic","coach_call_model")`). critic_node는 그대로 두되 needs_replan은 무시된다(다음 단계에서 길 B 등급화로 재작성).

- [ ] **Step 4: run_supervisor 초기 상태에 v3 필드 추가**

`run_supervisor`/`run_analysis`의 `initial` dict에 추가:
```python
        "resume_eval": None, "github_eval": None, "consensus": None, "fit_result": None,
```

- [ ] **Step 5: 디스패처 테스트 통과** — Run: `python -m pytest tests/unit/test_evaluator_dispatch.py -v` → 3 passed

- [ ] **Step 6: 통합 테스트 갱신**

`tests/integration/test_agent.py`의 `test_graph_has_plan_execute_nodes`를 v3 노드로 교체:
```python
    @requires_api_key
    def test_graph_has_v3_nodes(self, mock_clients) -> None:
        neo4j, chroma, openai = mock_clients
        graph = create_supervisor_graph(neo4j, chroma, openai)
        names = set(graph.get_graph().nodes.keys())
        for n in ("resume_eval", "github_eval", "consensus", "synthesizer", "critic"):
            assert n in names, f"'{n}' 누락"
```

- [ ] **Step 7: 구조·회귀 확인** — Run: `python -m pytest tests/ -q -k "not test_returns_dict"` → 통과

- [ ] **Step 8: 커밋**
```bash
git add src/agent/supervisor.py tests/unit/test_evaluator_dispatch.py tests/integration/test_agent.py
git commit -m "feat(agent): v3 단계1 그래프 — 디스패처+평가자 병렬+합의 (planner/retrieval/market 제거)"
```

---

## Task 6: Gap 적합도 출력 (synthesizer 프롬프트)

**Files:** Modify `src/agent/nodes.py`

- [ ] **Step 1: `_GAP_REPORT_PROMPT`에 적합도+신뢰도 반영**

`src/agent/nodes.py`의 `_GAP_REPORT_PROMPT` JSON 스키마에 적합도·신뢰도 필드를 추가하고, generate_report가 `consensus`를 프롬프트에 포함하도록 수정. 출력 JSON에 추가:
```json
{
  "fit_score": 0.0,
  "confidence_level": "high|medium|low",
  "advice": "GitHub·포트폴리오를 추가하면 더 정확한 분석이 가능합니다",
  "skills": [{"skill":"...", "required_level":"실무", "held_level":"실무(주장)", "verification":"Claimed", "gap":"..."}]
}
```
generate_report 본문에서 `consensus = state.get("consensus") or {}`를 프롬프트에 함께 전달.

- [ ] **Step 2: end-to-end로 fit_score 산출 확인** (Task 7에서 스모크)

- [ ] **Step 3: 커밋**
```bash
git add src/agent/nodes.py
git commit -m "feat(agent): Gap 적합도+신뢰도 출력 (fit_score + confidence + advice)"
```

---

## Task 7: 스모크 + progress

- [ ] **Step 1: 실제 데이터 스모크**

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
print('gap keys:', list((r.get('gap') or {}).keys()))
"
```
Expected: 예외 없이 완료. 로그에 `[resume_eval]` 등. gap에 fit_score/confidence 키.

- [ ] **Step 2: progress.md 갱신 + 커밋**
```bash
git add progress.md
git commit -m "docs: v3 단계1 텍스트 MVP 진행 기록"
```

---

## Self-Review

**Spec coverage:** 설계 §3(평가자)→Task 3·4, §5(합의)→Task 2, §6(Gap 적합도)→Task 6, §7(두 축 출력)→Task 6, §8(그래프)→Task 5. 멀티모달 포폴·배포URL은 단계 2~3(범위 밖, 명시). ✅

**Placeholder scan:** 각 코드 step에 완전 코드. Task 6의 프롬프트 수정은 스키마를 명시. ✅

**Type consistency:** 평가자 출력 형식 `{skills:[{skill,evidence,source,level_hint}]}`이 Task 3·4·2(build_consensus 입력)에서 일치. `consensus` 구조 `{skill:{verification,evidences}}`가 Task 2 생성·Task 5 seed_gap 소비에서 일치. ✅

**알려진 한계:** Task 5의 `route_after_critic_v3`는 정의했으나 `add_edge("critic","coach_call_model")`로 단순 직결했으므로 미사용(제거 가능 — 구현 시 dead code 정리). critic의 replan은 v3 단계1에서 무시되며, 다음 단계에서 길 B 등급화로 재작성 예정.
