# 유실된 백그라운드 분석이 영원히 processing에 머물지 않는지 검증
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from src.api.routers.portfolio import _ANALYSIS_TIMEOUT_SEC, get_report
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
