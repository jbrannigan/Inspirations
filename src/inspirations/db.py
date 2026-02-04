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
    db.exec("create unique index if not exists ux_assets_source_ref on assets(source, source_ref);")
    db.exec("create index if not exists ix_assets_source on assets(source);")
    db.exec("create index if not exists ix_assets_imported_at on assets(imported_at);")
    db.exec("create index if not exists ix_assets_sha256 on assets(sha256);")

