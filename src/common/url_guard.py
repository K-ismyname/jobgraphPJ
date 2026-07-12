# 사용자가 제출한 URL을 서버가 fetch하기 전에 SSRF 위험을 차단하는 가드
#
# 왜 필요한가: deploy_eval은 사용자가 준 배포 URL을 서버에서 직접 요청한다. 검증이 없으면
# 공격자가 http://169.254.169.254/(클라우드 메타데이터), http://localhost:7474/(내부 Neo4j),
# http://10.0.0.5/(사설망) 같은 주소를 넣어 서버를 프록시로 삼아 내부 자원을 긁어갈 수 있다.
# 이걸 SSRF(Server-Side Request Forgery)라 한다.
#
# 방어 핵심은 "호스트 이름"이 아니라 "실제로 연결될 IP"를 검사하는 것이다. 공격자는
# 자기 도메인의 DNS A 레코드를 127.0.0.1로 지정할 수 있으므로(DNS rebinding의 기본형),
# 도메인 문자열만 봐서는 막을 수 없다.

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import httpx

# 리다이렉트를 따라갈 최대 횟수 — 무한 리다이렉트 루프 방지
_MAX_REDIRECTS = 5


class UnsafeURLError(ValueError):
    """차단해야 할 URL (스킴 위반, 내부망 주소 등)."""


def _is_blocked_ip(ip: str) -> bool:
    """이 IP가 내부망·특수 목적 대역인가."""
    addr = ipaddress.ip_address(ip)
    return (
        addr.is_private          # 10.x, 172.16-31.x, 192.168.x
        or addr.is_loopback      # 127.x, ::1
        or addr.is_link_local    # 169.254.x — 클라우드 메타데이터가 여기 산다
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified   # 0.0.0.0
    )


def assert_safe_url(url: str) -> None:
    """공개 인터넷의 http/https 주소가 아니면 UnsafeURLError를 던진다.

    호스트가 해석되는 모든 IP를 검사한다 — 하나라도 내부망이면 차단.
    (A 레코드가 여러 개일 때 하나만 통과시키면 우회가 가능하다.)
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeURLError(f"http/https만 허용됩니다: {parsed.scheme or '(스킴 없음)'}")
    host = parsed.hostname
    if not host:
        raise UnsafeURLError("호스트가 없는 URL입니다.")

    try:
        # getaddrinfo는 이 호스트가 해석되는 모든 주소를 준다 (IPv4/IPv6 포함)
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as e:
        raise UnsafeURLError(f"호스트를 해석할 수 없습니다: {host}") from e

    for info in infos:
        ip = info[4][0]
        if _is_blocked_ip(ip):
            raise UnsafeURLError(f"내부망·예약 대역 주소는 요청할 수 없습니다: {host} → {ip}")


def safe_get(url: str, *, timeout: float = 10, headers: dict | None = None) -> httpx.Response:
    """SSRF 가드를 적용해 GET 요청을 보낸다.

    httpx의 follow_redirects=True를 쓰지 않는 이유: 최초 URL만 검사하고 리다이렉트를
    자동으로 따라가면, 공격자가 공개 도메인에서 302로 http://169.254.169.254/로 넘겨
    가드를 우회할 수 있다. 리다이렉트를 직접 따라가며 매 hop을 재검증한다.
    """
    current = url
    for _ in range(_MAX_REDIRECTS):
        assert_safe_url(current)
        resp = httpx.get(current, timeout=timeout, headers=headers, follow_redirects=False)
        if resp.is_redirect and resp.headers.get("location"):
            # 상대 경로 Location("/next")도 절대 URL로 만들어야 다음 hop을 검사할 수 있다
            current = str(resp.url.join(resp.headers["location"]))
            continue
        return resp
    raise UnsafeURLError(f"리다이렉트가 {_MAX_REDIRECTS}회를 초과했습니다.")
