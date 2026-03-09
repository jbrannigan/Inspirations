from __future__ import annotations

import re
import sqlite3
import uuid
from datetime import datetime, timezone
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
_SCAN_AUTOGEN_TITLE_RE = re.compile(r"\s-\sdoc\s+\d+(?:\s+p\d+)?\s*$", re.IGNORECASE)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _looks_like_scan_autogen_title(title: str) -> bool:
    text = (title or "").strip()
    if not text:
        return True
    return bool(_SCAN_AUTOGEN_TITLE_RE.search(text))


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


def _latest_title_audit_applied(db: Db) -> dict[str, sqlite3.Row]:
    rows = db.query(
        """
        select ta.asset_id, ta.batch_id, ta.old_title, ta.new_title, ta.applied_at, tb.actor
        from title_audit_applied ta
        left join title_audit_batches tb on tb.id = ta.batch_id
        where ta.undone_at is null
          and ta.applied_at = (
            select max(ta2.applied_at)
            from title_audit_applied ta2
            where ta2.asset_id = ta.asset_id
              and ta2.undone_at is null
          )
        """
    )
    return {str(r["asset_id"]): r for r in rows if str(r["asset_id"] or "").strip()}


def _latest_gemini_asset_ai(db: Db) -> dict[str, sqlite3.Row]:
    rows = db.query(
        """
        select ai.id, ai.asset_id, ai.provider, ai.model, ai.created_at
        from asset_ai ai
        where ai.provider = 'gemini'
          and ai.created_at = (
            select max(ai2.created_at)
            from asset_ai ai2
            where ai2.asset_id = ai.asset_id
              and ai2.provider = 'gemini'
          )
        """
    )
    return {str(r["asset_id"]): r for r in rows if str(r["asset_id"] or "").strip()}


def _infer_title_provenance(
    *,
    asset: sqlite3.Row,
    title_audit_row: sqlite3.Row | None,
    gemini_row: sqlite3.Row | None,
) -> tuple[str, str, str, float, str]:
    asset_id = str(asset["id"])
    source = str(asset["source"] or "").strip().lower()
    source_ref = str(asset["source_ref"] or "").strip()
    title = str(asset["title"] or "").strip()
    imported_at = str(asset["imported_at"] or "").strip() or _now_iso()

    if title_audit_row and str(title_audit_row["new_title"] or "").strip() == title:
        created_at = str(title_audit_row["applied_at"] or "").strip() or imported_at
        actor = str(title_audit_row["actor"] or "").strip() or "title_audit"
        return ("title_audit", str(title_audit_row["batch_id"] or ""), actor, 0.98, created_at)

    if source == "scan":
        if gemini_row and not _looks_like_scan_autogen_title(title):
            created_at = str(gemini_row["created_at"] or "").strip() or imported_at
            model = str(gemini_row["model"] or "").strip()
            origin_ref = f"asset_ai:{str(gemini_row['id'])}" if str(gemini_row["id"] or "").strip() else "asset_ai:gemini"
            actor = f"gemini:{model}" if model else "gemini"
            return ("ai_suggested", origin_ref, actor, 0.7, created_at)
        if _looks_like_scan_autogen_title(title):
            return ("imported", source_ref, "scan_importer", 0.95, imported_at)
        return ("derived", source_ref, "migration_backfill", 0.45, imported_at)

    if source == "pinterest":
        return ("source_native", source_ref, "pinterest_importer", 0.9, imported_at)
    if source == "houzz":
        return ("source_native", source_ref, "houzz_importer", 0.9, imported_at)
    if source == "facebook":
        return ("imported", source_ref, "facebook_importer", 0.85, imported_at)
    if source:
        return ("imported", source_ref, f"{source}_importer", 0.8, imported_at)
    return ("derived", f"asset:{asset_id}", "migration_backfill", 0.4, imported_at)


