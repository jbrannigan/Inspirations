from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


ALLOWLIST_HOSTS = {
    "i.pinimg.com",
    "s.pinimg.com",
    "pinimg.com",
    "images.thdstatic.com",
}


def _is_allowlisted(host: str) -> bool:
    host = host.lower().strip(".")
    if host in ALLOWLIST_HOSTS:
        return True
    return any(host.endswith("." + h) for h in ALLOWLIST_HOSTS)


def resolve_host(host: str) -> list[str]:
    # Returns a list of IP strings for host (best-effort).
    addrs: list[str] = []
    for family, _, _, _, sockaddr in socket.getaddrinfo(host, None):
        if family == socket.AF_INET:
            addrs.append(sockaddr[0])
        elif family == socket.AF_INET6:
            addrs.append(sockaddr[0])
    return addrs


def is_public_ip(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    if addr.is_private:
        return False
    if addr.is_loopback:
        return False
    if addr.is_link_local:
        return False
    if addr.is_multicast:
        return False
    if addr.is_reserved:
        return False
    if addr.is_unspecified:
        return False
    return True


def is_safe_public_url(url: str, *, allow_http: bool = False) -> bool:
    """
    Basic SSRF mitigation for image downloads.
    - Only allow https (or http if allow_http=True)
    - Block private/loopback/link-local/etc IPs (including DNS-resolved)
    """
    try:
        p = urlparse(url)
    except Exception:
        return False

    if p.scheme not in ("https", "http"):
        return False
    if p.scheme == "http" and not allow_http:
        return False
    if not p.netloc:
        return False

    host = p.hostname
    if not host:
        return False

    # Allowlist shortcut for known public CDNs (useful in offline environments).
    if _is_allowlisted(host):
        return True

    # If host is an IP literal, validate directly; otherwise DNS resolve.
    try:
        ipaddress.ip_address(host)
        ips = [host]
    except ValueError:
        try:
            ips = resolve_host(host)
        except Exception:
            return False

    if not ips:
        return False

    return all(is_public_ip(ip) for ip in ips)
