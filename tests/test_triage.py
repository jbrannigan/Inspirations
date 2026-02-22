"""Tests for triage store functions."""
from __future__ import annotations

import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
import unittest

from inspirations.db import Db, ensure_schema
from inspirations.store import (
    bulk_set_triage_status,
    list_assets,
    list_facets,
    set_triage_status,
    triage_stats,
)


def _insert_asset(db: Db, source: str = "pinterest", board: str | None = "kitchen") -> str:
    asset_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    db.exec(
        """insert into assets (id, source, source_ref, imported_at, media_status)
           values (?, ?, ?, ?, ?)""",
        (asset_id, source, f"https://example.com/{asset_id}", now, "image"),
    )
    if board:
        db.exec("update assets set board = ? where id = ?", (board, asset_id))
    return asset_id


class TestTriageStore(unittest.TestCase):
    def _make_db(self) -> tuple[Db, Path]:
        tmp = tempfile.mkdtemp()
        db_path = Path(tmp) / "test.sqlite"
        db = Db(db_path)
        db.__enter__()
        ensure_schema(db)
        return db, db_path

    def test_set_triage_status_keeper(self):
        db, _ = self._make_db()
        try:
            aid = _insert_asset(db)
            set_triage_status(db, aid, "keeper")
            row = db.query("select triage_status, triage_at, needs_annotation from assets where id=?", (aid,))
            self.assertEqual(row[0]["triage_status"], "keeper")
            self.assertIsNotNone(row[0]["triage_at"])
            self.assertEqual(row[0]["needs_annotation"], 0)
        finally:
            db.__exit__(None, None, None)

    def test_set_triage_status_reset_to_pending(self):
        db, _ = self._make_db()
        try:
            aid = _insert_asset(db)
            set_triage_status(db, aid, "keeper")
            set_triage_status(db, aid, None)
            row = db.query("select triage_status, needs_annotation from assets where id=?", (aid,))
            self.assertIsNone(row[0]["triage_status"])
            self.assertEqual(row[0]["needs_annotation"], 0)
        finally:
            db.__exit__(None, None, None)

    def test_set_triage_status_needs_annotation(self):
        db, _ = self._make_db()
        try:
            aid = _insert_asset(db)
            set_triage_status(db, aid, "keeper", needs_annotation=1)
            row = db.query("select triage_status, needs_annotation from assets where id=?", (aid,))
            self.assertEqual(row[0]["triage_status"], "keeper")
            self.assertEqual(row[0]["needs_annotation"], 1)
        finally:
            db.__exit__(None, None, None)

    def test_bulk_set_triage_status(self):
        db, _ = self._make_db()
        try:
            ids = [_insert_asset(db) for _ in range(3)]
            count = bulk_set_triage_status(db, ids, "hidden")
            self.assertEqual(count, 3)
            rows = db.query("select triage_status from assets where id in (?,?,?)", tuple(ids))
            for r in rows:
                self.assertEqual(r["triage_status"], "hidden")
        finally:
            db.__exit__(None, None, None)

    def test_bulk_set_empty_list(self):
        db, _ = self._make_db()
        try:
            count = bulk_set_triage_status(db, [], "keeper")
            self.assertEqual(count, 0)
        finally:
            db.__exit__(None, None, None)

    def test_triage_stats(self):
        db, _ = self._make_db()
        try:
            a1 = _insert_asset(db, board="kitchen")
            a2 = _insert_asset(db, board="kitchen")
            a3 = _insert_asset(db, board="bathroom")
            set_triage_status(db, a1, "keeper")
            set_triage_status(db, a2, "hidden")
            set_triage_status(db, a3, "keeper", needs_annotation=1)

            stats = triage_stats(db)
            overall = stats["overall"]
            self.assertEqual(overall["keepers"], 2)
            self.assertEqual(overall["hidden"], 1)
            self.assertEqual(overall["pending"], 0)
            self.assertEqual(overall["needs_comment"], 1)
            self.assertEqual(overall["total"], 3)
        finally:
            db.__exit__(None, None, None)

    def test_list_assets_triage_filter_pending(self):
        db, _ = self._make_db()
        try:
            a1 = _insert_asset(db)
            a2 = _insert_asset(db)
            set_triage_status(db, a1, "keeper")

            pending = list_assets(db, triage_status="pending")
            pending_ids = {r["id"] for r in pending}
            self.assertIn(a2, pending_ids)
            self.assertNotIn(a1, pending_ids)
        finally:
            db.__exit__(None, None, None)

    def test_list_assets_triage_filter_keeper(self):
        db, _ = self._make_db()
        try:
            a1 = _insert_asset(db)
            a2 = _insert_asset(db)
            set_triage_status(db, a1, "keeper")

            keepers = list_assets(db, triage_status="keeper")
            keeper_ids = {r["id"] for r in keepers}
            self.assertIn(a1, keeper_ids)
            self.assertNotIn(a2, keeper_ids)
        finally:
            db.__exit__(None, None, None)

    def test_list_assets_excludes_hidden_by_default(self):
        db, _ = self._make_db()
        try:
            a1 = _insert_asset(db)
            a2 = _insert_asset(db)
            set_triage_status(db, a1, "hidden")

            visible = list_assets(db)
            visible_ids = {r["id"] for r in visible}
            self.assertNotIn(a1, visible_ids)
            self.assertIn(a2, visible_ids)
        finally:
            db.__exit__(None, None, None)

    def test_list_assets_include_hidden(self):
        db, _ = self._make_db()
        try:
            a1 = _insert_asset(db)
            set_triage_status(db, a1, "hidden")

            all_assets = list_assets(db, include_hidden=True)
            all_ids = {r["id"] for r in all_assets}
            self.assertIn(a1, all_ids)
        finally:
            db.__exit__(None, None, None)

    def test_list_facets_includes_triage_statuses(self):
        db, _ = self._make_db()
        try:
            a1 = _insert_asset(db)
            set_triage_status(db, a1, "keeper")
            _insert_asset(db)  # pending

            facets = list_facets(db)
            self.assertIn("triage_statuses", facets)
            triage_vals = {f["value"]: f["count"] for f in facets["triage_statuses"]}
            self.assertIn("keeper", triage_vals)
            self.assertIn("pending", triage_vals)
            self.assertEqual(triage_vals["keeper"], 1)
        finally:
            db.__exit__(None, None, None)


if __name__ == "__main__":
    unittest.main()
