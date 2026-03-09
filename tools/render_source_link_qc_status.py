#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import re
import sqlite3
from pathlib import Path


def _tail_lines(path: Path, limit: int) -> str:
    try:
        lines = path.read_text(errors="replace").splitlines()
    except FileNotFoundError:
        return ""
    if limit <= 0:
        return "\n".join(lines)
    return "\n".join(lines[-limit:])


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _load_latest_enrichment_rows(db_path: Path, *, limit: int = 1) -> tuple[dict, list[dict]]:
    try:
        con = sqlite3.connect(str(db_path))
        con.row_factory = sqlite3.Row
    except Exception:
        return {}, []
    try:
        run = con.execute(
            """
            select id, notes, created_at
            from classification_runs
            where run_type='source_link_enrichment'
            order by created_at desc
            limit 1
            """
        ).fetchone()
        if not run:
            return {}, []
        rows = con.execute(
            """
            select asset_id, input_url, final_domain, page_title,
                   substr(text_excerpt, 1, 220) as text_excerpt, fetch_status
            from asset_source_link_enrichment
            where run_id=?
            order by rowid desc
            limit ?
            """,
            (str(run["id"]), int(limit)),
        ).fetchall()
        return dict(run), [dict(row) for row in rows]
    except Exception:
        return {}, []
    finally:
        con.close()


def _parse_progress(log_text: str) -> dict[str, str]:
    lines = [line for line in str(log_text or "").splitlines() if line.strip()]
    start_re = re.compile(
        r"^\[(?P<ts>[^\]]+)\]\s+source-link-enrichment start\s+"
        r"(?P<item>\d+/\d+)\s+asset=(?P<asset>\S+)\s+source=(?P<source>\S+)\s+host=(?P<host>\S+)\s+mode=(?P<mode>\S+)\s+title=(?P<title>.*)$"
    )
    done_re = re.compile(
        r"^\[(?P<ts>[^\]]+)\]\s+source-link-enrichment done\s+"
        r"(?P<item>\d+/\d+)\s+asset=(?P<asset>\S+)\s+status=(?P<status>\S+)\s+elapsed_s=(?P<elapsed>\S+)\s+domain=(?P<domain>\S+)\s+page_title=(?P<page_title>.*)$"
    )
    result: dict[str, str] = {}
    for line in reversed(lines):
        match = done_re.match(line)
        if match:
            result["last_event"] = "done"
            result["last_timestamp"] = match.group("ts")
            result["item"] = match.group("item")
            result["asset"] = match.group("asset")
            result["status"] = match.group("status")
            result["elapsed_s"] = match.group("elapsed")
            result["domain"] = match.group("domain")
            result["page_title"] = match.group("page_title")
            break
        match = start_re.match(line)
        if match:
            result["last_event"] = "start"
            result["last_timestamp"] = match.group("ts")
            result["item"] = match.group("item")
            result["asset"] = match.group("asset")
            result["source"] = match.group("source")
            result["host"] = match.group("host")
            result["mode"] = match.group("mode")
            result["title"] = match.group("title")
            break
    return result


def _html_escape(value: object) -> str:
    return html.escape(str(value or ""))


