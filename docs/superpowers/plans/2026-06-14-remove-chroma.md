# Chroma 제거 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 효과 미검증 벡터 DB(Chroma)를 제거하고, 공고 원문 근거를 Neo4j `JobPosting` 속성으로 옮긴다.

**Architecture:** 공고 요건 원문(`required_section`/`preferred_section`)을 원천 JSON에서 `JobPosting` 노드에 백필. `verify_skills`·`verify_suggestion`이 Chroma 대신 그 노드 텍스트에서 스킬 키워드 문장을 근거로 추출. `vector_search` 도구 제거. ChromaClient·관련 의존 전부 삭제.

**Tech Stack:** Neo4j(Cypher), Python.

**확인된 시그니처/구조:**
- `create_tools(neo4j, chroma)`(tools.py:32) → `create_tools(neo4j)`. `create_coach_tools(chroma)`(tools.py:261) → `create_coach_tools(neo4j)`. `create_nodes(gap_tools, neo4j, chroma)`(nodes.py:233) → `create_nodes(gap_tools, neo4j)`. `create_supervisor_graph(neo4j, chroma, openai_client)`(supervisor.py:119) → `create_supervisor_graph(neo4j, openai_client)`.
- `neo4j.get_postings_requiring_skill(skill, limit)`(neo4j_client.py:392) → `list[source_id]`. `MERGE (p:JobPosting {source_id})`(neo4j_client.py:67) 패턴 존재.
- github_eval에 `_word_match(kw, text_lower)`·`_keywords_for(skill)` 모듈 함수.
- 원천 `data/processed/jobs_filtered.json`(321건): `id`(=source_id)·`required_section`·`preferred_section`.
- chroma 참조: stats.py(6,8,38,49,67), deps.py(7,15,16), main.py(23,31,39), schemas.py(148 chroma_chunks), supervisor.py(20,130,131,132,335,339,342), nodes.py(15,236), ragas_eval.py(259,265,267), tools.py(verify_skills·vector_search·verify_suggestion).

---

### Task 1: JobPosting 원문 백필

**Files:**
- Modify: `src/storage/neo4j_client.py` (두 메서드 추가)
- Create: `scripts/backfill_posting_text.py`
- Test: `tests/integration/test_posting_sections.py`

- [ ] **Step 1: neo4j_client에 메서드 2개 추가**

`src/storage/neo4j_client.py`의 클래스 안(아무 메서드 옆)에 추가:
```python
    def set_posting_sections(self, source_id: str, required: str, preferred: str) -> None:
        """공고 노드에 요건 원문(필수·우대)을 속성으로 저장한다."""
        try:
            self.execute_query(
                "MATCH (p:JobPosting {source_id: $source_id}) "
                "SET p.required_section = $required, p.preferred_section = $preferred",
                source_id=source_id, required=required or "", preferred=preferred or "",
            )
        except Exception as e:
            print(f"[neo4j] 공고 원문 저장 실패({source_id}): {e}")

    def get_posting_sections(self, source_ids: list[str]) -> list[dict]:
        """source_id 목록의 공고 요건 원문을 가져온다."""
        try:
            return self.execute_query(
                "MATCH (p:JobPosting) WHERE p.source_id IN $ids "
                "RETURN p.source_id AS source_id, p.company AS company, "
                "p.required_section AS required_section, p.preferred_section AS preferred_section",
                ids=source_ids,
            )
        except Exception as e:
            print(f"[neo4j] 공고 원문 조회 실패: {e}")
            return []
```

- [ ] **Step 2: 백필 스크립트 작성**

`scripts/backfill_posting_text.py`:
```python
# 원천 jobs_filtered.json의 요건 원문을 JobPosting 노드 속성으로 백필
import json
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from src.storage.neo4j_client import Neo4jClient

SRC = Path(__file__).resolve().parents[1] / "data" / "processed" / "jobs_filtered.json"


def main() -> None:
    recs = json.loads(SRC.read_text(encoding="utf-8"))
    if isinstance(recs, dict):
        recs = recs.get("jobs") or list(recs.values())[0]
    neo4j = Neo4jClient()
    n = 0
    for r in recs:
        sid = str(r.get("id") or "")
        if not sid:
            continue
        neo4j.set_posting_sections(sid, r.get("required_section") or "", r.get("preferred_section") or "")
        n += 1
    print(f"백필 완료: {n}개 공고")
    neo4j.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: 실행 (NEO4J 키 필요)**

Run: `python -m scripts.backfill_posting_text`
Expected: `백필 완료: 321개 공고` (키 없으면 스킵, 후속 통합 테스트도 스킵).

- [ ] **Step 4: 통합 테스트**

`tests/integration/test_posting_sections.py`:
```python
# JobPosting 원문 속성 백필·조회 — 실 Neo4j 필요
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=True)

