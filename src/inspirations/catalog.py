"""Markdown catalog generator for AI-powered chat navigation.

Generates a hierarchical set of markdown files from the database that Claude
can navigate like a table of contents — read the index to route queries,
drill into board files for item-level search, return specific item IDs.

The catalog has multiple dimensions:
  - source/   → grouped by origin (pinterest, facebook, houzz, scan) and board
  - room/     → grouped by room type (bathroom, kitchen, bedroom, etc.)
  - style/    → grouped by design style (traditional, farmhouse, etc.)
  - magazine/ → grouped by magazine name (scans only)

Items appear in multiple dimensions simultaneously.
"""
from __future__ import annotations

import json
import re
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import Db

# Boards with fewer items than this get merged into _small.md
SMALL_BOARD_THRESHOLD = 15

# Maximum description length per item line
MAX_DESC_LEN = 60

# Maximum labels per item line
MAX_LABELS = 5

# Stop words for topic extraction
_STOP_WORDS = frozenset(
    "a an the and or but in on at to for of is it with from by this that "
    "are was were be been has have had do does did will would could should "
    "may might can shall not no so if as its all any some each every than "
    "very too also just about up out into over after before between through "
    "image contain may contains photo picture showing".split()
)

# --- Board → Room mapping ---
# Maps source board names to canonical room names for the room/ dimension.
# Items whose board doesn't map here fall back to AI rooms, then "Uncategorized".
BOARD_TO_ROOM: dict[str, str] = {
    # Direct room names (case-insensitive matching done at lookup)
    "bathroom": "Bathroom",
    "bathroom-remodel": "Bathroom",
    "kitchen": "Kitchen",
    "kitchen-remodel": "Kitchen",
    "bedroom": "Bedroom",
    "living room": "Living Room",
    "dining room": "Dining Room",
    "entry": "Entry & Mudroom",
    "entryway": "Entry & Mudroom",
    "mudroom": "Entry & Mudroom",
    "exterior": "Exterior",
    "landscape": "Landscape & Garden",
    "garden": "Landscape & Garden",
    "patio": "Outdoor Living",
    "porch": "Outdoor Living",
    "pool": "Outdoor Living",
    "garage": "Garage & Workshop",
    "closet": "Closet & Storage",
    "nursery": "Nursery & Kids",
    "laundry": "Laundry Room",
    "laundry-room": "Laundry Room",
    "laundry room": "Laundry Room",
    "home office": "Home Office",
    "staircase": "Hallway & Stairs",
    "hallway": "Hallway & Stairs",
    # Pinterest boards that map to rooms
    "favorite-places-spaces": None,  # too generic — skip
    "for-the-home": None,  # too generic — skip
    "misc": None,
    "door": "Entry & Mudroom",
    "flooring": None,  # material, not room
    "lighting": None,
    "furniture": None,
    "paint": None,
    "brick": None,
    "products-i-love": None,
    "my-style": None,
    "food": None,  # not home design
    "workout": None,
    "house-plans": None,  # plans, not room
    "floor plans": None,
    # Facebook boards
    "exercise": None,
    "building": None,
    "insulation": None,
    "hvac": None,
    "well": None,
    "water": None,
    "stone": None,
    "windows": None,
    "tile": None,
    "septic": None,
    "roofing": None,
    "propane": None,
    "plumbing": None,
    "generator": None,
    "freeze": None,
    "foundation": None,
    "estimates": None,
    "insurance": None,
    "cabinet": None,
    "interior design": None,
    "home & garden": None,
    # Houzz
    "home design": None,
}

