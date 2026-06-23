# 데모 비용 보호 — 일일 분석 횟수 상한 로직 단위 테스트
import pytest
from fastapi import HTTPException

from src.api.routers import portfolio as p


def _reset(date=None, count=0):
    p._demo_usage.update(date=date, count=count)


def test_unlimited_when_env_unset(monkeypatch):
    # DEMO_DAILY_LIMIT 미설정이면 무제한 (로컬 개발 영향 없음)
    monkeypatch.delenv("DEMO_DAILY_LIMIT", raising=False)
    _reset()
    for _ in range(50):
        p._enforce_daily_limit()  # 예외 없어야 함


def test_unlimited_when_zero(monkeypatch):
    monkeypatch.setenv("DEMO_DAILY_LIMIT", "0")
    _reset()
    for _ in range(50):
        p._enforce_daily_limit()


def test_blocks_over_cap(monkeypatch):
    monkeypatch.setenv("DEMO_DAILY_LIMIT", "3")
    _reset()
    p._enforce_daily_limit()  # 1
    p._enforce_daily_limit()  # 2
    p._enforce_daily_limit()  # 3
    with pytest.raises(HTTPException) as ei:
        p._enforce_daily_limit()  # 4 → 초과
    assert ei.value.status_code == 429


def test_resets_on_new_day(monkeypatch):
    # 어제 한도를 소진했어도 날짜가 바뀌면 리셋된다
    monkeypatch.setenv("DEMO_DAILY_LIMIT", "2")
    _reset(date="2000-01-01", count=2)
    p._enforce_daily_limit()  # 오늘 첫 호출 → 리셋 후 통과
    assert p._demo_usage["count"] == 1
