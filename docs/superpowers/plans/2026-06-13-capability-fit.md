# 역량 기반 적합도 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 적합도를 "직군 평균 × 개별 스킬"에서 "핵심 역량 충족"으로 바꾸고, 역방향 직군 추천 + 역량별 검증 등급을 더한다(합격자 이력서 30%→83% 검증 완료).

**Architecture:** 순수 모듈 `capability.py`(스킬→역량 매핑·직군 핵심 역량·충족 계산). `run_supervisor`가 그래프 실행 후 결과 state에서 보유 스킬·consensus를 읽어 역량 정보를 `final_report`에 후처리로 덧붙임(노드 시그니처 불변, neo4j 접근 용이). ReportResponse·프론트가 노출.

**Tech Stack:** Python(순수 함수), Neo4j(직군별 REQUIRES 집계), OpenAI(미매핑 스킬 1회 백필), 바닐라 JS.

**확인된 기존 구조:**
- 평가자 state: `{"<src>_eval": {"skills": [{"skill","evidence","source","level_hint"}]}}` (resume/github/portfolio/deploy 동일).
- `consensus = {정규화스킬명: {"verification": "Verified"|"Corroborated"|"Claimed", "evidences": [...]}}`.
- `run_supervisor`(supervisor.py) 끝: `result = graph.invoke(...)` 후 `return result.get("final_report") or {}`. `result`에 `resume_eval`·`consensus` 등 전체 state 있음. `neo4j` 인자 보유.
- `normalize_skill(raw)`(normalizer.py), `neo4j.list_job_families()`(10개), `neo4j.execute_query`.
- `ReportResponse`(schemas.py), `_map_final_report`(portfolio.py), `renderReport`(web/app.js).

---

### Task 1: capability.py — 역량 사전 + skills_to_capabilities

**Files:**
- Create: `src/analysis/capability.py`
- Test: `tests/unit/test_capability.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/unit/test_capability.py`:
```python
# 스킬→역량 매핑 검증 (정규화·계열 흡수·미지 제외)
from src.analysis.capability import skills_to_capabilities


def test_maps_known_skills():
    caps = skills_to_capabilities(["MariaDB", "Spring", "React.js", "Docker", "AWS"])
    assert {"database", "backend_fw", "frontend", "container", "cloud"} <= caps


def test_alias_and_normalize():
    # MariaDB·SQLite → database (계열 흡수), React.js → React → frontend
    assert "database" in skills_to_capabilities(["SQLite"])
    assert "frontend" in skills_to_capabilities(["React.js"])


def test_unknown_excluded():
    assert skills_to_capabilities(["완전미지스킬xyz"]) == set()
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/unit/test_capability.py -v`
Expected: FAIL — 모듈 없음(ImportError).

- [ ] **Step 3: capability.py 구현**

