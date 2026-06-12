# 배포 URL 평가자 (v3 단계 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 배포 URL을 fetch해 "작동 실증 + 프론트 기술"을 추출하는 평가자를 추가한다 — 4개 소스 설계의 마지막 소스.

**Architecture:** 기존 평가자 패턴(팩토리 → `evaluate(state)` → `{source_eval:{skills:[...]}}`)을 따른다. URL을 httpx로 가져와(200이면 "작동 실증") HTML+응답헤더에서 대상 직군 스킬을 단어경계+별칭 매칭(github 평가자 매처 재사용). 출력 `source:"deploy"` → 합의에서 **Verified**(consensus의 `_VERIFIABLE_SOURCES`에 deploy 이미 포함).

**Tech Stack:** httpx(이미 설치됨), 기존 `github_eval._word_match`·`_keywords_for` 재사용, Neo4j 직군 스킬 어휘(`get_job_family_skills`).

**설계 문서:** `docs/superpowers/specs/2026-06-11-agent-v3-fit-assessment-design.md` §4-2

---

## 사전 지식 (기존 코드)

- 평가자 계약: `{"<source>_eval": {"skills": [{skill, evidence, source, level_hint}]}}`. deploy는 `source:"deploy"`.
- `src/agent/consensus.py`: `_VERIFIABLE_SOURCES = {"github", "deploy"}` — deploy 증거가 있으면 Verified. `consensus_node`가 `for k in ("resume_eval","github_eval","portfolio_eval")`로 평가자 결과를 모음(여기에 "deploy_eval" 추가 필요).
- `src/agent/evaluators/github_eval.py`: `_word_match(keyword, text) -> bool`(단어경계), `_keywords_for(skill) -> list[str]`(스킬+별칭). 그대로 재사용.
- `src/storage/neo4j_client.py`: `get_job_family_skills(job_family) -> list[str]`(직군 상위 스킬, github와 공유).
- `src/agent/state.py`: 입력 필드 `pdf_path`/`portfolio_path`/`github_url`, 평가 필드 `resume_eval`/`github_eval`/`portfolio_eval`/`consensus`/`fit_result`.
- `src/agent/supervisor.py`: `evaluator_dispatch`(입력 있는 소스만 Send), `create_supervisor_graph`(평가자 노드+엣지), `run_supervisor`/`run_analysis`(초기 state dict 2곳).

---

## Task 1: AppState 필드 + 합의 노드 포함

**Files:** Modify `src/agent/state.py`, `src/agent/consensus.py` / Test `tests/unit/test_consensus.py`(추가)

- [ ] **Step 1: 실패 테스트**

`tests/unit/test_consensus.py` 끝에 추가:
```python
def test_consensus_node_includes_deploy_as_verified():
    from src.agent.consensus import create_consensus_node
    node = create_consensus_node()
    state = {
        "deploy_eval": {"skills": [{"skill": "React", "evidence": "배포", "source": "deploy", "level_hint": "실무"}]},
    }
    out = node(state)["consensus"]
    assert out["React"]["verification"] == "Verified"   # deploy = 실증 소스
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/unit/test_consensus.py::test_consensus_node_includes_deploy_as_verified -v`
Expected: FAIL (consensus_node가 deploy_eval을 안 읽어 KeyError 없이 빈 consensus → `out["React"]` KeyError).

- [ ] **Step 3: AppState 필드 추가**

`src/agent/state.py`에서 입력 필드(`github_url` 다음 줄)에 추가:
```python
    deploy_url: str | None       # 배포 URL (작동 실증 평가자 입력)
```
평가 필드(`portfolio_eval` 다음 줄)에 추가:
```python
    deploy_eval: dict | None
```

- [ ] **Step 4: 합의 노드가 deploy_eval 포함**

`src/agent/consensus.py`의 `consensus_node`의 outputs 줄을 다음으로 변경:
```python
        outputs = [state[k] for k in ("resume_eval", "github_eval", "portfolio_eval", "deploy_eval") if state.get(k)]
```

- [ ] **Step 5: 통과 확인**

Run: `python -m pytest tests/unit/test_consensus.py -v` → 전부 통과.
이어서 `python -m pytest tests/ -q -k "not test_returns_dict"` 회귀 확인.

- [ ] **Step 6: 커밋**

