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


if __name__ == "__main__":
    unittest.main()