`src/analysis/capability.py`:
```python
# 스킬을 역량(capability)으로 묶어 직군 핵심 역량 충족을 따지는 모듈
from __future__ import annotations

import json
from pathlib import Path

from src.extraction.normalizer import normalize_skill

# 역량 시드 사전 (수동 — 명백한 매핑은 사전이 정답). 키=역량, 값=스킬 소문자 집합.
SEED_CAPABILITIES: dict[str, set[str]] = {
    "language": {"python", "java", "javascript", "typescript", "go", "c++", "c#", "kotlin", "php", "scala", "ruby", "c", "rust"},
    "backend_fw": {"spring", "spring boot", "django", "express", "fastapi", "node.js", "flask", ".net", "rails", "nestjs"},
    "frontend": {"react", "vue.js", "angular", "next.js", "svelte", "html", "css", "tailwind css", "bootstrap", "redux"},
    "database": {"postgresql", "mysql", "mariadb", "sqlite", "mongodb", "redis", "oracle", "cassandra", "dynamodb", "mybatis", "ibatis"},
    "cloud": {"aws", "gcp", "azure", "naver cloud platform"},
    "container": {"docker", "kubernetes"},
    "cicd": {"jenkins", "github actions", "gitlab ci", "circleci", "argocd", "ci/cd"},
    "data_eng": {"spark", "hadoop", "kafka", "airflow", "snowflake", "dbt", "etl", "databricks", "bigquery"},
    "ml_ai": {"pytorch", "tensorflow", "llms", "ml", "ai", "langchain", "langgraph", "scikit-learn", "ai/ml"},
    "mobile": {"android", "ios", "swift", "react native", "flutter", "swiftui", "uikit"},
    "security": {"siem", "edr", "threat intelligence", "cissp", "penetration testing"},
}

# 백필 스크립트(Task 2)가 채우는 미매핑 스킬 분류
_JSON_PATH = Path(__file__).resolve().parents[2] / "data" / "seeds" / "skill_capabilities.json"

_skill2cap: dict[str, str] | None = None


def load_capabilities() -> dict[str, str]:
    """skill_lower → capability. 시드 + JSON 백필 병합(시드 우선)."""
    m = {s: cap for cap, ss in SEED_CAPABILITIES.items() for s in ss}
    if _JSON_PATH.exists():
        try:
            for s, cap in json.loads(_JSON_PATH.read_text(encoding="utf-8")).items():
                m.setdefault(s.lower(), cap)  # 시드가 우선
        except Exception:
            pass
    return m


def _cap_map() -> dict[str, str]:
    global _skill2cap
    if _skill2cap is None:
        _skill2cap = load_capabilities()
    return _skill2cap


def skills_to_capabilities(skills: list[str]) -> set[str]:
    """보유 스킬 목록을 역량 집합으로. 정규화·계열 흡수, 미지/other 제외."""
    m = _cap_map()
    caps: set[str] = set()
    for s in skills:
        cap = m.get(s.lower()) or m.get(normalize_skill(s).lower())
        if cap and cap != "other":
            caps.add(cap)
    return caps
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/unit/test_capability.py -v`
Expected: 3 passed

- [ ] **Step 5: 커밋**
```bash
git add src/analysis/capability.py tests/unit/test_capability.py
git commit -m "feat(analysis): 역량 사전 + skills_to_capabilities (계열 흡수)"
```

---

### Task 2: 미매핑 스킬 LLM 백필

**Files:**
- Create: `scripts/backfill_capabilities.py`
- Create(실행 산출): `data/seeds/skill_capabilities.json`

- [ ] **Step 1: 백필 스크립트 작성**

