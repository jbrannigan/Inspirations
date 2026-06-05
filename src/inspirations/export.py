from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

from .db import Db

PORTAL_EMBED_PREVIEW_MAX_ITEMS = 180
_SCAN_REF_RE = re.compile(r"^scan://([a-f0-9]{64})(?:#p(\d+))?$", re.IGNORECASE)
_SCAN_DOC_RE = re.compile(r"\s-\sdoc\s+(\d+)(?:\s+p(\d+))?$", re.IGNORECASE)


class PdfExportError(RuntimeError):
    """Base error for collection PDF export failures."""


class PdfToolUnavailableError(PdfExportError):
    """Raised when required local PDF tools are unavailable."""


class PdfRenderError(PdfExportError):
    """Raised when the local PDF renderer fails."""


def _looks_like_image_ref(value: str) -> bool:
    text = (value or "").strip().lower()
    if not text:
        return False
    image_parts = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".svg")
    if any(text.endswith(part) for part in image_parts):
        return True
    return any(f"{part}?" in text for part in image_parts)


def _mime_for_path(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in (".jpg", ".jpeg"):
        return "image/jpeg"
    if ext == ".png":
        return "image/png"
    if ext == ".webp":
        return "image/webp"
    if ext == ".gif":
        return "image/gif"
    if ext == ".bmp":
        return "image/bmp"
    if ext == ".svg":
        return "image/svg+xml"
    return "application/octet-stream"


def _as_data_uri(path: Path) -> str:
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{_mime_for_path(path)};base64,{payload}"


def _existing_local_path(raw_path: Any) -> Path | None:
    text = str(raw_path or "").strip()
    if not text:
        return None
    path = Path(text).expanduser()
    candidate = path if path.is_absolute() else (Path.cwd() / path)
    try:
        resolved = candidate.resolve()
    except OSError:
        return None
    if not resolved.exists() or not resolved.is_file():
        return None
    return resolved


def _relative_preview_url(path: Path, *, out_path: Path) -> str | None:
    project_root = Path.cwd().resolve()
    try:
        path.relative_to(project_root)
    except ValueError:
        return None
    relative = Path(os.path.relpath(path, out_path.parent.resolve()))
    return quote(relative.as_posix(), safe="/-._~")


def _prepare_preview_assets_dir(*, out_path: Path) -> Path:
    assets_dir = out_path.parent / f"{out_path.stem}_media"
    if assets_dir.exists():
        shutil.rmtree(assets_dir)
    assets_dir.mkdir(parents=True, exist_ok=True)
    return assets_dir


def _copy_preview_to_assets(
    path: Path,
    *,
    assets_dir: Path,
    copied_urls: dict[str, str],
) -> str:
    source_key = str(path)
    existing = copied_urls.get(source_key)
    if existing:
        return existing
    ext = path.suffix.lower() or ".img"
    digest = hashlib.sha1(source_key.encode("utf-8")).hexdigest()[:20]
    filename = f"{digest}{ext}"
    target = assets_dir / filename
    if not target.exists():
        shutil.copy2(path, target)
    url = quote(f"{assets_dir.name}/{filename}", safe="/-._~")
    copied_urls[source_key] = url
    return url


def _local_preview_src(
    path: Path,
    *,
    out_path: Path,
    embed_local_previews: bool,
    preview_assets_dir: Path | None,
    copied_preview_urls: dict[str, str],
) -> tuple[str, str]:
    if embed_local_previews:
        return _as_data_uri(path), "embedded"
    if preview_assets_dir:
        return _copy_preview_to_assets(path, assets_dir=preview_assets_dir, copied_urls=copied_preview_urls), "linked"
    relative_url = _relative_preview_url(path, out_path=out_path)
    if relative_url:
        return relative_url, "linked"
    return _as_data_uri(path), "embedded"


def _source_label(source: str) -> str:
    mapping = {"facebook": "Facebook", "pinterest": "Pinterest", "scan": "Scan"}
    key = (source or "").strip().lower()
    return mapping.get(key, source or "")


def _title_for_export(row: dict[str, Any]) -> str:
    source = str(row.get("source") or "").strip().lower()
    title = str(row.get("title") or "").strip()
    if not title:
        return "(untitled)"
    if source == "facebook":
        title = re.sub(r"^leslie brannigan saved a (?:link|product|video)(?: from)?\s+", "", title, flags=re.IGNORECASE).strip()
        title = re.sub(r"^leslie brannigan saved a (?:link|product|video)\.?$", "", title, flags=re.IGNORECASE).strip()
        if not title:
            source_ref = str(row.get("source_ref") or "").strip()
            host = urlparse(source_ref).netloc.replace("www.", "") if source_ref else ""
            return f"Saved from {host}" if host else "(untitled)"
    return title


def _scan_ref_parts(source_ref: str) -> tuple[str, int | None] | None:
    m = _SCAN_REF_RE.match((source_ref or "").strip())
    if not m:
        return None
    sha = str(m.group(1) or "").strip().lower()
    page_idx = int(m.group(2)) if m.group(2) else None
    return (sha, page_idx)


def _scan_doc_parts(title: str) -> tuple[int | None, int | None]:
    m = _SCAN_DOC_RE.search((title or "").strip())
    if not m:
        return (None, None)
    doc_idx = int(m.group(1)) if m.group(1) else None
    doc_page = int(m.group(2)) if m.group(2) else None
    return (doc_idx, doc_page)


def _annotations_by_asset(db: Db, *, asset_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not asset_ids:
        return {}
    placeholders = ",".join(["?"] * len(asset_ids))
    rows = db.query(
        f"""
        select asset_id, x, y, text
        from annotations
        where asset_id in ({placeholders})
        order by created_at asc
        """,
        tuple(asset_ids),
    )
    grouped: dict[str, list[dict[str, Any]]] = {aid: [] for aid in asset_ids}
    for row in rows:
        aid = str(row["asset_id"])
        grouped.setdefault(aid, []).append(
            {
                "x": float(row["x"]),
                "y": float(row["y"]),
                "text": str(row["text"] or ""),
            }
        )
    return grouped


def _rows_for_export(
    db: Db,
    *,
    source: str = "",
    collection_id: str = "",
    limit: int = 0,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    join_sql = ""
    order_sql = "order by a.imported_at desc"
    if source:
        sources = [s.strip() for s in source.split(",") if s.strip()]
        if sources:
            clauses.append("a.source in (%s)" % ",".join(["?"] * len(sources)))
            params.extend(sources)
    if collection_id:
        join_sql = "join collection_items ci on ci.asset_id = a.id"
        clauses.append("ci.collection_id = ?")
        params.append(collection_id)
        order_sql = "order by ci.position asc, a.imported_at desc"

    where = "where " + " and ".join(clauses) if clauses else ""
    limit_sql = "limit ?" if limit and limit > 0 else ""
    if limit_sql:
        params.append(int(limit))

    rows = db.query(
        f"""
        select a.id, a.source, a.source_ref, a.title, a.description, a.board, a.notes,
               a.image_url, a.stored_path, a.thumb_path, a.imported_at
        from assets a
        {join_sql}
        {where}
        {order_sql}
        {limit_sql}
        """,
        tuple(params),
    )
    return [dict(r) for r in rows]


def export_html_gallery(
    db: Db,
    *,
    out_path: Path,
    source: str = "",
    collection_id: str = "",
    limit: int = 0,
) -> dict[str, Any]:
    rows = _rows_for_export(db, source=source, collection_id=collection_id, limit=limit)
    annotations_by_asset = _annotations_by_asset(
        db,
        asset_ids=[str(row["id"]) for row in rows if str(row.get("id") or "").strip()],
    )
    out_path = out_path.expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cards: list[str] = []
    detail_payload: dict[str, dict[str, Any]] = {}
    embedded = 0
    remote = 0
    no_preview = 0

    for row in rows:
        asset_id = str(row.get("id") or "")
        preview_src = ""
        thumb_path = Path(str(row.get("thumb_path") or ""))
        stored_path = Path(str(row.get("stored_path") or ""))
        image_url = str(row.get("image_url") or "").strip()
        source_ref = str(row.get("source_ref") or "").strip()
        annotations = annotations_by_asset.get(asset_id, [])

        if thumb_path and thumb_path.exists() and thumb_path.is_file():
            preview_src = _as_data_uri(thumb_path)
            embedded += 1
        elif stored_path and stored_path.exists() and stored_path.is_file() and _looks_like_image_ref(str(stored_path)):
            preview_src = _as_data_uri(stored_path)
            embedded += 1
        elif image_url and _looks_like_image_ref(image_url):
            preview_src = image_url
            remote += 1
        else:
            no_preview += 1

        title_value = _title_for_export(row)
        title = html.escape(title_value)
        source_value = _source_label(str(row.get("source") or ""))
        source = html.escape(source_value)
        board = html.escape(str(row.get("board") or ""))
        notes_value = str(row.get("notes") or "").strip()
        notes = html.escape(notes_value)
        imported_value = str(row.get("imported_at") or "").strip()
        imported_short = html.escape(imported_value[:10] if imported_value else "")
        source_link = html.escape(source_ref, quote=True)
        safe_asset_id = html.escape(asset_id, quote=True)
        ann_count = len(annotations)
        ann_word = "note" if ann_count == 1 else "notes"

        media_html = (
            f'<img src="{preview_src}" alt="" loading="lazy" class="detailBtn detailPreview" '
            f'data-asset-id="{safe_asset_id}" data-preview-id="{safe_asset_id}" />'
            if preview_src
            else f'<button type="button" class="placeholder detailBtn detailPreview" data-asset-id="{safe_asset_id}" data-preview-id="{safe_asset_id}">No preview</button>'
        )
        annotation_badge_html = f'<span class="annotationBadge">{ann_count} {ann_word}</span>' if ann_count else ""
        card_class = "card hasAnnotations" if ann_count else "card"
        source_ref_html = (
            f'<a class="btn linkBtn" href="{source_link}" target="_blank" rel="noopener noreferrer">Open Source</a>'
            if source_link
            else '<span class="muted">No source link</span>'
        )
        cards.append(
            f"""
            <article class="{card_class}">
              <div class="media">
                {media_html}
                {annotation_badge_html}
              </div>
              <div class="body">
                <h3>{title}</h3>
                <p class="meta">Source: {source}{' • Board: ' + board if board else ''}</p>
                <p class="meta">Imported: {imported_short or 'unknown'}</p>
                <p class="notes">{notes or 'No general notes.'}</p>
                <div class="cardActions">
                  <button type="button" class="btn detailBtn" data-asset-id="{safe_asset_id}">Show Details</button>
                  {source_ref_html}
                </div>
              </div>
            </article>
            """
        )
        detail_payload[asset_id] = {
            "id": asset_id,
            "title": title_value,
            "source": source_value,
            "source_ref": source_ref,
            "imported_at": imported_value[:10] if imported_value else "",
            "notes": notes_value,
            "annotations": annotations,
        }

    details_json = json.dumps(detail_payload).replace("</", "<\\/")
    header_json = html.escape(json.dumps({"assets": len(rows), "source": source or None, "collection_id": collection_id or None}))
    payload = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Inspirations Share</title>
  <style>
    :root { color-scheme: light; }
    * { box-sizing: border-box; }
    body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f4f5f8; color: #1f2937; }
    header { padding: 18px; background: #0f172a; color: #f8fafc; }
    header h1 { margin: 0 0 6px; font-size: 20px; }
    header p { margin: 0; color: #cbd5e1; font-size: 13px; }
    .saveSteps {
      margin-top: 10px;
      border: 1px solid rgba(203, 213, 225, 0.45);
      border-radius: 10px;
      padding: 10px 12px;
      background: rgba(15, 23, 42, 0.35);
      max-width: 860px;
    }
    .saveSteps strong { display: block; margin-bottom: 4px; }
    .saveSteps ol { margin: 0; padding-left: 18px; }
    .saveSteps li { color: #dbe3f0; font-size: 12px; line-height: 1.45; }
    main { padding: 14px; display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; }
    .card {
      background: #fff;
      border: 1px solid #dbe0e8;
      border-radius: 12px;
      overflow: hidden;
      display: grid;
      grid-template-rows: auto 1fr;
      box-shadow: 0 2px 8px rgba(15, 23, 42, 0.08);
    }
    .card.hasAnnotations { border-color: #8cc4ff; box-shadow: 0 0 0 2px rgba(140, 196, 255, 0.28); }
    .media {
      aspect-ratio: 4/3;
      background: #e5e7eb;
      display: grid;
      place-items: center;
      position: relative;
      overflow: hidden;
    }
    .media img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
      cursor: pointer;
    }
    .placeholder {
      width: 100%;
      height: 100%;
      border: 0;
      margin: 0;
      padding: 0;
      background: #e5e7eb;
      color: #6b7280;
      font-size: 12px;
      cursor: pointer;
    }
    .annotationBadge {
      position: absolute;
      right: 8px;
      top: 8px;
      font-size: 11px;
      line-height: 1;
      padding: 5px 7px;
      border-radius: 999px;
      border: 1px solid #93c5fd;
      color: #1e3a8a;
      background: rgba(219, 234, 254, 0.96);
      font-weight: 600;
    }
    .body { padding: 12px; display: grid; gap: 8px; }
    .body h3 { margin: 0; font-size: 14px; line-height: 1.35; }
    .body p { margin: 0; font-size: 12px; line-height: 1.45; }
    .meta { color: #64748b; }
    .notes { white-space: pre-wrap; }
    .cardActions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
    .btn {
      border: 1px solid #cdd6e4;
      border-radius: 999px;
      padding: 6px 10px;
      background: #f8fafc;
      color: #1f2937;
      text-decoration: none;
      font-size: 12px;
      line-height: 1;
      cursor: pointer;
      font-family: inherit;
    }
    .btn:hover { border-color: #60a5fa; }
    .btn.linkBtn { color: #1d4ed8; }
    .muted { color: #6b7280; font-size: 12px; }
    .modal {
      position: fixed;
      inset: 0;
      background: rgba(2, 6, 23, 0.56);
      display: grid;
      place-items: center;
      padding: 14px;
      z-index: 20;
    }
    .modal.hidden { display: none; }
    .modalCard {
      width: min(980px, 96vw);
      max-height: 94vh;
      overflow: auto;
      border-radius: 14px;
      background: #ffffff;
      border: 1px solid #dbe0e8;
      box-shadow: 0 10px 32px rgba(15, 23, 42, 0.24);
      padding: 12px;
    }
    .modalHeader { display: flex; justify-content: space-between; gap: 8px; align-items: flex-start; }
    .modalHeader h2 { margin: 0; font-size: 18px; line-height: 1.3; }
    .modalBody { margin-top: 10px; display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(0, 0.8fr); gap: 12px; }
    .modalMedia {
      position: relative;
      border: 1px solid #dbe0e8;
      border-radius: 12px;
      background: #f8fafc;
      min-height: 240px;
      aspect-ratio: 4 / 3;
      overflow: hidden;
    }
    .modalMedia img {
      width: 100%;
      height: 100%;
      object-fit: contain;
      display: block;
      background: #eef2f7;
    }
    .modalMedia .placeholder {
      position: absolute;
      inset: 0;
      display: grid;
      place-items: center;
      cursor: default;
    }
    .markerLayer {
      position: absolute;
      inset: 0;
      pointer-events: none;
    }
    .marker {
      position: absolute;
      transform: translate(-50%, -50%);
      width: 24px;
      height: 24px;
      border-radius: 999px;
      border: 1px solid rgba(30, 58, 138, 0.55);
      background: rgba(191, 219, 254, 0.95);
      color: #1e3a8a;
      font-size: 11px;
      display: grid;
      place-items: center;
      font-weight: 700;
      box-shadow: 0 2px 7px rgba(30, 64, 175, 0.26);
    }
    .modalInfo { display: grid; gap: 10px; align-content: start; }
    .modalInfo h3 { margin: 0; font-size: 13px; }
    .annotations { margin: 0; padding-left: 18px; display: grid; gap: 6px; }
    .annotations li { font-size: 12px; line-height: 1.4; }
    .saveGuide { border-top: 1px solid #e5e7eb; padding-top: 10px; }
    .saveGuide ol { margin: 6px 0 0; padding-left: 18px; }
    .saveGuide li { font-size: 12px; line-height: 1.4; }
    @media (max-width: 860px) {
      .modalBody { grid-template-columns: 1fr; }
      .modalMedia { min-height: 180px; }
    }
  </style>
</head>
<body>
  <header>
    <h1>Inspirations Share</h1>
    <p>__HEADER_JSON__</p>
    <div class="saveSteps">
      <strong>How to save this idea</strong>
      <ol>
        <li>Click <em>Show Details</em> to view a larger image and notes.</li>
        <li>Click <em>Open Source</em> to open the original page.</li>
        <li>Save or bookmark from the original source page.</li>
      </ol>
    </div>
  </header>
  <main>
    __CARDS_HTML__
  </main>
  <div id="detailsModal" class="modal hidden" role="dialog" aria-modal="true" aria-labelledby="detailsTitle">
    <div class="modalCard">
      <div class="modalHeader">
        <div>
          <h2 id="detailsTitle">Details</h2>
          <p id="detailsMeta" class="meta"></p>
        </div>
        <button type="button" id="closeDetails" class="btn">Close</button>
      </div>
      <div class="modalBody">
        <div class="modalMedia">
          <img id="detailsImage" alt="" />
          <div id="detailsPlaceholder" class="placeholder">No preview available.</div>
          <div id="detailsMarkers" class="markerLayer"></div>
        </div>
        <div class="modalInfo">
          <div class="cardActions">
            <a id="detailsSourceLink" class="btn linkBtn" href="#" target="_blank" rel="noopener noreferrer">Open Source</a>
            <span id="detailsNoSource" class="muted">No source link</span>
          </div>
          <p id="detailsAnnCount" class="meta"></p>
          <ul id="detailsAnnList" class="annotations"></ul>
          <div>
            <h3>General Notes</h3>
            <p id="detailsNotes" class="notes"></p>
          </div>
          <div class="saveGuide">
            <h3>How to save this idea</h3>
            <ol>
              <li>Click Open Source.</li>
              <li>Save or bookmark from the original page.</li>
            </ol>
          </div>
        </div>
      </div>
    </div>
  </div>
  <script id="details-data" type="application/json">__DETAILS_JSON__</script>
  <script>
    const detailsById = JSON.parse(document.getElementById("details-data").textContent || "{}");
    const previewByAssetId = {};
    document.querySelectorAll(".detailPreview").forEach((node) => {
      const assetId = node.getAttribute("data-preview-id") || "";
      if (!assetId) return;
      previewByAssetId[assetId] = node.tagName === "IMG" ? (node.getAttribute("src") || "") : "";
    });
    const modal = document.getElementById("detailsModal");
    const titleEl = document.getElementById("detailsTitle");
    const metaEl = document.getElementById("detailsMeta");
    const imageEl = document.getElementById("detailsImage");
    const placeholderEl = document.getElementById("detailsPlaceholder");
    const markersEl = document.getElementById("detailsMarkers");
    const annCountEl = document.getElementById("detailsAnnCount");
    const annListEl = document.getElementById("detailsAnnList");
    const notesEl = document.getElementById("detailsNotes");
    const sourceLinkEl = document.getElementById("detailsSourceLink");
    const noSourceEl = document.getElementById("detailsNoSource");

    function clamp01(value) {
      const n = Number(value);
      if (!Number.isFinite(n)) return 0;
      return Math.min(1, Math.max(0, n));
    }

    function closeDetails() {
      modal.classList.add("hidden");
    }

    function renderMarkers(annotations) {
      markersEl.innerHTML = "";
      annotations.forEach((ann, idx) => {
        const marker = document.createElement("div");
        marker.className = "marker";
        marker.style.left = `${clamp01(ann.x) * 100}%`;
        marker.style.top = `${clamp01(ann.y) * 100}%`;
        marker.textContent = String(idx + 1);
        marker.title = ann.text || `Note ${idx + 1}`;
        markersEl.appendChild(marker);
      });
    }

    function openDetails(assetId) {
      const detail = detailsById[assetId];
      if (!detail) return;
      titleEl.textContent = detail.title || "(untitled)";
      const imported = detail.imported_at ? ` • Imported: ${detail.imported_at}` : "";
      metaEl.textContent = `Source: ${detail.source || ""}${imported}`;

      const previewSrc = previewByAssetId[assetId] || "";
      if (previewSrc) {
        imageEl.src = previewSrc;
        imageEl.style.display = "block";
        placeholderEl.style.display = "none";
      } else {
        imageEl.removeAttribute("src");
        imageEl.style.display = "none";
        placeholderEl.style.display = "grid";
      }

      if (detail.source_ref) {
        sourceLinkEl.href = detail.source_ref;
        sourceLinkEl.style.display = "inline-flex";
        noSourceEl.style.display = "none";
      } else {
        sourceLinkEl.removeAttribute("href");
        sourceLinkEl.style.display = "none";
        noSourceEl.style.display = "inline";
      }

      const annotations = Array.isArray(detail.annotations) ? detail.annotations : [];
      const countLabel = annotations.length === 1 ? "annotation" : "annotations";
      annCountEl.textContent = annotations.length ? `${annotations.length} ${countLabel} on this item` : "No annotations on this item.";
      annListEl.innerHTML = "";
      if (annotations.length) {
        annotations.forEach((ann, idx) => {
          const li = document.createElement("li");
          const text = `${ann.text || ""}`.trim() || "No text";
          li.textContent = `${idx + 1}. ${text}`;
          annListEl.appendChild(li);
        });
      } else {
        const li = document.createElement("li");
        li.textContent = "No annotation notes recorded.";
        annListEl.appendChild(li);
      }
      renderMarkers(annotations);
      notesEl.textContent = (detail.notes || "").trim() || "No general notes.";
      modal.classList.remove("hidden");
    }

    document.querySelectorAll(".detailBtn").forEach((btn) => {
      btn.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        openDetails(btn.getAttribute("data-asset-id") || "");
      });
    });

    document.getElementById("closeDetails").addEventListener("click", closeDetails);
    modal.addEventListener("click", (event) => {
      if (event.target === modal) closeDetails();
    });
    window.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeDetails();
    });
  </script>
</body>
</html>
""".replace("__HEADER_JSON__", header_json).replace("__CARDS_HTML__", "".join(cards)).replace("__DETAILS_JSON__", details_json)
    out_path.write_text(payload, encoding="utf-8")

    return {
        "ok": True,
        "path": str(out_path),
        "exported_assets": len(rows),
        "embedded_previews": embedded,
        "remote_previews": remote,
        "no_preview": no_preview,
        "source": source or None,
        "collection_id": collection_id or None,
        "limit": limit if limit > 0 else None,
    }


def _slugify_filename(value: str, *, fallback: str = "collection") -> str:
    text = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(value or "").strip().lower())
    text = re.sub(r"-+", "-", text).strip("-._")
    return text[:80] or fallback


def _markdown_escape(value: Any) -> str:
    text = str(value or "")
    # Keep prose readable while avoiding accidental Markdown structure.
    return text.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def _latex_escape(value: Any) -> str:
    text = str(value or "")
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(ch, ch) for ch in text)


def _latex_url_arg(value: str) -> str:
    # \url handles normal URL punctuation, but braces terminate the TeX arg.
    return str(value or "").replace("\\", "%5C").replace("{", "%7B").replace("}", "%7D")


def _collection_pdf_detail_text(notes: str, description: str) -> str:
    text = (notes or description or "").strip()
    text = re.sub(r"\s+", " ", text)
    if len(text) <= 320:
        return text
    return text[:317].rstrip() + "..."


def _collection_pdf_image_height(
    *,
    title: str,
    detail_text: str,
    annotations: list[dict[str, Any]],
    label_count: int,
) -> str:
    detail_units = 0
    if len(title) > 110:
        detail_units += 1
    if detail_text:
        detail_units += 2 if len(detail_text) > 160 else 1
    if label_count:
        detail_units += 1
    if annotations:
        detail_units += min(2, len(annotations))
    if detail_units >= 6:
        return "5.55in"
    if detail_units >= 4:
        return "5.95in"
    if detail_units >= 2:
        return "6.25in"
    if detail_units >= 1:
        return "6.45in"
    return "6.70in"


def _collection_pdf_labels_by_asset(db: Db, *, asset_ids: list[str]) -> dict[str, list[str]]:
    if not asset_ids:
        return {}
    placeholders = ",".join(["?"] * len(asset_ids))
    rows = db.query(
        f"""
        select asset_id, label
        from asset_labels
        where asset_id in ({placeholders})
        order by lower(label), label
        """,
        tuple(asset_ids),
    )
    grouped: dict[str, list[str]] = {aid: [] for aid in asset_ids}
    seen: dict[str, set[str]] = {aid: set() for aid in asset_ids}
    for row in rows:
        asset_id = str(row["asset_id"] or "")
        label = str(row["label"] or "").strip()
        key = label.casefold()
        if not asset_id or not label or key in seen.setdefault(asset_id, set()):
            continue
        seen[asset_id].add(key)
        grouped.setdefault(asset_id, []).append(label)
    return grouped


def _is_private_or_local_host(host: str) -> bool:
    clean = str(host or "").strip().lower().strip("[]")
    if not clean:
        return True
    if clean in {"localhost", "0.0.0.0", "::1"}:
        return True
    if clean.endswith(".local"):
        return True
    if clean.startswith("127."):
        return True
    if clean.startswith("10."):
        return True
    if clean.startswith("192.168."):
        return True
    parts = clean.split(".")
    if len(parts) >= 2 and parts[0] == "172":
        try:
            second = int(parts[1])
        except ValueError:
            second = -1
        if 16 <= second <= 31:
            return True
    return False


def _external_source_url(row: dict[str, Any]) -> str:
    for key in ("source_url", "source_ref"):
        raw = str(row.get(key) or "").strip()
        if not raw:
            continue
        parsed = urlparse(raw)
        if parsed.scheme.lower() not in {"http", "https"}:
            continue
        if not parsed.netloc or _is_private_or_local_host(parsed.hostname or ""):
            continue
        path = parsed.path or ""
        if path.startswith(("/api", "/media", "/store", "/app")):
            continue
        return raw
    return ""


def _collection_pdf_rows(db: Db, *, collection_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    collection_rows = db.query(
        """
        select id, name, description, created_at, updated_at
        from collections
        where id = ?
        limit 1
        """,
        (collection_id,),
    )
    if not collection_rows:
        raise FileNotFoundError("collection not found")

    hidden_collection_id = str(
        db.query_value("select id from collections where lower(name)='hidden' limit 1") or ""
    )
    params: list[Any] = [collection_id]
    hidden_filter = ""
    if hidden_collection_id:
        hidden_filter = """
          and a.id not in (
            select h.asset_id
            from collection_items h
            where h.collection_id = ?
          )
        """
        params.append(hidden_collection_id)

    rows = db.query(
        f"""
        select
          a.id,
          a.source,
          a.source_ref,
          a.source_url,
          a.source_domain,
          a.source_name,
          a.title,
          a.description,
          a.board,
          a.notes,
          a.image_url,
          a.stored_path,
          a.thumb_path,
          a.imported_at,
          a.media_status,
          a.content_kind,
          a.creator_name,
          ci.position
        from collection_items ci
        join assets a on a.id = ci.asset_id
        where ci.collection_id = ?
          and (a.triage_status is null or a.triage_status != 'hidden')
          {hidden_filter}
        order by ci.position asc, a.imported_at desc
        """,
        tuple(params),
    )
    return dict(collection_rows[0]), [dict(row) for row in rows]


def _collection_pdf_image_path(row: dict[str, Any]) -> Path | None:
    stored_path = _existing_local_path(row.get("stored_path"))
    if stored_path and _looks_like_image_ref(str(row.get("stored_path") or "")):
        return stored_path
    thumb_path = _existing_local_path(row.get("thumb_path"))
    if thumb_path:
        return thumb_path
    return None


def _write_collection_pdf_markdown(
    *,
    db: Db,
    collection: dict[str, Any],
    rows: list[dict[str, Any]],
    markdown_path: Path,
    media_dir: Path,
) -> dict[str, Any]:
    copied_preview_urls: dict[str, str] = {}
    asset_ids = [str(row.get("id") or "").strip() for row in rows if str(row.get("id") or "").strip()]
    annotations_by_asset = _annotations_by_asset(db, asset_ids=asset_ids)
    labels_by_asset = _collection_pdf_labels_by_asset(db, asset_ids=asset_ids)
    collection_name = str(collection.get("name") or "Collection").strip() or "Collection"
    collection_description = str(collection.get("description") or "").strip()
    exported_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines: list[str] = [
        "---",
        f'title-meta: "{collection_name.replace(chr(34), chr(39))}"',
        "geometry: margin=0.35in",
        "urlcolor: blue",
        "linkcolor: blue",
        "header-includes:",
        r"  - \usepackage{graphicx}",
        r"  - \usepackage{url}",
        r"  - \usepackage{tikz}",
        r"  - \usepackage{xcolor}",
        r"  - \usepackage{fancyhdr}",
        r"  - \definecolor{plateText}{HTML}{2C2825}",
        r"  - \definecolor{plateMuted}{HTML}{5F5852}",
        r"  - \definecolor{plateLabel}{HTML}{6B6158}",
        r"  - \definecolor{plateRule}{HTML}{D8D4CF}",
        r"  - \definecolor{plateChip}{HTML}{F7F4EF}",
        r"  - \definecolor{plateChipMore}{HTML}{FBF6E8}",
        r"  - \definecolor{markerOne}{HTML}{6F5AA8}",
        r"  - \definecolor{markerTwo}{HTML}{C4787A}",
        r"  - \definecolor{markerThree}{HTML}{7A9B8A}",
        r"  - \definecolor{markerFour}{HTML}{B8860B}",
        r"  - \definecolor{markerFive}{HTML}{5A8FC4}",
        r"  - \setlength{\parindent}{0pt}",
        r"  - \setlength{\parskip}{0.2em}",
        r"  - \setlength{\footskip}{0.20in}",
        r"  - \color{plateText}",
        r"  - \pagestyle{fancy}",
        r"  - \fancyhf{}",
        r"  - \renewcommand{\headrulewidth}{0pt}",
        r"  - \renewcommand{\footrulewidth}{0pt}",
        r"  - \fancyfoot[C]{\fontsize{7}{8}\selectfont\color{plateMuted}\thepage}",
        r"  - \tikzset{annotationBadge/.style={circle, draw=white, line width=0.8pt, text=white, font=\scriptsize\bfseries, inner sep=0pt, minimum size=1.55em}}",
        r"  - \tikzset{annotationBadge1/.style={annotationBadge, fill=markerOne}, annotationBadge2/.style={annotationBadge, fill=markerTwo}, annotationBadge3/.style={annotationBadge, fill=markerThree}, annotationBadge4/.style={annotationBadge, fill=markerFour}, annotationBadge5/.style={annotationBadge, fill=markerFive}}",
        r"  - \tikzset{labelChip/.style={draw=plateRule, fill=plateChip, rounded corners=7pt, line width=0.35pt, inner xsep=5pt, inner ysep=2pt, text=plateMuted, font=\fontsize{7}{8}\selectfont}}",
        r"  - \tikzset{labelMoreChip/.style={labelChip, fill=plateChipMore, text=plateLabel}}",
        r"  - \newcommand{\plateSection}[1]{\vspace{0.055in}\noindent{\color{plateRule}\rule{\linewidth}{0.35pt}}\par\vspace{0.025in}{\fontsize{7.5}{9}\selectfont\bfseries\color{plateLabel}\MakeUppercase{#1}\par}\vspace{0.012in}}",
        r"  - \newcommand{\plateChip}[1]{\tikz[baseline=(chip.base)]{\node[labelChip] (chip) {#1};}}",
        r"  - \newcommand{\plateMoreChip}[1]{\tikz[baseline=(chip.base)]{\node[labelMoreChip] (chip) {#1};}}",
        "---",
        "",
        r"\begin{titlepage}",
        r"\vspace*{1.0in}",
        r"\begin{minipage}{0.88\linewidth}",
        r"{\fontsize{9}{11}\selectfont\bfseries\color{plateLabel} INSPIRATIONS\par}",
        r"\vspace{0.12in}",
        r"{\color{plateRule}\rule{\linewidth}{0.7pt}\par}",
        r"\vspace{0.24in}",
        f"{{\\fontsize{{24}}{{28}}\\selectfont\\bfseries\\color{{plateText}} {_latex_escape(collection_name)}\\par}}",
        r"\vspace{0.16in}",
    ]
    if collection_description:
        lines.extend([
            f"{{\\fontsize{{11}}{{15}}\\selectfont\\color{{plateMuted}} {_latex_escape(collection_description)}\\par}}",
            r"\vspace{0.18in}",
        ])
    lines.extend([
        r"{\color{plateRule}\rule{0.62\linewidth}{0.45pt}\par}",
        r"\vspace{0.14in}",
        f"{{\\fontsize{{9}}{{12}}\\selectfont\\color{{plateMuted}} {len(rows)} items\\par}}",
        f"{{\\fontsize{{9}}{{12}}\\selectfont\\color{{plateMuted}} Exported {_latex_escape(exported_at)}\\par}}",
        r"\end{minipage}",
        r"\vfill",
        r"{\fontsize{8}{10}\selectfont\color{plateMuted} Designer-ready collection PDF\par}",
        r"\end{titlepage}",
        "",
    ])

    embedded_images = 0
    missing_images = 0
    external_links = 0
    missing_links = 0
    copied_images: list[str] = []

    for index, row in enumerate(rows, start=1):
        asset_id = str(row.get("id") or "").strip()
        title = _title_for_export(row)
        source = _source_label(str(row.get("source") or ""))
        board = str(row.get("board") or "").strip()
        creator_name = str(row.get("creator_name") or "").strip()
        notes = str(row.get("notes") or "").strip()
        description = str(row.get("description") or "").strip()
        detail_text = _collection_pdf_detail_text(notes, description)
        source_url = _external_source_url(row)
        annotations = annotations_by_asset.get(asset_id, [])
        labels = labels_by_asset.get(asset_id, [])
        visible_labels = labels[:12]
        extra_label_count = max(0, len(labels) - len(visible_labels))
        image_path = _collection_pdf_image_path(row)
        image_height = _collection_pdf_image_height(
            title=title,
            detail_text=detail_text,
            annotations=annotations,
            label_count=len(labels),
        )
        meta_bits = [bit for bit in (board, source, f"by {creator_name}" if creator_name else "") if bit]

        lines.extend([
            r"\begingroup",
            r"\setlength{\parskip}{0pt}",
            f"\\noindent{{\\fontsize{{8}}{{10}}\\selectfont\\bfseries\\color{{plateLabel}} ITEM {index}\\par}}",
            r"\vspace{0.018in}",
            f"\\noindent{{\\fontsize{{14}}{{16}}\\selectfont\\bfseries\\color{{plateText}} {_latex_escape(title)}\\par}}",
            r"\vspace{0.025in}",
            r"\begin{minipage}{\linewidth}",
            r"\fontsize{8}{10}\selectfont\color{plateMuted}",
        ])
        if meta_bits:
            lines.append(f"{_latex_escape(' · '.join(meta_bits))}\\par")
        lines.append(f"Collection: {_latex_escape(collection_name)}\\par")
        lines.append(f"Item ID {_latex_escape(asset_id)}\\par")
        if source_url:
            external_links += 1
            lines.append(f"\\textbf{{Source URL:}} \\url{{{_latex_url_arg(source_url)}}}\\par")
        else:
            missing_links += 1
            lines.append(r"\textbf{Source URL:} No source URL available\par")
        lines.extend([r"\end{minipage}", r"\vspace{0.07in}"])

        if image_path:
            image_url = _copy_preview_to_assets(
                image_path,
                assets_dir=media_dir,
                copied_urls=copied_preview_urls,
            )
            embedded_images += 1
            copied_images.append(image_url)
            lines.extend([
                r"\begin{center}",
                r"\begin{tikzpicture}",
                f"\\node[inner sep=0pt,anchor=south west] (itemimage) at (0,0) {{\\includegraphics[width=0.96\\linewidth,height={image_height},keepaspectratio]{{{image_url}}}}};",
                r"\draw[draw=plateRule, line width=0.45pt, rounded corners=7pt] ([xshift=-6pt,yshift=-6pt]itemimage.south west) rectangle ([xshift=6pt,yshift=6pt]itemimage.north east);",
            ])
            if annotations:
                lines.append(r"\begin{scope}[x={(itemimage.south east)},y={(itemimage.north west)}]")
                for ann_idx, ann in enumerate(annotations, start=1):
                    x = max(0.0, min(1.0, float(ann.get("x") or 0)))
                    # App annotation coordinates are top-left based; TikZ scope is bottom-left based.
                    y = 1.0 - max(0.0, min(1.0, float(ann.get("y") or 0)))
                    badge_style = ((ann_idx - 1) % 5) + 1
                    lines.append(f"\\node[annotationBadge{badge_style}] at ({x:.4f},{y:.4f}) {{{ann_idx}}};")
                lines.append(r"\end{scope}")
            lines.extend([
                r"\end{tikzpicture}",
                r"\end{center}",
                r"\vspace{-0.09in}",
            ])
        else:
            missing_images += 1
            lines.extend([
                r"\vspace*{2.65in}",
                r"\begin{center}{\color{plateMuted}\emph{No local preview image available.}}\end{center}",
                r"\vspace*{2.3in}",
            ])

        lines.append(r"\begin{minipage}{\linewidth}")
        if detail_text:
            detail_label = "Notes" if notes else "Description"
            lines.append(f"\\plateSection{{{detail_label}}}")
            lines.append(f"{{\\fontsize{{8}}{{10}}\\selectfont {_latex_escape(detail_text)}\\par}}")

        if visible_labels:
            lines.append(r"\plateSection{Labels}")
            label_parts = [
                f"\\plateChip{{{_latex_escape(label)}}}\\allowbreak\\hspace{{0.035in}}"
                for label in visible_labels
            ]
            if extra_label_count:
                label_parts.append(f"\\plateMoreChip{{+{extra_label_count} more}}")
            lines.append("".join(label_parts) + r"\par")

        if annotations:
            lines.append(r"\plateSection{Annotations}")
            for ann_idx, ann in enumerate(annotations, start=1):
                ann_text = str(ann.get("text") or "").strip() or "No text"
                ann_text = _collection_pdf_detail_text(ann_text, "")
                lines.append(f"{{\\fontsize{{8}}{{10}}\\selectfont\\textbf{{\\#{ann_idx}}} {_latex_escape(ann_text)}\\par}}")

        lines.extend([r"\end{minipage}", r"\par", r"\endgroup", ""])

        if index != len(rows):
            lines.extend(["\\newpage", ""])

    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return {
        "markdown_path": str(markdown_path),
        "media_dir": str(media_dir),
        "embedded_images": embedded_images,
        "missing_images": missing_images,
        "external_links": external_links,
        "missing_links": missing_links,
        "copied_images": sorted(set(copied_images)),
    }


def _render_markdown_pdf(*, markdown_path: Path, out_path: Path) -> None:
    pandoc = shutil.which("pandoc")
    tectonic = shutil.which("tectonic")
    missing = [name for name, path in (("pandoc", pandoc), ("tectonic", tectonic)) if not path]
    if missing:
        raise PdfToolUnavailableError(f"Missing PDF tool(s): {', '.join(missing)}")
    markdown_dir = markdown_path.parent.resolve()
    cmd = [
        str(pandoc),
        str(markdown_path.name),
        "--resource-path",
        ".",
        "--pdf-engine=tectonic",
        "-o",
        str(out_path),
    ]
    try:
        completed = subprocess.run(cmd, check=False, capture_output=True, text=True, cwd=markdown_dir)
    except OSError as exc:
        raise PdfRenderError(f"PDF renderer failed to start: {exc}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise PdfRenderError(detail or f"pandoc exited with status {completed.returncode}")


def export_collection_pdf(
    db: Db,
    *,
    collection_id: str,
    out_path: Path | None = None,
    render_pdf: bool = True,
) -> dict[str, Any]:
    """Generate a standalone designer-facing PDF for a single collection."""
    collection_id = str(collection_id or "").strip()
    if not collection_id:
        raise ValueError("collection_id required")
    collection, rows = _collection_pdf_rows(db, collection_id=collection_id)
    collection_name = str(collection.get("name") or "Collection").strip() or "Collection"
    if out_path is None:
        out_path = Path("data") / "exports" / f"{_slugify_filename(collection_name)}.pdf"
    out_path = out_path.expanduser().resolve()
    if out_path.suffix.lower() != ".pdf":
        out_path = out_path.with_suffix(".pdf")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path = out_path.with_suffix(".md")
    media_dir = _prepare_preview_assets_dir(out_path=out_path)
    source_report = _write_collection_pdf_markdown(
        db=db,
        collection=collection,
        rows=rows,
        markdown_path=markdown_path,
        media_dir=media_dir,
    )
    if render_pdf:
        _render_markdown_pdf(markdown_path=markdown_path, out_path=out_path)

    return {
        "ok": True,
        "path": str(out_path),
        "markdown_path": str(markdown_path),
        "media_dir": str(media_dir),
        "collection_id": collection_id,
        "collection_name": collection_name,
        "exported_assets": len(rows),
        "rendered_pdf": bool(render_pdf),
        **source_report,
    }


def _rows_for_portal(
    db: Db,
    *,
    source: str = "",
    collection_ids: list[str] | None = None,
    include_unassigned: bool = False,
    limit: int = 0,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    joins: list[str] = []
    collection_ids = [str(x).strip() for x in (collection_ids or []) if str(x).strip()]
    if source:
        sources = [s.strip() for s in source.split(",") if s.strip()]
        if sources:
            clauses.append("a.source in (%s)" % ",".join(["?"] * len(sources)))
            params.extend(sources)
    hidden_collection_id = db.query_value("select id from collections where lower(name)='hidden' limit 1")
    if collection_ids:
        joins.append("join collection_items ci_filter on ci_filter.asset_id = a.id")
        clauses.append("ci_filter.collection_id in (%s)" % ",".join(["?"] * len(collection_ids)))
        params.extend(collection_ids)
    elif not include_unassigned:
        joins.append("join collection_items ci_filter on ci_filter.asset_id = a.id")
        if hidden_collection_id:
            clauses.append("ci_filter.collection_id != ?")
            params.append(str(hidden_collection_id))
    if hidden_collection_id and hidden_collection_id not in collection_ids:
        clauses.append("a.id not in (select asset_id from collection_items where collection_id = ?)")
        params.append(str(hidden_collection_id))
    where = "where " + " and ".join(clauses) if clauses else ""
    join_sql = "\n        " + "\n        ".join(joins) if joins else ""
    limit_sql = "limit ?" if limit and limit > 0 else ""
    if limit_sql:
        params.append(int(limit))
    rows = db.query(
        f"""
        select distinct a.id, a.source, a.source_ref, a.title, a.description, a.board, a.notes,
               a.image_url, a.stored_path, a.thumb_path, a.imported_at, a.media_status, a.content_kind
        from assets a
        {join_sql}
        {where}
        order by a.imported_at desc
        {limit_sql}
        """,
        tuple(params),
    )
    return [dict(r) for r in rows]


def _labels_by_asset(db: Db, *, asset_ids: list[str]) -> dict[str, list[str]]:
    if not asset_ids:
        return {}
    placeholders = ",".join(["?"] * len(asset_ids))
    rows = db.query(
        f"""
        select distinct asset_id, label
        from asset_labels
        where asset_id in ({placeholders})
        order by lower(label) asc
        """,
        tuple(asset_ids),
    )
    out: dict[str, list[str]] = {aid: [] for aid in asset_ids}
    for row in rows:
        aid = str(row["asset_id"])
        label = str(row["label"] or "").strip()
        if not label:
            continue
        out.setdefault(aid, []).append(label)
    return out


def _memberships_by_asset(
    db: Db,
    *,
    asset_ids: list[str],
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    if not asset_ids:
        return {}, []
    placeholders = ",".join(["?"] * len(asset_ids))
    rows = db.query(
        f"""
        select ci.asset_id, ci.collection_id, ci.position, c.name
        from collection_items ci
        join collections c on c.id = ci.collection_id
        where ci.asset_id in ({placeholders})
        order by lower(c.name) asc, ci.position asc
        """,
        tuple(asset_ids),
    )
    grouped: dict[str, list[dict[str, Any]]] = {aid: [] for aid in asset_ids}
    counts: dict[str, int] = {}
    names: dict[str, str] = {}
    for row in rows:
        aid = str(row["asset_id"])
        cid = str(row["collection_id"])
        cname = str(row["name"] or "").strip() or "(untitled)"
        entry = {
            "id": cid,
            "name": cname,
            "position": int(row["position"] or 0),
        }
        grouped.setdefault(aid, []).append(entry)
    for aid in asset_ids:
        seen: set[str] = set()
        for m in grouped.get(aid, []):
            cid = str(m["id"])
            names[cid] = str(m["name"])
            if cid in seen:
                continue
            seen.add(cid)
            counts[cid] = counts.get(cid, 0) + 1
    collections = [
        {"id": cid, "name": names.get(cid, "(untitled)"), "count": int(counts.get(cid, 0))}
        for cid in counts.keys()
    ]
    collections.sort(key=lambda x: (str(x["name"]).lower(), str(x["id"])))
    return grouped, collections


def _resolve_preview(
    row: dict[str, Any],
    *,
    out_path: Path,
    embed_local_previews: bool,
    preview_assets_dir: Path | None,
    copied_preview_urls: dict[str, str],
) -> tuple[str, str]:
    thumb_path = _existing_local_path(row.get("thumb_path"))
    stored_path = _existing_local_path(row.get("stored_path"))
    image_url = str(row.get("image_url") or "").strip()
    if thumb_path:
        return _local_preview_src(
            thumb_path,
            out_path=out_path,
            embed_local_previews=embed_local_previews,
            preview_assets_dir=preview_assets_dir,
            copied_preview_urls=copied_preview_urls,
        )
    if stored_path and _looks_like_image_ref(str(row.get("stored_path") or "")):
        return _local_preview_src(
            stored_path,
            out_path=out_path,
            embed_local_previews=embed_local_previews,
            preview_assets_dir=preview_assets_dir,
            copied_preview_urls=copied_preview_urls,
        )
    if image_url and _looks_like_image_ref(image_url):
        return image_url, "remote"
    return "", "none"


def _resolve_detail_media(
    row: dict[str, Any],
    *,
    out_path: Path,
    embed_local_previews: bool,
    preview_assets_dir: Path | None,
    copied_preview_urls: dict[str, str],
) -> str:
    stored_path = _existing_local_path(row.get("stored_path"))
    thumb_path = _existing_local_path(row.get("thumb_path"))
    image_url = str(row.get("image_url") or "").strip()
    if stored_path and _looks_like_image_ref(str(row.get("stored_path") or "")):
        return _local_preview_src(
            stored_path,
            out_path=out_path,
            embed_local_previews=embed_local_previews,
            preview_assets_dir=preview_assets_dir,
            copied_preview_urls=copied_preview_urls,
        )[0]
    if image_url and _looks_like_image_ref(image_url):
        return image_url
    if thumb_path:
        return _local_preview_src(
            thumb_path,
            out_path=out_path,
            embed_local_previews=embed_local_previews,
            preview_assets_dir=preview_assets_dir,
            copied_preview_urls=copied_preview_urls,
        )[0]
    return ""


def export_static_share_portal(
    db: Db,
    *,
    out_path: Path,
    source: str = "",
    collection_ids: list[str] | None = None,
    include_unassigned: bool = False,
    limit: int = 0,
    title: str = "Inspirations Share Portal",
) -> dict[str, Any]:
    rows = _rows_for_portal(
        db,
        source=source,
        collection_ids=collection_ids or [],
        include_unassigned=include_unassigned,
        limit=limit,
    )
    out_path = out_path.expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    asset_ids = [str(row.get("id") or "").strip() for row in rows if str(row.get("id") or "").strip()]
    annotations_by_asset = _annotations_by_asset(db, asset_ids=asset_ids)
    labels_by_asset = _labels_by_asset(db, asset_ids=asset_ids)
    memberships_by_asset, collections = _memberships_by_asset(db, asset_ids=asset_ids)

    items: list[dict[str, Any]] = []
    embed_local_previews = len(rows) <= PORTAL_EMBED_PREVIEW_MAX_ITEMS
    preview_assets_dir = _prepare_preview_assets_dir(out_path=out_path) if not embed_local_previews else None
    copied_preview_urls: dict[str, str] = {}
    scan_doc_counts: dict[tuple[str, int], int] = {}
    scan_pdf_by_sha: dict[str, Path] = {}
    for row in rows:
        source_key = str(row.get("source") or "").strip().lower()
        if source_key != "scan":
            continue
        source_ref = str(row.get("source_ref") or "").strip()
        title_value = str(row.get("title") or "").strip()
        scan_ref = _scan_ref_parts(source_ref)
        if not scan_ref:
            continue
        sha, _ = scan_ref
        doc_idx, _ = _scan_doc_parts(title_value)
        doc_key = int(doc_idx or 1)
        scan_doc_counts[(sha, doc_key)] = scan_doc_counts.get((sha, doc_key), 0) + 1
        pdf_path = (Path.cwd() / "store" / "originals" / "scan" / f"{sha}.pdf").resolve()
        if pdf_path.exists() and pdf_path.is_file():
            scan_pdf_by_sha[sha] = pdf_path
    scan_docs_dir: Path | None = None
    copied_scan_doc_urls: dict[str, str] = {}
    embedded_previews = 0
    linked_previews = 0
    remote_previews = 0
    no_preview = 0
    source_counts: dict[str, int] = {}
    media_counts: dict[str, int] = {}
    unassigned = 0
    for row in rows:
        aid = str(row.get("id") or "").strip()
        if not aid:
            continue
        preview_src, preview_kind = _resolve_preview(
            row,
            out_path=out_path,
            embed_local_previews=embed_local_previews,
            preview_assets_dir=preview_assets_dir,
            copied_preview_urls=copied_preview_urls,
        )
        if preview_kind == "embedded":
            embedded_previews += 1
        elif preview_kind == "linked":
            linked_previews += 1
        elif preview_kind == "remote":
            remote_previews += 1
        else:
            no_preview += 1
        memberships = memberships_by_asset.get(aid, [])
        if not memberships:
            unassigned += 1
        source_key = str(row.get("source") or "").strip().lower()
        source_label = _source_label(source_key)
        source_counts[source_key] = source_counts.get(source_key, 0) + 1
        media_key = str(row.get("media_status") or "").strip().lower() or "unknown"
        media_counts[media_key] = media_counts.get(media_key, 0) + 1
        title_value = _title_for_export(row)
        source_ref_value = str(row.get("source_ref") or "").strip()
        notes_value = str(row.get("notes") or "").strip()
        imported_raw = str(row.get("imported_at") or "").strip()
        imported_short = imported_raw[:10] if imported_raw else ""
        detail_src = _resolve_detail_media(
            row,
            out_path=out_path,
            embed_local_previews=embed_local_previews,
            preview_assets_dir=preview_assets_dir,
            copied_preview_urls=copied_preview_urls,
        ) or preview_src
        scan_doc_index: int | None = None
        scan_doc_page: int | None = None
        scan_doc_pages: int | None = None
        scan_pdf_src = ""
        if source_key == "scan":
            scan_ref = _scan_ref_parts(source_ref_value)
            doc_idx, doc_page = _scan_doc_parts(title_value)
            if scan_ref:
                sha, page_idx = scan_ref
                scan_doc_index = int(doc_idx or 1)
                scan_doc_page = int(doc_page or page_idx or 1)
                scan_doc_pages = int(scan_doc_counts.get((sha, scan_doc_index), 0) or 0) or None
                pdf_path = scan_pdf_by_sha.get(sha)
                if pdf_path:
                    if scan_docs_dir is None:
                        scan_docs_dir = out_path.parent / f"{out_path.stem}_docs"
                        if scan_docs_dir.exists():
                            shutil.rmtree(scan_docs_dir)
                        scan_docs_dir.mkdir(parents=True, exist_ok=True)
                    scan_pdf_src = _copy_preview_to_assets(
                        pdf_path,
                        assets_dir=scan_docs_dir,
                        copied_urls=copied_scan_doc_urls,
                    )
        item = {
            "id": aid,
            "title": title_value,
            "source_key": source_key,
            "source_label": source_label,
            "source_ref": source_ref_value,
            "board": str(row.get("board") or "").strip(),
            "description": str(row.get("description") or "").strip(),
            "notes": notes_value,
            "imported_at": imported_short,
            "media_status": media_key,
            "content_kind": str(row.get("content_kind") or "").strip().lower(),
            "preview_src": preview_src,
            "detail_src": detail_src,
            "preview_kind": preview_kind,
            "scan_doc_index": scan_doc_index,
            "scan_doc_page": scan_doc_page,
            "scan_doc_pages": scan_doc_pages,
            "scan_pdf_src": scan_pdf_src,
            "labels": labels_by_asset.get(aid, [])[:100],
            "collections": memberships,
            "annotations": annotations_by_asset.get(aid, []),
        }
        items.append(item)
    if unassigned:
        collections.append({"id": "__unassigned__", "name": "Unassigned", "count": unassigned})
    collections.sort(key=lambda x: (str(x["name"]).lower(), str(x["id"])))
    source_facets = [
        {"key": key, "name": _source_label(key), "count": int(source_counts[key])}
        for key in sorted(source_counts.keys())
        if key
    ]
    media_labels = {
        "image": "Image",
        "link_only": "Link only",
        "metadata_only": "Metadata only",
        "unknown": "Unknown",
    }
    media_facets = [
        {"key": key, "name": media_labels.get(key, key.replace("_", " ").title()), "count": int(media_counts[key])}
        for key in sorted(media_counts.keys())
        if key
    ]
    portal = {
        "title": (title or "Inspirations Share Portal").strip(),
        "semantic_enabled": False,
        "semantic_notice": "Semantic search is not available in shared view. Keyword search is used instead.",
        "source_filter": source or None,
        "collection_filter": [str(x).strip() for x in (collection_ids or []) if str(x).strip()] or None,
        "include_unassigned": bool(include_unassigned),
        "items": items,
        "collections": collections,
        "sources": source_facets,
        "media_statuses": media_facets,
    }
    portal_json = json.dumps(portal).replace("</", "<\\/")
    title_safe = html.escape(portal["title"])
    payload = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>__TITLE__</title>
  <style>
    :root {
      --bg: #f4f8fb;
      --panel: #ffffff;
      --text: #1f2937;
      --muted: #64748b;
      --line: #dbe5ef;
      --accent: #0f766e;
      --accent-soft: #d5f4ef;
      --shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Avenir Next", "Avenir", "Segoe UI", sans-serif;
      color: var(--text);
      background:
        radial-gradient(1000px 560px at 92% -15%, rgba(16, 185, 129, 0.16), transparent 62%),
        radial-gradient(900px 520px at -10% -30%, rgba(14, 165, 233, 0.14), transparent 66%),
        var(--bg);
    }
    .shell {
      width: min(1760px, 98vw);
      margin: 18px auto 30px;
      display: grid;
      gap: 14px;
    }
    .hero {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 16px;
      box-shadow: var(--shadow);
      padding: 16px;
      display: grid;
      gap: 10px;
    }
    .heroTop {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: flex-start;
      flex-wrap: wrap;
    }
    h1 {
      margin: 0;
      font-size: clamp(20px, 2.4vw, 30px);
      line-height: 1.1;
      color: #0f172a;
      letter-spacing: -0.02em;
    }
    .subtitle {
      margin: 4px 0 0;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.4;
    }
    .pill {
      border: 1px solid #cce6df;
      background: var(--accent-soft);
      color: #115e59;
      border-radius: 999px;
      padding: 7px 12px;
      font-size: 12px;
      font-weight: 600;
      white-space: nowrap;
    }
    .controls {
      display: grid;
      gap: 10px;
    }
    .controlRow {
      display: flex;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
    }
    .controlGroup {
      display: grid;
      gap: 6px;
    }
    .controlGroupLabel {
      color: #334155;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.02em;
      text-transform: uppercase;
    }
    #search {
      flex: 1 1 360px;
      min-width: 220px;
      border: 1px solid #b9d3e5;
      border-radius: 11px;
      padding: 10px 12px;
      font-size: 15px;
      background: #f8fcff;
      color: #0f172a;
    }
    #search:focus {
      outline: none;
      border-color: #38bdf8;
      box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.16);
      background: #ffffff;
    }
    .select, .checkboxRow button, #clearBtn {
      border: 1px solid #c9d9e7;
      border-radius: 10px;
      background: #fff;
      color: #0f172a;
      padding: 9px 11px;
      font-size: 13px;
      font-family: inherit;
    }
    .select {
      min-width: 220px;
    }
    .checkboxRow {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      align-items: center;
    }
    .sourceChip {
      border: 1px solid #ccdae7;
      border-radius: 999px;
      padding: 7px 11px;
      font-size: 12px;
      background: #fff;
      cursor: pointer;
      color: #1f2937;
    }
    .sourceChip.on {
      border-color: #7fd6ca;
      background: #e8faf6;
      color: #0f766e;
      font-weight: 700;
    }
    .checkWrap {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      color: #334155;
      font-size: 13px;
      user-select: none;
    }
    #clearBtn {
      cursor: pointer;
      background: #f8fafc;
    }
    #clearBtn:hover {
      border-color: #93c5fd;
    }
    .notice {
      background: #fff7ed;
      border: 1px solid #fed7aa;
      color: #9a3412;
      border-radius: 10px;
      padding: 9px 11px;
      font-size: 13px;
      display: none;
    }
    .notice.on { display: block; }
    .metaRow {
      display: flex;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
      color: var(--muted);
      font-size: 13px;
    }
    .graphControls {
      display: none;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 8px 10px;
      padding: 10px;
      border: 1px solid #d8e4ef;
      border-radius: 12px;
      background: #f9fcff;
    }
    .graphControls.on { display: grid; }
    .graphControl {
      display: grid;
      gap: 4px;
      color: #334155;
      font-size: 12px;
      font-weight: 600;
    }
    .graphControl input[type="range"] {
      width: 100%;
      accent-color: #0f766e;
    }
    .graphValue {
      color: #64748b;
      font-size: 11px;
      font-weight: 700;
      font-variant-numeric: tabular-nums;
    }
    #cards {
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(auto-fill, minmax(clamp(160px, 24vw, 220px), 1fr));
    }
    .viewToggle {
      display: inline-flex;
      gap: 6px;
      align-items: center;
      border: 1px solid #cfdae8;
      border-radius: 999px;
      padding: 4px;
      background: #f8fbff;
    }
    .viewBtn {
      border: 0;
      border-radius: 999px;
      background: transparent;
      color: #334155;
      font-size: 12px;
      font-weight: 700;
      padding: 6px 11px;
      cursor: pointer;
    }
    .viewBtn.on {
      background: #def8f3;
      color: #115e59;
    }
    .card {
      border: 1px solid var(--line);
      border-radius: 14px;
      background: var(--panel);
      box-shadow: var(--shadow);
      overflow: hidden;
      display: grid;
      grid-template-rows: auto 1fr;
      min-height: 300px;
    }
    .media {
      aspect-ratio: 4 / 3;
      background: #ecf2f8;
      position: relative;
      display: grid;
      place-items: center;
    }
    .media img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
      cursor: pointer;
    }
    .placeholder {
      width: 100%;
      height: 100%;
      display: grid;
      place-items: center;
      color: #64748b;
      font-size: 12px;
      text-align: center;
      padding: 12px;
      background: #e8eef5;
      cursor: pointer;
    }
    .badgeRow {
      position: absolute;
      left: 8px;
      bottom: 8px;
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      pointer-events: none;
    }
    .badge {
      border-radius: 999px;
      padding: 4px 7px;
      font-size: 11px;
      color: #fff;
      background: rgba(15, 23, 42, 0.74);
    }
    .badge.collection {
      background: rgba(15, 118, 110, 0.86);
    }
    .badge.scan {
      background: rgba(76, 29, 149, 0.86);
    }
    .body {
      display: grid;
      gap: 8px;
      padding: 10px 11px 11px;
    }
    .title {
      margin: 0;
      font-size: 15px;
      line-height: 1.3;
      color: #0f172a;
    }
    .cardMeta {
      color: #64748b;
      font-size: 12px;
      line-height: 1.4;
    }
    .labelRow {
      display: flex;
      flex-wrap: wrap;
      gap: 5px;
      min-height: 20px;
    }
    .label {
      font-size: 11px;
      border: 1px solid #d6e0ea;
      border-radius: 999px;
      padding: 3px 7px;
      color: #334155;
      background: #f8fafc;
    }
    .actions {
      margin-top: auto;
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      align-items: center;
    }
    .btn {
      border: 1px solid #c8d6e4;
      border-radius: 999px;
      background: #f8fafc;
      color: #0f172a;
      text-decoration: none;
      padding: 6px 10px;
      font-size: 12px;
      font-family: inherit;
      cursor: pointer;
      line-height: 1.1;
    }
    .btn.primary {
      border-color: #6dd5c8;
      background: #def8f3;
      color: #115e59;
      font-weight: 700;
    }
    .btn.link {
      color: #1d4ed8;
    }
    #empty {
      border: 1px dashed #c7d4e2;
      border-radius: 14px;
      padding: 22px;
      text-align: center;
      color: #64748b;
      background: rgba(255, 255, 255, 0.68);
      display: none;
    }
    #empty.on { display: block; }
    .graphWrap {
      border: 1px solid #d7e2ee;
      border-radius: 14px;
      background: rgba(255, 255, 255, 0.9);
      min-height: 360px;
      height: var(--graph-height, 560px);
      display: none;
      overflow: hidden;
      box-shadow: var(--shadow);
      position: relative;
    }
    .graphWrap.on { display: block; }
    .graphHint {
      position: absolute;
      left: 10px;
      top: 10px;
      z-index: 2;
      font-size: 12px;
      color: #334155;
      border: 1px solid #d4deea;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.92);
      padding: 5px 9px;
    }
    .graphSvg {
      width: 100%;
      height: 100%;
      display: block;
      touch-action: none;
    }
    .graphEmpty {
      min-height: 100%;
      display: grid;
      place-items: center;
      color: #64748b;
      font-size: 14px;
      text-align: center;
      padding: 16px;
    }
    .modal {
      position: fixed;
      inset: 0;
      display: none;
      place-items: center;
      background: rgba(15, 23, 42, 0.56);
      padding: 14px;
      z-index: 20;
    }
    .modal.on { display: grid; }
    .modalCard {
      width: min(1020px, 97vw);
      max-height: 94vh;
      overflow: auto;
      border-radius: 14px;
      border: 1px solid #d6e0eb;
      background: #fff;
      box-shadow: 0 12px 34px rgba(15, 23, 42, 0.28);
      padding: 12px;
      display: grid;
      gap: 10px;
    }
    .modalHeader {
      display: flex;
      justify-content: space-between;
      gap: 8px;
      align-items: flex-start;
    }
    #modalTitle {
      margin: 0;
      font-size: 20px;
      line-height: 1.3;
    }
    #modalMeta {
      margin: 4px 0 0;
      color: #64748b;
      font-size: 13px;
    }
    .modalBody {
      display: grid;
      grid-template-columns: minmax(0, 1.2fr) minmax(0, 0.8fr);
      gap: 12px;
    }
    .modalMedia {
      border: 1px solid #dbe5ef;
      border-radius: 12px;
      overflow: hidden;
      background: #eef3f8;
      aspect-ratio: 4 / 3;
      min-height: 220px;
      display: grid;
      place-items: center;
      position: relative;
    }
    .modalMedia img {
      width: 100%;
      height: 100%;
      object-fit: contain;
      display: block;
    }
    .modalPlaceholder {
      color: #64748b;
      font-size: 13px;
      text-align: center;
      padding: 14px;
    }
    .markerLayer {
      position: absolute;
      inset: 0;
      pointer-events: none;
    }
    .marker {
      position: absolute;
      transform: translate(-50%, -50%);
      width: 22px;
      height: 22px;
      border-radius: 999px;
      border: 1px solid rgba(30, 64, 175, 0.5);
      background: rgba(191, 219, 254, 0.95);
      color: #1e3a8a;
      display: grid;
      place-items: center;
      font-size: 11px;
      font-weight: 700;
    }
    .modalInfo {
      display: grid;
      gap: 10px;
      align-content: start;
    }
    .modalInfo h3 {
      margin: 0;
      font-size: 13px;
      color: #0f172a;
    }
    .modalInfo p {
      margin: 0;
      color: #334155;
      font-size: 13px;
      line-height: 1.45;
      white-space: pre-wrap;
    }
    .annList {
      margin: 0;
      padding-left: 18px;
      display: grid;
      gap: 6px;
    }
    .annList li {
      font-size: 12px;
      line-height: 1.4;
      color: #334155;
    }
    .footer {
      color: #64748b;
      font-size: 12px;
      text-align: center;
      padding: 4px 0 0;
    }
    .pager {
      display: none;
      gap: 10px;
      align-items: center;
      justify-content: center;
      border: 1px solid #dbe5ef;
      background: #ffffff;
      border-radius: 12px;
      padding: 10px 12px;
    }
    .pager.on { display: flex; }
    .pagerText {
      color: #475569;
      font-size: 13px;
    }
    @media (max-width: 920px) {
      .modalBody { grid-template-columns: 1fr; }
      .select { min-width: 0; width: 100%; }
      #cards { grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); }
    }
    @media (max-width: 640px) {
      #cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
  </style>
</head>
<body>
  <div class="shell">
    <section class="hero">
      <div class="heroTop">
        <div>
          <h1>__TITLE__</h1>
          <p class="subtitle">Browse shared collections by keyword, source, media type, and collection. Switch between Grid and Graph. Semantic search is disabled in this shared view.</p>
        </div>
        <div class="pill">Browse-only share portal</div>
      </div>
      <div class="controls">
        <div class="controlRow">
          <input id="search" type="text" placeholder="Search titles, notes, labels, or source" />
          <select id="collectionFilter" class="select"></select>
          <div class="viewToggle">
            <button id="viewGrid" type="button" class="viewBtn on">Grid</button>
            <button id="viewGraph" type="button" class="viewBtn">Graph</button>
          </div>
          <button id="clearBtn" type="button">Reset</button>
        </div>
        <div class="controlRow">
          <div class="controlGroup">
            <div class="controlGroupLabel">Source</div>
            <div id="sourceFilters" class="checkboxRow"></div>
          </div>
          <div class="controlGroup">
            <div class="controlGroupLabel">Media type</div>
            <div id="mediaFilters" class="checkboxRow"></div>
          </div>
          <label class="checkWrap"><input id="notesOnly" type="checkbox" /> Only items with notes</label>
        </div>
        <div id="semNotice" class="notice"></div>
        <div class="metaRow">
          <strong id="resultCount">0 items</strong>
          <span id="resultMeta"></span>
        </div>
        <div id="graphControls" class="graphControls" aria-label="Graph controls">
          <label class="graphControl">
            Similarity
            <input id="graphSimilarity" type="range" min="0.20" max="0.90" step="0.02" value="0.36" />
            <span id="graphSimilarityValue" class="graphValue">0.36</span>
          </label>
          <label class="graphControl">
            Max nodes
            <input id="graphMaxNodes" type="range" min="40" max="260" step="10" value="140" />
            <span id="graphMaxNodesValue" class="graphValue">140</span>
          </label>
          <label class="graphControl">
            Node size
            <input id="graphNodeSize" type="range" min="12" max="36" step="1" value="24" />
            <span id="graphNodeSizeValue" class="graphValue">24 px</span>
          </label>
          <label class="graphControl">
            Graph height
            <input id="graphHeight" type="range" min="360" max="960" step="20" value="560" />
            <span id="graphHeightValue" class="graphValue">560 px</span>
          </label>
        </div>
      </div>
    </section>
    <section id="cards"></section>
    <section id="graphWrap" class="graphWrap"></section>
    <section id="pager" class="pager">
      <span id="pagerText" class="pagerText"></span>
      <button id="showMoreBtn" type="button" class="btn">Show More</button>
    </section>
    <section id="empty">No items match those filters. Try clearing one or more filters.</section>
    <p class="footer">This shared portal is static and browse-only. Use Inspirations to curate or edit collections.</p>
  </div>

  <div id="modal" class="modal" role="dialog" aria-modal="true" aria-labelledby="modalTitle">
    <div class="modalCard">
      <div class="modalHeader">
        <div>
          <h2 id="modalTitle">Details</h2>
          <p id="modalMeta"></p>
        </div>
        <button id="closeModal" class="btn" type="button">Close</button>
      </div>
      <div class="modalBody">
        <div class="modalMedia">
          <img id="modalImage" alt="" />
          <div id="modalPlaceholder" class="modalPlaceholder">No preview available.</div>
          <div id="modalMarkers" class="markerLayer"></div>
        </div>
        <div class="modalInfo">
          <div class="actions">
            <a id="modalSource" class="btn link" target="_blank" rel="noopener noreferrer">Open Source</a>
            <a id="modalScanPdf" class="btn link" target="_blank" rel="noopener noreferrer">Open Scan PDF</a>
            <a id="modalDownload" class="btn" download>Download Image</a>
            <button id="modalPrint" class="btn" type="button">Print Card</button>
          </div>
          <div>
            <h3>Notes</h3>
            <p id="modalNotes">No notes.</p>
          </div>
          <div>
            <h3>Annotations</h3>
            <ul id="modalAnnotations" class="annList"></ul>
          </div>
          <div>
            <h3>Collections</h3>
            <p id="modalCollections"></p>
          </div>
          <div>
            <h3>Labels</h3>
            <p id="modalLabels"></p>
          </div>
        </div>
      </div>
    </div>
  </div>

  <script id="portal-data" type="application/json">__PORTAL_DATA__</script>
  <script>
    const portal = JSON.parse(document.getElementById("portal-data").textContent || "{}");
    const byId = new Map((portal.items || []).map((item) => [String(item.id), item]));
    const PAGE_SIZE = 240;
    const initialGraphHeight = Math.max(420, Math.min(1200, Math.round((window.innerHeight || 900) * 0.72)));
    const state = {
      query: "",
      collectionId: "",
      sources: new Set((portal.sources || []).map((src) => String(src.key || ""))),
      mediaStatuses: new Set((portal.media_statuses || []).map((entry) => String(entry.key || ""))),
      notesOnly: false,
      viewMode: "grid",
      semNotice: "",
      visibleCount: PAGE_SIZE,
      graphSimilarity: 0.36,
      graphMaxNodes: 140,
      graphNodeSize: 24,
      graphHeight: initialGraphHeight,
    };

    const cardsEl = document.getElementById("cards");
    const emptyEl = document.getElementById("empty");
    const resultCountEl = document.getElementById("resultCount");
    const resultMetaEl = document.getElementById("resultMeta");
    const searchEl = document.getElementById("search");
    const collectionEl = document.getElementById("collectionFilter");
    const sourceEl = document.getElementById("sourceFilters");
    const mediaEl = document.getElementById("mediaFilters");
    const notesOnlyEl = document.getElementById("notesOnly");
    const clearEl = document.getElementById("clearBtn");
    const viewGridEl = document.getElementById("viewGrid");
    const viewGraphEl = document.getElementById("viewGraph");
    const semNoticeEl = document.getElementById("semNotice");
    const graphWrapEl = document.getElementById("graphWrap");
    const graphControlsEl = document.getElementById("graphControls");
    const graphSimilarityEl = document.getElementById("graphSimilarity");
    const graphSimilarityValueEl = document.getElementById("graphSimilarityValue");
    const graphMaxNodesEl = document.getElementById("graphMaxNodes");
    const graphMaxNodesValueEl = document.getElementById("graphMaxNodesValue");
    const graphNodeSizeEl = document.getElementById("graphNodeSize");
    const graphNodeSizeValueEl = document.getElementById("graphNodeSizeValue");
    const graphHeightEl = document.getElementById("graphHeight");
    const graphHeightValueEl = document.getElementById("graphHeightValue");
    const pagerEl = document.getElementById("pager");
    const pagerTextEl = document.getElementById("pagerText");
    const showMoreEl = document.getElementById("showMoreBtn");

    const modalEl = document.getElementById("modal");
    const modalTitleEl = document.getElementById("modalTitle");
    const modalMetaEl = document.getElementById("modalMeta");
    const modalImageEl = document.getElementById("modalImage");
    const modalPlaceholderEl = document.getElementById("modalPlaceholder");
    const modalSourceEl = document.getElementById("modalSource");
    const modalScanPdfEl = document.getElementById("modalScanPdf");
    const modalDownloadEl = document.getElementById("modalDownload");
    const modalPrintEl = document.getElementById("modalPrint");
    const modalNotesEl = document.getElementById("modalNotes");
    const modalAnnotationsEl = document.getElementById("modalAnnotations");
    const modalCollectionsEl = document.getElementById("modalCollections");
    const modalLabelsEl = document.getElementById("modalLabels");
    const modalMarkersEl = document.getElementById("modalMarkers");
    const closeModalEl = document.getElementById("closeModal");

    function esc(value) {
      return String(value || "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;");
    }

    function clamp01(value) {
      const n = Number(value);
      if (!Number.isFinite(n)) return 0;
      return Math.max(0, Math.min(1, n));
    }

    function normalizedSearch(raw) {
      const text = String(raw || "").trim();
      if (!text) {
        state.semNotice = "";
        return "";
      }
      const lower = text.toLowerCase();
      if (lower.startsWith("sem:") || lower.startsWith("similar:")) {
        state.semNotice = portal.semantic_notice || "Semantic search is not available in shared view. Keyword search is used instead.";
        const idx = text.indexOf(":");
        return text.slice(idx + 1).trim().toLowerCase();
      }
      state.semNotice = "";
      return text.toLowerCase();
    }

    function resetVisibleCount() {
      state.visibleCount = PAGE_SIZE;
    }

    function clampNumber(value, min, max, fallback) {
      const n = Number(value);
      if (!Number.isFinite(n)) return fallback;
      return Math.min(max, Math.max(min, n));
    }

    function syncGraphControlLabels() {
      const similarity = Number(state.graphSimilarity).toFixed(2);
      const maxNodes = String(Math.round(Number(state.graphMaxNodes) || 0));
      const nodeSize = Math.round(Number(state.graphNodeSize) || 0);
      const graphHeight = Math.round(Number(state.graphHeight) || 0);
      graphSimilarityEl.value = similarity;
      graphMaxNodesEl.value = maxNodes;
      graphNodeSizeEl.value = String(nodeSize);
      graphHeightEl.value = String(graphHeight);
      graphSimilarityValueEl.textContent = similarity;
      graphMaxNodesValueEl.textContent = maxNodes;
      graphNodeSizeValueEl.textContent = `${nodeSize} px`;
      graphHeightValueEl.textContent = `${graphHeight} px`;
      graphWrapEl.style.setProperty("--graph-height", `${Math.round(Number(state.graphHeight) || 560)}px`);
    }

    function toggleFacetSelection(key, setRef, keys) {
      const has = setRef.has(key);
      const allSelected = setRef.size === keys.length;
      if (allSelected) {
        setRef.clear();
        setRef.add(key);
        return;
      }
      if (has && setRef.size === 1) {
        setRef.clear();
        for (const value of keys) setRef.add(value);
        return;
      }
      if (has) {
        setRef.delete(key);
        if (!setRef.size) {
          for (const value of keys) setRef.add(value);
        }
        return;
      }
      setRef.add(key);
    }

    function renderCollectionOptions() {
      const options = [{ id: "", name: "All collections", count: (portal.items || []).length }, ...(portal.collections || [])];
      collectionEl.innerHTML = options
        .map((c) => `<option value="${esc(c.id)}">${esc(c.name)} (${Number(c.count || 0)})</option>`)
        .join("");
    }

    function renderSourceFilters() {
      sourceEl.innerHTML = "";
      const sources = portal.sources || [];
      const keys = sources.map((src) => String(src.key || "")).filter(Boolean);
      for (const src of sources) {
        const key = String(src.key || "");
        if (!key) continue;
        const button = document.createElement("button");
        button.type = "button";
        button.className = state.sources.has(key) ? "sourceChip on" : "sourceChip";
        button.textContent = `${src.name || key} (${Number(src.count || 0)})`;
        button.addEventListener("click", () => {
          toggleFacetSelection(key, state.sources, keys);
          renderSourceFilters();
          resetVisibleCount();
          render();
        });
        sourceEl.appendChild(button);
      }
    }

    function renderMediaFilters() {
      mediaEl.innerHTML = "";
      const media = portal.media_statuses || [];
      const keys = media.map((entry) => String(entry.key || "")).filter(Boolean);
      for (const entry of media) {
        const key = String(entry.key || "");
        if (!key) continue;
        const button = document.createElement("button");
        button.type = "button";
        button.className = state.mediaStatuses.has(key) ? "sourceChip on" : "sourceChip";
        button.textContent = `${entry.name || key} (${Number(entry.count || 0)})`;
        button.addEventListener("click", () => {
          toggleFacetSelection(key, state.mediaStatuses, keys);
          renderMediaFilters();
          resetVisibleCount();
          render();
        });
        mediaEl.appendChild(button);
      }
    }

    function itemMatches(item, query) {
      if (state.collectionId) {
        if (state.collectionId === "__unassigned__") {
          if (Array.isArray(item.collections) && item.collections.length > 0) return false;
        } else {
          const ids = (item.collections || []).map((c) => String(c.id || ""));
          if (!ids.includes(state.collectionId)) return false;
        }
      }
      if (!state.sources.has(String(item.source_key || ""))) return false;
      if (!state.mediaStatuses.has(String(item.media_status || ""))) return false;
      if (state.notesOnly && !String(item.notes || "").trim()) return false;
      if (!query) return true;
      const haystack = [
        item.title,
        item.notes,
        item.description,
        item.source_label,
        item.source_ref,
        item.board,
        ...(item.labels || []),
        ...((item.collections || []).map((c) => c.name || "")),
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(query);
    }

    function renderCards(items) {
      cardsEl.innerHTML = items
        .map((item) => {
          const firstCollection = (item.collections && item.collections[0] && item.collections[0].name) || "";
          const labels = (item.labels || []).slice(0, 4);
          const isHttpSource = /^https?:\\/\\//i.test(String(item.source_ref || ""));
          const metaBits = [];
          if (item.imported_at) metaBits.push(`Imported ${item.imported_at}`);
          if (item.board) metaBits.push(`Board: ${item.board}`);
          if (Number(item.scan_doc_pages || 0) > 1 && Number(item.scan_doc_page || 0) > 0) {
            metaBits.push(`Scan page ${item.scan_doc_page} of ${item.scan_doc_pages}`);
          }
          const meta = metaBits.join(" • ");
          const media = item.preview_src
            ? `<img src="${esc(item.preview_src)}" alt="" loading="lazy" data-open-detail="${esc(item.id)}" />`
            : `<button type="button" class="placeholder" data-open-detail="${esc(item.id)}">No preview available</button>`;
          const annCount = Array.isArray(item.annotations) ? item.annotations.length : 0;
          const scanBadge = Number(item.scan_doc_pages || 0) > 1
            ? `<span class="badge scan">Multi-page (${Number(item.scan_doc_pages)})</span>`
            : "";
          const sourceAction = isHttpSource
            ? `<a class="btn link" href="${esc(item.source_ref)}" target="_blank" rel="noopener noreferrer">Open Source</a>`
            : (item.scan_pdf_src
                ? `<a class="btn link" href="${esc(item.scan_pdf_src)}" target="_blank" rel="noopener noreferrer">Open Scan PDF</a>`
                : `<span class="cardMeta">No source link</span>`);
          return `
            <article class="card">
              <div class="media">
                ${media}
                <div class="badgeRow">
                  <span class="badge">${esc(item.source_label || item.source_key)}</span>
                  ${firstCollection ? `<span class="badge collection">${esc(firstCollection)}</span>` : ""}
                  ${annCount ? `<span class="badge">${annCount} note${annCount === 1 ? "" : "s"}</span>` : ""}
                  ${scanBadge}
                </div>
              </div>
              <div class="body">
                <h3 class="title">${esc(item.title || "(untitled)")}</h3>
                <div class="cardMeta">${meta ? esc(meta) : "No extra metadata"}</div>
                <div class="labelRow">
                  ${labels.map((label) => `<span class="label">${esc(label)}</span>`).join("")}
                </div>
                <div class="actions">
                  <button type="button" class="btn primary" data-open-detail="${esc(item.id)}">Show Details</button>
                  ${sourceAction}
                </div>
              </div>
            </article>
          `;
        })
        .join("");
      cardsEl.querySelectorAll("[data-open-detail]").forEach((el) => {
        el.addEventListener("click", (event) => {
          event.preventDefault();
          const id = el.getAttribute("data-open-detail") || "";
          openDetails(id);
        });
      });
    }

    function hashFloat(input, salt = 0) {
      const text = String(input || "");
      let h = 2166136261 ^ (salt >>> 0);
      for (let i = 0; i < text.length; i += 1) {
        h ^= text.charCodeAt(i);
        h = Math.imul(h, 16777619);
      }
      const u = h >>> 0;
      return (u % 100000) / 100000;
    }

    function sourceColor(key) {
      const map = {
        pinterest: "#0f766e",
        facebook: "#1d4ed8",
        scan: "#7c3aed",
        photo: "#b45309",
      };
      return map[String(key || "").toLowerCase()] || "#334155";
    }

    function renderGraph(items) {
      const MAX_NODES = Math.round(clampNumber(state.graphMaxNodes, 40, 260, 140));
      const scoreThreshold = clampNumber(state.graphSimilarity, 0.2, 0.9, 0.36);
      const nodeRadius = clampNumber(state.graphNodeSize, 12, 36, 24);
      const height = Math.round(clampNumber(state.graphHeight, 360, 960, 560));
      graphWrapEl.style.setProperty("--graph-height", `${height}px`);
      const viewItems = items.slice(0, MAX_NODES);
      if (!viewItems.length) {
        graphWrapEl.innerHTML = `<div class="graphEmpty">No items available for graph view with current filters.</div>`;
        return;
      }
      const width = Math.max(320, graphWrapEl.clientWidth || 1000);
      const pad = nodeRadius + 12;
      const nodes = viewItems.map((item, idx) => {
        const labels = new Set((item.labels || []).slice(0, 40).map((x) => String(x || "").toLowerCase()).filter(Boolean));
        const collections = new Set((item.collections || []).map((c) => String(c.id || "")));
        const titleTokens = new Set(
          String(item.title || "")
            .toLowerCase()
            .split(/[^a-z0-9]+/)
            .filter((token) => token.length >= 3)
            .slice(0, 24)
        );
        const scanPdf = String(item.scan_pdf_src || "");
        const scanDoc = Number(item.scan_doc_index || 0);
        const scanPage = Number(item.scan_doc_page || 0);
        const x = pad + hashFloat(item.id, 17 + idx) * Math.max(1, (width - (pad * 2)));
        const y = pad + hashFloat(item.id, 29 + idx) * Math.max(1, (height - (pad * 2)));
        return {
          item,
          labels,
          collections,
          titleTokens,
          scanPdf,
          scanDoc,
          scanPage,
          x,
          y,
          r: nodeRadius,
        };
      });
      const candidateEdges = [];
      for (let i = 0; i < nodes.length; i += 1) {
        for (let j = i + 1; j < nodes.length; j += 1) {
          const a = nodes[i];
          const b = nodes[j];
          let score = 0;
          if (a.item.source_key === b.item.source_key) score += 0.12;
          let sharedCollection = 0;
          for (const cid of a.collections) {
            if (b.collections.has(cid)) {
              sharedCollection += 1;
            }
          }
          if (sharedCollection > 0) score += 0.55;
          if (a.scanPdf && b.scanPdf && a.scanPdf === b.scanPdf) score += 0.18;
          if (a.scanDoc > 0 && b.scanDoc > 0 && a.scanDoc === b.scanDoc) score += 0.36;
          if (a.scanPage > 0 && b.scanPage > 0 && Math.abs(a.scanPage - b.scanPage) === 1 && a.scanDoc === b.scanDoc) score += 0.18;
          let sharedLabels = 0;
          for (const label of a.labels) {
            if (b.labels.has(label)) {
              sharedLabels += 1;
              if (sharedLabels >= 4) break;
            }
          }
          score += Math.min(0.36, sharedLabels * 0.12);
          let sharedTokens = 0;
          for (const token of a.titleTokens) {
            if (b.titleTokens.has(token)) {
              sharedTokens += 1;
              if (sharedTokens >= 4) break;
            }
          }
          score += Math.min(0.22, sharedTokens * 0.06);
          if (score >= scoreThreshold) {
            candidateEdges.push({ i, j, score });
          }
        }
      }
      if (!candidateEdges.length) {
        const fallback = [];
        for (let i = 0; i < nodes.length; i += 1) {
          const a = nodes[i];
          const picks = [];
          for (let j = 0; j < nodes.length; j += 1) {
            if (i === j) continue;
            const b = nodes[j];
            let score = 0;
            if (a.item.source_key === b.item.source_key) score += 0.18;
            if (a.scanDoc > 0 && b.scanDoc > 0 && a.scanDoc === b.scanDoc) score += 0.26;
            if (a.scanPage > 0 && b.scanPage > 0) {
              const delta = Math.abs(a.scanPage - b.scanPage);
              if (delta === 1 && a.scanDoc === b.scanDoc) score += 0.24;
              else if (delta === 2 && a.scanDoc === b.scanDoc) score += 0.12;
            }
            if (score > 0) picks.push({ i: Math.min(i, j), j: Math.max(i, j), score });
          }
          picks.sort((x, y) => y.score - x.score);
          for (const edge of picks.slice(0, 2)) fallback.push(edge);
        }
        const uniq = new Map();
        for (const edge of fallback) {
          const key = `${edge.i}:${edge.j}`;
          if (!uniq.has(key) || (uniq.get(key).score < edge.score)) uniq.set(key, edge);
        }
        candidateEdges.push(...uniq.values());
      }
      candidateEdges.sort((a, b) => b.score - a.score);
      const degree = new Array(nodes.length).fill(0);
      const edges = [];
      const maxDegree = 8;
      for (const edge of candidateEdges) {
        if (degree[edge.i] >= maxDegree || degree[edge.j] >= maxDegree) continue;
        edges.push(edge);
        degree[edge.i] += 1;
        degree[edge.j] += 1;
      }

      const iterations = 85;
      const repulsion = 4200 + (nodeRadius * 90);
      const spring = 0.021;
      const restLength = Math.max(72, nodeRadius * 4.6);
      const centerPull = 0.0075;
      const minX = pad;
      const maxX = width - pad;
      const minY = pad;
      const maxY = height - pad;
      for (let step = 0; step < iterations; step += 1) {
        const fx = new Array(nodes.length).fill(0);
        const fy = new Array(nodes.length).fill(0);
        for (let i = 0; i < nodes.length; i += 1) {
          for (let j = i + 1; j < nodes.length; j += 1) {
            const dx = nodes[i].x - nodes[j].x;
            const dy = nodes[i].y - nodes[j].y;
            const d2 = Math.max(36, (dx * dx) + (dy * dy));
            const force = repulsion / d2;
            const d = Math.sqrt(d2);
            const nx = dx / d;
            const ny = dy / d;
            fx[i] += nx * force;
            fy[i] += ny * force;
            fx[j] -= nx * force;
            fy[j] -= ny * force;
          }
        }
        for (const edge of edges) {
          const a = nodes[edge.i];
          const b = nodes[edge.j];
          const dx = b.x - a.x;
          const dy = b.y - a.y;
          const d = Math.max(1, Math.sqrt((dx * dx) + (dy * dy)));
          const stretch = d - restLength;
          const pull = stretch * spring * (0.7 + edge.score);
          const nx = dx / d;
          const ny = dy / d;
          fx[edge.i] += nx * pull;
          fy[edge.i] += ny * pull;
          fx[edge.j] -= nx * pull;
          fy[edge.j] -= ny * pull;
        }
        const cx = width / 2;
        const cy = height / 2;
        for (let i = 0; i < nodes.length; i += 1) {
          const node = nodes[i];
          fx[i] += (cx - node.x) * centerPull;
          fy[i] += (cy - node.y) * centerPull;
          node.x = Math.max(minX, Math.min(maxX, node.x + fx[i]));
          node.y = Math.max(minY, Math.min(maxY, node.y + fy[i]));
        }
      }

      const defs = nodes
        .map((node, idx) => `<clipPath id="clip-${idx}"><circle class="graphClip" data-node-index="${idx}" cx="${node.x.toFixed(2)}" cy="${node.y.toFixed(2)}" r="${node.r}" /></clipPath>`)
        .join("");
      const edgeHtml = edges
        .map((edge, idx) => {
          const a = nodes[edge.i];
          const b = nodes[edge.j];
          const opacity = Math.min(0.75, 0.18 + (edge.score * 0.56));
          return `<line class="graphEdge" data-edge-index="${idx}" data-a="${edge.i}" data-b="${edge.j}" x1="${a.x.toFixed(2)}" y1="${a.y.toFixed(2)}" x2="${b.x.toFixed(2)}" y2="${b.y.toFixed(2)}" stroke="#5b7590" stroke-width="${(0.8 + edge.score * 1.3).toFixed(2)}" opacity="${opacity.toFixed(2)}" />`;
        })
        .join("");
      const nodeHtml = nodes
        .map((node, idx) => {
          const border = sourceColor(node.item.source_key);
          const r = node.r;
          const x = node.x - r;
          const y = node.y - r;
          const title = String(node.item.title || "(untitled)");
          const short = title.length > 26 ? `${title.slice(0, 25)}…` : title;
          const preview = node.item.preview_src
            ? `<image class="graphImage" href="${esc(node.item.preview_src)}" x="${x.toFixed(2)}" y="${y.toFixed(2)}" width="${(r * 2).toFixed(2)}" height="${(r * 2).toFixed(2)}" clip-path="url(#clip-${idx})" preserveAspectRatio="xMidYMid slice" />`
            : `<circle cx="${node.x.toFixed(2)}" cy="${node.y.toFixed(2)}" r="${r}" fill="#dbe5ef" />`;
          return `
            <g class="graphNode" data-open-detail="${esc(node.item.id)}" data-node-index="${idx}" style="cursor:grab">
              ${preview}
              <circle class="graphRing" cx="${node.x.toFixed(2)}" cy="${node.y.toFixed(2)}" r="${r}" fill="none" stroke="${border}" stroke-width="2.6" />
              <text class="graphLabel" x="${node.x.toFixed(2)}" y="${(node.y + r + 14).toFixed(2)}" text-anchor="middle" fill="#334155" font-size="10">${esc(short)}</text>
            </g>
          `;
        })
        .join("");
      const hint = items.length > MAX_NODES
        ? `Graph view shows first ${MAX_NODES} of ${items.length} filtered items. Similarity ${scoreThreshold.toFixed(2)}. Drag nodes to inspect connections.`
        : `${items.length} items in graph view. Similarity ${scoreThreshold.toFixed(2)}. Drag nodes to inspect connections.`;
      graphWrapEl.innerHTML = `
        <div class="graphHint">${esc(hint)}</div>
        <svg class="graphSvg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="xMidYMid meet">
          <defs>${defs}</defs>
          ${edgeHtml}
          ${nodeHtml}
        </svg>
      `;
      const svg = graphWrapEl.querySelector(".graphSvg");
      if (!svg) return;
      const nodeGroups = Array.from(svg.querySelectorAll(".graphNode"));
      const edgeElements = Array.from(svg.querySelectorAll(".graphEdge"));
      const clipElements = Array.from(svg.querySelectorAll(".graphClip"));
      const nodeParts = new Array(nodes.length).fill(null).map(() => ({
        group: null,
        image: null,
        ring: null,
        label: null,
        clip: null,
      }));
      for (const clipEl of clipElements) {
        const idx = Number(clipEl.getAttribute("data-node-index") || "-1");
        if (!Number.isFinite(idx) || idx < 0 || idx >= nodeParts.length) continue;
        nodeParts[idx].clip = clipEl;
      }
      for (const group of nodeGroups) {
        const idx = Number(group.getAttribute("data-node-index") || "-1");
        if (!Number.isFinite(idx) || idx < 0 || idx >= nodeParts.length) continue;
        nodeParts[idx].group = group;
        nodeParts[idx].image = group.querySelector(".graphImage");
        nodeParts[idx].ring = group.querySelector(".graphRing");
        nodeParts[idx].label = group.querySelector(".graphLabel");
      }
      const edgesByNode = new Array(nodes.length).fill(null).map(() => []);
      for (const edgeEl of edgeElements) {
        const a = Number(edgeEl.getAttribute("data-a") || "-1");
        const b = Number(edgeEl.getAttribute("data-b") || "-1");
        if (!Number.isFinite(a) || !Number.isFinite(b) || a < 0 || b < 0) continue;
        if (a < edgesByNode.length) edgesByNode[a].push({ edgeEl, from: "a", other: b });
        if (b < edgesByNode.length) edgesByNode[b].push({ edgeEl, from: "b", other: a });
      }

      const applyNodePosition = (idx) => {
        if (idx < 0 || idx >= nodes.length) return;
        const node = nodes[idx];
        const part = nodeParts[idx];
        if (!part) return;
        const x = node.x - node.r;
        const y = node.y - node.r;
        if (part.image) {
          part.image.setAttribute("x", x.toFixed(2));
          part.image.setAttribute("y", y.toFixed(2));
          part.image.setAttribute("width", (node.r * 2).toFixed(2));
          part.image.setAttribute("height", (node.r * 2).toFixed(2));
        }
        if (part.ring) {
          part.ring.setAttribute("cx", node.x.toFixed(2));
          part.ring.setAttribute("cy", node.y.toFixed(2));
          part.ring.setAttribute("r", node.r.toFixed(2));
        }
        if (part.label) {
          part.label.setAttribute("x", node.x.toFixed(2));
          part.label.setAttribute("y", (node.y + node.r + 14).toFixed(2));
        }
        if (part.clip) {
          part.clip.setAttribute("cx", node.x.toFixed(2));
          part.clip.setAttribute("cy", node.y.toFixed(2));
          part.clip.setAttribute("r", node.r.toFixed(2));
        }
      };
      const applyEdgesForNode = (idx) => {
        if (idx < 0 || idx >= edgesByNode.length) return;
        const node = nodes[idx];
        const links = edgesByNode[idx] || [];
        for (const link of links) {
          if (link.from === "a") {
            link.edgeEl.setAttribute("x1", node.x.toFixed(2));
            link.edgeEl.setAttribute("y1", node.y.toFixed(2));
          } else {
            link.edgeEl.setAttribute("x2", node.x.toFixed(2));
            link.edgeEl.setAttribute("y2", node.y.toFixed(2));
          }
        }
      };
      const pointerToView = (event) => {
        const rect = svg.getBoundingClientRect();
        const vb = svg.viewBox.baseVal;
        const x = ((event.clientX - rect.left) / Math.max(1, rect.width)) * vb.width;
        const y = ((event.clientY - rect.top) / Math.max(1, rect.height)) * vb.height;
        return { x, y };
      };
      let dragState = null;
      let suppressOpenUntil = 0;
      const onPointerMove = (event) => {
        if (!dragState || event.pointerId !== dragState.pointerId) return;
        const pos = pointerToView(event);
        const dx = pos.x - dragState.startX;
        const dy = pos.y - dragState.startY;
        const nextX = Math.max(minX, Math.min(maxX, dragState.nodeX + dx));
        const nextY = Math.max(minY, Math.min(maxY, dragState.nodeY + dy));
        const idx = dragState.idx;
        if (Math.abs(dx) + Math.abs(dy) > 1.2) dragState.moved = true;
        nodes[idx].x = nextX;
        nodes[idx].y = nextY;
        applyNodePosition(idx);
        applyEdgesForNode(idx);
      };
      const onPointerEnd = (event) => {
        if (!dragState || event.pointerId !== dragState.pointerId) return;
        const idx = dragState.idx;
        const part = nodeParts[idx];
        if (part && part.group && part.group.releasePointerCapture) {
          try { part.group.releasePointerCapture(event.pointerId); } catch (_) {}
        }
        if (dragState.moved) suppressOpenUntil = Date.now() + 240;
        dragState = null;
      };
      for (let idx = 0; idx < nodeParts.length; idx += 1) {
        const part = nodeParts[idx];
        if (!part || !part.group) continue;
        part.group.addEventListener("pointerdown", (event) => {
          if (event.button !== undefined && event.button !== 0) return;
          const pos = pointerToView(event);
          dragState = {
            idx,
            pointerId: event.pointerId,
            startX: pos.x,
            startY: pos.y,
            nodeX: nodes[idx].x,
            nodeY: nodes[idx].y,
            moved: false,
          };
          if (part.group.setPointerCapture) {
            try { part.group.setPointerCapture(event.pointerId); } catch (_) {}
          }
          event.preventDefault();
        });
        part.group.addEventListener("pointermove", onPointerMove);
        part.group.addEventListener("pointerup", onPointerEnd);
        part.group.addEventListener("pointercancel", onPointerEnd);
        part.group.addEventListener("click", (event) => {
          if (Date.now() < suppressOpenUntil) {
            event.preventDefault();
            event.stopPropagation();
            return;
          }
          const id = part.group.getAttribute("data-open-detail") || "";
          openDetails(id);
        });
      }
    }

    function printItem(item) {
      const title = String(item.title || "(untitled)");
      const notes = String(item.notes || "").trim() || "No notes.";
      const sourceText = item.source_ref ? `<p><a href="${esc(item.source_ref)}">${esc(item.source_ref)}</a></p>` : "<p>No source link.</p>";
      const detailSrc = String(item.detail_src || item.preview_src || "");
      const imgHtml = detailSrc
        ? `<img src="${esc(detailSrc)}" alt="" style="max-width:100%;max-height:520px;object-fit:contain;border:1px solid #dbe5ef;border-radius:8px;" />`
        : "<p>No preview image.</p>";
      const printWin = window.open("", "_blank", "noopener,noreferrer,width=980,height=760");
      if (!printWin) return;
      printWin.document.write(`<!doctype html><html><head><title>${esc(title)}</title><meta charset="utf-8"><style>body{font-family:Segoe UI,sans-serif;margin:20px;color:#111827}h1{margin:0 0 8px;font-size:24px}p{font-size:14px;line-height:1.5}a{color:#1d4ed8}</style></head><body><h1>${esc(title)}</h1>${imgHtml}<h3>Notes</h3><p>${esc(notes)}</p><h3>Source</h3>${sourceText}</body></html>`);
      printWin.document.close();
      printWin.focus();
      printWin.print();
    }

    function renderMarkers(annotations) {
      modalMarkersEl.innerHTML = "";
      for (let i = 0; i < annotations.length; i += 1) {
        const ann = annotations[i] || {};
        const marker = document.createElement("div");
        marker.className = "marker";
        marker.style.left = `${clamp01(ann.x) * 100}%`;
        marker.style.top = `${clamp01(ann.y) * 100}%`;
        marker.textContent = String(i + 1);
        marker.title = String(ann.text || `Annotation ${i + 1}`);
        modalMarkersEl.appendChild(marker);
      }
    }

    function openDetails(assetId) {
      const item = byId.get(String(assetId || ""));
      if (!item) return;
      modalTitleEl.textContent = String(item.title || "(untitled)");
      const collectionText = (item.collections || []).map((c) => c.name || "").filter(Boolean).join(", ") || "Unassigned";
      const metaBits = [
        item.source_label || item.source_key || "",
        item.imported_at ? `Imported ${item.imported_at}` : "",
        item.board ? `Board: ${item.board}` : "",
      ].filter(Boolean);
      if (Number(item.scan_doc_pages || 0) > 1 && Number(item.scan_doc_page || 0) > 0) {
        metaBits.push(`Scan page ${item.scan_doc_page} of ${item.scan_doc_pages}`);
      }
      modalMetaEl.textContent = metaBits.join(" • ");
      const detailSrc = String(item.detail_src || item.preview_src || "");
      if (detailSrc) {
        modalImageEl.src = detailSrc;
        modalImageEl.style.display = "block";
        modalPlaceholderEl.style.display = "none";
        modalDownloadEl.href = detailSrc;
        const safeName = String(item.title || "inspiration").replace(/[^a-z0-9]+/gi, "-").replace(/^-+|-+$/g, "").toLowerCase() || "inspiration";
        modalDownloadEl.download = `${safeName}.jpg`;
        modalDownloadEl.style.display = "inline-flex";
      } else {
        modalImageEl.removeAttribute("src");
        modalImageEl.style.display = "none";
        modalPlaceholderEl.style.display = "block";
        modalDownloadEl.removeAttribute("href");
        modalDownloadEl.style.display = "none";
      }
      if (/^https?:\\/\\//i.test(String(item.source_ref || ""))) {
        modalSourceEl.href = item.source_ref;
        modalSourceEl.style.display = "inline-flex";
      } else {
        modalSourceEl.removeAttribute("href");
        modalSourceEl.style.display = "none";
      }
      if (item.scan_pdf_src) {
        modalScanPdfEl.href = item.scan_pdf_src;
        modalScanPdfEl.style.display = "inline-flex";
      } else {
        modalScanPdfEl.removeAttribute("href");
        modalScanPdfEl.style.display = "none";
      }
      modalNotesEl.textContent = String(item.notes || "").trim() || "No notes.";
      modalCollectionsEl.textContent = collectionText;
      modalLabelsEl.textContent = (item.labels || []).join(", ") || "No labels.";
      modalAnnotationsEl.innerHTML = "";
      const annotations = Array.isArray(item.annotations) ? item.annotations : [];
      if (!annotations.length) {
        const li = document.createElement("li");
        li.textContent = "No annotation notes recorded.";
        modalAnnotationsEl.appendChild(li);
      } else {
        for (let i = 0; i < annotations.length; i += 1) {
          const ann = annotations[i] || {};
          const li = document.createElement("li");
          li.textContent = `${i + 1}. ${String(ann.text || "").trim() || "No text"}`;
          modalAnnotationsEl.appendChild(li);
        }
      }
      renderMarkers(annotations);
      modalPrintEl.onclick = () => printItem(item);
      modalEl.classList.add("on");
    }

    function closeModal() {
      modalEl.classList.remove("on");
    }

    function render() {
      const query = normalizedSearch(state.query);
      semNoticeEl.textContent = state.semNotice;
      semNoticeEl.classList.toggle("on", Boolean(state.semNotice));
      const items = (portal.items || []).filter((item) => itemMatches(item, query));
      const graphMode = state.viewMode === "graph";
      const visibleItems = graphMode ? items : items.slice(0, state.visibleCount);
      viewGridEl.classList.toggle("on", !graphMode);
      viewGraphEl.classList.toggle("on", graphMode);
      graphControlsEl.classList.toggle("on", graphMode);
      cardsEl.style.display = graphMode ? "none" : "grid";
      graphWrapEl.classList.toggle("on", graphMode);
      if (graphMode) syncGraphControlLabels();
      if (graphMode) {
        renderGraph(items);
      } else {
        graphWrapEl.innerHTML = "";
        renderCards(visibleItems);
      }
      resultCountEl.textContent = `${items.length} item${items.length === 1 ? "" : "s"}`;
      const activeCollection = state.collectionId
        ? ((portal.collections || []).find((c) => String(c.id) === state.collectionId) || null)
        : null;
      const sourceCount = state.sources.size;
      const totalSources = (portal.sources || []).length;
      const mediaCount = state.mediaStatuses.size;
      const totalMedia = (portal.media_statuses || []).length;
      const bits = [];
      bits.push(activeCollection ? `Collection: ${activeCollection.name}` : "Collection: All");
      bits.push(sourceCount === totalSources ? "Source: All" : `Sources: ${sourceCount}/${totalSources}`);
      bits.push(mediaCount === totalMedia ? "Media: All" : `Media: ${mediaCount}/${totalMedia}`);
      if (state.notesOnly) bits.push("Notes only");
      resultMetaEl.textContent = bits.join(" • ");
      emptyEl.classList.toggle("on", items.length === 0);
      pagerEl.classList.toggle("on", !graphMode && items.length > visibleItems.length);
      pagerTextEl.textContent = `Showing ${visibleItems.length} of ${items.length}`;
    }

    searchEl.addEventListener("input", (event) => {
      state.query = String(event.target.value || "");
      resetVisibleCount();
      render();
    });
    collectionEl.addEventListener("change", (event) => {
      state.collectionId = String(event.target.value || "");
      resetVisibleCount();
      render();
    });
    notesOnlyEl.addEventListener("change", (event) => {
      state.notesOnly = Boolean(event.target.checked);
      resetVisibleCount();
      render();
    });
    viewGridEl.addEventListener("click", () => {
      state.viewMode = "grid";
      render();
    });
    viewGraphEl.addEventListener("click", () => {
      state.viewMode = "graph";
      render();
    });
    graphSimilarityEl.addEventListener("input", (event) => {
      state.graphSimilarity = clampNumber(event.target.value, 0.2, 0.9, 0.36);
      syncGraphControlLabels();
      if (state.viewMode === "graph") render();
    });
    graphMaxNodesEl.addEventListener("input", (event) => {
      state.graphMaxNodes = Math.round(clampNumber(event.target.value, 40, 260, 140));
      syncGraphControlLabels();
      if (state.viewMode === "graph") render();
    });
    graphNodeSizeEl.addEventListener("input", (event) => {
      state.graphNodeSize = Math.round(clampNumber(event.target.value, 12, 36, 24));
      syncGraphControlLabels();
      if (state.viewMode === "graph") render();
    });
    graphHeightEl.addEventListener("input", (event) => {
      state.graphHeight = Math.round(clampNumber(event.target.value, 360, 960, 560));
      syncGraphControlLabels();
      if (state.viewMode === "graph") render();
    });
    clearEl.addEventListener("click", () => {
      state.query = "";
      state.collectionId = "";
      state.notesOnly = false;
      state.sources = new Set((portal.sources || []).map((src) => String(src.key || "")));
      state.mediaStatuses = new Set((portal.media_statuses || []).map((entry) => String(entry.key || "")));
      resetVisibleCount();
      searchEl.value = "";
      collectionEl.value = "";
      notesOnlyEl.checked = false;
      renderSourceFilters();
      renderMediaFilters();
      render();
    });
    showMoreEl.addEventListener("click", () => {
      state.visibleCount += PAGE_SIZE;
      render();
    });
    closeModalEl.addEventListener("click", closeModal);
    modalEl.addEventListener("click", (event) => {
      if (event.target === modalEl) closeModal();
    });
    window.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeModal();
    });
    const updateGraphHeightForViewport = () => {
      const nextHeight = Math.max(420, Math.min(1200, Math.round((window.innerHeight || 900) * 0.72)));
      if (Math.abs(nextHeight - state.graphHeight) >= 10) {
        state.graphHeight = nextHeight;
        syncGraphControlLabels();
      }
    };
    let resizeTimer = 0;
    const rerenderGraphOnResize = () => {
      updateGraphHeightForViewport();
      if (state.viewMode !== "graph") return;
      clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(() => {
        render();
      }, 120);
    };
    window.addEventListener("resize", rerenderGraphOnResize);
    window.addEventListener("orientationchange", rerenderGraphOnResize);

    renderCollectionOptions();
    renderSourceFilters();
    renderMediaFilters();
    updateGraphHeightForViewport();
    syncGraphControlLabels();
    render();
  </script>
</body>
</html>
""".replace("__TITLE__", title_safe).replace("__PORTAL_DATA__", portal_json)
    out_path.write_text(payload, encoding="utf-8")
    return {
        "ok": True,
        "path": str(out_path),
        "exported_assets": len(items),
        "collections": len(collections),
        "preview_mode": "embedded" if embed_local_previews else "linked",
        "preview_embed_threshold": PORTAL_EMBED_PREVIEW_MAX_ITEMS,
        "embedded_previews": embedded_previews,
        "linked_previews": linked_previews,
        "remote_previews": remote_previews,
        "no_preview": no_preview,
        "source": source or None,
        "collection_ids": [str(x).strip() for x in (collection_ids or []) if str(x).strip()] or None,
        "include_unassigned": bool(include_unassigned),
        "limit": limit if limit > 0 else None,
        "semantic_enabled": False,
        "phase": "phase_1_static_portal",
    }
