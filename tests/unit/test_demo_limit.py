# 데모 비용 보호 — IP별 일일 분석 횟수 상한 로직 단위 테스트
import pytest
from fastapi import HTTPException

from src.api.routers import portfolio as p

_IP = "203.0.113.7"      # 테스트용 (TEST-NET-3, 문서화 전용 대역)
_OTHER_IP = "198.51.100.9"


def _reset():
    p._demo_usage.clear()


def test_defaults_to_three_when_unset(monkeypatch):
    # DEMO_DAILY_LIMIT 미설정이면 기본 3회 (무제한은 =0 센티넬).
    monkeypatch.delenv("DEMO_DAILY_LIMIT", raising=False)
    _reset()
    for _ in range(3):
        p._enforce_daily_limit(_IP)
    with pytest.raises(HTTPException) as ei:
        p._enforce_daily_limit(_IP)   # 4회째 → 초과
    assert ei.value.status_code == 429


def test_unlimited_when_zero(monkeypatch):
    monkeypatch.setenv("DEMO_DAILY_LIMIT", "0")
    _reset()
    for _ in range(50):
        p._enforce_daily_limit(_IP)


def test_blocks_over_cap(monkeypatch):
    monkeypatch.setenv("DEMO_DAILY_LIMIT", "3")
    _reset()
    for _ in range(3):
        p._enforce_daily_limit(_IP)
    with pytest.raises(HTTPException) as ei:
        p._enforce_daily_limit(_IP)
    assert ei.value.status_code == 429


def test_limit_is_per_ip(monkeypatch):
    """한 방문자가 상한을 소진해도 다른 방문자는 영향받지 않는다.

    전역 카운터였을 때는 누군가 아침에 소진하면 그날 하루 데모가 죽었다.
    """
    monkeypatch.setenv("DEMO_DAILY_LIMIT", "2")
    _reset()
    p._enforce_daily_limit(_IP)
    p._enforce_daily_limit(_IP)
    with pytest.raises(HTTPException):
        p._enforce_daily_limit(_IP)      # 이 IP는 소진

    p._enforce_daily_limit(_OTHER_IP)    # 다른 IP는 여전히 가능
    assert p._demo_usage[_OTHER_IP]["count"] == 1


def test_resets_on_new_day(monkeypatch):
    # 어제 한도를 소진했어도 날짜가 바뀌면 리셋된다
    monkeypatch.setenv("DEMO_DAILY_LIMIT", "2")
    _reset()
    p._demo_usage[_IP] = {"date": "2000-01-01", "count": 2}
    p._enforce_daily_limit(_IP)          # 오늘 첫 호출 → 리셋 후 통과
    assert p._demo_usage[_IP]["count"] == 1


# ── fail-closed 관리자 판정 ────────────────────────────────────────
def test_admin_denied_on_public_deploy_without_key(monkeypatch):
    """공개 배포인데 ACCESS_KEY를 안 걸었으면 관리자로 인정하지 않는다.

    예전에는 키 미설정 시 무조건 True를 반환해, 시크릿 설정을 깜빡하고 배포하면
    방문자 전원이 관리자가 되어 일일 상한이 통째로 무력화됐다.
    """
    monkeypatch.delenv("ACCESS_KEY", raising=False)
    monkeypatch.setenv("SPACE_ID", "user/jobgraph")   # HF Spaces가 주입하는 값
    assert p._is_admin("") is False
    assert p._is_admin("anything") is False


def test_admin_allowed_locally_without_key(monkeypatch):
    # 로컬 개발(공개 배포 아님)에서는 키 없이도 관리자 — 개발 편의
    monkeypatch.delenv("ACCESS_KEY", raising=False)
    monkeypatch.delenv("SPACE_ID", raising=False)
    monkeypatch.delenv("ENV", raising=False)
    assert p._is_admin("") is True


def test_admin_requires_matching_key(monkeypatch):
    monkeypatch.setenv("ACCESS_KEY", "s3cret")
    assert p._is_admin("s3cret") is True
    assert p._is_admin("wrong") is False
    assert p._is_admin("") is False
