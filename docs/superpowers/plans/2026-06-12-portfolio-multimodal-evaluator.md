# 포트폴리오 멀티모달 평가자 (v3 단계 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 포트폴리오 PDF를 vision(멀티모달)으로 분석하는 평가자를 추가해, 이력서·GitHub에 더해 "프로젝트 규모·역할·성과" 소스를 합의에 합친다.

**Architecture:** 기존 평가자 패턴(팩토리 → `evaluate(state)` → `{source_eval: {skills:[...]}}`)을 그대로 따른다. PyMuPDF로 PDF 페이지를 이미지로 렌더 → gpt-4o-mini vision으로 페이지별 스킬 추출(앞 8페이지) → 정규화 중복제거 → `source:"portfolio"`로 consensus에 합류. 합의 노드는 portfolio를 비검증 소스로 이미 처리(단독 Claimed, 2+ 소스면 Corroborated).

**Tech Stack:** PyMuPDF(fitz), pdfplumber, OpenAI gpt-4o-mini vision, 기존 `normalize_skill` 재사용.

**설계 문서:** `docs/superpowers/specs/2026-06-11-agent-v3-fit-assessment-design.md` §4-1

---

## 사전 지식 (기존 코드)

- 평가자 계약: `{"<source>_eval": {"skills": [{skill, evidence, source, level_hint}]}}`. resume_eval=`"resume"`, github_eval=`"github"`. portfolio는 `"portfolio"`.
- `src/agent/consensus.py`: `build_consensus`가 source별 증거를 합치고 `_VERIFIABLE_SOURCES={"github","deploy"}`로 Verified 판정. portfolio는 비검증 → 단독 Claimed, 2+ 소스면 Corroborated. `create_consensus_node`의 `consensus_node`가 `for k in ("resume_eval","github_eval")`로 평가자 결과를 모음(여기에 portfolio_eval 추가 필요).
- `src/agent/state.py`: AppState에 `pdf_path`(이력서)·`github_url`·`resume_text` 입력 필드, `resume_eval`·`github_eval`·`consensus`·`fit_result` 평가 필드.
- `src/agent/supervisor.py`: `evaluator_dispatch(state)`가 입력에 있는 소스만 `Send`. `create_supervisor_graph`가 평가자 노드 등록 + `add_conditional_edges(START, evaluator_dispatch, [...])` + 각 평가자→consensus 엣지. `run_supervisor`/`run_analysis`가 초기 state dict 구성(평가 필드 None 초기화 2곳: ~258, ~298줄).
- 평가자 팩토리는 lazy import 패턴(함수 안에서 무거운 의존성 import).
- PyMuPDF는 **현재 미설치** → requirements 추가 + 설치 필요.

---

## Task 1: 의존성 + AppState 필드 + 합의 노드 포함

**Files:** Modify `requirements.txt`, `src/agent/state.py`, `src/agent/consensus.py` / Test `tests/unit/test_consensus.py`(추가)

- [ ] **Step 1: PyMuPDF 설치 + requirements 추가**

Run: `pip install pymupdf`
Expected: 설치 성공.

`requirements.txt`에 한 줄 추가(파일 끝 또는 PDF 관련 줄 근처):
```
pymupdf>=1.24.0
```

- [ ] **Step 2: 실패 테스트 — 합의 노드가 portfolio_eval을 포함**

`tests/unit/test_consensus.py` 끝에 추가:
```python
def test_consensus_node_includes_portfolio():
    from src.agent.consensus import create_consensus_node
    node = create_consensus_node()
    state = {
        "resume_eval": {"skills": [{"skill": "Docker", "evidence": "a", "source": "resume", "level_hint": None}]},
        "portfolio_eval": {"skills": [{"skill": "Docker", "evidence": "b", "source": "portfolio", "level_hint": None}]},
    }
    out = node(state)["consensus"]
    # resume + portfolio 두 소스 → Corroborated
    assert out["Docker"]["verification"] == "Corroborated"
```

- [ ] **Step 3: 실패 확인**

Run: `python -m pytest tests/unit/test_consensus.py::test_consensus_node_includes_portfolio -v`
Expected: FAIL (portfolio_eval을 안 읽어 Docker가 Claimed).

- [ ] **Step 4: AppState 필드 추가**

