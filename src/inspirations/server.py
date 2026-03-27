from __future__ import annotations

import json
import gzip
import mimetypes
import os
import re
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from email.parser import BytesParser
from email.policy import default as email_policy_default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .ai import DEFAULT_GEMINI_EMBEDDING_MODEL, run_similarity_search
from .chat import process_chat_message
from .db import Db, ensure_schema
from .importers.scans import import_photos_inbox, import_scans_inbox, import_videos_inbox
from .store import (
    add_items_to_collection,
    bulk_set_flag,
    bulk_set_tag,
    bulk_set_triage_status,
    create_actor,
    create_annotation,
    create_collection,
    delete_actor,
    delete_annotation,
    delete_assets,
    get_actor_by_token,
    hidden_tree,
    list_actors,
    list_annotations,
    list_asset_ids,
    list_asset_labels,
    list_assets,
    list_collection_items,
    list_collections,
    delete_collection,
    list_facets,
    list_open_questions,
    list_tray,
    add_to_tray,
    remove_from_tray,
    clear_tray,
    create_collection_from_tray,
    remove_item_from_collection,
    remove_items_from_collection,
    rollback_triage_since,
    set_collection_order,
    set_triage_status,
    triage_stats,
    update_annotation,
    update_asset_notes,
)
from .explorer_layout import compute_layout
from .feature_vectors import build_feature_vectors
from .thumbnails import generate_thumbnails


BASE_PATH = os.environ.get("BASE_PATH", "").strip().rstrip("/")

MAX_BODY = 2_000_000
MAX_UPLOAD_BODY = 350_000_000
DEFAULT_ASSETS_PAGE_SIZE = 240
MAX_SCAN_DOC_GROUP_PAGES = 6
VIDEO_UPLOAD_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv", ".mpeg", ".mpg", ".wmv", ".3gp"}
SCAN_DOC_TITLE_SUFFIX_RE = re.compile(r"(\s-\sdoc\s+\d+(?:\s+p\d+)?)\s*$", re.IGNORECASE)

# ── API key helpers ──────────────────────────────────────────────────────────────

_keychain_cache: dict[str, str] = {}