def _backfill_title_field_provenance(db: Db) -> None:
    title_audit_by_asset = _latest_title_audit_applied(db)
    gemini_by_asset = _latest_gemini_asset_ai(db)
    rows = db.query(
        """
        select a.id, a.source, a.source_ref, a.title, a.imported_at,
               p.id as provenance_id, p.field_value as provenance_value
        from assets a
        left join asset_field_provenance p
          on p.asset_id = a.id
         and p.field_name = 'title'
         and p.is_current = 1
        where coalesce(a.title, '') != ''
        """
    )
    inserts: list[tuple[str, str, str, str, str, str | None, str | None, float, str, None, int]] = []
    supersede: list[tuple[str, str]] = []
    for row in rows:
        asset_id = str(row["id"])
        current_value = str(row["provenance_value"] or "").strip()
        title = str(row["title"] or "").strip()
        provenance_id = str(row["provenance_id"] or "").strip()
        if provenance_id and current_value == title:
            continue
        origin_type, origin_ref, actor, confidence, created_at = _infer_title_provenance(
            asset=row,
            title_audit_row=title_audit_by_asset.get(asset_id),
            gemini_row=gemini_by_asset.get(asset_id),
        )
        if provenance_id:
            supersede.append((_now_iso(), provenance_id))
        inserts.append(
            (
                str(uuid.uuid4()),
                asset_id,
                "title",
                title,
                origin_type,
                origin_ref or None,
                actor or None,
                float(confidence),
                created_at,
                None,
                1,
            )
        )
    if supersede:
        db.executemany(
            "update asset_field_provenance set superseded_at=?, is_current=0 where id=? and is_current=1",
            supersede,
        )
    if inserts:
        db.executemany(
            """
            insert into asset_field_provenance
              (id, asset_id, field_name, field_value, origin_type, origin_ref, actor,
               confidence, created_at, superseded_at, is_current)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            inserts,
        )


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
            # Rich metadata from page scrapes
            "source_url": "text",
            "seo_alt_text": "text",
            "closeup_desc": "text",
            "hashtags": "text",
            "dominant_color": "text",
            "image_width": "integer",
            "image_height": "integer",
            "post_text": "text",
            "engagement_json": "text",
            "scrape_json": "text",
            # Triage workflow
            "triage_status": "text",
            "triage_at": "text",
            "needs_annotation": "integer",
            # Categorization
            "category": "text",  # 'home_design' or 'other'
            # Review flags (e.g. wrong thumbnail)
            "flagged": "integer default 0",
            "flagged_by": "text",
            "flagged_note": "text",
            # Anomaly tags (Jim's "needs diagnosis" markers)
            "tagged": "integer default 0",
            "tagged_by": "text",
            "tagged_note": "text",
            # Video reel metadata
            "stored_video_path": "text",
            "video_duration": "real",
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
    db.exec("create index if not exists ix_assets_triage on assets(triage_status);")
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
    _ensure_columns(
        db,
        "collections",
        {
            "hidden": "integer default 0",
            "hidden_at": "text",
        },
    )
    db.exec("create index if not exists ix_collections_hidden on collections(hidden);")
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

    # Actors (magic-link auth for collaboration)
    db.exec(
        """
        create table if not exists actors (
          id text primary key,
          name text not null,
          token text not null unique,
          role text not null default 'collaborator',
          created_at text not null
        );
        """
    )
    db.exec("create unique index if not exists ux_actors_token on actors(token);")

    # Add attribution + question columns to annotations
    _ensure_columns(
        db,
        "annotations",
        {
            "actor_id": "text",
            "actor_name": "text",
            "annotation_type": "text",
            "resolved": "integer default 0",
        },
    )

    # Triage audit log — records every triage status change so bulk
    # operations can be reviewed and reverted.
    db.exec(
        """
        create table if not exists triage_log (
          id integer primary key autoincrement,
          asset_id text not null,
          old_status text,
          new_status text,
          reason text,
          actor text,
          created_at text not null
        );
        """
    )
    db.exec("create index if not exists ix_triage_log_asset on triage_log(asset_id);")
    db.exec("create index if not exists ix_triage_log_created on triage_log(created_at);")
    db.exec("create index if not exists ix_triage_log_actor on triage_log(actor);")

    # Title-audit staging/apply workflow (CLI-first review queue).
    db.exec(
        """
        create table if not exists title_audit_batches (
          id text primary key,
          created_at text not null,
          source_filter text,
          include_hidden integer not null default 1,
          limit_requested integer not null default 0,
          total_scanned integer not null default 0,
          candidate_count integer not null default 0,
          status text not null default 'staged',
          actor text,
          notes text,
          applied_at text,
          undone_at text
        );
        """
    )
    db.exec("create index if not exists ix_title_audit_batches_created on title_audit_batches(created_at);")
    db.exec("create index if not exists ix_title_audit_batches_status on title_audit_batches(status);")

    db.exec(
        """
        create table if not exists title_audit_candidates (
          id integer primary key autoincrement,
          batch_id text not null,
          asset_id text not null,
          old_title text,
          proposed_title text not null,
          technique_used text not null,
          review_status text not null default 'pending',
          review_note text,
          reviewed_at text,
          applied_at text,
          foreign key(batch_id) references title_audit_batches(id) on delete cascade,
          foreign key(asset_id) references assets(id) on delete cascade
        );
        """
    )
    db.exec(
        """
        create unique index if not exists ux_title_audit_candidates_batch_asset
        on title_audit_candidates(batch_id, asset_id);
        """
    )
    db.exec(
        """
        create index if not exists ix_title_audit_candidates_batch_status
        on title_audit_candidates(batch_id, review_status);
        """
    )
    db.exec(
        """
        create index if not exists ix_title_audit_candidates_batch_applied
        on title_audit_candidates(batch_id, applied_at);
        """
    )

    db.exec(
        """
        create table if not exists title_audit_applied (
          id integer primary key autoincrement,
          batch_id text not null,
          asset_id text not null,
          old_title text,
          new_title text not null,
          applied_at text not null,
          undone_at text,
          foreign key(batch_id) references title_audit_batches(id) on delete cascade,
          foreign key(asset_id) references assets(id) on delete cascade,
          unique(batch_id, asset_id)
        );
        """
    )
    db.exec("create index if not exists ix_title_audit_applied_batch on title_audit_applied(batch_id);")
    db.exec("create index if not exists ix_title_audit_applied_undone on title_audit_applied(batch_id, undone_at);")

    # Provenance-aware v2 classification layer. These tables preserve evidence
    # and human overrides without overwriting the legacy curation outputs.
    db.exec(
        """
        create table if not exists classification_runs (
          id text primary key,
          schema_version text not null,
          run_type text not null,
          model_provider text,
          model_name text,
          prompt_version text,
          config_json text,
          created_at text not null,
          notes text
        );
        """
    )
    db.exec("create index if not exists ix_classification_runs_type on classification_runs(run_type);")
    db.exec("create index if not exists ix_classification_runs_created on classification_runs(created_at);")

    db.exec(
        """
        create table if not exists asset_field_provenance (
          id text primary key,
          asset_id text not null,
          field_name text not null,
          field_value text,
          origin_type text not null,
          origin_ref text,
          actor text,
          confidence real,
          created_at text not null,
          superseded_at text,
          is_current integer not null default 1,
          foreign key(asset_id) references assets(id) on delete cascade
        );
        """
    )
    db.exec(
        """
        create index if not exists ix_asset_field_provenance_asset_field
        on asset_field_provenance(asset_id, field_name);
        """
    )
    db.exec(
        """
        create index if not exists ix_asset_field_provenance_current
        on asset_field_provenance(field_name, is_current);
        """
    )
    db.exec(
        """
        create unique index if not exists ux_asset_field_provenance_current
        on asset_field_provenance(asset_id, field_name)
        where is_current = 1;
        """
    )

    db.exec(
        """
        create table if not exists asset_track_assessments (
          id text primary key,
          run_id text not null,
          asset_id text not null,
          track text not null,
          confidence real,
          is_ambiguous integer not null default 0,
          decision_source text not null,
          reason text,
          created_at text not null,
          foreign key(run_id) references classification_runs(id) on delete cascade,
          foreign key(asset_id) references assets(id) on delete cascade
        );
        """
    )
    db.exec(
        """
        create unique index if not exists ux_asset_track_assessments_run_asset
        on asset_track_assessments(run_id, asset_id);
        """
    )
    db.exec("create index if not exists ix_asset_track_assessments_asset on asset_track_assessments(asset_id);")
    db.exec("create index if not exists ix_asset_track_assessments_track on asset_track_assessments(track);")

    db.exec(
        """
        create table if not exists asset_axis_memberships (
          id text primary key,
          run_id text not null,
          asset_id text not null,
          track text,
          axis_name text not null,
          axis_value text not null,
          confidence real,
          rank integer,
          is_primary integer not null default 0,
          is_ambiguous integer not null default 0,
          created_at text not null,
          foreign key(run_id) references classification_runs(id) on delete cascade,
          foreign key(asset_id) references assets(id) on delete cascade
        );
        """
    )
    db.exec(
        """
        create unique index if not exists ux_asset_axis_memberships_run_asset_axis_value
        on asset_axis_memberships(run_id, asset_id, axis_name, axis_value);
        """
    )
    db.exec("create index if not exists ix_asset_axis_memberships_asset on asset_axis_memberships(asset_id);")
    db.exec("create index if not exists ix_asset_axis_memberships_axis on asset_axis_memberships(axis_name, axis_value);")

    db.exec(
        """
        create table if not exists asset_axis_evidence (
          id text primary key,
          run_id text,
          asset_id text not null,
          track text,
          axis_name text not null,
          axis_value text,
          evidence_type text not null,
          evidence_ref text,
          weight real,
          confidence real,
          note text,
          created_at text not null,
          foreign key(run_id) references classification_runs(id) on delete cascade,
          foreign key(asset_id) references assets(id) on delete cascade
        );
        """
    )
    db.exec("create index if not exists ix_asset_axis_evidence_asset on asset_axis_evidence(asset_id);")
    db.exec("create index if not exists ix_asset_axis_evidence_axis on asset_axis_evidence(axis_name, axis_value);")

    db.exec(
        """
        create table if not exists asset_overrides (
          id text primary key,
          asset_id text not null,
          track text,
          axis_name text not null,
          axis_value text,
          operation text not null,
          actor text,
          note text,
          created_at text not null,
          expires_at text,
          foreign key(asset_id) references assets(id) on delete cascade
        );
        """
    )
    db.exec("create index if not exists ix_asset_overrides_asset on asset_overrides(asset_id);")
    db.exec("create index if not exists ix_asset_overrides_axis on asset_overrides(axis_name, axis_value);")

    db.exec(
        """
        create table if not exists asset_source_link_enrichment (
          id text primary key,
          run_id text not null,
          asset_id text not null,
          input_url text,
          final_url text,
          final_domain text,
          canonical_url text,
          og_image_url text,
          page_title text,
          og_title text,
          meta_description text,
          og_description text,
          text_excerpt text,
          content_type text,
          http_status integer,
          redirect_count integer not null default 0,
          truncated integer not null default 0,
          fetch_status text not null,
          error text,
          content_hash text,
          created_at text not null,
          foreign key(run_id) references classification_runs(id) on delete cascade,
          foreign key(asset_id) references assets(id) on delete cascade
        );
        """
    )
    db.exec(
        """
        create unique index if not exists ux_asset_source_link_enrichment_run_asset
        on asset_source_link_enrichment(run_id, asset_id);
        """
    )
    db.exec(
        """
        create index if not exists ix_asset_source_link_enrichment_asset
        on asset_source_link_enrichment(asset_id);
        """
    )
    db.exec(
        """
        create index if not exists ix_asset_source_link_enrichment_status
        on asset_source_link_enrichment(fetch_status);
        """
    )

    db.exec(
        """
        create table if not exists asset_source_link_qc (
          id text primary key,
          run_id text not null,
          asset_id text not null,
          track text,
          inferred_track text,
          verdict text not null,
          confidence real,
          reason text,
          fetch_status text,
          created_at text not null,
          foreign key(run_id) references classification_runs(id) on delete cascade,
          foreign key(asset_id) references assets(id) on delete cascade
        );
        """
    )
    db.exec(
        """
        create unique index if not exists ux_asset_source_link_qc_run_asset
        on asset_source_link_qc(run_id, asset_id);
        """
    )
    db.exec(
        """
        create index if not exists ix_asset_source_link_qc_asset
        on asset_source_link_qc(asset_id);
        """
    )
    db.exec(
        """
        create index if not exists ix_asset_source_link_qc_verdict
        on asset_source_link_qc(verdict);
        """
    )

    _backfill_assets_metadata(db)
    _backfill_title_field_provenance(db)
