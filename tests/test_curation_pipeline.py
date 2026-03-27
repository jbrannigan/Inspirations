import json
import tempfile
import unittest
from pathlib import Path

from inspirations.curation import TRACK_CONSTRUCTION, TRACK_STYLE, run_curation_pipeline
from inspirations.db import Db, ensure_schema


class TestCurationPipeline(unittest.TestCase):
    def _insert_asset(
        self,
        db: Db,
        *,
        asset_id: str,
        source: str,
        source_ref: str,
        title: str,
        board: str = "",
        triage_status: str | None = None,
        thumb_path: str | None = None,
        stored_path: str | None = None,
    ) -> None:
        db.exec(
            """
            insert into assets
              (id, source, source_ref, title, board, imported_at, triage_status, thumb_path, stored_path)
            values (?, ?, ?, ?, ?, datetime('now'), ?, ?, ?)
            """,
            (asset_id, source, source_ref, title, board, triage_status, thumb_path, stored_path),
        )

    def _insert_label(self, db: Db, *, label_id: str, asset_id: str, label: str) -> None:
        db.exec(
            """
            insert into asset_labels
              (id, asset_id, label, source, created_at)
            values (?, ?, ?, 'test', datetime('now'))
            """,
            (label_id, asset_id, label),
        )

    def test_run_pipeline_heuristic_exports_two_documents(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "t.sqlite"
            out_dir = root / "out"

            with Db(db_path) as db:
                ensure_schema(db)
                # Style/product/decor candidate
                self._insert_asset(
                    db,
                    asset_id="a-style",
                    source="pinterest",
                    source_ref="https://example.com/pin/1",
                    title="Kitchen lighting moodboard",
                    board="kitchen",
                )
                self._insert_label(db, label_id="l1", asset_id="a-style", label="kitchen")
                self._insert_label(db, label_id="l2", asset_id="a-style", label="lighting")
                self._insert_label(db, label_id="l3", asset_id="a-style", label="home decor")

                # Construction concern candidate
                self._insert_asset(
                    db,
                    asset_id="a-construction",
                    source="facebook",
                    source_ref="https://example.com/post/2",
                    title="HVAC rough-in checklist for new build",
                    board="construction tips",
                )
                self._insert_label(db, label_id="l4", asset_id="a-construction", label="hvac")
                self._insert_label(db, label_id="l5", asset_id="a-construction", label="construction")

                # Irrelevant candidate
                self._insert_asset(
                    db,
                    asset_id="a-irrelevant",
                    source="facebook",
                    source_ref="https://example.com/post/3",
                    title="Workout routine for summer",
                    board="workout",
                )
                self._insert_label(db, label_id="l6", asset_id="a-irrelevant", label="workout")

            with Db(db_path) as db:
                ensure_schema(db)
                report = run_curation_pipeline(
                    db,
                    out_dir=out_dir,
                    provider="heuristic",
                    summarize=False,
                    render_html=True,
                    media_base="http://localhost:8001",
                )

            self.assertTrue(report["ok"])
            self.assertEqual(report["provider"], "heuristic")
            self.assertEqual(report["counts"]["candidates"], 3)
            self.assertEqual(report["counts"]["included"], 2)
            self.assertEqual(report["counts"]["style"], 1)
            self.assertEqual(report["counts"]["construction"], 1)
            self.assertEqual(report["counts"]["irrelevantOrExcluded"], 1)

            style_path = Path(report["files"]["styleBestOfJson"])
            construction_path = Path(report["files"]["constructionConcernsJson"])
            manifest_path = Path(report["files"]["manifestJson"])
            style_html_path = Path(report["files"]["styleBestOfHtml"])
            construction_html_path = Path(report["files"]["constructionConcernsHtml"])
            self.assertTrue(style_path.exists())
            self.assertTrue(construction_path.exists())
            self.assertTrue(manifest_path.exists())
            self.assertTrue(style_html_path.exists())
            self.assertTrue(construction_html_path.exists())
            style_html = style_html_path.read_text(encoding="utf-8")
            construction_html = construction_html_path.read_text(encoding="utf-8")
            self.assertIn("http://localhost:8001/media/", style_html)
            self.assertIn("http://localhost:8001/media/", construction_html)

            style_doc = json.loads(style_path.read_text(encoding="utf-8"))
            self.assertEqual(style_doc["title"], "Curated Style Inspiration (Best Of)")
            self.assertEqual(style_doc["stats"]["totalStyleItems"], 1)
            style_items = []
            for cat in style_doc.get("categories", []):
                style_items.extend(cat.get("items", []))
            for cat in style_doc.get("appendixCategories", []):
                style_items.extend(cat.get("items", []))
            self.assertEqual(len(style_items), 1)
            self.assertEqual(style_items[0]["classification"], TRACK_STYLE)
            self.assertTrue(style_items[0]["include"])

            construction_doc = json.loads(construction_path.read_text(encoding="utf-8"))
            self.assertEqual(construction_doc["title"], "Construction Concerns")
            self.assertEqual(construction_doc["stats"]["totalConstructionItems"], 1)
            items = []
            for cat in construction_doc.get("categories", []):
                items.extend(cat.get("items", []))
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["classification"], TRACK_CONSTRUCTION)
            self.assertTrue(items[0]["include"])

    def test_best_of_max_total_caps_primary_style_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "t.sqlite"
            out_dir = root / "out"

            with Db(db_path) as db:
                ensure_schema(db)
                for i in range(5):
                    aid = f"a-style-{i}"
                    self._insert_asset(
                        db,
                        asset_id=aid,
                        source="pinterest",
                        source_ref=f"https://example.com/pin/{i}",
                        title=f"Kitchen lighting moodboard {i}",
                        board="kitchen",
                    )
                    self._insert_label(db, label_id=f"l-{i}-1", asset_id=aid, label="kitchen")
                    self._insert_label(db, label_id=f"l-{i}-2", asset_id=aid, label="home decor")

            with Db(db_path) as db:
                ensure_schema(db)
                report = run_curation_pipeline(
                    db,
                    out_dir=out_dir,
                    provider="heuristic",
                    summarize=False,
                    best_of_max_total=2,
                )

            style_doc = json.loads(Path(report["files"]["styleBestOfJson"]).read_text(encoding="utf-8"))
            self.assertEqual(style_doc["stats"]["bestOfItems"], 2)
            self.assertEqual(style_doc["stats"]["totalStyleItems"], 5)

    def test_best_of_show_all_if_under_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "t.sqlite"
            out_dir = root / "out"

            with Db(db_path) as db:
                ensure_schema(db)
                for i in range(3):
                    aid = f"a-style-{i}"
                    self._insert_asset(
                        db,
                        asset_id=aid,
                        source="pinterest",
                        source_ref=f"https://example.com/pin/{i}",
                        title=f"Simple interior idea {i}",
                        board="living room",
                    )
                    self._insert_label(db, label_id=f"l-{i}-1", asset_id=aid, label="living room")

            with Db(db_path) as db:
                ensure_schema(db)
                report = run_curation_pipeline(
                    db,
                    out_dir=out_dir,
                    provider="heuristic",
                    summarize=False,
                    best_of_min_rating=5,
                    best_of_max_total=10,
                    best_of_backfill_if_short=False,
                    best_of_show_all_if_under_target=True,
                )

            style_doc = json.loads(Path(report["files"]["styleBestOfJson"]).read_text(encoding="utf-8"))
            self.assertEqual(style_doc["stats"]["bestOfItems"], 3)
            self.assertEqual(style_doc["stats"]["appendixItems"], 0)

    def test_best_of_target_per_room_selects_top_n_each_room(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "t.sqlite"
            out_dir = root / "out"

            with Db(db_path) as db:
                ensure_schema(db)
                for i in range(5):
                    aid = f"k-style-{i}"
                    self._insert_asset(
                        db,
                        asset_id=aid,
                        source="pinterest",
                        source_ref=f"https://example.com/k/{i}",
                        title=f"Kitchen cabinet and lighting idea {i}",
                        board="kitchen",
                    )
                    self._insert_label(db, label_id=f"lk-{i}", asset_id=aid, label="kitchen")
                for i in range(5):
                    aid = f"b-style-{i}"
                    self._insert_asset(
                        db,
                        asset_id=aid,
                        source="pinterest",
                        source_ref=f"https://example.com/b/{i}",
                        title=f"Bedroom decor and furniture idea {i}",
                        board="bedroom",
                    )
                    self._insert_label(db, label_id=f"lb-{i}", asset_id=aid, label="bedroom")

            with Db(db_path) as db:
                ensure_schema(db)
                report = run_curation_pipeline(
                    db,
                    out_dir=out_dir,
                    provider="heuristic",
                    summarize=False,
                    best_of_target_per_room=2,
                    best_of_backfill_if_short=True,
                )

            style_doc = json.loads(Path(report["files"]["styleBestOfJson"]).read_text(encoding="utf-8"))
            by_name = {str(c.get("name")): len(c.get("items") or []) for c in style_doc.get("categories", [])}
            self.assertEqual(by_name.get("Kitchen"), 2)
            self.assertEqual(by_name.get("Bedroom"), 2)
            self.assertEqual(style_doc["stats"]["bestOfItems"], 4)

    def test_hidden_collection_items_are_excluded_from_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "t.sqlite"
            out_dir = root / "out"

            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into collections (id, name, created_at, updated_at)
                    values ('c-hidden', 'Hidden', datetime('now'), datetime('now'))
                    """
                )
                self._insert_asset(
                    db,
                    asset_id="a-hidden-scope",
                    source="pinterest",
                    source_ref="https://example.com/pin/hidden",
                    title="Kitchen cabinets hidden by collection",
                    board="kitchen",
                )
                self._insert_label(db, label_id="l1", asset_id="a-hidden-scope", label="kitchen")
                db.exec(
                    "insert into collection_items (collection_id, asset_id, position) values (?, ?, ?)",
                    ("c-hidden", "a-hidden-scope", 1),
                )

            with Db(db_path) as db:
                ensure_schema(db)
                report = run_curation_pipeline(
                    db,
                    out_dir=out_dir,
                    provider="heuristic",
                    summarize=False,
                )

            self.assertEqual(report["counts"]["candidates"], 0)
            self.assertEqual(report["counts"]["included"], 0)
            self.assertEqual(report["counts"]["style"], 0)
            self.assertEqual(report["counts"]["construction"], 0)
            self.assertEqual(report["counts"]["irrelevantOrExcluded"], 0)

    def test_render_html_uses_local_media_when_media_base_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "t.sqlite"
            out_dir = root / "out"
            thumb = root / "thumb.jpg"
            original = root / "orig.jpg"
            thumb.write_bytes(b"thumb-bytes")
            original.write_bytes(b"orig-bytes")

            with Db(db_path) as db:
                ensure_schema(db)
                self._insert_asset(
                    db,
                    asset_id="a-local",
                    source="pinterest",
                    source_ref="https://example.com/pin/local",
                    title="Kitchen lighting local media",
                    board="kitchen",
                    thumb_path=str(thumb),
                    stored_path=str(original),
                )
                self._insert_label(db, label_id="l1", asset_id="a-local", label="kitchen")

            with Db(db_path) as db:
                ensure_schema(db)
                report = run_curation_pipeline(
                    db,
                    out_dir=out_dir,
                    provider="heuristic",
                    summarize=False,
                    render_html=True,
                    media_base="",
                )

            style_html_path = Path(report["files"]["styleBestOfHtml"])
            construction_html_path = Path(report["files"]["constructionConcernsHtml"])
            style_html = style_html_path.read_text(encoding="utf-8")
            construction_html = construction_html_path.read_text(encoding="utf-8")
            self.assertIn("file://", style_html)
            # Construction document may have no items in this tiny sample; still should render.
            self.assertTrue("<!doctype html>" in construction_html.lower())

    def test_pairwise_votes_drive_room_top_pick(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "t.sqlite"
            out_dir = root / "out"
            votes_path = root / "pairwise_votes.json"

            with Db(db_path) as db:
                ensure_schema(db)
                self._insert_asset(
                    db,
                    asset_id="a-keeper",
                    source="pinterest",
                    source_ref="https://example.com/pin/keeper",
                    title="Kitchen cabinet lighting marble wood design keeper",
                    board="kitchen",
                    triage_status="keeper",
                )
                self._insert_label(db, label_id="l1", asset_id="a-keeper", label="kitchen")

                self._insert_asset(
                    db,
                    asset_id="a-favorite",
                    source="pinterest",
                    source_ref="https://example.com/pin/favorite",
                    title="Kitchen cabinet lighting marble wood design favorite",
                    board="kitchen",
                )
                self._insert_label(db, label_id="l2", asset_id="a-favorite", label="kitchen")

                self._insert_asset(
                    db,
                    asset_id="a-other",
                    source="pinterest",
                    source_ref="https://example.com/pin/other",
                    title="Kitchen cabinet lighting marble wood design other",
                    board="kitchen",
                )
                self._insert_label(db, label_id="l3", asset_id="a-other", label="kitchen")

            votes = [
                {"left": "a-keeper", "right": "a-favorite", "winner": "right"},
                {"left": "a-favorite", "right": "a-other", "winner": "left"},
                {"left": "a-keeper", "right": "a-other", "winner": "right"},
            ]
            votes_path.write_text(json.dumps(votes, indent=2), encoding="utf-8")

            with Db(db_path) as db:
                ensure_schema(db)
                report = run_curation_pipeline(
                    db,
                    out_dir=out_dir,
                    provider="heuristic",
                    summarize=False,
                    style_ranking_mode="pairwise",
                    pairwise_votes_path=str(votes_path),
                    pairwise_rounds_per_room=3,
                    best_of_target_per_room=1,
                )

            style_doc = json.loads(Path(report["files"]["styleBestOfJson"]).read_text(encoding="utf-8"))
            kitchen = next((c for c in style_doc.get("categories", []) if c.get("name") == "Kitchen"), None)
            self.assertIsNotNone(kitchen)
            items = list((kitchen or {}).get("items") or [])
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["assetId"], "a-favorite")
            self.assertEqual(style_doc["stats"]["styleRankingMode"], "pairwise")
            self.assertGreaterEqual(int(style_doc["stats"]["pairwiseHumanPairs"]), 1)
            self.assertIn("pairwiseScore", items[0])


if __name__ == "__main__":
    unittest.main()
