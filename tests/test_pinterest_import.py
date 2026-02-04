import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from inspirations.db import Db, ensure_schema
from inspirations.importers.pinterest_crawler import import_pinterest_crawler_zip


class TestPinterestImport(unittest.TestCase):
    def _make_zip(self, path: Path, payload) -> None:
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr("export.json", json.dumps(payload))

    def test_import_is_idempotent(self):
        payload = [
            {
                "id": 123,
                "seo_url": "/pin/123/",
                "title": "A pin",
                "board": "kitchen",
                "image": {"url": "https://example.com/a.jpg", "width": 100, "height": 100},
                "created_at": "Tue, 27 Jan 2026 15:46:34 +0000",
            }
        ]
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            zip_path = Path(td) / "p.zip"
            self._make_zip(zip_path, payload)

            with Db(db_path) as db:
                ensure_schema(db)
                import_pinterest_crawler_zip(db, zip_path)
                import_pinterest_crawler_zip(db, zip_path)
                n = db.query_value("select count(*) from assets where source='pinterest'")
            self.assertEqual(n, 1)


if __name__ == "__main__":
    unittest.main()