# AI room names → canonical room names
AI_ROOM_MAP: dict[str, str] = {
    "bathroom": "Bathroom",
    "master bathroom": "Bathroom",
    "powder room": "Bathroom",
    "kitchen": "Kitchen",
    "bedroom": "Bedroom",
    "master bedroom": "Bedroom",
    "living room": "Living Room",
    "family room": "Living Room",
    "dining room": "Dining Room",
    "dining area": "Dining Room",
    "entryway": "Entry & Mudroom",
    "foyer": "Entry & Mudroom",
    "mudroom": "Entry & Mudroom",
    "entry": "Entry & Mudroom",
    "exterior": "Exterior",
    "landscape": "Landscape & Garden",
    "garden": "Landscape & Garden",
    "backyard": "Landscape & Garden",
    "patio": "Outdoor Living",
    "porch": "Outdoor Living",
    "pool": "Outdoor Living",
    "deck": "Outdoor Living",
    "sunroom": "Outdoor Living",
    "garage": "Garage & Workshop",
    "workshop": "Garage & Workshop",
    "closet": "Closet & Storage",
    "pantry": "Closet & Storage",
    "nursery": "Nursery & Kids",
    "kids room": "Nursery & Kids",
    "laundry room": "Laundry Room",
    "laundry": "Laundry Room",
    "utility room": "Laundry Room",
    "home office": "Home Office",
    "office": "Home Office",
    "library": "Home Office",
    "staircase": "Hallway & Stairs",
    "hallway": "Hallway & Stairs",
    "stairs": "Hallway & Stairs",
    "basement": "Basement",
    "attic": "Attic",
    "home gym": "Gym & Fitness",
    "gym": "Gym & Fitness",
    "room under construction": None,  # skip
}

# Magazine detection from OCR text_in_image
MAGAZINE_KEYWORDS: dict[str, str] = {
    "beautiful kitchens": "Beautiful Kitchens & Baths",
    "kitchens & baths": "Beautiful Kitchens & Baths",
    "house beautiful": "House Beautiful",
    "southern living": "Southern Living",
    "country living": "Country Living",
    "cottage journal": "Cottage Journal",
    "cottage home": "Cottage Home Style",
    "cottage style": "Cottage Home Style",
    "do it yourself": "DIY Magazine",
    "makeover style": "Makeover Style",
    "french style": "French Style",
    "house + home": "House + Home",
    "circa lighting": "Circa Lighting (catalog)",
    "circalighting": "Circa Lighting (catalog)",
    "ferguson": "Ferguson (catalog)",
    "visual comfort": "Visual Comfort (catalog)",
    "troy lighting": "Troy Lighting (catalog)",
}


def _resolve_rooms(row: dict, ai_data: dict | None) -> list[str]:
    """Determine canonical room(s) for an item.

    Priority: board mapping → AI rooms → empty.
    """
    rooms: list[str] = []

    # 1. Try board → room mapping
    board = (row.get("board") or "").strip().lower()
    if board and board in BOARD_TO_ROOM:
        mapped = BOARD_TO_ROOM[board]
        if mapped:
            rooms.append(mapped)

    # 2. Try AI rooms
    if ai_data:
        for ai_room in ai_data.get("rooms", []):
            canonical = AI_ROOM_MAP.get(ai_room.lower())
            if canonical and canonical not in rooms:
                rooms.append(canonical)

    return rooms


def _resolve_styles(ai_data: dict | None) -> list[str]:
    """Extract style names from AI data."""
    if not ai_data:
        return []
    raw = ai_data.get("styles", [])
    # Normalize: title-case, dedup
    seen: set[str] = set()
    result: list[str] = []
    for s in raw:
        normalized = s.strip().title()
        if normalized and normalized.lower() not in seen:
            seen.add(normalized.lower())
            result.append(normalized)
    return result


def _resolve_magazine(ai_data: dict | None) -> str | None:
    """Detect magazine name from AI OCR text_in_image."""
    if not ai_data:
        return None
    texts = ai_data.get("text_in_image", [])
    if isinstance(texts, list):
        combined = " ".join(str(t) for t in texts).lower()
    else:
        combined = str(texts).lower()

    for keyword, magazine in MAGAZINE_KEYWORDS.items():
        if keyword in combined:
            return magazine
    return None


def _best_description(row: dict) -> str:
    """Pick the best display text for an item, truncated."""
    text = (
        (row.get("title") or "").strip()
        or (row.get("ai_summary") or "").strip()
        or (row.get("seo_alt_text") or "").strip()
        or (row.get("board") or "").strip()
        or (row.get("creator_name") or "").strip()
        or "(untitled)"
    )
    # Strip useless prefixes
    text = re.sub(r"^This may contain:\s*", "", text, flags=re.IGNORECASE)
    if len(text) > MAX_DESC_LEN:
        text = text[: MAX_DESC_LEN - 3].rstrip() + "..."
    return text


def _format_item_line(row: dict, labels: list[str] | None = None) -> str:
    """Format one item as a catalog line."""
    short_id = row["id"][:8]
    desc = _best_description(row)
    if labels:
        top = labels[:MAX_LABELS]
        return f"- {short_id} | {desc} | [{', '.join(top)}]"
    return f"- {short_id} | {desc}"


