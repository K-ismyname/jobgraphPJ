# API를 v3 에이전트로 재배선 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** FastAPI `/portfolio` 엔드포인트가 구 직접 파이프라인 대신 **v3 그래프(`run_supervisor`)** 를 호출해, 이력서·GitHub·배포 URL 다중 소스로 2축(적합도+신뢰도)+검증 리포트를 반환하게 한다.

**Architecture:** lifespan에서 v3 그래프를 1회 빌드해 `app.state.graph`로 주입. `/analyze`가 업로드된 이력서 텍스트 + github_url + deploy_url로 `run_supervisor`를 백그라운드 실행하고, `final_report`(gap·verification·coaching)를 새 응답 스키마로 매핑. 포트폴리오(vision)는 리소스 부담으로 이번 범위 제외.

**Tech Stack:** FastAPI, Pydantic, 기존 `run_supervisor`·`create_supervisor_graph`·`Neo4jClient.list_job_families`.

**범위:** 이력서(업로드 텍스트) + github_url + deploy_url. 포트폴리오 vision은 제외(별도). jobs 라우터는 미변경.

---

## 사전 지식 (기존 코드)

- `src/api/main.py`: `lifespan`이 `app.state.neo4j/chroma/openai/uploads/reports` 세팅. 라우터 등록.
- `src/api/deps.py`: `get_neo4j/get_chroma/get_openai/get_uploads/get_reports`가 `request.app.state.X` 반환.
- `src/api/routers/portfolio.py`: `/upload`(PDF→텍스트, uploads[report_id]=text), `/analyze`(background `_run_analysis`), `/report/{id}`(폴링), `/github`(구 confidence boost). `_run_analysis`가 구 `run_gap_analysis`·`generate_coaching` 호출.
- `src/api/schemas.py`: `AnalyzeRequest`(report_id, job_title, owner_name), `ReportResponse`(match_rate, have/missing/top_missing/suggestions — 구 형태), `GitHubRequest`/`GitHubUpdateResponse`, `GapSkillItem`, `SuggestionItem`.
- `src/agent/supervisor.py`: `create_supervisor_graph(neo4j, chroma, openai_client)`, `run_supervisor(graph, job_family, owner, pdf_path=, resume_text=, github_url=, deploy_url=, resume_skills=, neo4j=)`. neo4j 주면 job_family 검증, 무효면 `{"error":"invalid_job_family", "message", "valid_job_families"}` 반환. 입력 0개면 `{"error":"no_input", "message"}`. 정상이면 `final_report` 반환.
- `final_report = {"gap": {match_rate, confidence_level, advice, skills, ...}, "verification": {"counts": {Verified,Corroborated,Claimed}, "skills": [{skill, verification, sources}]}, "coaching": {"summary", "suggestions": [{target_section, missing_skill, original_text, rewritten_text, expected_impact, priority, verified}]}}`.
- `Neo4jClient.list_job_families() -> list[str]`(유효 직군).
- API 테스트는 없음(신규 추가).

---

## Task 1: 스키마 v3 교체

**Files:** Modify `src/api/schemas.py` / Test `tests/unit/test_api_schemas.py`

- [ ] **Step 1: 실패 테스트**