`src/agent/state.py`에서 입력 필드(`pdf_path` 다음 줄)에 추가:
```python
    portfolio_path: str | None   # 포트폴리오 PDF 경로 (멀티모달 평가자 입력)
```
그리고 평가 필드(`github_eval` 다음 줄)에 추가:
```python
    portfolio_eval: dict | None
```

- [ ] **Step 5: 합의 노드가 portfolio_eval 포함**

`src/agent/consensus.py`의 `consensus_node`에서:
```python
        outputs = [state[k] for k in ("resume_eval", "github_eval", "portfolio_eval") if state.get(k)]
```

- [ ] **Step 6: 통과 확인**

Run: `python -m pytest tests/unit/test_consensus.py -v`
Expected: 전부 통과 (신규 1개 포함).

- [ ] **Step 7: 커밋**

```bash
git add requirements.txt src/agent/state.py src/agent/consensus.py tests/unit/test_consensus.py
git commit -m "feat(agent): AppState portfolio 필드 + 합의 노드에 portfolio_eval 포함 + PyMuPDF 의존성"
```

---

## Task 2: 포트폴리오 평가자 (vision)

**Files:** Create `src/agent/evaluators/portfolio_eval.py` / Test `tests/unit/test_portfolio_eval.py`

- [ ] **Step 1: 실패 테스트**

Create `tests/unit/test_portfolio_eval.py`:
```python
# 포트폴리오 평가자 — 순수 파싱·병합 + 입력 가드 (vision/LLM 미호출)
from unittest.mock import MagicMock
from src.agent.evaluators.portfolio_eval import (
    create_portfolio_evaluator,
    _skills_from_vision,
    _merge_skills,
)


def test_no_path_empty():
    node = create_portfolio_evaluator(MagicMock())
    out = node({"portfolio_path": None})
    assert out["portfolio_eval"]["skills"] == []


def test_skills_from_vision_maps_source_and_where():
    data = {"skills": [
        {"skill": "LangGraph", "evidence": "멀티에이전트 다이어그램", "where": "diagram"},
        {"skill": "FastAPI", "evidence": "API 서버 스크린샷", "where": "screenshot"},
        {"not_skill": 1},          # skill 없는 항목은 무시
    ]}
    skills = _skills_from_vision(data)
    assert {s["skill"] for s in skills} == {"LangGraph", "FastAPI"}
    assert all(s["source"] == "portfolio" for s in skills)
    assert "diagram" in next(s["evidence"] for s in skills if s["skill"] == "LangGraph")


def test_merge_skills_dedupes_by_normalized_name():
    alls = [
        {"skill": "react.js", "evidence": "1p", "source": "portfolio", "level_hint": None},
        {"skill": "React", "evidence": "3p", "source": "portfolio", "level_hint": None},  # 정규화 시 중복
        {"skill": "Docker", "evidence": "2p", "source": "portfolio", "level_hint": None},
    ]
    merged = _merge_skills(alls)
    names = [s["skill"] for s in merged]
    assert names == ["react.js", "Docker"]   # 첫 등장(react.js) 유지, React 제거
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/unit/test_portfolio_eval.py -v`
Expected: FAIL (ModuleNotFound).

- [ ] **Step 3: 구현**