`scripts/backfill_capabilities.py`:
```python
# Neo4j의 모든 Skill 중 시드에 없는 것을 11개 역량으로 LLM 일괄 분류 → JSON 저장
import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from openai import OpenAI

from src.analysis.capability import SEED_CAPABILITIES, _JSON_PATH
from src.storage.neo4j_client import Neo4jClient

CAPS = list(SEED_CAPABILITIES.keys()) + ["other"]


def main() -> None:
    neo4j = Neo4jClient()
    rows = neo4j.execute_query("MATCH (s:Skill) RETURN s.name AS name")
    seeded = {s for ss in SEED_CAPABILITIES.values() for s in ss}
    todo = sorted({r["name"] for r in rows if r["name"] and r["name"].lower() not in seeded})
    print(f"미매핑 스킬 {len(todo)}개 분류")

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    result: dict[str, str] = {}
    batch = 60
    for i in range(0, len(todo), batch):
        chunk = todo[i:i + batch]
        prompt = (
            f"다음 기술 스킬들을 아래 역량 중 하나로 분류해 JSON(스킬명:역량)으로만 답하세요.\n"
            f"역량: {', '.join(CAPS)}\n"
            f"애매하면 other. 스킬: {json.dumps(chunk, ensure_ascii=False)}"
        )
        raw = client.chat.completions.create(
            model="gpt-4o-mini", temperature=0,
            messages=[{"role": "user", "content": prompt}],
        ).choices[0].message.content
        raw = raw.replace("```json", "").replace("```", "").strip()
        try:
            for k, v in json.loads(raw).items():
                result[k.lower()] = v if v in CAPS else "other"
        except json.JSONDecodeError:
            print(f"  [skip] 배치 {i} 파싱 실패")
        print(f"  {min(i + batch, len(todo))}/{len(todo)}")

    _JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    _JSON_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"저장: {_JSON_PATH} ({len(result)}개)")
    neo4j.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 실행 (OPENAI/NEO4J 키 필요, 1회 배치)**

Run: `python -m scripts.backfill_capabilities`
Expected: `저장: .../skill_capabilities.json (N개)` 출력, JSON 파일 생성.
키 없으면 이 Step은 건너뛰고 시드 사전만으로 동작(테스트는 Task 1·3이 시드로 통과).

- [ ] **Step 3: 결과 표본 검수 + 커밋**

생성된 `data/seeds/skill_capabilities.json`을 열어 명백한 오분류 표본 점검(예: `Terraform`이 `other`면 손으로 `cicd`/`container`로 수정 가능).
```bash
git add scripts/backfill_capabilities.py data/seeds/skill_capabilities.json
git commit -m "feat(analysis): 미매핑 스킬 역량 백필 스크립트 + 결과"
```

---

### Task 3: 직군 핵심 역량 · 충족 · 역방향 추천 · 검증 결합

**Files:**
- Modify: `src/analysis/capability.py`
- Test: `tests/unit/test_capability.py` (추가), `tests/integration/test_capability_fit.py`

- [ ] **Step 1: 단위 테스트 추가**

`tests/unit/test_capability.py` 끝에 추가:
```python
from src.analysis.capability import capability_fit, capability_evidence


def test_capability_fit_ratio():
    core = ["language", "frontend", "database", "container", "cloud", "backend_fw"]
    resume = {"language", "database", "container", "cloud", "backend_fw"}  # frontend 빠짐
    r = capability_fit(resume, core)
    assert r["fit"] == 0.83
    assert r["unmet"] == ["frontend"]
    assert set(r["met"]) == resume


def test_capability_evidence_grades():
    owned = [{"skill": "Spring", "source": "github"}, {"skill": "AWS", "source": "resume"}]
    consensus = {"Spring": {"verification": "Verified"}, "AWS": {"verification": "Claimed"}}
    ev = capability_evidence(owned, consensus, met_caps={"backend_fw", "cloud"})
    by_cap = {e["capability"]: e["tools"] for e in ev}
    assert by_cap["backend_fw"][0] == {"skill": "Spring", "verification": "Verified"}
    assert by_cap["cloud"][0] == {"skill": "AWS", "verification": "Claimed"}
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/unit/test_capability.py -v`
Expected: FAIL — `capability_fit`·`capability_evidence` 미정의.

- [ ] **Step 3: 함수 구현 (capability.py에 추가)**

`src/analysis/capability.py` 끝에 추가:
```python
_CORE_QUERY = """
MATCH (:JobFamily {name: $job_family})<-[:INSTANCE_OF]-(jp)-[:REQUIRES]->(s:Skill)
RETURN s.name AS skill, count(DISTINCT jp) AS w
"""


def job_family_core_capabilities(neo4j, job_family: str, n: int = 6) -> list[str]:
    """직군 REQUIRES 스킬을 역량으로 환산, 요구 공고 가중 상위 n개."""
    rows = neo4j.execute_query(_CORE_QUERY, job_family=job_family)
    m = _cap_map()
    capw: dict[str, int] = {}
    for r in rows:
        cap = m.get((r["skill"] or "").lower()) or m.get(normalize_skill(r["skill"] or "").lower())
        if cap and cap != "other":
            capw[cap] = capw.get(cap, 0) + int(r["w"] or 0)
    return [c for c, _ in sorted(capw.items(), key=lambda x: -x[1])[:n]]


