#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import os
import re
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from string import Template

DEFAULT_DB = "/Users/minime/Projects/Inspirations/data/inspirations.sqlite"
DEFAULT_LOG = "/tmp/inspirations_gemini_tag_progress.log"
DEFAULT_MODEL = "gemini-2.5-flash"

DB_PATH = Path(os.environ.get("DB_PATH", DEFAULT_DB))
LOG_PATH = Path(os.environ.get("PROGRESS_LOG", DEFAULT_LOG))
MODEL = os.environ.get("MODEL", DEFAULT_MODEL)
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8765"))

HTML_TEMPLATE = Template("""<!doctype html>
<html>
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Gemini Tagging Monitor</title>
  <style>
    body { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace; margin: 24px; }
    .card { border: 1px solid #ddd; padding: 16px; border-radius: 8px; max-width: 900px; }
    .row { display: flex; gap: 16px; flex-wrap: wrap; }
    .k { color: #666; }
    .v { font-weight: 600; }
    pre { background: #f7f7f7; padding: 12px; border-radius: 6px; overflow-x: auto; }
  </style>
</head>
<body>
  <h1>Gemini Tagging Monitor</h1>
  <div class=\"card\">
    <div class=\"row\">
      <div><div class=\"k\">Now (UTC)</div><div class=\"v\" id=\"now\">$now</div></div>
      <div><div class=\"k\">Tagged (gemini)</div><div class=\"v\" id=\"count\">$count</div></div>
      <div><div class=\"k\">Remaining</div><div class=\"v\" id=\"remaining\">$remaining</div></div>
      <div><div class=\"k\">Rate</div><div class=\"v\" id=\"rate\">$rate</div></div>
      <div><div class=\"k\">ETA</div><div class=\"v\" id=\"eta\">$eta</div></div>
    </div>
    <h3>Latest Log Line</h3>
    <pre id=\"last_line\">$last_line</pre>
    <h3>Recent Log</h3>
    <pre id=\"recent\">$recent</pre>
    <h3>Status JSON</h3>
    <pre id=\"raw\">$raw</pre>
  </div>

  <script>
    async function refresh() {
      try {
        const r = await fetch('/status');
        const s = await r.json();
        document.getElementById('now').textContent = s.now || '-';
        document.getElementById('count').textContent = s.gemini_count ?? '-';
        document.getElementById('remaining').textContent = s.remaining ?? '-';
        document.getElementById('rate').textContent = s.rate ?? '-';
        document.getElementById('eta').textContent = s.eta ?? '-';
        document.getElementById('last_line').textContent = s.last_line || '-';
        document.getElementById('recent').textContent = (s.recent_lines || []).join('\n') || '-';
        document.getElementById('raw').textContent = JSON.stringify(s, null, 2);
      } catch (e) {
        document.getElementById('last_line').textContent = 'fetch error: ' + e;
      }
    }
    refresh();
    setInterval(refresh, 5000);
  </script>
</body>
</html>
""")


def render_html(status: dict[str, Any]) -> str:
    def esc(value: Any) -> str:
        return html.escape("" if value is None else str(value))

    recent = status.get("recent_lines") or []
    return HTML_TEMPLATE.safe_substitute(
        now=esc(status.get("now") or "-"),
        count=esc(status.get("gemini_count") if status.get("gemini_count") is not None else "-"),
        remaining=esc(status.get("remaining") if status.get("remaining") is not None else "-"),
        rate=esc(status.get("rate") or "-"),
        eta=esc(status.get("eta") or "-"),
        last_line=esc(status.get("last_line") or "-"),
        recent=esc("\n".join(recent) or "-"),
        raw=esc(json.dumps(status, indent=2)),
    )


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _db_value(sql: str, params: tuple[Any, ...] = ()) -> Any:
    if not DB_PATH.exists():
        return None
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        cur = conn.execute(sql, params)
        row = cur.fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def _tail_lines(path: Path, n: int = 10) -> list[str]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        lines = f.read().splitlines()
    return lines[-n:]


def _parse_metrics(line: str) -> dict[str, str | None]:
    out: dict[str, str | None] = {"rate": None, "eta": None}
    m = re.search(r"rate=([0-9.]+)/s", line)
    if m:
        out["rate"] = f"{m.group(1)}/s"
    m = re.search(r"eta~([0-9]+)m", line)
    if m:
        out["eta"] = f"{m.group(1)}m"
    return out


def get_status() -> dict[str, Any]:
    gemini_count = _db_value(
        "select count(*) from asset_ai where provider='gemini'", ()
    )
    remaining = _db_value(
        """
        select count(*)
        from assets a
        where a.source = ?
          and a.id not in (select asset_id from asset_ai where provider=? and model=?)
        """,
        ("pinterest", "gemini", MODEL),
    )
    recent = _tail_lines(LOG_PATH, 10)
    last_line = recent[-1] if recent else ""
    metrics = _parse_metrics(last_line)

    return {
        "now": _utc_now(),
        "gemini_count": int(gemini_count or 0),
        "remaining": int(remaining or 0),
        "last_line": last_line,
        "recent_lines": recent,
        "rate": metrics.get("rate"),
        "eta": metrics.get("eta"),
    }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path.startswith("/status"):
            data = json.dumps(get_status()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        data = render_html(get_status()).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    httpd = HTTPServer((HOST, PORT), Handler)
    print(f"Dashboard running at http://{HOST}:{PORT}")
    httpd.serve_forever()