Create `src/agent/evaluators/portfolio_eval.py`:
```python
# 포트폴리오 PDF를 vision으로 분석해 프로젝트 스킬 증거를 추출하는 평가자 (멀티모달 modality)
from __future__ import annotations

import base64
import json
from typing import TYPE_CHECKING, Callable

from src.extraction.normalizer import normalize_skill

if TYPE_CHECKING:
    from src.agent.state import AppState

_VISION_MODEL = "gpt-4o-mini"
_MAX_PAGES = 8

_VISION_PROMPT = """이 포트폴리오 페이지(이미지)에서 지원자가 실제로 사용/구현한 기술 스킬을 추출하세요.
다이어그램의 박스·화살표·라벨, 스크린샷, 본문 텍스트를 모두 근거로 보세요.
보조 텍스트(있으면):
{page_text}

아래 JSON만 출력하세요 (코드펜스 없이):
{{"skills": [{{"skill": "LangGraph", "evidence": "멀티에이전트 RAG 다이어그램에 StateGraph 노드", "where": "diagram"}}]}}

규칙:
- 실제 사용/구현 근거가 페이지에 있는 기술만. 추측 금지.
- where 는 text/diagram/screenshot 중 근거가 나온 곳.
- 연차·학위·소프트스킬·도메인 지식 제외."""


def _render_pdf_pages(path: str, max_pages: int) -> list[bytes]:
    """PDF 앞 max_pages 페이지를 PNG 바이트로 렌더한다 (PyMuPDF, poppler 의존성 없음)."""
    import fitz  # PyMuPDF

    doc = fitz.open(path)
    pages: list[bytes] = []
    for i, page in enumerate(doc):
        if i >= max_pages:
            break
        pix = page.get_pixmap(dpi=220)
        pages.append(pix.tobytes("png"))
    doc.close()
    return pages


def _page_texts(path: str, n: int) -> list[str]:
    """pdfplumber로 페이지별 보조 텍스트 (실패 시 빈 문자열)."""
    try:
        import pdfplumber

        texts: list[str] = []
        with pdfplumber.open(path) as pdf:
            for i, page in enumerate(pdf.pages):
                if i >= n:
                    break
                texts.append(page.extract_text() or "")
        return texts
    except Exception as e:
        print(f"[portfolio_eval] 텍스트 추출 실패: {e}")
        return [""] * n


def _skills_from_vision(data: dict) -> list[dict]:
    """vision JSON 응답을 평가자 계약 형식으로 변환한다."""
    skills: list[dict] = []
    for item in data.get("skills", []):
        if not isinstance(item, dict) or not item.get("skill"):
            continue
        where = item.get("where", "")
        ev = item.get("evidence", "")
        evidence = f"[포트폴리오/{where}] {ev}".strip() if where else ev
        skills.append({"skill": item["skill"], "evidence": evidence,
                       "source": "portfolio", "level_hint": None})
    return skills


def _merge_skills(all_skills: list[dict]) -> list[dict]:
    """정규화명 기준 중복 제거 (첫 등장 유지)."""
    seen: set[str] = set()
    merged: list[dict] = []
    for s in all_skills:
        key = normalize_skill(s["skill"])
        if key in seen:
            continue
        seen.add(key)
        merged.append(s)
    return merged


def create_portfolio_evaluator(openai_client) -> Callable[["AppState"], dict]:
    """포트폴리오 평가자 팩토리. PDF 페이지를 vision으로 분석해 스킬 증거를 추출한다."""
    def evaluate(state: "AppState") -> dict:
        path = state.get("portfolio_path")
        if not path:
            return {"portfolio_eval": {"skills": []}}
        try:
            images = _render_pdf_pages(path, _MAX_PAGES)
        except Exception as e:
            print(f"[portfolio_eval] PDF 렌더 실패: {e}")
            return {"portfolio_eval": {"skills": []}}

        texts = _page_texts(path, len(images))
        all_skills: list[dict] = []
        for i, img in enumerate(images):
            b64 = base64.b64encode(img).decode()
            page_text = (texts[i] if i < len(texts) else "")[:2000]
            try:
                resp = openai_client.chat.completions.create(
                    model=_VISION_MODEL, temperature=0, max_tokens=1500,
                    messages=[{"role": "user", "content": [
                        {"type": "text", "text": _VISION_PROMPT.format(page_text=page_text)},
                        {"type": "image_url",
                         "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "high"}},
                    ]}],
                )
                raw = (resp.choices[0].message.content or "").strip()
                raw = raw.replace("```json", "").replace("```", "").strip()
                all_skills += _skills_from_vision(json.loads(raw))
            except Exception as e:
                print(f"[portfolio_eval] {i + 1}페이지 분석 실패: {e}")
        return {"portfolio_eval": {"skills": _merge_skills(all_skills)}}

    return evaluate
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/unit/test_portfolio_eval.py -v`
Expected: 3 passed.

- [ ] **Step 5: 커밋**

```bash
git add src/agent/evaluators/portfolio_eval.py tests/unit/test_portfolio_eval.py
git commit -m "feat(agent): 포트폴리오 평가자 (PDF vision → 프로젝트 스킬 증거)"
```

---

## Task 3: 그래프 배선 (디스패처·노드·run_supervisor)

**Files:** Modify `src/agent/supervisor.py` / Test `tests/unit/test_evaluator_dispatch.py`(추가)

- [ ] **Step 1: 실패 테스트 — 디스패처가 portfolio_path에 반응**