def render_status_page(status_path: Path, out_path: Path, tail_lines: int, db_path: Path) -> None:
    status = _load_json(status_path)
    log_path = Path(str(status.get("log_file") or "")).expanduser() if status.get("log_file") else None
    log_tail = _tail_lines(log_path, tail_lines) if log_path else ""
    progress = _parse_progress(log_tail)

    phase = str(status.get("phase") or "unknown")
    updated_at = str(status.get("updated_at") or "")
    track_run_id = str(status.get("track_run_id") or "")
    chunk = str(status.get("chunk") or "")
    start_index = str(status.get("start_index") or "")
    end_index = str(status.get("end_index") or "")
    total = str(status.get("total") or "")
    note = str(status.get("note") or "")

    manifest_path = status_path.parent.parent / "manifest.json"
    manifest = _load_json(manifest_path)
    counts = manifest.get("counts") if isinstance(manifest, dict) else {}
    if not isinstance(counts, dict):
        counts = {}
    latest_run, latest_rows = _load_latest_enrichment_rows(db_path, limit=1)
    latest_row = latest_rows[0] if latest_rows else {}

    html_text = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta http-equiv="refresh" content="10">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Source Link QC Status</title>
  <style>
    :root {{
      --bg: #f4efe6;
      --panel: #fffaf2;
      --ink: #27211b;
      --muted: #6a5f53;
      --line: #d7c8b6;
      --accent: #8e5b3a;
      --code: #f0e7da;
    }}
    body {{
      margin: 0;
      padding: 24px;
      background: linear-gradient(180deg, #f6f2ea 0%, #efe6d8 100%);
      color: var(--ink);
      font: 16px/1.5 Georgia, "Times New Roman", serif;
    }}
    .wrap {{
      max-width: 1100px;
      margin: 0 auto;
      display: grid;
      gap: 18px;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 18px 20px;
      box-shadow: 0 10px 24px rgba(58, 40, 20, 0.06);
    }}
    h1, h2 {{
      margin: 0 0 10px 0;
      font-weight: 600;
    }}
    .meta {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 10px 18px;
    }}
    .k {{
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}
    .v {{
      font-size: 16px;
    }}
    .counts {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 10px 18px;
    }}
    .row-card {{
      display: grid;
      gap: 8px;
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: 10px;
      background: #fcf7ef;
    }}
    .mono {{
      font-family: Menlo, Monaco, monospace;
      font-size: 12px;
      word-break: break-word;
    }}
    pre {{
      margin: 0;
      padding: 14px;
      overflow: auto;
      background: var(--code);
      border-radius: 10px;
      border: 1px solid var(--line);
      font: 12px/1.45 Menlo, Monaco, monospace;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    a {{
      color: var(--accent);
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="panel">
      <h1>Source Link QC Status</h1>
      <div class="meta">
        <div><div class="k">Phase</div><div class="v">{_html_escape(phase)}</div></div>
        <div><div class="k">Updated</div><div class="v">{_html_escape(updated_at)}</div></div>
        <div><div class="k">Chunk</div><div class="v">{_html_escape(chunk)}</div></div>
        <div><div class="k">Range</div><div class="v">{_html_escape(start_index)} - {_html_escape(end_index)} of {_html_escape(total)}</div></div>
        <div><div class="k">Track Run</div><div class="v">{_html_escape(track_run_id)}</div></div>
        <div><div class="k">Note</div><div class="v">{_html_escape(note)}</div></div>
      </div>
    </section>
    <section class="panel">
      <h2>Live Progress</h2>
      <div class="meta">
        <div><div class="k">Last Event</div><div class="v">{_html_escape(progress.get("last_event", ""))}</div></div>
        <div><div class="k">Last Timestamp</div><div class="v">{_html_escape(progress.get("last_timestamp", ""))}</div></div>
        <div><div class="k">Item</div><div class="v">{_html_escape(progress.get("item", ""))}</div></div>
        <div><div class="k">Asset</div><div class="v">{_html_escape(progress.get("asset", ""))}</div></div>
        <div><div class="k">Mode</div><div class="v">{_html_escape(progress.get("mode", ""))}</div></div>
        <div><div class="k">Status</div><div class="v">{_html_escape(progress.get("status", ""))}</div></div>
        <div><div class="k">Elapsed</div><div class="v">{_html_escape(progress.get("elapsed_s", ""))}</div></div>
        <div><div class="k">Domain</div><div class="v">{_html_escape(progress.get("domain", progress.get("host", "")))}</div></div>
      </div>
      <p><strong>Title:</strong> {_html_escape(progress.get("title", progress.get("page_title", "")))}</p>
    </section>
    <section class="panel">
      <h2>Current Export Snapshot</h2>
      <div class="counts">
        <div><div class="k">Conflicting</div><div class="v">{_html_escape(counts.get("source_link_conflicting", ""))}</div></div>
        <div><div class="k">Insufficient</div><div class="v">{_html_escape(counts.get("source_link_insufficient", ""))}</div></div>
        <div><div class="k">Platform Wrapper</div><div class="v">{_html_escape(counts.get("source_link_platform_wrapper", ""))}</div></div>
        <div><div class="k">Ambiguous Track</div><div class="v">{_html_escape(counts.get("ambiguous_track", ""))}</div></div>
      </div>
      <p>
        <a href="../index.html">Review Index</a> |
        <a href="../manifest.json">Manifest</a> |
        <a href="./source_link_browser_qc_status_latest.json">Status JSON</a> |
        <a href="{_html_escape(log_path.name if log_path else '')}">Log File</a>
      </p>
    </section>
    <section class="panel">
      <h2>Latest Stored Row</h2>
      <p>
        Latest completed enrichment run:
        <strong>{_html_escape(latest_run.get("id", ""))}</strong>
        {_html_escape(latest_run.get("notes", ""))}
      </p>
      <p>
        This is the newest enrichment row already written to the database. It updates when a chunk completes, so it will lag the live log by up to one chunk.
      </p>
      {(
        "<div class=\"row-card\">"
        f"<div><span class=\"k\">Asset</span><div class=\"v mono\">{_html_escape(latest_row.get('asset_id', ''))}</div></div>"
        f"<div><span class=\"k\">Status</span><div class=\"v\">{_html_escape(latest_row.get('fetch_status', ''))}</div></div>"
        f"<div><span class=\"k\">Domain</span><div class=\"v\">{_html_escape(latest_row.get('final_domain', ''))}</div></div>"
        f"<div><span class=\"k\">Page Title</span><div class=\"v\">{_html_escape(latest_row.get('page_title', ''))}</div></div>"
        f"<div><span class=\"k\">Input URL</span><div class=\"v mono\">{_html_escape(latest_row.get('input_url', ''))}</div></div>"
        f"<div><span class=\"k\">Text Excerpt</span><div class=\"v\">{_html_escape(latest_row.get('text_excerpt', ''))}</div></div>"
        "</div>"
      ) if latest_row else '<p>No stored enrichment rows yet.</p>'}
    </section>
    <section class="panel">
      <h2>Log Tail</h2>
      <pre>{_html_escape(log_tail or "No log output yet.")}</pre>
    </section>
  </div>
</body>
</html>
"""
    out_path.write_text(html_text)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", required=True, help="Path to status JSON")
    parser.add_argument("--out", required=True, help="Path to output HTML")
    parser.add_argument("--tail-lines", type=int, default=80, help="How many log lines to embed")
    parser.add_argument("--db", default="data/inspirations.sqlite", help="Path to SQLite database")
    args = parser.parse_args()

    render_status_page(Path(args.status), Path(args.out), int(args.tail_lines), Path(args.db))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
