from __future__ import annotations

import hashlib
import json
import re
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..db import Db


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_dict(x: Any) -> dict[str, Any] | None:
    return x if isinstance(x, dict) else None


def _as_list(x: Any) -> list[Any] | None:
    return x if isinstance(x, list) else None


def _extract_external_context(item: dict[str, Any]) -> dict[str, Any] | None:
    atts = _as_list(item.get("attachments"))
    if not atts:
        return None
    first = _as_dict(atts[0])
    if not first:
        return None
    data = _as_list(first.get("data"))
    if not data:
        return None
    d0 = _as_dict(data[0])
    if not d0:
        return None
    return _as_dict(d0.get("external_context"))


_IMAGE_SUFFIX_RE = re.compile(r"\.(jpg|jpeg|png|webp|gif|bmp|svg)(?:\?.*)?$", re.IGNORECASE)


def _is_http_url(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(("http://", "https://"))


def _looks_like_image_url(value: str) -> bool:
    text = (value or "").strip().lower()
    if not text:
        return False
    if _IMAGE_SUFFIX_RE.search(text):
        return True
    return any(part in text for part in (".jpg?", ".jpeg?", ".png?", ".webp?", ".gif?", ".bmp?", ".svg?"))


def _normalize_whitespace(value: str) -> str:
    return " ".join((value or "").replace("\r", " ").replace("\n", " ").split())


def _content_kind_from_title(title: str) -> str:
    t = _normalize_whitespace(title).lower()
    if "saved a reel" in t:
        return "reel"
    if "saved a video" in t:
        return "video"
    if "saved a photo" in t:
        return "photo"
    if "saved a product" in t:
        return "product"
    if "saved a place" in t:
        return "place"
    if "saved a link" in t:
        return "link"
    if "'s post" in t:
        return "post"
    return "other"


def _creator_from_title(title: str) -> str | None:
    t = _normalize_whitespace(title)
    patterns = [
        r"saved a (?:reel|video|photo|link|product) from (.+?)'s post\.?$",
        r"saved (.+?)'s post\.?$",
    ]
    for pat in patterns:
        m = re.search(pat, t, flags=re.IGNORECASE)
        if not m:
            continue
        value = _normalize_whitespace(m.group(1))
        return value or None
    return None


def _domain_from_any(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip().lower()
    if not text:
        return ""
    if text.startswith(("http://", "https://")):
        host = (urlparse(text).hostname or "").strip().lower()
    else:
        host = text.split("/", 1)[0].strip().lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def _stable_item_ref(item: dict[str, Any]) -> str:
    canonical = json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"facebook://saved/{digest}"


def _collection_name(item: dict[str, Any]) -> str:
    atts = _as_list(item.get("attachments")) or []
    if not atts:
        return ""
    first = _as_dict(atts[0]) or {}
    data = _as_list(first.get("data")) or []
    if not data:
        return ""
    d0 = _as_dict(data[0]) or {}
    return _normalize_whitespace(str(d0.get("name") or ""))


def _collection_ref(name: str) -> str:
    digest = hashlib.sha256(name.lower().encode("utf-8")).hexdigest()
    return f"facebook://collection/{digest}"


def _row_for_saved_item(item: dict[str, Any], imported_at: str) -> tuple[Any, ...]:
    ec = _extract_external_context(item) or {}
    source_candidate = ec.get("source")
    source_ref = source_candidate if _is_http_url(source_candidate) else _stable_item_ref(item)
    image_url = source_candidate if _is_http_url(source_candidate) else None
    media_status = "metadata_only"
    if image_url:
        media_status = "image" if _looks_like_image_url(image_url) else "link_only"

    title = _normalize_whitespace(str(item.get("title") or "")) or None
    source_name = _normalize_whitespace(str(ec.get("name") or "")) or None
    description = source_name if source_name and source_name != title else None
    creator_name = _creator_from_title(title or "") or None
    domain = _domain_from_any(ec.get("url")) or _domain_from_any(source_candidate)
    created_at = None
    ts = item.get("timestamp")
    if isinstance(ts, (int, float)):
        created_at = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

    return (
        str(uuid.uuid4()),
        "facebook",
        source_ref,
        title,
        description,
        None,
        created_at,
        imported_at,
        image_url,
        media_status,
        _content_kind_from_title(title or ""),
        creator_name,
        domain or None,
        source_name,
    )


def import_facebook_saved_zip(db: Db, zip_path: Path, limit: int = 0) -> dict[str, Any]:
    """
    Import from a Facebook "Your saved items" export ZIP.

    Observed structure:
      - your_facebook_activity/saved_items_and_collections/your_saved_items.json (dict with key 'saves_v2')
      - items are heterogeneous; many have only a domain name, while a subset contain a usable URL in:
          attachments[0].data[0].external_context.source  (often a direct image URL)
    """
    with zipfile.ZipFile(zip_path) as z:
        saved_path = "your_facebook_activity/saved_items_and_collections/your_saved_items.json"
        collections_path = "your_facebook_activity/saved_items_and_collections/collections.json"
        raw = z.read(saved_path)
        raw_collections = z.read(collections_path) if collections_path in z.namelist() else None

    data = json.loads(raw)
    collections_data = json.loads(raw_collections) if raw_collections else {}
    items = data.get("saves_v2") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ValueError("Expected {saves_v2: [...]} in Facebook saved items JSON")

    imported_at = _now_iso()
    before_total = int(db.query_value("select count(*) from assets where source='facebook'") or 0)
    parsed = 0
    skipped = 0
    skipped_reasons: dict[str, int] = {}

    rows: list[tuple[Any, ...]] = []
    for i, it in enumerate(items):
        if limit and i >= limit:
            break
        if not isinstance(it, dict):
            skipped += 1
            skipped_reasons["non_dict_item"] = skipped_reasons.get("non_dict_item", 0) + 1
            continue
        parsed += 1
        rows.append(_row_for_saved_item(it, imported_at))

    db.executemany(
        """
        insert or ignore into assets
          (
            id, source, source_ref, title, description, board, created_at, imported_at, image_url,
            media_status, content_kind, creator_name, source_domain, source_name
          )
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        rows,
    )
    inserted_rows = db.query(
        """
        select media_status, content_kind
        from assets
        where source='facebook' and imported_at=?
        """,
        (imported_at,),
    )
    inserted_total = len(inserted_rows)
    media_counts: dict[str, int] = {}
    content_kind_counts: dict[str, int] = {}
    for row in inserted_rows:
        media = str(row["media_status"] or "unknown")
        kind = str(row["content_kind"] or "other")
        media_counts[media] = media_counts.get(media, 0) + 1
        content_kind_counts[kind] = content_kind_counts.get(kind, 0) + 1

    existing_items = max(0, parsed - inserted_total)
    after_total = int(db.query_value("select count(*) from assets where source='facebook'") or 0)

    collection_rows: list[tuple[Any, ...]] = []
    parsed_collections = 0
    raw_collections_rows = collections_data.get("collections_v2") if isinstance(collections_data, dict) else None
    if isinstance(raw_collections_rows, list):
        for it in raw_collections_rows:
            if not isinstance(it, dict):
                continue
            name = _collection_name(it)
            if not name:
                continue
            parsed_collections += 1
            created_at = None
            ts = it.get("timestamp")
            if isinstance(ts, (int, float)):
                created_at = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
            collection_rows.append(
                (
                    str(uuid.uuid4()),
                    "facebook",
                    _collection_ref(name),
                    name,
                    created_at,
                    imported_at,
                )
            )
    if collection_rows:
        db.executemany(
            """
            insert or ignore into source_collections
              (id, source, source_ref, name, created_at, imported_at)
            values (?, ?, ?, ?, ?, ?);
            """,
            collection_rows,
        )
    imported_collections = int(
        db.query_value(
            "select count(*) from source_collections where source='facebook' and imported_at=?",
            (imported_at,),
        )
        or 0
    )

    return {
        "source": "facebook",
        "zip": str(zip_path),
        "parsed_items": parsed,
        "candidate_assets": parsed,
        "imported_assets": {
            "total": inserted_total,
            "image": media_counts.get("image", 0),
            "link_only": media_counts.get("link_only", 0),
            "metadata_only": media_counts.get("metadata_only", 0),
        },
        "existing_assets": existing_items,
        "skipped_items": skipped,
        "skip_reasons": skipped_reasons,
        "media_status_counts": media_counts,
        "content_kind_counts": content_kind_counts,
        "collections": {
            "parsed": parsed_collections,
            "imported": imported_collections,
        },
        "note": "Importer now stores URL-backed and reference-only Facebook saves; re-import remains idempotent.",
        "total_assets_for_source_before": before_total,
        "total_assets_for_source": after_total,
    }
