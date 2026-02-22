"""Tests for the Facebook scrape importer."""
from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path

from inspirations.db import Db, ensure_schema
from inspirations.importers.facebook_scrape import import_facebook_scrape, _parse_date


# Minimal 1x1 JPEG bytes (valid JPEG)
_TINY_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
    b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
    b"\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\x1c\xc0"
    b"\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00"
    b"\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xc4\x00\xb5\x10"
    b"\x00\x02\x01\x03\x03\x02\x04\x03\x05\x05\x04\x04\x00\x00\x01}\x01"
    b"\x02\x03\x00\x04\x11\x05\x12!1A\x06\x13Qa\x07\"q\x142\x81\x91\xa1"
    b"\x08#B\xb1\xc1\x15R\xd1\xf0$3br\x82\t\n\x16\x17\x18\x19\x1a%&'()*"
    b"456789:CDEFGHIJSTUVWXYZcdefghijstuvwxyz\x83\x84\x85\x86\x87\x88\x89"
    b"\x8a\x92\x93\x94\x95\x96\x97\x98\x99\x9a\xa2\xa3\xa4\xa5\xa6\xa7"
    b"\xa8\xa9\xaa\xb2\xb3\xb4\xb5\xb6\xb7\xb8\xb9\xba\xc2\xc3\xc4\xc5"
    b"\xc6\xc7\xc8\xc9\xca\xd2\xd3\xd4\xd5\xd6\xd7\xd8\xd9\xda\xe1\xe2"
    b"\xe3\xe4\xe5\xe6\xe7\xe8\xe9\xea\xf1\xf2\xf3\xf4\xf5\xf6\xf7\xf8"
    b"\xf9\xfa\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xfb\xd2\x8a(\x03\xff\xd9"
)