Create `tests/unit/test_api_schemas.py`:
```python
# v3 API 스키마 검증
from src.api.schemas import AnalyzeRequest, ReportResponse, VerificationItem, SuggestionItem


def test_analyze_request_v3_fields():
    req = AnalyzeRequest(report_id="r1", job_family="Software Engineer",
                         github_url="https://github.com/x/y", deploy_url="https://x.com")
    assert req.job_family == "Software Engineer"
    assert req.github_url and req.deploy_url
    # 선택 입력은 None 허용
    req2 = AnalyzeRequest(report_id="r1", job_family="Software Engineer")
    assert req2.github_url is None and req2.deploy_url is None


def test_report_response_v3_shape():
    r = ReportResponse(
        report_id="r1", status="done", owner="x", job_family="Software Engineer",
        match_rate=0.44, confidence_level="high", advice="좋음",
        verification_counts={"Verified": 2, "Corroborated": 0, "Claimed": 1},
        verified_skills=[VerificationItem(skill="React", verification="Verified", sources=["github"])],
        coaching_summary="요약",
        suggestions=[SuggestionItem(target_section="경력", missing_skill="K8s",
                                    rewritten_text="...", expected_impact="...", priority="high")],
    )
    assert r.match_rate == 0.44
    assert r.verified_skills[0].skill == "React"
    assert r.verification_counts["Verified"] == 2
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/unit/test_api_schemas.py -v`
Expected: FAIL (`VerificationItem` 없음, `AnalyzeRequest`에 job_family/github_url/deploy_url 없음, `ReportResponse` 필드 불일치).

- [ ] **Step 3: 스키마 교체**

`src/api/schemas.py`에서 Portfolio 섹션을 교체한다.

(a) `AnalyzeRequest`를 다음으로 교체:
```python
class AnalyzeRequest(BaseModel):
    report_id: str
    job_family: str = "AI/LLM Engineer"   # 유효 직군명 (Neo4j JobFamily)
    owner_name: str | None = None         # None이면 PDF에서 추출한 이름 사용
    github_url: str | None = None         # 선택 — 코드 검증
    deploy_url: str | None = None         # 선택 — 작동 실증
```

(b) `GitHubRequest`, `GitHubUpdateResponse`, `GapSkillItem` 클래스를 **삭제**.

(c) `SuggestionItem`에 `verified` 필드 추가(coach 출력 호환):
```python
class SuggestionItem(BaseModel):
    target_section: str
    missing_skill: str
    original_text: str | None = None
    rewritten_text: str
    expected_impact: str
    priority: Literal["high", "medium", "low"]
    verified: bool = False
```

(d) `VerificationItem` 추가 + `ReportResponse`를 v3 형태로 교체:
```python
class VerificationItem(BaseModel):
    skill: str
    verification: str               # Verified | Corroborated | Claimed
    sources: list[str]


class ReportResponse(BaseModel):
    report_id: str
    status: Literal["processing", "done", "error"]
    owner: str
    job_family: str
    # 적합도 축
    match_rate: float = 0.0
    # 신뢰도 축
    confidence_level: str | None = None      # high | medium | low
    advice: str | None = None
    verification_counts: dict[str, int] = Field(default_factory=dict)
    verified_skills: list[VerificationItem] = Field(default_factory=list)
    # 코칭
    coaching_summary: str | None = None
    suggestions: list[SuggestionItem] = Field(default_factory=list)
    error_detail: str | None = None
    generated_at: str | None = None
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/unit/test_api_schemas.py -v` → 2 passed.

- [ ] **Step 5: 커밋**

```bash
git add src/api/schemas.py tests/unit/test_api_schemas.py
git commit -m "feat(api): v3 스키마 — AnalyzeRequest(job_family/github/deploy) + 2축·검증 ReportResponse"
```

---

## Task 2: lifespan에서 v3 그래프 빌드 + 주입

**Files:** Modify `src/api/main.py`, `src/api/deps.py`

- [ ] **Step 1: lifespan에서 그래프 빌드**

`src/api/main.py`의 import에 추가:
```python
from src.agent.supervisor import create_supervisor_graph
```
`lifespan`의 startup 블록에서 `app.state.reports: dict = {}` 다음에 추가:
```python
    # v3 그래프는 1회 빌드해 재사용 (openai 키 없으면 None — /analyze가 503)
    app.state.graph = (
        create_supervisor_graph(app.state.neo4j, app.state.chroma, app.state.openai)
        if app.state.openai else None
    )
```

- [ ] **Step 2: deps에 get_graph 추가**