```bash
git add src/agent/state.py src/agent/consensus.py tests/unit/test_consensus.py
git commit -m "feat(agent): AppState deploy 필드 + 합의 노드에 deploy_eval 포함 (실증 소스)"
```

---

## Task 2: 배포 URL 평가자

**Files:** Create `src/agent/evaluators/deploy_eval.py` / Test `tests/unit/test_deploy_eval.py`

- [ ] **Step 1: 실패 테스트**

Create `tests/unit/test_deploy_eval.py`:
```python
# 배포 URL 평가자 — 순수 매칭 + 입력 가드 (네트워크 미호출)
from src.agent.evaluators.deploy_eval import (
    create_deploy_evaluator,
    _build_text,
    _skills_from_deploy,
)


class _FakeNeo4j:
    def __init__(self, skills):
        self._skills = skills

    def get_job_family_skills(self, job_family):
        return self._skills


def test_no_url_empty():
    node = create_deploy_evaluator(_FakeNeo4j(["React"]))
    out = node({"deploy_url": None, "job_family": "Frontend Engineer"})
    assert out["deploy_eval"]["skills"] == []


def test_build_text_combines_html_and_headers_lowercased():
    text = _build_text("<div>Built with NEXT.js</div>", {"X-Powered-By": "Next.js", "Server": "Vercel"})
    assert "next.js" in text and "vercel" in text


def test_skills_from_deploy_matches_vocab_and_marks_verified_source():
    text = _build_text("<script src='/_next/static/chunk.js'></script> uses react and tailwind", {"server": "vercel"})
    skills = _skills_from_deploy(text, vocab=["React", "Tailwind CSS", "Java"])
    by = {s["skill"]: s for s in skills}
    assert "React" in by and "Tailwind CSS" in by and "Java" not in by
    assert all(s["source"] == "deploy" for s in skills)
    assert "작동" in by["React"]["evidence"]
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/unit/test_deploy_eval.py -v` → FAIL (ModuleNotFound).

- [ ] **Step 3: 구현**

Create `src/agent/evaluators/deploy_eval.py`:
```python
# 배포 URL을 fetch해 작동 실증 + 프론트 기술을 추출하는 평가자 (웹 modality)
from __future__ import annotations

from typing import TYPE_CHECKING, Callable

import httpx

from src.agent.evaluators.github_eval import _word_match, _keywords_for

if TYPE_CHECKING:
    from src.agent.state import AppState
    from src.storage.neo4j_client import Neo4jClient


def _build_text(html: str, headers: dict) -> str:
    """HTML 본문 + 응답 헤더를 매칭용 소문자 텍스트로 합친다."""
    header_text = " ".join(f"{k} {v}" for k, v in headers.items())
    return f"{html} {header_text}".lower()


def _skills_from_deploy(text: str, vocab: list[str]) -> list[dict]:
    """직군 스킬 어휘를 배포 텍스트에 단어경계+별칭 매칭한다 (source=deploy → 실증)."""
    skills: list[dict] = []
    for skill in vocab:
        if any(_word_match(kw, text) for kw in _keywords_for(skill)):
            skills.append({
                "skill": skill,
                "evidence": f"배포 URL 작동 확인 — {skill} 사용 흔적",
                "source": "deploy",
                "level_hint": "실무",
            })
    return skills


def create_deploy_evaluator(neo4j: "Neo4jClient") -> Callable[["AppState"], dict]:
    """배포 URL 평가자 팩토리. 작동하는 배포에서 직군 스킬을 코드 외부 근거로 확인한다."""
    def evaluate(state: "AppState") -> dict:
        url = state.get("deploy_url")
        if not url:
            return {"deploy_eval": {"skills": []}}

        vocab = neo4j.get_job_family_skills(state.get("job_family") or "")
        if not vocab:
            print(f"[deploy_eval] 직군 스킬 어휘 없음 (job_family={state.get('job_family')!r})")
            return {"deploy_eval": {"skills": []}}

        try:
            resp = httpx.get(url, timeout=10, follow_redirects=True,
                             headers={"User-Agent": "Mozilla/5.0 (job-skill-analyzer)"})
            resp.raise_for_status()
        except Exception as e:
            print(f"[deploy_eval] URL fetch 실패 (미작동/접근불가): {e}")
            return {"deploy_eval": {"skills": []}}

        text = _build_text(resp.text, dict(resp.headers))
        return {"deploy_eval": {"skills": _skills_from_deploy(text, vocab)}}

    return evaluate
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/unit/test_deploy_eval.py -v` → 3 passed.

