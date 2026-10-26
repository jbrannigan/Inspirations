from __future__ import annotations

import ipaddress
import socket
import threading
import time
from collections import deque
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


class RateLimiter:
    """Sliding-window request limiter keyed by caller identity.

    The server is threaded, so every access takes a lock. Windows are pruned
    lazily, and the key table is capped so a flood of distinct keys cannot grow
    memory without bound.

    Keying caveat: behind a reverse proxy on the same host every request arrives
    from 127.0.0.1, so callers should pass the forwarded client address when one
    is available. Where it is not, the whole proxy shares a single bucket, which
    still bounds total attempt volume even though it cannot isolate one caller.
    """

    def __init__(self, *, limit: int, window_seconds: float, max_keys: int = 4096) -> None:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self.limit = limit
        self.window_seconds = float(window_seconds)
        self.max_keys = max_keys
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str, *, now: float | None = None) -> tuple[bool, float]:
        """Record an attempt. Returns (allowed, retry_after_seconds)."""
        stamp = time.monotonic() if now is None else now
        cutoff = stamp - self.window_seconds
        with self._lock:
            window = self._hits.get(key)
            if window is None:
                if len(self._hits) >= self.max_keys:
                    self._evict_locked(cutoff)
                window = self._hits.setdefault(key, deque())
            while window and window[0] <= cutoff:
                window.popleft()
            if len(window) >= self.limit:
                retry_after = max(0.0, window[0] + self.window_seconds - stamp)
                return False, retry_after
            window.append(stamp)
            return True, 0.0

    def _evict_locked(self, cutoff: float) -> None:
        stale = [k for k, w in self._hits.items() if not w or w[-1] <= cutoff]
        for k in stale:
            self._hits.pop(k, None)
        if len(self._hits) >= self.max_keys:
            # Still full of live windows: drop the oldest to stay bounded.
            oldest = min(self._hits, key=lambda k: self._hits[k][-1])
            self._hits.pop(oldest, None)
