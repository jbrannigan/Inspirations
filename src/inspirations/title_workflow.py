from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from .db import Db, _looks_like_scan_autogen_title as _db_looks_like_scan_autogen_title
from .title_audit import (
    _FB_SAVED_LINK_TITLE_RE,
    _JUNK_SHORT_DOMAIN_RE,
    _NOISE_PREFIX_RE,
    _clean_alt_text,
    _clean_source_name,
    _host_title,
    _slug_title_from_source_ref,
    concise_title,
    propose_title,
    strip_facebook_engagement_prefix,
)

_SCAN_DOC_SUFFIX_RE = re.compile(r"(\s-\sdoc\s+\d+(?:\s+p\d+)?)\s*$", re.IGNORECASE)
_TITLE_DYNAMIC_SEGMENT_RE = re.compile(
    r"^(?:home|index|main|blog|news|latest|feed|explore|discover|topics?|category|categories|tag|tags|shop|products?|wirecutter)$",
    re.IGNORECASE,
)
_TITLE_DYNAMIC_QUERY_KEY_RE = re.compile(r"^(?:page|p|offset|start|sort|view)$", re.IGNORECASE)
_TITLE_GENERIC_PREVIEW_RE = re.compile(
    r"(?:og[_-]?(?:image|default|general)|default(?:[_-]?image)?|site[_-]?icon|logo|placeholder)",
    re.IGNORECASE,
)

_ORIGIN_PRIORITY = {
    "source_native": 100,
    "imported": 92,
    "title_audit_old": 88,
    "ai_suggested": 72,
    "derived": 48,
    "manual_working": 18,
    "title_audit": 12,
}

_ORIGIN_LABELS = {
    "source_native": "Imported source title",
    "imported": "Imported title",
    "title_audit_old": "Pre-audit title",
    "ai_suggested": "AI-suggested title",
    "derived": "Derived title",
    "manual_working": "Working title",
    "title_audit": "Title audit title",
}

_SUGGESTION_LABELS = {
    "empty_title_ai_summary": "Suggested from AI summary",
    "empty_title_seo_alt": "Suggested from alt text",
    "empty_title_source_slug": "Suggested from source link",
    "junk_domain_source_slug": "Suggested from source link",
    "fb_saved_link_slug": "Suggested from source link",
    "fb_saved_link_source_name": "Suggested from source name",
    "fb_saved_link_host": "Suggested from source host",
    "scan_ai_summary": "Suggested from image analysis",
    "unusable_title_ai_summary": "Suggested from AI summary",
    "unusable_title_seo_alt": "Suggested from alt text",
    "shorten_existing_title": "Shortened for easier reuse",
    "shorten_ai_summary": "Shortened from AI summary",
    "shorten_seo_alt": "Shortened from alt text",
    "strip_engagement_prefix": "Suggested without Facebook engagement counts",
}


class TitleConflictError(RuntimeError):
    pass


