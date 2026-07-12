# SSRF 가드 — 내부망·비 http 스킴 차단 검증
import pytest

from src.common.url_guard import UnsafeURLError, assert_safe_url
from src.portfolio.github_connector import parse_github_repo


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:7474/",           # 로컬 Neo4j
    "http://localhost:8000/",           # 로컬 API
    "http://169.254.169.254/latest/meta-data/",  # 클라우드 메타데이터
    "http://10.0.0.5/",                 # 사설망
    "http://192.168.1.1/",              # 사설망
    "http://[::1]/",                    # IPv6 루프백
    "http://0.0.0.0/",                  # unspecified
])
def test_blocks_internal_addresses(url):
    with pytest.raises(UnsafeURLError):
        assert_safe_url(url)


@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "gopher://evil.com/",
    "ftp://internal/",
])
def test_blocks_non_http_schemes(url):
    with pytest.raises(UnsafeURLError):
        assert_safe_url(url)


def test_allows_public_https():
    # 공개 인터넷 주소는 통과해야 한다 (DNS 조회가 일어나므로 안정적인 도메인 사용)
    assert_safe_url("https://example.com/")


def test_blocks_unresolvable_host():
    with pytest.raises(UnsafeURLError):
        assert_safe_url("http://this-host-does-not-exist.invalid/")


# ── GitHub owner/repo 경로 조작 방어 ──────────────────────────────
def test_github_parse_rejects_traversal():
    with pytest.raises(ValueError):
        parse_github_repo("https://github.com/../../etc")


def test_github_parse_accepts_normal_repo():
    assert parse_github_repo("https://github.com/K-ismyname/jobgraphPJ") == ("K-ismyname", "jobgraphPJ")
