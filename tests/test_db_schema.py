import tempfile
import unittest
from pathlib import Path

from inspirations.db import Db, ensure_schema


class TestDbSchema(unittest.TestCase):
    def test_ensure_schema_creates_v2_classification_tables(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                names = {
                    str(r["name"])
                    for r in db.query(
                        """
                        select name
                        from sqlite_master
                        where type='table'
                          and name in (
                            'classification_runs',
                            'asset_field_provenance',
                            'asset_track_assessments',
                            'asset_axis_memberships',
                            'asset_axis_evidence',
                            'asset_overrides',
                            'asset_source_link_enrichment',
                            'asset_source_link_qc'
                          )
                        """
                    )
                }
            self.assertEqual(
                names,
                {
                    "classification_runs",
                    "asset_field_provenance",
                    "asset_track_assessments",
                    "asset_axis_memberships",
                    "asset_axis_evidence",
                    "asset_overrides",
                    "asset_source_link_enrichment",
                    "asset_source_link_qc",
                },
            )

    def test_title_provenance_prefers_title_audit_application(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, imported_at)
                    values (?, ?, ?, ?, ?)
                    """,
                    ("a1", "facebook", "https://www.facebook.com/reel/1", "Edited title", "2026-03-06T00:00:00+00:00"),
                )
                db.exec(
                    """
                    insert into title_audit_batches
                      (id, created_at, candidate_count, total_scanned, status, actor)
                    values (?, ?, ?, ?, ?, ?)
                    """,
                    ("b1", "2026-03-06T01:00:00+00:00", 1, 1, "applied", "jim"),
                )
                db.exec(
                    """
                    insert into title_audit_applied
                      (batch_id, asset_id, old_title, new_title, applied_at)
                    values (?, ?, ?, ?, ?)
                    """,
                    ("b1", "a1", "Original title", "Edited title", "2026-03-06T02:00:00+00:00"),
                )

                ensure_schema(db)
                row = db.query(
                    """
                    select field_name, field_value, origin_type, origin_ref, actor, is_current
                    from asset_field_provenance
                    where asset_id=?
                    """,
                    ("a1",),
                )[0]

            self.assertEqual(str(row["field_name"]), "title")
            self.assertEqual(str(row["field_value"]), "Edited title")
            self.assertEqual(str(row["origin_type"]), "title_audit")
            self.assertEqual(str(row["origin_ref"]), "b1")
            self.assertEqual(str(row["actor"]), "jim")
            self.assertEqual(int(row["is_current"]), 1)

    def test_title_provenance_supersedes_imported_scan_title_when_ai_updates_it(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, imported_at)
                    values (?, ?, ?, ?, ?)
                    """,
                    (
                        "s1",
                        "scan",
                        "scan://abc123#p7",
                        "Book Mar 4, 2026 - doc 7",
                        "2026-03-06T00:00:00+00:00",
                    ),
                )

                ensure_schema(db)
                first = db.query(
                    """
                    select id, field_value, origin_type, is_current, superseded_at
                    from asset_field_provenance
                    where asset_id=?
                    order by created_at asc
                    """,
                    ("s1",),
                )
                self.assertEqual(len(first), 1)
                self.assertEqual(str(first[0]["origin_type"]), "imported")
                self.assertEqual(int(first[0]["is_current"]), 1)

                db.exec(
                    """
                    insert into asset_ai (id, asset_id, provider, model, summary, json, created_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "ai1",
                        "s1",
                        "gemini",
                        "gemini-2.5-flash",
                        "A bright kitchen with windows.",
                        "{}",
                        "2026-03-06T03:00:00+00:00",
                    ),
                )
                db.exec("update assets set title=? where id=?", ("Bright kitchen with large windows", "s1"))

                ensure_schema(db)
                rows = db.query(
                    """
                    select field_value, origin_type, origin_ref, is_current, superseded_at
                    from asset_field_provenance
                    where asset_id=?
                    order by created_at asc
                    """,
                    ("s1",),
                )

            self.assertEqual(len(rows), 2)
            self.assertEqual(str(rows[0]["field_value"]), "Book Mar 4, 2026 - doc 7")
            self.assertEqual(str(rows[0]["origin_type"]), "imported")
            self.assertEqual(int(rows[0]["is_current"]), 0)
            self.assertTrue(str(rows[0]["superseded_at"] or "").strip())
            self.assertEqual(str(rows[1]["field_value"]), "Bright kitchen with large windows")
            self.assertEqual(str(rows[1]["origin_type"]), "ai_suggested")
            self.assertEqual(str(rows[1]["origin_ref"]), "asset_ai:ai1")
            self.assertEqual(int(rows[1]["is_current"]), 1)

    def test_collection_provenance_backfills_cb_collection(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into collections (id, name, description, created_at, updated_at)
                    values (?, ?, ?, ?, ?)
                    """,
                    (
                        "cb1",
                        "CB: Kitchen",
                        "Kitchen layouts, cabinets, countertops, appliances.",
                        "2026-03-10T00:00:00+00:00",
                        "2026-03-10T00:00:00+00:00",
                    ),
                )

                ensure_schema(db)
                row = db.query(
                    """
                    select provenance_kind, provenance_note, curator, description
                    from collections
                    where id='cb1'
                    """
                )[0]

            self.assertEqual(str(row["provenance_kind"]), "ai_derived_representative")
            self.assertEqual(str(row["curator"]), "claude_code_session")
            self.assertIn("Not a human-curated final selection", str(row["provenance_note"]))
            self.assertTrue(
                str(row["description"]).startswith(
                    "AI-derived representative set from high-confidence descriptions/tagging."
                )
            )


if __name__ == "__main__":
    unittest.main()
