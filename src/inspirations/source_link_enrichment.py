from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import textwrap
import time
import urllib.error
import urllib.request
import uuid
from io import BytesIO
from datetime import datetime, timezone
from html import escape as html_escape, unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urljoin, urlparse

from .db import Db
from .security import is_safe_public_url
from .storage import download_url_to_store
from .thumbnails import generate_thumbnails


DEFAULT_TIMEOUT_S = 8.0
DEFAULT_MAX_BYTES = 262_144
DEFAULT_MAX_REDIRECTS = 4
DEFAULT_BROWSER_WAIT_MS = 1500
USER_AGENT = "Inspirations/0.1"
HTML_CONTENT_HINTS = ("text/html", "application/xhtml+xml", "text/plain")
PLATFORM_WRAPPER_HOSTS = {"pinterest.com", "facebook.com"}
HTTPS_UPGRADE_HOSTS = {"blogspot.com"}
DEFAULT_AUTH_BROWSER_CHANNEL = "chrome"
DEFAULT_AUTH_BROWSER_SESSION = "media-repair-auth"
TEXT_CARD_CANDIDATE_ID = "text-card"
DEFAULT_MAX_MEDIA_CANDIDATES = 48


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        return None


class _HeadMetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_title = False
        self._title_parts: list[str] = []
        self.meta: dict[str, str] = {}
        self.links: dict[str, str] = {}
        self.images: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = {str(key or "").lower(): str(value or "") for key, value in attrs}
        tag = str(tag or "").lower()
        if tag == "title":
            self._in_title = True
            return
        if tag == "meta":
            key = (attrs_map.get("property") or attrs_map.get("name") or "").strip().lower()
            value = (attrs_map.get("content") or "").strip()
            if key and value and key not in self.meta:
                self.meta[key] = value
            return
        if tag == "link":
            rel = (attrs_map.get("rel") or "").strip().lower()
            href = (attrs_map.get("href") or "").strip()
            if rel and href and rel not in self.links:
                self.links[rel] = href
            return
        if tag == "img":
            src = (attrs_map.get("src") or attrs_map.get("data-src") or "").strip()
            if src:
                self.images.append({"url": src, "alt": (attrs_map.get("alt") or "").strip()})

    def handle_endtag(self, tag: str) -> None:
        if str(tag or "").lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(str(data or ""))

    @property
    def title(self) -> str:
        return _normalize_space("".join(self._title_parts))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_space(value: Any) -> str:
    text = str(value or "")
    try:
        text = text.encode("utf-8", errors="replace").decode("utf-8", errors="replace")
    except Exception:
        text = str(value or "")
    return re.sub(r"\s+", " ", text.strip())


_PLATFORM_UI_NOISE_PATTERNS = (
    "ok not now stories",
    "feed posts facebook",
    "facebook facebook",
    "what's on your mind,",
    "remember password",
    "create story",
)


def _looks_like_platform_ui_noise(value: Any) -> bool:
    text = _normalize_space(value).lower()
    if not text:
        return False
    return any(pattern in text for pattern in _PLATFORM_UI_NOISE_PATTERNS)


def _extract_middle_page_title_segment(page_title: Any) -> str:
    parts = [_normalize_space(part) for part in str(page_title or "").split("|")]
    parts = [part for part in parts if part]
    if len(parts) >= 3:
        return parts[1]
    if len(parts) >= 2:
        return parts[-2]
    return parts[0] if parts else ""


def _db_text(value: Any) -> str | None:
    if value is None:
        return None
    return _normalize_space(value)


def _log_progress(message: str) -> None:
    print(f"[{_now_iso()}] {message}", file=sys.stderr, flush=True)