`src/api/deps.py` 끝에 추가:
```python
def get_graph(request: Request):
    """v3 supervisor 그래프 (openai 키 없으면 None)."""
    return request.app.state.graph
```

- [ ] **Step 3: import 확인 (앱 로드)**

Run: `python -c "import src.api.main"`
Expected: 예외 없음.

- [ ] **Step 4: 커밋**

```bash
git add src/api/main.py src/api/deps.py
git commit -m "feat(api): lifespan에서 v3 그래프 빌드 + get_graph 주입"
```

---

## Task 3: portfolio 라우터를 run_supervisor로 재배선

**Files:** Modify `src/api/routers/portfolio.py` / Test `tests/unit/test_api_mapping.py`

- [ ] **Step 1: 실패 테스트 — final_report → ReportResponse 매핑**

Create `tests/unit/test_api_mapping.py`:
```python
# final_report → v3 ReportResponse 매핑 (순수 함수)
from src.api.routers.portfolio import _map_final_report


def test_map_final_report():
    final = {
        "gap": {"match_rate": 0.44, "confidence_level": "high", "advice": "좋음"},
        "verification": {
            "counts": {"Verified": 1, "Corroborated": 0, "Claimed": 1},
            "skills": [
                {"skill": "React", "verification": "Verified", "sources": ["github", "deploy"]},
                {"skill": "Docker", "verification": "Claimed", "sources": ["resume"]},
            ],
        },
        "coaching": {"summary": "요약", "suggestions": [
            {"target_section": "경력", "missing_skill": "K8s", "rewritten_text": "...",
             "expected_impact": "...", "priority": "high", "verified": True},
        ]},
    }
    r = _map_final_report("r1", "지원자", "Software Engineer", final)
    assert r.status == "done" and r.match_rate == 0.44 and r.confidence_level == "high"
    assert r.verification_counts["Verified"] == 1
    assert [s.skill for s in r.verified_skills] == ["React", "Docker"]
    assert r.coaching_summary == "요약"
    assert r.suggestions[0].missing_skill == "K8s"


def test_map_final_report_tolerates_missing_fields():
    # 빈/부분 final_report도 안전하게 매핑
    r = _map_final_report("r1", "x", "Software Engineer", {})
    assert r.status == "done" and r.match_rate == 0.0
    assert r.verified_skills == [] and r.suggestions == []
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/unit/test_api_mapping.py -v` → FAIL (ImportError `_map_final_report`).

- [ ] **Step 3: 라우터 재작성**

