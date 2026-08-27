# 유실된 백그라운드 분석이 영원히 processing에 머물지 않는지 검증
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from src.api.routers import portfolio as portfolio_router
from src.api.routers.portfolio import _ANALYSIS_TIMEOUT_SEC, _run_analysis, delete_portfolio_upload, delete_report, get_report
from src.api.schemas import ReportResponse


def _report(started_delta_sec: float, status="processing") -> ReportResponse:
    started = datetime.now(timezone.utc) - timedelta(seconds=started_delta_sec)
    return ReportResponse(
        report_id="r1", status=status, owner="tester", job_family="AI/LLM Engineer",
        started_at=started.isoformat(),
    )


def test_stale_processing_downgraded_to_error():
    """프로세스 재시작 등으로 작업이 유실되면 프론트가 무한 폴링하게 된다 — error로 강등."""
    reports = {"r1": _report(_ANALYSIS_TIMEOUT_SEC + 60)}
    out = asyncio.run(get_report("r1", reports))
    assert out.status == "error"
    assert "다시 시도" in out.error_detail


def test_recent_processing_stays_processing():
    reports = {"r1": _report(30)}   # 30초 전 시작 — 아직 정상 진행 중
    out = asyncio.run(get_report("r1", reports))
    assert out.status == "processing"


def test_done_report_untouched():
    reports = {"r1": _report(_ANALYSIS_TIMEOUT_SEC + 60, status="done")}
    out = asyncio.run(get_report("r1", reports))
    assert out.status == "done"   # 완료된 건 시간이 지나도 건드리지 않는다


def test_missing_report_404():
    with pytest.raises(HTTPException) as ei:
        asyncio.run(get_report("nope", {}))
    assert ei.value.status_code == 404


def test_expired_done_report_is_purged(monkeypatch):
    monkeypatch.setenv("REPORT_TTL_SEC", "10")
    old = datetime.now(timezone.utc) - timedelta(seconds=30)
    reports = {
        "r1": ReportResponse(
            report_id="r1", status="done", owner="tester", job_family="AI/LLM Engineer",
            generated_at=old.isoformat(),
        )
    }
    with pytest.raises(HTTPException) as ei:
        asyncio.run(get_report("r1", reports))
    assert ei.value.status_code == 404
    assert "r1" not in reports


def test_report_ttl_can_be_disabled(monkeypatch):
    monkeypatch.setenv("REPORT_TTL_SEC", "0")
    old = datetime.now(timezone.utc) - timedelta(days=30)
    reports = {
        "r1": ReportResponse(
            report_id="r1", status="done", owner="tester", job_family="AI/LLM Engineer",
            generated_at=old.isoformat(),
        )
    }
    out = asyncio.run(get_report("r1", reports))
    assert out.status == "done"


def test_delete_report_removes_report_and_upload():
    reports = {"r1": _report(0, status="done")}
    uploads = {"r1": "resume text"}
    out = asyncio.run(delete_report("r1", reports, uploads))
    assert out == {"report_id": "r1", "status": "deleted"}
    assert reports == {}
    assert uploads == {}


def test_delete_report_missing_404():
    with pytest.raises(HTTPException) as ei:
        asyncio.run(delete_report("missing", {}, {}))
    assert ei.value.status_code == 404


def test_delete_portfolio_upload_removes_temp_file(tmp_path, monkeypatch):
    monkeypatch.setattr("src.api.routers.portfolio.tempfile.gettempdir", lambda: str(tmp_path))
    pdf = tmp_path / "portfolio.pdf"
    pdf.write_bytes(b"%PDF")
    uploads = {"pf:p1": str(pdf)}

    out = asyncio.run(delete_portfolio_upload("p1", uploads))

    assert out == {"portfolio_report_id": "p1", "status": "deleted"}
    assert uploads == {}
    assert not pdf.exists()


def test_delete_portfolio_upload_missing_404():
    with pytest.raises(HTTPException) as ei:
        asyncio.run(delete_portfolio_upload("missing", {}))
    assert ei.value.status_code == 404


def test_deleted_report_is_not_resurrected_by_late_background_success(monkeypatch):
    monkeypatch.setattr(
        portfolio_router,
        "run_supervisor",
        lambda *a, **k: {"gap": {"match_rate": 0.7}, "verification": {"counts": {}}},
    )
    reports = {}

    _run_analysis(
        report_id="r1",
        resume_text="resume",
        job_family="AI/LLM Engineer",
        owner_name="tester",
        github_urls=[],
        deploy_urls=[],
        graph=object(),
        neo4j=object(),
        reports=reports,
    )

    assert reports == {}


def test_deleted_report_is_not_resurrected_by_late_background_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("late failure")

    monkeypatch.setattr(portfolio_router, "run_supervisor", boom)
    reports = {}

    _run_analysis(
        report_id="r1",
        resume_text="resume",
        job_family="AI/LLM Engineer",
        owner_name="tester",
        github_urls=[],
        deploy_urls=[],
        graph=object(),
        neo4j=object(),
        reports=reports,
    )

    assert reports == {}
