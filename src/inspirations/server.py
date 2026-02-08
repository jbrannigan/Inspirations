from __future__ import annotations

import json
import os
import re
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .db import Db, ensure_schema
from .store import (
    add_items_to_collection,
    create_annotation,
    create_collection,
    delete_annotation,
    delete_assets,
    list_annotations,
    list_assets,
    list_collection_items,
    list_collections,
    delete_collection,
    list_facets,
    list_tray,
    add_to_tray,
    remove_from_tray,
    clear_tray,
    create_collection_from_tray,
    remove_item_from_collection,
    remove_items_from_collection,
    set_collection_order,
    update_annotation,
    update_asset_notes,
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
        m = re.match(r"^/media/([^/]+)$", parsed.path)
        if m:
            asset_id = m.group(1)
            q = parse_qs(parsed.query)
            kind = q.get("kind", ["thumb"])[0]
            return self._serve_media(asset_id, kind)

        if parsed.path == "/api/assets":
            q = parse_qs(parsed.query)
            assets = self._with_db(
                list_assets,
                q=q.get("q", [""])[0],
                source=q.get("source", [""])[0],
                board=q.get("board", [""])[0],
                label=q.get("label", [""])[0],
                collection_id=q.get("collection_id", [""])[0],
                limit=int(q.get("limit", ["200"])[0]),
                offset=int(q.get("offset", ["0"])[0]),
            )
            return _send(self, 200, {"assets": assets})

        if parsed.path == "/api/collections":
            cols = self._with_db(list_collections)
            return _send(self, 200, {"collections": cols})

        if parsed.path == "/api/facets":
            facets = self._with_db(list_facets)
            return _send(self, 200, {"facets": facets})

        if parsed.path == "/api/tray":
            items = self._with_db(list_tray)
            return _send(self, 200, {"items": items})

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

        if parsed.path == "/api/tray/add":
            asset_ids = body.get("asset_ids") or []
            if not isinstance(asset_ids, list):
                return _send(self, 400, {"error": "asset_ids must be list"})
            n = self._with_db(add_to_tray, asset_ids=asset_ids)
            return _send(self, 200, {"added": n})

        if parsed.path == "/api/tray/remove":
            asset_ids = body.get("asset_ids") or []
            if not isinstance(asset_ids, list):
                return _send(self, 400, {"error": "asset_ids must be list"})
            self._with_db(remove_from_tray, asset_ids=asset_ids)
            return _send(self, 200, {"ok": True})

        if parsed.path == "/api/tray/clear":
            self._with_db(clear_tray)
            return _send(self, 200, {"ok": True})

        if parsed.path == "/api/tray/create-collection":
            name = (body.get("name") or "").strip()
            if not name:
                return _send(self, 400, {"error": "name required"})
            desc = (body.get("description") or "").strip()
            col = self._with_db(create_collection_from_tray, name=name, description=desc)
            return _send(self, 201, {"collection": col})

        if parsed.path == "/api/admin/login":
            expected = self._admin_password()
            if not expected:
                return _send(
                    self,
                    503,
                    {
                        "error": (
                            "admin password not configured; set INSPIRATIONS_ADMIN_PASSWORD "
                            f"or create {self._admin_password_file()}"
                        )
                    },
                )
            password = (body.get("password") or "").strip()
            if password != expected:
                return _send(self, 403, {"error": "invalid admin password"})
            token = secrets.token_urlsafe(32)
            self.server.admin_tokens[token] = time.time() + 3600
            return _send(self, 200, {"token": token, "expires_in": 3600})

        if parsed.path == "/api/admin/logout":
            token = (self.headers.get("X-Admin-Token") or "").strip()
            if token:
                self.server.admin_tokens.pop(token, None)
            return _send(self, 200, {"ok": True})

        if parsed.path == "/api/admin/assets/delete":
            _token, token_error = self._require_admin_token()
            if token_error:
                return _send(self, 403, {"error": token_error})
            if body.get("admin_mode") is not True:
                return _send(self, 403, {"error": "admin_mode=true required"})
            confirm = (body.get("confirm") or "").strip()
            if confirm != "DELETE":
                return _send(self, 400, {"error": "confirm must be DELETE"})
            asset_ids = body.get("asset_ids") or []
            if not isinstance(asset_ids, list):
                return _send(self, 400, {"error": "asset_ids must be list"})
            try:
                backup_path = self._backup_primary_db()
            except Exception as e:
                return _send(self, 500, {"error": f"backup failed: {e}"})
            report = self._delete_assets_and_files(asset_ids)
            report["backup_path"] = backup_path
            return _send(self, 200, report)

        m = re.match(r"^/api/collections/([^/]+)/items/remove$", parsed.path)
        if m:
            asset_ids = body.get("asset_ids") or []
            if not isinstance(asset_ids, list):
                return _send(self, 400, {"error": "asset_ids must be list"})
            n = self._with_db(remove_items_from_collection, collection_id=m.group(1), asset_ids=asset_ids)
            return _send(self, 200, {"removed": n})

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

        m = re.match(r"^/api/assets/([^/]+)$", parsed.path)
        if m:
            notes = body.get("notes") or ""
            self._with_db(update_asset_notes, asset_id=m.group(1), notes=notes)
            return _send(self, 200, {"ok": True})

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
        if parsed.path == "/api/assets" or re.match(r"^/api/assets/([^/]+)$", parsed.path):
            return _send(self, 403, {"error": "Use POST /api/admin/assets/delete in admin mode"})
        if parsed.path == "/api/collections":
            try:
                body = _json_body(self)
            except Exception as e:
                return _send(self, 400, {"error": str(e)})
            cid = body.get("id") or ""
            if not cid:
                return _send(self, 400, {"error": "id required"})
            self._with_db(delete_collection, collection_id=cid)
            return _send(self, 200, {"ok": True})
        m = re.match(r"^/api/collections/([^/]+)$", parsed.path)
        if m:
            self._with_db(delete_collection, collection_id=m.group(1))
            return _send(self, 200, {"ok": True})
        m = re.match(r"^/api/collections/([^/]+)/items/([^/]+)$", parsed.path)
        if m:
            self._with_db(remove_item_from_collection, collection_id=m.group(1), asset_id=m.group(2))
            return _send(self, 200, {"ok": True})
        m = re.match(r"^/api/annotations/([^/]+)$", parsed.path)
        if m:
            self._with_db(delete_annotation, annotation_id=m.group(1))
            return _send(self, 200, {"ok": True})
        self.send_error(404)

    def _delete_assets_and_files(self, asset_ids: list[str]) -> dict:
        report = self._with_db(delete_assets, asset_ids=asset_ids)
        files_deleted = self._delete_media_paths(report.get("paths") or [])
        return {"deleted": int(report.get("deleted") or 0), "files_deleted": files_deleted}

    def _admin_password_file(self) -> Path:
        return Path(self.server.db_path).resolve().parent / "admin_password.txt"

    def _admin_password(self) -> str:
        env_pw = (os.environ.get("INSPIRATIONS_ADMIN_PASSWORD") or "").strip()
        if env_pw:
            return env_pw
        pw_file = self._admin_password_file()
        if pw_file.exists():
            return (pw_file.read_text(encoding="utf-8") or "").strip()
        return ""

    def _require_admin_token(self) -> tuple[str | None, str | None]:
        token = (self.headers.get("X-Admin-Token") or "").strip()
        if not token:
            return None, "missing admin token"
        expires_at = self.server.admin_tokens.get(token)
        if expires_at is None:
            return None, "invalid admin token"
        now = time.time()
        if expires_at < now:
            self.server.admin_tokens.pop(token, None)
            return None, "admin token expired"
        self.server.admin_tokens[token] = now + 3600
        return token, None

    def _backup_primary_db(self) -> str:
        db_path = Path(self.server.db_path).resolve()
        with Db(db_path) as db:
            ensure_schema(db)
        backups_dir = db_path.parent / "backups"
        backups_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
        backup_path = backups_dir / f"{db_path.stem}-backup-{stamp}.sqlite"
        src = sqlite3.connect(db_path)
        try:
            dst = sqlite3.connect(backup_path)
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
        return str(backup_path)

    def _delete_media_paths(self, paths: list[str]) -> int:
        base = Path(self.server.store_dir).resolve()
        deleted = 0
        seen: set[str] = set()
        for raw in paths:
            p = (raw or "").strip()
            if not p:
                continue
            try:
                target = Path(p).resolve()
                target_key = str(target)
                if target_key in seen:
                    continue
                seen.add(target_key)
                target.relative_to(base)
            except Exception:
                continue
            try:
                if target.exists() and target.is_file():
                    target.unlink()
                    deleted += 1
            except OSError:
                # best-effort cleanup: DB records are already removed
                continue
        return deleted

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

    def _serve_media(self, asset_id: str, kind: str) -> None:
        kind = kind if kind in ("thumb", "original") else "thumb"
        with Db(self.server.db_path) as db:
            ensure_schema(db)
            row = db.query(
                "select id, stored_path, thumb_path from assets where id=?",
                (asset_id,),
            )
            if not row:
                return self.send_error(404)
            r = row[0]
            path = r["thumb_path"] if kind == "thumb" else r["stored_path"]
            if not path:
                return self.send_error(404)
            base = Path(self.server.store_dir).resolve()
            target = Path(path).resolve()
            if not str(target).startswith(str(base)):
                return self.send_error(403)
            if not target.exists() or not target.is_file():
                return self.send_error(404)
            data = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", _guess_mime(str(target)))
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


def run_server(*, host: str, port: int, db_path: Path, app_dir: Path, store_dir: Path) -> None:
    server = HTTPServer((host, port), ApiHandler)
    server.db_path = db_path
    server.app_dir = app_dir
    server.store_dir = store_dir
    server.admin_tokens = {}
    print(f"Serving on http://{host}:{port}")
    server.serve_forever()
