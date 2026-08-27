# SSRF 가드 — 내부망·비 http 스킴 차단 검증
#
# DNS 조회(socket.getaddrinfo)는 mock한다 — 단위 테스트가 네트워크에 의존하면 오프라인·CI
# 환경에서 불안정하게 실패하고 느려진다. 가드의 판정 로직만 결정적으로 검증한다.
import socket

import pytest

from src.common import url_guard
from src.common.url_guard import UnsafeURLError, assert_safe_url
from src.portfolio.github_connector import parse_github_repo


@pytest.fixture
def resolve_to(monkeypatch):
    """host가 항상 지정한 IP로 해석되도록 getaddrinfo를 대체하는 헬퍼를 반환한다."""
    def _set(ip: str):
        def fake_getaddrinfo(host, port, *a, **k):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port or 80))]
        monkeypatch.setattr(url_guard.socket, "getaddrinfo", fake_getaddrinfo)
    return _set


@pytest.mark.parametrize("url,ip", [
    ("http://127.0.0.1:7474/", "127.0.0.1"),          # 로컬 Neo4j
    ("http://localhost:8000/", "127.0.0.1"),          # 로컬 API
    ("http://metadata.evil.com/", "169.254.169.254"), # 클라우드 메타데이터 (DNS rebinding)
    ("http://internal.corp/", "10.0.0.5"),            # 사설망
    ("http://x.example/", "192.168.1.1"),             # 사설망
    ("http://y.example/", "0.0.0.0"),                 # unspecified
])
def test_blocks_internal_addresses(resolve_to, url, ip):
    # 공개 도메인이라도 내부 IP로 해석되면 차단돼야 한다 (호스트 문자열이 아니라 실제 IP를 검사)
    resolve_to(ip)
    with pytest.raises(UnsafeURLError):
        assert_safe_url(url)


@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "gopher://evil.com/",
    "ftp://internal/",
])
def test_blocks_non_http_schemes(url):
    # 스킴 검사는 DNS 이전에 이뤄지므로 mock 불필요
    with pytest.raises(UnsafeURLError):
        assert_safe_url(url)


def test_allows_public_ip(resolve_to):
    # 공개 인터넷 IP로 해석되면 통과해야 한다
    resolve_to("93.184.216.34")   # example.com의 공개 IP 대역
    assert_safe_url("https://example.com/")


def test_blocks_unresolvable_host(monkeypatch):
    def boom(*a, **k):
        raise socket.gaierror("name resolution failed")
    monkeypatch.setattr(url_guard.socket, "getaddrinfo", boom)
    with pytest.raises(UnsafeURLError):
        assert_safe_url("http://this-host-does-not-exist.invalid/")


# ── GitHub owner/repo 경로 조작 방어 ──────────────────────────────
def test_github_parse_rejects_traversal():
    with pytest.raises(ValueError):
        parse_github_repo("https://github.com/../../etc")


@pytest.mark.parametrize("url", [
    "https://example.com/github.com/owner/repo",
    "https://github.com.evil.test/owner/repo",
    "https://github.com@evil.test/owner/repo",
    "ssh://github.com/owner/repo",
])
def test_github_parse_rejects_non_github_hosts(url):
    with pytest.raises(ValueError):
        parse_github_repo(url)


def test_github_parse_accepts_normal_repo():
    assert parse_github_repo("https://github.com/K-ismyname/jobgraphPJ") == ("K-ismyname", "jobgraphPJ")
    assert parse_github_repo("github.com/K-ismyname/jobgraphPJ") == ("K-ismyname", "jobgraphPJ")
    assert parse_github_repo("https://www.github.com/K-ismyname/jobgraphPJ") == ("K-ismyname", "jobgraphPJ")
