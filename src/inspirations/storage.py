from __future__ import annotations

import hashlib
import html as html_lib
import os
import re
import uuid
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urljoin, parse_qs

from .db import Db
from .security import is_safe_public_url
from .thumbnails import generate_thumbnails


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
        "image/bmp": ".bmp",
        "image/x-ms-bmp": ".bmp",
    }.get(ct)


def _ext_from_url(url: str) -> str | None:
    path = urlparse(url).path
    m = re.search(r"(\.jpg|\.jpeg|\.png|\.webp|\.gif|\.bmp)$", path, re.IGNORECASE)
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
    if chunk.startswith(b"BM"):
        return ".bmp"
    return None


def _extract_preview_image(html: str) -> str | None:
    candidates = _extract_preview_image_candidates(html)
    return candidates[0] if candidates else None


def _extract_preview_image_candidates(html: str) -> list[str]:
    # Small HTML parser for preview image tags plus a best-effort <img> fallback.
    meta_patterns = [
        r'<meta[^>]+property=["\']og:image:secure_url["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image:secure_url["\']',
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
        r'<meta[^>]+name=["\']twitter:image:src["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image:src["\']',
        r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image["\']',
        r'<meta[^>]+itemprop=["\']image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+itemprop=["\']image["\']',
        r'<link[^>]+rel=["\']image_src["\'][^>]+href=["\']([^"\']+)["\']',
        r'<link[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\']image_src["\']',
    ]
    candidates: list[str] = []
    seen: set[str] = set()
    for pat in meta_patterns:
        for m in re.finditer(pat, html, re.IGNORECASE):
            val = html_lib.unescape((m.group(1) or "").strip())
            if not val or val in seen:
                continue
            seen.add(val)
            candidates.append(val)
    if candidates:
        return candidates

    image_patterns = [
        r'<img[^>]+src=["\']([^"\']+)["\']',
        r'<img[^>]+data-src=["\']([^"\']+)["\']',
        r'<img[^>]+data-original=["\']([^"\']+)["\']',
    ]
    for pat in image_patterns:
        for m in re.finditer(pat, html, re.IGNORECASE):
            val = html_lib.unescape((m.group(1) or "").strip())
            if not val or val.startswith("data:") or val in seen:
                continue
            seen.add(val)
            candidates.append(val)
    return candidates


def _normalize_preview_candidate(base_url: str, candidate: str) -> str | None:
    cand = (candidate or "").strip()
    if not cand:
        return None
    if cand.startswith("//"):
        cand = "https:" + cand
    elif cand.startswith("/"):
        cand = urljoin(base_url, cand)
    else:
        p = urlparse(cand)
        if not p.scheme:
            cand = urljoin(base_url, cand)
    if cand.startswith("http://"):
        cand = "https://" + cand[len("http://") :]
    return cand if cand.startswith("https://") else None


def _is_tracking_preview(url: str) -> bool:
    try:
        p = urlparse(url)
    except Exception:
        return True
    host = (p.hostname or "").lower()
    path = (p.path or "").lower()
    query = (p.query or "").lower()
    if host.endswith("facebook.com") and path.startswith("/tr"):
        return True
    if host.endswith("pinterest.com") and path.startswith("/v3/"):
        return True
    if "event=init" in query and host.endswith("pinterest.com"):
        return True
    if "doubleclick.net" in host or "google-analytics.com" in host:
        return True
    return False


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
            for candidate in _extract_preview_image_candidates(raw):
                preview = _normalize_preview_candidate(url, candidate)
                if not preview or _is_tracking_preview(preview):
                    continue
                if is_safe_public_url(preview, allow_http=False):
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
            # Some hosts return octet-stream for images (e.g., .bmp).
            if ct_short not in ("application/octet-stream",):
                raise ValueError(f"Non-image content-type: {ct_short}")
        ext = _ext_from_content_type(ct) or _ext_from_url(url)

        # pre-check size if available
        clen = resp.headers.get("Content-Length")
        if clen:
            try:
                if int(clen) > max_bytes:
                    raise ValueError(f"Refusing to download >{max_bytes} bytes: {url}")
            except ValueError:
                pass

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
        with open(tmp_path, "wb") as f:
            if first:
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


def _stable_image_path_for_sha(downloaded_path: Path, sha256: str) -> Path:
    ext = downloaded_path.suffix.lower() or ".jpg"
    stable_path = downloaded_path.with_name(f"{sha256}{ext}")
    if stable_path == downloaded_path:
        return stable_path
    if stable_path.exists():
        try:
            downloaded_path.unlink()
        except FileNotFoundError:
            pass
        return stable_path
    os.replace(downloaded_path, stable_path)
    return stable_path


def _remove_unreferenced_file(db: Db, path_str: str) -> bool:
    path = Path((path_str or "").strip())
    if not path_str or not path.exists():
        return False
    ref_count = db.query_value("select count(*) from assets where stored_path=?", (path_str,))
    if int(ref_count or 0) != 0:
        return False
    try:
        path.unlink()
        return True
    except Exception:
        return False


def backfill_previews_from_source_ref(
    db: Db,
    store_dir: Path,
    *,
    source: str = "facebook",
    media_status: str = "placeholder",
    include_hidden: bool = False,
    limit: int = 0,
    force: bool = False,
    dry_run: bool = False,
    regenerate_thumbs: bool = True,
) -> dict[str, Any]:
    """
    Resolve source_ref URLs to preview images and attach downloaded originals.
    """
    source = (source or "").strip()
    if not source:
        raise ValueError("source is required")
    status_filter = (media_status or "").strip()

    clauses = [
        "source = ?",
        "coalesce(source_ref, '') != ''",
    ]
    params: list[Any] = [source]
    if status_filter:
        clauses.append("coalesce(media_status, '') = ?")
        params.append(status_filter)
    if not include_hidden:
        clauses.append("coalesce(triage_status, '') != 'hidden'")
    where_sql = " and ".join(clauses)
    rows = db.query(
        f"""
        select id, source_ref, image_url, stored_path, thumb_path, sha256, media_status
        from assets
        where {where_sql}
        order by imported_at asc, id asc
        """,
        tuple(params),
    )

    total_candidates = len(rows)
    attempted = 0
    resolved = 0
    downloaded = 0
    updated = 0
    would_update = 0
    unchanged = 0
    skipped_unsafe = 0
    skipped_invalid_ref = 0
    cleaned_orphans = 0
    errors: list[dict[str, str]] = []
    updated_ids: list[str] = []

    dest_dir = store_dir / "originals" / source
    dest_dir.mkdir(parents=True, exist_ok=True)

    for row in rows:
        if limit and attempted >= limit:
            break
        attempted += 1

        asset_id = str(row["id"] or "").strip()
        source_ref = str(row["source_ref"] or "").strip()
        if not asset_id or not source_ref:
            skipped_invalid_ref += 1
            continue
        if not is_safe_public_url(source_ref, allow_http=False):
            skipped_unsafe += 1
            continue

        try:
            resolved_url = resolve_image_url(source_ref)
        except Exception as e:
            errors.append({"id": asset_id, "url": source_ref, "error": f"resolve failed: {e}"})
            continue

        if not resolved_url:
            errors.append({"id": asset_id, "url": source_ref, "error": "No image preview found for URL"})
            continue
        resolved += 1

        current_url = str(row["image_url"] or "").strip()
        current_path = str(row["stored_path"] or "").strip()
        current_sha = str(row["sha256"] or "").strip()
        current_status = str(row["media_status"] or "").strip()
        has_thumb = bool(str(row["thumb_path"] or "").strip())
        needs_update = force or (
            resolved_url != current_url
            or not current_path
            or current_status != "image"
            or has_thumb
        )

        if dry_run:
            if needs_update:
                would_update += 1
            else:
                unchanged += 1
            continue
        if not needs_update:
            unchanged += 1
            continue

        try:
            tmp_path, new_sha, _nbytes = download_url_to_store(
                url=resolved_url,
                dest_dir=dest_dir,
                filename_stem=asset_id or str(uuid.uuid4()),
            )
            downloaded += 1
            stable_path = _stable_image_path_for_sha(tmp_path, new_sha)
            stable_str = str(stable_path)
            changed = (
                stable_str != current_path
                or new_sha != current_sha
                or resolved_url != current_url
                or current_status != "image"
                or has_thumb
            )
            if not changed:
                unchanged += 1
                continue
            db.exec(
                """
                update assets
                set image_url=?, stored_path=?, sha256=?, thumb_path=null, media_status='image'
                where id=?
                """,
                (resolved_url, stable_str, new_sha, asset_id),
            )
            updated += 1
            updated_ids.append(asset_id)
            if current_path and current_path != stable_str:
                if _remove_unreferenced_file(db, current_path):
                    cleaned_orphans += 1
        except Exception as e:
            errors.append({"id": asset_id, "url": resolved_url, "error": str(e)})

    thumbs_report: dict[str, Any] = {}
    if not dry_run and regenerate_thumbs and updated_ids:
        thumbs_report = generate_thumbnails(db, store_dir=store_dir, source=source, limit=0)

    return {
        "source": source,
        "media_status_filter": status_filter or None,
        "include_hidden": include_hidden,
        "dry_run": dry_run,
        "force": force,
        "limit": limit,
        "candidates": total_candidates,
        "attempted": attempted,
        "resolved": resolved,
        "downloaded": downloaded,
        "updated": updated,
        "would_update": would_update,
        "unchanged": unchanged,
        "skipped_unsafe": skipped_unsafe,
        "skipped_invalid_ref": skipped_invalid_ref,
        "cleaned_orphan_files": cleaned_orphans,
        "updated_ids": updated_ids[:100],
        "errors": errors[:25],
        "thumbnails": thumbs_report,
    }