class TitleNotFoundError(RuntimeError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _scan_doc_suffix(title: str) -> str:
    match = _SCAN_DOC_SUFFIX_RE.search(str(title or "").strip())
    return str(match.group(1) or "") if match else ""


def _preserve_scan_doc_suffix(current_title: str, next_title: str) -> str:
    suffix = _scan_doc_suffix(current_title)
    base = str(next_title or "").strip()
    if not base:
        return ""
    return f"{base}{suffix}" if suffix else base


def _display_scan_title(title: str) -> str:
    text = _SCAN_DOC_SUFFIX_RE.sub("", str(title or "").strip()).strip()
    return text or "Scanned inspiration"


def _looks_like_scan_autogen_title(title: str) -> bool:
    return bool(_db_looks_like_scan_autogen_title(str(title or "")))


def _title_case_words(text: str) -> str:
    out: list[str] = []
    for word in str(text or "").split():
        if len(word) <= 2:
            out.append(word.upper())
        else:
            out.append(word[:1].upper() + word[1:].lower())
    return " ".join(out)


def _saved_link_fallback_title(asset: dict[str, Any]) -> str:
    title = str(asset.get("title") or "").strip()
    match = _FB_SAVED_LINK_TITLE_RE.search(title)
    if not match:
        return ""
    source_name = _clean_source_name(str(match.group(1) or "").strip())
    source_ref = str(asset.get("source_ref") or "").strip()
    slug = _slug_title_from_source_ref(source_ref)
    host = _host_title(source_ref)
    if slug:
        return f"{source_name}: {slug}" if source_name else slug
    if source_name:
        return f"{source_name} link"
    if host:
        return _title_case_words(host.replace(".", " "))
    return ""


def _current_title_unusable(asset: dict[str, Any], title: str) -> bool:
    source = str(asset.get("source") or "").strip().lower()
    text = str(title or "").strip()
    if not text:
        return True
    if source == "facebook" and _FB_SAVED_LINK_TITLE_RE.search(text):
        return True
    if _JUNK_SHORT_DOMAIN_RE.search(text) and len(text) < 48:
        return True
    if source == "scan" and _looks_like_scan_autogen_title(text):
        return True
    if re.match(r"^https?://", text, re.IGNORECASE):
        return True
    return False


def _title_is_verbose(title: str) -> bool:
    text = _SCAN_DOC_SUFFIX_RE.sub("", str(title or "").strip()).strip()
    if not text:
        return False
    if len(text) >= 88:
        return True
    if _NOISE_PREFIX_RE.search(text):
        return True
    if text.count(".") >= 1 and len(text) >= 54:
        return True
    if ";" in text and len(text) >= 48:
        return True
    if "," in text and len(text) >= 78:
        return True
    return False


def _title_quality_penalty(asset: dict[str, Any], title: str) -> int:
    text = str(title or "").strip()
    if not text:
        return -100
    penalty = 0
    if _current_title_unusable(asset, text):
        penalty -= 60
    if _title_is_verbose(text):
        penalty -= 12
    if len(text) < 3:
        penalty -= 18
    return penalty


def _best_original_title(
    asset: dict[str, Any],
    provenance_rows: list[dict[str, Any]],
    title_audit_old: dict[str, Any] | None,
) -> tuple[str, str, float]:
    candidates: list[tuple[int, str, str, float]] = []
    for row in provenance_rows:
        origin_type = str(row.get("origin_type") or "").strip().lower()
        if origin_type in {"manual_working", "title_audit"}:
            continue
        title = str(row.get("field_value") or "").strip()
        if not title:
            continue
        score = _ORIGIN_PRIORITY.get(origin_type, 25) + _title_quality_penalty(asset, title)
        confidence = float(row.get("confidence") or 0.0)
        candidates.append((score, title, origin_type, confidence))
    if title_audit_old:
        old_title = str(title_audit_old.get("old_title") or "").strip()
        if old_title:
            score = _ORIGIN_PRIORITY["title_audit_old"] + _title_quality_penalty(asset, old_title)
            candidates.append((score, old_title, "title_audit_old", 0.9))
    current_title = str(asset.get("title") or "").strip()
    if current_title and not candidates:
        candidates.append((35 + _title_quality_penalty(asset, current_title), current_title, "", 0.4))
    if not candidates:
        return ("", "", 0.0)
    candidates.sort(key=lambda item: (item[0], item[3], len(item[1])), reverse=True)
    _, title, origin_type, confidence = candidates[0]
    return (title, origin_type, confidence)


def _suggested_title(asset: dict[str, Any]) -> tuple[str, str]:
    source = str(asset.get("source") or "").strip().lower()
    current = str(asset.get("title") or "").strip()
    source_ref = str(asset.get("source_ref") or "").strip()
    ai_summary = str(asset.get("ai_summary") or "").strip()
    seo_alt = str(asset.get("seo_alt_text") or "").strip()

    if source == "facebook":
        cleaned = strip_facebook_engagement_prefix(current)
        if cleaned and cleaned != current:
            return (cleaned, "strip_engagement_prefix")

    proposal = propose_title(
        source=source,
        old_title=current,
        source_ref=source_ref,
        ai_summary=ai_summary,
        seo_alt_text=seo_alt,
    )
    if proposal:
        suggested, technique = proposal
        if source == "scan":
            suggested = _preserve_scan_doc_suffix(current, suggested)
        return (str(suggested or "").strip(), technique)

    base = ""
    technique = ""
    if source == "scan" and _looks_like_scan_autogen_title(current):
        if ai_summary:
            base = ai_summary
            technique = "scan_ai_summary"
        elif seo_alt:
            base = _clean_alt_text(seo_alt)
            technique = "unusable_title_seo_alt"
    elif _current_title_unusable(asset, current):
        if ai_summary:
            base = ai_summary
            technique = "unusable_title_ai_summary"
        elif seo_alt:
            base = _clean_alt_text(seo_alt)
            technique = "unusable_title_seo_alt"
    elif _title_is_verbose(current):
        base = current
        technique = "shorten_existing_title"
        if ai_summary and len(ai_summary) < len(current):
            base = ai_summary
            technique = "shorten_ai_summary"
        elif _clean_alt_text(seo_alt) and len(_clean_alt_text(seo_alt)) < len(base):
            base = _clean_alt_text(seo_alt)
            technique = "shorten_seo_alt"

    if not base:
        return ("", "")

    suggested = concise_title(base)
    if source == "scan":
        suggested = _preserve_scan_doc_suffix(current, suggested)
    suggested = str(suggested or "").strip(" ,;:-")
    if not suggested or suggested == current:
        return ("", "")
    return (suggested, technique)


def _display_title(asset: dict[str, Any], working_title: str, suggested_title: str, best_original_title: str) -> tuple[str, str]:
    source = str(asset.get("source") or "").strip().lower()
    working = str(working_title or "").strip()
    if working and not _current_title_unusable(asset, working):
        return (_display_scan_title(working) if source == "scan" else working, "working_title")
    if suggested_title:
        return (_display_scan_title(suggested_title) if source == "scan" else suggested_title, "suggested_title")
    if best_original_title:
        return (_display_scan_title(best_original_title) if source == "scan" else best_original_title, "best_original_title")
    fallback = _saved_link_fallback_title(asset)
    if fallback:
        return (fallback, "source_ref")
    ai_summary = str(asset.get("ai_summary") or "").strip()
    if ai_summary:
        return (concise_title(ai_summary), "ai_summary")
    seo_alt = _clean_alt_text(str(asset.get("seo_alt_text") or "").strip())
    if seo_alt:
        return (concise_title(seo_alt), "seo_alt_text")
    board = str(asset.get("board") or "").strip()
    if board:
        return (board, "board")
    creator = str(asset.get("creator_name") or "").strip()
    if creator:
        return (f"via {creator}", "creator_name")
    return ("(untitled)", "untitled")


def _title_quality(asset: dict[str, Any], title_info: dict[str, Any]) -> dict[str, str]:
    source = str(asset.get("source") or "").strip().lower()
    title = str(asset.get("title") or "").strip()
    source_ref = str(asset.get("source_ref") or "").strip()
    image_url = str(asset.get("image_url") or "").strip()
    suggestion = str(title_info.get("suggested_title") or "").strip()

    if not title:
        if suggestion:
            return {
                "kind": "title-suggested",
                "label": "Title Needed",
                "tooltip": "This item needs a shorter working title. A suggestion is available.",
            }
        return {"kind": "title-missing", "label": "Title Needed", "tooltip": "This item needs a working title."}

    is_generic_saved_link = source == "facebook" and _FB_SAVED_LINK_TITLE_RE.search(title)
    if is_generic_saved_link:
        host = ""
        root_like_path = False
        dynamic_path = False
        dynamic_query = False
        try:
            parsed = urlparse(source_ref)
            host = (parsed.hostname or "").replace("www.", "")
            parts = [p for p in parsed.path.split("/") if p]
            root_like_path = len(parts) <= 1
            last = str(parts[-1] if parts else "").strip().lower()
            dynamic_path = root_like_path or bool(_TITLE_DYNAMIC_SEGMENT_RE.search(last))
            if parsed.query:
                for pair in parsed.query.split("&"):
                    key = pair.split("=", 1)[0].strip().lower()
                    if _TITLE_DYNAMIC_QUERY_KEY_RE.search(key):
                        dynamic_query = True
                        break
        except Exception:
            host = ""
        generic_preview = bool(_TITLE_GENERIC_PREVIEW_RE.search(image_url.lower()))
        dynamic = dynamic_path or dynamic_query or generic_preview
        if dynamic:
            host_suffix = f" ({host})" if host else ""
            return {
                "kind": "dynamic-link",
                "label": "Dynamic Link",
                "tooltip": f"Title may drift over time because this source looks dynamic{host_suffix}.",
            }
        return {
            "kind": "title-check",
            "label": "Title Check",
            "tooltip": "Saved-link title was auto-generated. Verify before sharing.",
        }

    if suggestion and _title_is_verbose(title):
        return {
            "kind": "title-suggested",
            "label": "Shorten",
            "tooltip": "A shorter working title is available for this item.",
        }

    return {"kind": "", "label": "", "tooltip": ""}


def load_title_context(
    db: Db,
    *,
    asset_ids: list[str],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]]]:
    ids = [str(asset_id or "").strip() for asset_id in asset_ids if str(asset_id or "").strip()]
    if not ids:
        return ({}, {})
    placeholders = ",".join(["?"] * len(ids))
    provenance_rows = db.query(
        f"""
        select asset_id, field_value, origin_type, origin_ref, actor, confidence, created_at, is_current
        from asset_field_provenance
        where field_name = 'title'
          and asset_id in ({placeholders})
        order by asset_id asc, is_current desc, created_at desc, id desc
        """,
        tuple(ids),
    )
    provenance_by_asset: dict[str, list[dict[str, Any]]] = {}
    for row in provenance_rows:
        asset_id = str(row["asset_id"] or "").strip()
        if not asset_id:
            continue
        provenance_by_asset.setdefault(asset_id, []).append(dict(row))

    audit_rows = db.query(
        f"""
        select ta.asset_id, ta.old_title, ta.applied_at
        from title_audit_applied ta
        join (
            select asset_id, max(applied_at) as max_applied_at
            from title_audit_applied
            where undone_at is null
              and asset_id in ({placeholders})
            group by asset_id
        ) latest
          on latest.asset_id = ta.asset_id
         and latest.max_applied_at = ta.applied_at
        where ta.undone_at is null
        """,
        tuple(ids),
    )
    audit_by_asset = {
        str(row["asset_id"] or "").strip(): dict(row)
        for row in audit_rows
        if str(row["asset_id"] or "").strip()
    }
    return (provenance_by_asset, audit_by_asset)


