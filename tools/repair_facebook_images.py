#!/usr/bin/env python3
"""Repair Facebook asset images from the original Word doc export.

The merge_and_capture_facebook.py tool replaced original scrape thumbnails
with incorrectly-captured images (it grabbed the largest fbcdn image on
each post page, which was often wrong). This script restores correct images
from the Word doc where each image is paired with its URL in document order.

Usage:
    python3 tools/repair_facebook_images.py [--dry-run]
"""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile

PROJECT = Path(__file__).resolve().parent.parent
DOCX_PATH = PROJECT / "imports" / "raw" / "Leslies Facebook Saves.docx"
DB_PATH = PROJECT / "data" / "inspirations.sqlite"
STORE_DIR = PROJECT / "store" / "originals" / "facebook"
THUMB_DIR = PROJECT / "store" / "thumbs"

DRY_RUN = "--dry-run" in sys.argv


def extract_pairs_from_docx(docx_path: Path) -> list[tuple[str, str]]:
    """Extract (facebook_url, image_filename) pairs from the Word doc.

    The document structure repeats: LINK, LINK, IMAGE, LINK, ...
    Each IMAGE is paired with the Facebook post URL that precedes it.
    """
    with ZipFile(docx_path) as z:
        # Parse relationships for rId -> target mapping
        with z.open("word/_rels/document.xml.rels") as f:
            rels_root = ET.parse(f).getroot()

        hyperlink_map: dict[str, str] = {}
        image_map: dict[str, str] = {}

        for rel in rels_root:
            rid = rel.get("Id", "")
            target = rel.get("Target", "")
            rtype = rel.get("Type", "")
            if "hyperlink" in rtype:
                hyperlink_map[rid] = target
            elif "image" in rtype:
                image_map[rid] = target

        # Parse document.xml for rId references in document order
        with z.open("word/document.xml") as f:
            content = f.read().decode("utf-8", errors="replace")

    rid_pattern = re.compile(r'r:(?:id|embed)="(rId\d+)"', re.IGNORECASE)
    rids_in_order = rid_pattern.findall(content)

    pairs: list[tuple[str, str]] = []
    last_fb_url: str | None = None

    for rid in rids_in_order:
        if rid in hyperlink_map:
            url = hyperlink_map[rid].replace("&amp;", "&")
            if "facebook.com" in url and "list_id=" not in url:
                last_fb_url = url
        elif rid in image_map and last_fb_url:
            pairs.append((last_fb_url, image_map[rid]))
            last_fb_url = None

    return pairs


def extract_video_id(url: str) -> str | None:
    """Extract the numeric ID from a Facebook URL for cross-matching."""
    for pat in [r"/reel/(\d+)", r"v=(\d+)", r"/permalink/(\d+)", r"/posts/(\d+)"]:
        m = re.search(pat, url)
        if m:
            return m.group(1)
    return None


def main():
    if not DOCX_PATH.exists():
        print(f"ERROR: Word doc not found at {DOCX_PATH}")
        sys.exit(1)
    if not DB_PATH.exists():
        print(f"ERROR: Database not found at {DB_PATH}")
        sys.exit(1)

    print(f"{'DRY RUN — no changes will be made' if DRY_RUN else 'LIVE RUN'}")
    print(f"Word doc: {DOCX_PATH}")
    print(f"Database: {DB_PATH}")
    print()

    # Step 1: Load DB assets
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row

    db_assets: dict[str, dict] = {}  # source_ref -> row data
    db_by_vid: dict[str, str] = {}   # video_id -> source_ref

    for row in db.execute(
        "SELECT id, source_ref, sha256, stored_path FROM assets WHERE source='facebook'"
    ).fetchall():
        ref = row["source_ref"]
        db_assets[ref] = dict(row)
        vid = extract_video_id(ref)
        if vid:
            db_by_vid[vid] = ref

    print(f"DB Facebook assets: {len(db_assets)}")

    # Step 2: Extract pairs from Word doc
    print("Parsing Word doc...")
    pairs = extract_pairs_from_docx(DOCX_PATH)
    print(f"Image-URL pairs extracted: {len(pairs)}")

    # Step 3: Match pairs to DB and replace images
    STORE_DIR.mkdir(parents=True, exist_ok=True)

    updated = 0
    not_in_db = 0
    read_errors = 0
    old_files_to_remove: list[str] = []

    with ZipFile(DOCX_PATH) as z:
        for url, img_file in pairs:
            # Find matching DB entry
            db_ref: str | None = None
            if url in db_assets:
                db_ref = url
            else:
                vid = extract_video_id(url)
                if vid and vid in db_by_vid:
                    db_ref = db_by_vid[vid]

            if not db_ref:
                not_in_db += 1
                continue

            asset = db_assets[db_ref]

            # Read image from docx
            try:
                img_data = z.read(f"word/{img_file}")
            except (KeyError, Exception):
                read_errors += 1
                continue

            new_sha = hashlib.sha256(img_data).hexdigest()
            old_sha = asset["sha256"]
            old_path = asset["stored_path"]

            if new_sha == old_sha:
                continue  # Already correct

            new_path = STORE_DIR / f"{new_sha}.jpg"

            if not DRY_RUN:
                # Write new image
                if not new_path.exists():
                    new_path.write_bytes(img_data)

                # Update DB
                db.execute(
                    "UPDATE assets SET sha256=?, stored_path=?, thumb_path=NULL WHERE id=?",
                    (new_sha, str(new_path), asset["id"]),
                )

                # Track old file for cleanup
                if old_path and old_path != str(new_path) and os.path.exists(old_path):
                    old_files_to_remove.append(old_path)

                # Remove old thumbnail if it exists
                old_thumb = THUMB_DIR / f"{asset['id']}.webp"
                if old_thumb.exists():
                    old_thumb.unlink()

            updated += 1

            if updated <= 5:
                print(f"  [{updated}] {db_ref[:70]}")
                print(f"       old: {old_sha[:16]}... -> new: {new_sha[:16]}...")

    if not DRY_RUN:
        db.commit()

    db.close()

    print(f"\nResults:")
    print(f"  Updated: {updated}")
    print(f"  Not in DB: {not_in_db}")
    print(f"  Read errors: {read_errors}")
    print(f"  Old files to clean: {len(old_files_to_remove)}")

    if DRY_RUN:
        print(f"\nDry run complete. Re-run without --dry-run to apply changes.")
    else:
        print(f"\nImages updated. Run thumbnail regeneration to create new thumbs:")
        print(f"  PYTHONPATH=src python3 -m inspirations --db data/inspirations.sqlite --store store thumbs")

        # Clean up old image files that are no longer referenced
        cleaned = 0
        for old_file in old_files_to_remove:
            # Check if any other asset still references this file
            db2 = sqlite3.connect(str(DB_PATH))
            still_used = db2.execute(
                "SELECT COUNT(*) FROM assets WHERE stored_path=?", (old_file,)
            ).fetchone()[0]
            db2.close()
            if still_used == 0 and os.path.exists(old_file):
                os.remove(old_file)
                cleaned += 1
        if cleaned:
            print(f"  Cleaned up {cleaned} orphaned image files")


if __name__ == "__main__":
    main()
