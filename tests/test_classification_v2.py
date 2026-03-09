import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from inspirations.classification_v2 import run_multi_axis_inference_v2, run_track_gate_v2
from inspirations.cli import main
from inspirations.db import Db, ensure_schema
from inspirations.store import add_items_to_collection, create_collection


class TestClassificationV2(unittest.TestCase):
    def test_run_track_gate_v2_writes_assessments_and_skips_hidden(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                assets = [
                    (
                        "a_style",
                        "pinterest",
                        "pin://1",
                        "White oak kitchen with brass faucet",
                        "pins: kitchen",
                        "2026-03-06T00:00:00+00:00",
                    ),
                    (
                        "a_construction",
                        "pinterest",
                        "pin://2",
                        "Foundation waterproofing and drainage details",
                        "pins: slab",
                        "2026-03-06T00:00:01+00:00",
                    ),
                    (
                        "a_irrelevant",
                        "facebook",
                        "fb://1",
                        "Makeup tutorial for glowing skin",
                        "",
                        "2026-03-06T00:00:02+00:00",
                    ),
                    (
                        "a_video",
                        "facebook",
                        "fb://video1",
                        "",
                        "",
                        "2026-03-06T00:00:03+00:00",
                    ),
                    (
                        "a_hidden",
                        "pinterest",
                        "pin://hidden",
                        "Kitchen with blue island",
                        "pins: kitchen",
                        "2026-03-06T00:00:04+00:00",
                    ),
                ]
                for asset_id, source, source_ref, title, board, imported_at in assets:
                    db.exec(
                        """
                        insert into assets (id, source, source_ref, title, board, imported_at)
                        values (?, ?, ?, ?, ?, ?)
                        """,
                        (asset_id, source, source_ref, title, board, imported_at),
                    )
                db.exec(
                    """
                    insert into asset_labels (id, asset_id, label, confidence, source, model, run_id, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("lab1", "a_style", "kitchen", 0.9, "ai", "gemini", "r1", "2026-03-06T00:01:00+00:00"),
                )
                db.exec(
                    """
                    insert into asset_labels (id, asset_id, label, confidence, source, model, run_id, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "lab2",
                        "a_construction",
                        "foundation",
                        0.9,
                        "ai",
                        "gemini",
                        "r1",
                        "2026-03-06T00:01:01+00:00",
                    ),
                )
                db.exec(
                    """
                    insert into asset_ai (id, asset_id, provider, model, summary, json, created_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "ai_video_1",
                        "a_video",
                        "gemini-video",
                        "gemini-2.5-flash",
                        "Construction reel",
                        json.dumps(
                            {
                                "category": "construction",
                                "subcategory": "general",
                                "relevant_to_home_design": True,
                                "confidence": 0.91,
                            }
                        ),
                        "2026-03-06T00:02:00+00:00",
                    ),
                )
                hidden = create_collection(db, name="hidden")
                add_items_to_collection(db, collection_id=hidden["id"], asset_ids=["a_hidden"])
                ensure_schema(db)

                report = run_track_gate_v2(db)
                rows = db.query(
                    """
                    select asset_id, track
                    from asset_track_assessments
                    where run_id=?
                    order by asset_id
                    """,
                    (report["run_id"],),
                )
                evidence_count = db.query_value(
                    "select count(*) from asset_axis_evidence where run_id=?",
                    (report["run_id"],),
                )

            self.assertEqual(report["candidate_count"], 4)
            self.assertEqual(report["assessments_written"], 4)
            self.assertGreater(int(evidence_count or 0), 0)
            track_by_asset = {str(r["asset_id"]): str(r["track"]) for r in rows}
            self.assertEqual(track_by_asset["a_style"], "style_product_decor")
            self.assertEqual(track_by_asset["a_construction"], "construction_concern")
            self.assertEqual(track_by_asset["a_irrelevant"], "irrelevant")
            self.assertEqual(track_by_asset["a_video"], "construction_concern")
            self.assertNotIn("a_hidden", track_by_asset)

    def test_cli_curation_track_gate_v2_outputs_json(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, board, imported_at)
                    values (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "a1",
                        "pinterest",
                        "pin://1",
                        "Warm kitchen with brass pendants",
                        "pins: kitchen",
                        "2026-03-06T00:00:00+00:00",
                    ),
                )
                ensure_schema(db)

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = main(["--db", str(db_path), "curation", "track-gate-v2", "--limit", "1", "--notes", "test run"])

            self.assertEqual(rc, 0)
            payload = json.loads(buf.getvalue())
            self.assertTrue(payload.get("ok"))
            self.assertEqual(payload.get("candidate_count"), 1)
            self.assertEqual(payload.get("assessments_written"), 1)
            self.assertTrue(str(payload.get("run_id") or "").strip())

    def test_track_gate_v2_prefers_construction_for_unfinished_build_scene(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, board, category, imported_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "a1",
                        "facebook",
                        "fb://construction-scene",
                        "Construction site with exposed studs, pipes, and spray paint",
                        "building",
                        "home_design",
                        "2026-03-06T00:00:00+00:00",
                    ),
                )
                db.exec(
                    """
                    insert into asset_ai (id, asset_id, provider, model, summary, json, created_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "ai1",
                        "a1",
                        "gemini",
                        "gemini-2.5-flash",
                        "Interior under construction",
                        json.dumps(
                            {
                                "image_type": "interior",
                                "materials": ["wood", "plastic", "foam", "osb"],
                                "elements": ["construction", "unfinished", "framing", "plumbing"],
                                "tags": ["construction", "building", "framing", "insulation", "plumbing"],
                            }
                        ),
                        "2026-03-06T00:01:00+00:00",
                    ),
                )

                report = run_track_gate_v2(db)
                row = db.query(
                    "select track from asset_track_assessments where run_id=? and asset_id=?",
                    (report["run_id"], "a1"),
                )[0]

            self.assertEqual(str(row["track"]), "construction_concern")

    def test_track_gate_v2_marks_low_signal_supplement_post_irrelevant(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, category, imported_at)
                    values (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "a1",
                        "facebook",
                        "fb://vitamins",
                        "Vitamin and supplement timing guide",
                        "home_design",
                        "2026-03-06T00:00:00+00:00",
                    ),
                )
                report = run_track_gate_v2(db)
                row = db.query(
                    "select track from asset_track_assessments where run_id=? and asset_id=?",
                    (report["run_id"], "a1"),
                )[0]

            self.assertEqual(str(row["track"]), "irrelevant")

    def test_track_gate_v2_does_not_promote_generic_code_pin_to_construction(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, category, imported_at)
                    values (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "a1",
                        "pinterest",
                        "pin://altcode",
                        "Special ALT Characters",
                        "home_design",
                        "2026-03-06T00:00:00+00:00",
                    ),
                )
                db.exec(
                    """
                    insert into asset_labels (id, asset_id, label, confidence, source, model, run_id, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("lab1", "a1", "code", 0.9, "ai", "gemini", "r1", "2026-03-06T00:01:00+00:00"),
                )
                db.exec(
                    """
                    insert into asset_ai (id, asset_id, provider, model, summary, json, created_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "ai1",
                        "a1",
                        "gemini",
                        "gemini-2.5-flash",
                        "Text chart",
                        json.dumps({"tags": ["code", "typography"]}),
                        "2026-03-06T00:02:00+00:00",
                    ),
                )
                report = run_track_gate_v2(db)
                row = db.query(
                    "select track from asset_track_assessments where run_id=? and asset_id=?",
                    (report["run_id"], "a1"),
                )[0]

            self.assertNotEqual(str(row["track"]), "construction_concern")

    def test_track_gate_v2_keeps_patio_reference_on_style_track(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, board, category, imported_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "a1",
                        "pinterest",
                        "pin://patio",
                        "Traditional patio with concrete pavers and lanterns",
                        "garden",
                        "home_design",
                        "2026-03-06T00:00:00+00:00",
                    ),
                )
                for label_id, label in (("lab1", "patio"), ("lab2", "concrete pavers"), ("lab3", "lantern")):
                    db.exec(
                        """
                        insert into asset_labels (id, asset_id, label, confidence, source, model, run_id, created_at)
                        values (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (label_id, "a1", label, 0.9, "ai", "gemini", "r1", "2026-03-06T00:01:00+00:00"),
                    )
                db.exec(
                    """
                    insert into asset_ai (id, asset_id, provider, model, summary, json, created_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "ai1",
                        "a1",
                        "gemini",
                        "gemini-2.5-flash",
                        "Outdoor patio scene",
                        json.dumps(
                            {
                                "image_type": "exterior",
                                "rooms": ["patio"],
                                "styles": ["traditional"],
                                "materials": ["concrete"],
                                "tags": ["patio", "concrete pavers", "lantern"],
                            }
                        ),
                        "2026-03-06T00:02:00+00:00",
                    ),
                )
                report = run_track_gate_v2(db)
                row = db.query(
                    "select track from asset_track_assessments where run_id=? and asset_id=?",
                    (report["run_id"], "a1"),
                )[0]

            self.assertEqual(str(row["track"]), "style_product_decor")

    def test_track_gate_v2_moves_house_plan_reference_to_style(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, board, category, imported_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "a1",
                        "pinterest",
                        "pin://house-plan",
                        "Plan 70865MK: Balanced Modern Farmhouse Plan - 2930 Sq. Ft.",
                        "house-plans",
                        "home_design",
                        "2026-03-06T00:00:00+00:00",
                    ),
                )
                for label_id, label in (
                    ("lab1", "floor plan"),
                    ("lab2", "house plan"),
                    ("lab3", "architectural drawing"),
                    ("lab4", "kitchen layout"),
                    ("lab5", "dining room"),
                ):
                    db.exec(
                        """
                        insert into asset_labels (id, asset_id, label, confidence, source, model, run_id, created_at)
                        values (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (label_id, "a1", label, 0.9, "ai", "gemini", "r1", "2026-03-06T00:01:00+00:00"),
                    )
                db.exec(
                    """
                    insert into asset_ai (id, asset_id, provider, model, summary, json, created_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "ai1",
                        "a1",
                        "gemini",
                        "gemini-2.5-flash",
                        "Residential floor plan",
                        json.dumps(
                            {
                                "image_type": "plan",
                                "tags": ["floor plan", "house plan", "architectural drawing", "residential design"],
                                "rooms": ["kitchen", "dining room"],
                            }
                        ),
                        "2026-03-06T00:02:00+00:00",
                    ),
                )

                report = run_track_gate_v2(db)
                row = db.query(
                    "select track from asset_track_assessments where run_id=? and asset_id=?",
                    (report["run_id"], "a1"),
                )[0]

            self.assertEqual(str(row["track"]), "style_product_decor")

    def test_track_gate_v2_moves_style_material_reference_to_style(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, board, category, imported_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "a1",
                        "pinterest",
                        "pin://brick-stain",
                        "Houston brick stain",
                        "misc",
                        "home_design",
                        "2026-03-06T00:00:00+00:00",
                    ),
                )
                for label_id, label in (
                    ("lab1", "brick samples"),
                    ("lab2", "color palette"),
                    ("lab3", "building material"),
                    ("lab4", "construction material"),
                ):
                    db.exec(
                        """
                        insert into asset_labels (id, asset_id, label, confidence, source, model, run_id, created_at)
                        values (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (label_id, "a1", label, 0.9, "ai", "gemini", "r1", "2026-03-06T00:01:00+00:00"),
                    )
                db.exec(
                    """
                    insert into asset_ai (id, asset_id, provider, model, summary, json, created_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "ai1",
                        "a1",
                        "gemini",
                        "gemini-2.5-flash",
                        "Brick stain sample board",
                        json.dumps(
                            {
                                "image_type": "product",
                                "tags": ["brick", "samples", "color palette", "building material"],
                                "materials": ["brick"],
                            }
                        ),
                        "2026-03-06T00:02:00+00:00",
                    ),
                )

                report = run_track_gate_v2(db)
                row = db.query(
                    "select track from asset_track_assessments where run_id=? and asset_id=?",
                    (report["run_id"], "a1"),
                )[0]

            self.assertEqual(str(row["track"]), "style_product_decor")

    def test_track_gate_v2_moves_style_finish_reference_document_to_style(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, board, category, imported_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "a1",
                        "pinterest",
                        "pin://brick-wash",
                        "Brick wall with instructions for whitewash",
                        "misc",
                        "home_design",
                        "2026-03-06T00:00:00+00:00",
                    ),
                )
                for label_id, label in (
                    ("lab1", "brick treatment"),
                    ("lab2", "whitewash"),
                    ("lab3", "brick wash"),
                    ("lab4", "masonry"),
                ):
                    db.exec(
                        """
                        insert into asset_labels (id, asset_id, label, confidence, source, model, run_id, created_at)
                        values (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (label_id, "a1", label, 0.9, "ai", "gemini", "r1", "2026-03-06T00:01:00+00:00"),
                    )
                db.exec(
                    """
                    insert into asset_ai (id, asset_id, provider, model, summary, json, created_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "ai1",
                        "a1",
                        "gemini",
                        "gemini-2.5-flash",
                        "Brick whitewash guide",
                        json.dumps(
                            {
                                "image_type": "document",
                                "tags": ["brick treatment", "whitewash", "brick wash", "masonry"],
                            }
                        ),
                        "2026-03-06T00:02:00+00:00",
                    ),
                )

                report = run_track_gate_v2(db)
                row = db.query(
                    "select track from asset_track_assessments where run_id=? and asset_id=?",
                    (report["run_id"], "a1"),
                )[0]

            self.assertEqual(str(row["track"]), "style_product_decor")

    def test_track_gate_v2_marks_survival_gear_pin_irrelevant(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, board, category, imported_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "a1",
                        "pinterest",
                        "pin://survival",
                        "Bug out bag essentials checklist",
                        "misc",
                        "home_design",
                        "2026-03-06T00:00:00+00:00",
                    ),
                )
                db.exec(
                    """
                    insert into asset_ai (id, asset_id, provider, model, summary, json, created_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "ai1",
                        "a1",
                        "gemini",
                        "gemini-2.5-flash",
                        "Preparedness gear laid out on a table",
                        json.dumps(
                            {
                                "image_type": "other",
                                "tags": ["bug out bag", "emergency preparedness", "survival gear", "camping"],
                            }
                        ),
                        "2026-03-06T00:02:00+00:00",
                    ),
                )

                report = run_track_gate_v2(db)
                row = db.query(
                    "select track from asset_track_assessments where run_id=? and asset_id=?",
                    (report["run_id"], "a1"),
                )[0]

            self.assertEqual(str(row["track"]), "irrelevant")

    def test_track_gate_v2_moves_repair_reference_to_maintenance_diy(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, board, category, imported_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "a1",
                        "pinterest",
                        "pin://repair",
                        "How to repair cracked concrete",
                        "misc",
                        "home_design",
                        "2026-03-06T00:00:00+00:00",
                    ),
                )
                for label_id, label in (
                    ("lab1", "repair"),
                    ("lab2", "cracked concrete"),
                    ("lab3", "home improvement"),
                ):
                    db.exec(
                        """
                        insert into asset_labels (id, asset_id, label, confidence, source, model, run_id, created_at)
                        values (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (label_id, "a1", label, 0.9, "ai", "gemini", "r1", "2026-03-06T00:01:00+00:00"),
                    )
                db.exec(
                    """
                    insert into asset_ai (id, asset_id, provider, model, summary, json, created_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "ai1",
                        "a1",
                        "gemini",
                        "gemini-2.5-flash",
                        "Concrete repair tip",
                        json.dumps(
                            {
                                "image_type": "exterior",
                                "tags": ["repair", "cracked concrete", "home improvement"],
                            }
                        ),
                        "2026-03-06T00:02:00+00:00",
                    ),
                )

                report = run_track_gate_v2(db)
                row = db.query(
                    "select track from asset_track_assessments where run_id=? and asset_id=?",
                    (report["run_id"], "a1"),
                )[0]

            self.assertEqual(str(row["track"]), "home_maintenance_diy")

    def test_track_gate_v2_keeps_new_build_electrical_on_construction(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, board, category, imported_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "a1",
                        "pinterest",
                        "pin://electrical",
                        "Electrical Must-Haves for a New Build",
                        "house-plans",
                        "home_design",
                        "2026-03-06T00:00:00+00:00",
                    ),
                )
                for label_id, label in (
                    ("lab1", "electrical"),
                    ("lab2", "new build"),
                    ("lab3", "framing"),
                ):
                    db.exec(
                        """
                        insert into asset_labels (id, asset_id, label, confidence, source, model, run_id, created_at)
                        values (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (label_id, "a1", label, 0.9, "ai", "gemini", "r1", "2026-03-06T00:01:00+00:00"),
                    )
                db.exec(
                    """
                    insert into asset_ai (id, asset_id, provider, model, summary, json, created_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "ai1",
                        "a1",
                        "gemini",
                        "gemini-2.5-flash",
                        "New build electrical planning",
                        json.dumps(
                            {
                                "image_type": "other",
                                "tags": ["electrical", "new build", "framing"],
                            }
                        ),
                        "2026-03-06T00:02:00+00:00",
                    ),
                )

                report = run_track_gate_v2(db)
                row = db.query(
                    "select track from asset_track_assessments where run_id=? and asset_id=?",
                    (report["run_id"], "a1"),
                )[0]

            self.assertEqual(str(row["track"]), "construction_concern")

    def test_track_gate_v2_moves_rainwater_harvesting_to_construction(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, board, category, imported_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "a1",
                        "facebook",
                        "fb://rainwater",
                        "DIY Rainwater Harvesting System for Tiny House",
                        "Sustainable Living | Tiny House Systems | Rainwater Harvesting",
                        "diy",
                        "2026-03-06T00:00:00+00:00",
                    ),
                )
                for label_id, label in (
                    ("lab1", "rainwater harvesting system"),
                    ("lab2", "underground tank"),
                    ("lab3", "gutters"),
                ):
                    db.exec(
                        """
                        insert into asset_labels (id, asset_id, label, confidence, source, model, run_id, created_at)
                        values (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (label_id, "a1", label, 0.9, "ai", "gemini", "r1", "2026-03-06T00:01:00+00:00"),
                    )
                db.exec(
                    """
                    insert into asset_ai (id, asset_id, provider, model, summary, json, created_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "ai1",
                        "a1",
                        "gemini-video",
                        "gemini-2.5-flash",
                        "DIY rainwater harvesting system",
                        json.dumps(
                            {
                                "category": "diy",
                                "subcategory": "exterior",
                                "confidence": 1.0,
                                "elements": ["rainwater harvesting system", "underground tank", "gutters"],
                            }
                        ),
                        "2026-03-06T00:02:00+00:00",
                    ),
                )
                report = run_track_gate_v2(db)
                row = db.query(
                    "select track from asset_track_assessments where run_id=? and asset_id=?",
                    (report["run_id"], "a1"),
                )[0]

            self.assertEqual(str(row["track"]), "construction_concern")

    def test_track_gate_v2_moves_garage_floor_finish_reference_to_construction(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, board, category, imported_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "a1",
                        "facebook",
                        "fb://garage-floor",
                        "DIY Garage Floor Epoxy Coating",
                        "Garage Renovation",
                        "diy",
                        "2026-03-06T00:00:00+00:00",
                    ),
                )
                for label_id, label in (
                    ("lab1", "garage floor"),
                    ("lab2", "epoxy coating"),
                    ("lab3", "anti-skid material"),
                ):
                    db.exec(
                        """
                        insert into asset_labels (id, asset_id, label, confidence, source, model, run_id, created_at)
                        values (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (label_id, "a1", label, 0.9, "ai", "gemini", "r1", "2026-03-06T00:01:00+00:00"),
                    )
                db.exec(
                    """
                    insert into asset_ai (id, asset_id, provider, model, summary, json, created_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "ai1",
                        "a1",
                        "gemini-video",
                        "gemini-2.5-flash",
                        "DIY garage floor epoxy coating",
                        json.dumps(
                            {
                                "category": "diy",
                                "subcategory": "garage",
                                "confidence": 1.0,
                                "elements": ["garage floor", "epoxy coating", "anti-skid material"],
                                "materials": ["epoxy", "paint"],
                            }
                        ),
                        "2026-03-06T00:02:00+00:00",
                    ),
                )
                report = run_track_gate_v2(db)
                row = db.query(
                    "select track from asset_track_assessments where run_id=? and asset_id=?",
                    (report["run_id"], "a1"),
                )[0]

            self.assertEqual(str(row["track"]), "construction_concern")

    def test_track_gate_v2_moves_painting_tip_to_style(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, board, category, imported_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "a1",
                        "facebook",
                        "fb://paint-tip",
                        "Color drenching a room - what do you do with the doors?",
                        "Painting Tips",
                        "diy",
                        "2026-03-06T00:00:00+00:00",
                    ),
                )
                for label_id, label in (
                    ("lab1", "paint"),
                    ("lab2", "door casing"),
                    ("lab3", "door"),
                ):
                    db.exec(
                        """
                        insert into asset_labels (id, asset_id, label, confidence, source, model, run_id, created_at)
                        values (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (label_id, "a1", label, 0.9, "ai", "gemini", "r1", "2026-03-06T00:01:00+00:00"),
                    )
                db.exec(
                    """
                    insert into asset_ai (id, asset_id, provider, model, summary, json, created_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "ai1",
                        "a1",
                        "gemini-video",
                        "gemini-2.5-flash",
                        "Painting door casings during color drenching",
                        json.dumps(
                            {
                                "category": "diy",
                                "subcategory": "general",
                                "confidence": 1.0,
                                "elements": ["door", "door casing", "paint"],
                                "materials": ["paint"],
                            }
                        ),
                        "2026-03-06T00:02:00+00:00",
                    ),
                )
                report = run_track_gate_v2(db)
                row = db.query(
                    "select track from asset_track_assessments where run_id=? and asset_id=?",
                    (report["run_id"], "a1"),
                )[0]

            self.assertEqual(str(row["track"]), "style_product_decor")

    def test_track_gate_v2_moves_landscaping_reference_to_style(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, board, category, imported_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "a1",
                        "facebook",
                        "fb://landscaping",
                        "Why Verbena is a great perennial recommendation",
                        "Gardening & Landscaping",
                        "diy",
                        "2026-03-06T00:00:00+00:00",
                    ),
                )
                for label_id, label in (
                    ("lab1", "flowers"),
                    ("lab2", "garden"),
                    ("lab3", "landscaping"),
                ):
                    db.exec(
                        """
                        insert into asset_labels (id, asset_id, label, confidence, source, model, run_id, created_at)
                        values (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (label_id, "a1", label, 0.9, "ai", "gemini", "r1", "2026-03-06T00:01:00+00:00"),
                    )
                db.exec(
                    """
                    insert into asset_ai (id, asset_id, provider, model, summary, json, created_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "ai1",
                        "a1",
                        "gemini-video",
                        "gemini-2.5-flash",
                        "A landscaping reference about verbena",
                        json.dumps(
                            {
                                "category": "diy",
                                "subcategory": "landscaping",
                                "confidence": 0.9,
                                "elements": ["flowers", "garden", "plants"],
                            }
                        ),
                        "2026-03-06T00:02:00+00:00",
                    ),
                )
                report = run_track_gate_v2(db)
                row = db.query(
                    "select track from asset_track_assessments where run_id=? and asset_id=?",
                    (report["run_id"], "a1"),
                )[0]

            self.assertEqual(str(row["track"]), "style_product_decor")

    def test_track_gate_v2_honors_manual_track_override(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, board, category, imported_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "a1",
                        "facebook",
                        "fb://override",
                        "Generic gutter tip",
                        "Exterior Home Maintenance",
                        "diy",
                        "2026-03-06T00:00:00+00:00",
                    ),
                )
                db.exec(
                    """
                    insert into asset_overrides
                      (id, asset_id, track, axis_name, axis_value, operation, actor, note, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "ov1",
                        "a1",
                        "construction_concern",
                        "track",
                        "construction_concern",
                        "set",
                        "Jim",
                        "Jim said this is an idea for construction.",
                        "2026-03-06T00:01:00+00:00",
                    ),
                )
                report = run_track_gate_v2(db)
                row = db.query(
                    "select track, decision_source from asset_track_assessments where run_id=? and asset_id=?",
                    (report["run_id"], "a1"),
                )[0]

            self.assertEqual(str(row["track"]), "construction_concern")
            self.assertEqual(str(row["decision_source"]), "manual_override")

    def test_track_gate_v2_marks_cleaning_diy_video_irrelevant(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, board, category, imported_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "a1",
                        "facebook",
                        "fb://cleaning",
                        "So soapy... cold water works! #cleaninghacksandtips #Mopping",
                        "Cleaning Tips",
                        "diy",
                        "2026-03-06T00:00:00+00:00",
                    ),
                )
                for label_id, label in (
                    ("lab1", "shower"),
                    ("lab2", "tile"),
                    ("lab3", "glass shower door"),
                    ("lab4", "cleaning brush"),
                    ("lab5", "bathroom"),
                ):
                    db.exec(
                        """
                        insert into asset_labels (id, asset_id, label, confidence, source, model, run_id, created_at)
                        values (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (label_id, "a1", label, 0.9, "ai", "gemini", "r1", "2026-03-06T00:01:00+00:00"),
                    )
                db.exec(
                    """
                    insert into asset_ai (id, asset_id, provider, model, summary, json, created_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "ai1",
                        "a1",
                        "gemini-video",
                        "gemini-2.5-flash",
                        "A woman demonstrates cleaning a shower with a brush",
                        json.dumps(
                            {
                                "category": "diy",
                                "subcategory": "bathroom",
                                "relevant_to_home_design": True,
                                "confidence": 0.88,
                                "elements": ["shower", "tile", "glass shower door", "cleaning brush"],
                                "materials": ["tile", "glass"],
                            }
                        ),
                        "2026-03-06T00:02:00+00:00",
                    ),
                )

                report = run_track_gate_v2(db)
                row = db.query(
                    "select track from asset_track_assessments where run_id=? and asset_id=?",
                    (report["run_id"], "a1"),
                )[0]

            self.assertEqual(str(row["track"]), "irrelevant")

    def test_track_gate_v2_marks_workout_scene_irrelevant_when_raw_and_visual_agree(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, board, category, imported_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "a1",
                        "pinterest",
                        "pin://workout",
                        "Body Workout",
                        "workout",
                        "home_design",
                        "2026-03-06T00:00:00+00:00",
                    ),
                )
                db.exec(
                    """
                    insert into asset_ai (id, asset_id, provider, model, summary, json, created_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "ai1",
                        "a1",
                        "gemini",
                        "gemini-2.5-flash",
                        "A woman exercising in a living room fitness scene.",
                        json.dumps(
                            {
                                "image_type": "interior",
                                "rooms": ["living room"],
                                "tags": ["workout", "exercise", "fitness"],
                                "elements": ["person exercising"],
                            }
                        ),
                        "2026-03-06T00:02:00+00:00",
                    ),
                )

                report = run_track_gate_v2(db)
                row = db.query(
                    "select track, is_ambiguous from asset_track_assessments where run_id=? and asset_id=?",
                    (report["run_id"], "a1"),
                )[0]

            self.assertEqual(str(row["track"]), "irrelevant")
            self.assertEqual(int(row["is_ambiguous"]), 0)

    def test_track_gate_v2_marks_makeup_lesson_irrelevant_when_raw_and_visual_agree(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, board, category, imported_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "a1",
                        "pinterest",
                        "pin://makeup",
                        "Professional Makeup Lesson",
                        "makeup",
                        "home_design",
                        "2026-03-06T00:00:00+00:00",
                    ),
                )
                db.exec(
                    """
                    insert into asset_ai (id, asset_id, provider, model, summary, json, created_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "ai1",
                        "a1",
                        "gemini",
                        "gemini-2.5-flash",
                        "A makeup artist applies cosmetics in a salon.",
                        json.dumps(
                            {
                                "image_type": "interior",
                                "tags": ["makeup", "beauty", "salon"],
                                "elements": ["makeup artist", "cosmetics"],
                            }
                        ),
                        "2026-03-06T00:02:00+00:00",
                    ),
                )

                report = run_track_gate_v2(db)
                row = db.query(
                    "select track, is_ambiguous from asset_track_assessments where run_id=? and asset_id=?",
                    (report["run_id"], "a1"),
                )[0]

            self.assertEqual(str(row["track"]), "irrelevant")
            self.assertEqual(int(row["is_ambiguous"]), 0)

    def test_track_gate_v2_marks_workout_pin_irrelevant_when_board_and_title_agree(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, board, category, imported_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "a1",
                        "pinterest",
                        "pin://stairs-workout",
                        "At Home Workout.",
                        "workout",
                        "home_design",
                        "2026-03-06T00:00:00+00:00",
                    ),
                )
                db.exec(
                    """
                    insert into asset_ai (id, asset_id, provider, model, summary, json, created_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "ai1",
                        "a1",
                        "gemini",
                        "gemini-2.5-flash",
                        "A person is walking up a carpeted staircase with a dark banister.",
                        json.dumps(
                            {
                                "image_type": "interior",
                                "tags": ["staircase", "carpeted stairs", "interior"],
                                "materials": ["carpet", "wood"],
                            }
                        ),
                        "2026-03-06T00:02:00+00:00",
                    ),
                )

                report = run_track_gate_v2(db)
                row = db.query(
                    "select track, is_ambiguous from asset_track_assessments where run_id=? and asset_id=?",
                    (report["run_id"], "a1"),
                )[0]

            self.assertEqual(str(row["track"]), "irrelevant")
            self.assertEqual(int(row["is_ambiguous"]), 0)

    def test_track_gate_v2_marks_eyeshadow_guide_irrelevant(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, board, category, imported_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "a1",
                        "pinterest",
                        "pin://eyeshadow",
                        "Eyeshadow Basics",
                        "favorite-places-spaces",
                        "home_design",
                        "2026-03-06T00:00:00+00:00",
                    ),
                )
                for label_id, label in (("lab1", "eye makeup"), ("lab2", "makeup tutorial"), ("lab3", "document")):
                    db.exec(
                        """
                        insert into asset_labels (id, asset_id, label, confidence, source, model, run_id, created_at)
                        values (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (label_id, "a1", label, 0.9, "ai", "gemini", "r1", "2026-03-06T00:01:00+00:00"),
                    )
                db.exec(
                    """
                    insert into asset_ai (id, asset_id, provider, model, summary, json, created_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "ai1",
                        "a1",
                        "gemini",
                        "gemini-2.5-flash",
                        "Step-by-step eyeshadow application guide showing eyelid and brow bone areas.",
                        json.dumps(
                            {
                                "image_type": "document",
                                "tags": ["eye makeup", "eyeshadow guide", "makeup tutorial"],
                                "elements": ["eyelid", "eyebrow"],
                            }
                        ),
                        "2026-03-06T00:02:00+00:00",
                    ),
                )

                report = run_track_gate_v2(db)
                row = db.query(
                    "select track, is_ambiguous from asset_track_assessments where run_id=? and asset_id=?",
                    (report["run_id"], "a1"),
                )[0]

            self.assertEqual(str(row["track"]), "irrelevant")
            self.assertEqual(int(row["is_ambiguous"]), 0)

    def test_track_gate_v2_keeps_color_palette_reference_on_style_track(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, board, category, imported_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "a1",
                        "pinterest",
                        "pin://palette",
                        "Bye bye, black beauty...",
                        "misc",
                        "home_design",
                        "2026-03-06T00:00:00+00:00",
                    ),
                )
                for label_id, label in (("lab1", "color palette"), ("lab2", "paint swatches"), ("lab3", "neutral colors")):
                    db.exec(
                        """
                        insert into asset_labels (id, asset_id, label, confidence, source, model, run_id, created_at)
                        values (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (label_id, "a1", label, 0.9, "ai", "gemini", "r1", "2026-03-06T00:01:00+00:00"),
                    )
                db.exec(
                    """
                    insert into asset_ai (id, asset_id, provider, model, summary, json, created_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "ai1",
                        "a1",
                        "gemini",
                        "gemini-2.5-flash",
                        "A grid of neutral paint swatches with named colors.",
                        json.dumps(
                            {
                                "image_type": "document",
                                "tags": ["color palette", "paint swatches", "neutral colors"],
                                "elements": ["color chart"],
                            }
                        ),
                        "2026-03-06T00:02:00+00:00",
                    ),
                )

                report = run_track_gate_v2(db)
                row = db.query(
                    "select track, is_ambiguous from asset_track_assessments where run_id=? and asset_id=?",
                    (report["run_id"], "a1"),
                )[0]

            self.assertEqual(str(row["track"]), "style_product_decor")
            self.assertEqual(int(row["is_ambiguous"]), 0)

    def test_track_gate_v2_treats_leslie_magazine_clips_as_style_signal(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, board, category, imported_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "a1",
                        "scan",
                        "scan://magclips",
                        "Leslie's Magazine Clips - doc 52 p2",
                        None,
                        "home_design",
                        "2026-03-06T00:00:00+00:00",
                    ),
                )
                for label_id, label in (("lab1", "builder"), ("lab2", "roof"), ("lab3", "trim"), ("lab4", "exterior")):
                    db.exec(
                        """
                        insert into asset_labels (id, asset_id, label, confidence, source, model, run_id, created_at)
                        values (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (label_id, "a1", label, 0.9, "ai", "gemini", "r1", "2026-03-06T00:01:00+00:00"),
                    )
                db.exec(
                    """
                    insert into asset_ai (id, asset_id, provider, model, summary, json, created_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "ai1",
                        "a1",
                        "gemini",
                        "gemini-2.5-flash",
                        "Exterior house elevation reference.",
                        json.dumps(
                            {
                                "image_type": "document",
                                "styles": ["colonial"],
                                "tags": ["builder", "roof", "trim", "exterior"],
                            }
                        ),
                        "2026-03-06T00:02:00+00:00",
                    ),
                )

                report = run_track_gate_v2(db)
                row = db.query(
                    "select track, is_ambiguous from asset_track_assessments where run_id=? and asset_id=?",
                    (report["run_id"], "a1"),
                )[0]

            self.assertEqual(str(row["track"]), "style_product_decor")
            self.assertEqual(int(row["is_ambiguous"]), 0)

    def test_track_gate_v2_marks_woodworking_reference_irrelevant(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, board, category, imported_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "a1",
                        "pinterest",
                        "pin://woodworking",
                        "Power Tool Woodworking for Everyone Online Overarm Pin Router",
                        "misc",
                        "home_design",
                        "2026-03-06T00:00:00+00:00",
                    ),
                )
                for label_id, label in (
                    ("lab1", "woodworking"),
                    ("lab2", "joinery"),
                    ("lab3", "technical drawing"),
                    ("lab4", "carpentry"),
                ):
                    db.exec(
                        """
                        insert into asset_labels (id, asset_id, label, confidence, source, model, run_id, created_at)
                        values (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (label_id, "a1", label, 0.9, "ai", "gemini", "r1", "2026-03-06T00:01:00+00:00"),
                    )
                db.exec(
                    """
                    insert into asset_ai (id, asset_id, provider, model, summary, json, created_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "ai1",
                        "a1",
                        "gemini",
                        "gemini-2.5-flash",
                        "Document showing woodworking joint diagrams",
                        json.dumps(
                            {
                                "image_type": "document",
                                "tags": ["woodworking", "joinery", "construction details", "carpentry", "furniture making"],
                                "elements": ["wood joints", "diagrams"],
                                "text_in_image": ["through dado", "tongue & groove", "mortise & tenon"],
                            }
                        ),
                        "2026-03-06T00:02:00+00:00",
                    ),
                )

                report = run_track_gate_v2(db)
                row = db.query(
                    "select track from asset_track_assessments where run_id=? and asset_id=?",
                    (report["run_id"], "a1"),
                )[0]

            self.assertEqual(str(row["track"]), "irrelevant")

    def test_run_multi_axis_inference_v2_assigns_expected_axes(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                assets = [
                    (
                        "style_outdoor",
                        "pinterest",
                        "pin://outdoor",
                        "Outdoor dining table on covered patio",
                        "patio dining",
                        "",
                        "2026-03-06T00:00:00+00:00",
                    ),
                    (
                        "style_product",
                        "pinterest",
                        "pin://product",
                        "Unlacquered brass bridge faucet",
                        "bath fixtures",
                        "",
                        "2026-03-06T00:00:01+00:00",
                    ),
                    (
                        "construction_system",
                        "facebook",
                        "fb://construction",
                        "ZIP system waterproofing membrane around window opening",
                        "",
                        "Builder detail for window waterproofing and flashing",
                        "2026-03-06T00:00:02+00:00",
                    ),
                ]
                for asset_id, source, source_ref, title, board, notes, imported_at in assets:
                    db.exec(
                        """
                        insert into assets (id, source, source_ref, title, board, notes, imported_at)
                        values (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (asset_id, source, source_ref, title, board, notes, imported_at),
                    )

                labels = [
                    ("lab_outdoor_1", "style_outdoor", "patio"),
                    ("lab_outdoor_2", "style_outdoor", "dining"),
                    ("lab_product_1", "style_product", "faucet"),
                    ("lab_construction_1", "construction_system", "zip system"),
                    ("lab_construction_2", "construction_system", "window detail"),
                ]
                for label_id, asset_id, label in labels:
                    db.exec(
                        """
                        insert into asset_labels (id, asset_id, label, confidence, source, model, run_id, created_at)
                        values (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (label_id, asset_id, label, 0.9, "ai", "gemini", "r1", "2026-03-06T00:01:00+00:00"),
                    )

                ai_rows = [
                    (
                        "ai_outdoor",
                        "style_outdoor",
                        "gemini",
                        "gemini-2.5-flash",
                        "Outdoor patio dining inspiration",
                        {
                            "image_type": "exterior",
                            "rooms": ["patio"],
                            "elements": ["dining table"],
                            "styles": ["organic modern"],
                        },
                    ),
                    (
                        "ai_product",
                        "style_product",
                        "gemini",
                        "gemini-2.5-flash",
                        "Single faucet product shot",
                        {
                            "image_type": "product",
                            "fixtures": ["faucet"],
                            "materials": ["brass"],
                            "styles": ["traditional"],
                        },
                    ),
                    (
                        "ai_construction",
                        "construction_system",
                        "gemini",
                        "gemini-2.5-flash",
                        "Window waterproofing detail",
                        {
                            "image_type": "detail",
                            "tags": ["zip system", "waterproofing membrane", "window detail", "flashing"],
                            "elements": ["window detail"],
                        },
                    ),
                ]
                for ai_id, asset_id, provider, model, summary, payload in ai_rows:
                    db.exec(
                        """
                        insert into asset_ai (id, asset_id, provider, model, summary, json, created_at)
                        values (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            ai_id,
                            asset_id,
                            provider,
                            model,
                            summary,
                            json.dumps(payload),
                            "2026-03-06T00:02:00+00:00",
                        ),
                    )

                track_report = run_track_gate_v2(db)
                report = run_multi_axis_inference_v2(db, track_run_id=track_report["run_id"])
                rows = db.query(
                    """
                    select asset_id, axis_name, axis_value
                    from asset_axis_memberships
                    where run_id=?
                    order by asset_id, axis_name, rank
                    """,
                    (report["run_id"],),
                )

            self.assertEqual(report["candidate_count"], 3)
            self.assertGreater(report["memberships_written"], 0)

            by_asset: dict[str, dict[str, list[str]]] = {}
            for row in rows:
                asset_axes = by_asset.setdefault(str(row["asset_id"]), {})
                asset_axes.setdefault(str(row["axis_name"]), []).append(str(row["axis_value"]))

            self.assertEqual(by_asset["style_outdoor"].get("space_context"), ["outdoor_zone"])
            self.assertIn("dining", by_asset["style_outdoor"].get("function", []))
            self.assertEqual(by_asset["style_outdoor"].get("subject_type"), ["full_space_scene"])
            self.assertNotIn("room", by_asset["style_outdoor"])

            self.assertEqual(by_asset["style_product"].get("space_context"), ["non_spatial"])
            self.assertEqual(by_asset["style_product"].get("subject_type"), ["single_product"])
            self.assertIn("faucet", by_asset["style_product"].get("product_focus", []))
            self.assertNotIn("room", by_asset["style_product"])

            self.assertIn("envelope", by_asset["construction_system"].get("concern_domain", []))
            self.assertIn("envelope", by_asset["construction_system"].get("trade_system", []))
            self.assertIn("zip_system", by_asset["construction_system"].get("product_system_focus", []))

    def test_multi_axis_inference_v2_keeps_style_plan_as_non_spatial_reference(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, board, category, imported_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "a1",
                        "pinterest",
                        "pin://style-plan",
                        "36x24 House 2-bedroom 2-bath 864 Sq Ft PDF Floor Plan",
                        "house-plans",
                        "home_design",
                        "2026-03-06T00:00:00+00:00",
                    ),
                )
                for label_id, label in (
                    ("lab1", "floor plan"),
                    ("lab2", "house plan"),
                    ("lab3", "kitchen"),
                    ("lab4", "living room"),
                ):
                    db.exec(
                        """
                        insert into asset_labels (id, asset_id, label, confidence, source, model, run_id, created_at)
                        values (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (label_id, "a1", label, 0.9, "ai", "gemini", "r1", "2026-03-06T00:01:00+00:00"),
                    )
                db.exec(
                    """
                    insert into asset_ai (id, asset_id, provider, model, summary, json, created_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "ai1",
                        "a1",
                        "gemini",
                        "gemini-2.5-flash",
                        "Compact residential floor plan",
                        json.dumps(
                            {
                                "image_type": "plan",
                                "tags": ["floor plan", "house plan", "architectural drawing", "layout"],
                                "rooms": ["kitchen", "living room"],
                            }
                        ),
                        "2026-03-06T00:02:00+00:00",
                    ),
                )

                track_report = run_track_gate_v2(db)
                axis_report = run_multi_axis_inference_v2(db, track_run_id=track_report["run_id"])
                rows = db.query(
                    """
                    select axis_name, axis_value
                    from asset_axis_memberships
                    where run_id=? and asset_id=?
                    order by axis_name, rank
                    """,
                    (axis_report["run_id"], "a1"),
                )

            by_axis: dict[str, list[str]] = {}
            for row in rows:
                by_axis.setdefault(str(row["axis_name"]), []).append(str(row["axis_value"]))

            self.assertEqual(by_axis.get("space_context"), ["non_spatial"])
            self.assertEqual(by_axis.get("subject_type"), ["plan_drawing"])
            self.assertNotIn("room", by_axis)
            self.assertNotIn("concern_domain", by_axis)

    def test_multi_axis_inference_v2_honors_manual_axis_override(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, board, category, imported_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "a1",
                        "facebook",
                        "fb://paint-override",
                        "Color drenching door painting tip",
                        "Painting Tips",
                        "diy",
                        "2026-03-06T00:00:00+00:00",
                    ),
                )
                db.exec(
                    """
                    insert into asset_labels (id, asset_id, label, confidence, source, model, run_id, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("lab1", "a1", "paint", 0.9, "ai", "gemini", "r1", "2026-03-06T00:01:00+00:00"),
                )
                db.exec(
                    """
                    insert into classification_runs
                      (id, schema_version, run_type, model_provider, model_name, prompt_version, config_json, created_at, notes)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "track_run_1",
                        "curation_v2",
                        "track_gate",
                        "heuristic",
                        "test",
                        "",
                        "{}",
                        "2026-03-06T00:02:00+00:00",
                        "test",
                    ),
                )
                db.exec(
                    """
                    insert into asset_track_assessments
                      (id, run_id, asset_id, track, confidence, is_ambiguous, decision_source, reason, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "assess1",
                        "track_run_1",
                        "a1",
                        "style_product_decor",
                        0.95,
                        0,
                        "test",
                        "seeded style track",
                        "2026-03-06T00:02:01+00:00",
                    ),
                )
                db.exec(
                    """
                    insert into asset_overrides
                      (id, asset_id, axis_name, axis_value, operation, actor, note, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "ov1",
                        "a1",
                        "subject_type",
                        "material_finish",
                        "set",
                        "Jim",
                        "Jim said this is an interior design detail on painting.",
                        "2026-03-06T00:02:02+00:00",
                    ),
                )

                report = run_multi_axis_inference_v2(db, track_run_id="track_run_1")
                rows = db.query(
                    """
                    select axis_name, axis_value, confidence
                    from asset_axis_memberships
                    where run_id=? and asset_id=?
                    order by axis_name, rank
                    """,
                    (report["run_id"], "a1"),
                )

            by_axis: dict[str, list[str]] = {}
            for row in rows:
                by_axis.setdefault(str(row["axis_name"]), []).append(str(row["axis_value"]))
            self.assertEqual(by_axis.get("subject_type"), ["material_finish"])

    def test_cli_curation_axis_infer_v2_outputs_json(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, board, imported_at)
                    values (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "a1",
                        "pinterest",
                        "pin://1",
                        "Warm kitchen with brass pendants",
                        "pins: kitchen",
                        "2026-03-06T00:00:00+00:00",
                    ),
                )
                track_report = run_track_gate_v2(db, limit=1)

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = main(
                    [
                        "--db",
                        str(db_path),
                        "curation",
                        "axis-infer-v2",
                        "--track-run-id",
                        str(track_report["run_id"]),
                        "--limit",
                        "1",
                        "--notes",
                        "axis test",
                    ]
                )

            self.assertEqual(rc, 0)
            payload = json.loads(buf.getvalue())
            self.assertTrue(payload.get("ok"))
            self.assertEqual(payload.get("candidate_count"), 1)
            self.assertGreaterEqual(int(payload.get("memberships_written") or 0), 1)
            self.assertTrue(str(payload.get("run_id") or "").strip())

    def test_multi_axis_inference_v2_recognizes_zip_r_variant(self):
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
                        "a1",
                        "facebook",
                        "fb://zipr",
                        "55K views | Zip R Sheathing explained #zipsheathing",
                        "2026-03-06T00:00:00+00:00",
                    ),
                )
                db.exec(
                    """
                    insert into asset_field_provenance
                      (id, asset_id, field_name, origin_type, origin_ref, confidence, field_value, is_current, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "prov1",
                        "a1",
                        "title",
                        "imported",
                        "fb://zipr",
                        0.85,
                        "55K views | Zip R Sheathing explained #zipsheathing",
                        1,
                        "2026-03-06T00:00:00+00:00",
                    ),
                )
                for label_id, label in (("lab1", "insulation"), ("lab2", "insulation foam"), ("lab3", "insulated sheathing")):
                    db.exec(
                        """
                        insert into asset_labels (id, asset_id, label, confidence, source, model, run_id, created_at)
                        values (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (label_id, "a1", label, 0.8, "ai", "gemini", "r1", "2026-03-06T00:01:00+00:00"),
                    )
                db.exec(
                    """
                    insert into asset_ai (id, asset_id, provider, model, summary, json, created_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "ai1",
                        "a1",
                        "gemini-video",
                        "gemini-2.5-flash",
                        "ZIP-R wall sheathing detail",
                        json.dumps(
                            {
                                "category": "construction",
                                "subcategory": "general",
                                "confidence": 1.0,
                                "elements": ["insulated sheathing", "wall studs", "insulation", "framing"],
                                "materials": ["wood", "insulation foam"],
                            }
                        ),
                        "2026-03-06T00:02:00+00:00",
                    ),
                )
                db.exec(
                    """
                    insert into classification_runs
                      (id, schema_version, run_type, model_provider, model_name, prompt_version, config_json, created_at, notes)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "track_run_1",
                        "curation_v2",
                        "track_gate",
                        "heuristic",
                        "test",
                        "",
                        "{}",
                        "2026-03-06T00:03:00+00:00",
                        "test",
                    ),
                )
                db.exec(
                    """
                    insert into asset_track_assessments
                      (id, run_id, asset_id, track, confidence, is_ambiguous, decision_source, reason, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "assess1",
                        "track_run_1",
                        "a1",
                        "construction_concern",
                        0.9,
                        0,
                        "test",
                        "seeded construction track",
                        "2026-03-06T00:03:01+00:00",
                    ),
                )

                report = run_multi_axis_inference_v2(db, track_run_id="track_run_1")
                values = {
                    str(row["axis_value"])
                    for row in db.query(
                        """
                        select axis_value
                        from asset_axis_memberships
                        where run_id=? and asset_id=? and axis_name='product_system_focus'
                        """,
                        (report["run_id"], "a1"),
                    )
                }

            self.assertIn("zip_system", values)
            self.assertIn("insulation_system", values)

    def test_multi_axis_inference_v2_adds_specific_envelope_systems(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, board, category, imported_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "a1",
                        "facebook",
                        "fb://envelope-detail",
                        "Window flashing detail at siding transition",
                        "building",
                        "construction",
                        "2026-03-06T00:00:00+00:00",
                    ),
                )
                for label_id, label in (
                    ("lab1", "window"),
                    ("lab2", "flashing tape"),
                    ("lab3", "vinyl siding"),
                ):
                    db.exec(
                        """
                        insert into asset_labels (id, asset_id, label, confidence, source, model, run_id, created_at)
                        values (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (label_id, "a1", label, 0.9, "ai", "gemini", "r1", "2026-03-06T00:01:00+00:00"),
                    )
                db.exec(
                    """
                    insert into classification_runs
                      (id, schema_version, run_type, model_provider, model_name, prompt_version, config_json, created_at, notes)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "track_run_1",
                        "curation_v2",
                        "track_gate",
                        "heuristic",
                        "test",
                        "",
                        "{}",
                        "2026-03-06T00:03:00+00:00",
                        "test",
                    ),
                )
                db.exec(
                    """
                    insert into asset_track_assessments
                      (id, run_id, asset_id, track, confidence, is_ambiguous, decision_source, reason, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "assess1",
                        "track_run_1",
                        "a1",
                        "construction_concern",
                        0.95,
                        0,
                        "test",
                        "seeded construction track",
                        "2026-03-06T00:03:01+00:00",
                    ),
                )

                report = run_multi_axis_inference_v2(db, track_run_id="track_run_1")
                values = {
                    str(row["axis_value"])
                    for row in db.query(
                        """
                        select axis_value
                        from asset_axis_memberships
                        where run_id=? and asset_id=? and axis_name='product_system_focus'
                        """,
                        (report["run_id"], "a1"),
                    )
                }

            self.assertIn("window_system", values)
            self.assertIn("flashing_system", values)
            self.assertIn("siding_system", values)

    def test_multi_axis_inference_v2_does_not_map_shower_drain_to_site_exterior(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, notes, imported_at)
                    values (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "a1",
                        "facebook",
                        "fb://shower",
                        "Large format tile shower floor has to drain properly",
                        "Builder advice about shower installation",
                        "2026-03-06T00:00:00+00:00",
                    ),
                )
                db.exec(
                    """
                    insert into asset_ai (id, asset_id, provider, model, summary, json, created_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "ai1",
                        "a1",
                        "gemini",
                        "gemini-2.5-flash",
                        "Shower installation advice",
                        json.dumps({"tags": ["shower", "tile", "drain", "plumbing"]}),
                        "2026-03-06T00:02:00+00:00",
                    ),
                )
                db.exec(
                    """
                    insert into classification_runs
                      (id, schema_version, run_type, model_provider, model_name, prompt_version, config_json, created_at, notes)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "track_run_1",
                        "curation_v2",
                        "track_gate",
                        "heuristic",
                        "test",
                        "",
                        "{}",
                        "2026-03-06T00:03:00+00:00",
                        "test",
                    ),
                )
                db.exec(
                    """
                    insert into asset_track_assessments
                      (id, run_id, asset_id, track, confidence, is_ambiguous, decision_source, reason, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "assess1",
                        "track_run_1",
                        "a1",
                        "construction_concern",
                        0.9,
                        0,
                        "test",
                        "seeded construction track",
                        "2026-03-06T00:03:01+00:00",
                    ),
                )

                report = run_multi_axis_inference_v2(db, track_run_id="track_run_1")
                concern_domains = {
                    str(row["axis_value"])
                    for row in db.query(
                        """
                        select axis_value
                        from asset_axis_memberships
                        where run_id=? and asset_id=? and axis_name='concern_domain'
                        """,
                        (report["run_id"], "a1"),
                    )
                }

            self.assertNotIn("site_exterior", concern_domains)

    def test_multi_axis_inference_v2_maps_builder_inspection_to_inspection_quality_control(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, board, description, imported_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "a1",
                        "facebook",
                        "fb://inspection",
                        "Some builders actually care!",
                        "Home Building Process",
                        "Two men discuss a rough-in home inspection at a house under construction.",
                        "2026-03-06T00:00:00+00:00",
                    ),
                )
                db.exec(
                    """
                    insert into asset_ai (id, asset_id, provider, model, summary, json, created_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "ai1",
                        "a1",
                        "gemini",
                        "gemini-2.5-flash",
                        "Rough-in home inspection during construction",
                        json.dumps({"tags": ["builder", "rough-in inspection", "home inspection", "construction"]}),
                        "2026-03-06T00:02:00+00:00",
                    ),
                )
                db.exec(
                    """
                    insert into classification_runs
                      (id, schema_version, run_type, model_provider, model_name, prompt_version, config_json, created_at, notes)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "track_run_1",
                        "curation_v2",
                        "track_gate",
                        "heuristic",
                        "test",
                        "",
                        "{}",
                        "2026-03-06T00:03:00+00:00",
                        "test",
                    ),
                )
                db.exec(
                    """
                    insert into asset_track_assessments
                      (id, run_id, asset_id, track, confidence, is_ambiguous, decision_source, reason, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "assess1",
                        "track_run_1",
                        "a1",
                        "construction_concern",
                        0.95,
                        0,
                        "test",
                        "seeded construction track",
                        "2026-03-06T00:03:01+00:00",
                    ),
                )

                report = run_multi_axis_inference_v2(db, track_run_id="track_run_1")
                concern_domains = {
                    str(row["axis_value"])
                    for row in db.query(
                        """
                        select axis_value
                        from asset_axis_memberships
                        where run_id=? and asset_id=? and axis_name='concern_domain'
                        """,
                        (report["run_id"], "a1"),
                    )
                }

            self.assertIn("inspection_quality_control", concern_domains)
            self.assertNotIn("plans_code_permits", concern_domains)

    def test_multi_axis_inference_v2_uses_source_link_text_for_inspection_domain(self):
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
                        "a1",
                        "facebook",
                        "fb://inspection-source-link",
                        "Bearded man in black polo shirt with logo",
                        "2026-03-06T00:00:00+00:00",
                    ),
                )
                db.exec(
                    """
                    insert into classification_runs
                      (id, schema_version, run_type, model_provider, model_name, prompt_version, config_json, created_at, notes)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "source_run_1",
                        "curation_v2",
                        "source_link_enrichment",
                        "test",
                        "test",
                        "",
                        "{}",
                        "2026-03-09T03:24:40+00:00",
                        "test",
                    ),
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
                        "sle1",
                        "source_run_1",
                        "a1",
                        "https://www.facebook.com/reel/873910842167631/",
                        "https://www.facebook.com/reel/873910842167631",
                        "facebook.com",
                        "",
                        "",
                        "Facebook",
                        "",
                        "",
                        "",
                        "You’re paying for an inspection — not a builder’s to-do list. Buyers hire me to find what’s missed, wrong, broken, or not functioning. Texas Edge Home Inspections.",
                        "browser/document",
                        200,
                        0,
                        0,
                        "fetched",
                        "",
                        "hash1",
                        "2026-03-09T03:24:43+00:00",
                    ),
                )
                db.exec(
                    """
                    insert into classification_runs
                      (id, schema_version, run_type, model_provider, model_name, prompt_version, config_json, created_at, notes)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "track_run_1",
                        "curation_v2",
                        "track_gate",
                        "heuristic",
                        "test",
                        "",
                        "{}",
                        "2026-03-06T00:03:00+00:00",
                        "test",
                    ),
                )
                db.exec(
                    """
                    insert into asset_track_assessments
                      (id, run_id, asset_id, track, confidence, is_ambiguous, decision_source, reason, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "assess1",
                        "track_run_1",
                        "a1",
                        "construction_concern",
                        0.95,
                        0,
                        "test",
                        "seeded construction track",
                        "2026-03-06T00:03:01+00:00",
                    ),
                )

                report = run_multi_axis_inference_v2(db, track_run_id="track_run_1")
                concern_domains = {
                    str(row["axis_value"])
                    for row in db.query(
                        """
                        select axis_value
                        from asset_axis_memberships
                        where run_id=? and asset_id=? and axis_name='concern_domain'
                        """,
                        (report["run_id"], "a1"),
                    )
                }

            self.assertIn("inspection_quality_control", concern_domains)
            self.assertNotIn("plans_code_permits", concern_domains)


if __name__ == "__main__":
    unittest.main()
