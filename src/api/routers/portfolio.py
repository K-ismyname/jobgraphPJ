# 포트폴리오 관련 엔드포인트 (upload / analyze / report / github)
from __future__ import annotations

import os
import tempfile
import uuid
from datetime import datetime, timezone

from openai import OpenAI
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile

from src.analysis.coach import CoachingResult, generate_coaching
from src.analysis.gap_analyzer import GapAnalysisResult, run_gap_analysis
from src.api.deps import get_openai, get_chroma, get_neo4j, get_reports, get_uploads
from src.api.schemas import (
    AnalyzeAccepted,
    AnalyzeRequest,
    GapSkillItem,
    GitHubRequest,
    GitHubUpdateResponse,
    ReportResponse,
    SuggestionItem,
    UploadResponse,
)
from src.extraction.skill_extractor import extract_skills_from_resume
from src.portfolio.github_connector import boost_confidence_from_github, parse_github_username
from src.portfolio.pdf_parser import extract_pdf_info
from src.storage.chroma_client import ChromaClient
from src.storage.neo4j_client import Neo4jClient

router = APIRouter()

_MAX_PDF_BYTES = 10 * 1024 * 1024  # 10 MB


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
        report_id=report_id,
        candidate_name_hint=name_hint,
        page_count=page_count,
        text_length=len(text),
        status="uploaded",
    )


@router.post("/analyze", response_model=AnalyzeAccepted)
async def analyze_portfolio(
    req: AnalyzeRequest,
    background_tasks: BackgroundTasks,
    uploads: dict = Depends(get_uploads),
    reports: dict = Depends(get_reports),
    neo4j: Neo4jClient = Depends(get_neo4j),
    chroma: ChromaClient = Depends(get_chroma),
    openai: OpenAI | None = Depends(get_openai),
) -> AnalyzeAccepted:
    """갭 분석 시작. 즉시 반환 후 백그라운드에서 처리."""
    if req.report_id not in uploads:
        raise HTTPException(404, "report_id를 찾을 수 없습니다. 먼저 /portfolio/upload를 호출하세요.")

    existing = reports.get(req.report_id)
    if existing and getattr(existing, "status", None) == "processing":
        raise HTTPException(409, "이미 분석 중입니다.")

    reports[req.report_id] = ReportResponse(
        report_id=req.report_id,
        status="processing",
        owner=req.owner_name or "분석 중",
        job_title=req.job_title,
        match_rate=0.0,
        have=[],
        missing=[],
        top_missing=[],
        suggestions=[],
    )

    background_tasks.add_task(
        _run_analysis,
        report_id=req.report_id,
        pdf_text=uploads[req.report_id],
        job_title=req.job_title,
        owner_name=req.owner_name,
        neo4j=neo4j,
        chroma=chroma,
        openai_client=openai,
        reports=reports,
    )

    return AnalyzeAccepted(report_id=req.report_id)


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


@router.post("/github", response_model=GitHubUpdateResponse)
async def link_github(
    req: GitHubRequest,
    reports: dict = Depends(get_reports),
) -> GitHubUpdateResponse:
    """GitHub 연동으로 보유 기술 confidence 상승."""
    if not os.getenv("GITHUB_TOKEN"):
        raise HTTPException(503, "GitHub 연동이 비활성화되어 있습니다. GITHUB_TOKEN을 설정하세요.")

    report: ReportResponse | None = reports.get(req.report_id)
    if report is None:
        raise HTTPException(404, "report_id를 찾을 수 없습니다.")
    if report.status != "done":
        raise HTTPException(409, "분석이 완료된 후 GitHub 연동이 가능합니다.")

    try:
        username = parse_github_username(req.github_url)
    except ValueError as e:
        raise HTTPException(422, str(e))

    from src.extraction.skill_extractor import DemonstratedSkill

    have_skills = [
        DemonstratedSkill(
            name=s.skill,
            category=s.category,
            evidence=s.evidence or "",
            confidence=s.confidence or "low",
        )
        for s in report.have
        if s.confidence  # have_it=True인 것만
    ]

    updated_skills, changes = boost_confidence_from_github(have_skills, username)

    # 메모리 내 report 업데이트
    updated_have = list(report.have)
    skill_map = {s.name: s for s in updated_skills}
    for i, gap_item in enumerate(updated_have):
        if gap_item.skill in skill_map:
            updated_have[i] = gap_item.model_copy(update={
                "confidence": skill_map[gap_item.skill].confidence,
                "evidence": skill_map[gap_item.skill].evidence,
            })

    reports[req.report_id] = report.model_copy(update={"have": updated_have})

    return GitHubUpdateResponse(
        report_id=req.report_id,
        skills_boosted=list(changes.keys()),
        confidence_changes=changes,
        status="updated",
    )


# ── 백그라운드 태스크 ──────────────────────────────────────────
def _run_analysis(
    report_id: str,
    pdf_text: str,
    job_title: str,
    owner_name: str | None,
    neo4j: Neo4jClient,
    chroma: ChromaClient,
    openai_client: OpenAI | None,
    reports: dict,
) -> None:
    """PDF 텍스트 → 기술 추출 → Neo4j/Chroma 저장 → 갭 분석 → 코칭."""
    try:
        extraction = extract_skills_from_resume(pdf_text, openai_client)
        owner = owner_name or extraction.candidate_name

        neo4j.save_portfolio(extraction)
        chroma.save_resume(pdf_text, owner)

        gap_result: GapAnalysisResult = run_gap_analysis(neo4j, chroma, job_title, owner)
        coaching: CoachingResult = generate_coaching(gap_result, chroma, openai_client)

        reports[report_id] = ReportResponse(
            report_id=report_id,
            status="done",
            owner=owner,
            job_title=job_title,
            match_rate=gap_result.match_rate,
            have=[GapSkillItem(**s.model_dump()) for s in gap_result.have],
            missing=[GapSkillItem(**s.model_dump()) for s in gap_result.missing],
            top_missing=gap_result.top_missing,
            suggestions=[SuggestionItem(**s.model_dump()) for s in coaching.suggestions],
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as e:
        current = reports.get(report_id)
        reports[report_id] = (current or ReportResponse(
            report_id=report_id,
            status="error",
            owner=owner_name or "unknown",
            job_title=job_title,
            match_rate=0.0,
            have=[],
            missing=[],
            top_missing=[],
            suggestions=[],
        )).model_copy(update={
            "status": "error",
            "error_detail": str(e),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        })
