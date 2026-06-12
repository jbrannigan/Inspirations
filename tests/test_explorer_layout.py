from __future__ import annotations

import json
import random
import tempfile
import unittest
from pathlib import Path

from inspirations.db import Db
from inspirations.explorer_layout import compute_layout, _cache_key


def _make_db(tmp_dir: str, asset_count: int = 20, collection_id: str | None = None) -> Path:
    """Create a SQLite DB file with fake embeddings and labels. Returns the path."""
    db_path = Path(tmp_dir) / "test.sqlite"
    with Db(db_path) as db:
        db.exec(
            """
            create table if not exists assets (
                id text primary key,
                title text,
                thumb_path text,
                media_status text
            )
            """
        )
        db.exec(
            """
            create table if not exists asset_embeddings (
                id text primary key,
                asset_id text,
                provider text,
                model text,
                input_text text,
                vector_json text,
                dimensions integer,
                created_at text
            )
            """
        )
        db.exec(
            """
            create table if not exists asset_labels (
                id text primary key,
                asset_id text,
                label text,
                confidence real,
                source text,
                model text,
                run_id text,
                created_at text
            )
            """
        )
        db.exec(
            """
            create table if not exists collection_items (
                id text primary key,
                collection_id text,
                asset_id text,
                position integer
            )
            """
        )

        rng = random.Random(0)
        labels_pool = ["Kitchen", "Oak", "Warm", "Living Room", "Blue", "Modern", "Cozy"]
        for i in range(asset_count):
            aid = f"asset-{i:04d}"
            vec = [rng.gauss(0, 1) for _ in range(64)]
            db.exec(
                "insert into assets values (?,?,?,?)",
                (aid, f"Title {i}", f"store/thumbs/{aid}.jpg", "image"),
            )
            db.exec(
                "insert into asset_embeddings values (?,?,?,?,?,?,?,?)",
                (f"emb-{i}", aid, "gemini", "text-embedding", None, json.dumps(vec), 64, "2024-01-01"),
            )
            for j, lbl in enumerate(rng.choices(labels_pool, k=2)):
                db.exec(
                    "insert into asset_labels values (?,?,?,?,?,?,?,?)",
                    (f"lbl-{i}-{j}", aid, lbl, 0.9, "ai", "gemini", None, "2024-01-01"),
                )

        if collection_id:
            for i in range(8):
                aid = f"asset-{i:04d}"
                db.exec(
                    "insert into collection_items values (?,?,?,?)",
                    (f"ci-{i}", collection_id, aid, i),
                )

    return db_path


