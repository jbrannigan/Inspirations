from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


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
        },
    )
    db.exec("create unique index if not exists ux_assets_source_ref on assets(source, source_ref);")
    db.exec("create index if not exists ix_assets_source on assets(source);")
    db.exec("create index if not exists ix_assets_imported_at on assets(imported_at);")
    db.exec("create index if not exists ix_assets_sha256 on assets(sha256);")
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
