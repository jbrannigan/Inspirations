"""Pinterest scrape importer.

Reads browser-scraped Pinterest JSON (produced by Opus) and imports pins
into the database. Matches existing stored images via an optional image map
to avoid re-downloading files already on disk.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..db import Db
from ..storage import download_url_to_store


def import_pinterest_scrape(
    db: Db,
    json_path: Path,
    store_dir: Path,
    image_map_path: Path | None = None,
    download_missing: bool = True,
    limit: int = 0,
) -> dict[str, Any]:
    """Import pins from browser scrape JSON, matching existing images by URL."""

    pins: list[dict[str, Any]] = json.loads(json_path.read_text(encoding="utf-8"))

    # Load image map if provided: {image_url: {stored_path, sha256}}
    image_map: dict[str, dict[str, str]] = {}
    if image_map_path and image_map_path.exists():
        image_map = json.loads(image_map_path.read_text(encoding="utf-8"))

    dest_dir = store_dir / "originals" / "pinterest"
    dest_dir.mkdir(parents=True, exist_ok=True)

    total_in_json = len(pins)
    imported = 0
    skipped_no_url = 0
    images_matched = 0
    images_downloaded = 0
    images_failed = 0

    if limit:
        pins = pins[:limit]

    now = datetime.now(timezone.utc).isoformat()

    for pin in pins:
        source_ref = (pin.get("pin_url") or "").strip()
        if not source_ref:
            skipped_no_url += 1
            continue

        image_url = (pin.get("image_url") or "").strip()
        if not image_url:
            skipped_no_url += 1
            continue

        hashtags_raw = pin.get("hashtags") or []
        hashtags = ",".join(str(h) for h in hashtags_raw) if hashtags_raw else None

        engagement: dict[str, Any] = {}
        if pin.get("repin_count") is not None:
            engagement["repins"] = pin["repin_count"]
        if pin.get("comment_count") is not None:
            engagement["comments"] = pin["comment_count"]
        engagement_json = json.dumps(engagement) if engagement else None

        rich_meta = pin.get("rich_metadata")
        scrape_json = json.dumps(rich_meta) if rich_meta else None

        # Resolve stored image
        stored_path: str | None = None
        sha256: str | None = None

        if image_url in image_map:
            entry = image_map[image_url]
            stored_path = entry.get("stored_path")
            sha256 = entry.get("sha256")
            images_matched += 1
        elif download_missing:
            try:
                stem = str(uuid.uuid4())
                path, checksum, _ = download_url_to_store(
                    url=image_url,
                    dest_dir=dest_dir,
                    filename_stem=stem,
                )
                stored_path = str(path)
                sha256 = checksum
                images_downloaded += 1
            except Exception:
                images_failed += 1

        db.exec(
            """
            insert or ignore into assets (
                id, source, source_ref, title, description, board,
                created_at, imported_at, image_url,
                stored_path, sha256,
                media_status, content_kind,
                source_url, source_domain,
                seo_alt_text, closeup_desc,
                dominant_color, hashtags,
                image_width, image_height,
                engagement_json, scrape_json
            ) values (
                ?,?,?,?,?,?,
                ?,?,?,
                ?,?,
                ?,?,
                ?,?,
                ?,?,
                ?,?,
                ?,?,
                ?,?
            )
            """,
            (
                str(uuid.uuid4()),
                "pinterest",
                source_ref,
                (pin.get("title") or "").strip() or None,
                (pin.get("description") or "").strip() or None,
                (pin.get("board_name") or "").strip() or None,
                (pin.get("created_at") or "").strip() or None,
                now,
                image_url,
                stored_path,
                sha256,
                "image",
                "pin",
                (pin.get("source_url") or "").strip() or None,
                (pin.get("source_domain") or "").strip() or None,
                (pin.get("seo_alt_text") or "").strip() or None,
                (pin.get("closeup_desc") or "").strip() or None,
                (pin.get("dominant_color") or "").strip() or None,
                hashtags,
                pin.get("image_width"),
                pin.get("image_height"),
                engagement_json,
                scrape_json,
            ),
        )
        imported += 1

    total_assets = db.query_value("select count(*) from assets where source = 'pinterest'") or 0

    return {
        "source": "pinterest",
        "json_path": str(json_path),
        "total_in_json": total_in_json,
        "imported": imported,
        "skipped_no_url": skipped_no_url,
        "images_matched": images_matched,
        "images_downloaded": images_downloaded,
        "images_failed": images_failed,
        "total_assets_for_source": int(total_assets),
    }
