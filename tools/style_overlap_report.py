#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit


def _canonical_url(raw: str) -> str:
    value = str(raw or "").strip()
    if not value.startswith("http"):
        return ""
    parts = urlsplit(value)
    scheme = parts.scheme.lower() or "https"
    netloc = parts.netloc.lower()
    if netloc.startswith("m."):
        netloc = netloc[2:]
    path = parts.path.rstrip("/") or "/"
    # Ignore query/fragment for overlap matching.
    return urlunsplit((scheme, netloc, path, "", ""))


def _resolve_local_file(path: str, *, db_path: Path, cwd: Path) -> str:
    raw = str(path or "").strip()
    if not raw:
        return ""
    p = Path(raw).expanduser()
    checks: list[Path]
    if p.is_absolute():
        checks = [p]
    else:
        checks = [cwd / p, db_path.parent.parent / p, db_path.parent / p]
    for c in checks:
        r = c.resolve()
        if r.exists() and r.is_file():
            return r.as_uri()
    return ""


def _parse_old_style_md(path: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    room = "Unknown"
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("## "):
            room = line[3:].strip() or "Unknown"
            continue
        if not line.startswith("* "):
            continue
        m_url = re.search(r"\]\((https?://[^)]+)\)", line)
        if not m_url:
            continue
        url = m_url.group(1).strip()
        canon = _canonical_url(url)
        if not canon:
            continue
        m_stars = re.search(r"Rating:\s*([⭐]+)", line)
        stars = len(m_stars.group(1)) if m_stars else 0
        m_img = re.search(r"!\[Thumbnail\]\(([^)]+)\)", line)
        image = str(m_img.group(1)).strip() if m_img else ""
        m_note = re.search(r"Rating:\s*[⭐]+\s*-\s*(.*?)\s*\|\s*`Tags:`", line)
        note = (m_note.group(1).strip() if m_note else "")[:240]
        rec = {
            "url": url,
            "canon": canon,
            "room": room,
            "stars": int(stars),
            "image": image,
            "note": note,
            "source": "old",
            "bucket": "best" if stars >= 4 else "appendix",
        }
        prev = out.get(canon)
        if prev is None or int(rec["stars"]) > int(prev.get("stars") or 0):
            out[canon] = rec
    return out


def _parse_new_style_json(path: Path) -> dict[str, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8") or "{}")
    out: dict[str, dict[str, Any]] = {}
    for bucket_key, bucket_name in (("categories", "best"), ("appendixCategories", "appendix")):
        for cat in data.get(bucket_key) or []:
            room = str(cat.get("name") or "Unknown")
            for item in cat.get("items") or []:
                url = str(item.get("sourceUrl") or "").strip()
                canon = _canonical_url(url)
                if not canon:
                    continue
                rec = {
                    "url": url,
                    "canon": canon,
                    "room": room,
                    "stars": int(item.get("ratingValue") or 0),
                    "image": "",
                    "note": str(item.get("description") or item.get("classificationReason") or "")[:240],
                    "source": str(item.get("source") or ""),
                    "bucket": bucket_name,
                }
                prev = out.get(canon)
                if prev is None:
                    out[canon] = rec
                else:
                    prev_best = 1 if str(prev.get("bucket")) == "best" else 0
                    rec_best = 1 if bucket_name == "best" else 0
                    if rec_best > prev_best or (
                        rec_best == prev_best and int(rec["stars"]) > int(prev.get("stars") or 0)
                    ):
                        out[canon] = rec
    return out


def _thumb_map_for_urls(db_path: Path, urls: set[str], cwd: Path) -> dict[str, str]:
    wanted = set(urls)
    out: dict[str, str] = {}
    con = sqlite3.connect(str(db_path))
    try:
        cur = con.cursor()
        cur.execute("select source_ref, source_url, image_url, thumb_path from assets")
        for source_ref, source_url, image_url, thumb_path in cur.fetchall():
            thumb_uri = _resolve_local_file(str(thumb_path or ""), db_path=db_path, cwd=cwd)
            if not thumb_uri:
                continue
            for field in (source_ref, source_url, image_url):
                canon = _canonical_url(str(field or ""))
                if canon and canon in wanted and canon not in out:
                    out[canon] = thumb_uri
    finally:
        con.close()
    return out


def _render_rows(
    keys: list[str],
    *,
    old: dict[str, dict[str, Any]],
    new: dict[str, dict[str, Any]],
    thumbs: dict[str, str],
    max_rows: int,
) -> str:
    rows: list[str] = []
    for key in keys[:max_rows]:
        o = old.get(key) or {}
        n = new.get(key) or {}
        url = str((o or n).get("url") or key)
        image = str(o.get("image") or n.get("image") or thumbs.get(key) or "").strip()
        if image and image.startswith("/"):
            image = Path(image).expanduser().resolve().as_uri() if Path(image).exists() else image
        img_html = (
            f'<img src="{html.escape(image, quote=True)}" alt="" loading="lazy" />'
            if image
            else '<div class="imgMissing">No image</div>'
        )
        rows.append(
            f"""
            <tr>
              <td class="imgCol">{img_html}</td>
              <td><a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">Source</a></td>
              <td>{html.escape(str(o.get("room") or ""))}</td>
              <td>{html.escape(str(o.get("stars") or ""))}</td>
              <td>{html.escape(str(n.get("room") or ""))}</td>
              <td>{html.escape(str(n.get("stars") or ""))}</td>
              <td>{html.escape(str(o.get("note") or n.get("note") or ""))}</td>
            </tr>
            """
        )
    return "\n".join(rows)


def _room_table(old_best: dict[str, dict[str, Any]], new_best: dict[str, dict[str, Any]]) -> str:
    old_counts = Counter(str(v.get("room") or "Unknown") for v in old_best.values())
    new_counts = Counter(str(v.get("room") or "Unknown") for v in new_best.values())
    rooms = sorted(set(old_counts) | set(new_counts))
    rows = []
    for room in rooms:
        rows.append(
            f"<tr><td>{html.escape(room)}</td><td>{old_counts.get(room,0)}</td><td>{new_counts.get(room,0)}</td></tr>"
        )
    return "\n".join(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate old-vs-new style overlap report")
    parser.add_argument(
        "--old-style-md",
        default="Exploration/ai_curated_style.md",
        help="Legacy style markdown path",
    )
    parser.add_argument(
        "--new-style-json",
        default="data/exports/curation_full_gemini_summaries/style-best-of.json",
        help="New pipeline style JSON path",
    )
    parser.add_argument(
        "--db",
        default="data/inspirations.sqlite",
        help="SQLite DB path for thumbnail lookup",
    )
    parser.add_argument(
        "--out-html",
        default="",
        help="Output HTML path (default data/exports/style_overlap_report_<timestamp>.html)",
    )
    parser.add_argument(
        "--max-rows-per-section",
        type=int,
        default=350,
        help="Max rows rendered for each overlap section",
    )
    args = parser.parse_args()

    old_path = Path(args.old_style_md).expanduser().resolve()
    new_path = Path(args.new_style_json).expanduser().resolve()
    db_path = Path(args.db).expanduser().resolve()
    cwd = Path.cwd().resolve()

    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_html = (
        Path(args.out_html).expanduser().resolve()
        if str(args.out_html).strip()
        else (cwd / "data" / "exports" / f"style_overlap_report_{ts}.html")
    )
    out_json = out_html.with_suffix(".json")
    out_html.parent.mkdir(parents=True, exist_ok=True)

    old_all = _parse_old_style_md(old_path)
    new_all = _parse_new_style_json(new_path)
    old_best = {k: v for k, v in old_all.items() if int(v.get("stars") or 0) >= 4}
    new_best = {k: v for k, v in new_all.items() if str(v.get("bucket") or "") == "best"}

    old_keys = set(old_best)
    new_keys = set(new_best)
    common = sorted(old_keys & new_keys)
    old_only = sorted(old_keys - new_keys)
    new_only = sorted(new_keys - old_keys)
    union_keys = old_keys | new_keys

    thumbs = _thumb_map_for_urls(db_path, union_keys, cwd)

    report_data = {
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "inputs": {
            "oldStyleMd": str(old_path),
            "newStyleJson": str(new_path),
            "db": str(db_path),
        },
        "summary": {
            "oldBestCount": len(old_keys),
            "newBestCount": len(new_keys),
            "overlapCount": len(common),
            "oldOnlyCount": len(old_only),
            "newOnlyCount": len(new_only),
        },
        "roomsOldBest": dict(Counter(v["room"] for v in old_best.values())),
        "roomsNewBest": dict(Counter(v["room"] for v in new_best.values())),
        "starsOldBest": dict(Counter(int(v["stars"]) for v in old_best.values())),
        "starsNewBest": dict(Counter(int(v["stars"]) for v in new_best.values())),
        "common": [{"canon": k, "old": old_best.get(k), "new": new_best.get(k)} for k in common],
        "oldOnly": [{"canon": k, "old": old_best.get(k)} for k in old_only],
        "newOnly": [{"canon": k, "new": new_best.get(k)} for k in new_only],
    }
    out_json.write_text(json.dumps(report_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    html_doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Style Overlap Report</title>
  <style>
    :root {{
      --bg: #f5f7fa;
      --panel: #ffffff;
      --text: #102a43;
      --muted: #486581;
      --line: #d9e2ec;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--bg); color: var(--text); font-family: "Avenir Next", "Segoe UI", sans-serif; }}
    main {{ width: min(1500px, 96vw); margin: 20px auto 40px; display: grid; gap: 14px; }}
    .panel {{ background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 14px; }}
    h1, h2 {{ margin: 0 0 8px; }}
    .muted {{ color: var(--muted); }}
    .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; }}
    .stat {{ border: 1px solid var(--line); border-radius: 10px; padding: 10px; background: #fff; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border-bottom: 1px solid var(--line); text-align: left; padding: 8px; vertical-align: top; font-size: 13px; }}
    th {{ position: sticky; top: 0; background: #f8fbff; }}
    .tableWrap {{ overflow: auto; max-height: 70vh; border: 1px solid var(--line); border-radius: 10px; }}
    .imgCol {{ width: 82px; }}
    .imgCol img {{ width: 72px; height: 72px; object-fit: cover; border-radius: 6px; display: block; }}
    .imgMissing {{ width: 72px; height: 72px; border: 1px dashed var(--line); border-radius: 6px; color: var(--muted); display: grid; place-items: center; font-size: 11px; }}
    details > summary {{ cursor: pointer; font-weight: 700; margin-bottom: 8px; }}
    code {{ background: #eef4fb; padding: 1px 4px; border-radius: 4px; }}
  </style>
</head>
<body>
  <main>
    <section class="panel">
      <h1>Style Overlap Report (Old vs New)</h1>
      <p class="muted">Generated: {html.escape(report_data["generatedAt"])}</p>
      <p class="muted">Inputs: <code>{html.escape(str(old_path))}</code> vs <code>{html.escape(str(new_path))}</code></p>
      <p class="muted">Stars are integer buckets. Continuous signal available separately as classification confidence.</p>
      <div class="stats">
        <div class="stat"><strong>Old Best (>=4★)</strong><div>{len(old_keys)}</div></div>
        <div class="stat"><strong>New Best</strong><div>{len(new_keys)}</div></div>
        <div class="stat"><strong>Overlap</strong><div>{len(common)}</div></div>
        <div class="stat"><strong>Old Only</strong><div>{len(old_only)}</div></div>
        <div class="stat"><strong>New Only</strong><div>{len(new_only)}</div></div>
      </div>
    </section>

    <section class="panel">
      <h2>Room Distribution (Best Sets)</h2>
      <div class="tableWrap">
        <table>
          <thead><tr><th>Room</th><th>Old Best</th><th>New Best</th></tr></thead>
          <tbody>
            {_room_table(old_best, new_best)}
          </tbody>
        </table>
      </div>
    </section>

    <section class="panel">
      <details open>
        <summary>Common Best Picks ({len(common)}) - showing first {min(len(common), int(args.max_rows_per_section))}</summary>
        <div class="tableWrap">
          <table>
            <thead><tr><th>Img</th><th>URL</th><th>Old Room</th><th>Old ★</th><th>New Room</th><th>New ★</th><th>Note</th></tr></thead>
            <tbody>
              {_render_rows(common, old=old_best, new=new_best, thumbs=thumbs, max_rows=int(args.max_rows_per_section))}
            </tbody>
          </table>
        </div>
      </details>
    </section>

    <section class="panel">
      <details>
        <summary>Old-Only Best Picks ({len(old_only)}) - showing first {min(len(old_only), int(args.max_rows_per_section))}</summary>
        <div class="tableWrap">
          <table>
            <thead><tr><th>Img</th><th>URL</th><th>Old Room</th><th>Old ★</th><th>New Room</th><th>New ★</th><th>Note</th></tr></thead>
            <tbody>
              {_render_rows(old_only, old=old_best, new=new_best, thumbs=thumbs, max_rows=int(args.max_rows_per_section))}
            </tbody>
          </table>
        </div>
      </details>
    </section>

    <section class="panel">
      <details>
        <summary>New-Only Best Picks ({len(new_only)}) - showing first {min(len(new_only), int(args.max_rows_per_section))}</summary>
        <div class="tableWrap">
          <table>
            <thead><tr><th>Img</th><th>URL</th><th>Old Room</th><th>Old ★</th><th>New Room</th><th>New ★</th><th>Note</th></tr></thead>
            <tbody>
              {_render_rows(new_only, old=old_best, new=new_best, thumbs=thumbs, max_rows=int(args.max_rows_per_section))}
            </tbody>
          </table>
        </div>
      </details>
    </section>

    <section class="panel">
      <p class="muted">Full diff data: <code>{html.escape(str(out_json))}</code></p>
    </section>
  </main>
</body>
</html>
"""
    out_html.write_text(html_doc, encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "outHtml": str(out_html),
                "outJson": str(out_json),
                "summary": report_data["summary"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
