import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from inspirations.cli import main
from inspirations.db import Db, ensure_schema
from inspirations.title_audit import (
    apply_title_audit_batch,
    concise_title,
    edit_title_audit_candidate,
    mark_title_audit_candidates,
    propose_title,
    review_title_audit_batch,
    run_title_audit,
    stage_title_audit_batch,
    strip_facebook_engagement_prefix,
    undo_title_audit_batch,
)


class TestTitleAudit(unittest.TestCase):
    def test_concise_title_removes_framing_and_background(self):
        text = (
            "A close-up shot of pitted butter olives in a light green bowl, "
            "set against a vibrant green background with descriptive text."
        )
        got = concise_title(text)
        self.assertIn("pitted butter olives", got.lower())
        self.assertNotIn("close-up", got.lower())
        self.assertNotIn("background", got.lower())

    def test_propose_title_for_empty_title_from_ai_summary(self):
        proposal = propose_title(
            source="facebook",
            old_title="",
            source_ref="https://www.facebook.com/reel/123",
            ai_summary=(
                "This image shows a construction site with exposed wooden studs, "
                "various pipes, and spray paint markings on the floor."
            ),
            seo_alt_text="",
        )
        self.assertIsNotNone(proposal)
        new_title, technique = proposal or ("", "")
        self.assertEqual(technique, "empty_title_ai_summary")
        self.assertIn("construction site", new_title.lower())
        self.assertNotIn("this image shows", new_title.lower())

    def test_propose_title_for_saved_link_drops_code_like_suffix(self):
        proposal = propose_title(
            source="facebook",
            old_title="Leslie Brannigan saved a link from Emuaid's post.",
            source_ref="https://www.emuaid.com/pages/eczema-cndrf05",
            ai_summary="",
            seo_alt_text="",
        )
        self.assertIsNotNone(proposal)
        new_title, technique = proposal or ("", "")
        self.assertEqual(technique, "fb_saved_link_slug")
        self.assertEqual(new_title, "Emuaid: Eczema")

    def test_propose_title_for_saved_link_source_name_drops_link_and_domain(self):
        proposal = propose_title(
            source="facebook",
            old_title="Leslie Brannigan saved a link from JoePill.com's post.",
            source_ref="https://joepill.com",
            ai_summary="",
            seo_alt_text="",
        )
        self.assertIsNotNone(proposal)
        new_title, technique = proposal or ("", "")
        self.assertEqual(technique, "fb_saved_link_source_name")
        self.assertEqual(new_title, "JoePill")

    def test_propose_title_for_saved_link_slug_drops_numeric_ids(self):
        proposal = propose_title(
            source="facebook",
            old_title="Leslie Brannigan saved a link from NYT Cooking's post.",
            source_ref="https://cooking.nytimes.com/recipes/1026708-white-bean-feta-and-quick-pickled-celery-salad",
            ai_summary="",
            seo_alt_text="",
        )
        self.assertIsNotNone(proposal)
        new_title, technique = proposal or ("", "")
        self.assertEqual(technique, "fb_saved_link_slug")
        self.assertEqual(new_title, "NYT Cooking: White Bean Feta And Quick Pickled Celery Salad")
        self.assertNotIn("1026708", new_title)

    def test_propose_title_ignores_generic_pin_slug_for_junk_domain(self):
        proposal = propose_title(
            source="pinterest",
            old_title="BlueHost.com",
            source_ref="pinterest://pin/1234567890",
            ai_summary="",
            seo_alt_text="",
        )
        self.assertIsNone(proposal)

    def test_concise_title_avoids_cutoff_tail_words(self):
        text = (
            "Woman with curly hair is smiling at the camera wearing a red cardigan "
            "over a white blouse in a bright room with framed art and plants."
        )
        got = concise_title(text)
        self.assertFalse(got.lower().endswith("over"))
        self.assertIn("red cardigan", got.lower())

    def test_strip_facebook_engagement_prefix_handles_dash_separators(self):
        title = "62K views - 1.8K reactions | Better Building Practices | Texas Signature Inspections"
        self.assertEqual(
            strip_facebook_engagement_prefix(title),
            "Better Building Practices | Texas Signature Inspections",
        )

    def test_strip_facebook_engagement_prefix_keeps_normal_title_intact(self):
        title = "A clever built-in cabinet with a charging drawer"
        self.assertEqual(strip_facebook_engagement_prefix(title), title)

    def test_run_title_audit_excludes_hidden_when_requested(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            table_path = Path(td) / "impact.md"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, ai_summary, triage_status, imported_at)
                    values (?, ?, ?, ?, ?, ?, datetime('now'))
                    """,
                    (
                        "a1",
                        "facebook",
                        "https://www.facebook.com/reel/1",
                        "",
                        "A woman is applying makeup in what appears to be a living room or bedroom setting.",
                        "",
                    ),
                )
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, ai_summary, triage_status, imported_at)
                    values (?, ?, ?, ?, ?, ?, datetime('now'))
                    """,
                    (
                        "a2",
                        "facebook",
                        "https://www.facebook.com/reel/2",
                        "",
                        "A man is speaking to camera.",
                        "hidden",
                    ),
                )
                report = run_title_audit(
                    db,
                    include_hidden=False,
                    table_out=table_path,
                )
            self.assertEqual(report["total_scanned"], 1)
            self.assertEqual(report["candidate_count"], 1)
            self.assertTrue(table_path.exists())

    def test_cli_ai_title_audit_outputs_json_and_writes_table(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            table_path = Path(td) / "impact.md"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, ai_summary, imported_at)
                    values (?, ?, ?, ?, ?, datetime('now'))
                    """,
                    (
                        "a1",
                        "facebook",
                        "https://www.facebook.com/reel/1",
                        "",
                        "A woman is applying makeup in what appears to be a living room or bedroom setting.",
                    ),
                )

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = main(
                    [
                        "--db",
                        str(db_path),
                        "ai",
                        "title-audit",
                        "--table-out",
                        str(table_path),
                    ]
                )
            self.assertEqual(rc, 0)
            payload = json.loads(buf.getvalue())
            self.assertTrue(payload.get("ok"))
            self.assertEqual(payload.get("candidate_count"), 1)
            self.assertEqual(payload.get("table_out"), str(table_path.resolve()))
            self.assertTrue(table_path.exists())

    def test_title_audit_batch_lifecycle_stage_mark_edit_apply_undo(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, ai_summary, imported_at)
                    values (?, ?, ?, ?, ?, datetime('now'))
                    """,
                    (
                        "a1",
                        "facebook",
                        "https://www.facebook.com/reel/1",
                        "",
                        "A woman is applying makeup in what appears to be a bedroom setting.",
                    ),
                )
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, imported_at)
                    values (?, ?, ?, ?, datetime('now'))
                    """,
                    (
                        "a2",
                        "facebook",
                        "https://www.emuaid.com/pages/eczema-cndrf05",
                        "Leslie Brannigan saved a link from Emuaid's post.",
                    ),
                )

                stage = stage_title_audit_batch(db, source="facebook", include_hidden=True)
                batch_id = stage["batch_id"]
                self.assertEqual(stage["candidate_count"], 2)

                marked = mark_title_audit_candidates(
                    db,
                    batch_id=batch_id,
                    status="approved",
                    asset_ids=["a1"],
                )
                self.assertEqual(marked["updated"], 1)

                edited = edit_title_audit_candidate(
                    db,
                    batch_id=batch_id,
                    asset_id="a2",
                    new_title="Emuaid eczema",
                )
                self.assertEqual(edited["status_set"], "edited")

                applied = apply_title_audit_batch(db, batch_id=batch_id)
                self.assertEqual(applied["applied_count"], 2)
                row_a1 = db.query("select title from assets where id = 'a1'")[0]
                row_a2 = db.query("select title from assets where id = 'a2'")[0]
                self.assertTrue(str(row_a1["title"] or "").strip())
                self.assertEqual(row_a2["title"], "Emuaid eczema")

                reviewed = review_title_audit_batch(db, batch_id=batch_id, status="applied")
                self.assertEqual(reviewed["rows_total"], 2)

                undone = undo_title_audit_batch(db, batch_id=batch_id)
                self.assertEqual(undone["undone_count"], 2)
                row_a1_after = db.query("select title from assets where id = 'a1'")[0]
                row_a2_after = db.query("select title from assets where id = 'a2'")[0]
                self.assertEqual(str(row_a1_after["title"] or ""), "")
                self.assertEqual(
                    row_a2_after["title"],
                    "Leslie Brannigan saved a link from Emuaid's post.",
                )

    def test_title_audit_apply_detects_title_drift_without_force(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, ai_summary, imported_at)
                    values (?, ?, ?, ?, ?, datetime('now'))
                    """,
                    (
                        "a1",
                        "facebook",
                        "https://www.facebook.com/reel/1",
                        "",
                        "A woman is applying makeup in what appears to be a bedroom setting.",
                    ),
                )

                stage = stage_title_audit_batch(db, source="facebook")
                batch_id = stage["batch_id"]
                mark_title_audit_candidates(
                    db,
                    batch_id=batch_id,
                    status="approved",
                    asset_ids=["a1"],
                )
                db.exec("update assets set title = ? where id = 'a1'", ("Manual override",))

                blocked = apply_title_audit_batch(db, batch_id=batch_id, force=False)
                self.assertEqual(blocked["applied_count"], 0)
                self.assertEqual(blocked["conflict_count"], 1)

                forced = apply_title_audit_batch(db, batch_id=batch_id, force=True)
                self.assertEqual(forced["applied_count"], 1)
                row = db.query("select title from assets where id = 'a1'")[0]
                self.assertNotEqual(row["title"], "Manual override")

    def test_cli_title_audit_stage_apply_and_undo(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, ai_summary, imported_at)
                    values (?, ?, ?, ?, ?, datetime('now'))
                    """,
                    (
                        "a1",
                        "facebook",
                        "https://www.facebook.com/reel/1",
                        "",
                        "A woman is applying makeup in what appears to be a bedroom setting.",
                    ),
                )

            stage_buf = io.StringIO()
            with redirect_stdout(stage_buf):
                rc = main(["--db", str(db_path), "ai", "title-audit-stage", "--source", "facebook"])
            self.assertEqual(rc, 0)
            stage_payload = json.loads(stage_buf.getvalue())
            self.assertTrue(stage_payload.get("ok"))
            batch_id = str(stage_payload.get("batch_id") or "")
            self.assertTrue(batch_id)

            review_buf = io.StringIO()
            with redirect_stdout(review_buf):
                rc = main(["--db", str(db_path), "ai", "title-audit-review", "--batch-id", batch_id])
            self.assertEqual(rc, 0)
            review_payload = json.loads(review_buf.getvalue())
            self.assertEqual(review_payload.get("rows_total"), 1)
            asset_id = review_payload["candidates"][0]["asset_id"]

            mark_buf = io.StringIO()
            with redirect_stdout(mark_buf):
                rc = main(
                    [
                        "--db",
                        str(db_path),
                        "ai",
                        "title-audit-mark",
                        "--batch-id",
                        batch_id,
                        "--asset-id",
                        asset_id,
                        "--status",
                        "approved",
                    ]
                )
            self.assertEqual(rc, 0)
            mark_payload = json.loads(mark_buf.getvalue())
            self.assertEqual(mark_payload.get("updated"), 1)

            apply_buf = io.StringIO()
            with redirect_stdout(apply_buf):
                rc = main(["--db", str(db_path), "ai", "title-audit-apply", "--batch-id", batch_id])
            self.assertEqual(rc, 0)
            apply_payload = json.loads(apply_buf.getvalue())
            self.assertEqual(apply_payload.get("applied_count"), 1)

            undo_buf = io.StringIO()
            with redirect_stdout(undo_buf):
                rc = main(["--db", str(db_path), "ai", "title-audit-undo", "--batch-id", batch_id])
            self.assertEqual(rc, 0)
            undo_payload = json.loads(undo_buf.getvalue())
            self.assertEqual(undo_payload.get("undone_count"), 1)

            with Db(db_path) as db:
                row = db.query("select title from assets where id = 'a1'")[0]
            self.assertEqual(str(row["title"] or ""), "")