def capability_fit(resume_caps: set[str], core_caps: list[str]) -> dict:
    """핵심 역량 충족률 + 충족/미충족 목록."""
    met = [c for c in core_caps if c in resume_caps]
    unmet = [c for c in core_caps if c not in resume_caps]
    return {
        "fit": round(len(met) / len(core_caps), 2) if core_caps else 0.0,
        "met": met,
        "unmet": unmet,
    }


def recommend_families(neo4j, resume_caps: set[str], families: list[str]) -> list[dict]:
    """직군별 충족률을 계산해 내림차순 정렬 — 역방향 직군 추천."""
    out = []
    for fam in families:
        core = job_family_core_capabilities(neo4j, fam)
        out.append({"job_family": fam, **capability_fit(resume_caps, core)})
    return sorted(out, key=lambda x: -x["fit"])


def capability_evidence(owned: list[dict], consensus: dict, met_caps: set[str]) -> list[dict]:
    """충족된 역량별로, 그 역량을 충족시킨 보유 도구 + 검증 등급(consensus)."""
    m = _cap_map()
    by_cap: dict[str, list[dict]] = {}
    for item in owned:
        sk = item.get("skill") if isinstance(item, dict) else None
        if not sk:
            continue
        cap = m.get(sk.lower()) or m.get(normalize_skill(sk).lower())
        if cap in met_caps:
            grade = (consensus.get(normalize_skill(sk)) or {}).get("verification", "Claimed")
            by_cap.setdefault(cap, []).append({"skill": sk, "verification": grade})
    return [{"capability": c, "tools": ts} for c, ts in by_cap.items()]
```

- [ ] **Step 4: 단위 통과 + 통합 테스트 작성**

Run: `python -m pytest tests/unit/test_capability.py -v`
Expected: 모두 PASS

`tests/integration/test_capability_fit.py`:
```python
# 직군 핵심 역량·역방향 추천 — 실 Neo4j 필요
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=True)

from src.analysis.capability import (  # noqa: E402
    job_family_core_capabilities, recommend_families, skills_to_capabilities,
)
from src.storage.neo4j_client import Neo4jClient  # noqa: E402

requires_neo4j = pytest.mark.skipif(not os.getenv("NEO4J_URI"), reason="NEO4J_URI 필요")


@requires_neo4j
def test_se_core_has_backend_and_db():
    neo4j = Neo4jClient()
    core = job_family_core_capabilities(neo4j, "Software Engineer")
    assert "backend_fw" in core and "database" in core
    neo4j.close()


@requires_neo4j
def test_backend_resume_ranks_se_above_ai():
    neo4j = Neo4jClient()
    caps = skills_to_capabilities(["Java", "Spring", "MariaDB", "Docker", "AWS", "Jenkins"])
    rec = recommend_families(neo4j, caps, neo4j.list_job_families())
    rank = {r["job_family"]: i for i, r in enumerate(rec)}
    assert rank["Software Engineer"] < rank["AI/LLM Engineer"]
    neo4j.close()
```

- [ ] **Step 5: 통합 통과 + 커밋**

Run: `python -m pytest tests/integration/test_capability_fit.py -v` (키 있으면 PASS, 없으면 SKIP)
Run: `python -m pytest tests/unit/ -q` → 전체 PASS
```bash
git add src/analysis/capability.py tests/unit/test_capability.py tests/integration/test_capability_fit.py
git commit -m "feat(analysis): 직군 핵심 역량·충족·역방향 추천·검증 결합"
```

---

### Task 4: run_supervisor 후처리 + API 노출

**Files:**
- Modify: `src/agent/supervisor.py` (`run_supervisor` 반환부)
- Modify: `src/api/schemas.py` (`ReportResponse`)
- Modify: `src/api/routers/portfolio.py` (`_map_final_report`)
- Test: `tests/unit/test_api_mapping.py` (추가)

- [ ] **Step 1: run_supervisor가 역량 정보를 final_report에 후처리로 추가**

`src/agent/supervisor.py`의 `run_supervisor` 끝부분 — 현재:
```python
    result = graph.invoke(initial, config)
    return result.get("final_report") or {}