- [ ] **Step 5: 커밋**

```bash
git add src/agent/evaluators/deploy_eval.py tests/unit/test_deploy_eval.py
git commit -m "feat(agent): 배포 URL 평가자 (작동 실증 + HTML/헤더 기술 매칭, source=deploy)"
```

---

## Task 3: 그래프 배선

**Files:** Modify `src/agent/supervisor.py` / Test `tests/unit/test_evaluator_dispatch.py`(추가), `tests/integration/test_agent.py`(수정)

- [ ] **Step 1: 실패 테스트 — 디스패처가 deploy_url에 반응**

`tests/unit/test_evaluator_dispatch.py` 끝에 추가:
```python
def test_deploy_url_dispatches_deploy():
    sends = evaluator_dispatch({"resume_skills": [], "github_url": None,
                                "pdf_path": None, "resume_text": None,
                                "portfolio_path": None, "deploy_url": "https://x.com"})
    assert "deploy_eval" in [s.node for s in sends]
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/unit/test_evaluator_dispatch.py::test_deploy_url_dispatches_deploy -v` → FAIL.

- [ ] **Step 3: 디스패처에 deploy 분기 추가**

`src/agent/supervisor.py`의 `evaluator_dispatch`에서 portfolio 분기 다음에 추가:
```python
    if state.get("deploy_url"):
        sends.append(Send("deploy_eval", state))
```

- [ ] **Step 4: 그래프에 deploy_eval 노드 등록**

`create_supervisor_graph` 안에서:
(a) import 추가(다른 평가자 import 근처):
```python
    from src.agent.evaluators.deploy_eval import create_deploy_evaluator
```
(b) 인스턴스 생성(`portfolio_eval = create_portfolio_evaluator(openai_client)` 다음 줄):
```python
    deploy_eval = create_deploy_evaluator(neo4j)
```
(c) 노드 등록(`workflow.add_node("portfolio_eval", portfolio_eval)` 다음 줄):
```python
    workflow.add_node("deploy_eval", deploy_eval)
```
(d) 디스패처 타겟 목록 교체 — `add_conditional_edges(START, evaluator_dispatch, [...])`:
```python
    workflow.add_conditional_edges(START, evaluator_dispatch,
                                   ["resume_eval", "github_eval", "portfolio_eval", "deploy_eval"])
```
(e) deploy_eval → consensus 엣지(`workflow.add_edge("portfolio_eval", "consensus")` 다음 줄):
```python
    workflow.add_edge("deploy_eval", "consensus")
```

- [ ] **Step 5: run_supervisor/run_analysis에 deploy_url 추가**

`run_supervisor` 시그니처에 `portfolio_path` 다음(neo4j 앞)에 추가:
```python
    deploy_url: str | None = None,
```
`run_supervisor`의 initial dict에서 `"portfolio_path": portfolio_path,` 다음 줄에 추가:
```python
        "deploy_url": deploy_url,
```
그리고 `run_supervisor`의 `"resume_eval": None, "github_eval": None, "portfolio_eval": None, "consensus": None, "fit_result": None,` 줄을 다음으로 교체:
```python
        "resume_eval": None, "github_eval": None, "portfolio_eval": None, "deploy_eval": None, "consensus": None, "fit_result": None,
```
`run_analysis`의 initial dict에서 `"portfolio_path": None,` 다음 줄에 추가:
```python
        "deploy_url": None,
```
그리고 `run_analysis`의 `"resume_eval": None, "github_eval": None, "portfolio_eval": None, "consensus": None, "fit_result": None,` 줄을 다음으로 교체:
```python
        "resume_eval": None, "github_eval": None, "portfolio_eval": None, "deploy_eval": None, "consensus": None, "fit_result": None,
```

- [ ] **Step 6: 디스패처 테스트 통과**

Run: `python -m pytest tests/unit/test_evaluator_dispatch.py -v` → 전부 통과.

- [ ] **Step 7: 통합 테스트 — 그래프에 deploy_eval 노드**

