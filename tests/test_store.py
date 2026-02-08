import tempfile
import unittest
from pathlib import Path

from inspirations.db import Db, ensure_schema
from inspirations.store import (
    add_items_to_collection,
    create_annotation,
    create_collection,
    delete_assets,
    list_annotations,
    list_assets,
    list_collection_items,
    list_collections,
    remove_items_from_collection,
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
                db.exec("update assets set notes=? where id=?", ("blue cabinets", "a1"))
                res = list_assets(db, q="cabinet")
            self.assertEqual(len(res), 1)

    def test_list_assets_searches_labels_and_summary(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    "insert into assets (id, source, source_ref, title, imported_at, ai_summary) values (?, ?, ?, ?, datetime('now'), ?)",
                    ("a1", "pinterest", "pin://1", "Kitchen", "rustic kitchen with oak cabinets"),
                )
                db.exec(
                    """
                    insert into asset_labels (id, asset_id, label, confidence, source, model, run_id, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                    """,
                    ("l1", "a1", "oak cabinets", 0.7, "ai", "test", "r1"),
                )
                res_label = list_assets(db, q="oak")
                res_summary = list_assets(db, q="rustic")
            self.assertEqual(len(res_label), 1)
            self.assertEqual(len(res_summary), 1)

    def test_remove_items_from_collection(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    "insert into assets (id, source, source_ref, title, imported_at) values (?, ?, ?, ?, datetime('now'))",
                    ("a1", "pinterest", "pin://1", "Item 1"),
                )
                db.exec(
                    "insert into assets (id, source, source_ref, title, imported_at) values (?, ?, ?, ?, datetime('now'))",
                    ("a2", "pinterest", "pin://2", "Item 2"),
                )
                col = create_collection(db, name="Kitchen", description="Round 1")
                add_items_to_collection(db, collection_id=col["id"], asset_ids=["a1", "a2"])
                removed = remove_items_from_collection(db, collection_id=col["id"], asset_ids=["a1"])
                remaining = list_collection_items(db, collection_id=col["id"])
            self.assertEqual(removed, 1)
            self.assertEqual(len(remaining), 1)
            self.assertEqual(remaining[0]["id"], "a2")

    def test_delete_assets_cascades_and_returns_media_paths(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            store_dir = Path(td) / "store"
            original = store_dir / "originals" / "pinterest" / "a1.jpg"
            thumb = store_dir / "thumbs" / "pinterest" / "a1.jpg"
            original.parent.mkdir(parents=True, exist_ok=True)
            thumb.parent.mkdir(parents=True, exist_ok=True)
            original.write_bytes(b"img")
            thumb.write_bytes(b"th")

            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, imported_at, stored_path, thumb_path)
                    values (?, ?, ?, ?, datetime('now'), ?, ?)
                    """,
                    ("a1", "pinterest", "pin://1", "Kitchen cabinets", str(original), str(thumb)),
                )
                col = create_collection(db, name="Kitchen", description="Round 1")
                add_items_to_collection(db, collection_id=col["id"], asset_ids=["a1"])
                create_annotation(db, asset_id="a1", x=0.2, y=0.3, text="Handle")
                db.exec("insert into tray_items (asset_id, added_at) values (?, datetime('now'))", ("a1",))

                report = delete_assets(db, asset_ids=["a1"])
                items = list_collection_items(db, collection_id=col["id"])
                anns = list_annotations(db, asset_id="a1")
                remaining_assets = list_assets(db)
                tray_count = db.query_value("select count(*) from tray_items")

            self.assertEqual(report["deleted"], 1)
            self.assertIn(str(original), report["paths"])
            self.assertIn(str(thumb), report["paths"])
            self.assertEqual(len(items), 0)
            self.assertEqual(len(anns), 0)
            self.assertEqual(len(remaining_assets), 0)
            self.assertEqual(tray_count, 0)


if __name__ == "__main__":
    unittest.main()
