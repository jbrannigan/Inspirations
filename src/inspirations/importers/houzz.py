"""Houzz ideabook importer.

Reads a JSON file produced by the Safari scraper (houzz_ideabook_final.json)
and imports Houzz saved photos into the database. Downloads images from
Houzz CDN.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..db import Db
from ..storage import download_url_to_store


# Houzz category IDs to human-readable room names
HOUZZ_CATEGORIES: dict[int, str] = {
    1001: "Exterior",
    1002: "Entry",
    1004: "Living Room",
    1005: "Kitchen",
    1007: "Bathroom",
    1013: "Bedroom",
    1014: "Nursery",
    1018: "Dining Room",
    1019: "Patio",
    1029: "Closet",
    1: "Home Design",
    4: "Landscape",
}


def _title_from_slug(slug: str) -> str:
    """Convert a URL slug to a readable title."""
    # "livable-luxury-traditional-kitchen-san-francisco" -> "Livable Luxury Traditional Kitchen San Francisco"
    return slug.replace("-", " ").strip().title() if slug else ""


def _build_image_url(external_id: str, content_modified: str, width: int = 800, height: int = 600) -> str:
    """Construct a Houzz CDN image URL from external ID components."""
    return f"https://st.hzcdn.com/fimgs/{external_id}_{content_modified}-w{width}-h{height}-b0-p0--.jpg"


def _extract_board_from_description(desc: str) -> str | None:
    """Try to extract a room/board from the auto-description.

    Houzz auto-descriptions look like:
      "Kitchen - traditional kitchen idea in San Francisco"
      "Small elegant master gray tile and stone tile marble floor bathroom"
    """
    if not desc:
        return None
    desc_lower = desc.lower()
    rooms = [
        "kitchen", "bathroom", "bedroom", "living room", "dining room",
        "entry", "entryway", "patio", "exterior", "nursery", "closet",
        "laundry", "hallway", "staircase", "home office", "mudroom",
        "porch", "pool", "landscape", "garage", "basement",
    ]
    for room in rooms:
        if room in desc_lower:
            return room.title()
    return None


def import_houzz_ideabook(
    db: Db,
    json_path: Path,
    store_dir: Path,
    download_images: bool = True,
    limit: int = 0,
) -> dict[str, Any]:
    """Import Houzz ideabook items from scraped JSON.

    Parameters
    ----------
    db : Db
        Open database handle.
    json_path : Path
        Path to the houzz_ideabook_final.json file.
    store_dir : Path
        Root of the media store (contains originals/ and thumbs/).
    download_images : bool
        If True, download images from Houzz CDN.
    limit : int
        Max items to import (0 = all).
    """
    raw = json.loads(json_path.read_text(encoding="utf-8"))
    items: list[dict[str, Any]] = raw if isinstance(raw, list) else raw.get("items", [])

    dest_dir = store_dir / "originals" / "houzz"
    dest_dir.mkdir(parents=True, exist_ok=True)

    total_in_json = len(items)
    imported = 0
    skipped_dup = 0
    skipped_no_id = 0
    images_downloaded = 0
    images_failed = 0

    if limit:
        items = items[:limit]

    now = datetime.now(timezone.utc).isoformat()

    # Pre-fetch existing source_refs for this source to skip known items
    existing_refs: set[str] = set()
    for row in db.query("select source_ref from assets where source = 'houzz'"):
        existing_refs.add(row["source_ref"])

    pending_refs: set[str] = set()

    for item in items:
        houzz_id = str(item.get("houzz_id", "")).strip()
        if not houzz_id:
            skipped_no_id += 1
            continue

        source_ref = f"houzz://photo/{houzz_id}"

        if source_ref in existing_refs or source_ref in pending_refs:
            skipped_dup += 1
            continue
        pending_refs.add(source_ref)

        # Resolve title
        title = (item.get("title") or "").strip()
        if not title:
            title = _title_from_slug(item.get("slug", ""))
        if not title:
            title = f"Houzz Photo {houzz_id}"

        # Resolve image URL
        image_url: str = ""
        ext_id = (item.get("image_external_id") or "").strip()
        content_mod = (item.get("image_content_modified") or "").strip()
        if ext_id and content_mod:
            image_url = _build_image_url(ext_id, content_mod)
        else:
            image_url = (item.get("image_url") or "").strip()

        # If we still don't have an image URL, try to construct from the photo page
        if not image_url:
            # Use the Houzz photo page URL as fallback
            image_url = (item.get("url") or "").strip()

        # Board/room from auto-description, category, or slug
        auto_desc = (item.get("autoDescription") or "").strip()
        board = _extract_board_from_description(auto_desc)
        if not board:
            cat_id = item.get("categoryId")
            if cat_id:
                try:
                    board = HOUZZ_CATEGORIES.get(int(cat_id))
                except (ValueError, TypeError):
                    pass
        if not board:
            # Try slug
            board = _extract_board_from_description(
                (item.get("slug") or "").replace("-", " ")
            )

        # Download image
        stored_path: str | None = None
        sha256: str | None = None

        if download_images and image_url and "hzcdn.com" in image_url:
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

        media_status = "image" if stored_path else ("link_only" if image_url else "metadata_only")

        houzz_url = (item.get("url") or "").strip()
        owner_name = (item.get("owner_name") or "").strip() or None
        comment = (item.get("comment") or "").strip() or None

        db.exec(
            """
            insert or ignore into assets (
                id, source, source_ref, title, description, board,
                imported_at, image_url,
                stored_path, sha256,
                media_status, content_kind,
                source_url, source_domain,
                seo_alt_text, creator_name, notes
            ) values (
                ?,?,?,?,?,?,
                ?,?,
                ?,?,
                ?,?,
                ?,?,
                ?,?,?
            )
            """,
            (
                str(uuid.uuid4()),
                "houzz",
                source_ref,
                title,
                auto_desc or None,
                board,
                now,
                image_url or None,
                stored_path,
                sha256,
                media_status,
                "houzz_photo",
                houzz_url or None,
                "houzz.com",
                auto_desc or None,
                owner_name,
                comment,
            ),
        )
        imported += 1

    total_assets = db.query_value("select count(*) from assets where source = 'houzz'") or 0

    return {
        "source": "houzz",
        "json_path": str(json_path),
        "total_in_json": total_in_json,
        "imported": imported,
        "skipped_dup": skipped_dup,
        "skipped_no_id": skipped_no_id,
        "images_downloaded": images_downloaded,
        "images_failed": images_failed,
        "total_assets_for_source": int(total_assets),
    }
