#!/usr/bin/env python3
"""
Serve the Cluster Explorer UI and exported cluster JSON over local HTTP.

Allowed routes:
- /                  -> tools/cluster_explorer.html
- /cluster_data.json -> exported JSON file
- /store/...         -> project_root/store files only
"""

from __future__ import annotations

import argparse
import mimetypes
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


REPO_ROOT = Path(__file__).resolve().parent.parent


def _guess_mime(path: Path) -> str:
    if path.name.endswith(".html"):
        return "text/html; charset=utf-8"
    if path.name.endswith(".json"):
        return "application/json"
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


def _safe_relative_store_path(url_path: str) -> Path | None:
    raw = unquote(url_path or "")
    if not raw.startswith("/store/"):
        return None
    rel = raw.lstrip("/")
    rel_path = Path(rel)
    if rel_path.is_absolute():
        return None
    parts = rel_path.parts
    if any(part in {"..", ""} for part in parts):
        return None
    return rel_path


class ExplorerHandler(BaseHTTPRequestHandler):
    server_version = "InspirationsClusterExplorer/0.1"

    def do_GET(self) -> None:
        return self._dispatch(send_body=True)

    def do_HEAD(self) -> None:
        return self._dispatch(send_body=False)

    def _dispatch(self, *, send_body: bool) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/index.html"}:
            return self._serve_file(self.server.explorer_html_path, cache_control="no-store", send_body=send_body)

        if parsed.path == "/cluster_data.json":
            return self._serve_file(self.server.data_path, cache_control="no-store", send_body=send_body)

        if parsed.path.startswith("/store/"):
            rel = _safe_relative_store_path(parsed.path)
            if rel is None:
                return self.send_error(403)
            store_root = self.server.store_root
            target = (self.server.project_root / rel).resolve()
            try:
                target.relative_to(store_root)
            except ValueError:
                return self.send_error(403)
            return self._serve_file(target, cache_control="max-age=3600", send_body=send_body)

        return self.send_error(404)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        # Keep script output concise while still allowing access logs if needed.
        return

    def _serve_file(self, path: Path, *, cache_control: str, send_body: bool) -> None:
        if not path.exists() or not path.is_file():
            return self.send_error(404)
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", _guess_mime(path))
        self.send_header("Cache-Control", cache_control)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if send_body:
            self.wfile.write(data)


def make_server(*, host: str, port: int, project_root: Path, data_path: Path) -> HTTPServer:
    server = HTTPServer((host, port), ExplorerHandler)
    server.project_root = project_root.resolve()
    server.store_root = (project_root.resolve() / "store").resolve()
    server.explorer_html_path = (project_root.resolve() / "tools" / "cluster_explorer.html").resolve()
    server.data_path = data_path.resolve()
    return server


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve Cluster Explorer over local HTTP")
    parser.add_argument("--host", default="127.0.0.1", help="Host bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8080, help="Port (default: 8080)")
    parser.add_argument("--data", default="tools/cluster_data.json", help="Cluster JSON file path")
    parser.add_argument("--project-root", default=str(REPO_ROOT), help="Project root path")
    return parser.parse_args()


def resolve_arg_path(base: Path, raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute():
        return path
    return (base / path).resolve()


def main() -> int:
    args = parse_args()
    project_root = Path(args.project_root).resolve()
    data_path = resolve_arg_path(project_root, args.data)

    server = make_server(
        host=args.host,
        port=args.port,
        project_root=project_root,
        data_path=data_path,
    )
    url = f"http://{args.host}:{args.port}"
    print(f"Serving Cluster Explorer at {url}")
    print(f"Data: {data_path}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