def _b64(data: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(data).decode()


SAMPLE_POSTS = [
    {
        "post_url": "https://www.facebook.com/watch/?v=111111",
        "collection_name": "furniture",
        "post_text": "Great sofa find for the living room",
        "creator_name": "Test Creator",
        "hashtags": ["furniture", "sofa"],
        "date": "December 18, 2025",
        "content_type": "reel",
        "engagement": {"likes": 100, "comments": 5},
        "images": [{"base64": _b64(_TINY_JPEG), "width": 720, "height": 1280}],
        "unavailable": False,
    },
    {
        "post_url": "https://www.facebook.com/post/222222",
        "collection_name": "kitchen",
        "post_text": None,
        "creator_name": None,
        "hashtags": [],
        "date": "January 3, 2026",
        "content_type": "post",
        "engagement": None,
        "images": [],
        "unavailable": False,
    },
    {
        "post_url": "https://www.facebook.com/post/333333",
        "collection_name": "other",
        "post_text": "This post was deleted",
        "creator_name": None,
        "hashtags": [],
        "date": None,
        "content_type": "post",
        "engagement": None,
        "images": [],
        "unavailable": True,
    },
]


class TestFacebookScrapeImport(unittest.TestCase):
    def _make_db(self, tmp: Path) -> Db:
        db_path = tmp / "test.sqlite"
        db = Db(db_path)
        db.__enter__()
        ensure_schema(db)
        return db

    def _write_scrape_file(self, tmp: Path, posts: list, name: str = "facebook_scrape_01.json") -> Path:
        p = tmp / name
        p.write_text(json.dumps(posts))
        return tmp

    def test_basic_import(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            self._write_scrape_file(tmp, SAMPLE_POSTS)
            store_dir = tmp / "store"

            db = self._make_db(tmp)
            try:
                result = import_facebook_scrape(db, json_dir=tmp, store_dir=store_dir)
            finally:
                db.__exit__(None, None, None)

            self.assertEqual(result["files_read"], 1)
            self.assertEqual(result["total_in_json"], 3)
            self.assertEqual(result["imported"], 3)
            self.assertEqual(result["images_saved"], 1)
            self.assertGreaterEqual(result["metadata_only"], 1)
            self.assertEqual(result["total_assets_for_source"], 3)

    def test_dedup(self):
        """Re-importing same JSON should not create duplicates."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            self._write_scrape_file(tmp, SAMPLE_POSTS[:1])
            store_dir = tmp / "store"

            for _ in range(2):
                db = self._make_db(tmp)
                try:
                    import_facebook_scrape(db, json_dir=tmp, store_dir=store_dir)
                finally:
                    db.__exit__(None, None, None)

            db = Db(tmp / "test.sqlite")
            with db:
                count = db.query_value("select count(*) from assets where source='facebook'")
            self.assertEqual(count, 1)

    def test_metadata_only_items(self):
        """Items with no images should be imported as metadata_only."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            self._write_scrape_file(tmp, [SAMPLE_POSTS[1]])
            store_dir = tmp / "store"

            db = self._make_db(tmp)
            try:
                import_facebook_scrape(db, json_dir=tmp, store_dir=store_dir)
            finally:
                db.__exit__(None, None, None)

            db = Db(tmp / "test.sqlite")
            with db:
                rows = db.query("select media_status, stored_path from assets where source='facebook'")
            self.assertEqual(rows[0]["media_status"], "metadata_only")
            self.assertIsNone(rows[0]["stored_path"])

    def test_date_parsing(self):
        self.assertEqual(_parse_date("December 18, 2025"), "2025-12-18T00:00:00+00:00")
        self.assertEqual(_parse_date("January 3, 2026"), "2026-01-03T00:00:00+00:00")
        self.assertIsNone(_parse_date("not a date"))
        self.assertIsNone(_parse_date(None))

    def test_unavailable_items(self):
        """Unavailable posts should be imported as metadata_only."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            self._write_scrape_file(tmp, [SAMPLE_POSTS[2]])
            store_dir = tmp / "store"

            db = self._make_db(tmp)
            try:
                result = import_facebook_scrape(db, json_dir=tmp, store_dir=store_dir)
            finally:
                db.__exit__(None, None, None)

            self.assertEqual(result["unavailable"], 1)
            db = Db(tmp / "test.sqlite")
            with db:
                rows = db.query("select media_status from assets where source='facebook'")
            self.assertEqual(rows[0]["media_status"], "metadata_only")

    def test_title_truncation(self):
        """Post text over 200 chars should be truncated in title."""
        long_text = "A" * 250
        post = {
            "post_url": "https://www.facebook.com/post/long",
            "collection_name": "test",
            "post_text": long_text,
            "date": "December 1, 2025",
            "images": [],
        }
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            self._write_scrape_file(tmp, [post])
            store_dir = tmp / "store"

            db = self._make_db(tmp)
            try:
                import_facebook_scrape(db, json_dir=tmp, store_dir=store_dir)
            finally:
                db.__exit__(None, None, None)

            db = Db(tmp / "test.sqlite")
            with db:
                rows = db.query("select title from assets where source='facebook'")
            self.assertEqual(len(rows[0]["title"]), 203)  # 200 + "..."
            self.assertTrue(rows[0]["title"].endswith("..."))

    def test_limit(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            self._write_scrape_file(tmp, SAMPLE_POSTS)
            store_dir = tmp / "store"

            db = self._make_db(tmp)
            try:
                result = import_facebook_scrape(db, json_dir=tmp, store_dir=store_dir, limit=1)
            finally:
                db.__exit__(None, None, None)

            self.assertEqual(result["imported"], 1)

    def test_multiple_json_files(self):
        """Importer should read all facebook_scrape_*.json files in directory."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "facebook_scrape_01.json").write_text(json.dumps([SAMPLE_POSTS[0]]))
            (tmp / "facebook_scrape_02.json").write_text(json.dumps([SAMPLE_POSTS[1]]))
            store_dir = tmp / "store"

            db = self._make_db(tmp)
            try:
                result = import_facebook_scrape(db, json_dir=tmp, store_dir=store_dir)
            finally:
                db.__exit__(None, None, None)

            self.assertEqual(result["files_read"], 2)
            self.assertEqual(result["total_in_json"], 2)


if __name__ == "__main__":
    unittest.main()