from src.storage.neo4j_client import Neo4jClient  # noqa: E402

requires_neo4j = pytest.mark.skipif(not os.getenv("NEO4J_URI"), reason="NEO4J_URI 필요")


@requires_neo4j
def test_posting_sections_present():
    neo4j = Neo4jClient()
    rows = neo4j.execute_query(
        "MATCH (p:JobPosting) WHERE p.required_section IS NOT NULL RETURN count(p) AS c"
    )
    assert rows[0]["c"] > 0  # 백필됨
    sample = neo4j.execute_query("MATCH (p:JobPosting) RETURN p.source_id AS sid LIMIT 1")[0]["sid"]
    secs = neo4j.get_posting_sections([sample])
    assert secs and "required_section" in secs[0]
    neo4j.close()
```

Run: `python -m pytest tests/integration/test_posting_sections.py -v` (키 있으면 PASS, 없으면 SKIP)

- [ ] **Step 5: 커밋**
```bash
git add src/storage/neo4j_client.py scripts/backfill_posting_text.py tests/integration/test_posting_sections.py
git commit -m "feat(storage): JobPosting 요건 원문 속성 + 백필 스크립트"
```

---

### Task 2: verify_skills·verify_suggestion을 Neo4j 텍스트로, vector_search 제거

**Files:**
- Modify: `src/agent/tools.py`
- Test: `tests/unit/test_verify_skills_neo4j.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/unit/test_verify_skills_neo4j.py`:
```python
# verify_skills가 Neo4j 텍스트에서 스킬 근거 문장을 뽑는지 (DB mock)
from unittest.mock import MagicMock

from src.agent.tools import create_tools


def _gap_tool(name):
    neo4j = MagicMock()
    neo4j.get_postings_requiring_skill.return_value = ["job1"]
    neo4j.get_posting_sections.return_value = [
        {"source_id": "job1", "company": "Acme",
         "required_section": "Strong Python skills required. Docker experience preferred.",
         "preferred_section": ""}
    ]
    tools = create_tools(neo4j)
    return next(t for t in tools if t.name == name)


def test_verify_skills_pulls_sentence():
    vs = _gap_tool("verify_skills")
    res = vs.invoke({"skill_names": ["Python"]})
    ev = res["Python"]["evidence"]
    assert ev and "Python" in ev[0]["text"]
    assert ev[0]["company"] == "Acme"


def test_vector_search_removed():
    neo4j = MagicMock()
    names = [t.name for t in create_tools(neo4j)]
    assert "vector_search" not in names
    assert "verify_skills" in names
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/unit/test_verify_skills_neo4j.py -v`
Expected: FAIL — `create_tools`가 2인자(neo4j, chroma)라 1인자 호출 시 TypeError 또는 vector_search 잔존.

- [ ] **Step 3: tools.py 수정**

`src/agent/tools.py` 상단 import 영역에 추가:
```python
import re
from src.agent.evaluators.github_eval import _keywords_for, _word_match
```
모듈 레벨 헬퍼 추가(`create_tools` 위):
```python
def _evidence_sentence(skill: str, text: str) -> str:
    """텍스트에서 스킬 키워드가 든 문장을 근거로. 없으면 앞부분."""
    kws = _keywords_for(skill)
    for sent in re.split(r"[.\n•]", text or ""):
        if any(_word_match(kw, sent.lower()) for kw in kws):
            return sent.strip()[:300]
    return (text or "").strip()[:300]
```
`create_tools(neo4j: "Neo4jClient", chroma: "ChromaClient") -> list:` 시그니처를 `create_tools(neo4j: "Neo4jClient") -> list:`로 변경. 그 안의 `verify_skills` 함수 본문을 다음으로 교체:
```python
    @tool
    def verify_skills(
        skill_names: Annotated[list[str], "근거를 확인할 부족 스킬 목록 (최대 5개)"],
    ) -> dict:
        """여러 부족 스킬의 공고 근거를 한 번에 조회한다(Neo4j 요건 원문 기반)."""
        results: dict = {}
        try:
            for skill in skill_names[:5]:
                posting_ids = neo4j.get_postings_requiring_skill(skill, limit=3)
                evidence = []
                if posting_ids:
                    for s in neo4j.get_posting_sections(posting_ids):
                        text = f"{s.get('required_section') or ''} {s.get('preferred_section') or ''}"
                        sent = _evidence_sentence(skill, text)
                        if sent:
                            evidence.append({"source_id": s["source_id"], "company": s.get("company") or "", "text": sent})
                if evidence:
                    results[skill] = {"method": "neo4j_text", "posting_count": len(posting_ids), "evidence": evidence}
                else:
                    results[skill] = {"method": "graph_only", "posting_count": len(posting_ids), "evidence": []}
        except Exception as e:
            return {"error": str(e)}
        return results
