from __future__ import annotations

import hashlib
import os
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urljoin, parse_qs

from .db import Db
from .security import is_safe_public_url


@dataclass(frozen=True)
class DownloadResult:
    asset_id: str
    stored_path: str
    sha256: str
    bytes: int


def _ext_from_content_type(ct: str | None) -> str | None:
    if not ct:
        return None
    ct = ct.split(";")[0].strip().lower()
    return {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "image/svg+xml": ".svg",
    }.get(ct)


def _ext_from_url(url: str) -> str | None:
    path = urlparse(url).path
    m = re.search(r"(\\.jpg|\\.jpeg|\\.png|\\.webp|\\.gif)$", path, re.IGNORECASE)
    if not m:
        return None
    ext = m.group(1).lower()
    return ".jpg" if ext in (".jpeg", ".jpg") else ext


def _sniff_image_ext(chunk: bytes) -> str | None:
    if chunk.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if chunk.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if chunk.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if chunk.startswith(b"RIFF") and chunk[8:12] == b"WEBP":
        return ".webp"
    return None


def _extract_preview_image(html: str) -> str | None:
    # Very small HTML parser for og:image / twitter:image
    import re

    patterns = [
        r'<meta[^>]+property=["\']og:image:secure_url["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+name=["\']twitter:image:src["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image["\']',
        r'<meta[^>]+itemprop=["\']image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<link[^>]+rel=["\']image_src["\'][^>]+href=["\']([^"\']+)["\']',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def _youtube_thumb_url(url: str) -> str | None:
    try:
        p = urlparse(url)
    except Exception:
        return None
    host = (p.hostname or "").lower()
    vid = None
    if host in ("youtu.be", "www.youtu.be"):
        vid = p.path.lstrip("/").split("/")[0]
    if host in ("youtube.com", "www.youtube.com", "m.youtube.com"):
        if p.path.startswith("/watch"):
            q = parse_qs(p.query)
            vid = (q.get("v") or [""])[0]
        elif p.path.startswith("/shorts/"):
            vid = p.path.split("/")[2] if len(p.path.split("/")) > 2 else None
    if vid:
        return f"https://img.youtube.com/vi/{vid}/hqdefault.jpg"
    return None


def resolve_image_url(url: str, *, timeout_s: float = 20.0, max_html_bytes: int = 512 * 1024) -> str | None:
    if not is_safe_public_url(url, allow_http=False):
        return None
    yt = _youtube_thumb_url(url)
    if yt:
        return yt
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        ct = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ct.startswith("image/"):
            return url
        if ct in ("text/html", "application/xhtml+xml"):
            raw = resp.read(max_html_bytes).decode("utf-8", errors="ignore")
            preview = _extract_preview_image(raw)
            if preview:
                if preview.startswith("//"):
                    preview = "https:" + preview
                if preview.startswith("/"):
                    preview = urljoin(url, preview)
            if preview and is_safe_public_url(preview, allow_http=False):
                return preview
            return None
        # if content-type missing, try sniff from the first chunk
        first = resp.read(64 * 1024)
        ext = _sniff_image_ext(first)
        return url if ext else None


def download_url_to_store(
    *,
    url: str,
    dest_dir: Path,
    filename_stem: str,
    timeout_s: float = 30.0,
    max_bytes: int = 25 * 1024 * 1024,
) -> tuple[Path, str, int]:
    if not is_safe_public_url(url, allow_http=False):
        raise ValueError(f"Refusing to download non-public or non-https url: {url}")

    dest_dir.mkdir(parents=True, exist_ok=True)

    req = urllib.request.Request(url, headers={"User-Agent": "Inspirations/0.1"})
    sha = hashlib.sha256()
    total = 0

    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        ct = resp.headers.get("Content-Type")
        ct_short = (ct or "").split(";")[0].strip().lower()
        if ct_short and not ct_short.startswith("image/"):
            raise ValueError(f"Non-image content-type: {ct_short}")
        ext = _ext_from_content_type(ct) or _ext_from_url(url)
        out_path = dest_dir / f"{filename_stem}{ext}"

        # pre-check size if available
        clen = resp.headers.get("Content-Length")
        if clen:
            try:
                if int(clen) > max_bytes:
                    raise ValueError(f"Refusing to download >{max_bytes} bytes: {url}")
            except ValueError:
                pass

        tmp_path = out_path.with_suffix(out_path.suffix + ".part")
        with open(tmp_path, "wb") as f:
            first = resp.read(1024 * 64)
            if first:
                total += len(first)
                if total > max_bytes:
                    raise ValueError(f"Refusing to download >{max_bytes} bytes: {url}")
                if ext is None:
                    sniff = _sniff_image_ext(first)
                    if not sniff:
                        raise ValueError("Unknown image type (missing content-type)")
                    ext = sniff
                    out_path = dest_dir / f"{filename_stem}{ext}"
                    tmp_path = out_path.with_suffix(out_path.suffix + ".part")
                sha.update(first)
                f.write(first)
            while True:
                chunk = resp.read(1024 * 64)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError(f"Refusing to download >{max_bytes} bytes: {url}")
                sha.update(chunk)
                f.write(chunk)

        os.replace(tmp_path, out_path)
        return out_path, sha.hexdigest(), total


def download_and_attach_originals(
    db: Db, store_dir: Path, source: str, limit: int = 0, *, retry_non_image: bool = False
) -> dict[str, Any]:
    """
    Downloads originals for assets where stored_path is null and image_url is present.
    """
    if retry_non_image:
        rows = db.query(
            "select id, image_url, stored_path from assets where source=? and image_url is not null and (stored_path is null or stored_path like '%.bin') order by imported_at asc",
            (source,),
        )
    else:
        rows = db.query(
            "select id, image_url, stored_path from assets where source=? and stored_path is null and image_url is not null order by imported_at asc",
            (source,),
        )
    downloaded: list[DownloadResult] = []
    errors: list[dict[str, str]] = []
    for i, r in enumerate(rows):
        if limit and i >= limit:
            break
        asset_id = r["id"]
        url = r["image_url"]
        try:
            resolved = resolve_image_url(url) or None
            if not resolved:
                raise ValueError("No image preview found for URL")
            out_path, sha, n = download_url_to_store(
                url=resolved, dest_dir=store_dir / "originals" / source, filename_stem=asset_id
            )
            db.exec(
                "update assets set stored_path=?, sha256=?, image_url=? where id=?",
                (str(out_path), sha, resolved, asset_id),
            )
            downloaded.append(DownloadResult(asset_id=asset_id, stored_path=str(out_path), sha256=sha, bytes=n))
        except Exception as e:
            errors.append({"id": asset_id, "url": str(url), "error": str(e)})

    return {
        "attempted": min(len(rows), limit) if limit else len(rows),
        "downloaded": len(downloaded),
        "errors": errors[:25],
        "note": "Errors are truncated to 25 in output.",
    }
