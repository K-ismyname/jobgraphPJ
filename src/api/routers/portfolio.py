# 포트폴리오 엔드포인트 — 업로드 → v3 다중소스 분석 → 리포트 폴링
from __future__ import annotations

import os
import tempfile
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile

from src.api.deps import get_graph, get_neo4j, get_reports, get_uploads
from src.api.schemas import (
    AnalyzeAccepted,
    AnalyzeRequest,
    LearningRecommendation,
    PortfolioUploadResponse,
    ProjectSuggestion,
    ReportResponse,
    UploadResponse,
    VerificationItem,
)
from src.agent.supervisor import run_supervisor
from src.portfolio.pdf_parser import extract_pdf_info
from src.storage.neo4j_client import Neo4jClient

router = APIRouter()

_MAX_PDF_BYTES = 10 * 1024 * 1024  # 10 MB

# 데모 비용 보호 — 하루 분석 횟수 상한(메모리, 날짜 바뀌면 리셋).
# DEMO_DAILY_LIMIT 미설정/0이면 무제한(로컬 개발). 공개 데모는 HF 시크릿으로 설정.
_demo_usage: dict = {"date": None, "count": 0}


def _enforce_daily_limit() -> None:
    """오늘 분석 횟수가 상한을 넘으면 429를 던지고, 아니면 카운트를 1 올린다."""
    limit = int(os.getenv("DEMO_DAILY_LIMIT", "0") or "0")
    if limit <= 0:
        return
    today = datetime.now(timezone.utc).date().isoformat()
    if _demo_usage["date"] != today:
        _demo_usage["date"] = today
        _demo_usage["count"] = 0
    if _demo_usage["count"] >= limit:
        raise HTTPException(
            429,
            f"오늘 데모 분석 한도({limit}회)가 모두 사용되었습니다. "
            "공개 데모 비용 보호를 위한 제한이며, 내일 다시 시도해 주세요.",
        )
    _demo_usage["count"] += 1
_NODE_PHASE = {
    "resume_eval": "소스 평가 중", "github_eval": "소스 평가 중",
    "portfolio_eval": "소스 평가 중", "deploy_eval": "소스 평가 중",
    "consensus": "교차검증 합의 중",
    "seed_gap": "적합도 분석 중", "call_model": "적합도 분석 중", "tools": "적합도 분석 중",
    "synthesizer": "리포트 생성 중", "critic": "검증 중",
    "coach_call_model": "코칭 생성 중", "coach_tools": "코칭 생성 중",
    "finalize_coach": "코칭 생성 중",
}


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


@router.post("/upload-portfolio", response_model=PortfolioUploadResponse)
async def upload_portfolio(
    file: UploadFile = File(...),
    uploads: dict = Depends(get_uploads),
) -> PortfolioUploadResponse:
    """포트폴리오 PDF 업로드. 경로를 임시 저장 후 portfolio_report_id 반환."""
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(415, "PDF 파일만 업로드 가능합니다.")
    content = await file.read()
    if len(content) > _MAX_PDF_BYTES:
        raise HTTPException(413, "파일 크기는 10MB 이하여야 합니다.")
    import pdfplumber
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name
    try:
        with pdfplumber.open(tmp_path) as pdf:
            page_count = len(pdf.pages)
    except Exception:
        os.unlink(tmp_path)
        raise HTTPException(422, "PDF를 열 수 없습니다.")
    portfolio_id = str(uuid.uuid4())
    uploads[f"pf:{portfolio_id}"] = tmp_path   # 파일 경로 저장 (텍스트가 아님)
    return PortfolioUploadResponse(
        portfolio_report_id=portfolio_id, page_count=page_count, status="uploaded",
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

    # 공개 데모 비용 보호 — 분석(=OpenAI 호출) 시작 직전에 일일 상한 검사
    _enforce_daily_limit()

    reports[req.report_id] = ReportResponse(
        report_id=req.report_id, status="processing", phase="소스 평가 중",
        owner=req.owner_name or "분석 중", job_family=req.job_family,
    )
    portfolio_path = uploads.get(f"pf:{req.portfolio_report_id}") if req.portfolio_report_id else None
    background_tasks.add_task(
        _run_analysis,
        report_id=req.report_id, resume_text=uploads[req.report_id],
        job_family=req.job_family, owner_name=req.owner_name,
        github_urls=req.github_urls, deploy_urls=req.deploy_urls,
        portfolio_path=portfolio_path,
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
    project_suggestions = [
        ProjectSuggestion(repo=s.get("repo", ""), add_skill=s.get("add_skill", ""),
                          why=s.get("why", ""), how=s.get("how", ""))
        for s in (coaching.get("project_suggestions") or [])
        if isinstance(s, dict) and s.get("add_skill")
    ]
    learning_recommendations = [
        LearningRecommendation(skill=s.get("skill", ""), reason=s.get("reason", ""))
        for s in (coaching.get("learning_recommendations") or [])
        if isinstance(s, dict) and s.get("skill")
    ]
    return ReportResponse(
        report_id=report_id, status="done", owner=owner, job_family=job_family,
        match_rate=gap.get("match_rate") or 0.0,
        confidence_level=gap.get("confidence_level"),
        advice=gap.get("advice"),
        verification_counts=ver.get("counts") or {},
        verified_skills=[VerificationItem(**s) for s in (ver.get("skills") or [])
                         if isinstance(s, dict) and s.get("skill")],
        coaching_summary=coaching.get("summary"),
        project_suggestions=project_suggestions,
        learning_recommendations=learning_recommendations,
        generated_at=datetime.now(timezone.utc).isoformat(),
        trace=final.get("trace"),
        capability_fit=final.get("capability_fit"),
        common_skill_fit=final.get("common_skill_fit"),
        recommended_families=final.get("recommended_families") or [],
    )


# ── 백그라운드 태스크 ──────────────────────────────────────────
def _run_analysis(
    report_id: str, resume_text: str, job_family: str, owner_name: str | None,
    github_urls: list[str], deploy_urls: list[str],
    graph, neo4j: Neo4jClient, reports: dict,
    portfolio_path: str | None = None,
) -> None:
    """업로드 이력서 + GitHub + 배포 URL + 포트폴리오 PDF → v3 그래프 → 2축·검증 리포트."""
    owner = owner_name or "지원자"

    def _progress(node: str) -> None:
        phase = _NODE_PHASE.get(node)
        if phase and report_id in reports:
            reports[report_id].phase = phase

    try:
        out = run_supervisor(
            graph, job_family=job_family, owner=owner,
            resume_text=resume_text, github_urls=github_urls, deploy_urls=deploy_urls,
            portfolio_path=portfolio_path,
            neo4j=neo4j, progress_cb=_progress,
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