class TestComputeLayout(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name) / "layouts"

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, db_path: Path, **kwargs):
        with Db(db_path) as db:
            return compute_layout(db, self.data_dir, **kwargs)

    def test_basic_shape(self):
        db_path = _make_db(self.tmp.name)
        result = self._run(db_path, method="pca")
        self.assertIn("nodes", result)
        self.assertIn("clusters", result)
        nodes = result["nodes"]
        self.assertEqual(len(nodes), 20)
        for node in nodes:
            self.assertIn("id", node)
            self.assertIn("x", node)
            self.assertIn("y", node)
            self.assertIn("z", node)
            self.assertIn("cluster_id", node)
            self.assertIn("thumb_url", node)
            self.assertIn("title", node)

    def test_clusters_have_required_fields(self):
        db_path = _make_db(self.tmp.name)
        result = self._run(db_path, method="pca")
        clusters = result["clusters"]
        self.assertGreater(len(clusters), 0)
        for cluster in clusters:
            self.assertIn("id", cluster)
            self.assertIn("label", cluster)
            self.assertIn("centroid", cluster)
            self.assertIn("color", cluster)
            self.assertIn("count", cluster)
            self.assertEqual(len(cluster["centroid"]), 3)

    def test_cluster_labels_from_asset_labels(self):
        db_path = _make_db(self.tmp.name)
        result = self._run(db_path, method="pca")
        labels = [c["label"] for c in result["clusters"]]
        has_real_label = any(
            "/" in label or any(w in label for w in ["Kitchen", "Oak", "Warm", "Living Room"])
            for label in labels
        )
        self.assertTrue(has_real_label, f"Expected real labels, got: {labels}")

    def test_empty_embeddings(self):
        db_path = Path(self.tmp.name) / "empty.sqlite"
        with Db(db_path) as db:
            db.exec("create table asset_embeddings (id text, asset_id text, vector_json text)")
            db.exec("create table assets (id text, title text, thumb_path text)")
            db.exec("create table asset_labels (id text, asset_id text, label text, confidence real, source text, model text, run_id text, created_at text)")
            db.exec("create table collection_items (id text, collection_id text, asset_id text, position integer)")

        result = self._run(db_path)
        self.assertEqual(result["nodes"], [])
        self.assertEqual(result["clusters"], [])

    def test_caching(self):
        db_path = _make_db(self.tmp.name)
        result1 = self._run(db_path, method="pca")

        ids = [n["id"] for n in result1["nodes"]]
        cache_file = next(self.data_dir.glob("*.json"))
        self.assertTrue(cache_file.exists(), "Cache file should be created")

        cached_id = ids[0]
        cache_file.write_text(
            json.dumps(
                {
                    "nodes": [
                        {
                            "id": cached_id,
                            "x": 1.0,
                            "y": 2.0,
                            "z": 3.0,
                            "cluster_id": 0,
                            "thumb_url": "",
                            "title": "sentinel",
                        }
                    ],
                    "clusters": [],
                }
            )
        )
        result2 = self._run(db_path, method="pca")
        self.assertEqual(len(result2["nodes"]), 1)
        self.assertEqual(result2["nodes"][0]["id"], cached_id, "Should return cached result")
        self.assertEqual(result2["nodes"][0]["title"], "sentinel", "Should return cached result")

    def test_refresh_bypasses_cache(self):
        db_path = _make_db(self.tmp.name)
        result1 = self._run(db_path, method="pca")

        ids = [n["id"] for n in result1["nodes"]]
        cache_file = next(self.data_dir.glob("*.json"))
        cached_id = ids[0]
        cache_file.write_text(
            json.dumps(
                {
                    "nodes": [
                        {
                            "id": cached_id,
                            "x": 1.0,
                            "y": 2.0,
                            "z": 3.0,
                            "cluster_id": 0,
                            "thumb_url": "",
                            "title": "sentinel",
                        }
                    ],
                    "clusters": [],
                }
            )
        )

        result2 = self._run(db_path, method="pca", refresh=True)
        node_titles = [n["title"] for n in result2["nodes"]]
        self.assertNotIn("sentinel", node_titles, "refresh=True should recompute")
        self.assertEqual(len(result2["nodes"]), 20)

    def test_cache_key_changes_when_embedding_signature_changes(self):
        ids = ["a1", "a2"]
        self.assertNotEqual(
            _cache_key(ids, method="pca", include_hidden=False, signature=(2, "2026-01-01T00:00:00", 20)),
            _cache_key(ids, method="pca", include_hidden=False, signature=(2, "2026-01-02T00:00:00", 20)),
        )

    def test_collection_id_filtering(self):
        cid = "col-001"
        db_path = _make_db(self.tmp.name, collection_id=cid)

        all_dir = self.data_dir / "all"
        col_dir = self.data_dir / "col"

        with Db(db_path) as db:
            result_all = compute_layout(db, all_dir, method="pca")
        with Db(db_path) as db:
            result_col = compute_layout(db, col_dir, method="pca", collection_id=cid)

        self.assertEqual(len(result_all["nodes"]), 20)
        self.assertEqual(len(result_col["nodes"]), 8)

        col_ids = {n["id"] for n in result_col["nodes"]}
        expected_ids = {f"asset-{i:04d}" for i in range(8)}
        self.assertEqual(col_ids, expected_ids)

    def test_thumb_url_set(self):
        db_path = _make_db(self.tmp.name, asset_count=5)
        result = self._run(db_path, method="pca")
        for node in result["nodes"]:
            self.assertTrue(
                node["thumb_url"].startswith("/media/"),
                f"Expected /media/... thumb_url, got {node['thumb_url']}",
            )


if __name__ == "__main__":
    unittest.main()
