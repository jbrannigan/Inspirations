import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from inspirations.db import Db, ensure_schema
from inspirations.importers.facebook_saved import import_facebook_saved_zip


class TestFacebookImport(unittest.TestCase):
    def _make_zip(self, path: Path, payload: dict) -> None:
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr(
                "your_facebook_activity/saved_items_and_collections/your_saved_items.json",
                json.dumps(payload),
            )

    def test_import_only_items_with_source_url(self):
        payload = {
            "saves_v2": [
                {
                    "timestamp": 1694249767,
                    "title": "Saved link with image",
                    "attachments": [
                        {
                            "data": [
                                {
                                    "external_context": {
                                        "name": "images.example.com",
                                        "source": "https://images.example.com/a.jpg",
                                        "url": "images.example.com",
                                    }
                                }
                            ]
                        }
                    ],
                },
                {
                    "timestamp": 1440106109,
                    "title": "Saved place without URL",
                    "attachments": [{"data": [{"external_context": {"name": "Some Place"}}]}],
                },
            ]
        }
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            zip_path = Path(td) / "f.zip"
            self._make_zip(zip_path, payload)

            with Db(db_path) as db:
                ensure_schema(db)
                import_facebook_saved_zip(db, zip_path)
                n = db.query_value("select count(*) from assets where source='facebook'")
            self.assertEqual(n, 1)


if __name__ == "__main__":
    unittest.main()

