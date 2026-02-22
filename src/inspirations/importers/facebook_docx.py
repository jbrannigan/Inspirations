from __future__ import annotations

import hashlib
import re
import uuid
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..db import Db

# ─── XML namespace URIs ───────────────────────────────────────────────────────

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_R_OFF = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"

_W_P = f"{{{_W}}}p"
_W_T = f"{{{_W}}}t"
_W_HYPERLINK = f"{{{_W}}}hyperlink"
_A_BLIP = f"{{{_A}}}blip"
_R_ID = f"{{{_R_OFF}}}id"
_R_EMBED = f"{{{_R_OFF}}}embed"

# ─── Home/design collection whitelist ────────────────────────────────────────

HOME_DESIGN_COLLECTIONS: frozenset[str] = frozenset(
    {
        "kitchen",
        "building",
        "bathroom",
        "door",
        "floor plans",
        "paint",
        "furniture",
        "flooring",
        "lighting",
        "windows",
        "garage",
        "hvac",
        "insulation",
        "roofing",
        "interior design",
        "interior design/architect",
        "cabinet",
        "cabinets",
        "tile",
        "concrete",
        "stone",
        "brick",
        "mudroom",
        "laundry",
        "drywall",
        "ceiling fan",
        "molding",
        "appliances",
        "style board",
        "living room",
        "bedroom",
        "Fireplace",
        "aging in place",
        "pocket door",
        "quartzite",
        "carpet",
        "Sheet rock",
        "foundation",
        "propane",
        "electric",
        "generator",
        "plumbing",
        "water heater",
        "Water heater",
        "water",
        "well",
        "septic",
        "Inspection",
        "Gutters",
        "land",
        "lot",
        "survey",
        "soil test",
        "architect",
        "contract",
        "estimates",
        "punch list",
        "Selling home",
        "Mortgage",
        "Insurance",
        "insurance",
        "home insurance",
        "Trust",
        "legal",
        "Home & Garden",
        "garden",
        "2b/2b",
        "re: builders",
        "cottage of the year",
        "freeze",
        "mold",
        "security",
        "internet",
        "solar",
        "land clearing",
        "caulk",
        "drain pan",
        "water softener",
        "ADA",
    }
)

_CONTENT_KIND_MAP: dict[str, str] = {
    "reels": "reel",
    "reel": "reel",
    "post": "post",
    "link": "link",
}

_SAVED_TO_RE = re.compile(r"^(.*?)\s*[•·]\s*Saved to\s+(.+)$")
_SAVED_FROM_RE = re.compile(r"Saved from (.+?)'s (?:post|video|reel)")
_DURATION_RE = re.compile(r"^\d{2}:\d{2}$")
_COLLECTION_SUFFIX_RE = re.compile(r"\s*\+\s*\d+\s+other\s*$")


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_relationships(z: zipfile.ZipFile) -> tuple[dict[str, str], dict[str, str]]:
    """Parse word/_rels/document.xml.rels → (hyperlinks {rId: url}, images {rId: zip_path})."""
    rels_xml = z.read("word/_rels/document.xml.rels")
    root = ET.fromstring(rels_xml)
    hyperlinks: dict[str, str] = {}
    images: dict[str, str] = {}
    for rel in root:
        rid = rel.get("Id", "")
        target = rel.get("Target", "")
        rel_type = rel.get("Type", "")
        if not rid:
            continue
        if "hyperlink" in rel_type:
            hyperlinks[rid] = target
        elif "image" in rel_type:
            # Targets are relative to word/, e.g. "media/image1.jpeg"
            zip_path = f"word/{target}" if not target.startswith("/") else target.lstrip("/")
            images[rid] = zip_path
    return hyperlinks, images


def _extract_text(para: ET.Element) -> str:
    return "".join(t.text or "" for t in para.iter(_W_T)).strip()


def _extract_urls(para: ET.Element, hyperlinks: dict[str, str]) -> list[str]:
    urls = []
    for hl in para.iter(_W_HYPERLINK):
        rid = hl.get(_R_ID, "")
        url = hyperlinks.get(rid, "")
        if url:
            urls.append(url)
    return urls


def _extract_image_ref(para: ET.Element, images: dict[str, str]) -> str | None:
    for blip in para.iter(_A_BLIP):
        rid = blip.get(_R_EMBED, "")
        if rid and rid in images:
            return images[rid]
    return None


def _normalize_collection(raw: str) -> str:
    return _COLLECTION_SUFFIX_RE.sub("", raw).strip()


def _content_kind(content_type: str) -> str:
    return _CONTENT_KIND_MAP.get((content_type or "").lower().strip(), "other")


def _domain_from_url(url: str) -> str:
    if not url:
        return ""
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        host = ""
    if host.startswith("www."):
        host = host[4:]
    return host


# ─── DOCX parser ─────────────────────────────────────────────────────────────


