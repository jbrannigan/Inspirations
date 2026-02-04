import tempfile
import unittest
from pathlib import Path

from inspirations.db import Db, ensure_schema
from inspirations.store import (
    add_items_to_collection,
    create_annotation,
    create_collection,
    list_annotations,
    list_assets,
    list_collection_items,
    list_collections,
    set_collection_order,
)


class TestStore(unittest.TestCase):
    def test_collections_and_items(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    "insert into assets (id, source, source_ref, title, imported_at) values (?, ?, ?, ?, datetime('now'))",
                    ("a1", "pinterest", "pin://1", "Kitchen cabinets"),
                )
                col = create_collection(db, name="Kitchen", description="Round 1")
                add_items_to_collection(db, collection_id=col["id"], asset_ids=["a1"])
                cols = list_collections(db)
                items = list_collection_items(db, collection_id=col["id"])
            self.assertEqual(cols[0]["count"], 1)
            self.assertEqual(items[0]["id"], "a1")

    def test_annotations(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    "insert into assets (id, source, source_ref, title, imported_at) values (?, ?, ?, ?, datetime('now'))",
                    ("a1", "pinterest", "pin://1", "Kitchen cabinets"),
                )
                ann = create_annotation(db, asset_id="a1", x=0.4, y=0.6, text="Hardware")
                anns = list_annotations(db, asset_id="a1")
            self.assertEqual(anns[0]["id"], ann["id"])

    def test_list_assets_with_query(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    "insert into assets (id, source, source_ref, title, imported_at) values (?, ?, ?, ?, datetime('now'))",
                    ("a1", "pinterest", "pin://1", "White oak cabinets"),
                )
                db.exec(
                    "insert into assets (id, source, source_ref, title, imported_at) values (?, ?, ?, ?, datetime('now'))",
                    ("a2", "pinterest", "pin://2", "Bathroom tile"),
                )
                res = list_assets(db, q="cabinet")
            self.assertEqual(len(res), 1)


if __name__ == "__main__":
    unittest.main()

