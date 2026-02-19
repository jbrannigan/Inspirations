import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from inspirations.db import Db, ensure_schema


def _load_export_module():
    path = Path(__file__).resolve().parent.parent / "tools" / "export_clusters.py"
    spec = importlib.util.spec_from_file_location("export_clusters_tool", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestExportClusters(unittest.TestCase):
    def _insert_embedding(self, db: Db, *, emb_id: str, asset_id: str, vector: list[float]) -> None:
        db.exec(
            """
            insert into asset_embeddings
              (id, asset_id, provider, model, input_text, vector_json, dimensions, created_at)
            values (?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                emb_id,
                asset_id,
                "gemini",
                "gemini-embedding-001",
                "",
                json.dumps(vector),
                len(vector),
            ),
        )

    def test_export_clusters_writes_v2_schema(self):
        export_clusters = _load_export_module()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store_thumb = root / "store" / "thumbs" / "pinterest" / "a1.jpg"
            store_original = root / "store" / "originals" / "pinterest" / "a1.jpg"
            store_thumb.parent.mkdir(parents=True, exist_ok=True)
            store_original.parent.mkdir(parents=True, exist_ok=True)
            store_thumb.write_bytes(b"thumb")
            store_original.write_bytes(b"orig")

            db_path = root / "data.sqlite"
            out_path = root / "cluster_data.json"

            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets
                      (id, source, source_ref, title, imported_at, media_status, thumb_path, stored_path, image_url)
                    values (?, ?, ?, ?, datetime('now'), ?, ?, ?, ?)
                    """,
                    (
                        "a1",
                        "pinterest",
                        "pin://123",
                        "Pin token",
                        "image",
                        str(store_thumb),
                        str(store_original),
                        "https://img.example.com/a1.jpg",
                    ),
                )
                db.exec(
                    """
                    insert into assets
                      (id, source, source_ref, title, imported_at, media_status, image_url)
                    values (?, ?, ?, ?, datetime('now'), ?, ?)
                    """,
                    ("a2", "pinterest", "https://www.pinterest.com/pin/456", "Pin url", "image", "https://img.example.com/a2.jpg"),
                )
                db.exec(
                    """
                    insert into assets
                      (id, source, source_ref, title, imported_at, media_status)
                    values (?, ?, ?, ?, datetime('now'), ?)
                    """,
                    ("a3", "facebook", "facebook://saved/abc", "FB synthetic", "image"),
                )
                db.exec(
                    """
                    insert into assets
                      (id, source, source_ref, title, imported_at, media_status, stored_path)
                    values (?, ?, ?, ?, datetime('now'), ?, ?)
                    """,
                    ("a4", "pinterest", "pin://999", "Outside path", "image", "/tmp/outside.jpg"),
                )

                db.exec(
                    """
                    insert into collections (id, name, description, created_at, updated_at)
                    values (?, ?, ?, datetime('now'), datetime('now'))
                    """,
                    ("c1", "CB: Kitchen", ""),
                )
                db.exec("insert into collection_items (collection_id, asset_id, position) values (?, ?, ?)", ("c1", "a1", 1))
                db.exec("insert into collection_items (collection_id, asset_id, position) values (?, ?, ?)", ("c1", "a2", 2))
                db.exec(
                    """
                    insert into asset_labels (id, asset_id, label, confidence, source, model, run_id, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                    """,
                    ("l1", "a1", "white oak", 0.9, "ai", "test", "r1"),
                )

                self._insert_embedding(db, emb_id="e1", asset_id="a1", vector=[1.0, 0.0, 0.0])
                self._insert_embedding(db, emb_id="e2", asset_id="a2", vector=[0.92, 0.08, 0.0])
                self._insert_embedding(db, emb_id="e3", asset_id="a3", vector=[0.0, 1.0, 0.0])
                self._insert_embedding(db, emb_id="e4", asset_id="a4", vector=[0.85, 0.15, 0.0])

            payload = export_clusters.export_clusters(
                db_path=str(db_path),
                out_path=str(out_path),
                sim_threshold=0.5,
                max_neighbors=4,
                clusters="none",
                collection_id="",
                include_neighbors=0,
                api_base="http://minime.local:8000",
                project_root=root,
            )

            self.assertTrue(out_path.exists())
            self.assertEqual(payload["meta"]["source_db"], str(db_path))
            self.assertEqual(payload["meta"]["api_base"], "http://minime.local:8000")
            self.assertEqual(payload["meta"]["total_assets"], 4)
            self.assertEqual(payload["meta"]["collection_name"], "")
            self.assertEqual(payload["meta"]["focus_count"], 0)
            self.assertEqual(payload["meta"]["nearby_count"], 0)

            nodes = {node["id"]: node for node in payload["nodes"]}
            self.assertEqual(nodes["a1"]["source_url"], "https://www.pinterest.com/pin/123")
            self.assertEqual(nodes["a2"]["source_url"], "https://www.pinterest.com/pin/456")
            self.assertEqual(nodes["a3"]["source_url"], "")
            self.assertEqual(nodes["a1"]["thumb_url_local"], "store/thumbs/pinterest/a1.jpg")
            self.assertEqual(nodes["a1"]["image_url_local"], "store/originals/pinterest/a1.jpg")
            self.assertEqual(nodes["a4"]["image_url_local"], "")
            self.assertEqual(nodes["a1"]["collection_ids"], ["c1"])
            self.assertIn("isolation_score", nodes["a1"])
            self.assertIn("bridge_score", nodes["a1"])
            self.assertIn("is_outlier", nodes["a1"])
            self.assertFalse(nodes["a1"]["in_focus_collection"])
            self.assertFalse(nodes["a1"]["is_nearby_context"])
            self.assertTrue(any(node["is_outlier"] for node in payload["nodes"]))

    def test_export_clusters_collection_scope_includes_neighbors(self):
        export_clusters = _load_export_module()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / "data.sqlite"
            out_path = root / "cluster_data.json"

            with Db(db_path) as db:
                ensure_schema(db)
                for asset_id in ("a1", "a2", "a3"):
                    db.exec(
                        """
                        insert into assets (id, source, source_ref, title, imported_at, media_status)
                        values (?, ?, ?, ?, datetime('now'), ?)
                        """,
                        (asset_id, "pinterest", f"pin://{asset_id}", asset_id, "image"),
                    )

                db.exec(
                    """
                    insert into collections (id, name, description, created_at, updated_at)
                    values (?, ?, ?, datetime('now'), datetime('now'))
                    """,
                    ("focus", "Focus", ""),
                )
                db.exec("insert into collection_items (collection_id, asset_id, position) values (?, ?, ?)", ("focus", "a1", 1))

                self._insert_embedding(db, emb_id="e1", asset_id="a1", vector=[1.0, 0.0])
                self._insert_embedding(db, emb_id="e2", asset_id="a2", vector=[0.95, 0.05])
                self._insert_embedding(db, emb_id="e3", asset_id="a3", vector=[0.0, 1.0])

            payload = export_clusters.export_clusters(
                db_path=str(db_path),
                out_path=str(out_path),
                sim_threshold=0.1,
                max_neighbors=4,
                clusters="none",
                collection_id="focus",
                include_neighbors=1,
                api_base="",
                project_root=root,
            )

            ids = {node["id"] for node in payload["nodes"]}
            self.assertEqual(ids, {"a1", "a2"})
            self.assertEqual(payload["meta"]["collection_id"], "focus")
            self.assertEqual(payload["meta"]["collection_name"], "Focus")
            self.assertEqual(payload["meta"]["include_neighbors"], 1)
            self.assertEqual(payload["meta"]["focus_count"], 1)
            self.assertEqual(payload["meta"]["nearby_count"], 1)

            nodes = {node["id"]: node for node in payload["nodes"]}
            self.assertTrue(nodes["a1"]["in_focus_collection"])
            self.assertFalse(nodes["a1"]["is_nearby_context"])
            self.assertFalse(nodes["a2"]["in_focus_collection"])
            self.assertTrue(nodes["a2"]["is_nearby_context"])


if __name__ == "__main__":
    unittest.main()
