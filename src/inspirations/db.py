from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


class Db:
    def __init__(self, path: Path):
        self.path = path
        self._conn: sqlite3.Connection | None = None

    def __enter__(self) -> "Db":
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("pragma foreign_keys=on;")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._conn is not None:
            if exc_type is None:
                self._conn.commit()
            else:
                self._conn.rollback()
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Db not opened. Use 'with Db(...) as db:'")
        return self._conn

    def exec(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self.conn.execute(sql, params)

    def executemany(self, sql: str, rows: list[tuple[Any, ...]]) -> None:
        self.conn.executemany(sql, rows)

    def query(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        cur = self.conn.execute(sql, params)
        return list(cur.fetchall())

    def query_value(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        cur = self.conn.execute(sql, params)
        row = cur.fetchone()
        return row[0] if row else None


def _ensure_columns(db: Db, table: str, columns: dict[str, str]) -> None:
    existing = {r["name"] for r in db.query(f"pragma table_info({table});")}
    for name, decl in columns.items():
        if name in existing:
            continue
        db.exec(f"alter table {table} add column {name} {decl};")


_IMAGE_REF_RE = re.compile(r"\.(jpg|jpeg|png|webp|gif|bmp|svg)(?:\?.*)?$", re.IGNORECASE)


def _looks_like_image_ref(value: str) -> bool:
    text = (value or "").strip().lower()
    if not text:
        return False
    if _IMAGE_REF_RE.search(text):
        return True
    return any(part in text for part in (".jpg?", ".jpeg?", ".png?", ".webp?", ".gif?", ".bmp?", ".svg?"))


def _extract_domain(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    try:
        host = (urlparse(text).hostname or "").strip().lower()
    except Exception:
        host = ""
    if host.startswith("www."):
        host = host[4:]
    return host


def _infer_media_status(row: sqlite3.Row) -> str:
    thumb_path = str(row["thumb_path"] or "").strip()
    stored_path = str(row["stored_path"] or "").strip()
    image_url = str(row["image_url"] or "").strip()
    if thumb_path:
        return "image"
    if stored_path and _looks_like_image_ref(stored_path):
        return "image"
    if image_url and _looks_like_image_ref(image_url):
        return "image"
    if image_url:
        return "link_only"
    return "metadata_only"


def _backfill_assets_metadata(db: Db) -> None:
    rows = db.query(
        """
        select id, source, source_ref, image_url, stored_path, thumb_path,
               media_status, source_domain, content_kind
        from assets
        where coalesce(media_status, '') = ''
           or coalesce(source_domain, '') = ''
           or (source='scan' and coalesce(content_kind, '') = '')
           or (source='pinterest' and coalesce(content_kind, '') = '')
        """
    )
    updates: list[tuple[str, str | None, str | None, str]] = []
    for row in rows:
        media_status = str(row["media_status"] or "").strip() or _infer_media_status(row)
        source_domain = str(row["source_domain"] or "").strip()
        if not source_domain:
            source_domain = _extract_domain(str(row["source_ref"] or "")) or _extract_domain(str(row["image_url"] or ""))
        content_kind = str(row["content_kind"] or "").strip()
        source = str(row["source"] or "").strip()
        if not content_kind and source == "scan":
            content_kind = "scan"
        if not content_kind and source == "pinterest":
            content_kind = "pin"
        updates.append(
            (
                media_status,
                source_domain or None,
                content_kind or None,
                str(row["id"]),
            )
        )
    if updates:
        db.executemany("update assets set media_status=?, source_domain=?, content_kind=? where id=?", updates)


def ensure_schema(db: Db) -> None:
    db.exec(
        """
        create table if not exists assets (
          id text primary key,
          source text not null,
          source_ref text not null,
          title text,
          description text,
          board text,
          created_at text,
          imported_at text not null,
          image_url text,
          stored_path text,
          sha256 text
        );
        """
    )
    _ensure_columns(
        db,
        "assets",
        {
            "thumb_path": "text",
            "notes": "text",
            "ai_summary": "text",
            "media_status": "text",
            "content_kind": "text",
            "creator_name": "text",
            "source_domain": "text",
            "source_name": "text",
        },
    )
    db.exec("create unique index if not exists ux_assets_source_ref on assets(source, source_ref);")
    db.exec("create index if not exists ix_assets_source on assets(source);")
    db.exec("create index if not exists ix_assets_imported_at on assets(imported_at);")
    db.exec("create index if not exists ix_assets_sha256 on assets(sha256);")
    db.exec("create index if not exists ix_assets_media_status on assets(media_status);")
    db.exec("create index if not exists ix_assets_content_kind on assets(content_kind);")
    db.exec("create index if not exists ix_assets_creator_name on assets(creator_name);")
    db.exec("create index if not exists ix_assets_source_domain on assets(source_domain);")
    db.exec(
        """
        create table if not exists collections (
          id text primary key,
          name text not null,
          description text,
          created_at text not null,
          updated_at text not null
        );
        """
    )
    db.exec(
        """
        create table if not exists collection_items (
          collection_id text not null,
          asset_id text not null,
          position integer not null,
          primary key(collection_id, asset_id),
          foreign key(collection_id) references collections(id) on delete cascade,
          foreign key(asset_id) references assets(id) on delete cascade
        );
        """
    )
    db.exec("create index if not exists ix_collection_items_collection on collection_items(collection_id);")
    db.exec("create index if not exists ix_collection_items_asset on collection_items(asset_id);")
    db.exec(
        """
        create table if not exists annotations (
          id text primary key,
          asset_id text not null,
          x real not null,
          y real not null,
          text text,
          created_at text not null,
          updated_at text not null,
          foreign key(asset_id) references assets(id) on delete cascade
        );
        """
    )
    db.exec("create index if not exists ix_annotations_asset on annotations(asset_id);")

    db.exec(
        """
        create table if not exists tray_items (
          asset_id text primary key,
          added_at text not null,
          foreign key(asset_id) references assets(id) on delete cascade
        );
        """
    )
    db.exec("create index if not exists ix_tray_items_added on tray_items(added_at);")
    db.exec(
        """
        create table if not exists ai_runs (
          id text primary key,
          provider text not null,
          model text,
          created_at text not null
        );
        """
    )
    db.exec(
        """
        create table if not exists asset_ai (
          id text primary key,
          asset_id text not null,
          provider text not null,
          model text,
          summary text,
          json text,
          created_at text not null,
          foreign key(asset_id) references assets(id) on delete cascade
        );
        """
    )
    db.exec("create index if not exists ix_asset_ai_asset on asset_ai(asset_id);")
    db.exec(
        """
        create table if not exists asset_labels (
          id text primary key,
          asset_id text not null,
          label text not null,
          confidence real,
          source text not null,
          model text,
          run_id text,
          created_at text not null,
          foreign key(asset_id) references assets(id) on delete cascade
        );
        """
    )
    db.exec("create unique index if not exists ux_asset_labels on asset_labels(asset_id, label, source);")
    db.exec("create index if not exists ix_asset_labels_asset on asset_labels(asset_id);")

    db.exec(
        """
        create table if not exists asset_ai_errors (
          id text primary key,
          asset_id text,
          provider text not null,
          model text,
          error text,
          raw text,
          run_id text,
          created_at text not null,
          foreign key(asset_id) references assets(id) on delete cascade
        );
        """
    )
    db.exec("create index if not exists ix_asset_ai_errors_asset on asset_ai_errors(asset_id);")
    db.exec(
        """
        create table if not exists asset_embeddings (
          id text primary key,
          asset_id text not null,
          provider text not null,
          model text not null,
          input_text text,
          vector_json text not null,
          dimensions integer not null,
          created_at text not null,
          foreign key(asset_id) references assets(id) on delete cascade
        );
        """
    )
    db.exec("create index if not exists ix_asset_embeddings_asset on asset_embeddings(asset_id);")
    db.exec("create index if not exists ix_asset_embeddings_provider_model on asset_embeddings(provider, model);")
    db.exec(
        """
        create unique index if not exists ux_asset_embeddings_asset_provider_model
        on asset_embeddings(asset_id, provider, model);
        """
    )
    db.exec(
        """
        create table if not exists source_collections (
          id text primary key,
          source text not null,
          source_ref text,
          name text not null,
          created_at text,
          imported_at text not null
        );
        """
    )
    db.exec(
        """
        create unique index if not exists ux_source_collections_source_name
        on source_collections(source, name);
        """
    )
    db.exec("create index if not exists ix_source_collections_source on source_collections(source);")
    _backfill_assets_metadata(db)
