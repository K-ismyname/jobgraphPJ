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
        trace=final.get("trace"),
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