Replace `src/api/routers/portfolio.py` 전체:
```python
# 포트폴리오 엔드포인트 — 업로드 → v3 다중소스 분석 → 리포트 폴링
from __future__ import annotations

import os
import tempfile
import uuid
from datetime import datetime, timezone

from openai import OpenAI
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile

from src.api.deps import get_graph, get_neo4j, get_openai, get_reports, get_uploads
from src.api.schemas import (
    AnalyzeAccepted,
    AnalyzeRequest,
    ReportResponse,
    SuggestionItem,
    UploadResponse,
    VerificationItem,
)
from src.agent.supervisor import run_supervisor
from src.portfolio.pdf_parser import extract_pdf_info
from src.storage.neo4j_client import Neo4jClient

router = APIRouter()

_MAX_PDF_BYTES = 10 * 1024 * 1024  # 10 MB
_SUGGESTION_FIELDS = ("target_section", "missing_skill", "original_text",
                      "rewritten_text", "expected_impact", "priority", "verified")


@router.post("/upload", response_model=UploadResponse)
async def upload_resume(
    file: UploadFile = File(...),
    uploads: dict = Depends(get_uploads),
) -> UploadResponse:
    """PDF 이력서 업로드. 텍스트 추출 후 report_id 반환."""
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(415, "PDF 파일만 업로드 가능합니다.")
    content = await file.read()
    if len(content) > _MAX_PDF_BYTES:
        raise HTTPException(413, "파일 크기는 10MB 이하여야 합니다.")
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name
    try:
        text, page_count = extract_pdf_info(tmp_path)
    except ValueError as e:
        raise HTTPException(422, str(e))
    finally:
        os.unlink(tmp_path)

    report_id = str(uuid.uuid4())
    uploads[report_id] = text
    name_hint = (text.split("\n")[0].strip()[:60]) if text else "Unknown"
    return UploadResponse(
        report_id=report_id, candidate_name_hint=name_hint,
        page_count=page_count, text_length=len(text), status="uploaded",
    )


@router.post("/analyze", response_model=AnalyzeAccepted)
async def analyze_portfolio(
    req: AnalyzeRequest,
    background_tasks: BackgroundTasks,
    uploads: dict = Depends(get_uploads),
    reports: dict = Depends(get_reports),
    neo4j: Neo4jClient = Depends(get_neo4j),
    graph=Depends(get_graph),
) -> AnalyzeAccepted:
    """v3 다중소스 분석 시작. 즉시 반환 후 백그라운드 처리."""
    if req.report_id not in uploads:
        raise HTTPException(404, "report_id를 찾을 수 없습니다. 먼저 /portfolio/upload를 호출하세요.")
    if graph is None:
        raise HTTPException(503, "분석 비활성화 — OPENAI_API_KEY가 필요합니다.")
    valid = neo4j.list_job_families()
    if valid and req.job_family not in valid:
        raise HTTPException(422, f"유효하지 않은 직군 '{req.job_family}'. 가능: {', '.join(valid)}")

    existing = reports.get(req.report_id)
    if existing and getattr(existing, "status", None) == "processing":
        raise HTTPException(409, "이미 분석 중입니다.")

    reports[req.report_id] = ReportResponse(
        report_id=req.report_id, status="processing",
        owner=req.owner_name or "분석 중", job_family=req.job_family,
    )
    background_tasks.add_task(
        _run_analysis,
        report_id=req.report_id, resume_text=uploads[req.report_id],
        job_family=req.job_family, owner_name=req.owner_name,
        github_url=req.github_url, deploy_url=req.deploy_url,
        graph=graph, neo4j=neo4j, reports=reports,
    )
    return AnalyzeAccepted(report_id=req.report_id, status="processing")


@router.get("/report/{report_id}", response_model=ReportResponse)
async def get_report(
    report_id: str,
    reports: dict = Depends(get_reports),
) -> ReportResponse:
    """분석 결과 조회. status=processing이면 재시도 권장."""
    report = reports.get(report_id)
    if report is None:
        raise HTTPException(404, "report_id를 찾을 수 없습니다.")
    return report


# ── 매핑 (순수) ────────────────────────────────────────────────
def _map_final_report(report_id: str, owner: str, job_family: str, final: dict) -> ReportResponse:
    """run_supervisor의 final_report를 v3 ReportResponse로 매핑한다."""
    gap = final.get("gap") or {}
    ver = final.get("verification") or {}
    coaching = final.get("coaching") if isinstance(final.get("coaching"), dict) else {}
    suggestions = []
    for s in (coaching.get("suggestions") or []):
        if isinstance(s, dict) and s.get("rewritten_text"):
            suggestions.append(SuggestionItem(**{k: s.get(k) for k in _SUGGESTION_FIELDS if k in s}))
    return ReportResponse(
        report_id=report_id, status="done", owner=owner, job_family=job_family,
        match_rate=gap.get("match_rate") or 0.0,
        confidence_level=gap.get("confidence_level"),
        advice=gap.get("advice"),
        verification_counts=ver.get("counts") or {},
        verified_skills=[VerificationItem(**s) for s in (ver.get("skills") or [])
                         if isinstance(s, dict) and s.get("skill")],
        coaching_summary=coaching.get("summary"),
        suggestions=suggestions,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


# ── 백그라운드 태스크 ──────────────────────────────────────────
def _run_analysis(
    report_id: str, resume_text: str, job_family: str, owner_name: str | None,
    github_url: str | None, deploy_url: str | None,
    graph, neo4j: Neo4jClient, reports: dict,
) -> None:
    """업로드 이력서 + GitHub + 배포 URL → v3 그래프 → 2축·검증 리포트."""
    owner = owner_name or "지원자"
    try:
        out = run_supervisor(
            graph, job_family=job_family, owner=owner,
            resume_text=resume_text, github_url=github_url, deploy_url=deploy_url,
            neo4j=neo4j,
        )
        if out.get("error"):
            reports[report_id] = ReportResponse(
                report_id=report_id, status="error", owner=owner, job_family=job_family,
                error_detail=out.get("message") or out.get("error"),
                generated_at=datetime.now(timezone.utc).isoformat(),
            )
            return
        reports[report_id] = _map_final_report(report_id, owner, job_family, out)
    except Exception as e:
        reports[report_id] = ReportResponse(
            report_id=report_id, status="error", owner=owner, job_family=job_family,
            error_detail=str(e), generated_at=datetime.now(timezone.utc).isoformat(),
        )
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/unit/test_api_mapping.py -v` → 2 passed.