```
를 다음으로 교체:
```python
    result = graph.invoke(initial, config)
    final = result.get("final_report") or {}
    if neo4j and final and not final.get("error"):
        from src.analysis.capability import (
            capability_evidence, capability_fit, job_family_core_capabilities,
            recommend_families, skills_to_capabilities,
        )
        owned: list[dict] = []
        for k in ("resume_eval", "github_eval", "portfolio_eval", "deploy_eval"):
            owned += (result.get(k) or {}).get("skills", [])
        names = [it["skill"] for it in owned if isinstance(it, dict) and it.get("skill")]
        resume_caps = skills_to_capabilities(names)
        core = job_family_core_capabilities(neo4j, job_family)
        final["capability_fit"] = {"job_family": job_family, "core": core, **capability_fit(resume_caps, core)}
        final["recommended_families"] = recommend_families(neo4j, resume_caps, neo4j.list_job_families())[:5]
        final["capability_evidence"] = capability_evidence(owned, result.get("consensus") or {}, set(final["capability_fit"]["met"]))
    return final
```

- [ ] **Step 2: 실패하는 매핑 테스트 추가**

`tests/unit/test_api_mapping.py` 끝에 추가:
```python
def test_map_final_report_passes_capability():
    from src.api.routers.portfolio import _map_final_report
    final = {
        "gap": {"match_rate": 0.5},
        "verification": {"counts": {}, "skills": []},
        "coaching": {"summary": "s", "suggestions": []},
        "capability_fit": {"job_family": "Software Engineer", "core": ["backend_fw"], "fit": 1.0, "met": ["backend_fw"], "unmet": []},
        "recommended_families": [{"job_family": "Software Engineer", "fit": 1.0, "met": ["backend_fw"], "unmet": []}],
        "capability_evidence": [{"capability": "backend_fw", "tools": [{"skill": "Spring", "verification": "Verified"}]}],
    }
    resp = _map_final_report("rid", "owner", "Software Engineer", final)
    assert resp.capability_fit["fit"] == 1.0
    assert resp.recommended_families[0]["job_family"] == "Software Engineer"
    assert resp.capability_evidence[0]["capability"] == "backend_fw"
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `python -m pytest tests/unit/test_api_mapping.py::test_map_final_report_passes_capability -v`
Expected: FAIL — `ReportResponse`에 필드 없음.

- [ ] **Step 4: 스키마 + 매핑 구현**

`src/api/schemas.py`의 `ReportResponse`에 `trace: dict | None = None` 옆에 추가:
```python
    capability_fit: dict | None = None
    recommended_families: list[dict] = Field(default_factory=list)
    capability_evidence: list[dict] = Field(default_factory=list)
```

`src/api/routers/portfolio.py`의 `_map_final_report` 반환 `ReportResponse(...)`에 `trace=final.get("trace"),` 옆에 추가:
```python
        capability_fit=final.get("capability_fit"),
        recommended_families=final.get("recommended_families") or [],
        capability_evidence=final.get("capability_evidence") or [],
```

- [ ] **Step 5: 테스트 통과 + 커밋**

Run: `python -m pytest tests/unit/ -q` → 전체 PASS
```bash
git add src/agent/supervisor.py src/api/schemas.py src/api/routers/portfolio.py tests/unit/test_api_mapping.py
git commit -m "feat(agent/api): 역량 적합도·역방향 추천·검증 결합을 리포트에 노출"
```

---

### Task 5: 프론트 — 역량 충족 맵 + 역방향 추천 + 검증

**Files:**
- Modify: `web/app.js` (`renderReport`)
- Modify: `web/style.css` (역량 칩 스타일)

