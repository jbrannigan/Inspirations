from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .db import Db, ensure_schema
from .store import (
    add_items_to_collection,
    create_annotation,
    create_collection,
    delete_annotation,
    list_annotations,
    list_assets,
    list_collection_items,
    list_collections,
    remove_item_from_collection,
    set_collection_order,
    update_annotation,
)


MAX_BODY = 2_000_000


def _json_body(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0") or "0")
    if length > MAX_BODY:
        raise ValueError("Body too large")
    raw = handler.rfile.read(length) if length else b"{}"
    return json.loads(raw.decode("utf-8") or "{}")


def _send(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    data = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


class ApiHandler(BaseHTTPRequestHandler):
    server_version = "Inspirations/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            return self._serve_file("index.html", "text/html")
        if parsed.path.startswith("/app/"):
            rel = parsed.path[len("/app/") :]
            return self._serve_file(rel, _guess_mime(parsed.path))

        if parsed.path == "/api/assets":
            q = parse_qs(parsed.query)
            assets = self._with_db(
                list_assets,
                q=q.get("q", [""])[0],
                source=q.get("source", [""])[0],
                collection_id=q.get("collection_id", [""])[0],
                limit=int(q.get("limit", ["200"])[0]),
                offset=int(q.get("offset", ["0"])[0]),
            )
            return _send(self, 200, {"assets": assets})

        if parsed.path == "/api/collections":
            cols = self._with_db(list_collections)
            return _send(self, 200, {"collections": cols})

        m = re.match(r"^/api/collections/([^/]+)/items$", parsed.path)
        if m:
            items = self._with_db(list_collection_items, collection_id=m.group(1))
            return _send(self, 200, {"items": items})

        m = re.match(r"^/api/annotations$", parsed.path)
        if m:
            q = parse_qs(parsed.query)
            asset_id = q.get("asset_id", [""])[0]
            anns = self._with_db(list_annotations, asset_id=asset_id)
            return _send(self, 200, {"annotations": anns})

        self.send_error(404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            body = _json_body(self)
        except Exception as e:
            return _send(self, 400, {"error": str(e)})

        if parsed.path == "/api/collections":
            name = (body.get("name") or "").strip()
            if not name:
                return _send(self, 400, {"error": "name required"})
            desc = (body.get("description") or "").strip()
            col = self._with_db(create_collection, name=name, description=desc)
            return _send(self, 201, {"collection": col})

        m = re.match(r"^/api/collections/([^/]+)/items$", parsed.path)
        if m:
            asset_ids = body.get("asset_ids") or []
            if not isinstance(asset_ids, list):
                return _send(self, 400, {"error": "asset_ids must be list"})
            n = self._with_db(add_items_to_collection, collection_id=m.group(1), asset_ids=asset_ids)
            return _send(self, 200, {"added": n})

        m = re.match(r"^/api/collections/([^/]+)/order$", parsed.path)
        if m:
            asset_ids = body.get("asset_ids") or []
            if not isinstance(asset_ids, list):
                return _send(self, 400, {"error": "asset_ids must be list"})
            self._with_db(set_collection_order, collection_id=m.group(1), asset_ids=asset_ids)
            return _send(self, 200, {"ok": True})

        if parsed.path == "/api/annotations":
            asset_id = (body.get("asset_id") or "").strip()
            x = body.get("x")
            y = body.get("y")
            if not asset_id or x is None or y is None:
                return _send(self, 400, {"error": "asset_id, x, y required"})
            ann = self._with_db(create_annotation, asset_id=asset_id, x=float(x), y=float(y), text=body.get("text") or "")
            return _send(self, 201, {"annotation": ann})

        self.send_error(404)

    def do_PUT(self) -> None:
        parsed = urlparse(self.path)
        try:
            body = _json_body(self)
        except Exception as e:
            return _send(self, 400, {"error": str(e)})

        m = re.match(r"^/api/annotations/([^/]+)$", parsed.path)
        if m:
            self._with_db(
                update_annotation,
                annotation_id=m.group(1),
                x=body.get("x"),
                y=body.get("y"),
                text=body.get("text"),
            )
            return _send(self, 200, {"ok": True})
        self.send_error(404)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        m = re.match(r"^/api/collections/([^/]+)/items/([^/]+)$", parsed.path)
        if m:
            self._with_db(remove_item_from_collection, collection_id=m.group(1), asset_id=m.group(2))
            return _send(self, 200, {"ok": True})
        m = re.match(r"^/api/annotations/([^/]+)$", parsed.path)
        if m:
            self._with_db(delete_annotation, annotation_id=m.group(1))
            return _send(self, 200, {"ok": True})
        self.send_error(404)

    def _with_db(self, fn, **kwargs):
        with Db(self.server.db_path) as db:
            ensure_schema(db)
            return fn(db, **kwargs)

    def _serve_file(self, rel: str, mime: str) -> None:
        base = Path(self.server.app_dir).resolve()
        target = (base / rel).resolve()
        if not str(target).startswith(str(base)):
            return self.send_error(403)
        if not target.exists() or not target.is_file():
            return self.send_error(404)
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _guess_mime(path: str) -> str:
    if path.endswith(".js"):
        return "application/javascript"
    if path.endswith(".css"):
        return "text/css"
    if path.endswith(".html"):
        return "text/html"
    if path.endswith(".svg"):
        return "image/svg+xml"
    return "application/octet-stream"


def run_server(*, host: str, port: int, db_path: Path, app_dir: Path) -> None:
    server = HTTPServer((host, port), ApiHandler)
    server.db_path = db_path
    server.app_dir = app_dir
    print(f"Serving on http://{host}:{port}")
    server.serve_forever()