`tests/unit/test_evaluator_dispatch.py` 끝에 추가:
```python
def test_portfolio_path_dispatches_portfolio():
    sends = evaluator_dispatch({"resume_skills": [], "github_url": None,
                                "pdf_path": None, "resume_text": None,
                                "portfolio_path": "p.pdf"})
    assert "portfolio_eval" in [s.node for s in sends]
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/unit/test_evaluator_dispatch.py::test_portfolio_path_dispatches_portfolio -v`
Expected: FAIL (portfolio_eval Send 없음).

- [ ] **Step 3: 디스패처에 portfolio 분기 추가**

`src/agent/supervisor.py`의 `evaluator_dispatch`에서 github 분기 다음에 추가:
```python
    if state.get("portfolio_path"):
        sends.append(Send("portfolio_eval", state))
```

- [ ] **Step 4: 그래프에 portfolio_eval 노드 등록**

`create_supervisor_graph` 안에서:

(a) import 추가 (다른 평가자 import 근처):
```python
    from src.agent.evaluators.portfolio_eval import create_portfolio_evaluator
```
(b) 인스턴스 생성 (`github_eval = create_github_evaluator(neo4j)` 다음 줄):
```python
    portfolio_eval = create_portfolio_evaluator(openai_client)
```
(c) 노드 등록 (`workflow.add_node("github_eval", github_eval)` 다음 줄):
```python
    workflow.add_node("portfolio_eval", portfolio_eval)
```
(d) 디스패처 타겟 목록에 추가 — `add_conditional_edges(START, evaluator_dispatch, [...])`의 리스트를:
```python
    workflow.add_conditional_edges(START, evaluator_dispatch,
                                   ["resume_eval", "github_eval", "portfolio_eval"])
```
(e) portfolio_eval → consensus 엣지 (`workflow.add_edge("github_eval", "consensus")` 다음 줄):
```python
    workflow.add_edge("portfolio_eval", "consensus")
```

- [ ] **Step 5: run_supervisor/run_analysis에 portfolio_path 추가**

`run_supervisor` 시그니처에 `resume_skills` 다음(neo4j 앞)에 추가:
```python
    portfolio_path: str | None = None,
```
`run_supervisor`의 initial dict에서 `"pdf_path": pdf_path,` 다음 줄에 추가:
```python
        "portfolio_path": portfolio_path,
```
그리고 같은 dict의 `"resume_eval": None, "github_eval": None, ...` 줄을 다음으로 교체:
```python
        "resume_eval": None, "github_eval": None, "portfolio_eval": None, "consensus": None, "fit_result": None,
```
`run_analysis`의 initial dict에서도 `"pdf_path": None,` 다음 줄에 추가:
```python
        "portfolio_path": None,
```
그리고 `run_analysis`의 `"resume_eval": None, "github_eval": None, ...` 줄을 다음으로 교체:
```python
        "resume_eval": None, "github_eval": None, "portfolio_eval": None, "consensus": None, "fit_result": None,
```

- [ ] **Step 6: 디스패처 테스트 통과**

Run: `python -m pytest tests/unit/test_evaluator_dispatch.py -v`
Expected: 전부 통과 (신규 1개 포함).

- [ ] **Step 7: 통합 테스트 — 그래프에 portfolio_eval 노드**

`tests/integration/test_agent.py`의 `test_graph_has_v3_nodes`의 노드 집합에 `"portfolio_eval"` 추가:
```python
        for n in ("resume_eval", "github_eval", "portfolio_eval", "consensus", "synthesizer", "critic"):
            assert n in names, f"'{n}' 누락"
```

- [ ] **Step 8: 회귀 확인**

Run: `python -m pytest tests/ -q -k "not test_returns_dict"`
Expected: 전부 통과.

- [ ] **Step 9: 커밋**

```bash
git add src/agent/supervisor.py tests/unit/test_evaluator_dispatch.py tests/integration/test_agent.py
git commit -m "feat(agent): 그래프에 portfolio 평가자 배선 (디스패처·노드·run_supervisor)"
```

---

## Task 4: 스모크 + progress

- [ ] **Step 1: 실제 포트폴리오 PDF 스모크**