def _extract_topics(titles: list[str], n: int = 5) -> list[str]:
    """Extract top topic words from a list of titles by frequency."""
    counter: Counter[str] = Counter()
    for title in titles:
        words = re.findall(r"[a-z]+", title.lower())
        for w in words:
            if w not in _STOP_WORDS and len(w) > 2:
                counter[w] += 1
    return [w for w, _ in counter.most_common(n)]


def _slugify(name: str) -> str:
    """Convert a board name to a filesystem-safe slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "other"


def _write_dimension_files(
    *,
    dimension: str,
    grouped: dict[str, list[dict]],
    catalog_dir: Path,
    labels_by_asset: dict[str, list[str]],
    id_map: dict[str, str],
    files_meta: list[dict[str, Any]],
    threshold: int = SMALL_BOARD_THRESHOLD,
) -> None:
    """Write markdown files for a single catalog dimension (room, style, magazine)."""
    dim_dir = catalog_dir / dimension
    dim_dir.mkdir(parents=True, exist_ok=True)

    big_groups: dict[str, list[dict]] = {}
    small_items: list[tuple[str, dict]] = []  # (group_name, item)

    for group_name, items in sorted(grouped.items(), key=lambda x: -len(x[1])):
        if len(items) >= threshold:
            big_groups[group_name] = items
        else:
            for item in items:
                small_items.append((group_name, item))

    # Write big group files
    for group_name, items in big_groups.items():
        slug = _slugify(group_name)
        path = dim_dir / f"{slug}.md"
        titles = [_best_description(i) for i in items]
        topics = _extract_topics(titles)
        has_labels = any(i["id"] in labels_by_asset for i in items)

        # Count sources in this group
        source_counts: Counter[str] = Counter()
        for item in items:
            source_counts[item["source"]] += 1
        source_str = ", ".join(
            f"{s} ({n})" for s, n in source_counts.most_common()
        )

        lines = [f"# {dimension.title()}: {group_name} ({len(items)} items)"]
        label_note = "Has AI labels." if has_labels else "No AI labels."
        lines.append(f"Sources: {source_str} | {label_note}")
        lines.append("")

        for item in items:
            labels = labels_by_asset.get(item["id"])
            lines.append(_format_item_line(item, labels))
            id_map[item["id"][:8]] = item["id"]

        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        files_meta.append({
            "path": f"{dimension}/{slug}.md",
            "source": dimension,
            "board": group_name,
            "item_count": len(items),
            "topics": topics,
        })

    # Write small groups file
    if small_items:
        path = dim_dir / "_small.md"
        by_group: dict[str, list[dict]] = {}
        for gname, item in small_items:
            by_group.setdefault(gname, []).append(item)

        total = len(small_items)
        lines = [f"# {dimension.title()}: Small Groups ({total} items)"]
        lines.append("")
        group_names: list[str] = []
        for gname, items in sorted(by_group.items(), key=lambda x: -len(x[1])):
            lines.append(f"## {gname} ({len(items)})")
            group_names.append(f"{gname} ({len(items)})")
            for item in items:
                labels = labels_by_asset.get(item["id"])
                lines.append(_format_item_line(item, labels))
                id_map[item["id"][:8]] = item["id"]
            lines.append("")

        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        files_meta.append({
            "path": f"{dimension}/_small.md",
            "source": dimension,
            "board": "(small groups)",
            "item_count": total,
            "topics": [g.split(" (")[0] for g in group_names[:5]],
        })


def generate_catalog(db: Db, catalog_dir: Path) -> dict[str, Any]:
    """Generate the full markdown catalog from the database.

    Produces multiple dimensions:
      - source/board (original by-source grouping)
      - room/ (by canonical room type)
      - style/ (by design style)
      - magazine/ (by magazine name, scans only)

    Returns a generation report with file counts and item counts.
    """
    catalog_dir = Path(catalog_dir)

    # Clean and recreate
    if catalog_dir.exists():
        shutil.rmtree(catalog_dir)
    catalog_dir.mkdir(parents=True)

    # Load all assets
    rows = [
        dict(r)
        for r in db.query(
            """
            select a.id, a.source, a.title, a.board, a.ai_summary,
                   a.seo_alt_text, a.creator_name, a.content_kind,
                   a.triage_status, a.media_status,
                   coalesce(a.category, 'home_design') as category
            from assets a
            order by a.source, a.board, a.title
            """
        )
    ]

    # Separate home-design items from "other" (food, fitness, personal, etc.)
    home_rows = [r for r in rows if r.get("category") != "other"]
    other_rows = [r for r in rows if r.get("category") == "other"]

    # Load labels grouped by asset
    labels_by_asset: dict[str, list[str]] = {}
    for r in db.query(
        "select asset_id, label from asset_labels order by asset_id, confidence desc"
    ):
        labels_by_asset.setdefault(r["asset_id"], []).append(r["label"])

    # Load AI JSON data for room/style/magazine extraction
    ai_by_asset: dict[str, dict] = {}
    for r in db.query("select asset_id, json from asset_ai"):
        try:
            ai_by_asset[r["asset_id"]] = json.loads(r["json"])
        except (json.JSONDecodeError, TypeError):
            pass

    # Load collections
    collections = [
        dict(r)
        for r in db.query(
            """
            select c.id, c.name, c.description, count(ci.asset_id) as count
            from collections c
            left join collection_items ci on ci.collection_id = c.id
            group by c.id
            order by c.name
            """
        )
    ]

    # Triage stats
    triage_counts: dict[str, int] = {}
    for r in db.query(
        "select coalesce(triage_status, 'pending') as ts, count(*) as n from assets group by ts"
    ):
        triage_counts[r["ts"]] = r["n"]

    id_map: dict[str, str] = {}
    files_meta: list[dict[str, Any]] = []

    # ── Dimension 0: Source / Board (original grouping) ──

    grouped_source: dict[str, dict[str, list[dict]]] = {}
    for row in rows:
        source = row["source"] or "unknown"
        board = (row["board"] or "").strip()
        grouped_source.setdefault(source, {}).setdefault(board, []).append(row)

    for source, boards in sorted(grouped_source.items()):
        source_dir = catalog_dir / source
        source_dir.mkdir(parents=True, exist_ok=True)

        # Split boards into big (own file) and small (merged)
        big_boards: dict[str, list[dict]] = {}
        small_items: list[dict] = []
        unboarded: dict[str, list[dict]] = {}  # content_kind -> items

        for board_name, items in sorted(boards.items(), key=lambda x: -len(x[1])):
            if not board_name:
                # Group unboarded by content_kind
                for item in items:
                    kind = item.get("content_kind") or "other"
                    unboarded.setdefault(kind, []).append(item)
            elif len(items) >= SMALL_BOARD_THRESHOLD:
                big_boards[board_name] = items
            else:
                small_items.extend(items)

        # Write big board files
        for board_name, items in big_boards.items():
            slug = _slugify(board_name)
            path = source_dir / f"{slug}.md"
            titles = [_best_description(i) for i in items]
            topics = _extract_topics(titles)
            has_labels = any(i["id"] in labels_by_asset for i in items)

            lines = [f"# {source.title()}: {board_name} ({len(items)} items)"]
            label_note = "Has AI labels." if has_labels else "No AI labels."
            lines.append(f"Board: {board_name} | Source: {source} | {label_note}")
            lines.append("")

            for item in items:
                labels = labels_by_asset.get(item["id"])
                lines.append(_format_item_line(item, labels))
                id_map[item["id"][:8]] = item["id"]

            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            files_meta.append({
                "path": f"{source}/{slug}.md",
                "source": source,
                "board": board_name,
                "item_count": len(items),
                "topics": topics,
            })

        # Write small boards file
        if small_items:
            path = source_dir / "_small.md"
            by_board: dict[str, list[dict]] = {}
            for item in small_items:
                b = item.get("board") or "other"
                by_board.setdefault(b, []).append(item)

            lines = [f"# {source.title()}: Small Boards ({len(small_items)} items)"]
            lines.append("")
            small_boards_list = []
            for b, items in sorted(by_board.items(), key=lambda x: -len(x[1])):
                lines.append(f"## {b} ({len(items)})")
                small_boards_list.append(f"{b} ({len(items)})")
                for item in items:
                    labels = labels_by_asset.get(item["id"])
                    lines.append(_format_item_line(item, labels))
                    id_map[item["id"][:8]] = item["id"]
                lines.append("")

            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            files_meta.append({
                "path": f"{source}/_small.md",
                "source": source,
                "board": "(small boards)",
                "item_count": len(small_items),
                "topics": [b.split(" (")[0] for b in small_boards_list[:5]],
            })

        # Write unboarded files (grouped by content_kind)
        for kind, items in sorted(unboarded.items(), key=lambda x: -len(x[1])):
            slug = f"_unboarded-{_slugify(kind)}" if len(unboarded) > 1 else "_unboarded"
            path = source_dir / f"{slug}.md"
            titles = [_best_description(i) for i in items]
            topics = _extract_topics(titles)
            has_labels = any(i["id"] in labels_by_asset for i in items)

            lines = [f"# {source.title()}: Unsorted {kind.title()}s ({len(items)} items)"]
            label_note = "Has AI labels." if has_labels else "No AI labels."
            lines.append(f"Source: {source} | Type: {kind} | {label_note}")
            lines.append("")

            for item in items:
                labels = labels_by_asset.get(item["id"])
                lines.append(_format_item_line(item, labels))
                id_map[item["id"][:8]] = item["id"]

            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            files_meta.append({
                "path": f"{source}/{slug}.md",
                "source": source,
                "board": f"(unsorted {kind}s)",
                "item_count": len(items),
                "topics": topics,
            })

    # ── Dimension 1: Room (PRIMARY) — home_design items only ──

    room_grouped: dict[str, list[dict]] = {}
    room_uncategorized: list[dict] = []

    for row in home_rows:
        ai_data = ai_by_asset.get(row["id"])
        rooms = _resolve_rooms(row, ai_data)
        if rooms:
            for room in rooms:
                room_grouped.setdefault(room, []).append(row)
        else:
            room_uncategorized.append(row)

    _write_dimension_files(
        dimension="room",
        grouped=room_grouped,
        catalog_dir=catalog_dir,
        labels_by_asset=labels_by_asset,
        id_map=id_map,
        files_meta=files_meta,
    )

    # Write room uncategorized
    if room_uncategorized:
        unc_dir = catalog_dir / "room"
        unc_dir.mkdir(parents=True, exist_ok=True)
        path = unc_dir / "_uncategorized.md"
        lines = [f"# Room: Uncategorized ({len(room_uncategorized)} items)"]
        lines.append("Items not assigned to any room.")
        lines.append("")
        for item in room_uncategorized:
            labels = labels_by_asset.get(item["id"])
            lines.append(_format_item_line(item, labels))
            id_map[item["id"][:8]] = item["id"]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        files_meta.append({
            "path": "room/_uncategorized.md",
            "source": "room",
            "board": "(uncategorized)",
            "item_count": len(room_uncategorized),
            "topics": [],
        })

    # ── Dimension 2: Style (SECONDARY) — home_design items only ──

    style_grouped: dict[str, list[dict]] = {}
    for row in home_rows:
        ai_data = ai_by_asset.get(row["id"])
        styles = _resolve_styles(ai_data)
        for style in styles:
            style_grouped.setdefault(style, []).append(row)

    _write_dimension_files(
        dimension="style",
        grouped=style_grouped,
        catalog_dir=catalog_dir,
        labels_by_asset=labels_by_asset,
        id_map=id_map,
        files_meta=files_meta,
    )

    # ── Dimension 3: Magazine (TERTIARY, scans only) ──

    magazine_grouped: dict[str, list[dict]] = {}
    magazine_unknown: list[dict] = []

    for row in home_rows:
        if row["source"] != "scan":
            continue
        ai_data = ai_by_asset.get(row["id"])
        mag = _resolve_magazine(ai_data)
        if mag:
            magazine_grouped.setdefault(mag, []).append(row)
        else:
            magazine_unknown.append(row)

    if magazine_grouped:
        _write_dimension_files(
            dimension="magazine",
            grouped=magazine_grouped,
            catalog_dir=catalog_dir,
            labels_by_asset=labels_by_asset,
            id_map=id_map,
            files_meta=files_meta,
            threshold=3,  # Magazines can be small
        )

    if magazine_unknown:
        mag_dir = catalog_dir / "magazine"
        mag_dir.mkdir(parents=True, exist_ok=True)
        path = mag_dir / "_unknown.md"
        lines = [f"# Magazine: Unknown Source ({len(magazine_unknown)} items)"]
        lines.append("Scanned pages where the magazine couldn't be identified.")
        lines.append("")
        for item in magazine_unknown:
            labels = labels_by_asset.get(item["id"])
            lines.append(_format_item_line(item, labels))
            id_map[item["id"][:8]] = item["id"]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        files_meta.append({
            "path": "magazine/_unknown.md",
            "source": "magazine",
            "board": "(unknown magazine)",
            "item_count": len(magazine_unknown),
            "topics": [],
        })

    # ── Other: non-home-design items (hidden from collaborators) ──

    if other_rows:
        other_grouped: dict[str, list[dict]] = {}
        for row in other_rows:
            board = (row.get("board") or "uncategorized").strip()
            other_grouped.setdefault(board, []).append(row)

        _write_dimension_files(
            dimension="other",
            grouped=other_grouped,
            catalog_dir=catalog_dir,
            labels_by_asset=labels_by_asset,
            id_map=id_map,
            files_meta=files_meta,
            threshold=5,
        )

    # ── Generate index, labels, manifest ──

    _generate_index(
        files_meta=files_meta,
        total_items=len(rows),
        collections=collections,
        triage_counts=triage_counts,
        out_path=catalog_dir / "_index.md",
    )

    _generate_labels(labels_by_asset, catalog_dir / "_labels.md")

    now = datetime.now(timezone.utc).isoformat()
    manifest = {
        "generated_at": now,
        "total_items": len(rows),
        "files": {
            fm["path"]: {
                "source": fm["source"],
                "board": fm["board"],
                "item_count": fm["item_count"],
                "topics": fm["topics"],
            }
            for fm in files_meta
        },
        "id_map": id_map,
    }
    (catalog_dir / "_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    # Compute dimension stats
    room_count = sum(len(v) for v in room_grouped.values())
    style_count = sum(len(v) for v in style_grouped.values())
    magazine_count = sum(len(v) for v in magazine_grouped.values())

    return {
        "catalog_dir": str(catalog_dir),
        "total_items": len(rows),
        "home_design_items": len(home_rows),
        "other_items": len(other_rows),
        "files_written": len(files_meta) + 3,  # +3 for index, labels, manifest
        "board_files": len([f for f in files_meta if not f["path"].endswith("_small.md")]),
        "id_map_entries": len(id_map),
        "collections": len(collections),
        "dimensions": {
            "room": {"items_assigned": room_count, "uncategorized": len(room_uncategorized)},
            "style": {"items_assigned": style_count},
            "magazine": {"items_assigned": magazine_count, "unknown": len(magazine_unknown)},
            "other": {"items": len(other_rows)},
        },
    }


def _is_catchall(board_name: str) -> bool:
    """Return True for catch-all categories (uncategorized, unsorted, small, unknown)."""
    lower = board_name.lower()
    return any(
        kw in lower
        for kw in ("uncategorized", "unsorted", "small", "unknown")
    )


def _index_sort_key(fm: dict) -> tuple[int, int]:
    """Sort key: catch-all entries last, then by item count descending."""
    return (1 if _is_catchall(fm["board"]) else 0, -fm["item_count"])


def _generate_index(
    *,
    files_meta: list[dict[str, Any]],
    total_items: int,
    collections: list[dict[str, Any]],
    triage_counts: dict[str, int],
    out_path: Path,
) -> None:
    """Write the _index.md table of contents."""
    # Group files by top-level directory (source or dimension)
    by_section: dict[str, list[dict]] = {}
    for fm in files_meta:
        by_section.setdefault(fm["source"], []).append(fm)

    # Separate real sources from dimensions
    sources = ["facebook", "houzz", "pinterest", "scan"]
    dimensions = ["room", "style", "magazine"]
    hidden_dims = ["other"]  # Not exposed to collaborators

    source_totals = {
        s: sum(f["item_count"] for f in files)
        for s, files in by_section.items()
    }

    lines = ["# Inspirations Catalog"]
    lines.append("")

    # Summary line with source counts
    src_summary = ", ".join(
        f"{s.title()} ({source_totals.get(s, 0)})"
        for s in sources
        if s in by_section
    )
    lines.append(f"{total_items} home design inspiration items: {src_summary}.")
    lines.append("")

    # Dimensions overview
    dim_parts = []
    for dim in dimensions:
        if dim in by_section:
            total_in_dim = source_totals.get(dim, 0)
            file_count = len(by_section[dim])
            dim_parts.append(f"{dim.title()} ({total_in_dim} assignments in {file_count} files)")
    if dim_parts:
        lines.append(f"Cross-cutting dimensions: {', '.join(dim_parts)}.")
        lines.append("Items appear in multiple dimensions (source + room + style + magazine).")
        lines.append("")

    # ── Source sections ──
    for source in sources:
        if source not in by_section:
            continue
        files = by_section[source]
        lines.append(f"## {source.title()} ({source_totals[source]} items)")
        lines.append("")
        lines.append("| File | Category | Items | Topics |")
        lines.append("|------|----------|-------|--------|")
        for fm in sorted(files, key=_index_sort_key):
            topics_str = ", ".join(fm["topics"][:5]) if fm["topics"] else ""
            lines.append(
                f"| {fm['path']} | {fm['board']} | {fm['item_count']} | {topics_str} |"
            )
        lines.append("")

    # ── Dimension sections ──
    for dim in dimensions:
        if dim not in by_section:
            continue
        files = by_section[dim]
        dim_total = source_totals[dim]
        lines.append(f"## By {dim.title()} ({dim_total} item-assignments)")
        lines.append("")
        lines.append("| File | Category | Items | Topics |")
        lines.append("|------|----------|-------|--------|")
        for fm in sorted(files, key=_index_sort_key):
            topics_str = ", ".join(fm["topics"][:5]) if fm["topics"] else ""
            lines.append(
                f"| {fm['path']} | {fm['board']} | {fm['item_count']} | {topics_str} |"
            )
        lines.append("")

    # ── Other (hidden from collaborators) ──
    for dim in hidden_dims:
        if dim not in by_section:
            continue
        files = by_section[dim]
        dim_total = source_totals[dim]
        lines.append(f"## Other / Non-Home-Design ({dim_total} items)")
        lines.append("*Hidden from collaborators. Categorized for owner reference.*")
        lines.append("")
        lines.append("| File | Category | Items | Topics |")
        lines.append("|------|----------|-------|--------|")
        for fm in sorted(files, key=_index_sort_key):
            topics_str = ", ".join(fm["topics"][:5]) if fm["topics"] else ""
            lines.append(
                f"| {fm['path']} | {fm['board']} | {fm['item_count']} | {topics_str} |"
            )
        lines.append("")

    # Collections
    if collections:
        lines.append("## Collections")
        lines.append("")
        for c in collections:
            count = c.get("count", 0)
            if count > 0:
                lines.append(f"- \"{c['name']}\" ({count} items, id={c['id']})")
        lines.append("")

    # Triage
    lines.append("## Triage Status")
    total = sum(triage_counts.values())
    parts = []
    for status in ["keeper", "hidden", "pending"]:
        n = triage_counts.get(status, 0)
        if status == "pending":
            # Items with NULL triage_status count as pending
            n += triage_counts.get("", 0)
        parts.append(f"{n} {status}")
    lines.append(f"{total} total: {', '.join(parts)}")
    lines.append("")

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _generate_labels(
    labels_by_asset: dict[str, list[str]],
    out_path: Path,
) -> None:
    """Write the _labels.md reference."""
    all_labels: Counter[str] = Counter()
    for labels in labels_by_asset.values():
        for label in labels:
            all_labels[label] += 1

    lines = [f"# Label Reference ({len(labels_by_asset)} items labeled)"]
    lines.append("")
    lines.append("Top labels by frequency:")
    top = all_labels.most_common(50)
    label_strs = [f"{label} ({count})" for label, count in top]
    lines.append(", ".join(label_strs))
    lines.append("")
    lines.append(f"Total distinct labels: {len(all_labels)}")
    lines.append("")

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --- Loading functions (used at query time) ---


def load_catalog_index(catalog_dir: Path) -> str | None:
    """Load _index.md content, or None if catalog doesn't exist."""
    path = catalog_dir / "_index.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


def load_catalog_files(catalog_dir: Path, files: list[str]) -> str:
    """Load and concatenate requested catalog files."""
    parts: list[str] = []
    for f in files:
        path = catalog_dir / f
        if path.exists():
            parts.append(path.read_text(encoding="utf-8"))
    return "\n\n".join(parts)


def load_manifest(catalog_dir: Path) -> dict[str, Any] | None:
    """Load _manifest.json, or None if it doesn't exist."""
    path = catalog_dir / "_manifest.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def resolve_short_ids(manifest: dict[str, Any], short_ids: list[str]) -> list[str]:
    """Map 8-char prefixes to full UUIDs using the manifest id_map."""
    id_map = manifest.get("id_map", {})
    result: list[str] = []
    for sid in short_ids:
        full = id_map.get(sid[:8])
        if full:
            result.append(full)
    return result
