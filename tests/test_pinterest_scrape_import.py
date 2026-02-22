"""Tests for the Pinterest scrape importer."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from inspirations.db import Db, ensure_schema
from inspirations.importers.pinterest_scrape import import_pinterest_scrape


SAMPLE_PINS = [
    {
        "pin_id": "100000000000001",
        "pin_url": "https://www.pinterest.com/pin/100000000000001/",
        "board_name": "kitchen",
        "title": "Oak Kitchen",
        "description": "Warm oak cabinets",
        "seo_alt_text": "A kitchen with oak cabinets and marble countertops",
        "closeup_desc": "Lee Industries makes quality furniture",
        "source_url": "https://example.com/kitchen",
        "source_domain": "example.com",
        "dominant_color": "#cbc1b4",
        "hashtags": ["kitchen", "oak"],
        "created_at": "Thu, 13 Sep 2012 11:41:35 +0000",
        "image_url": "https://i.pinimg.com/originals/aa/bb/cc/aabbcc.jpg",
        "image_width": 600,
        "image_height": 400,
        "repin_count": 42,
        "comment_count": 3,
        "rich_metadata": {"site_name": "Example", "type": "richpindataview"},
    },
    {
        "pin_id": "100000000000002",
        "pin_url": "https://www.pinterest.com/pin/100000000000002/",
        "board_name": "bathroom",
        "title": "Marble Bath",
        "description": "White marble bathroom",
        "seo_alt_text": None,
        "source_url": None,
        "source_domain": "pinterest.com",
        "dominant_color": "#ffffff",
        "hashtags": [],
        "created_at": None,
        "image_url": "https://i.pinimg.com/originals/dd/ee/ff/ddeeff.jpg",
        "image_width": None,
        "image_height": None,
        "repin_count": 10,
        "comment_count": 0,
    },
    {
        # Missing image_url — should be skipped
        "pin_id": "100000000000003",
        "pin_url": "https://www.pinterest.com/pin/100000000000003/",
        "board_name": "other",
        "title": "No Image",
        "image_url": "",
    },
    {
        # Missing pin_url — should be skipped
        "pin_id": "100000000000004",
        "pin_url": "",
        "board_name": "other",
        "title": "No URL",
        "image_url": "https://i.pinimg.com/originals/xx/yy/zz/xxyyzz.jpg",
    },
]


class TestPinterestScrapeImport(unittest.TestCase):
    def _make_db(self, tmp: Path) -> Db:
        db_path = tmp / "test.sqlite"
        db = Db(db_path)
        db.__enter__()
        ensure_schema(db)
        return db

    def test_basic_import(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            json_path = tmp / "pins.json"
            json_path.write_text(json.dumps(SAMPLE_PINS))
            store_dir = tmp / "store"

            db = self._make_db(tmp)
            try:
                result = import_pinterest_scrape(
                    db, json_path=json_path, store_dir=store_dir, download_missing=False
                )
            finally:
                db.__exit__(None, None, None)

            self.assertEqual(result["total_in_json"], 4)
            self.assertEqual(result["imported"], 2)  # 2 valid pins
            self.assertEqual(result["skipped_no_url"], 2)  # 2 skipped
            self.assertEqual(result["total_assets_for_source"], 2)

    def test_dedup(self):
        """Re-importing same JSON should not create duplicates."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            json_path = tmp / "pins.json"
            json_path.write_text(json.dumps(SAMPLE_PINS[:2]))
            store_dir = tmp / "store"

            for _ in range(2):
                db = self._make_db(tmp)
                try:
                    import_pinterest_scrape(db, json_path=json_path, store_dir=store_dir, download_missing=False)
                finally:
                    db.__exit__(None, None, None)

            db = Db(tmp / "test.sqlite")
            with db:
                count = db.query_value("select count(*) from assets where source='pinterest'")
            self.assertEqual(count, 2)

    def test_image_map_matching(self):
        """Image map should reuse stored_path without downloading."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            pins = [SAMPLE_PINS[0]]
            json_path = tmp / "pins.json"
            json_path.write_text(json.dumps(pins))
            image_map_path = tmp / "image_map.json"
            image_map_path.write_text(
                json.dumps({
                    "https://i.pinimg.com/originals/aa/bb/cc/aabbcc.jpg": {
                        "stored_path": "store/originals/pinterest/existing.jpg",
                        "sha256": "abc123",
                    }
                })
            )
            store_dir = tmp / "store"

            db = self._make_db(tmp)
            try:
                result = import_pinterest_scrape(
                    db,
                    json_path=json_path,
                    store_dir=store_dir,
                    image_map_path=image_map_path,
                    download_missing=False,
                )
            finally:
                db.__exit__(None, None, None)

            self.assertEqual(result["images_matched"], 1)
            self.assertEqual(result["images_downloaded"], 0)

            db = Db(tmp / "test.sqlite")
            with db:
                row = db.query("select stored_path, sha256 from assets where source='pinterest'")
            self.assertEqual(row[0]["stored_path"], "store/originals/pinterest/existing.jpg")
            self.assertEqual(row[0]["sha256"], "abc123")

    def test_new_columns_populated(self):
        """New scrape columns should be populated correctly."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            json_path = tmp / "pins.json"
            json_path.write_text(json.dumps([SAMPLE_PINS[0]]))
            store_dir = tmp / "store"

            db = self._make_db(tmp)
            try:
                import_pinterest_scrape(db, json_path=json_path, store_dir=store_dir, download_missing=False)
            finally:
                db.__exit__(None, None, None)

            db = Db(tmp / "test.sqlite")
            with db:
                rows = db.query(
                    "select seo_alt_text, closeup_desc, dominant_color, hashtags, "
                    "image_width, image_height, engagement_json, scrape_json, source_url "
                    "from assets where source='pinterest'"
                )
            r = dict(rows[0])
            self.assertEqual(r["seo_alt_text"], "A kitchen with oak cabinets and marble countertops")
            self.assertEqual(r["closeup_desc"], "Lee Industries makes quality furniture")
            self.assertEqual(r["dominant_color"], "#cbc1b4")
            self.assertEqual(r["hashtags"], "kitchen,oak")
            self.assertEqual(r["image_width"], 600)
            self.assertEqual(r["image_height"], 400)
            self.assertEqual(r["source_url"], "https://example.com/kitchen")
            engagement = json.loads(r["engagement_json"])
            self.assertEqual(engagement["repins"], 42)
            self.assertEqual(engagement["comments"], 3)
            scrape = json.loads(r["scrape_json"])
            self.assertEqual(scrape["site_name"], "Example")

    def test_limit(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            json_path = tmp / "pins.json"
            json_path.write_text(json.dumps(SAMPLE_PINS[:2]))
            store_dir = tmp / "store"

            db = self._make_db(tmp)
            try:
                result = import_pinterest_scrape(
                    db, json_path=json_path, store_dir=store_dir, download_missing=False, limit=1
                )
            finally:
                db.__exit__(None, None, None)

            self.assertEqual(result["imported"], 1)


if __name__ == "__main__":
    unittest.main()