- [ ] **Step 1: style.css에 역량 칩 스타일 추가 (파일 끝)**

`web/style.css` 끝에 추가:
```css
.cap { display:inline-block; padding:3px 10px; margin:3px; border-radius:8px; font-size:.82rem; border:1px solid var(--line); }
.cap.met { background:#eef2ff; border-color:var(--accent); }
.cap.unmet { background:#fef2f2; color:#b91c1c; border-color:#fecaca; }
.fam-row { display:flex; justify-content:space-between; padding:6px 0; border-bottom:1px solid var(--line); font-size:.9rem; }
.cap-ev { font-size:.82rem; color:var(--muted); padding:3px 0; }
```

- [ ] **Step 2: renderReport에 역량 섹션 추가**

`web/app.js`의 `renderReport(d)`에서, 적합도 게이지가 들어있는 `.metrics` 블록을 **역량 충족 맵으로 교체**한다. 현재 `$("result").innerHTML = \`` 템플릿의 `<div class="metrics">...</div>` 부분(적합도/신뢰도 두 metric)을 다음으로 대체:
```javascript
    ${renderCapability(d)}
    <div class="metrics">
      <div class="metric"><div>신뢰도</div><div class="big">${d.confidence_level ? esc(d.confidence_level) : "-"}</div>
        <div class="prio">Verified ${counts.Verified || 0} · Corroborated ${counts.Corroborated || 0} · Claimed ${counts.Claimed || 0}</div></div>
    </div>
```
그리고 `renderReport` 함수 **위**에 헬퍼 추가:
```javascript
function renderCapability(d) {
  const cf = d.capability_fit;
  if (!cf) return "";
  const pct = Math.round((cf.fit || 0) * 100);
  const met = (cf.met || []).map((c) => `<span class="cap met">${esc(c)} ✓</span>`).join("");
  const unmet = (cf.unmet || []).map((c) => `<span class="cap unmet">${esc(c)} ✗</span>`).join("");
  const ev = (d.capability_evidence || [])
    .map((e) => `<div class="cap-ev">${esc(e.capability)}: ${(e.tools || []).map((t) => `${esc(t.skill)}(${esc(t.verification)})`).join(", ")}</div>`)
    .join("");
  const rec = (d.recommended_families || [])
    .map((r) => `<div class="fam-row"><span>${esc(r.job_family)}</span><span>${Math.round((r.fit || 0) * 100)}%</span></div>`)
    .join("");
  return `
    <h3>${esc(cf.job_family || "")} 핵심 역량 충족 ${pct}%</h3>
    <div>${met}${unmet}</div>
    ${ev ? `<h3>역량별 근거 (검증 등급)</h3>${ev}` : ""}
    ${rec ? `<h3>당신에게 맞는 직군</h3>${rec}` : ""}
  `;
}
```

- [ ] **Step 3: 문법 체크 + 수동 확인**

Run: `node --check web/app.js` → 출력 없음
Run: `python -m pytest tests/unit/test_static_serving.py -q` → PASS
수동: `uvicorn src.api.main:app --port 8055` 후 이력서 분석 → 결과에 "핵심 역량 충족 N%(met/unmet 칩)" + "역량별 근거(검증 등급)" + "당신에게 맞는 직군" 표시.

- [ ] **Step 4: 커밋**
```bash
git add web/app.js web/style.css
git commit -m "feat(web): 역량 충족 맵 + 역방향 직군 추천 + 검증 등급 표시"
```

---

## 비결정 사항(구현 중 확정)

- 핵심 역량 수 N(기본 6).
- 백필 JSON 검수에서 명백한 오분류는 손으로 교정 가능(시드 우선이라 시드에 추가해도 됨).
- 기존 `match_rate`(gap)는 당분간 신뢰도 카드와 함께 잔존 — 역량 맵이 주 적합도 표현. 완전 제거는 2차.
