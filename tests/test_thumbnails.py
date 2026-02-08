import tempfile
import unittest
from pathlib import Path
from unittest import mock

from inspirations.db import Db, ensure_schema
from inspirations.thumbnails import generate_thumbnails


class TestThumbnails(unittest.TestCase):
    def test_no_tool_reports_error(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            db_path = base / "t.sqlite"
            stored = base / "a.jpg"
            stored.write_bytes(b"fake")

            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, imported_at, stored_path)
                    values (?, ?, ?, datetime('now'), ?)
                    """,
                    ("a1", "scan", "scan://x", str(stored)),
                )
                with mock.patch("inspirations.thumbnails.shutil.which", return_value=None):
                    report = generate_thumbnails(db, store_dir=base / "store")

            self.assertEqual(report["generated"], 0)
            self.assertTrue(report["errors"])

    def test_svg_falls_back_to_original_when_raster_conversion_fails(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            db_path = base / "t.sqlite"
            store_dir = base / "store"
            stored = store_dir / "originals" / "facebook" / "a1.svg"
            stored.parent.mkdir(parents=True, exist_ok=True)
            stored.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="40"><rect width="100" height="40"/></svg>',
                encoding="utf-8",
            )

            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, imported_at, stored_path)
                    values (?, ?, ?, datetime('now'), ?)
                    """,
                    ("a1", "facebook", "https://example.com/x", str(stored)),
                )
                with mock.patch(
                    "inspirations.thumbnails._make_thumb",
                    side_effect=RuntimeError("svg conversion failed"),
                ):
                    with mock.patch("inspirations.thumbnails._can_use_pillow", return_value=False):
                        report = generate_thumbnails(
                            db,
                            store_dir=store_dir,
                            source="facebook",
                            tool="sips",
                        )
                row = db.query("select thumb_path from assets where id=?", ("a1",))[0]

            self.assertEqual(report["generated"], 1)
            self.assertEqual(report["errors"], [])
            self.assertEqual(row["thumb_path"], str(stored))

    def test_non_svg_conversion_failure_still_reports_error(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            db_path = base / "t.sqlite"
            store_dir = base / "store"
            stored = store_dir / "originals" / "facebook" / "a1.jpg"
            stored.parent.mkdir(parents=True, exist_ok=True)
            stored.write_bytes(b"jpg")

            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, imported_at, stored_path)
                    values (?, ?, ?, datetime('now'), ?)
                    """,
                    ("a1", "facebook", "https://example.com/x", str(stored)),
                )
                with mock.patch(
                    "inspirations.thumbnails._make_thumb",
                    side_effect=RuntimeError("conversion failed"),
                ):
                    with mock.patch("inspirations.thumbnails._can_use_pillow", return_value=False):
                        report = generate_thumbnails(
                            db,
                            store_dir=store_dir,
                            source="facebook",
                            tool="sips",
                        )
                row = db.query("select thumb_path from assets where id=?", ("a1",))[0]

            self.assertEqual(report["generated"], 0)
            self.assertEqual(len(report["errors"]), 1)
            self.assertIsNone(row["thumb_path"])


if __name__ == "__main__":
    unittest.main()