`tests/integration/test_agent.py`의 `test_graph_has_v3_nodes`의 노드 검사 루프에 `"deploy_eval"` 추가:
```python
        for n in ("resume_eval", "github_eval", "portfolio_eval", "deploy_eval", "consensus", "synthesizer", "critic"):
            assert n in names, f"'{n}' 누락"
```

- [ ] **Step 8: 회귀 확인**

Run: `python -m pytest tests/ -q -k "not test_returns_dict"` → 전부 통과.

- [ ] **Step 9: 커밋**

```bash
git add src/agent/supervisor.py tests/unit/test_evaluator_dispatch.py tests/integration/test_agent.py
git commit -m "feat(agent): 그래프에 deploy 평가자 배선 (디스패처·노드·run_supervisor)"
```

---

## Task 4: 스모크 + progress

- [ ] **Step 1: 실제 배포 URL 스모크**

작동하는 배포 URL을 `DEPLOY_URL`로 둔다(프론트 기술이 드러나는 사이트, 예: Next.js/React 앱). Run:
```bash
python -c "
from dotenv import load_dotenv
load_dotenv('/Users/leegahee/workspace/pj1/.env', override=True)
from src.storage.neo4j_client import Neo4jClient
from src.agent.evaluators.deploy_eval import create_deploy_evaluator
node = create_deploy_evaluator(Neo4jClient())
out = node({'deploy_url': 'DEPLOY_URL', 'job_family': 'Software Engineer'})
skills = out['deploy_eval']['skills']
print('검출 스킬 수:', len(skills))
for s in skills: print(' -', s['skill'], '|', s['source'], '|', s['evidence'][:50])
"
```
Expected: 예외 없이 완료. 작동 URL이면 프론트 기술(React/Next.js 등)이 `source:deploy`로 검출. 미작동 URL이면 빈 결과 + `[deploy_eval]` 로그.

- [ ] **Step 2: 교차검증 확인 (deploy + 다른 소스)**

deploy에서 나온 스킬이 consensus에서 Verified가 되는지(또는 github와 겹치면 강한 검증) 확인. Run:
```bash
python -c "
from dotenv import load_dotenv
load_dotenv('/Users/leegahee/workspace/pj1/.env', override=True)
from src.agent.consensus import build_consensus
# deploy 단독 → Verified
con = build_consensus([{'skills':[{'skill':'React','evidence':'배포','source':'deploy','level_hint':'실무'}]}])
print('deploy 단독 React:', con['React']['verification'])   # Verified 기대
"
```
Expected: `Verified`.

- [ ] **Step 3: progress.md 갱신 + 커밋**

`progress.md`에 `## [2026-06-12] 배포 URL 평가자 (v3 단계3)` 섹션 추가(작업 절차/발생 문제/해결·검증 3단). 그 후:
```bash
git add progress.md
git commit -m "docs: 배포 URL 평가자 진행 기록 — 4개 소스 설계 완성"
```

---

## Self-Review

**Spec coverage:** 설계 §4-2 (HTML/헤더 fetch→Task2, 작동 실증=200 OK→Task2 fetch, source=deploy→Verified→consensus 기존, GitHub와 교차="코드+작동"→consensus가 둘 다 Verified로 처리). vision 스크린샷은 범위 밖(MVP, 명시). ✅

**Placeholder scan:** 각 코드 step에 완전 코드. 스모크의 `DEPLOY_URL`은 실행 시 실제 URL로 치환(데이터). ✅

**Type consistency:** `_build_text(html, headers)`·`_skills_from_deploy(text, vocab)`·`create_deploy_evaluator(neo4j)` 시그니처가 Task2 구현·테스트에서 일치. `deploy_url`/`deploy_eval` 필드가 Task1(state)·Task3(dispatch/graph/run_supervisor)에서 일치. github의 `_word_match`/`_keywords_for` 재사용(기존). ✅

**알려진 의존:** httpx 설치됨. deploy_eval이 github_eval의 `_word_match`/`_keywords_for`를 import(형제 평가자 재사용 — DRY). consensus `_VERIFIABLE_SOURCES`에 deploy 이미 포함(변경 없음). 정직한 한계(백엔드·AI 미검출)는 설계대로 수용. 스모크엔 실제 작동 배포 URL 필요.