- [ ] **Step 5: 앱 로드 + 회귀**

Run: `python -c "import src.api.main"` (예외 없음)
Run: `python -m pytest tests/ -q -k "not test_returns_dict"` → 전부 통과.

- [ ] **Step 6: 커밋**

```bash
git add src/api/routers/portfolio.py tests/unit/test_api_mapping.py
git commit -m "feat(api): portfolio 라우터를 v3 run_supervisor로 재배선 (구 /github·gap_analyzer 제거)"
```

---

## Task 4: API 스모크 + progress

- [ ] **Step 1: TestClient 스모크 (네트워크 없이 라우트·검증)**

Run:
```bash
python -c "
import os
os.environ.pop('OPENAI_API_KEY', None)   # graph None 경로 확인 (503)
from fastapi.testclient import TestClient
from src.api.main import app
with TestClient(app) as c:
    assert c.get('/health').status_code == 200
    # upload 없이 analyze → 404
    r = c.post('/portfolio/analyze', json={'report_id':'nope','job_family':'Software Engineer'})
    print('analyze(미존재 report_id):', r.status_code)   # 404
print('OK: 라우트·헬스 정상')
"
```
Expected: `/health` 200, analyze 404, 예외 없음.

- [ ] **Step 2: progress.md 갱신 + 커밋**

`progress.md`에 `## [2026-06-12] API를 v3 에이전트로 재배선` 섹션(작업 절차/발생 문제/해결·검증). 그 후:
```bash
git add progress.md
git commit -m "docs: API v3 재배선 진행 기록"
```

---

## Self-Review

**Spec coverage:** /analyze가 run_supervisor 호출(Task3), 응답 2축+검증(Task1 스키마·Task3 매핑), 그래프 1회 빌드 주입(Task2), job_family 검증(Task3 422), 구 /github·gap_analyzer 제거(Task3). 포폴 vision은 범위 밖(명시). ✅

**Placeholder scan:** 각 step 완전 코드. 스모크는 실제 호출. ✅

**Type consistency:** `_map_final_report(report_id, owner, job_family, final)`·`VerificationItem(skill, verification, sources)`·`AnalyzeRequest(job_family, github_url, deploy_url)`·`ReportResponse` 필드가 Task1 스키마·Task3 매핑·테스트에서 일치. `run_supervisor` 시그니처(resume_text, github_url, deploy_url, neo4j) 기존과 일치. `get_graph` Task2 정의·Task3 사용 일치. ✅

**알려진 의존:** 그래프는 openai 키 있을 때만 빌드(없으면 /analyze 503). job_family 무효 시 동기 422. 포트폴리오(vision)·배포 vision은 범위 밖. jobs 라우터 미변경. 기존 API 테스트 없음(신규 추가).