def _keychain_get(service: str) -> str:
    """Read a password from macOS Keychain (cached)."""
    if service in _keychain_cache:
        return _keychain_cache[service]
    try:
        val = subprocess.check_output(
            ["security", "find-generic-password", "-s", service, "-w"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        val = ""
    _keychain_cache[service] = val
    return val


def _get_api_key(env_var: str, keychain_service: str) -> str:
    """Return API key from env-var first, then macOS Keychain fallback."""
    val = (os.environ.get(env_var) or "").strip()
    if val:
        return val
    return _keychain_get(keychain_service)


def _parse_bool_param(raw: str, *, default: bool = False) -> bool:
    text = (raw or "").strip().lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _json_body(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0") or "0")
    if length > MAX_BODY:
        raise ValueError("Body too large")
    raw = handler.rfile.read(length) if length else b"{}"
    return json.loads(raw.decode("utf-8") or "{}")


def _parse_ingest_tags(raw: str) -> list[str]:
    return _dedupe_ingest_tags(re.split(r"[,\n;]+", str(raw or "")))


def _dedupe_ingest_tags(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for chunk in values:
        tag = chunk.strip()
        if not tag:
            continue
        key = tag.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(tag[:120])
    return out


def _ingest_actor_tag(actor: dict | None) -> str:
    raw_name = str((actor or {}).get("name") or "")
    cleaned = re.sub(r"\s+", " ", raw_name).strip()
    return f"actor:{cleaned or 'unknown'}"


def _ingest_time_tag(imported_at: str) -> str:
    stamp = str(imported_at or "").strip() or datetime.now(timezone.utc).isoformat()
    return f"ingested_at:{stamp}"


def _multipart_form(handler: BaseHTTPRequestHandler, *, max_body: int) -> tuple[dict[str, str], dict[str, dict[str, object]]]:
    content_type = (handler.headers.get("Content-Type") or "").strip()
    if not content_type.lower().startswith("multipart/form-data"):
        raise ValueError("Content-Type must be multipart/form-data")
    length = int(handler.headers.get("Content-Length", "0") or "0")
    if length <= 0:
        raise ValueError("Body required")
    if length > max_body:
        raise ValueError("Body too large")
    raw = handler.rfile.read(length)
    wrapped = b"Content-Type: " + content_type.encode("utf-8") + b"\r\nMIME-Version: 1.0\r\n\r\n" + raw
    message = BytesParser(policy=email_policy_default).parsebytes(wrapped)
    if not message.is_multipart():
        raise ValueError("Invalid multipart body")
    fields: dict[str, str] = {}
    files: dict[str, dict[str, object]] = {}
    for part in message.iter_parts():
        name = (part.get_param("name", header="content-disposition") or "").strip()
        if not name:
            continue
        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""
        if filename is None:
            charset = part.get_content_charset() or "utf-8"
            fields[name] = payload.decode(charset, errors="replace")
            continue
        files[name] = {
            "filename": filename,
            "content_type": part.get_content_type(),
            "data": payload,
        }
    return fields, files


def _send(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    raw = json.dumps(payload).encode("utf-8")
    wants_gzip = "gzip" in (handler.headers.get("Accept-Encoding") or "").lower()
    use_gzip = wants_gzip and len(raw) >= 1024
    data = gzip.compress(raw, compresslevel=6) if use_gzip else raw
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    # API responses should always be fresh to avoid stale UI state.
    handler.send_header("Cache-Control", "no-store")
    if use_gzip:
        handler.send_header("Content-Encoding", "gzip")
        handler.send_header("Vary", "Accept-Encoding")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    if handler.command != "HEAD":
        handler.wfile.write(data)


def _resolve_actor(handler: BaseHTTPRequestHandler) -> dict | None:
    """Resolve actor from X-Actor-Token header or ?actor= query param."""
    token = (handler.headers.get("X-Actor-Token") or "").strip()
    if not token:
        parsed = urlparse(handler.path)
        q = parse_qs(parsed.query)
        token = (q.get("actor", [""])[0] or "").strip()
    if not token:
        return None
    with Db(handler.server.db_path) as db:
        ensure_schema(db)
        return get_actor_by_token(db, token=token)


class ApiHandler(BaseHTTPRequestHandler):
    server_version = "Inspirations/0.1"
    protocol_version = "HTTP/1.1"

    def _strip_base_path(self) -> None:
        """Strip BASE_PATH prefix from self.path so routing works unchanged."""
        if BASE_PATH and self.path.startswith(BASE_PATH):
            self.path = self.path[len(BASE_PATH):] or "/"

    def do_HEAD(self) -> None:
        self._strip_base_path()
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            return self._serve_file("index.html", "text/html", cache_control="no-cache")
        if parsed.path.startswith("/app/"):
            rel = parsed.path[len("/app/") :]
            cache_control = self._app_cache_control(rel=rel, query=parsed.query)
            return self._serve_file(rel, _guess_mime(parsed.path), cache_control=cache_control)
        if parsed.path.startswith("/store/"):
            rel = parsed.path[len("/store/") :]
            return self._serve_store_file(rel, _guess_mime(parsed.path), cache_control="public, max-age=3600")
        if parsed.path == "/tools/cluster_explorer.html":
            tool = self._project_root() / "tools" / "cluster_explorer.html"
            return self._serve_path(tool, "text/html", cache_control="no-cache")
        m = re.match(r"^/media/([^/]+)$", parsed.path)
        if m:
            asset_id = m.group(1)
            q = parse_qs(parsed.query)
            kind = q.get("kind", ["thumb"])[0]
            return self._serve_media(asset_id, kind)
        if parsed.path.startswith("/api/"):
            # Reuse GET routing for API HEAD responses; _send omits body for HEAD.
            return self.do_GET()
        return self.send_error(404)

    def do_GET(self) -> None:
        self._strip_base_path()
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            return self._serve_file("index.html", "text/html", cache_control="no-cache")
        if parsed.path.startswith("/app/"):
            rel = parsed.path[len("/app/") :]
            cache_control = self._app_cache_control(rel=rel, query=parsed.query)
            return self._serve_file(rel, _guess_mime(parsed.path), cache_control=cache_control)
        if parsed.path.startswith("/store/"):
            rel = parsed.path[len("/store/") :]
            return self._serve_store_file(rel, _guess_mime(parsed.path), cache_control="public, max-age=3600")
        if parsed.path == "/tools/cluster_explorer.html":
            tool = self._project_root() / "tools" / "cluster_explorer.html"
            return self._serve_path(tool, "text/html", cache_control="no-cache")
        m = re.match(r"^/media/([^/]+)$", parsed.path)
        if m:
            asset_id = m.group(1)
            q = parse_qs(parsed.query)
            kind = q.get("kind", ["thumb"])[0]
            return self._serve_media(asset_id, kind)
        if parsed.path == "/api/scan/doc-pdf":
            q = parse_qs(parsed.query)
            asset_id = (q.get("asset_id", [""])[0] or "").strip()
            if not asset_id:
                return _send(self, 400, {"error": "asset_id required"})
            return self._serve_scan_doc_pdf(asset_id)

        if parsed.path == "/api/assets":
            q = parse_qs(parsed.query)
            include_hidden_req = _parse_bool_param(q.get("include_hidden", [""])[0], default=False)
            actor = _resolve_actor(self)
            include_hidden = bool(include_hidden_req and actor and actor.get("role") == "owner")
            page_limit = int(q.get("limit", [str(DEFAULT_ASSETS_PAGE_SIZE)])[0])
            assets = self._with_db(
                list_assets,
                ids=q.get("ids", [""])[0],
                q=q.get("q", [""])[0],
                source=q.get("source", [""])[0],
                board=q.get("board", [""])[0],
                label=q.get("label", [""])[0],
                label_mode=q.get("label_mode", ["any"])[0],
                media_status=q.get("media_status", [""])[0],
                content_kind=q.get("content_kind", [""])[0],
                creator=q.get("creator", [""])[0],
                collection_id=q.get("collection_id", [""])[0],
                triage_status=q.get("triage_status", [""])[0],
                category=q.get("category", [""])[0],
                needs_annotation=_parse_bool_param(q.get("needs_annotation", [""])[0], default=False),
                flagged_only=_parse_bool_param(q.get("flagged", [""])[0], default=False),
                tagged_only=_parse_bool_param(q.get("tagged", [""])[0], default=False),
                include_hidden=include_hidden,
                limit=page_limit + 1,
                offset=int(q.get("offset", ["0"])[0]),
            )
            # Use pre-collapse row count when available (scan page collapse
            # can reduce the list below the SQL limit even when more rows exist).
            pre_collapse = assets[0].pop("_pre_collapse_count", len(assets)) if assets else 0
            for a in assets:
                a.pop("_pre_collapse_count", None)
            total_count = assets[0].pop("_total_count", None) if assets else 0
            for a in assets:
                a.pop("_total_count", None)
            has_more = pre_collapse > page_limit
            if has_more:
                assets = assets[:page_limit]
            return _send(self, 200, {"assets": assets, "has_more": has_more, "total": total_count})

        m = re.match(r"^/api/assets/([^/]+)$", parsed.path)
        if m:
            q = parse_qs(parsed.query)
            include_hidden_req = _parse_bool_param(q.get("include_hidden", [""])[0], default=False)
            actor = _resolve_actor(self)
            include_hidden = bool(include_hidden_req and actor and actor.get("role") == "owner")
            asset = self._with_db(
                self._get_asset_for_modal,
                asset_id=m.group(1),
                include_hidden=include_hidden,
            )
            if not asset:
                return self.send_error(404)
            return _send(self, 200, {"asset": asset})

        if parsed.path == "/api/asset-ids":
            q = parse_qs(parsed.query)
            include_hidden_req = _parse_bool_param(q.get("include_hidden", [""])[0], default=False)
            actor = _resolve_actor(self)
            include_hidden = bool(include_hidden_req and actor and actor.get("role") == "owner")
            ids = self._with_db(
                list_asset_ids,
                q=q.get("q", [""])[0],
                source=q.get("source", [""])[0],
                board=q.get("board", [""])[0],
                collection_id=q.get("collection_id", [""])[0],
                triage_status=q.get("triage_status", [""])[0],
                needs_annotation=_parse_bool_param(q.get("needs_annotation", [""])[0], default=False),
                flagged_only=_parse_bool_param(q.get("flagged", [""])[0], default=False),
                include_hidden=include_hidden,
            )
            return _send(self, 200, {"ids": ids})

        m = re.match(r"^/api/assets/([^/]+)/labels$", parsed.path)
        if m:
            labels = self._with_db(list_asset_labels, asset_id=m.group(1))
            return _send(self, 200, {"labels": labels})

        if parsed.path == "/api/search/similar":
            q = parse_qs(parsed.query)
            query_text = (q.get("q", [""])[0] or "").strip()
            if not query_text:
                return _send(self, 400, {"error": "q is required"})
            api_key = _get_api_key("GEMINI_API_KEY", "inspirations_gemini_api_key")
            if not api_key:
                return _send(self, 503, {"error": "GEMINI_API_KEY is required for semantic search"})
            source = (q.get("source", [""])[0] or "").strip()
            model = (q.get("model", [""])[0] or "").strip() or DEFAULT_GEMINI_EMBEDDING_MODEL
            limit_raw = (q.get("limit", ["25"])[0] or "25").strip()
            semantic_weight_raw = (q.get("semantic_weight", ["0.85"])[0] or "0.85").strip()
            lexical_weight_raw = (q.get("lexical_weight", ["0.15"])[0] or "0.15").strip()
            min_score_raw = (q.get("min_score", ["0.0"])[0] or "0.0").strip()
            try:
                limit = max(1, min(500, int(limit_raw)))
            except ValueError:
                return _send(self, 400, {"error": "limit must be integer"})
            try:
                semantic_weight = float(semantic_weight_raw)
            except ValueError:
                return _send(self, 400, {"error": "semantic_weight must be number"})
            try:
                lexical_weight = float(lexical_weight_raw)
            except ValueError:
                return _send(self, 400, {"error": "lexical_weight must be number"})
            try:
                min_score = float(min_score_raw)
            except ValueError:
                return _send(self, 400, {"error": "min_score must be number"})

            report = self._with_db(
                run_similarity_search,
                api_key=api_key,
                query=query_text,
                model=model,
                source=source,
                limit=limit,
                semantic_weight=semantic_weight,
                lexical_weight=lexical_weight,
                min_score=min_score,
            )
            return _send(self, 200, report)

        if parsed.path == "/api/collections":
            cols = self._with_db(list_collections)
            return _send(self, 200, {"collections": cols})

        if parsed.path == "/api/facets":
            q = parse_qs(parsed.query)
            facets = self._with_db(
                list_facets,
                source=q.get("source", [""])[0],
                media_status=q.get("media_status", [""])[0],
            )
            return _send(self, 200, {"facets": facets})

        if parsed.path == "/api/cluster/review":
            q = parse_qs(parsed.query)
            collection_id = (q.get("collection_id", [""])[0] or "").strip()
            board = (q.get("board", [""])[0] or "").strip()
            if not collection_id and not board:
                return _send(self, 400, {"error": "collection_id or board required"})
            include_neighbors_raw = (q.get("include_neighbors", ["0"])[0] or "0").strip()
            similarity_raw = (q.get("similarity_threshold", ["0.72"])[0] or "0.72").strip()
            max_neighbors_raw = (q.get("max_neighbors", ["6"])[0] or "6").strip()
            clusters = (q.get("clusters", ["auto"])[0] or "auto").strip()
            try:
                include_neighbors = max(0, int(include_neighbors_raw))
            except ValueError:
                return _send(self, 400, {"error": "include_neighbors must be integer"})
            try:
                similarity = float(similarity_raw)
            except ValueError:
                return _send(self, 400, {"error": "similarity_threshold must be number"})
            try:
                max_neighbors = max(1, int(max_neighbors_raw))
            except ValueError:
                return _send(self, 400, {"error": "max_neighbors must be integer"})
            if clusters not in {"auto", "none"}:
                try:
                    int(clusters)
                except ValueError:
                    return _send(self, 400, {"error": 'clusters must be "auto", "none", or integer'})

            try:
                payload = self._export_cluster_review_payload(
                    collection_id=collection_id,
                    board=board,
                    include_neighbors=include_neighbors,
                    similarity_threshold=similarity,
                    max_neighbors=max_neighbors,
                    clusters=clusters,
                )
            except Exception as e:
                return _send(self, 500, {"error": f"cluster review export failed: {e}"})
            return _send(self, 200, payload)

        if parsed.path == "/api/explorer/attractor-data":
            q = parse_qs(parsed.query)
            pca_dims = int((q.get("dims", ["2"])[0] or "2").strip())
            include_hidden_req = _parse_bool_param(q.get("include_hidden", [""])[0], default=False)
            actor = _resolve_actor(self)
            include_hidden = bool(include_hidden_req and actor and actor.get("role") == "owner")
            data_dir = Path(self.server.db_path).parent / "explorer_layouts"
            try:
                payload = self._with_db(
                    build_feature_vectors,
                    data_dir=data_dir,
                    dims=pca_dims,
                    include_hidden=include_hidden,
                )
            except Exception as e:
                return _send(self, 500, {"error": f"attractor data failed: {e}"})
            return _send(self, 200, payload)

        if parsed.path == "/api/explorer/layout":
            q = parse_qs(parsed.query)
            collection_id = (q.get("collection_id", [""])[0] or "").strip() or None
            method = (q.get("method", ["umap"])[0] or "umap").strip()
            refresh_raw = (q.get("refresh", ["false"])[0] or "false").strip().lower()
            refresh = refresh_raw in {"1", "true", "yes"}
            include_hidden_req = _parse_bool_param(q.get("include_hidden", [""])[0], default=False)
            actor = _resolve_actor(self)
            include_hidden = bool(include_hidden_req and actor and actor.get("role") == "owner")
            data_dir = Path(self.server.db_path).parent / "explorer_layouts"
            try:
                payload = self._with_db(
                    compute_layout,
                    data_dir=data_dir,
                    collection_id=collection_id,
                    method=method,
                    refresh=refresh,
                    include_hidden=include_hidden,
                )
            except Exception as e:
                return _send(self, 500, {"error": f"explorer layout failed: {e}"})
            return _send(self, 200, payload)

        if parsed.path == "/api/triage/stats":
            stats = self._with_db(triage_stats)
            return _send(self, 200, stats)

        if parsed.path == "/api/catalog/tree":
            catalog_dir = getattr(self.server, "catalog_dir", None)
            if not catalog_dir:
                return _send(self, 200, {"tree": []})
            try:
                tree = self._build_catalog_tree(Path(catalog_dir))
            except Exception:
                tree = []
            # Adjust counts to exclude hidden items
            try:
                self._adjust_tree_counts_for_hidden(tree)
            except Exception:
                pass
            return _send(self, 200, {"tree": tree})

        if parsed.path == "/api/catalog/items":
            # Load items by one or more catalog file paths.
            q = parse_qs(parsed.query)
            include_hidden_req = _parse_bool_param(q.get("include_hidden", [""])[0], default=False)
            actor = _resolve_actor(self)
            include_hidden = bool(include_hidden_req and actor and actor.get("role") == "owner")
            catalog_dir = getattr(self.server, "catalog_dir", None)
            file_params = [str(v or "").strip() for v in q.get("file", []) if str(v or "").strip()]
            if not catalog_dir or not file_params:
                return _send(self, 400, {"error": "file param required"})
            short_ids, err_status, err_msg = self._catalog_short_ids_for_files(Path(catalog_dir), file_params)
            if err_status:
                return _send(self, err_status, {"error": err_msg})
            if not short_ids:
                return _send(self, 200, {"assets": [], "has_more": False, "total": 0})
            ids_str = ",".join(short_ids)
            limit = int(q.get("limit", ["500"])[0])
            offset = int(q.get("offset", ["0"])[0])
            assets = self._with_db(
                list_assets,
                ids=ids_str,
                include_hidden=include_hidden,
                limit=limit + 1,
                offset=offset,
            )
            pre_collapse = assets[0].pop("_pre_collapse_count", len(assets)) if assets else 0
            for a in assets:
                a.pop("_pre_collapse_count", None)
            total_count = assets[0].pop("_total_count", None) if assets else 0
            for a in assets:
                a.pop("_total_count", None)
            has_more = pre_collapse > limit
            if has_more:
                assets = assets[:limit]
            return _send(self, 200, {"assets": assets, "has_more": has_more, "total": total_count})

        if parsed.path == "/api/catalog/asset-ids":
            q = parse_qs(parsed.query)
            include_hidden_req = _parse_bool_param(q.get("include_hidden", [""])[0], default=False)
            actor = _resolve_actor(self)
            include_hidden = bool(include_hidden_req and actor and actor.get("role") == "owner")
            catalog_dir = getattr(self.server, "catalog_dir", None)
            file_params = [str(v or "").strip() for v in q.get("file", []) if str(v or "").strip()]
            if not catalog_dir or not file_params:
                return _send(self, 400, {"error": "file param required"})
            short_ids, err_status, err_msg = self._catalog_short_ids_for_files(Path(catalog_dir), file_params)
            if err_status:
                return _send(self, err_status, {"error": err_msg})
            if not short_ids:
                return _send(self, 200, {"ids": []})
            ids = self._with_db(list_asset_ids, ids=",".join(short_ids), include_hidden=include_hidden)
            return _send(self, 200, {"ids": ids})

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

        if parsed.path == "/api/context/resolve":
            actor = _resolve_actor(self)
            if not actor:
                return _send(self, 401, {"error": "authentication required"})
            q = parse_qs(parsed.query)
            collection_id = (q.get("collection_id", [""])[0] or "").strip()
            item_id = (q.get("item_id", [""])[0] or "").strip()
            if not collection_id or not item_id:
                return _send(self, 400, {"error": "collection_id and item_id required"})
            report = self._with_db(
                self._resolve_context_link,
                collection_id=collection_id,
                item_id=item_id,
                actor_role=str(actor.get("role") or ""),
            )
            return _send(self, 200, report)

        if parsed.path == "/api/me":
            actor = _resolve_actor(self)
            return _send(self, 200, {"actor": actor})

        if parsed.path == "/api/actors":
            actor = _resolve_actor(self)
            if not actor or actor.get("role") != "owner":
                return _send(self, 403, {"error": "owner access required"})
            actors = self._with_db(list_actors)
            return _send(self, 200, {"actors": actors})

        if parsed.path == "/api/hidden/tree":
            actor = _resolve_actor(self)
            if not actor or actor.get("role") != "owner":
                return _send(self, 403, {"error": "owner access required"})
            tree = self._with_db(hidden_tree)
            return _send(self, 200, tree)

        if parsed.path == "/api/questions/dashboard":
            actor = _resolve_actor(self)
            if not actor or actor.get("role") != "owner":
                return _send(self, 403, {"error": "owner access required"})
            questions = self._with_db(list_open_questions)
            return _send(self, 200, {"questions": questions, "total": len(questions)})

        self.send_error(404)

    def do_POST(self) -> None:
        self._strip_base_path()
        parsed = urlparse(self.path)
        if parsed.path == "/api/import/scans":
            return self._handle_scan_pdf_upload()
        if parsed.path == "/api/import/photos":
            return self._handle_photo_upload()
        if parsed.path == "/api/import/videos":
            return self._handle_video_upload()
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
            if not secrets.compare_digest(password, expected):
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

        if parsed.path == "/api/assets/triage/bulk":
            ids = body.get("ids") or []
            status = body.get("status")
            reason = body.get("reason", "")
            if not isinstance(ids, list):
                return _send(self, 400, {"error": "ids must be list"})
            if status not in ("keeper", "hidden", None):
                return _send(self, 400, {"error": "status must be 'keeper', 'hidden', or null"})
            actor = _resolve_actor(self)
            actor_name = actor.get("name", "") if actor else ""
            count = self._with_db(
                bulk_set_triage_status, asset_ids=ids, status=status,
                reason=reason or "bulk triage (UI)", actor=actor_name or "ui",
            )
            return _send(self, 200, {"updated": count})

        if parsed.path == "/api/triage/rollback":
            actor = _resolve_actor(self)
            if not actor or actor.get("role") != "owner":
                return _send(self, 403, {"error": "owner role required"})
            since_iso = str(body.get("since_iso") or "").strip()
            days_ago_raw = body.get("days_ago")
            if not since_iso:
                if days_ago_raw is None:
                    return _send(self, 400, {"error": "since_iso or days_ago required"})
                try:
                    days_ago = int(days_ago_raw)
                except Exception:
                    return _send(self, 400, {"error": "days_ago must be integer"})
                if days_ago < 0 or days_ago > 3650:
                    return _send(self, 400, {"error": "days_ago must be between 0 and 3650"})
                since_iso = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()

            actor_name = str(actor.get("name") or "").strip() or "ui"
            report = self._with_db(
                rollback_triage_since,
                since_iso=since_iso,
                reason=body.get("reason", "") or f"owner rollback since {since_iso}",
                actor=actor_name,
            )
            report["since_iso"] = since_iso
            return _send(self, 200, report)

        if parsed.path == "/api/assets/flag/bulk":
            ids = body.get("ids") or []
            flagged = body.get("flagged", 1)
            if not isinstance(ids, list):
                return _send(self, 400, {"error": "ids must be list"})
            actor = _resolve_actor(self)
            actor_name = actor.get("name", "") if actor else ""
            count = self._with_db(
                bulk_set_flag,
                asset_ids=ids,
                flagged=1 if flagged else 0,
                flagged_by=actor_name,
            )
            return _send(self, 200, {"updated": count})

        m = re.match(r"^/api/assets/([^/]+)/triage$", parsed.path)
        if m:
            asset_id = m.group(1)
            status = body.get("status")
            needs_annotation = body.get("needs_annotation")
            if status not in ("keeper", "hidden", None):
                return _send(self, 400, {"error": "status must be 'keeper', 'hidden', or null"})
            actor = _resolve_actor(self)
            actor_name = actor.get("name", "") if actor else ""
            self._with_db(
                set_triage_status, asset_id=asset_id, status=status,
                needs_annotation=needs_annotation,
                reason=body.get("reason", "") or "triage (UI)", actor=actor_name or "ui",
            )
            return _send(self, 200, {"ok": True})

        m = re.match(r"^/api/assets/([^/]+)/flag$", parsed.path)
        if m:
            asset_id = m.group(1)
            flagged = body.get("flagged", 1)
            note = body.get("note", "")
            actor = _resolve_actor(self)
            actor_name = actor.get("name", "") if actor else ""
            self._with_db(
                lambda db: db.exec(
                    "update assets set flagged=?, flagged_by=?, flagged_note=? where id=?",
                    (1 if flagged else 0, actor_name, note, asset_id),
                )
            )
            return _send(self, 200, {"ok": True})

        if parsed.path == "/api/assets/tag/bulk":
            ids = body.get("ids") or []
            tagged = body.get("tagged", 1)
            if not isinstance(ids, list):
                return _send(self, 400, {"error": "ids must be list"})
            actor = _resolve_actor(self)
            actor_name = actor.get("name", "") if actor else ""
            count = self._with_db(
                bulk_set_tag,
                asset_ids=ids,
                tagged=1 if tagged else 0,
                tagged_by=actor_name,
            )
            return _send(self, 200, {"updated": count})

        m = re.match(r"^/api/assets/([^/]+)/tag$", parsed.path)
        if m:
            asset_id = m.group(1)
            tagged = body.get("tagged", 1)
            note = body.get("note", "")
            actor = _resolve_actor(self)
            actor_name = actor.get("name", "") if actor else ""
            self._with_db(
                lambda db: db.exec(
                    "update assets set tagged=?, tagged_by=?, tagged_note=? where id=?",
                    (1 if tagged else 0, actor_name, note, asset_id),
                )
            )
            return _send(self, 200, {"ok": True})

        m = re.match(r"^/api/assets/([^/]+)/hide$", parsed.path)
        if m:
            asset_id = m.group(1)
            cols = self._with_db(list_collections)
            hidden = None
            for c in cols:
                if (c.get("name") or "").strip().lower() == "hidden":
                    hidden = c
                    break
            if not hidden:
                hidden = self._with_db(
                    create_collection,
                    name="Hidden",
                    description="Items hidden from the main canvas",
                )
            self._with_db(add_items_to_collection, collection_id=hidden["id"], asset_ids=[asset_id])
            return _send(
                self,
                200,
                {"ok": True, "hidden_collection_id": hidden["id"], "hidden_collection_name": hidden["name"]},
            )

        if parsed.path == "/api/chat":
            user_message = (body.get("message") or "").strip()
            if not user_message:
                return _send(self, 400, {"error": "message required"})
            api_key = _get_api_key("ANTHROPIC_API_KEY", "inspirations_anthropic_api_key")
            if not api_key:
                return _send(self, 503, {"error": "Chat requires an Anthropic API key. Set ANTHROPIC_API_KEY."})
            try:
                catalog_dir = getattr(self.server, "catalog_dir", None)
                result = self._with_db(
                    process_chat_message,
                    api_key=api_key,
                    user_message=user_message,
                    catalog_dir=catalog_dir,
                )
                return _send(self, 200, result)
            except Exception as e:
                return _send(self, 500, {"error": f"Chat failed: {e}"})

        if parsed.path == "/api/annotations":
            asset_id = (body.get("asset_id") or "").strip()
            x = body.get("x")
            y = body.get("y")
            if not asset_id or x is None or y is None:
                return _send(self, 400, {"error": "asset_id, x, y required"})
            actor = _resolve_actor(self)
            annotation_type = (body.get("annotation_type") or "note").strip()
            if annotation_type not in ("note", "question"):
                annotation_type = "note"
            ann = self._with_db(
                create_annotation,
                asset_id=asset_id,
                x=float(x),
                y=float(y),
                text=body.get("text") or "",
                actor_id=actor["id"] if actor else None,
                actor_name=actor["name"] if actor else None,
                annotation_type=annotation_type,
            )
            # Fire-and-forget notification for questions
            if annotation_type == "question":
                _notify_question(actor, body.get("text") or "")
            return _send(self, 201, {"annotation": ann})

        if parsed.path == "/api/actors":
            actor = _resolve_actor(self)
            if not actor or actor.get("role") != "owner":
                return _send(self, 403, {"error": "owner access required"})
            name = (body.get("name") or "").strip()
            if not name:
                return _send(self, 400, {"error": "name required"})
            role = (body.get("role") or "collaborator").strip()
            if role not in ("owner", "collaborator"):
                role = "collaborator"
            new_actor = self._with_db(create_actor, name=name, role=role)
            return _send(self, 201, {"actor": new_actor})

        self.send_error(404)

    def _handle_scan_pdf_upload(self) -> None:
        try:
            fields, files = _multipart_form(self, max_body=MAX_UPLOAD_BODY)
        except Exception as e:
            return _send(self, 400, {"error": str(e)})

        split_on_delimiters_raw = str(fields.get("split_on_delimiters") or "1").strip().lower()
        split_on_delimiters = split_on_delimiters_raw not in {"0", "false", "off", "no"}
        use_form_parser_raw = str(fields.get("use_form_parser") or "0").strip().lower()
        use_form_parser = use_form_parser_raw in {"1", "true", "on", "yes"}
        title_override = str(fields.get("title") or "").strip()
        ingest_tags = _parse_ingest_tags(str(fields.get("tags") or ""))
        actor = _resolve_actor(self)

        upload = files.get("file") or {}
        filename = str(upload.get("filename") or "").strip()
        data = upload.get("data") or b""
        if not filename:
            return _send(self, 400, {"error": "file required"})
        if not filename.lower().endswith(".pdf"):
            return _send(self, 400, {"error": "file must be a .pdf"})
        if not isinstance(data, (bytes, bytearray)) or not data:
            return _send(self, 400, {"error": "uploaded file is empty"})

        cleaned_name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename).name).strip("._")
        if not cleaned_name:
            cleaned_name = "scan_upload.pdf"
        if not cleaned_name.lower().endswith(".pdf"):
            cleaned_name = f"{cleaned_name}.pdf"

        uploads_root = self._imports_root() / "scans" / "inbox" / "uploads"
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
        batch_dir = uploads_root / f"{stamp}-{secrets.token_hex(4)}"
        batch_dir.mkdir(parents=True, exist_ok=True)
        uploaded_path = batch_dir / cleaned_name
        uploaded_path.write_bytes(bytes(data))

        try:
            import_report = self._with_db(
                import_scans_inbox,
                inbox_dir=batch_dir,
                store_dir=Path(self.server.store_dir).resolve(),
                format="jpg",
                limit=0,
                max_pages=0,
                renderer="auto",
                split_on_delimiters=split_on_delimiters,
            )
            thumbs_report = self._with_db(
                generate_thumbnails,
                store_dir=Path(self.server.store_dir).resolve(),
                source="scan",
                size=512,
                limit=0,
                tool="auto",
            )
            imported_at = str(import_report.get("imported_at") or "")
            auto_tags = [
                _ingest_actor_tag(actor),
                _ingest_time_tag(imported_at),
            ]
            ingest_meta_report = self._with_db(
                self._apply_ingest_metadata,
                source="scan",
                imported_at=imported_at,
                title=title_override,
                tags=ingest_tags,
                auto_tags=auto_tags,
            )
        except Exception as e:
            return _send(self, 500, {"error": f"scan import failed: {e}"})

        return _send(
            self,
            200,
            {
                "ok": True,
                "uploaded_file": str(uploaded_path),
                "upload_size_bytes": len(data),
                "options": {
                    "split_on_delimiters": split_on_delimiters,
                    "use_form_parser": use_form_parser,
                    "title": title_override,
                    "tags": ingest_tags,
                    "auto_tags": auto_tags,
                },
                "import": import_report,
                "thumbs": thumbs_report,
                "ingest_metadata": ingest_meta_report,
            },
        )

    def _handle_photo_upload(self) -> None:
        try:
            fields, files = _multipart_form(self, max_body=MAX_UPLOAD_BODY)
        except Exception as e:
            return _send(self, 400, {"error": str(e)})

        title_override = str(fields.get("title") or "").strip()
        ingest_tags = _parse_ingest_tags(str(fields.get("tags") or ""))
        actor = _resolve_actor(self)

        upload = files.get("file") or {}
        filename = str(upload.get("filename") or "").strip()
        data = upload.get("data") or b""
        if not filename:
            return _send(self, 400, {"error": "file required"})
        ext = Path(filename).suffix.lower()
        if ext not in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".heic", ".heif", ".tif", ".tiff"}:
            return _send(self, 400, {"error": "file must be an image"})
        if not isinstance(data, (bytes, bytearray)) or not data:
            return _send(self, 400, {"error": "uploaded file is empty"})

        cleaned_name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename).name).strip("._")
        if not cleaned_name:
            cleaned_name = f"photo_upload{ext or '.jpg'}"

        uploads_root = self._imports_root() / "photos" / "inbox" / "uploads"
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
        batch_dir = uploads_root / f"{stamp}-{secrets.token_hex(4)}"
        batch_dir.mkdir(parents=True, exist_ok=True)
        uploaded_path = batch_dir / cleaned_name
        uploaded_path.write_bytes(bytes(data))

        try:
            import_report = self._with_db(
                import_photos_inbox,
                inbox_dir=batch_dir,
                store_dir=Path(self.server.store_dir).resolve(),
                limit=0,
                source="scan",
                content_kind="photo",
                source_ref_scheme="clip-photo",
            )
            thumbs_report = self._with_db(
                generate_thumbnails,
                store_dir=Path(self.server.store_dir).resolve(),
                source="scan",
                size=512,
                limit=0,
                tool="auto",
            )
            imported_at = str(import_report.get("imported_at") or "")
            auto_tags = [
                _ingest_actor_tag(actor),
                _ingest_time_tag(imported_at),
            ]
            ingest_meta_report = self._with_db(
                self._apply_ingest_metadata,
                source="scan",
                imported_at=imported_at,
                title=title_override,
                tags=ingest_tags,
                auto_tags=auto_tags,
            )
        except Exception as e:
            return _send(self, 500, {"error": f"photo import failed: {e}"})

        return _send(
            self,
            200,
            {
                "ok": True,
                "uploaded_file": str(uploaded_path),
                "upload_size_bytes": len(data),
                "import": import_report,
                "thumbs": thumbs_report,
                "options": {
                    "title": title_override,
                    "tags": ingest_tags,
                    "auto_tags": auto_tags,
                },
                "ingest_metadata": ingest_meta_report,
            },
        )

    def _handle_video_upload(self) -> None:
        try:
            fields, files = _multipart_form(self, max_body=MAX_UPLOAD_BODY)
        except Exception as e:
            return _send(self, 400, {"error": str(e)})

        title_override = str(fields.get("title") or "").strip()
        ingest_tags = _parse_ingest_tags(str(fields.get("tags") or ""))
        actor = _resolve_actor(self)

        upload = files.get("file") or {}
        filename = str(upload.get("filename") or "").strip()
        data = upload.get("data") or b""
        if not filename:
            return _send(self, 400, {"error": "file required"})
        ext = Path(filename).suffix.lower()
        if ext not in VIDEO_UPLOAD_EXTS:
            return _send(self, 400, {"error": "file must be a supported video"})
        if not isinstance(data, (bytes, bytearray)) or not data:
            return _send(self, 400, {"error": "uploaded file is empty"})

        cleaned_name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename).name).strip("._")
        if not cleaned_name:
            cleaned_name = f"video_upload{ext or '.mp4'}"

        uploads_root = self._imports_root() / "videos" / "inbox" / "uploads"
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
        batch_dir = uploads_root / f"{stamp}-{secrets.token_hex(4)}"
        batch_dir.mkdir(parents=True, exist_ok=True)
        uploaded_path = batch_dir / cleaned_name
        uploaded_path.write_bytes(bytes(data))

        try:
            import_report = self._with_db(
                import_videos_inbox,
                inbox_dir=batch_dir,
                store_dir=Path(self.server.store_dir).resolve(),
                limit=0,
                source="scan",
                content_kind="video",
                source_ref_scheme="clip-video",
            )
            imported_at = str(import_report.get("imported_at") or "")
            auto_tags = [
                _ingest_actor_tag(actor),
                _ingest_time_tag(imported_at),
            ]
            ingest_meta_report = self._with_db(
                self._apply_ingest_metadata,
                source="scan",
                imported_at=imported_at,
                title=title_override,
                tags=ingest_tags,
                auto_tags=auto_tags,
            )
        except Exception as e:
            return _send(self, 500, {"error": f"video import failed: {e}"})

        return _send(
            self,
            200,
            {
                "ok": True,
                "uploaded_file": str(uploaded_path),
                "upload_size_bytes": len(data),
                "import": import_report,
                "options": {
                    "title": title_override,
                    "tags": ingest_tags,
                    "auto_tags": auto_tags,
                },
                "ingest_metadata": ingest_meta_report,
            },
        )

    def do_PUT(self) -> None:
        self._strip_base_path()
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
            actor = _resolve_actor(self)
            if not actor:
                return _send(self, 401, {"error": "authentication required"})
            annotation_id = m.group(1)
            ann = self._with_db(self._annotation_record, annotation_id=annotation_id)
            if not ann:
                return _send(self, 404, {"error": "annotation not found"})
            resolved = body.get("resolved")
            if resolved is not None:
                if actor.get("role") != "owner":
                    return _send(self, 403, {"error": "owner access required to resolve questions"})
                resolved = int(resolved)
            if not self._can_manage_annotation(actor=actor, annotation=ann):
                return _send(self, 403, {"error": "not allowed to edit this annotation"})
            self._with_db(
                update_annotation,
                annotation_id=annotation_id,
                x=body.get("x"),
                y=body.get("y"),
                text=body.get("text"),
                resolved=resolved,
            )
            return _send(self, 200, {"ok": True})
        self.send_error(404)

    def do_DELETE(self) -> None:
        self._strip_base_path()
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
            actor = _resolve_actor(self)
            if not actor:
                return _send(self, 401, {"error": "authentication required"})
            annotation_id = m.group(1)
            ann = self._with_db(self._annotation_record, annotation_id=annotation_id)
            if not ann:
                return _send(self, 404, {"error": "annotation not found"})
            if not self._can_manage_annotation(actor=actor, annotation=ann):
                return _send(self, 403, {"error": "not allowed to delete this annotation"})
            self._with_db(delete_annotation, annotation_id=annotation_id)
            return _send(self, 200, {"ok": True})
        m = re.match(r"^/api/actors/([^/]+)$", parsed.path)
        if m:
            actor = _resolve_actor(self)
            if not actor or actor.get("role") != "owner":
                return _send(self, 403, {"error": "owner access required"})
            self._with_db(delete_actor, actor_id=m.group(1))
            return _send(self, 200, {"ok": True})
        self.send_error(404)

    def _delete_assets_and_files(self, asset_ids: list[str]) -> dict:
        report = self._with_db(delete_assets, asset_ids=asset_ids)
        files_deleted = self._delete_media_paths(report.get("paths") or [])
        return {"deleted": int(report.get("deleted") or 0), "files_deleted": files_deleted}

    def _admin_password_file(self) -> Path:
        return Path(self.server.db_path).resolve().parent / "admin_password.txt"

    def _imports_root(self) -> Path:
        configured = getattr(self.server, "imports_dir", None)
        if configured:
            return Path(configured).resolve()
        return Path(self.server.app_dir).resolve().parent / "imports"

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

    def _apply_ingest_metadata(
        self,
        db: Db,
        *,
        source: str,
        imported_at: str,
        title: str = "",
        tags: list[str] | None = None,
        auto_tags: list[str] | None = None,
    ) -> dict[str, int]:
        src = str(source or "").strip()
        stamp = str(imported_at or "").strip()
        tags = _dedupe_ingest_tags([*(tags or []), *(auto_tags or [])])
        if not src or not stamp or (not title and not tags):
            return {"updated_titles": 0, "applied_tags": 0}

        rows = db.query(
            "select id, source_ref, title from assets where source=? and imported_at=?",
            (src, stamp),
        )
        if not rows:
            return {"updated_titles": 0, "applied_tags": 0}

        updated_titles = 0
        if title:
            updates: list[tuple[str, str]] = []
            for row in rows:
                current_title = str(row["title"] or "").strip()
                source_ref = str(row["source_ref"] or "").strip()
                next_title = title
                m = SCAN_DOC_TITLE_SUFFIX_RE.search(current_title)
                if source_ref.startswith("scan://") and "#p" in source_ref and m:
                    next_title = f"{title}{m.group(1)}"
                if next_title != current_title:
                    updates.append((next_title, str(row["id"])))
            if updates:
                db.executemany("update assets set title=? where id=?", updates)
                updated_titles = len(updates)

        applied_tags = 0
        if tags:
            now = datetime.now(timezone.utc).isoformat()
            label_rows: list[tuple[str, str, str, float, str, str | None, str | None, str]] = []
            for row in rows:
                asset_id = str(row["id"])
                for tag in tags:
                    label_rows.append(
                        (
                            str(uuid.uuid4()),
                            asset_id,
                            tag,
                            1.0,
                            "owner-upload",
                            None,
                            None,
                            now,
                        )
                    )
            if label_rows:
                db.executemany(
                    """
                    insert or ignore into asset_labels
                      (id, asset_id, label, confidence, source, model, run_id, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    label_rows,
                )
                applied_tags = len(label_rows)

        return {"updated_titles": updated_titles, "applied_tags": applied_tags}

    def _resolve_context_link(
        self,
        db: Db,
        *,
        collection_id: str,
        item_id: str,
        actor_role: str,
    ) -> dict:
        collection_rows = db.query(
            "select id, name from collections where id = ? limit 1",
            (collection_id,),
        )
        if not collection_rows:
            return {
                "ok": True,
                "found": False,
                "collection_id": collection_id,
                "item_id": item_id,
                "reason": "collection_not_found",
            }

        collection_name = str(collection_rows[0]["name"] or "")
        in_collection = db.query_value(
            "select 1 from collection_items where collection_id = ? and asset_id = ? limit 1",
            (collection_id, item_id),
        )
        if not in_collection:
            return {
                "ok": True,
                "found": False,
                "collection_id": collection_id,
                "collection_name": collection_name,
                "item_id": item_id,
                "reason": "item_not_in_collection",
            }

        asset_rows = db.query(
            "select id, coalesce(triage_status, '') as triage_status from assets where id = ? limit 1",
            (item_id,),
        )
        if not asset_rows:
            return {
                "ok": True,
                "found": False,
                "collection_id": collection_id,
                "collection_name": collection_name,
                "item_id": item_id,
                "reason": "item_missing",
            }

        triage_status = str(asset_rows[0]["triage_status"] or "")
        is_hidden = triage_status == "hidden"
        if is_hidden and str(actor_role or "").strip().lower() != "owner":
            return {
                "ok": True,
                "found": False,
                "collection_id": collection_id,
                "collection_name": collection_name,
                "item_id": item_id,
                "reason": "item_hidden_for_role",
            }

        return {
            "ok": True,
            "found": True,
            "collection_id": collection_id,
            "collection_name": collection_name,
            "item_id": item_id,
            "item_hidden": bool(is_hidden),
        }

    def _annotation_record(self, db: Db, *, annotation_id: str) -> dict | None:
        rows = db.query(
            """
            select id, asset_id, actor_id, actor_name, annotation_type, resolved
            from annotations
            where id = ?
            limit 1
            """,
            (annotation_id,),
        )
        return dict(rows[0]) if rows else None

    def _can_manage_annotation(self, *, actor: dict | None, annotation: dict | None) -> bool:
        if not actor or not annotation:
            return False
        role = str(actor.get("role") or "").strip().lower()
        if role == "owner":
            return True
        actor_id = str(actor.get("id") or "").strip()
        ann_actor_id = str(annotation.get("actor_id") or "").strip()
        if not actor_id or not ann_actor_id:
            return False
        return actor_id == ann_actor_id

    def _catalog_short_ids_for_files(self, catalog_dir: Path, file_params: list[str]) -> tuple[list[str], int | None, str | None]:
        """Resolve catalog files safely and return unique 8-char asset prefixes."""
        root = catalog_dir.resolve()
        short_ids: list[str] = []
        seen_ids: set[str] = set()
        seen_files: set[str] = set()
        for raw in file_params:
            rel = str(raw or "").strip()
            if not rel or rel in seen_files:
                continue
            seen_files.add(rel)
            try:
                target = (root / rel).resolve()
                target.relative_to(root)
            except Exception:
                return [], 400, "invalid file path"
            if not target.exists() or not target.is_file():
                return [], 404, "catalog file not found"
            text = target.read_text(encoding="utf-8")
            for sid in re.findall(r"^- ([0-9a-f]{8}) \|", text, re.MULTILINE):
                if sid in seen_ids:
                    continue
                seen_ids.add(sid)
                short_ids.append(sid)
        return short_ids, None, None

    def _build_catalog_tree(self, catalog_dir: Path) -> list[dict]:
        """Build a tree structure from the catalog for the sidebar browser."""
        index_path = catalog_dir / "_index.md"
        if not index_path.exists():
            return []

        tree: list[dict] = []
        index_text = index_path.read_text(encoding="utf-8")

        # Known real sources (filter by actual source name in DB)
        real_sources = {"facebook", "houzz", "pinterest", "scan"}
        # Dimension sections identified by "By " prefix
        # "Other / Non-Home-Design" is also a dimension (hidden category)

        current_section = None  # current section node being populated
        current_section_type = None  # "source" | "dimension"
        in_collections = False
        in_triage = False

        for line in index_text.splitlines():
            line = line.strip()

            # Triage section — stop processing
            if line.startswith("## Triage"):
                current_section = None
                current_section_type = None
                in_triage = True
                continue
            if in_triage:
                continue

            # Collections header
            if line == "## Collections":
                current_section = None
                current_section_type = None
                in_collections = True
                continue

            # Collection item: - "Name" (N items, id=...)
            if in_collections and line.startswith("- \"") and "id=" in line:
                name_match = re.match(r'^- "(.+?)"\s+\((\d+)\s+items?,\s+id=([^)]+)\)', line)
                if name_match:
                    cname = name_match.group(1)
                    ccount = int(name_match.group(2))
                    cid = name_match.group(3)
                    if not tree or tree[-1].get("type") != "collections_group":
                        tree.append({
                            "id": "collections",
                            "label": "Collections",
                            "count": 0,
                            "type": "collections_group",
                            "children": [],
                        })
                    collections_node = tree[-1]
                    collections_node["children"].append({
                        "id": f"collection:{cid}",
                        "label": cname,
                        "count": ccount,
                        "type": "collection",
                        "collection_id": cid,
                    })
                    collections_node["count"] = len(collections_node["children"])
                continue

            # Section header: ## Facebook (1190 items) or ## By Room (5257 item-assignments)
            if line.startswith("## ") and "(" in line:
                in_collections = False
                name = line[3:].strip()
                count_match = re.search(r"\((\d+)\s+item", name)
                count = int(count_match.group(1)) if count_match else 0
                section_name = name.split("(")[0].strip()

                # Determine if this is a real source or a dimension
                section_lower = section_name.lower()
                if section_lower in real_sources:
                    current_section_type = "source"
                    node_type = "source"
                    node_id = f"source:{section_lower}"
                else:
                    current_section_type = "dimension"
                    node_type = "dimension"
                    # Normalize dimension name: "By Room" → "room", "Other / Non-Home-Design" → "other"
                    dim_key = section_lower.replace("by ", "").split("/")[0].strip()
                    node_id = f"dimension:{dim_key}"

                current_section = {
                    "id": node_id,
                    "label": section_name,
                    "count": count,
                    "type": node_type,
                    "children": [],
                }
                tree.append(current_section)
                continue

            # Table row: | path | category | count | topics |
            if line.startswith("|") and current_section is not None:
                parts = [p.strip() for p in line.split("|")]
                if len(parts) < 5 or parts[1].startswith("File") or parts[1].startswith("---"):
                    continue
                file_path = parts[1]
                category = parts[2]
                try:
                    item_count = int(parts[3])
                except (ValueError, IndexError):
                    item_count = 0
                # Clean up category display
                display = category.replace("-", " ").replace("_", " ").title()

                child = {
                    "label": display,
                    "count": item_count,
                    "file": file_path,
                }

                if current_section_type == "source":
                    child["id"] = f"board:{file_path}"
                    child["type"] = "board"
                    child["source"] = current_section["label"].lower()
                    child["board_name"] = category  # original board name from DB
                else:
                    child["id"] = f"dim:{file_path}"
                    child["type"] = "dimension_item"

                current_section["children"].append(child)
                continue

        return tree

    def _adjust_tree_counts_for_hidden(self, tree: list[dict]) -> None:
        """Adjust browse-tree counts so they reflect only visible items.

        CONTRACT: every tree node with count > 0 must deliver items when
        clicked.  The count shown IS the number of items the user will see.
        If a source or board has zero visible items it is pruned from the
        tree entirely so the UI never promises items it cannot deliver.
        """
        with Db(self.server.db_path) as db:
            ensure_schema(db)
            # Visible (non-hidden) counts per source
            src_rows = db.query(
                "select lower(source) as src, count(*) as n "
                "from assets where triage_status is null or triage_status != 'hidden' "
                "group by 1"
            )
            # Visible counts per source+board (for boards that exist in DB)
            board_rows = db.query(
                "select lower(source) as src, lower(coalesce(board,'')) as brd, count(*) as n "
                "from assets where triage_status is null or triage_status != 'hidden' "
                "group by 1, 2"
            )
            # Visible counts per source+content_kind (for subtype browsing under Clip)
            kind_rows = db.query(
                "select lower(source) as src, lower(coalesce(content_kind,'')) as kind, count(*) as n "
                "from assets where triage_status is null or triage_status != 'hidden' "
                "group by 1, 2"
            )
        visible_by_source: dict[str, int] = {r["src"]: r["n"] for r in src_rows}
        visible_by_board: dict[tuple[str, str], int] = {
            (r["src"], r["brd"]): r["n"] for r in board_rows
        }
        visible_by_kind: dict[tuple[str, str], int] = {
            (r["src"], r["kind"]): r["n"] for r in kind_rows
        }

        for node in tree:
            if node.get("type") != "source":
                continue
            src = node["label"].lower()
            # Default to 0: if a source has no visible items at all it won't
            # appear in the query results, but we must still zero-out its
            # count so the pruning step below removes it from the tree.
            visible_total = visible_by_source.get(src, 0)
            # Set source-level count to visible total
            node["count"] = visible_total
            # Adjust known board children
            accounted = 0
            synthetic_children = []  # children that aggregate multiple DB boards
            board_children = [c for c in node.get("children", []) if c.get("type") == "board"]
            for child in board_children:
                board_name = (child.get("board_name") or "").lower()
                # Synthetic groups like "(unsorted reels)" aggregate many DB boards
                if board_name.startswith("("):
                    synthetic_children.append(child)
                    continue
                vis = visible_by_board.get((src, board_name), 0)
                child["count"] = vis
                accounted += vis
            # Distribute remaining visible items across synthetic groups proportionally
            remaining = visible_total - accounted
            if synthetic_children and remaining >= 0:
                old_total = sum(c["count"] for c in synthetic_children) or 1
                for child in synthetic_children:
                    child["count"] = max(0, round(remaining * child["count"] / old_total))
            # Remove zero-count board children (all items hidden)
            board_children = [c for c in board_children if c.get("count", 0) > 0]

            # JIM-2: expose Clip subtype branches under source=scan.
            if src == "scan":
                scan_count = visible_by_kind.get((src, "scan"), 0) + visible_by_kind.get((src, ""), 0)
                photo_count = visible_by_kind.get((src, "photo"), 0)
                video_count = visible_by_kind.get((src, "video"), 0)
                known_total = scan_count + photo_count + video_count
                # Keep subtype totals aligned with visible source count even if
                # legacy rows use unexpected content_kind values.
                if known_total < visible_total:
                    scan_count += visible_total - known_total
                subtype_children = [
                    {
                        "id": "source_subtype:scan:scan",
                        "label": "Scan",
                        "count": scan_count,
                        "type": "source_subtype",
                        "source": "scan",
                        "content_kind": "scan",
                    },
                    {
                        "id": "source_subtype:scan:photo",
                        "label": "Photo",
                        "count": photo_count,
                        "type": "source_subtype",
                        "source": "scan",
                        "content_kind": "photo",
                    },
                    {
                        "id": "source_subtype:scan:video",
                        "label": "Video",
                        "count": video_count,
                        "type": "source_subtype",
                        "source": "scan",
                        "content_kind": "video",
                    },
                ]
                node["children"] = [c for c in subtype_children if c["count"] > 0] + board_children
            else:
                node["children"] = board_children

        # Remove zero-count source nodes (all items hidden)
        tree[:] = [n for n in tree if n.get("type") != "source" or n["count"] > 0]

    def _project_root(self) -> Path:
        return Path(self.server.app_dir).resolve().parent

    def _app_cache_control(self, *, rel: str, query: str) -> str:
        rel_l = rel.lower()
        if rel_l.endswith(".html"):
            return "no-cache"
        if rel_l.endswith((".js", ".mjs", ".css", ".svg", ".woff", ".woff2", ".ttf", ".otf")):
            q = parse_qs(query)
            if "v" in q:
                return "public, max-age=31536000, immutable"
            return "public, max-age=300"
        return "public, max-age=3600"

    def _can_gzip_mime(self, mime: str) -> bool:
        m = (mime or "").split(";")[0].strip().lower()
        return m.startswith("text/") or m in {
            "application/javascript",
            "application/json",
            "application/xml",
            "application/xhtml+xml",
            "image/svg+xml",
        }

    def _serve_path(self, target: Path, mime: str, *, cache_control: str = "no-store") -> None:
        if not target.exists() or not target.is_file():
            return self.send_error(404)
        raw = target.read_bytes()
        data = raw
        wants_gzip = "gzip" in (self.headers.get("Accept-Encoding") or "").lower()
        use_gzip = wants_gzip and len(raw) >= 1024 and self._can_gzip_mime(mime)
        if use_gzip:
            data = gzip.compress(raw, compresslevel=6)
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Cache-Control", cache_control)
        if use_gzip:
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _serve_file(self, rel: str, mime: str, *, cache_control: str = "no-store") -> None:
        base = Path(self.server.app_dir).resolve()
        target = (base / rel).resolve()
        try:
            target.relative_to(base)
        except ValueError:
            return self.send_error(403)
        if BASE_PATH and rel == "index.html":
            return self._serve_index_with_base_path(target, cache_control=cache_control)
        return self._serve_path(target, mime, cache_control=cache_control)

    def _serve_index_with_base_path(self, target: Path, *, cache_control: str) -> None:
        if not target.exists() or not target.is_file():
            return self.send_error(404)
        html = target.read_text(encoding="utf-8")
        # Inject window.__BASE_PATH before the first script tag
        bp_script = f'<script>window.__BASE_PATH="{BASE_PATH}"</script>\n'
        html = html.replace("<head>\n", f"<head>\n    {bp_script}", 1)
        # Rewrite absolute asset paths to include the base path
        html = html.replace('href="/app/', f'href="{BASE_PATH}/app/')
        html = html.replace('src="/app/', f'src="{BASE_PATH}/app/')
        raw = html.encode("utf-8")
        data = raw
        wants_gzip = "gzip" in (self.headers.get("Accept-Encoding") or "").lower()
        use_gzip = wants_gzip and len(raw) >= 1024
        if use_gzip:
            data = gzip.compress(raw, compresslevel=6)
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Cache-Control", cache_control)
        if use_gzip:
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _serve_store_file(self, rel: str, mime: str, *, cache_control: str = "no-store") -> None:
        base = Path(self.server.store_dir).resolve()
        target = (base / rel).resolve()
        try:
            target.relative_to(base)
        except ValueError:
            return self.send_error(403)
        return self._serve_path(target, mime, cache_control=cache_control)

    def _export_cluster_review_payload(
        self,
        *,
        collection_id: str,
        board: str = "",
        include_neighbors: int,
        similarity_threshold: float,
        max_neighbors: int,
        clusters: str,
    ) -> dict:
        script = self._project_root() / "tools" / "export_clusters.py"
        if not script.exists():
            raise FileNotFoundError("tools/export_clusters.py not found")

        with tempfile.NamedTemporaryFile(prefix="cluster_review_", suffix=".json", delete=False) as tmp:
            out_path = Path(tmp.name)

        try:
            cmd = [
                sys.executable,
                str(script),
                "--db",
                str(self.server.db_path),
                "--out",
                str(out_path),
                "--collection-id",
                collection_id,
                "--include-neighbors",
                str(include_neighbors),
                "--similarity-threshold",
                str(similarity_threshold),
                "--max-neighbors",
                str(max_neighbors),
                "--clusters",
                clusters,
                "--api-base",
                "",
            ]
            if board:
                cmd += ["--board", board]
            proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
            if proc.returncode != 0:
                err = (proc.stderr or proc.stdout or "unknown export error").strip()
                raise RuntimeError(err)
            return json.loads(out_path.read_text(encoding="utf-8"))
        finally:
            try:
                out_path.unlink(missing_ok=True)
            except Exception:
                pass

    def _serve_media(self, asset_id: str, kind: str) -> None:
        kind = kind if kind in ("thumb", "original", "pdf") else "thumb"
        with Db(self.server.db_path) as db:
            ensure_schema(db)
            row = db.query(
                "select id, source, source_ref, stored_path, thumb_path from assets where id=?",
                (asset_id,),
            )
            if not row:
                return self.send_error(404)
            r = row[0]
            if kind == "pdf" and (r["source"] or "") == "scan":
                # Prefer doc-scoped PDF (single/multi-page clip); fallback to source scan PDF.
                try:
                    path = str(self._ensure_scan_doc_pdf_path(db, asset_id))
                except Exception:
                    scan_pdf_path = self._scan_pdf_path_from_source_ref(r["source_ref"])
                    if not (scan_pdf_path and scan_pdf_path.exists() and scan_pdf_path.is_file()):
                        return self.send_error(404)
                    path = str(scan_pdf_path)
            elif kind == "thumb":
                path = r["thumb_path"]
            else:
                path = r["stored_path"]
            if not path:
                return self.send_error(404)
            base = Path(self.server.store_dir).resolve()
            target = Path(path).resolve()
            try:
                target.relative_to(base)
            except ValueError:
                return self.send_error(403)
            if not target.exists() or not target.is_file():
                return self.send_error(404)
            data = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", _guess_mime(str(target)))
            # Media paths are content-addressed/stable per asset ID + kind.
            self.send_header("Cache-Control", "public, max-age=604800")
            self.send_header("Content-Length", str(len(data)))
            if str(target).lower().endswith(".pdf"):
                self.send_header("Content-Disposition", "inline")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

    def _get_asset_for_modal(self, db: Db, *, asset_id: str, include_hidden: bool = False) -> dict | None:
        rows = db.query(
            """
            select a.id, a.source, a.source_ref, a.title, a.description, a.board,
                   a.created_at, a.imported_at, a.image_url, a.stored_path, a.thumb_path,
                   a.triage_status, a.needs_annotation, a.source_url, a.seo_alt_text,
                   a.post_text, a.hashtags, a.engagement_json, a.dominant_color,
                   a.ai_summary, a.image_width, a.image_height, a.content_kind,
                   a.creator_name, a.source_domain, a.source_name, a.notes,
                   a.flagged, a.flagged_by, a.flagged_note,
                   a.tagged, a.tagged_by, a.tagged_note
            from assets a
            where a.id = ?
            limit 1
            """,
            (asset_id,),
        )
        if not rows:
            return None
        asset = dict(rows[0])
        if include_hidden:
            return asset
        if str(asset.get("triage_status") or "").strip().lower() == "hidden":
            return None
        hidden_collection_id = db.query_value(
            "select id from collections where lower(name)='hidden' limit 1"
        )
        if hidden_collection_id:
            in_hidden = db.query_value(
                "select 1 from collection_items where collection_id=? and asset_id=? limit 1",
                (str(hidden_collection_id), asset_id),
            )
            if in_hidden:
                return None
        return asset

    def _scan_pdf_path_from_source_ref(self, source_ref: str | None) -> Path | None:
        m = re.match(r"^scan://([a-f0-9]{64})(?:#p\d+)?$", (source_ref or "").strip(), re.IGNORECASE)
        if not m:
            return None
        sha = m.group(1).lower()
        return Path(self.server.store_dir) / "originals" / "scan" / f"{sha}.pdf"

    def _scan_ref_parts(self, source_ref: str | None) -> tuple[str, int | None] | None:
        m = re.match(r"^scan://([a-f0-9]{64})(?:#p(\d+))?$", (source_ref or "").strip(), re.IGNORECASE)
        if not m:
            return None
        sha = m.group(1).lower()
        page = int(m.group(2)) if m.group(2) else None
        return (sha, page)

    def _scan_doc_parts(self, title: str | None) -> tuple[int | None, int | None]:
        m = re.search(r"\bdoc\s+(\d+)(?:\s+p(\d+))?\b", (title or "").strip(), re.IGNORECASE)
        if not m:
            return (None, None)
        doc_idx = int(m.group(1)) if m.group(1) else None
        doc_page = int(m.group(2)) if m.group(2) else None
        return (doc_idx, doc_page)

    def _serve_scan_doc_pdf(self, asset_id: str) -> None:
        with Db(self.server.db_path) as db:
            ensure_schema(db)
            row = db.query("select source_ref from assets where id=?", (asset_id,))
            if not row:
                return self.send_error(404)
            try:
                path = self._ensure_scan_doc_pdf_path(db, asset_id)
            except Exception:
                source_pdf_path = self._scan_pdf_path_from_source_ref(row[0]["source_ref"])
                if not (source_pdf_path and source_pdf_path.exists() and source_pdf_path.is_file()):
                    return self.send_error(404)
                path = source_pdf_path
        target = path.resolve()
        base = Path(self.server.store_dir).resolve()
        try:
            target.relative_to(base)
        except ValueError:
            return self.send_error(403)
        if not target.exists() or not target.is_file():
            return self.send_error(404)
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Cache-Control", "public, max-age=604800")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", "inline")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _ensure_scan_doc_pdf_path(self, db: Db, asset_id: str) -> Path:
        row = db.query(
            "select id, source, source_ref, title from assets where id=?",
            (asset_id,),
        )
        if not row:
            raise FileNotFoundError("asset not found")
        selected = row[0]
        if str(selected["source"] or "").strip().lower() != "scan":
            raise FileNotFoundError("asset is not scan source")

        ref_parts = self._scan_ref_parts(selected["source_ref"])
        if not ref_parts:
            raise FileNotFoundError("scan source_ref missing or invalid")
        sha, selected_ref_page = ref_parts
        selected_doc_idx, _ = self._scan_doc_parts(selected["title"])

        candidates = db.query(
            "select id, source_ref, title, stored_path from assets where source='scan' and source_ref like ?",
            (f"scan://{sha}%",),
        )
        if not candidates:
            raise FileNotFoundError("scan document members not found")

        members: list[dict] = []
        for c in candidates:
            doc_idx, doc_page = self._scan_doc_parts(c["title"])
            ref = self._scan_ref_parts(c["source_ref"])
            ref_page = ref[1] if ref else None
            c_dict = dict(c)
            c_dict["_doc_idx"] = doc_idx
            c_dict["_doc_page"] = int(doc_page or ref_page or 1)
            if selected_doc_idx is None or doc_idx == selected_doc_idx:
                members.append(c_dict)
        if not members:
            raise FileNotFoundError("scan document has no matching pages")
        members.sort(key=lambda r: (int(r.get("_doc_page") or 1), str(r.get("id") or "")))
        if len(members) > MAX_SCAN_DOC_GROUP_PAGES:
            # Large inferred groups are often ambiguous; keep item-level PDF behavior.
            selected_members = [m for m in members if str(m.get("id") or "") == asset_id]
            members = selected_members if selected_members else [members[0]]

        store_base = Path(self.server.store_dir).resolve()
        page_paths: list[Path] = []
        for member in members:
            stored_path = str(member.get("stored_path") or "").strip()
            if not stored_path:
                continue
            p = Path(stored_path).resolve()
            try:
                p.relative_to(store_base)
            except ValueError:
                continue
            if p.exists() and p.is_file():
                page_paths.append(p)

        if not page_paths:
            raise FileNotFoundError("no scan page images found")

        if len(members) == 1:
            out_path = store_base / "originals" / "scan_docs" / sha / f"asset-{members[0]['id']}.pdf"
        elif selected_doc_idx is not None:
            out_path = store_base / "originals" / "scan_docs" / sha / f"doc-{selected_doc_idx:04d}.pdf"
        else:
            # Fallback for scans without doc markers in title.
            page_key = int(selected_ref_page or 1)
            out_path = store_base / "originals" / "scan_docs" / sha / f"page-{page_key:04d}.pdf"
        out_path.parent.mkdir(parents=True, exist_ok=True)

        src_mtime = max(p.stat().st_mtime for p in page_paths)
        need_build = True
        if out_path.exists():
            try:
                need_build = out_path.stat().st_mtime < src_mtime
            except Exception:
                need_build = True
        if need_build:
            self._build_pdf_from_images(page_paths, out_path)
        return out_path

    def _build_pdf_from_images(self, image_paths: list[Path], out_path: Path) -> None:
        # Optional dependency: Pillow. Fallbacks are handled by caller.
        from PIL import Image  # type: ignore

        images = []
        try:
            for p in image_paths:
                im = Image.open(p)
                if im.mode != "RGB":
                    im = im.convert("RGB")
                images.append(im)
            if not images:
                raise ValueError("no images to build PDF")
            first, *rest = images
            tmp_path = out_path.with_suffix(".tmp.pdf")
            first.save(tmp_path, format="PDF", save_all=True, append_images=rest, resolution=150.0)
            tmp_path.replace(out_path)
        finally:
            for im in images:
                try:
                    im.close()
                except Exception:
                    pass


def _notify_question(actor: dict | None, text: str) -> None:
    """Fire-and-forget notification when a question annotation is created."""
    actor_name = (actor or {}).get("name", "Someone")
    msg = f"New question on your inspiration library from {actor_name}: {(text or '')[:100]}"
    phone = (os.environ.get("INSPIRATIONS_NOTIFY_PHONE") or "").strip()
    if phone:
        try:
            escaped = msg.replace('"', '\\"')
            subprocess.run(
                ["osascript", "-e",
                 f'tell application "Messages" to send "{escaped}" to buddy "{phone}"'],
                check=False, capture_output=True, timeout=10,
            )
        except Exception:
            pass  # best-effort


def _seed_default_actors(db_path: Path, host: str, port: int) -> None:
    """Create default owner actors (Jim + Leslie) if the actors table is empty."""
    with Db(db_path) as db:
        ensure_schema(db)
        existing = db.query_value("select count(*) from actors")
        if existing:
            # Print existing magic links on startup
            actors = list_actors(db)
            for a in actors:
                url = f"http://{host}:{port}{BASE_PATH}/?actor={a['token']}"
                print(f"  {a['name']} ({a['role']}): {url}")
            return
        leslie = create_actor(db, name="Leslie", role="owner")
        jim = create_actor(db, name="Jim", role="owner")
        print("Created default owner actors:")
        print(f"  Leslie (owner): http://{host}:{port}{BASE_PATH}/?actor={leslie['token']}")
        print(f"  Jim (owner): http://{host}:{port}{BASE_PATH}/?actor={jim['token']}")


def _guess_mime(path: str) -> str:
    p = path.lower()
    if p.endswith(".js"):
        return "application/javascript"
    if p.endswith(".css"):
        return "text/css"
    if p.endswith(".html"):
        return "text/html"
    if p.endswith(".svg"):
        return "image/svg+xml"
    guessed, _ = mimetypes.guess_type(p)
    if guessed:
        return guessed
    return "application/octet-stream"


class InspirationsHTTPServer(ThreadingHTTPServer):
    # Prevent slow/stuck clients from blocking shutdown/reload.
    daemon_threads = True
    allow_reuse_address = True


def run_server(*, host: str, port: int, db_path: Path, app_dir: Path, store_dir: Path) -> None:
    server = InspirationsHTTPServer((host, port), ApiHandler)
    server.db_path = db_path
    server.app_dir = app_dir
    server.store_dir = store_dir
    server.imports_dir = app_dir.resolve().parent / "imports"
    server.admin_tokens = {}

    # Catalog directory — look next to the database
    catalog_dir = Path(db_path).resolve().parent / "catalog"
    if catalog_dir.is_dir() and (catalog_dir / "_index.md").exists():
        server.catalog_dir = catalog_dir
        print(f"Catalog loaded from {catalog_dir}")
    else:
        server.catalog_dir = None
        print("No catalog found — chat will use routing-only mode")

    # Seed default actors (Jim + Leslie) and print magic link URLs
    print("\nMagic link URLs:")
    _seed_default_actors(db_path, host, port)

    print(f"\nServing on http://{host}:{port}")
    server.serve_forever()