```
`vector_search` 도구 함수 전체를 **삭제**한다. `create_tools` 반환 줄을 다음으로(vector_search 제외):
```python
    return [gap_analysis, verify_skills, skill_unlock, posting_trend,
            market_insights, graph_query, ask_human]
```

`create_coach_tools(chroma: "ChromaClient") -> list:` 시그니처를 `create_coach_tools(neo4j: "Neo4jClient") -> list:`로 변경. `verify_suggestion` 본문을 다음으로 교체:
```python
        try:
            ids = neo4j.get_postings_requiring_skill(skill, limit=2)
            if not ids:
                return {"skill": skill, "evidence": "", "company": "",
                        "note": "해당 스킬의 공고 텍스트 없음 — 제안을 더 일반적으로 작성하세요."}
            secs = neo4j.get_posting_sections(ids)
            s = secs[0] if secs else {}
            text = (s.get("required_section") or s.get("preferred_section") or "")[:400]
            return {"skill": skill, "evidence": text, "company": s.get("company") or ""}
        except Exception as e:
            return {"skill": skill, "evidence": "", "company": "", "error": str(e)}
```
(verify_suggestion의 기존 `chroma.search` 블록 전체를 위로 교체. 이후 줄에 남는 `results[0]["original_text"]` 참조가 있으면 함께 제거.)

`vector_search` 관련: `src/agent/nodes.py`의 gap 프롬프트에서 `vector_search` 언급 줄 삭제. `src/agent/supervisor.py` `_make_tools_node`의 `if tc["name"] == "vector_search"` dedup 분기 삭제(verify_skills 분기는 유지).

- [ ] **Step 4: 통과 + 커밋**

Run: `python -m pytest tests/unit/test_verify_skills_neo4j.py -v` → PASS
```bash
git add src/agent/tools.py src/agent/nodes.py src/agent/supervisor.py tests/unit/test_verify_skills_neo4j.py
git commit -m "feat(agent): verify_skills·verify_suggestion을 Neo4j 텍스트로, vector_search 제거"
```

---

### Task 3: chroma 인자 제거 (시그니처 정리)

**Files:**
- Modify: `src/agent/nodes.py`, `src/agent/supervisor.py`, `src/evaluation/ragas_eval.py`

- [ ] **Step 1: create_nodes에서 chroma 인자 제거**

`src/agent/nodes.py:233` `create_nodes` 시그니처에서 `chroma: "ChromaClient",` 파라미터 줄 삭제, line 15의 `from src.storage.chroma_client import ChromaClient` TYPE_CHECKING import 삭제(다른 데서 안 쓰면). 함수 본문에서 `chroma` 사용처 없음(도구가 캡처) — 있으면 보고.

- [ ] **Step 2: create_supervisor_graph 정리**

`src/agent/supervisor.py`:
- line 20 `from src.storage.chroma_client import ChromaClient` 삭제.
- line 119 `def create_supervisor_graph(neo4j, chroma, openai_client):` → `def create_supervisor_graph(neo4j, openai_client):`.
- line 130 `create_tools(neo4j, chroma)` → `create_tools(neo4j)`.
- line 131 `create_coach_tools(chroma)` → `create_coach_tools(neo4j)`.
- line 132 `create_nodes(gap_tools, neo4j, chroma)` → `create_nodes(gap_tools, neo4j)`.
- `__main__`(line 335,339,342): `from ...chroma_client` + `chroma = ChromaClient()` 삭제, `create_supervisor_graph(neo4j, openai_client)`.

- [ ] **Step 3: ragas_eval __main__ 정리**

`src/evaluation/ragas_eval.py` line 259,265,267: `from ...chroma_client import ChromaClient` + `chroma = ChromaClient()` 삭제, `create_supervisor_graph(neo4j, openai_client)`.

- [ ] **Step 4: import 확인 + 커밋**

Run: `python -c "import src.agent.supervisor; import src.evaluation.ragas_eval; print('OK')"`
Expected: `OK`
```bash
git add src/agent/nodes.py src/agent/supervisor.py src/evaluation/ragas_eval.py
git commit -m "refactor(agent): create_supervisor_graph/create_nodes에서 chroma 인자 제거"
```

---

### Task 4: API·스키마·UI에서 chroma 제거

**Files:**
- Modify: `src/api/main.py`, `src/api/deps.py`, `src/api/routers/stats.py`, `src/api/schemas.py`, `web/observe.js`

- [ ] **Step 1: main.py lifespan + 그래프 빌드**

`src/api/main.py`:
- line 23 `from src.storage.chroma_client import ChromaClient` 삭제.
- line 31 `app.state.chroma = ChromaClient()` 삭제.
- line 39 `create_supervisor_graph(app.state.neo4j, app.state.chroma, app.state.openai)` → `create_supervisor_graph(app.state.neo4j, app.state.openai)`.

- [ ] **Step 2: deps.py**

`src/api/deps.py`: line 7 `from ...chroma_client import ChromaClient` + line 15-16 `get_chroma` 함수 삭제.

- [ ] **Step 3: stats.py + schemas.py**

`src/api/routers/stats.py`:
- line 6 `from src.api.deps import get_chroma, get_neo4j` → `from src.api.deps import get_neo4j`.
- line 8 `from src.storage.chroma_client import ChromaClient` 삭제.
- `stats` 핸들러에서 `chroma: ChromaClient = Depends(get_chroma)` 파라미터 삭제, `chunks = chroma.count()` 블록 삭제, `chroma_chunks=chunks` 인자 삭제.

`src/api/schemas.py:148`: `StatsResponse`의 `chroma_chunks: int | None = None` 필드 삭제.

- [ ] **Step 4: observe.js 데이터 탭**

`web/observe.js`의 `loadData`에서 벡터 청크 표시 줄 삭제:
```javascript
      <div class="stat-row"><span>벡터 청크</span><span>${d.chroma_chunks ?? "—"}</span></div>
