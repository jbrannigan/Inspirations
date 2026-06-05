#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from inspirations.review_slices import (
    AMBIGUOUS_LOW_SIGNAL_URL,
    AMBIGUOUS_MEDIA_LINK_MISMATCH,
    AMBIGUOUS_MEDIA_MISMATCH,
    AMBIGUOUS_MEDIA_WEAK_THUMBNAIL,
    AMBIGUOUS_TRUE_CONTESTED,
    classify_ambiguous_review_bucket,
)


AXES_TO_EXPORT = (
    "space_context",
    "subject_type",
    "room",
    "product_focus",
    "concern_domain",
    "product_system_focus",
)

TRACK_MAINTENANCE = "home_maintenance_diy"


def _truncate(value: Any, limit: int = 240) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def _latest_run_id(con: sqlite3.Connection, run_type: str) -> str:
    row = con.execute(
        "select id from classification_runs where run_type = ? order by created_at desc limit 1",
        (run_type,),
    ).fetchone()
    if not row or not row["id"]:
        raise SystemExit(f"no classification_runs row found for run_type={run_type!r}")
    return str(row["id"])


def _load_assets(con: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    rows = con.execute(
        """
        select
          id,
          lower(coalesce(source, '')) as source,
          coalesce(board, '') as board,
          coalesce(title, '') as title,
          coalesce(description, '') as description,
          coalesce(ai_summary, '') as ai_summary,
          coalesce(notes, '') as notes,
          coalesce(source_url, '') as source_url,
          coalesce(source_ref, '') as source_ref,
          coalesce(source_domain, '') as source_domain,
          coalesce(media_status, '') as media_status,
          coalesce(content_kind, '') as content_kind,
          coalesce(triage_status, '') as triage_status,
          coalesce(thumb_path, '') as thumb_path,
          coalesce(stored_path, '') as stored_path,
          coalesce((
            select axis_value
            from asset_overrides
            where asset_id=assets.id
              and axis_name='media_reliability'
              and operation='set'
              and expires_at is null
            order by created_at desc, id desc
            limit 1
          ), '') as media_reliability
        from assets
        """
    ).fetchall()
    return {str(row["id"]): dict(row) for row in rows}


def _load_track_assessments(con: sqlite3.Connection, run_id: str) -> dict[str, dict[str, Any]]:
    rows = con.execute(
        """
        select asset_id, track, confidence, is_ambiguous, decision_source, coalesce(reason, '') as reason
        from asset_track_assessments
        where run_id = ?
        """,
        (run_id,),
    ).fetchall()
    return {
        str(row["asset_id"]): {
            "track": str(row["track"] or ""),
            "track_confidence": row["confidence"],
            "track_is_ambiguous": int(row["is_ambiguous"] or 0),
            "track_decision_source": str(row["decision_source"] or ""),
            "track_reason": str(row["reason"] or ""),
        }
        for row in rows
    }


def _load_axis_memberships(
    con: sqlite3.Connection, run_id: str
) -> tuple[dict[str, dict[str, list[str]]], dict[str, dict[str, Any]]]:
    rows = con.execute(
        """
        select asset_id, axis_name, axis_value, confidence, rank, is_primary
        from asset_axis_memberships
        where run_id = ?
        order by asset_id asc, axis_name asc, is_primary desc, rank asc, confidence desc, axis_value asc
        """,
        (run_id,),
    ).fetchall()
    values: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    envelope_flags: dict[str, dict[str, Any]] = defaultdict(lambda: {"has_envelope": False, "has_product_system_focus": False})
    for row in rows:
        asset_id = str(row["asset_id"])
        axis_name = str(row["axis_name"] or "")
        axis_value = str(row["axis_value"] or "")
        if not axis_name or not axis_value:
            continue
        bucket = values[asset_id][axis_name]
        if axis_value not in bucket:
            bucket.append(axis_value)
        if axis_name == "concern_domain" and axis_value == "envelope":
            envelope_flags[asset_id]["has_envelope"] = True
        if axis_name == "product_system_focus":
            envelope_flags[asset_id]["has_product_system_focus"] = True
    return values, envelope_flags


def _load_latest_ai(con: sqlite3.Connection, asset_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not asset_ids:
        return {}
    placeholders = ",".join(["?"] * len(asset_ids))
    rows = con.execute(
        f"""
        select ai.asset_id, ai.provider, ai.model, coalesce(ai.summary, '') as summary, coalesce(ai.json, '') as raw_json
        from asset_ai ai
        join (
          select asset_id, max(created_at) as max_created_at
          from asset_ai
          where asset_id in ({placeholders})
          group by asset_id
        ) latest
          on latest.asset_id = ai.asset_id
         and latest.max_created_at = ai.created_at
        where ai.asset_id in ({placeholders})
        """,
        (*asset_ids, *asset_ids),
    ).fetchall()
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        raw_json = str(row["raw_json"] or "").strip()
        try:
            payload = json.loads(raw_json) if raw_json else {}
        except Exception:
            payload = {}
        out[str(row["asset_id"])] = {
            "provider": str(row["provider"] or ""),
            "model": str(row["model"] or ""),
            "summary": str(row["summary"] or ""),
            "payload": payload if isinstance(payload, dict) else {},
        }
    return out


def _load_latest_source_link_enrichment(con: sqlite3.Connection, asset_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not asset_ids:
        return {}
    placeholders = ",".join(["?"] * len(asset_ids))
    try:
        rows = con.execute(
            f"""
            select e.asset_id, e.input_url, e.final_url, e.final_domain, e.canonical_url,
                   e.og_image_url, e.page_title, e.og_title, e.meta_description,
                   e.og_description, e.text_excerpt, e.content_type, e.http_status,
                   e.redirect_count, e.truncated, e.fetch_status, e.error
            from asset_source_link_enrichment e
            join (
              select asset_id, max(created_at) as max_created_at
              from asset_source_link_enrichment
              where asset_id in ({placeholders})
              group by asset_id
            ) latest
              on latest.asset_id = e.asset_id
             and latest.max_created_at = e.created_at
            where e.asset_id in ({placeholders})
            """,
            (*asset_ids, *asset_ids),
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    return {str(row["asset_id"]): dict(row) for row in rows}


def _load_latest_source_link_qc(con: sqlite3.Connection, asset_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not asset_ids:
        return {}
    placeholders = ",".join(["?"] * len(asset_ids))
    try:
        rows = con.execute(
            f"""
            select q.asset_id, q.track, q.inferred_track, q.verdict, q.confidence, q.reason, q.fetch_status
            from asset_source_link_qc q
            join (
              select asset_id, max(created_at) as max_created_at
              from asset_source_link_qc
              where asset_id in ({placeholders})
              group by asset_id
            ) latest
              on latest.asset_id = q.asset_id
             and latest.max_created_at = q.created_at
            where q.asset_id in ({placeholders})
            """,
            (*asset_ids, *asset_ids),
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    return {str(row["asset_id"]): dict(row) for row in rows}


def _load_axis_evidence(
    con: sqlite3.Connection, run_id: str, asset_ids: list[str]
) -> dict[str, list[str]]:
    if not asset_ids:
        return {}
    placeholders = ",".join(["?"] * len(asset_ids))
    rows = con.execute(
        f"""
        select asset_id, axis_name, axis_value, evidence_type, coalesce(note, '') as note
        from asset_axis_evidence
        where run_id = ?
          and asset_id in ({placeholders})
        order by asset_id asc, weight desc, confidence desc, axis_name asc, axis_value asc
        """,
        (run_id, *asset_ids),
    ).fetchall()
    grouped: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        asset_id = str(row["asset_id"])
        note = _truncate(row["note"], 180)
        axis_name = str(row["axis_name"] or "")
        axis_value = str(row["axis_value"] or "")
        evidence_type = str(row["evidence_type"] or "")
        text = note or f"{axis_name}:{axis_value} ({evidence_type})"
        if text not in grouped[asset_id] and len(grouped[asset_id]) < 5:
            grouped[asset_id].append(text)
    return grouped


def _build_row(
    asset_id: str,
    *,
    assets: dict[str, dict[str, Any]],
    tracks: dict[str, dict[str, Any]],
    axes: dict[str, dict[str, list[str]]],
    evidence: dict[str, list[str]],
    ai: dict[str, dict[str, Any]],
    source_links: dict[str, dict[str, Any]],
    source_qc: dict[str, dict[str, Any]],
    slice_name: str,
) -> dict[str, Any]:
    asset = assets[asset_id]
    track = tracks.get(asset_id, {})
    axis_map = axes.get(asset_id, {})
    latest_ai = ai.get(asset_id, {})
    source_link = source_links.get(asset_id, {})
    qc = source_qc.get(asset_id, {})
    payload = latest_ai.get("payload") or {}
    row: dict[str, Any] = {
        "slice": slice_name,
        "asset_id": asset_id,
        "source": asset.get("source", ""),
        "source_domain": asset.get("source_domain", ""),
        "media_status": asset.get("media_status", ""),
        "content_kind": asset.get("content_kind", ""),
        "board": asset.get("board", ""),
        "triage_status": asset.get("triage_status", "") or "pending",
        "title": asset.get("title", ""),
        "description_excerpt": _truncate(asset.get("description", ""), 180),
        "ai_summary_excerpt": _truncate(asset.get("ai_summary", ""), 180),
        "latest_ai_provider": latest_ai.get("provider", ""),
        "latest_ai_summary_excerpt": _truncate(latest_ai.get("summary", ""), 180),
        "ai_image_type": str(payload.get("image_type", "") or ""),
        "notes_excerpt": _truncate(asset.get("notes", ""), 180),
        "source_url": asset.get("source_url", ""),
        "source_ref": asset.get("source_ref", ""),
        "source_fetch_status": source_link.get("fetch_status", ""),
        "source_http_status": source_link.get("http_status"),
        "source_final_url": source_link.get("final_url", ""),
        "source_final_domain": source_link.get("final_domain", ""),
        "source_canonical_url": source_link.get("canonical_url", ""),
        "source_page_title": source_link.get("page_title", ""),
        "source_og_title": source_link.get("og_title", ""),
        "source_meta_description_excerpt": _truncate(source_link.get("meta_description", ""), 180),
        "source_og_description_excerpt": _truncate(source_link.get("og_description", ""), 180),
        "source_text_excerpt": _truncate(source_link.get("text_excerpt", ""), 220),
        "source_fetch_error": source_link.get("error", ""),
        "source_qc_verdict": qc.get("verdict", ""),
        "source_qc_inferred_track": qc.get("inferred_track", ""),
        "source_qc_confidence": qc.get("confidence"),
        "source_qc_reason": _truncate(qc.get("reason", ""), 220),
        "track": track.get("track", ""),
        "track_confidence": track.get("track_confidence"),
        "track_is_ambiguous": track.get("track_is_ambiguous", 0),
        "track_decision_source": track.get("track_decision_source", ""),
        "track_reason": _truncate(track.get("track_reason", ""), 240),
        "evidence_notes": " || ".join(evidence.get(asset_id, [])),
    }
    for axis_name in AXES_TO_EXPORT:
        row[axis_name] = " | ".join(axis_map.get(axis_name, []))
    return row


def _resolve_existing_local_path(raw: str, *, cwd: Path) -> Path | None:
    value = str(raw or "").strip()
    if not value:
        return None
    p = Path(value).expanduser()
    if not p.is_absolute():
        p = (cwd / p).resolve()
    else:
        p = p.resolve()
    if p.exists() and p.is_file():
        return p
    return None


def _image_uri_for_asset(asset: dict[str, Any], *, cwd: Path) -> str:
    thumb_path = _resolve_existing_local_path(asset.get("thumb_path", ""), cwd=cwd)
    if thumb_path:
        return thumb_path.as_uri()
    stored_path = _resolve_existing_local_path(asset.get("stored_path", ""), cwd=cwd)
    if stored_path:
        return stored_path.as_uri()
    return ""


def _source_href(row: dict[str, Any]) -> str:
    for key in ("source_final_url", "source_url", "source_ref"):
        value = str(row.get(key, "")).strip()
        if value.startswith("http://") or value.startswith("https://"):
            return value
    return ""


def _render_slice_html(
    *,
    slice_name: str,
    rows: list[dict[str, Any]],
    out_path: Path,
    generated_at: str,
    track_run_id: str,
    axis_run_id: str,
    cwd: Path,
) -> None:
    display_titles = {
        "ambiguous_media_weak_thumbnail": "Media: Trust Title / Source",
        "ambiguous_media_link_mismatch": "Media: Link / Thumbnail Mismatch",
        "ambiguous_media_mismatch": "Media Mismatch",
        "ambiguous_low_signal_url": "Ambiguous: Low-Signal URLs",
        "ambiguous_true_contested": "Ambiguous: True Contested",
        "maintenance_diy_track": "Maintenance / DIY Track",
        "source_link_conflicting": "Source Link Conflicts",
        "source_link_insufficient": "Source Link Insufficient",
        "source_link_platform_wrapper": "Source Link Platform Wrappers",
    }
    title = display_titles.get(slice_name, slice_name.replace("_", " ").title())
    cards: list[str] = []
    for row in rows:
        asset = {
            "thumb_path": row.get("thumb_path", ""),
            "stored_path": row.get("stored_path", ""),
        }
        image_uri = _image_uri_for_asset(asset, cwd=cwd)
        image_html = (
            f'<img src="{html.escape(image_uri, quote=True)}" alt="{html.escape(str(row.get("title") or ""), quote=True)}" loading="lazy" />'
            if image_uri
            else '<div class="thumb-missing">No image</div>'
        )
        source_href = _source_href(row)
        source_link = (
            f'<a href="{html.escape(source_href, quote=True)}" target="_blank" rel="noopener noreferrer">Open source</a>'
            if source_href
            else ""
        )
        chips = []
        for label_key in ("track", "source_qc_verdict", "source_qc_inferred_track", "ambiguous_bucket", "suggested_track", "space_context", "subject_type", "room", "concern_domain", "product_system_focus"):
            value = str(row.get(label_key) or "").strip()
            if value:
                chips.append(f'<span class="chip"><strong>{html.escape(label_key.replace("_", " "))}:</strong> {html.escape(value)}</span>')
        cards.append(
            f"""
            <article class="card">
              <div class="thumb">{image_html}</div>
              <div class="body">
                <div class="title">{html.escape(str(row.get("title") or ""))}</div>
                <div class="meta">{html.escape(str(row.get("source") or ""))} · {html.escape(str(row.get("board") or ""))}</div>
                <div class="chips">{''.join(chips)}</div>
                <div class="block"><strong>Track reason</strong><br>{html.escape(str(row.get("track_reason") or ""))}</div>
                <div class="block"><strong>Suggested action</strong><br>{html.escape(str(row.get("suggested_reason") or ""))}</div>
                <div class="block"><strong>Source page</strong><br>{html.escape(str(row.get("source_fetch_status") or ""))} · {html.escape(str(row.get("source_page_title") or ""))}<br>{html.escape(str(row.get("source_meta_description_excerpt") or row.get("source_og_description_excerpt") or row.get("source_text_excerpt") or row.get("source_fetch_error") or ""))}</div>
                <div class="block"><strong>Source QC</strong><br>{html.escape(str(row.get("source_qc_verdict") or ""))} · {html.escape(str(row.get("source_qc_reason") or ""))}</div>
                <div class="block"><strong>Evidence notes</strong><br>{html.escape(str(row.get("evidence_notes") or ""))}</div>
                <div class="links">
                  {source_link}
                  <span class="asset-id">{html.escape(str(row.get("asset_id") or ""))}</span>
                </div>
              </div>
            </article>
            """
        )

    doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(title)} Review</title>
  <style>
    :root {{
      --bg: #f2eee6;
      --panel: #fffaf2;
      --ink: #231f1a;
      --muted: #6b6258;
      --line: #d9cfbf;
      --chip: #ebe1d2;
      --accent: #8c5b2f;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      padding: 24px;
      font-family: Georgia, "Iowan Old Style", serif;
      background: linear-gradient(180deg, #f7f2ea 0%, var(--bg) 100%);
      color: var(--ink);
    }}
    .shell {{
      max-width: 1400px;
      margin: 0 auto;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 34px;
      line-height: 1.1;
    }}
    .sub {{
      color: var(--muted);
      margin-bottom: 24px;
      font-size: 15px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
      gap: 18px;
    }}
    .card {{
      display: grid;
      grid-template-columns: 160px 1fr;
      gap: 16px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 14px;
      box-shadow: 0 12px 30px rgba(35, 31, 26, 0.06);
      min-height: 220px;
    }}
    .thumb {{
      width: 160px;
      height: 190px;
      border-radius: 12px;
      overflow: hidden;
      background: #ddd4c8;
      display: flex;
      align-items: center;
      justify-content: center;
    }}
    .thumb img {{
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }}
    .thumb-missing {{
      color: var(--muted);
      font-size: 13px;
      text-align: center;
      padding: 12px;
    }}
    .body {{
      display: flex;
      flex-direction: column;
      gap: 10px;
      min-width: 0;
    }}
    .title {{
      font-size: 21px;
      line-height: 1.2;
    }}
    .meta {{
      color: var(--muted);
      font-size: 14px;
    }}
    .chips {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .chip {{
      background: var(--chip);
      border-radius: 999px;
      padding: 6px 10px;
      font-size: 12px;
      line-height: 1.2;
    }}
    .block {{
      font-size: 13px;
      line-height: 1.45;
      color: var(--ink);
    }}
    .links {{
      margin-top: auto;
      display: flex;
      gap: 12px;
      align-items: center;
      flex-wrap: wrap;
      font-size: 13px;
    }}
    a {{
      color: var(--accent);
      text-decoration: none;
    }}
    a:hover {{ text-decoration: underline; }}
    .asset-id {{
      color: var(--muted);
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 12px;
    }}
    @media (max-width: 720px) {{
      body {{ padding: 14px; }}
      .card {{ grid-template-columns: 1fr; }}
      .thumb {{ width: 100%; height: 220px; }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <h1>{html.escape(title)} Review</h1>
    <div class="sub">Generated {html.escape(generated_at)} · Track run {html.escape(track_run_id)} · Axis run {html.escape(axis_run_id)} · {len(rows)} items</div>
    <div class="grid">
      {''.join(cards)}
    </div>
  </div>
</body>
</html>
"""
    out_path.write_text(doc, encoding="utf-8")


def _render_index_html(
    *,
    out_path: Path,
    manifest: dict[str, Any],
    html_files: dict[str, Path],
) -> None:
    display_titles = {
        "ambiguous_media_weak_thumbnail": "Media: Trust Title / Source",
        "ambiguous_media_link_mismatch": "Media: Link / Thumbnail Mismatch",
        "ambiguous_media_mismatch": "Media Mismatch",
        "ambiguous_low_signal_url": "Ambiguous: Low-Signal URLs",
        "ambiguous_true_contested": "Ambiguous: True Contested",
        "maintenance_diy_track": "Maintenance / DIY Track",
        "source_link_conflicting": "Source Link Conflicts",
        "source_link_insufficient": "Source Link Insufficient",
        "source_link_platform_wrapper": "Source Link Platform Wrappers",
    }
    entries = []
    for slice_name, count in manifest["counts"].items():
        html_path = html_files.get(slice_name)
        entries.append(
            f'<li><a href="{html.escape(html_path.name if html_path else "")}">{html.escape(display_titles.get(slice_name, slice_name.replace("_", " ").title()))}</a> <span>{int(count)}</span></li>'
        )
    doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Classification Review Checkpoint</title>
  <style>
    body {{
      margin: 0;
      padding: 32px;
      font-family: Georgia, "Iowan Old Style", serif;
      background: #f5efe5;
      color: #231f1a;
    }}
    .shell {{ max-width: 920px; margin: 0 auto; }}
    h1 {{ margin-top: 0; font-size: 36px; }}
    .meta {{ color: #6b6258; margin-bottom: 22px; }}
    ul {{ list-style: none; padding: 0; margin: 0; display: grid; gap: 12px; }}
    li {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 14px 16px;
      border: 1px solid #d9cfbf;
      border-radius: 14px;
      background: #fffaf2;
    }}
    a {{ color: #8c5b2f; text-decoration: none; font-size: 20px; }}
    a:hover {{ text-decoration: underline; }}
    span {{ color: #6b6258; font-size: 15px; }}
  </style>
</head>
<body>
  <div class="shell">
    <h1>Classification Review Checkpoint</h1>
    <div class="meta">Generated {html.escape(str(manifest.get("generated_at") or ""))} · Track run {html.escape(str(manifest.get("track_run_id") or ""))} · Axis run {html.escape(str(manifest.get("axis_run_id") or ""))}</div>
    <ul>{''.join(entries)}</ul>
  </div>
</body>
</html>
"""
    out_path.write_text(doc, encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Export checkpoint review slices for the latest v2 classification runs")
    parser.add_argument("--db", default="data/inspirations.sqlite", help="SQLite DB path")
    parser.add_argument(
        "--outdir",
        default="",
        help="Output directory (default data/exports/classification_review_checkpoint_<YYYYMMDD>)",
    )
    args = parser.parse_args()

    db_path = Path(args.db).expanduser().resolve()
    date_slug = datetime.now().strftime("%Y%m%d")
    outdir = (
        Path(args.outdir).expanduser().resolve()
        if args.outdir
        else (db_path.parent / "exports" / f"classification_review_checkpoint_{date_slug}").resolve()
    )
    outdir.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    try:
        track_run_id = _latest_run_id(con, "track_gate")
        axis_run_id = _latest_run_id(con, "multi_axis_inference")
        assets = _load_assets(con)
        tracks = _load_track_assessments(con, track_run_id)
        axes, envelope_flags = _load_axis_memberships(con, axis_run_id)
        ai = _load_latest_ai(con, list(assets.keys()))
        source_links = _load_latest_source_link_enrichment(con, list(assets.keys()))
        source_qc = _load_latest_source_link_qc(con, list(assets.keys()))

        ambiguous_ids = sorted(
            [asset_id for asset_id, row in tracks.items() if int(row.get("track_is_ambiguous") or 0)],
            key=lambda asset_id: (
                assets.get(asset_id, {}).get("source", ""),
                float(tracks[asset_id].get("track_confidence") or 0.0),
                assets.get(asset_id, {}).get("title", "").lower(),
            ),
        )
        pinterest_construction_ids = sorted(
            [
                asset_id
                for asset_id, row in tracks.items()
                if row.get("track") == "construction_concern"
                and assets.get(asset_id, {}).get("source") == "pinterest"
            ],
            key=lambda asset_id: (
                float(tracks[asset_id].get("track_confidence") or 0.0),
                assets.get(asset_id, {}).get("board", "").lower(),
                assets.get(asset_id, {}).get("title", "").lower(),
            ),
        )
        maintenance_track_ids = sorted(
            [
                asset_id
                for asset_id, row in tracks.items()
                if row.get("track") == TRACK_MAINTENANCE
            ],
            key=lambda asset_id: (
                assets.get(asset_id, {}).get("source", ""),
                assets.get(asset_id, {}).get("board", "").lower(),
                assets.get(asset_id, {}).get("title", "").lower(),
            ),
        )
        pinterest_maintenance_ids = sorted(
            [
                asset_id
                for asset_id, row in tracks.items()
                if row.get("track") == TRACK_MAINTENANCE
                and assets.get(asset_id, {}).get("source") == "pinterest"
            ],
            key=lambda asset_id: (
                float(tracks[asset_id].get("track_confidence") or 0.0),
                assets.get(asset_id, {}).get("board", "").lower(),
                assets.get(asset_id, {}).get("title", "").lower(),
            ),
        )
        undiff_envelope_ids = sorted(
            [
                asset_id
                for asset_id, flags in envelope_flags.items()
                if flags["has_envelope"] and not flags["has_product_system_focus"]
            ],
            key=lambda asset_id: (
                assets.get(asset_id, {}).get("source", ""),
                assets.get(asset_id, {}).get("board", "").lower(),
                assets.get(asset_id, {}).get("title", "").lower(),
            ),
        )

        evidence_ids = sorted(set(ambiguous_ids + pinterest_construction_ids + maintenance_track_ids + pinterest_maintenance_ids + undiff_envelope_ids))
        evidence = _load_axis_evidence(con, axis_run_id, evidence_ids)

        ambiguous_low_signal_ids: list[str] = []
        ambiguous_media_mismatch_ids: list[str] = []
        ambiguous_media_link_mismatch_ids: list[str] = []
        ambiguous_media_weak_thumbnail_ids: list[str] = []
        ambiguous_true_contested_ids: list[str] = []
        ambiguous_meta: dict[str, dict[str, str]] = {}
        for asset_id in ambiguous_ids:
            bucket, suggested_track, suggested_reason = classify_ambiguous_review_bucket(
                assets.get(asset_id, {}),
                tracks.get(asset_id, {}),
                ai.get(asset_id, {}),
                source_links.get(asset_id, {}),
            )
            ambiguous_meta[asset_id] = {
                "ambiguous_bucket": bucket,
                "suggested_track": suggested_track,
                "suggested_reason": suggested_reason,
            }
            if bucket == AMBIGUOUS_LOW_SIGNAL_URL:
                ambiguous_low_signal_ids.append(asset_id)
            elif bucket == AMBIGUOUS_MEDIA_LINK_MISMATCH:
                ambiguous_media_mismatch_ids.append(asset_id)
                ambiguous_media_link_mismatch_ids.append(asset_id)
            elif bucket == AMBIGUOUS_MEDIA_WEAK_THUMBNAIL:
                ambiguous_media_mismatch_ids.append(asset_id)
                ambiguous_media_weak_thumbnail_ids.append(asset_id)
            elif bucket == AMBIGUOUS_MEDIA_MISMATCH:
                ambiguous_media_mismatch_ids.append(asset_id)
            else:
                ambiguous_true_contested_ids.append(asset_id)

        source_link_conflicting_ids = sorted(
            [asset_id for asset_id, qc in source_qc.items() if str(qc.get("verdict") or "") == "conflicting"],
            key=lambda asset_id: (
                assets.get(asset_id, {}).get("source", ""),
                assets.get(asset_id, {}).get("board", "").lower(),
                assets.get(asset_id, {}).get("title", "").lower(),
            ),
        )
        source_link_insufficient_ids = sorted(
            [asset_id for asset_id, qc in source_qc.items() if str(qc.get("verdict") or "") == "insufficient"],
            key=lambda asset_id: (
                assets.get(asset_id, {}).get("source", ""),
                assets.get(asset_id, {}).get("board", "").lower(),
                assets.get(asset_id, {}).get("title", "").lower(),
            ),
        )
        source_link_platform_wrapper_ids = sorted(
            [asset_id for asset_id, qc in source_qc.items() if str(qc.get("verdict") or "") == "platform_wrapper"],
            key=lambda asset_id: (
                assets.get(asset_id, {}).get("source", ""),
                assets.get(asset_id, {}).get("board", "").lower(),
                assets.get(asset_id, {}).get("title", "").lower(),
            ),
        )

        slices = {
            "ambiguous_track": ambiguous_ids,
            AMBIGUOUS_LOW_SIGNAL_URL: ambiguous_low_signal_ids,
            AMBIGUOUS_MEDIA_MISMATCH: ambiguous_media_mismatch_ids,
            AMBIGUOUS_MEDIA_LINK_MISMATCH: ambiguous_media_link_mismatch_ids,
            AMBIGUOUS_MEDIA_WEAK_THUMBNAIL: ambiguous_media_weak_thumbnail_ids,
            AMBIGUOUS_TRUE_CONTESTED: ambiguous_true_contested_ids,
            "pinterest_construction": pinterest_construction_ids,
            "maintenance_diy_track": maintenance_track_ids,
            "pinterest_maintenance_diy": pinterest_maintenance_ids,
            "undifferentiated_envelope": undiff_envelope_ids,
            "source_link_conflicting": source_link_conflicting_ids,
            "source_link_insufficient": source_link_insufficient_ids,
            "source_link_platform_wrapper": source_link_platform_wrapper_ids,
        }
        manifest = {
            "db": str(db_path),
            "generated_at": datetime.now().astimezone().isoformat(),
            "track_run_id": track_run_id,
            "axis_run_id": axis_run_id,
            "counts": {},
            "files": {},
        }
        html_files: dict[str, Path] = {}

        for slice_name, asset_ids in slices.items():
            rows = [
                _build_row(
                    asset_id,
                    assets=assets,
                    tracks=tracks,
                    axes=axes,
                    evidence=evidence,
                    ai=ai,
                    source_links=source_links,
                    source_qc=source_qc,
                    slice_name=slice_name,
                )
                for asset_id in asset_ids
                if asset_id in assets
            ]
            for row in rows:
                row["thumb_path"] = assets[row["asset_id"]].get("thumb_path", "")
                row["stored_path"] = assets[row["asset_id"]].get("stored_path", "")
                row.update(ambiguous_meta.get(row["asset_id"], {"ambiguous_bucket": "", "suggested_track": "", "suggested_reason": ""}))
            json_path = outdir / f"{slice_name}.json"
            csv_path = outdir / f"{slice_name}.csv"
            html_path = outdir / f"{slice_name}.html"
            _write_json(json_path, rows)
            _write_csv(csv_path, rows)
            _render_slice_html(
                slice_name=slice_name,
                rows=rows,
                out_path=html_path,
                generated_at=manifest["generated_at"],
                track_run_id=track_run_id,
                axis_run_id=axis_run_id,
                cwd=Path.cwd(),
            )
            html_files[slice_name] = html_path
            manifest["counts"][slice_name] = len(rows)
            manifest["files"][slice_name] = {
                "json": str(json_path),
                "csv": str(csv_path),
                "html": str(html_path),
            }

        _render_index_html(out_path=outdir / "index.html", manifest=manifest, html_files=html_files)
        _write_json(outdir / "manifest.json", manifest)
    finally:
        con.close()

    print(json.dumps({"ok": True, "outdir": str(outdir), "manifest": str(outdir / "manifest.json")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