포트폴리오 PDF 경로를 `PORTFOLIO_PDF`로 둔다(없으면 이력서 PDF로 "vision이 에러 없이 도는지"만 확인). Run:
```bash
python -c "
from dotenv import load_dotenv
load_dotenv('/Users/leegahee/workspace/pj1/.env', override=True)
import os
from openai import OpenAI
from src.agent.evaluators.portfolio_eval import create_portfolio_evaluator
node = create_portfolio_evaluator(OpenAI(api_key=os.getenv('OPENAI_API_KEY')))
out = node({'portfolio_path': 'PORTFOLIO_PDF경로'})
skills = out['portfolio_eval']['skills']
print('추출 스킬 수:', len(skills))
for s in skills[:15]:
    print(' -', s['skill'], '|', s['evidence'][:60])
"
```
Expected: 예외 없이 완료. 포트폴리오 PDF면 프로젝트 스킬이 `source:portfolio`로 추출됨. 로그에 `[portfolio_eval]` (실패 시).

- [ ] **Step 2: 전체 그래프 스모크 (이력서+포폴 → Corroborated 확인)**

이력서 PDF + 포폴 PDF를 함께 넣어 겹치는 스킬이 Corroborated로 올라가는지 확인(포폴 PDF 있을 때). Run:
```bash
python -c "
from dotenv import load_dotenv
load_dotenv('/Users/leegahee/workspace/pj1/.env', override=True)
import os, uuid
from openai import OpenAI
from src.storage.neo4j_client import Neo4jClient
from src.storage.chroma_client import ChromaClient
from src.agent.supervisor import create_supervisor_graph
neo4j = Neo4jClient()
g = create_supervisor_graph(neo4j, ChromaClient(), OpenAI(api_key=os.getenv('OPENAI_API_KEY')))
initial = {'job_family':'Software Engineer','owner':'테스트','pdf_path':'이력서.pdf','github_url':None,
  'portfolio_path':'PORTFOLIO_PDF경로','resume_skills':[],'resume_text':None,'messages':[],'iteration':0,
  'seen_source_ids':[],'coach_messages':[],'coach_iteration':0,'skill_trends':None,'gap_result':None,
  'github_result':None,'coaching_result':None,'final_report':None,'plan':None,'replan_count':0,
  'profile_result':None,'retrieved_context':[],'market_result':None,'critic_report':None,
  'resume_eval':None,'github_eval':None,'portfolio_eval':None,'consensus':None,'fit_result':None}
res = g.invoke(initial, {'configurable':{'thread_id':str(uuid.uuid4())}})
con = res.get('consensus') or {}
print('Corroborated 수:', sum(1 for v in con.values() if v['verification']=='Corroborated'))
print('portfolio 증거 포함 스킬:', [k for k,v in con.items() if any(e['source']=='portfolio' for e in v['evidences'])][:10])
"
```
Expected: 예외 없이 완료. 이력서·포폴 겹치는 스킬이 Corroborated.

- [ ] **Step 3: progress.md 갱신 + 커밋**

`progress.md`에 `## [2026-06-12] 포트폴리오 멀티모달 평가자 (v3 단계2)` 섹션 추가(작업 절차/발생 문제/해결·검증 3단). 그 후:
```bash
git add progress.md
git commit -m "docs: 포트폴리오 멀티모달 평가자 진행 기록"
```

---

## Self-Review

**Spec coverage:** 설계 §4-1 (PyMuPDF dpi=220→Task2, pdfplumber 보조텍스트→Task2, gpt-4o-mini vision detail=high→Task2, 페이지별 호출+병합→Task2, where 근거출처→`_skills_from_vision`). 합의 비검증 소스 처리→기존 build_consensus(Task1 노드 포함). ✅

**Placeholder scan:** 각 코드 step에 완전 코드. 스모크의 `PORTFOLIO_PDF경로`/`이력서.pdf`는 실행 시 사용자 경로로 치환(데이터 입력, 코드 아님). ✅

**Type consistency:** 평가자 출력 `{"portfolio_eval":{"skills":[{skill,evidence,source,level_hint}]}}`이 Task2 생성·Task1 consensus 소비에서 일치. `_skills_from_vision`/`_merge_skills`/`create_portfolio_evaluator(openai_client)` 시그니처가 Task2 구현·테스트에서 일치. `portfolio_path`/`portfolio_eval` 필드가 Task1(state)·Task3(dispatch/graph/run_supervisor)에서 일치. ✅

**알려진 의존:** PyMuPDF 설치 필요(Task1 Step1). vision 경로는 단위 테스트 대신 스모크로 검증(API·이미지 필요). 스모크엔 실제 포트폴리오 PDF 경로 필요(없으면 이력서 PDF로 에러무결성만). 합의 노드 `_VERIFIABLE_SOURCES`에 portfolio 없음 → 단독 Claimed(설계 의도, 변경 없음).