```
이 한 줄을 제거.

- [ ] **Step 5: 통과 + 커밋**

Run: `python -m pytest tests/unit/ -q` (chroma mock 쓰던 테스트는 Task 5에서 정리 — 여기선 import 깨짐만 없으면 진행)
Run: `node --check web/observe.js` → 출력 없음
```bash
git add src/api/main.py src/api/deps.py src/api/routers/stats.py src/api/schemas.py web/observe.js
git commit -m "refactor(api): chroma·chroma_chunks 제거 (deps·lifespan·stats·UI)"
```

---

### Task 5: ChromaClient 삭제 + 의존·테스트 정리 + 회귀

**Files:**
- Delete: `src/storage/chroma_client.py`
- Modify: `src/storage/__init__.py`, `src/ingestion/pipeline.py`, `requirements.txt`, chroma mock 쓰던 테스트들

- [ ] **Step 1: 잔존 chroma 참조 전수 확인**

Run: `grep -rn "chroma\|Chroma\|ChromaClient" src/ tests/ web/ | grep -v "test 정리 예정"`
남은 참조(아래)를 처리:
- `src/storage/__init__.py`: ChromaClient export 줄 삭제.
- `src/ingestion/pipeline.py`: `ChromaClient`/`ingest_posting`/`step_ingest_chroma` 호출 삭제(공고 적재는 Neo4j만).
- `src/analysis/gap_analyzer.py`·`src/analysis/coach.py`·`src/portfolio/github_connector.py`·`src/extraction/normalizer.py`: chroma import가 있으면 미사용 여부 확인 후 삭제(대부분 주석/미사용).
- 테스트: `tests/unit/test_gap_analyzer.py`·`tests/unit/test_gap_core_required.py`·`tests/integration/test_stats.py`·`tests/integration/test_agent.py`에서 chroma mock 인자 제거(`create_tools(neo4j, MagicMock())` → `create_tools(neo4j)`, `create_supervisor_graph(...,chroma,...)` → 2인자, stats 테스트의 chroma_chunks assert 삭제).

- [ ] **Step 2: ChromaClient 삭제 + requirements**

```bash
git rm src/storage/chroma_client.py
```
`requirements.txt`에서 `chromadb`·`sentence-transformers`·`rank_bm25` 줄 삭제(CrossEncoder·BM25는 Chroma 전용이었음).

- [ ] **Step 3: 전체 회귀**

Run: `python -c "import src.api.main; print('import OK')"`
Expected: `import OK` (ModuleNotFoundError 없음)
Run: `python -m pytest tests/unit/ -q`
Expected: 모두 PASS
Run: `grep -rn "import.*chroma\|ChromaClient\|\.chroma" src/ tests/`
Expected: 출력 없음(완전 제거)

- [ ] **Step 4: 커밋**
```bash
git add -A
git commit -m "refactor: ChromaClient 삭제 + chromadb/sentence-transformers 의존 제거"
```

---

## 비결정 사항(구현 중 확정)

- `rank_bm25`/`sentence-transformers` 제거 시 다른 사용처 없는지 grep로 재확인(없으면 제거).
- `pipeline.py`의 Chroma 적재 단계 제거 후, 공고 적재가 Neo4j만으로 완결되는지 확인.
- gap_analyzer.py·coach.py의 chroma 참조가 v1 잔재(미사용)면 삭제, 실사용이면 보고.