def _log_value(value: Any, *, limit: int = 160) -> str:
    text = _normalize_space(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _extract_domain(url: str) -> str:
    try:
        host = (urlparse(url).hostname or "").strip().lower()
    except Exception:
        host = ""
    if host.startswith("www."):
        host = host[4:]
    return host


def _is_platform_wrapper_host(host: str) -> bool:
    text = _normalize_space(host).lower().strip(".")
    if text.startswith("www."):
        text = text[4:]
    return text in PLATFORM_WRAPPER_HOSTS or any(text.endswith("." + item) for item in PLATFORM_WRAPPER_HOSTS)


def _upgrade_known_https_url(url: str) -> str:
    try:
        parsed = urlparse(str(url or "").strip())
    except Exception:
        return str(url or "").strip()
    host = (parsed.hostname or "").strip().lower().strip(".")
    if parsed.scheme != "http" or not host:
        return str(url or "").strip()
    if host in HTTPS_UPGRADE_HOSTS or any(host.endswith("." + item) for item in HTTPS_UPGRADE_HOSTS):
        return parsed._replace(scheme="https").geturl()
    return str(url or "").strip()


def _safe_external_outbound_url(value: Any) -> str:
    url = _upgrade_known_https_url(_normalize_space(value))
    host = _extract_domain(url)
    if not host or _is_platform_wrapper_host(host):
        return ""
    if not is_safe_public_url(url, allow_http=True):
        return ""
    return url


def _first_safe_external_outbound_url(raw: Any) -> str:
    if not isinstance(raw, list):
        return ""
    ranked: list[tuple[int, int, str]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        url = _safe_external_outbound_url(item.get("url", ""))
        if not url:
            continue
        label = _normalize_space(item.get("text", "")).lower()
        ranked.append((0 if "visit site" in label else 1, index, url))
    ranked.sort()
    return ranked[0][2] if ranked else ""


def _best_source_url(asset: dict[str, Any]) -> str:
    for key in ("source_url", "source_ref"):
        value = str(asset.get(key) or "").strip()
        if value.startswith("https://") or value.startswith("http://"):
            return value
    return ""


def _promoted_source_url_candidate(asset: dict[str, Any], result: dict[str, Any]) -> str:
    current = str(asset.get("source_url") or "").strip()
    current_host = _extract_domain(current)
    candidate = str(result.get("canonical_url") or "").strip() or str(result.get("final_url") or "").strip()
    candidate_host = _extract_domain(candidate)
    if not candidate or not candidate_host or _is_platform_wrapper_host(candidate_host):
        return ""
    if current and current == candidate:
        return ""
    if current and not _is_platform_wrapper_host(current_host):
        return ""
    return candidate


def _record_field_provenance(
    db: Db,
    *,
    asset_id: str,
    field_name: str,
    field_value: str,
    origin_type: str,
    origin_ref: str,
    actor: str,
    confidence: float,
    created_at: str,
) -> None:
    current_rows = db.query(
        """
        select id, field_value
        from asset_field_provenance
        where asset_id=? and field_name=? and is_current=1
        """,
        (asset_id, field_name),
    )
    for row in current_rows:
        if str(row["field_value"] or "").strip() == field_value:
            return
    if current_rows:
        db.executemany(
            "update asset_field_provenance set superseded_at=?, is_current=0 where id=? and is_current=1",
            [(created_at, str(row["id"])) for row in current_rows],
        )
    db.exec(
        """
        insert into asset_field_provenance
          (id, asset_id, field_name, field_value, origin_type, origin_ref, actor,
           confidence, created_at, superseded_at, is_current)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            asset_id,
            field_name,
            field_value,
            origin_type,
            origin_ref or None,
            actor or None,
            float(confidence),
            created_at,
            None,
            1,
        ),
    )


def _safe_redirect_target(current_url: str, location: str) -> str:
    next_url = urljoin(current_url, str(location or "").strip())
    return next_url


def _decode_bytes(raw: bytes, content_type: str, headers: Any) -> str:
    charset = ""
    if hasattr(headers, "get_content_charset"):
        charset = str(headers.get_content_charset() or "").strip()
    if not charset:
        match = re.search(r"charset=([A-Za-z0-9._-]+)", content_type, re.IGNORECASE)
        if match:
            charset = match.group(1)
    if not charset:
        charset = "utf-8"
    return raw.decode(charset, errors="replace")


def _strip_html_text(html_text: str, *, limit: int = 600) -> str:
    text = re.sub(r"(?is)<script\b.*?</script>", " ", html_text)
    text = re.sub(r"(?is)<style\b.*?</style>", " ", text)
    text = re.sub(r"(?is)<noscript\b.*?</noscript>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = unescape(text)
    text = _normalize_space(text)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def _parse_html_payload(raw_text: str, *, final_url: str) -> dict[str, Any]:
    parser = _HeadMetaParser()
    try:
        parser.feed(raw_text)
    except Exception:
        pass
    canonical_url = parser.links.get("canonical", "")
    if canonical_url:
        canonical_url = urljoin(final_url, canonical_url)
    return {
        "page_title": parser.title,
        "og_title": _normalize_space(parser.meta.get("og:title", "")),
        "meta_description": _normalize_space(parser.meta.get("description", "")),
        "og_description": _normalize_space(parser.meta.get("og:description", "")),
        "og_image_url": urljoin(final_url, parser.meta.get("og:image", "")) if parser.meta.get("og:image") else "",
        "canonical_url": canonical_url,
        "text_excerpt": _strip_html_text(raw_text),
        "hero_image_url": "",
        "hero_image_alt": "",
        "hero_text_excerpt": "",
        "media_candidates": [
            {
                "url": urljoin(final_url, item.get("url", "")),
                "alt": _normalize_space(item.get("alt", "")),
                "label": f"Page image {index + 1}",
            }
            for index, item in enumerate(parser.images)
            if item.get("url")
        ],
    }


def _parse_text_payload(raw_text: str) -> dict[str, Any]:
    lines = [line.strip() for line in str(raw_text or "").splitlines() if line.strip()]
    page_title = lines[0] if lines else ""
    excerpt = _normalize_space(" ".join(lines[:8]))
    if len(excerpt) > 600:
        excerpt = excerpt[:599].rstrip() + "..."
    return {
        "page_title": page_title,
        "og_title": "",
        "meta_description": "",
        "og_description": "",
        "og_image_url": "",
        "canonical_url": "",
        "text_excerpt": excerpt,
        "hero_image_url": "",
        "hero_image_alt": "",
        "hero_text_excerpt": "",
        "media_candidates": [],
    }


def _stable_download_path(downloaded_path: Path, sha256: str) -> Path:
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


def _archive_and_invalidate_media_evidence(
    db: Db,
    *,
    asset_id: str,
    repair_kind: str,
    origin_ref: str,
    created_at: str,
) -> dict[str, int]:
    asset_rows = db.query(
        """
        select id, image_url, stored_path, thumb_path, sha256, ai_summary
        from assets
        where id=?
        limit 1
        """,
        (asset_id,),
    )
    if not asset_rows:
        raise FileNotFoundError("asset not found")
    stale_rows = {
        "asset": dict(asset_rows[0]),
        "asset_ai": [dict(row) for row in db.query("select * from asset_ai where asset_id=? order by created_at, id", (asset_id,))],
        "asset_labels": [
            dict(row)
            for row in db.query("select * from asset_labels where asset_id=? and source='ai' order by created_at, id", (asset_id,))
        ],
        "asset_embeddings": [
            dict(row) for row in db.query("select * from asset_embeddings where asset_id=? order by created_at, id", (asset_id,))
        ],
        "asset_track_assessments": [
            dict(row) for row in db.query("select * from asset_track_assessments where asset_id=? order by created_at, id", (asset_id,))
        ],
        "asset_axis_memberships": [
            dict(row) for row in db.query("select * from asset_axis_memberships where asset_id=? order by created_at, id", (asset_id,))
        ],
        "asset_axis_evidence": [
            dict(row) for row in db.query("select * from asset_axis_evidence where asset_id=? order by created_at, id", (asset_id,))
        ],
        "asset_source_link_qc": [
            dict(row) for row in db.query("select * from asset_source_link_qc where asset_id=? order by created_at, id", (asset_id,))
        ],
    }
    counts = {key: len(rows) for key, rows in stale_rows.items() if isinstance(rows, list)}
    db.exec(
        """
        insert into asset_media_repair_audit
          (id, asset_id, repair_kind, origin_ref, stale_evidence_json, created_at)
        values (?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            asset_id,
            repair_kind,
            origin_ref or None,
            json.dumps(stale_rows, ensure_ascii=True, sort_keys=True),
            created_at,
        ),
    )
    db.exec("delete from asset_ai where asset_id=?", (asset_id,))
    db.exec("delete from asset_labels where asset_id=? and source='ai'", (asset_id,))
    db.exec("delete from asset_embeddings where asset_id=?", (asset_id,))
    db.exec("delete from asset_track_assessments where asset_id=?", (asset_id,))
    db.exec("delete from asset_axis_memberships where asset_id=?", (asset_id,))
    db.exec("delete from asset_axis_evidence where asset_id=?", (asset_id,))
    db.exec("delete from asset_source_link_qc where asset_id=?", (asset_id,))
    db.exec("update assets set ai_summary=null where id=?", (asset_id,))
    _record_field_provenance(
        db,
        asset_id=asset_id,
        field_name="media_evidence_status",
        field_value=f"refresh_required:{repair_kind}",
        origin_type="media_repair",
        origin_ref=origin_ref,
        actor="source_link_enrichment",
        confidence=1.0,
        created_at=created_at,
    )
    return counts


def list_pending_media_repairs(db: Db) -> list[dict[str, str]]:
    rows = db.query(
        """
        select p.asset_id, p.field_value, p.created_at,
               coalesce(a.title, '') as title
        from asset_field_provenance p
        join assets a on a.id=p.asset_id
        where p.field_name='media_evidence_status'
          and p.is_current=1
          and p.field_value like 'refresh_required:%'
        order by p.created_at, p.asset_id
        """
    )
    pending: list[dict[str, str]] = []
    for row in rows:
        status = str(row["field_value"] or "").strip()
        pending.append(
            {
                "asset_id": str(row["asset_id"]),
                "title": str(row["title"] or ""),
                "status": status,
                "repair_kind": status.split(":", 1)[1] if ":" in status else "",
                "created_at": str(row["created_at"] or ""),
            }
        )
    return pending


def mark_media_repair_evidence_refreshed(
    db: Db,
    *,
    asset_id: str,
    repair_kind: str,
    origin_ref: str,
) -> None:
    _record_field_provenance(
        db,
        asset_id=asset_id,
        field_name="media_evidence_status",
        field_value=f"refreshed:{repair_kind}",
        origin_type="media_repair",
        origin_ref=origin_ref,
        actor="admin_refresh",
        confidence=1.0,
        created_at=_now_iso(),
    )


def _media_candidate_id(url: str) -> str:
    digest = hashlib.sha1(str(url or "").strip().encode("utf-8", errors="ignore")).hexdigest()[:16]
    return f"source-{digest}"


def _media_candidate_filename_hint(url: str) -> str:
    try:
        name = Path(unquote(urlparse(str(url or "")).path)).stem
    except Exception:
        return ""
    name = re.sub(r"\[\d+\]$", "", name)
    name = _normalize_space(re.sub(r"[-_+]+", " ", name))
    if len(name) < 4 or len(name) > 90 or re.fullmatch(r"[0-9a-f]{16,}", name, re.IGNORECASE):
        return ""
    return name[0].upper() + name[1:]


def _normalize_media_candidates(raw: Any, *, limit: int = DEFAULT_MAX_MEDIA_CANDIDATES) -> list[dict[str, str]]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = []
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        url = _normalize_space(item.get("url", ""))
        if not url or url in seen or not is_safe_public_url(url, allow_http=False):
            continue
        seen.add(url)
        normalized = {
            "id": _media_candidate_id(url),
            "kind": "post_image",
            "label": _normalize_space(item.get("label", "")) or f"Post image {len(out) + 1}",
            "url": url,
            "alt": _normalize_space(item.get("alt", "")),
            "text": _normalize_space(item.get("text", "")),
        }
        source_page_url = _safe_external_outbound_url(item.get("source_page_url", ""))
        if source_page_url:
            normalized["source_page_url"] = source_page_url
            normalized["source_page_label"] = _normalize_space(item.get("source_page_label", "")) or "Linked source page"
        out.append(normalized)
        if len(out) >= max(1, int(limit)):
            break
    return out


def _text_card_lines(text: str, *, width: int = 34) -> list[str]:
    normalized = _normalize_space(text)
    if not normalized:
        return []
    return textwrap.wrap(normalized, width=width, break_long_words=False, break_on_hyphens=False)[:8]


def _text_card_svg(text: str) -> bytes:
    lines = _text_card_lines(text)
    line_height = 62
    start_y = 360 - ((len(lines) - 1) * line_height // 2)
    tspans = "".join(
        f'<tspan x="600" y="{start_y + (index * line_height)}">{html_escape(line)}</tspan>'
        for index, line in enumerate(lines)
    )
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="675" viewBox="0 0 1200 675">
  <defs>
    <linearGradient id="card-gradient" x1="0" x2="0" y1="0" y2="1">
      <stop offset="0%" stop-color="#bd258d"/>
      <stop offset="48%" stop-color="#755bd5"/>
      <stop offset="100%" stop-color="#60c4ee"/>
    </linearGradient>
  </defs>
  <rect width="1200" height="675" fill="url(#card-gradient)"/>
  <text x="600" y="{start_y}" fill="#ffffff" text-anchor="middle"
        font-family="Arial, Helvetica, sans-serif" font-size="54" font-weight="700">{tspans}</text>
</svg>
"""
    return svg.encode("utf-8")


def _text_card_png(text: str) -> bytes | None:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return None

    width, height = 1200, 675
    top = (189, 37, 141)
    bottom = (96, 196, 238)
    image = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(image)
    for y in range(height):
        ratio = y / max(1, height - 1)
        color = tuple(round(top[channel] + ((bottom[channel] - top[channel]) * ratio)) for channel in range(3))
        draw.line((0, y, width, y), fill=color)

    font = None
    for font_path in (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "/System/Library/Fonts/SFNS.ttf",
    ):
        try:
            font = ImageFont.truetype(font_path, 54)
            break
        except Exception:
            continue
    if font is None:
        try:
            font = ImageFont.load_default(size=54)
        except TypeError:
            font = ImageFont.load_default()

    lines = _text_card_lines(text)
    multiline = "\n".join(lines)
    spacing = 12
    box = draw.multiline_textbbox((0, 0), multiline, font=font, spacing=spacing, align="center")
    x = width / 2
    y = (height - (box[3] - box[1])) / 2
    draw.multiline_text((x, y), multiline, font=font, fill="white", anchor="ma", spacing=spacing, align="center")
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _promote_text_card(
    db: Db,
    *,
    asset: dict[str, Any],
    text: str,
    store_dir: Path,
    created_at: str,
    run_id: str,
) -> dict[str, Any]:
    asset_id = str(asset.get("id") or "").strip()
    source = str(asset.get("source") or "").strip() or "enriched"
    if not asset_id or not _normalize_space(text):
        raise ValueError("no source text is available for a generated text card")
    payload = _text_card_png(text)
    ext = ".png"
    if payload is None:
        payload = _text_card_svg(text)
        ext = ".svg"
    sha256 = hashlib.sha256(payload).hexdigest()
    target = store_dir / "originals" / source / f"{sha256}{ext}"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_bytes(payload)
    invalidated = _archive_and_invalidate_media_evidence(
        db,
        asset_id=asset_id,
        repair_kind="generated_text_card",
        origin_ref=run_id,
        created_at=created_at,
    )
    db.exec(
        """
        update assets
        set stored_path=?, sha256=?, thumb_path=null, media_status='image'
        where id=?
        """,
        (str(target), sha256, asset_id),
    )
    _record_field_provenance(
        db,
        asset_id=asset_id,
        field_name="stored_path",
        field_value=str(target),
        origin_type="generated_text_card",
        origin_ref=run_id,
        actor="source_link_enrichment",
        confidence=1.0,
        created_at=created_at,
    )
    _record_field_provenance(
        db,
        asset_id=asset_id,
        field_name="media_representation",
        field_value="generated_text_card",
        origin_type="generated_text_card",
        origin_ref=run_id,
        actor="source_link_enrichment",
        confidence=1.0,
        created_at=created_at,
    )
    generate_thumbnails(db, store_dir=store_dir, source=source, limit=0)
    return {
        "promoted": True,
        "stored_path": str(target),
        "sha256": sha256,
        "kind": "text_card",
        "invalidated": invalidated,
    }


def _promote_hero_image(
    db: Db,
    *,
    asset: dict[str, Any],
    hero_image_url: str,
    store_dir: Path,
    created_at: str,
    run_id: str,
) -> dict[str, Any]:
    source = str(asset.get("source") or "").strip() or "enriched"
    asset_id = str(asset.get("id") or "").strip()
    if not asset_id or not hero_image_url:
        return {"promoted": False, "stored_path": "", "thumb_generated": False}
    tmp_path, sha256, _nbytes = download_url_to_store(
        url=hero_image_url,
        dest_dir=store_dir / "originals" / source,
        filename_stem=asset_id,
    )
    stable_path = _stable_download_path(tmp_path, sha256)
    stable_str = str(stable_path)
    invalidated = _archive_and_invalidate_media_evidence(
        db,
        asset_id=asset_id,
        repair_kind="source_image",
        origin_ref=run_id,
        created_at=created_at,
    )
    db.exec(
        """
        update assets
        set image_url=?, stored_path=?, sha256=?, thumb_path=null, media_status='image'
        where id=?
        """,
        (hero_image_url, stable_str, sha256, asset_id),
    )
    _record_field_provenance(
        db,
        asset_id=asset_id,
        field_name="image_url",
        field_value=hero_image_url,
        origin_type="source_link_enrichment",
        origin_ref=run_id,
        actor="source_link_enrichment",
        confidence=0.9,
        created_at=created_at,
    )
    _record_field_provenance(
        db,
        asset_id=asset_id,
        field_name="media_representation",
        field_value="source_image",
        origin_type="source_link_enrichment",
        origin_ref=run_id,
        actor="source_link_enrichment",
        confidence=1.0,
        created_at=created_at,
    )
    return {"promoted": True, "stored_path": stable_str, "thumb_generated": False, "invalidated": invalidated}


def _fetch_source_page(
    *,
    url: str,
    timeout_s: float,
    max_bytes: int,
    max_redirects: int,
    allow_http: bool,
) -> dict[str, Any]:
    current_url = url
    opener = urllib.request.build_opener(_NoRedirectHandler())

    for redirect_count in range(max_redirects + 1):
        if not is_safe_public_url(current_url, allow_http=allow_http):
            return {
                "input_url": url,
                "final_url": current_url,
                "final_domain": _extract_domain(current_url),
                "canonical_url": "",
                "og_image_url": "",
                "page_title": "",
                "og_title": "",
                "meta_description": "",
                "og_description": "",
                "text_excerpt": "",
                "content_type": "",
                "http_status": None,
                "redirect_count": redirect_count,
                "truncated": 0,
                "fetch_status": "unsafe_url",
                "error": "URL failed public safety checks",
                "content_hash": "",
            }

        req = urllib.request.Request(
            current_url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.2",
            },
        )
        try:
            with opener.open(req, timeout=timeout_s) as resp:
                status = int(resp.getcode() or 200)
                final_url = str(resp.geturl() or current_url)
                content_type = str(resp.headers.get("Content-Type") or "").strip()
                raw = resp.read(max_bytes + 1)
                truncated = 1 if len(raw) > max_bytes else 0
                raw = raw[:max_bytes]
                text = _decode_bytes(raw, content_type, resp.headers)
                parsed = (
                    _parse_html_payload(text, final_url=final_url)
                    if any(hint in content_type.lower() for hint in HTML_CONTENT_HINTS[:-1])
                    else _parse_text_payload(text)
                )
                return {
                    "input_url": url,
                    "final_url": final_url,
                    "final_domain": _extract_domain(final_url),
                    "content_type": content_type,
                    "http_status": status,
                    "redirect_count": redirect_count,
                    "truncated": truncated,
                    "fetch_status": "fetched",
                    "error": "",
                    "content_hash": hashlib.sha256(raw).hexdigest() if raw else "",
                    **parsed,
                }
        except urllib.error.HTTPError as exc:
            code = int(getattr(exc, "code", 0) or 0)
            location = ""
            if exc.headers is not None:
                location = str(exc.headers.get("Location") or "").strip()
            if 300 <= code < 400 and location:
                if redirect_count >= max_redirects:
                    return {
                        "input_url": url,
                        "final_url": current_url,
                        "final_domain": _extract_domain(current_url),
                        "canonical_url": "",
                        "og_image_url": "",
                        "page_title": "",
                        "og_title": "",
                        "meta_description": "",
                        "og_description": "",
                        "text_excerpt": "",
                        "content_type": "",
                        "http_status": code,
                        "redirect_count": redirect_count,
                        "truncated": 0,
                        "fetch_status": "redirect_limit",
                        "error": f"Too many redirects from {url}",
                        "content_hash": "",
                    }
                current_url = _safe_redirect_target(current_url, location)
                continue
            return {
                "input_url": url,
                "final_url": current_url,
                "final_domain": _extract_domain(current_url),
                "canonical_url": "",
                "og_image_url": "",
                "page_title": "",
                "og_title": "",
                "meta_description": "",
                "og_description": "",
                "text_excerpt": "",
                "content_type": str(exc.headers.get("Content-Type") or "").strip() if exc.headers else "",
                "http_status": code or None,
                "redirect_count": redirect_count,
                "truncated": 0,
                "fetch_status": "http_error",
                "error": _normalize_space(exc.reason if hasattr(exc, "reason") else f"HTTP {code}"),
                "content_hash": "",
            }
        except urllib.error.URLError as exc:
            return {
                "input_url": url,
                "final_url": current_url,
                "final_domain": _extract_domain(current_url),
                "canonical_url": "",
                "og_image_url": "",
                "page_title": "",
                "og_title": "",
                "meta_description": "",
                "og_description": "",
                "text_excerpt": "",
                "content_type": "",
                "http_status": None,
                "redirect_count": redirect_count,
                "truncated": 0,
                "fetch_status": "network_error",
                "error": _normalize_space(getattr(exc, "reason", str(exc))),
                "content_hash": "",
            }
        except Exception as exc:
            return {
                "input_url": url,
                "final_url": current_url,
                "final_domain": _extract_domain(current_url),
                "canonical_url": "",
                "og_image_url": "",
                "page_title": "",
                "og_title": "",
                "meta_description": "",
                "og_description": "",
                "text_excerpt": "",
                "content_type": "",
                "http_status": None,
                "redirect_count": redirect_count,
                "truncated": 0,
                "fetch_status": "error",
                "error": _normalize_space(str(exc)),
                "content_hash": "",
            }

    return {
        "input_url": url,
        "final_url": current_url,
        "final_domain": _extract_domain(current_url),
        "canonical_url": "",
        "og_image_url": "",
        "page_title": "",
        "og_title": "",
        "meta_description": "",
        "og_description": "",
        "text_excerpt": "",
        "content_type": "",
        "http_status": None,
        "redirect_count": max_redirects,
        "truncated": 0,
        "fetch_status": "redirect_limit",
        "error": f"Too many redirects from {url}",
        "content_hash": "",
    }


def _playwright_cli_path() -> str:
    codex_home = str(os.environ.get("CODEX_HOME") or "").strip() or os.path.expanduser("~/.codex")
    return os.path.join(codex_home, "skills", "playwright", "scripts", "playwright_cli.sh")


def default_auth_browser_profile_dir(*, cwd: Path | None = None) -> Path:
    root = Path(cwd or Path.cwd()).resolve()
    return root / "data" / "playwright_profiles" / "media_repair_auth"


def _run_playwright_cli(
    args: list[str],
    *,
    session_name: str,
    timeout_s: float,
    profile_dir: Path | None = None,
) -> str:
    cli_path = _playwright_cli_path()
    env = dict(os.environ)
    env["PLAYWRIGHT_CLI_SESSION"] = session_name
    cmd_args = list(args)
    if profile_dir is not None and cmd_args and cmd_args[0] == "open":
        profile_dir = profile_dir.resolve()
        profile_dir.mkdir(parents=True, exist_ok=True)
        if "--persistent" not in cmd_args:
            cmd_args.append("--persistent")
        if "--profile" not in cmd_args:
            cmd_args.extend(["--profile", str(profile_dir)])
        if "--browser" not in cmd_args:
            cmd_args.extend(["--browser", DEFAULT_AUTH_BROWSER_CHANNEL])
    process = subprocess.Popen(
        [cli_path, *cmd_args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=max(10.0, float(timeout_s) + 10.0))
    except subprocess.TimeoutExpired as exc:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        stdout, stderr = process.communicate()
        raise subprocess.TimeoutExpired(exc.cmd, exc.timeout, output=stdout, stderr=stderr)
    if process.returncode != 0:
        raise subprocess.CalledProcessError(process.returncode, process.args, output=stdout, stderr=stderr)
    return str(stdout or "")


def _extract_playwright_result(stdout: str) -> Any:
    text = str(stdout or "")
    match = re.search(r"### Result\s*(.*?)\s*### Ran Playwright code", text, re.DOTALL)
    if not match:
        raise ValueError("Could not parse Playwright CLI result block")
    payload = match.group(1).strip()
    if not payload:
        raise ValueError("Playwright CLI result block was empty")
    return json.loads(payload)


def _close_playwright_session(session_name: str, *, timeout_s: float, profile_dir: Path | None = None) -> None:
    if profile_dir is not None:
        return
    try:
        _run_playwright_cli(["close"], session_name=session_name, timeout_s=timeout_s, profile_dir=profile_dir)
    except Exception:
        return


def _fetch_source_page_browser(
    *,
    url: str,
    timeout_s: float,
    session_name: str,
    wait_ms: int = DEFAULT_BROWSER_WAIT_MS,
    profile_dir: Path | None = None,
) -> dict[str, Any]:
    if not is_safe_public_url(url, allow_http=False):
        return {
            "input_url": url,
            "final_url": url,
            "final_domain": _extract_domain(url),
            "canonical_url": "",
            "og_image_url": "",
            "page_title": "",
            "og_title": "",
            "meta_description": "",
            "og_description": "",
            "text_excerpt": "",
            "content_type": "",
            "http_status": None,
            "redirect_count": 0,
            "truncated": 0,
            "fetch_status": "browser_unsafe_url",
            "error": "URL did not pass public-URL safety checks",
            "content_hash": "",
        }
    try:
        nav_command = ["open", url]
        if profile_dir is not None:
            nav_command = ["goto", url]
        _run_playwright_cli(nav_command, session_name=session_name, timeout_s=timeout_s, profile_dir=profile_dir)
        if wait_ms > 0:
            _run_playwright_cli(
                ["run-code", f"await page.waitForTimeout({int(wait_ms)});"],
                session_name=session_name,
                timeout_s=timeout_s,
                profile_dir=profile_dir,
            )
        stdout = _run_playwright_cli(
            [
                "eval",
                """() => {
                  const UI_NOISE_PATTERNS = [
                    /Remember Password/gi,
                    /Next time you log in on this browser, just click your profile picture instead of typing a password\\./gi,
                    /OK Not Now/gi,
                    /Create a post/gi,
                    /What's on your mind, [^?.!]+\\??/gi,
                    /Stories Create story/gi,
                    /Create story/gi,
                    /Meta AI/gi,
                    /Friends Saved Feeds Groups Videos Marketplace/gi,
                    /Call Me Tae & Dontae Muse/gi,
                    /REALWolfhatfans/gi,
                  ];
                  const clean = (value, limit = 1200) => {
                    let text = String(value || '');
                    for (const pattern of UI_NOISE_PATTERNS) {
                      text = text.replace(pattern, ' ');
                    }
                    return text.replace(/\\s+/g, ' ').trim().slice(0, limit);
                  };
                  const titleParts = String(document.title || '')
                    .split('|')
                    .map(part => clean(part, 240))
                    .filter(Boolean);
                  const titleNeedle = titleParts.length >= 2
                    ? titleParts[titleParts.length - 2]
                    : (titleParts[0] || '');
                  const normalizedNeedle = titleNeedle.toLowerCase().replace(/[’']/g, "'");
                  const viewportW = window.innerWidth || document.documentElement.clientWidth || 0;
                  const viewportH = window.innerHeight || document.documentElement.clientHeight || 0;
                  const containsNeedle = (node) => {
                    if (!node || !normalizedNeedle) return false;
                    const text = clean(node.textContent || '', 3000).toLowerCase().replace(/[’']/g, "'");
                    return !!text && text.includes(normalizedNeedle);
                  };
                  const matchingLeaves = normalizedNeedle
                    ? Array.from(document.querySelectorAll('body *'))
                        .filter(node => {
                          try {
                            if (!containsNeedle(node)) return false;
                            return !Array.from(node.children || []).some(child => containsNeedle(child));
                          } catch (_err) {
                            return false;
                          }
                        })
                    : [];
                  const anchoredLeaf = matchingLeaves
                    .map(node => {
                      const rect = node.getBoundingClientRect();
                      const text = clean(node.innerText || node.textContent || '', 400);
                      return { node, rect, text };
                    })
                    .filter(item => item.text && item.rect.width > 100 && item.rect.height > 0)
                    .sort((a, b) => {
                      const areaA = a.rect.width * Math.max(1, a.rect.height);
                      const areaB = b.rect.width * Math.max(1, b.rect.height);
                      return areaA - areaB;
                    })[0] || null;
                  let anchoredRoot = null;
                  if (anchoredLeaf && anchoredLeaf.node) {
                    let cur = anchoredLeaf.node;
                    for (let i = 0; cur && i < 8; i += 1, cur = cur.parentElement) {
                      try {
                        const rect = cur.getBoundingClientRect();
                        const text = clean(cur.innerText || '', 2200);
                        if (!text || text.length < Math.max(40, normalizedNeedle.length)) continue;
                        if (text.toLowerCase().replace(/[’']/g, "'").includes(normalizedNeedle) && rect.width >= Math.min(420, viewportW * 0.45) && rect.height >= 80) {
                          anchoredRoot = cur;
                          break;
                        }
                      } catch (_err) {}
                    }
                  }
                  const contentRoots = Array.from(document.querySelectorAll(
                    'article, [role="article"], main, [role="main"], [data-pagelet], section'
                  ));
                  const scoreRoot = (node) => {
                    try {
                      const text = clean(node ? node.innerText : '', 2400);
                      if (!text || text.length < 40) return null;
                      const rect = node.getBoundingClientRect();
                      let score = text.length;
                      const lower = text.toLowerCase();
                      if (rect.top >= -80 && rect.top <= viewportH * 0.75) score += 500;
                      if (rect.width >= Math.min(600, viewportW * 0.6)) score += 250;
                      if (rect.height >= 180) score += 150;
                      if (titleNeedle && lower.includes(titleNeedle.toLowerCase())) score += 1600;
                      if (lower.includes('what\\'s on your mind') || lower.includes('create story')) score -= 2200;
                      if (lower.includes('remember password')) score -= 2600;
                      return { node, text, score };
                    } catch (_err) {
                      return null;
                    }
                  };
                  const rankedRoots = contentRoots
                    .map(scoreRoot)
                    .filter(Boolean)
                    .sort((a, b) => b.score - a.score);
                  const primaryRoot = anchoredRoot || (rankedRoots[0] ? rankedRoots[0].node : (document.querySelector('main, [role="main"]') || document.body));
                  const primaryText = clean(primaryRoot ? primaryRoot.innerText : ((document.body && document.body.innerText) || ''), 1600);
                  const scoreImage = (img) => {
                    try {
                      const rect = img.getBoundingClientRect();
                      const src = img.currentSrc || img.src || '';
                      if (!src || src.startsWith('data:')) return null;
                      if (rect.width < 140 || rect.height < 140) return null;
                      const area = rect.width * rect.height;
                      const centerX = rect.left + rect.width / 2;
                      const centerY = rect.top + rect.height / 2;
                      const horizCenterPenalty = Math.abs(centerX - viewportW / 2) / Math.max(1, viewportW);
                      const vertPenalty = centerY < -50 ? 2 : centerY > (viewportH * 1.35) ? 1.5 : Math.abs(centerY - Math.min(viewportH * 0.45, centerY)) / Math.max(1, viewportH);
                      let score = area;
                      score *= (1.15 - Math.min(0.9, horizCenterPenalty));
                      score *= (1.1 - Math.min(0.8, vertPenalty));
                      const parent = img.closest('article, [role="article"], main, [role="main"], section, [data-pagelet]') || primaryRoot || document.body;
                      const text = clean(parent ? parent.innerText : '', 320);
                      if (primaryRoot && parent && primaryRoot.contains(parent)) score *= 1.12;
                      return {
                        src,
                        alt: clean(img.alt || '', 240),
                        width: Math.round(rect.width),
                        height: Math.round(rect.height),
                        score,
                        text,
                      };
                    } catch (_err) {
                      return null;
                    }
                  };
                  // Do not borrow a visually prominent image from an unrelated feed post.
                  // A text-only anchored post should produce useful text evidence with no image candidate.
                  const imageScope = primaryRoot && primaryRoot !== document.body ? primaryRoot : null;
                  const imageNodes = imageScope ? Array.from(imageScope.querySelectorAll('img')) : [];
                  const images = imageNodes.map(scoreImage).filter(Boolean).sort((a, b) => b.score - a.score);
                  const hero = images[0] || null;
                  const mediaCandidates = [];
                  const seenCandidateUrls = new Set();
                  for (const item of images) {
                    if (!item.src || seenCandidateUrls.has(item.src)) continue;
                    seenCandidateUrls.add(item.src);
                    mediaCandidates.push({
                      url: item.src,
                      alt: item.alt,
                      text: item.text,
                      label: `Post image ${mediaCandidates.length + 1}`,
                    });
                    if (mediaCandidates.length >= 12) break;
                  }
                  const outboundLinks = Array.from((primaryRoot || document).querySelectorAll('a[href]'))
                    .map(link => ({
                      url: link.href || '',
                      text: clean(link.innerText || link.textContent || '', 160),
                    }))
                    .filter(item => /^https?:\\/\\//i.test(item.url))
                    .slice(0, 60);
                  return {
                    url: location.href,
                    title: document.title || '',
                    h1: Array.from(document.querySelectorAll('h1')).map(el => clean(el.textContent || '', 240)).filter(Boolean).slice(0, 3),
                    text: primaryText,
                    heroImageUrl: hero ? hero.src : '',
                    heroImageAlt: hero ? hero.alt : '',
                    heroText: hero ? hero.text : '',
                    mediaCandidates,
                    outboundLinks,
                  };
                }""",
            ],
            session_name=session_name,
            timeout_s=timeout_s,
            profile_dir=profile_dir,
        )
        payload = _extract_playwright_result(stdout)
        final_url = _normalize_space(payload.get("url", "")) or url
        page_title = _normalize_space(payload.get("title", ""))
        h1_values = payload.get("h1", [])
        if not isinstance(h1_values, list):
            h1_values = []
        h1_values = [_normalize_space(item) for item in h1_values if _normalize_space(item)]
        text_excerpt = _normalize_space(payload.get("text", ""))
        if _looks_like_platform_ui_noise(text_excerpt):
            fallback_text = _extract_middle_page_title_segment(page_title)
            if fallback_text:
                text_excerpt = fallback_text
        content_hash = ""
        if text_excerpt:
            content_hash = hashlib.sha256(text_excerpt.encode("utf-8", errors="ignore")).hexdigest()
        media_candidates = _normalize_media_candidates(payload.get("mediaCandidates", []))
        if _is_platform_wrapper_host(_extract_domain(final_url)) and _extract_domain(final_url).endswith("pinterest.com"):
            outbound_url = _first_safe_external_outbound_url(payload.get("outboundLinks", []))
            if outbound_url:
                linked = _fetch_source_page(
                    url=outbound_url,
                    timeout_s=timeout_s,
                    max_bytes=DEFAULT_MAX_BYTES,
                    max_redirects=DEFAULT_MAX_REDIRECTS,
                    allow_http=True,
                )
                linked_source_url = _safe_external_outbound_url(linked.get("final_url", "")) or outbound_url
                linked_media = [
                    {
                        **item,
                        "label": " · ".join(
                            part
                            for part in [
                                f"Linked page image {index + 1}",
                                _media_candidate_filename_hint(str(item.get("url") or "")),
                            ]
                            if part
                        ),
                        "source_page_url": linked_source_url,
                        "source_page_label": "Linked source page",
                    }
                    for index, item in enumerate(_normalize_media_candidates(linked.get("media_candidates", [])))
                ]
                media_candidates = _normalize_media_candidates([*media_candidates, *linked_media])
        return {
            "input_url": url,
            "final_url": final_url,
            "final_domain": _extract_domain(final_url),
            "canonical_url": "",
            "og_image_url": "",
            "page_title": page_title,
            "og_title": h1_values[0] if h1_values else "",
            "meta_description": "",
            "og_description": "",
            "text_excerpt": text_excerpt,
            "hero_image_url": _normalize_space(payload.get("heroImageUrl", "")),
            "hero_image_alt": _normalize_space(payload.get("heroImageAlt", "")),
            "hero_text_excerpt": _normalize_space(payload.get("heroText", "")),
            "media_candidates": media_candidates,
            "content_type": "browser/document",
            "http_status": 200,
            "redirect_count": 0,
            "truncated": 1 if len(text_excerpt) >= 1199 else 0,
            "fetch_status": "fetched",
            "error": "",
            "content_hash": content_hash,
        }
    except subprocess.TimeoutExpired:
        return {
            "input_url": url,
            "final_url": url,
            "final_domain": _extract_domain(url),
            "canonical_url": "",
            "og_image_url": "",
            "page_title": "",
            "og_title": "",
            "meta_description": "",
            "og_description": "",
            "text_excerpt": "",
            "hero_image_url": "",
            "hero_image_alt": "",
            "hero_text_excerpt": "",
            "content_type": "",
            "http_status": None,
            "redirect_count": 0,
            "truncated": 0,
            "fetch_status": "browser_timeout",
            "error": "Playwright wrapper fetch timed out",
            "content_hash": "",
        }
    except subprocess.CalledProcessError as exc:
        detail = _normalize_space(exc.stderr or exc.stdout or str(exc))
        if profile_dir is not None and ("session" in detail.lower() or "browser" in detail.lower()):
            detail = (
                f"Candidate capture browser '{session_name}' is not running. "
                "On the Mac, run tools/open_media_repair_auth_browser.sh, sign into Facebook in the Chrome window "
                "if prompted, leave that window open, and try Find source media again."
            )
        return {
            "input_url": url,
            "final_url": url,
            "final_domain": _extract_domain(url),
            "canonical_url": "",
            "og_image_url": "",
            "page_title": "",
            "og_title": "",
            "meta_description": "",
            "og_description": "",
            "text_excerpt": "",
            "hero_image_url": "",
            "hero_image_alt": "",
            "hero_text_excerpt": "",
            "content_type": "",
            "http_status": None,
            "redirect_count": 0,
            "truncated": 0,
            "fetch_status": "browser_error",
            "error": detail or "Playwright wrapper fetch failed",
            "content_hash": "",
        }
    except Exception as exc:
        return {
            "input_url": url,
            "final_url": url,
            "final_domain": _extract_domain(url),
            "canonical_url": "",
            "og_image_url": "",
            "page_title": "",
            "og_title": "",
            "meta_description": "",
            "og_description": "",
            "text_excerpt": "",
            "hero_image_url": "",
            "hero_image_alt": "",
            "hero_text_excerpt": "",
            "content_type": "",
            "http_status": None,
            "redirect_count": 0,
            "truncated": 0,
            "fetch_status": "browser_error",
            "error": _normalize_space(str(exc)),
            "content_hash": "",
        }


def _latest_track_run_id(db: Db) -> str:
    value = db.query_value(
        """
        select id
        from classification_runs
        where run_type='track_gate'
        order by created_at desc
        limit 1
        """
    )
    return str(value or "").strip()


def _csv_values(value: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in str(value or "").split(","):
        item = raw.strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def collect_source_link_enrichment_candidates(
    db: Db,
    *,
    track_run_id: str = "",
    only_ambiguous: bool = True,
    source: str = "",
    collection_id: str = "",
    limit: int = 0,
    offset: int = 0,
) -> tuple[str, list[dict[str, Any]]]:
    resolved_track_run_id = str(track_run_id or "").strip() or _latest_track_run_id(db)
    if not resolved_track_run_id:
        raise RuntimeError("No track_gate run found for source-link enrichment")

    clauses = ["ata.run_id = ?"]
    params: list[Any] = [resolved_track_run_id]
    if only_ambiguous:
        clauses.append("ata.is_ambiguous = 1")
    sources = _csv_values(source)
    if sources:
        clauses.append("lower(a.source) in (%s)" % ",".join(["?"] * len(sources)))
        params.extend(source.lower() for source in sources)
    collection_id = str(collection_id or "").strip()
    if collection_id:
        clauses.append("a.id in (select asset_id from collection_items where collection_id = ?)")
        params.append(collection_id)
    clauses.append("(coalesce(a.source_url, '') like 'http%' or coalesce(a.source_ref, '') like 'http%')")
    where = " and ".join(clauses)
    offset_value = max(0, int(offset or 0))
    if limit and limit > 0 and offset_value > 0:
        limit_sql = " limit ? offset ?"
        params.extend((int(limit), offset_value))
    elif limit and limit > 0:
        limit_sql = " limit ?"
        params.append(int(limit))
    elif offset_value > 0:
        limit_sql = " limit -1 offset ?"
        params.append(offset_value)
    else:
        limit_sql = ""
    rows = db.query(
        f"""
        select
          a.id,
          a.source,
          a.source_ref,
          a.source_url,
          a.title,
          a.board,
          ata.track,
          ata.is_ambiguous
        from assets a
        join asset_track_assessments ata
          on ata.asset_id = a.id
        where {where}
        order by ata.is_ambiguous desc, a.source asc, a.imported_at desc, a.id asc
        {limit_sql}
        """,
        tuple(params),
    )
    return resolved_track_run_id, [dict(row) for row in rows]


def run_source_link_enrichment(
    db: Db,
    *,
    track_run_id: str = "",
    only_ambiguous: bool = True,
    source: str = "",
    collection_id: str = "",
    limit: int = 0,
    offset: int = 0,
    notes: str = "",
    timeout_s: float = DEFAULT_TIMEOUT_S,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    allow_http: bool = False,
    include_platform_hosts: bool = False,
    browser_platform_hosts: bool = False,
    promote_best_source_url: bool = False,
    store_dir: Path | None = None,
    promote_hero_image: bool = False,
    progress_every: int = 0,
    browser_profile_dir: Path | None = None,
) -> dict[str, Any]:
    resolved_track_run_id, candidates = collect_source_link_enrichment_candidates(
        db,
        track_run_id=track_run_id,
        only_ambiguous=only_ambiguous,
        source=source,
        collection_id=collection_id,
        limit=limit,
        offset=offset,
    )

    run_id = str(uuid.uuid4())
    created_at = _now_iso()
    config = {
        "track_run_id": resolved_track_run_id,
        "only_ambiguous": bool(only_ambiguous),
        "source": source,
        "collection_id": collection_id,
        "limit": int(limit),
        "offset": int(offset),
        "timeout_s": float(timeout_s),
        "max_bytes": int(max_bytes),
        "max_redirects": int(max_redirects),
        "allow_http": bool(allow_http),
        "include_platform_hosts": bool(include_platform_hosts),
        "browser_platform_hosts": bool(browser_platform_hosts),
        "promote_best_source_url": bool(promote_best_source_url),
        "promote_hero_image": bool(promote_hero_image),
        "progress_every": int(progress_every),
        "browser_profile_dir": str(browser_profile_dir.resolve()) if browser_profile_dir is not None else "",
    }
    db.exec(
        """
        insert into classification_runs
          (id, schema_version, run_type, model_provider, model_name, prompt_version, config_json, created_at, notes)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            "curation_v2",
            "source_link_enrichment",
            "heuristic",
            "url_fetch_head_meta_v1",
            "",
            json.dumps(config, sort_keys=True),
            created_at,
            notes or None,
        ),
    )

    rows_to_insert: list[tuple[Any, ...]] = []
    outcome_counts: dict[str, int] = {}
    promoted = 0
    promoted_hero_images = 0
    examples: list[dict[str, Any]] = []
    updated_sources: set[str] = set()
    browser_session_name = f"sl{run_id[:6]}"
    if browser_profile_dir is not None:
        browser_session_name = DEFAULT_AUTH_BROWSER_SESSION
    total = len(candidates)
    try:
        for index, asset in enumerate(candidates, start=1):
            url = _best_source_url(asset)
            host = _extract_domain(url)
            item_started_at = time.monotonic()
            mode = "http"
            if url and _is_platform_wrapper_host(host):
                mode = "browser_wrapper" if browser_platform_hosts and include_platform_hosts else "wrapper"
            if progress_every and (index == 1 or index % progress_every == 0 or mode == "browser_wrapper"):
                _log_progress(
                    "source-link-enrichment start "
                    f"{index}/{total} asset={asset['id']} source={asset.get('source','')} host={host or '-'} "
                    f"mode={mode} title={_log_value(asset.get('title', ''))}"
                )
            if url and _is_platform_wrapper_host(host):
                if not include_platform_hosts:
                    result = {
                        "input_url": url,
                        "final_url": url,
                        "final_domain": host,
                        "canonical_url": "",
                        "og_image_url": "",
                        "page_title": "",
                        "og_title": "",
                        "meta_description": "",
                        "og_description": "",
                        "text_excerpt": "",
                        "content_type": "",
                        "http_status": None,
                        "redirect_count": 0,
                        "truncated": 0,
                        "fetch_status": "platform_wrapper_skipped",
                        "error": "Platform wrapper URL; no direct source page captured on this asset",
                        "content_hash": "",
                    }
                elif browser_platform_hosts:
                    result = _fetch_source_page_browser(
                        url=url,
                        timeout_s=timeout_s,
                        session_name=browser_session_name,
                        profile_dir=browser_profile_dir,
                    )
                else:
                    result = _fetch_source_page(
                        url=url,
                        timeout_s=timeout_s,
                        max_bytes=max_bytes,
                        max_redirects=max_redirects,
                        allow_http=allow_http,
                    )
            elif url:
                result = _fetch_source_page(
                    url=url,
                    timeout_s=timeout_s,
                    max_bytes=max_bytes,
                    max_redirects=max_redirects,
                    allow_http=allow_http,
                )
            else:
                result = {
                    "input_url": "",
                    "final_url": "",
                    "final_domain": "",
                    "canonical_url": "",
                    "og_image_url": "",
                    "page_title": "",
                    "og_title": "",
                    "meta_description": "",
                    "og_description": "",
                    "text_excerpt": "",
                    "content_type": "",
                    "http_status": None,
                    "redirect_count": 0,
                    "truncated": 0,
                    "fetch_status": "no_url",
                    "error": "No fetchable source URL",
                    "content_hash": "",
                }
            outcome = str(result["fetch_status"])
            outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1
            promoted_url = ""
            if promote_best_source_url:
                promoted_url = _promoted_source_url_candidate(asset, result)
                if promoted_url:
                    promoted_host = _extract_domain(promoted_url)
                    db.exec(
                        "update assets set source_url=?, source_domain=? where id=?",
                        (promoted_url, promoted_host or None, str(asset["id"])),
                    )
                    _record_field_provenance(
                        db,
                        asset_id=str(asset["id"]),
                        field_name="source_url",
                        field_value=promoted_url,
                        origin_type="source_link_enrichment",
                        origin_ref=run_id,
                        actor="source_link_enrichment",
                        confidence=0.92,
                        created_at=created_at,
                    )
                    promoted += 1
            promoted_hero = False
            hero_image_url = str(result.get("hero_image_url") or "").strip()
            if promote_hero_image and store_dir is not None and hero_image_url:
                try:
                    hero_report = _promote_hero_image(
                        db,
                        asset=asset,
                        hero_image_url=hero_image_url,
                        store_dir=store_dir,
                        created_at=created_at,
                        run_id=run_id,
                    )
                    promoted_hero = bool(hero_report.get("promoted"))
                    if promoted_hero:
                        updated_sources.add(str(asset.get("source") or "").strip())
                        promoted_hero_images += 1
                except Exception as exc:
                    result["error"] = _normalize_space(" | ".join(part for part in [str(result.get("error") or ""), f"hero promote failed: {exc}"] if part))
            rows_to_insert.append(
                (
                    str(uuid.uuid4()),
                    run_id,
                    str(asset["id"]),
                    _db_text(result.get("input_url")),
                    _db_text(result.get("final_url")),
                    _db_text(result.get("final_domain")),
                    _db_text(result.get("canonical_url")),
                    _db_text(result.get("og_image_url")),
                    _db_text(result.get("page_title")),
                    _db_text(result.get("og_title")),
                    _db_text(result.get("meta_description")),
                    _db_text(result.get("og_description")),
                    _db_text(result.get("text_excerpt")),
                    _db_text(result.get("hero_image_url")),
                    _db_text(result.get("hero_image_alt")),
                    _db_text(result.get("hero_text_excerpt")),
                    _db_text(json.dumps(_normalize_media_candidates(result.get("media_candidates", [])), sort_keys=True)),
                    _db_text(result.get("content_type")),
                    result.get("http_status"),
                    int(result.get("redirect_count") or 0),
                    int(result.get("truncated") or 0),
                    outcome,
                    _db_text(result.get("error")),
                    _db_text(result.get("content_hash")),
                    created_at,
                )
            )
            if len(examples) < 10:
                examples.append(
                    {
                        "asset_id": str(asset["id"]),
                        "source": str(asset.get("source") or ""),
                        "input_url": str(result.get("input_url") or ""),
                        "fetch_status": outcome,
                        "page_title": str(result.get("page_title") or ""),
                        "final_domain": str(result.get("final_domain") or ""),
                        "promoted_source_url": promoted_url,
                        "hero_image_url": str(result.get("hero_image_url") or ""),
                        "promoted_hero_image": promoted_hero,
                    }
                )
            elapsed_s = time.monotonic() - item_started_at
            if progress_every and (index == 1 or index % progress_every == 0 or outcome != "fetched" or mode == "browser_wrapper" or index == total):
                _log_progress(
                    "source-link-enrichment done "
                    f"{index}/{total} asset={asset['id']} status={outcome} elapsed_s={elapsed_s:.1f} "
                    f"domain={_log_value(result.get('final_domain', ''), limit=80)} "
                    f"page_title={_log_value(result.get('page_title', ''))}"
                )
    finally:
        if browser_platform_hosts and include_platform_hosts:
            _close_playwright_session(browser_session_name, timeout_s=timeout_s, profile_dir=browser_profile_dir)

    if rows_to_insert:
        db.executemany(
            """
            insert into asset_source_link_enrichment (
              id, run_id, asset_id, input_url, final_url, final_domain, canonical_url, og_image_url,
              page_title, og_title, meta_description, og_description, text_excerpt, hero_image_url,
              hero_image_alt, hero_text_excerpt, media_candidates_json, content_type, http_status, redirect_count, truncated,
              fetch_status, error, content_hash, created_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows_to_insert,
        )
    thumbs_report: dict[str, Any] = {}
    if promote_hero_image and store_dir is not None and updated_sources:
        generated = 0
        attempted = 0
        errors: list[dict[str, Any]] = []
        for source_name in sorted(updated_sources):
            report = generate_thumbnails(db, store_dir=store_dir, source=source_name, limit=0)
            generated += int(report.get("generated") or 0)
            attempted += int(report.get("attempted") or 0)
            if report.get("errors"):
                errors.extend(report.get("errors") or [])
        thumbs_report = {"attempted": attempted, "generated": generated, "errors": errors[:25]}

    return {
        "ok": True,
        "run_id": run_id,
        "track_run_id": resolved_track_run_id,
        "schema_version": "curation_v2",
        "run_type": "source_link_enrichment",
        "model_provider": "heuristic",
        "model_name": "url_fetch_head_meta_v1",
        "candidate_count": len(candidates),
        "rows_written": len(rows_to_insert),
        "counts": outcome_counts,
        "promoted_source_url_count": promoted,
        "promoted_hero_image_count": promoted_hero_images,
        "thumbnails": thumbs_report,
        "examples": examples,
    }


def latest_source_link_enrichment_for_asset(db: Db, *, asset_id: str) -> dict[str, Any]:
    rows = db.query(
        """
        select run_id, input_url, final_url, final_domain, canonical_url, og_image_url,
               page_title, og_title, meta_description, og_description, text_excerpt,
               hero_image_url, hero_image_alt, hero_text_excerpt, media_candidates_json,
               content_type, http_status, redirect_count, truncated, fetch_status, error, created_at
        from asset_source_link_enrichment
        where asset_id=?
        order by created_at desc, id desc
        limit 1
        """,
        (asset_id,),
    )
    return dict(rows[0]) if rows else {}


def _generated_text_card_text(*, asset: dict[str, Any], latest: dict[str, Any]) -> str:
    return (
        _normalize_space(asset.get("title", ""))
        or _normalize_space(latest.get("text_excerpt", ""))
        or _normalize_space(asset.get("description", ""))
    )


def media_repair_gallery_for_asset(db: Db, *, asset_id: str) -> list[dict[str, Any]]:
    asset_rows = db.query(
        """
        select id, source, title, description, image_url, stored_path, thumb_path, sha256
        from assets
        where id=?
        limit 1
        """,
        (asset_id,),
    )
    if not asset_rows:
        raise FileNotFoundError("asset not found")
    asset = dict(asset_rows[0])
    latest = latest_source_link_enrichment_for_asset(db, asset_id=asset_id)
    representation = str(
        db.query_value(
            """
            select field_value
            from asset_field_provenance
            where asset_id=? and field_name='media_representation' and is_current=1
            limit 1
            """,
            (asset_id,),
        )
        or ""
    ).strip()
    evidence_status = str(
        db.query_value(
            """
            select field_value
            from asset_field_provenance
            where asset_id=? and field_name='media_evidence_status' and is_current=1
            limit 1
            """,
            (asset_id,),
        )
        or ""
    ).strip()
    representation_label = {
        "generated_text_card": "Generated text card",
        "source_image": "Source image",
    }.get(representation, "Saved image")
    gallery: list[dict[str, Any]] = []
    current_preview = ""
    current_version = str(asset.get("sha256") or "").strip()
    current_suffix = f"&v={quote(current_version)}" if current_version else ""
    if str(asset.get("stored_path") or "").strip():
        current_preview = f"/media/{asset_id}?kind=original{current_suffix}"
    elif str(asset.get("thumb_path") or "").strip():
        current_preview = f"/media/{asset_id}?kind=thumb{current_suffix}"
    else:
        current_preview = str(asset.get("image_url") or "").strip()
    if current_preview:
        gallery.append(
            {
                "id": "current-media",
                "kind": "current_media",
                "label": f"In use: {representation_label}",
                "preview_url": current_preview,
                "selectable": False,
                "current": True,
                "representation": representation or "saved_image",
                "representation_label": representation_label,
                "evidence_status": evidence_status,
            }
        )
    for item in _normalize_media_candidates(latest.get("media_candidates_json", "[]")):
        gallery.append(
            {
                **item,
                "preview_url": item["url"],
                "selectable": True,
                "current": False,
            }
        )
    text = _generated_text_card_text(asset=asset, latest=latest)
    if text:
        gallery.append(
            {
                "id": TEXT_CARD_CANDIDATE_ID,
                "kind": "text_card",
                "label": "Generated text card",
                "text": text,
                "selectable": True,
                "current": False,
            }
        )
    return gallery


def promote_media_repair_candidate_for_asset(
    db: Db,
    *,
    asset_id: str,
    candidate_id: str,
    store_dir: Path,
    notes: str = "",
) -> dict[str, Any]:
    asset_rows = db.query(
        """
        select id, source, title, description, image_url, stored_path, thumb_path, source_url, source_ref
        from assets
        where id=?
        limit 1
        """,
        (asset_id,),
    )
    if not asset_rows:
        raise FileNotFoundError("asset not found")
    asset = dict(asset_rows[0])
    latest = latest_source_link_enrichment_for_asset(db, asset_id=asset_id)
    candidate_id = str(candidate_id or "").strip()
    if not candidate_id:
        raise ValueError("choose source media before using it")
    created_at = _now_iso()
    run_id = str(latest.get("run_id") or "").strip()
    if candidate_id == TEXT_CARD_CANDIDATE_ID:
        text = _generated_text_card_text(asset=asset, latest=latest)
        report = _promote_text_card(
            db,
            asset=asset,
            text=text,
            store_dir=store_dir,
            created_at=created_at,
            run_id=run_id,
        )
        return {
            "ok": True,
            "asset_id": asset_id,
            "candidate_id": candidate_id,
            "kind": "text_card",
            "promoted": bool(report.get("promoted")),
            "invalidated": report.get("invalidated") or {},
            "refresh_required": ["embedding", "classification"],
            "notes": notes,
        }
    selected = next(
        (
            item
            for item in _normalize_media_candidates(latest.get("media_candidates_json", "[]"))
            if str(item.get("id") or "") == candidate_id
        ),
        None,
    )
    if not selected:
        raise ValueError("selected source media candidate is not available")
    report = _promote_hero_image(
        db,
        asset=asset,
        hero_image_url=str(selected.get("url") or "").strip(),
        store_dir=store_dir,
        created_at=created_at,
        run_id=run_id,
    )
    promoted_source_url = ""
    selected_source_url = _safe_external_outbound_url(selected.get("source_page_url", ""))
    current_source_url = str(asset.get("source_url") or "").strip()
    if selected_source_url and (not current_source_url or _is_platform_wrapper_host(_extract_domain(current_source_url))):
        promoted_source_url = selected_source_url
        db.exec(
            "update assets set source_url=?, source_domain=? where id=?",
            (promoted_source_url, _extract_domain(promoted_source_url) or None, asset_id),
        )
        _record_field_provenance(
            db,
            asset_id=asset_id,
            field_name="source_url",
            field_value=promoted_source_url,
            origin_type="media_repair_linked_page",
            origin_ref=run_id,
            actor="source_link_enrichment",
            confidence=0.92,
            created_at=created_at,
        )
    generate_thumbnails(db, store_dir=store_dir, source=str(asset.get("source") or "").strip() or None, limit=0)
    return {
        "ok": True,
        "asset_id": asset_id,
        "candidate_id": candidate_id,
        "kind": "post_image",
        "hero_image_url": str(selected.get("url") or "").strip(),
        "promoted_source_url": promoted_source_url,
        "promoted": bool(report.get("promoted")),
        "invalidated": report.get("invalidated") or {},
        "refresh_required": ["image_tagging", "embedding", "classification"],
        "notes": notes,
    }


def promote_latest_hero_image_for_asset(
    db: Db,
    *,
    asset_id: str,
    store_dir: Path,
    notes: str = "",
) -> dict[str, Any]:
    asset_rows = db.query(
        "select id, source, image_url, stored_path, thumb_path, source_url, source_ref from assets where id=? limit 1",
        (asset_id,),
    )
    if not asset_rows:
        raise FileNotFoundError("asset not found")
    asset = dict(asset_rows[0])
    latest = latest_source_link_enrichment_for_asset(db, asset_id=asset_id)
    hero_image_url = str(latest.get("hero_image_url") or "").strip()
    if not hero_image_url:
        raise ValueError("no captured hero image available for this asset")
    created_at = _now_iso()
    report = _promote_hero_image(
        db,
        asset=asset,
        hero_image_url=hero_image_url,
        store_dir=store_dir,
        created_at=created_at,
        run_id=str(latest.get("run_id") or ""),
    )
    generate_thumbnails(db, store_dir=store_dir, source=str(asset.get("source") or "").strip() or None, limit=0)
    return {
        "ok": True,
        "asset_id": asset_id,
        "hero_image_url": hero_image_url,
        "promoted": bool(report.get("promoted")),
        "notes": notes,
    }


def capture_source_link_candidate_for_asset(
    db: Db,
    *,
    asset_id: str,
    store_dir: Path,
    browser: bool = True,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    allow_http: bool = False,
    include_platform_hosts: bool = True,
    promote_best_source_url: bool = False,
    promote_hero_image: bool = False,
    notes: str = "",
    browser_profile_dir: Path | None = None,
) -> dict[str, Any]:
    asset_rows = db.query(
        """
        select a.id, a.source, a.source_ref, a.source_url, a.title, a.board, coalesce(ata.track, '') as track
        from assets a
        left join (
          select asset_id, track
          from asset_track_assessments
          where asset_id=?
          order by created_at desc, id desc
          limit 1
        ) ata on ata.asset_id=a.id
        where a.id=?
        limit 1
        """,
        (asset_id, asset_id),
    )
    if not asset_rows:
        raise FileNotFoundError("asset not found")
    asset = dict(asset_rows[0])
    return _capture_single_asset_source_link_enrichment(
        db,
        asset=asset,
        store_dir=store_dir,
        browser=browser,
        timeout_s=timeout_s,
        max_bytes=max_bytes,
        max_redirects=max_redirects,
        allow_http=allow_http,
        include_platform_hosts=include_platform_hosts,
        promote_best_source_url=promote_best_source_url,
        promote_hero_image=promote_hero_image,
        notes=notes or f"asset-level capture for {asset_id}",
        browser_profile_dir=browser_profile_dir,
    )


def _capture_single_asset_source_link_enrichment(
    db: Db,
    *,
    asset: dict[str, Any],
    store_dir: Path,
    browser: bool,
    timeout_s: float,
    max_bytes: int,
    max_redirects: int,
    allow_http: bool,
    include_platform_hosts: bool,
    promote_best_source_url: bool,
    promote_hero_image: bool,
    notes: str,
    browser_profile_dir: Path | None,
) -> dict[str, Any]:
    run_id = str(uuid.uuid4())
    created_at = _now_iso()
    config = {
        "asset_id": str(asset.get("id") or ""),
        "browser": bool(browser),
        "timeout_s": float(timeout_s),
        "max_bytes": int(max_bytes),
        "max_redirects": int(max_redirects),
        "allow_http": bool(allow_http),
        "include_platform_hosts": bool(include_platform_hosts),
        "promote_best_source_url": bool(promote_best_source_url),
        "promote_hero_image": bool(promote_hero_image),
        "browser_profile_dir": str(browser_profile_dir.resolve()) if browser_profile_dir is not None else "",
    }
    db.exec(
        """
        insert into classification_runs
          (id, schema_version, run_type, model_provider, model_name, prompt_version, config_json, created_at, notes)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            "curation_v2",
            "source_link_enrichment",
            "heuristic",
            "url_fetch_head_meta_v1",
            "",
            json.dumps(config, sort_keys=True),
            created_at,
            notes or None,
        ),
    )
    url = _best_source_url(asset)
    host = _extract_domain(url)
    if url and _is_platform_wrapper_host(host):
        if not include_platform_hosts:
            result = {
                "input_url": url,
                "final_url": url,
                "final_domain": host,
                "canonical_url": "",
                "og_image_url": "",
                "page_title": "",
                "og_title": "",
                "meta_description": "",
                "og_description": "",
                "text_excerpt": "",
                "hero_image_url": "",
                "hero_image_alt": "",
                "hero_text_excerpt": "",
                "content_type": "",
                "http_status": None,
                "redirect_count": 0,
                "truncated": 0,
                "fetch_status": "platform_wrapper_skipped",
                "error": "Platform wrapper URL; no direct source page captured on this asset",
                "content_hash": "",
            }
        elif browser:
            session_name = f"sl{run_id[:6]}"
            if browser_profile_dir is not None:
                session_name = DEFAULT_AUTH_BROWSER_SESSION
            try:
                result = _fetch_source_page_browser(
                    url=url,
                    timeout_s=timeout_s,
                    session_name=session_name,
                    profile_dir=browser_profile_dir,
                )
            finally:
                _close_playwright_session(session_name, timeout_s=timeout_s, profile_dir=browser_profile_dir)
        else:
            result = _fetch_source_page(
                url=url,
                timeout_s=timeout_s,
                max_bytes=max_bytes,
                max_redirects=max_redirects,
                allow_http=allow_http,
            )
    elif url:
        result = _fetch_source_page(
            url=url,
            timeout_s=timeout_s,
            max_bytes=max_bytes,
            max_redirects=max_redirects,
            allow_http=allow_http,
        )
    else:
        result = {
            "input_url": "",
            "final_url": "",
            "final_domain": "",
            "canonical_url": "",
            "og_image_url": "",
            "page_title": "",
            "og_title": "",
            "meta_description": "",
            "og_description": "",
            "text_excerpt": "",
            "hero_image_url": "",
            "hero_image_alt": "",
            "hero_text_excerpt": "",
            "content_type": "",
            "http_status": None,
            "redirect_count": 0,
            "truncated": 0,
            "fetch_status": "no_url",
            "error": "No fetchable source URL",
            "content_hash": "",
        }
    promoted_url = ""
    if promote_best_source_url:
        promoted_url = _promoted_source_url_candidate(asset, result)
        if promoted_url:
            promoted_host = _extract_domain(promoted_url)
            db.exec("update assets set source_url=?, source_domain=? where id=?", (promoted_url, promoted_host or None, str(asset["id"])))
            _record_field_provenance(
                db,
                asset_id=str(asset["id"]),
                field_name="source_url",
                field_value=promoted_url,
                origin_type="source_link_enrichment",
                origin_ref=run_id,
                actor="source_link_enrichment",
                confidence=0.92,
                created_at=created_at,
            )
    promoted_hero = False
    hero_image_url = str(result.get("hero_image_url") or "").strip()
    if promote_hero_image and hero_image_url:
        hero_report = _promote_hero_image(
            db,
            asset=asset,
            hero_image_url=hero_image_url,
            store_dir=store_dir,
            created_at=created_at,
            run_id=run_id,
        )
        promoted_hero = bool(hero_report.get("promoted"))
        if promoted_hero:
            generate_thumbnails(db, store_dir=store_dir, source=str(asset.get("source") or "").strip() or None, limit=0)
    db.exec(
        """
        insert into asset_source_link_enrichment (
          id, run_id, asset_id, input_url, final_url, final_domain, canonical_url, og_image_url,
          page_title, og_title, meta_description, og_description, text_excerpt, hero_image_url,
          hero_image_alt, hero_text_excerpt, media_candidates_json, content_type, http_status, redirect_count, truncated,
          fetch_status, error, content_hash, created_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            run_id,
            str(asset["id"]),
            _db_text(result.get("input_url")),
            _db_text(result.get("final_url")),
            _db_text(result.get("final_domain")),
            _db_text(result.get("canonical_url")),
            _db_text(result.get("og_image_url")),
            _db_text(result.get("page_title")),
            _db_text(result.get("og_title")),
            _db_text(result.get("meta_description")),
            _db_text(result.get("og_description")),
            _db_text(result.get("text_excerpt")),
            _db_text(result.get("hero_image_url")),
            _db_text(result.get("hero_image_alt")),
            _db_text(result.get("hero_text_excerpt")),
            _db_text(json.dumps(_normalize_media_candidates(result.get("media_candidates", [])), sort_keys=True)),
            _db_text(result.get("content_type")),
            result.get("http_status"),
            int(result.get("redirect_count") or 0),
            int(result.get("truncated") or 0),
            str(result.get("fetch_status") or ""),
            _db_text(result.get("error")),
            _db_text(result.get("content_hash")),
            created_at,
        ),
    )
    return {
        "ok": True,
        "run_id": run_id,
        "asset_id": str(asset["id"]),
        "fetch_status": str(result.get("fetch_status") or ""),
        "page_title": str(result.get("page_title") or ""),
        "hero_image_url": str(result.get("hero_image_url") or ""),
        "hero_image_alt": str(result.get("hero_image_alt") or ""),
        "hero_text_excerpt": str(result.get("hero_text_excerpt") or ""),
        "media_candidates": _normalize_media_candidates(result.get("media_candidates", [])),
        "promoted_source_url": promoted_url,
        "promoted_hero_image": promoted_hero,
    }