def _parse_entries(z: zipfile.ZipFile) -> list[dict[str, Any]]:
    """Walk document.xml paragraphs and extract structured entries."""
    hyperlinks, images = _load_relationships(z)
    doc_xml = z.read("word/document.xml")
    root = ET.fromstring(doc_xml)

    body = root.find(f"{{{_W}}}body")
    if body is None:
        return []

    entries: list[dict[str, Any]] = []
    current: dict[str, Any] = {}

    for child in body:
        if child.tag != _W_P:
            continue

        text = _extract_text(child)
        urls = _extract_urls(child, hyperlinks)
        image_path = _extract_image_ref(child, images)

        # Duration line: "00:25"
        if _DURATION_RE.match(text):
            if current and "title" in current:
                entries.append(current)
            current = {"duration": text}
            continue

        # "Saved to" line — "Reels • Saved to kitchen"
        m = _SAVED_TO_RE.match(text)
        if m:
            if current:
                current["content_type"] = m.group(1).strip()
                current["collection"] = m.group(2).strip()
            continue

        # "Saved from" line — last line of an entry
        if text.startswith("Saved from"):
            m2 = _SAVED_FROM_RE.match(text)
            if m2 and current:
                current["creator_name"] = m2.group(1).strip()
            if current and "title" in current:
                entries.append(current)
                current = {}
            continue

        # Title/content line
        if text and not current.get("title"):
            current["title"] = text
            if urls:
                current["url"] = urls[0]
            if image_path:
                current["image_path"] = image_path
        elif image_path and "image_path" not in current:
            current["image_path"] = image_path

    if current and "title" in current:
        entries.append(current)

    return entries


# ─── Image extraction ─────────────────────────────────────────────────────────


def _save_image(z: zipfile.ZipFile, zip_path: str, store_dir: Path) -> tuple[str, str] | None:
    """Extract image from DOCX ZIP and save with sha256 name. Returns (stored_path, sha256)."""
    try:
        img_bytes = z.read(zip_path)
    except Exception:
        return None
    sha = hashlib.sha256(img_bytes).hexdigest()
    out_dir = store_dir / "originals" / "facebook"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{sha}.jpg"
    if not out_path.exists():
        out_path.write_bytes(img_bytes)
    return str(out_path), sha


# ─── Main importer ────────────────────────────────────────────────────────────


def import_facebook_docx(
    db: Db,
    docx_path: Path,
    store_dir: Path,
    collections_filter: str = "home-design",
) -> dict[str, Any]:
    imported_at = _now_iso()

    # Remove any existing Facebook rows from a prior import to avoid cross-importer
    # dedup drift (JSON importer and DOCX importer hash source_ref differently).
    existing = int(db.query_value("SELECT COUNT(*) FROM assets WHERE source = 'facebook'") or 0)
    if existing > 0:
        db.exec(
            "DELETE FROM collection_items WHERE asset_id IN"
            " (SELECT id FROM assets WHERE source = 'facebook')"
        )
        db.exec("DELETE FROM assets WHERE source = 'facebook'")

    with zipfile.ZipFile(docx_path) as z:
        all_entries = _parse_entries(z)
        total_parsed = len(all_entries)

        # Filter by collection
        if collections_filter == "home-design":
            filtered = []
            for entry in all_entries:
                col = _normalize_collection(entry.get("collection", ""))
                if col in HOME_DESIGN_COLLECTIONS:
                    filtered.append(dict(entry, collection=col))
        else:
            filtered = [
                dict(e, collection=_normalize_collection(e.get("collection", "")))
                for e in all_entries
            ]

        # Build rows (image extraction happens here, inside the open ZipFile)
        rows: list[tuple[Any, ...]] = []
        images_extracted = 0

        for entry in filtered:
            title = (entry.get("title") or "").strip() or None
            url = entry.get("url") or ""
            collection = entry.get("collection") or ""
            content_type = entry.get("content_type") or ""
            creator = (entry.get("creator_name") or "").strip() or None
            image_zip_path = entry.get("image_path")

            # source_ref: URL if valid, else content hash
            if url.startswith(("http://", "https://")):
                source_ref = url
            else:
                source_ref = hashlib.sha256(
                    f"{title or ''}|{collection}".encode()
                ).hexdigest()

            # Extract image
            stored_path: str | None = None
            sha256: str | None = None
            media_status = "metadata_only"
            if image_zip_path:
                result = _save_image(z, image_zip_path, store_dir)
                if result:
                    stored_path, sha256 = result
                    media_status = "image"
                    images_extracted += 1

            domain = _domain_from_url(url) or None
            kind = _content_kind(content_type)

            rows.append(
                (
                    str(uuid.uuid4()),  # id
                    "facebook",  # source
                    source_ref,  # source_ref
                    title,  # title
                    None,  # description
                    collection or None,  # board
                    None,  # created_at
                    imported_at,  # imported_at
                    None,  # image_url
                    stored_path,  # stored_path
                    sha256,  # sha256
                    media_status,  # media_status
                    kind,  # content_kind
                    creator,  # creator_name
                    domain,  # source_domain
                    creator,  # source_name
                )
            )

    db.executemany(
        """
        insert or ignore into assets
          (id, source, source_ref, title, description, board,
           created_at, imported_at, image_url, stored_path, sha256,
           media_status, content_kind, creator_name, source_domain, source_name)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )

    inserted_rows = db.query(
        "select content_kind from assets where source='facebook' and imported_at=?",
        (imported_at,),
    )
    inserted_total = len(inserted_rows)

    content_kind_counts: dict[str, int] = {}
    for row in inserted_rows:
        kind = str(row["content_kind"] or "other")
        content_kind_counts[kind] = content_kind_counts.get(kind, 0) + 1

    collections_seen = sorted(
        {e.get("collection", "") for e in filtered if e.get("collection")}
    )

    return {
        "source_file": docx_path.name,
        "total_entries_parsed": total_parsed,
        "filtered_home_design": len(filtered),
        "imported_assets": inserted_total,
        "existing_assets": len(filtered) - inserted_total,
        "images_extracted": images_extracted,
        "metadata_only": len(filtered) - images_extracted,
        "collections_seen": collections_seen,
        "content_kind_counts": content_kind_counts,
    }