def build_title_info(
    asset: dict[str, Any],
    *,
    provenance_rows: list[dict[str, Any]] | None = None,
    title_audit_old: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rows = list(provenance_rows or [])
    working_title = str(asset.get("title") or "").strip()
    current_row = rows[0] if rows and int(rows[0].get("is_current") or 0) == 1 else None
    best_original_title, best_original_origin_type, best_original_confidence = _best_original_title(
        asset,
        rows,
        title_audit_old,
    )
    suggested_title, suggestion_reason = _suggested_title(asset)
    display_title, display_source = _display_title(asset, working_title, suggested_title, best_original_title)
    info: dict[str, Any] = {
        "working_title": working_title,
        "working_origin_type": str((current_row or {}).get("origin_type") or "").strip(),
        "working_origin_label": _ORIGIN_LABELS.get(str((current_row or {}).get("origin_type") or "").strip(), ""),
        "best_original_title": best_original_title,
        "best_original_origin_type": best_original_origin_type,
        "best_original_origin_label": _ORIGIN_LABELS.get(best_original_origin_type, ""),
        "best_original_confidence": round(float(best_original_confidence or 0.0), 3),
        "suggested_title": suggested_title,
        "suggestion_reason": suggestion_reason,
        "suggestion_label": _SUGGESTION_LABELS.get(suggestion_reason, ""),
        "display_title": display_title,
        "display_source": display_source,
        "has_override": bool(working_title and best_original_title and working_title != best_original_title),
    }
    info["quality"] = _title_quality(asset, info)
    return info


def enrich_assets_with_title_info(db: Db, assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    asset_ids = [str(asset.get("id") or "").strip() for asset in assets if str(asset.get("id") or "").strip()]
    provenance_by_asset, audit_by_asset = load_title_context(db, asset_ids=asset_ids)
    for asset in assets:
        asset_id = str(asset.get("id") or "").strip()
        title_info = build_title_info(
            asset,
            provenance_rows=provenance_by_asset.get(asset_id, []),
            title_audit_old=audit_by_asset.get(asset_id),
        )
        asset["title_info"] = title_info
        asset["display_title"] = title_info["display_title"]
        asset["best_original_title"] = title_info["best_original_title"]
        asset["suggested_title"] = title_info["suggested_title"]
        asset["title_quality"] = title_info["quality"]
    return assets


def apply_working_title(
    db: Db,
    *,
    asset_id: str,
    title: str,
    actor_name: str,
    expected_title: str | None = None,
    origin_ref: str = "api:title",
) -> dict[str, Any]:
    rows = db.query(
        """
        select a.id, a.source, a.source_ref, a.title, a.description, a.board, a.notes,
               a.media_status, a.content_kind, a.creator_name, a.source_domain, a.source_name,
               coalesce(
                 (select ai.summary from asset_ai ai where ai.asset_id=a.id order by ai.created_at desc limit 1),
                 a.ai_summary
               ) as ai_summary,
               a.created_at, a.imported_at, a.image_url, a.stored_path, a.thumb_path,
               a.triage_status, a.needs_annotation, a.source_url, a.seo_alt_text,
               a.post_text, a.hashtags, a.engagement_json, a.dominant_color,
               a.image_width, a.image_height, a.closeup_desc,
               a.flagged, a.flagged_by, a.flagged_note,
               a.tagged, a.tagged_by, a.tagged_note
        from assets a
        where a.id = ?
        limit 1
        """,
        (asset_id,),
    )
    if not rows:
        raise TitleNotFoundError(asset_id)
    asset = dict(rows[0])
    current_title = str(asset.get("title") or "").strip()
    if expected_title is not None and str(expected_title or "").strip() != current_title:
        raise TitleConflictError("title changed since modal was opened")

    clean_title = str(title or "").strip()
    if str(asset.get("source") or "").strip().lower() == "scan":
        clean_title = _preserve_scan_doc_suffix(current_title, clean_title)
    if not clean_title:
        raise ValueError("title is required")
    if clean_title == current_title:
        return enrich_assets_with_title_info(db, [asset])[0]

    db.exec("update assets set title = ? where id = ?", (clean_title, asset_id))
    now = _now_iso()
    db.exec(
        """
        update asset_field_provenance
        set superseded_at = ?, is_current = 0
        where asset_id = ? and field_name = 'title' and is_current = 1
        """,
        (now, asset_id),
    )
    db.exec(
        """
        insert into asset_field_provenance
          (id, asset_id, field_name, field_value, origin_type, origin_ref, actor,
           confidence, created_at, superseded_at, is_current)
        values (?, ?, 'title', ?, 'manual_working', ?, ?, ?, ?, null, 1)
        """,
        (
            str(uuid.uuid4()),
            asset_id,
            clean_title,
            origin_ref,
            actor_name or "ui",
            0.99,
            now,
        ),
    )
    asset["title"] = clean_title
    return enrich_assets_with_title_info(db, [asset])[0]
