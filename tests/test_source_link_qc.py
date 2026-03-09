import tempfile
import unittest
from pathlib import Path

from inspirations.db import Db, ensure_schema
from inspirations.source_link_qc import run_source_link_qc


class TestSourceLinkQc(unittest.TestCase):
    def test_source_link_qc_marks_supporting_when_source_page_matches_track(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into classification_runs
                      (id, schema_version, run_type, model_provider, model_name, prompt_version, config_json, created_at, notes)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("track1", "curation_v2", "track_gate", "heuristic", "test", "", "{}", "2026-03-08T00:00:00+00:00", ""),
                )
                db.exec(
                    """
                    insert into classification_runs
                      (id, schema_version, run_type, model_provider, model_name, prompt_version, config_json, created_at, notes)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("enrich1", "curation_v2", "source_link_enrichment", "heuristic", "test", "", "{}", "2026-03-08T00:01:00+00:00", ""),
                )
                db.exec(
                    """
                    insert into assets (id, source, source_ref, source_url, title, imported_at)
                    values (?, ?, ?, ?, ?, ?)
                    """,
                    ("a1", "facebook", "https://example.com/post", "https://doorware.com", "Doorware", "2026-03-08T00:00:00+00:00"),
                )
                db.exec(
                    """
                    insert into asset_track_assessments
                      (id, run_id, asset_id, track, confidence, is_ambiguous, decision_source, reason, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("ta1", "track1", "a1", "style_product_decor", 0.8, 0, "merged", "winner=style", "2026-03-08T00:00:00+00:00"),
                )
                db.exec(
                    """
                    insert into asset_source_link_enrichment
                      (id, run_id, asset_id, input_url, final_url, final_domain, canonical_url, og_image_url,
                       page_title, og_title, meta_description, og_description, text_excerpt, content_type,
                       http_status, redirect_count, truncated, fetch_status, error, content_hash, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "e1",
                        "enrich1",
                        "a1",
                        "https://doorware.com",
                        "https://doorware.com",
                        "doorware.com",
                        "https://doorware.com",
                        None,
                        "Door Hardware, Commercial Door Hardware",
                        None,
                        "Find knobs, handles, locks and hinges.",
                        None,
                        "Find knobs, handles, locks and hinges for your home.",
                        "text/html",
                        200,
                        0,
                        0,
                        "fetched",
                        None,
                        "abc",
                        "2026-03-08T00:01:00+00:00",
                    ),
                )

                report = run_source_link_qc(db, track_run_id="track1", notes="test")
                row = db.query(
                    "select verdict, inferred_track, reason from asset_source_link_qc where run_id=?",
                    (report["run_id"],),
                )[0]

            self.assertEqual(report["counts"]["supporting"], 1)
            self.assertEqual(str(row["verdict"]), "supporting")
            self.assertEqual(str(row["inferred_track"]), "style_product_decor")
            self.assertIn("supports", str(row["reason"]).lower())

    def test_source_link_qc_marks_conflicting_when_source_page_is_irrelevant(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into classification_runs
                      (id, schema_version, run_type, model_provider, model_name, prompt_version, config_json, created_at, notes)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("track1", "curation_v2", "track_gate", "heuristic", "test", "", "{}", "2026-03-08T00:00:00+00:00", ""),
                )
                db.exec(
                    """
                    insert into classification_runs
                      (id, schema_version, run_type, model_provider, model_name, prompt_version, config_json, created_at, notes)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("enrich1", "curation_v2", "source_link_enrichment", "heuristic", "test", "", "{}", "2026-03-08T00:01:00+00:00", ""),
                )
                db.exec(
                    """
                    insert into assets (id, source, source_ref, source_url, title, imported_at)
                    values (?, ?, ?, ?, ?, ?)
                    """,
                    ("a1", "facebook", "https://example.com/post", "https://epicurious.com/recipe", "Kitchen inspiration", "2026-03-08T00:00:00+00:00"),
                )
                db.exec(
                    """
                    insert into asset_track_assessments
                      (id, run_id, asset_id, track, confidence, is_ambiguous, decision_source, reason, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("ta1", "track1", "a1", "style_product_decor", 0.8, 0, "merged", "winner=style", "2026-03-08T00:00:00+00:00"),
                )
                db.exec(
                    """
                    insert into asset_source_link_enrichment
                      (id, run_id, asset_id, input_url, final_url, final_domain, canonical_url, og_image_url,
                       page_title, og_title, meta_description, og_description, text_excerpt, content_type,
                       http_status, redirect_count, truncated, fetch_status, error, content_hash, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "e1",
                        "enrich1",
                        "a1",
                        "https://epicurious.com/recipe",
                        "https://epicurious.com/recipe",
                        "epicurious.com",
                        "https://epicurious.com/recipe",
                        None,
                        "Easy Pasta Recipe",
                        None,
                        "A quick food recipe for dinner.",
                        None,
                        "Food recipe and cooking guide.",
                        "text/html",
                        200,
                        0,
                        0,
                        "fetched",
                        None,
                        "abc",
                        "2026-03-08T00:01:00+00:00",
                    ),
                )

                report = run_source_link_qc(db, track_run_id="track1", notes="test")
                row = db.query(
                    "select verdict, inferred_track, reason from asset_source_link_qc where run_id=?",
                    (report["run_id"],),
                )[0]

            self.assertEqual(report["counts"]["conflicting"], 1)
            self.assertEqual(str(row["verdict"]), "conflicting")
            self.assertEqual(str(row["inferred_track"]), "irrelevant")
            self.assertIn("instead of", str(row["reason"]).lower())


if __name__ == "__main__":
    unittest.main()
