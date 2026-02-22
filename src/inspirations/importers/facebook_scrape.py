"""Facebook scrape importer.

Reads browser-scraped Facebook saved-items JSON (produced by Opus) and
imports posts into the database. Images are embedded as base64 in the
JSON and are decoded, SHA256-deduped, and written to disk.
"""
from __future__ import annotations

import base64
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


from ..db import Db


def _parse_date(date_str: str | None) -> str | None:
    """Parse 'December 18, 2025' → ISO 8601. Returns None on failure."""
    if not date_str:
        return None
    try:
        dt = datetime.strptime(date_str.strip(), "%B %d, %Y")
        return dt.replace(tzinfo=timezone.utc).isoformat()
    except ValueError:
        return None


def _truncate_title(text: str | None, max_len: int = 200) -> str | None:
    if not text:
        return None
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def import_facebook_scrape(
    db: Db,
    json_dir: Path,
    store_dir: Path,
    limit: int = 0,
) -> dict[str, Any]:
    """Import Facebook saved items from browser scrape JSON files with base64 images."""

    json_files = sorted(json_dir.glob("facebook_scrape_*.json"))

    dest_dir = store_dir / "originals" / "facebook"
    dest_dir.mkdir(parents=True, exist_ok=True)

    files_read = 0
    total_in_json = 0
    imported = 0
    images_saved = 0
    metadata_only_count = 0
    unavailable_count = 0

    now = datetime.now(timezone.utc).isoformat()

    all_posts: list[dict[str, Any]] = []
    for json_file in json_files:
        posts = json.loads(json_file.read_text(encoding="utf-8"))
        all_posts.extend(posts)
        files_read += 1

    total_in_json = len(all_posts)

    if limit:
        all_posts = all_posts[:limit]

    for post in all_posts:
        source_ref = (post.get("post_url") or "").strip()
        if not source_ref:
            continue

        unavailable = bool(post.get("unavailable"))
        if unavailable:
            unavailable_count += 1

        post_text = (post.get("post_text") or "").strip() or None
        images = post.get("images") or []

        # Resolve stored image from base64
        stored_path: str | None = None
        sha256: str | None = None
        image_width: int | None = None
        image_height: int | None = None
        media_status: str

        if images and not unavailable:
            first_image = images[0]
            raw_b64 = first_image.get("base64") or ""
            # Strip data URI prefix
            if "," in raw_b64:
                raw_b64 = raw_b64.split(",", 1)[1]
            try:
                img_bytes = base64.b64decode(raw_b64)
                checksum = hashlib.sha256(img_bytes).hexdigest()
                dest_path = dest_dir / f"{checksum}.jpg"
                if not dest_path.exists():
                    dest_path.write_bytes(img_bytes)
                    images_saved += 1
                stored_path = str(dest_path)
                sha256 = checksum
                image_width = first_image.get("width")
                image_height = first_image.get("height")
                media_status = "image"
            except Exception:
                media_status = "metadata_only"
        else:
            media_status = "metadata_only"
            metadata_only_count += 1

        hashtags_raw = post.get("hashtags") or []
        hashtags = ",".join(str(h) for h in hashtags_raw) if hashtags_raw else None

        engagement = post.get("engagement")
        engagement_json = json.dumps(engagement) if engagement else None

        content_type = (post.get("content_type") or "").strip() or None

        db.exec(
            """
            insert or ignore into assets (
                id, source, source_ref, title, description, post_text,
                board, created_at, imported_at,
                stored_path, sha256,
                media_status, content_kind,
                creator_name, hashtags,
                engagement_json,
                image_width, image_height,
                source_domain
            ) values (
                ?,?,?,?,?,?,
                ?,?,?,
                ?,?,
                ?,?,
                ?,?,
                ?,
                ?,?,
                ?
            )
            """,
            (
                str(uuid.uuid4()),
                "facebook",
                source_ref,
                _truncate_title(post_text),
                post_text,
                post_text,
                (post.get("collection_name") or "").strip() or None,
                _parse_date(post.get("date")),
                now,
                stored_path,
                sha256,
                media_status,
                content_type,
                (post.get("creator_name") or "").strip() or None,
                hashtags,
                engagement_json,
                image_width,
                image_height,
                "facebook.com",
            ),
        )
        imported += 1

    total_assets = db.query_value("select count(*) from assets where source = 'facebook'") or 0

    return {
        "source": "facebook",
        "json_dir": str(json_dir),
        "files_read": files_read,
        "total_in_json": total_in_json,
        "imported": imported,
        "images_saved": images_saved,
        "metadata_only": metadata_only_count,
        "unavailable": unavailable_count,
        "total_assets_for_source": int(total_assets),
    }
