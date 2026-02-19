import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from inspirations.db import Db, ensure_schema
from inspirations.importers.facebook_saved import import_facebook_saved_zip


class TestFacebookImport(unittest.TestCase):
    def _make_zip(self, path: Path, payload: dict, collections: dict | None = None) -> None:
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr(
                "your_facebook_activity/saved_items_and_collections/your_saved_items.json",
                json.dumps(payload),
            )
            if collections is not None:
                z.writestr(
                    "your_facebook_activity/saved_items_and_collections/collections.json",
                    json.dumps(collections),
                )

    def test_import_media_and_reference_only_items(self):
        payload = {
            "saves_v2": [
                {
                    "timestamp": 1694249767,
                    "title": "Leslie Brannigan saved a link from Example Home's post.",
                    "attachments": [
                        {
                            "data": [
                                {
                                    "external_context": {
                                        "name": "Example Home",
                                        "source": "https://www.example.com/article",
                                        "url": "www.example.com",
                                    }
                                }
                            ]
                        }
                    ],
                },
                {
                    "timestamp": 1694249768,
                    "title": "Leslie Brannigan saved a product from Example Shop's post.",
                    "attachments": [
                        {
                            "data": [
                                {
                                    "external_context": {
                                        "name": "Example Shop Product",
                                        "source": "https://images.example.com/a.jpg",
                                        "url": "images.example.com",
                                    }
                                }
                            ]
                        }
                    ],
                },
                {"timestamp": 1694249770, "title": "Leslie Brannigan saved a reel."},
            ]
        }
        collections = {
            "collections_v2": [
                {
                    "timestamp": 1694249780,
                    "title": "Leslie Brannigan created a new collection: Home & Garden.",
                    "attachments": [{"data": [{"name": "Home & Garden"}]}],
                },
                {
                    "timestamp": 1694249781,
                    "title": "Leslie Brannigan created a new collection: Home & Garden.",
                    "attachments": [{"data": [{"name": "Home & Garden"}]}],
                },
            ]
        }
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            zip_path = Path(td) / "f.zip"
            self._make_zip(zip_path, payload, collections)

            with Db(db_path) as db:
                ensure_schema(db)
                report = import_facebook_saved_zip(db, zip_path)
                n = db.query_value("select count(*) from assets where source='facebook'")
                media_rows = db.query(
                    """
                    select source_ref, media_status, content_kind, creator_name, source_domain, source_name
                    from assets
                    where source='facebook'
                    order by created_at asc, source_ref asc
                    """
                )
                collection_count = db.query_value("select count(*) from source_collections where source='facebook'")

            self.assertEqual(n, 3)
            self.assertEqual(report["imported_assets"]["total"], 3)
            self.assertEqual(report["imported_assets"]["image"], 1)
            self.assertEqual(report["imported_assets"]["link_only"], 1)
            self.assertEqual(report["imported_assets"]["metadata_only"], 1)
            self.assertEqual(report["collections"]["imported"], 1)
            self.assertEqual(collection_count, 1)

            by_status = {r["media_status"]: dict(r) for r in media_rows}
            self.assertEqual(by_status["metadata_only"]["content_kind"], "reel")
            self.assertEqual(by_status["link_only"]["creator_name"], "Example Home")
            self.assertEqual(by_status["image"]["source_domain"], "images.example.com")

    def test_import_is_idempotent(self):
        payload = {
            "saves_v2": [
                {"timestamp": 1694249770, "title": "Leslie Brannigan saved a reel."},
                {
                    "timestamp": 1694249768,
                    "title": "Leslie Brannigan saved a link from Example's post.",
                    "attachments": [
                        {
                            "data": [
                                {
                                    "external_context": {
                                        "name": "Example",
                                        "source": "https://example.com/post",
                                        "url": "example.com",
                                    }
                                }
                            ]
                        }
                    ],
                },
            ]
        }
        collections = {
            "collections_v2": [
                {
                    "timestamp": 1694249780,
                    "title": "Leslie Brannigan created a new collection: Kitchen.",
                    "attachments": [{"data": [{"name": "Kitchen"}]}],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            zip_path = Path(td) / "f.zip"
            self._make_zip(zip_path, payload, collections)

            with Db(db_path) as db:
                ensure_schema(db)
                import_facebook_saved_zip(db, zip_path)
                import_facebook_saved_zip(db, zip_path)
                n_assets = db.query_value("select count(*) from assets where source='facebook'")
                n_collections = db.query_value("select count(*) from source_collections where source='facebook'")
            self.assertEqual(n_assets, 2)
            self.assertEqual(n_collections, 1)


if __name__ == "__main__":
    unittest.main()
