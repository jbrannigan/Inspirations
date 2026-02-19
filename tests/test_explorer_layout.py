from __future__ import annotations

import json
import random
import sqlite3
import tempfile
import unittest
from pathlib import Path

from inspirations.explorer_layout import compute_layout, _cache_key


def _make_db(asset_count: int = 20, collection_id: str | None = None) -> sqlite3.Connection:
    """Create an in-memory SQLite DB with fake embeddings and labels."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        create table assets (
            id text primary key,
            title text,
            thumb_path text,
            media_status text
        );
        create table asset_embeddings (
            id text primary key,
            asset_id text,
            provider text,
            model text,
            input_text text,
            vector_json text,
            dimensions integer,
            created_at text
        );
        create table asset_labels (
            id text primary key,
            asset_id text,
            label text,
            confidence real,
            source text,
            model text,
            run_id text,
            created_at text
        );
        create table collection_items (
            id text primary key,
            collection_id text,
            asset_id text,
            position integer
        );
        """
    )
    rng = random.Random(0)
    labels_pool = ["Kitchen", "Oak", "Warm", "Living Room", "Blue", "Modern", "Cozy"]
    for i in range(asset_count):
        aid = f"asset-{i:04d}"
        vec = [rng.gauss(0, 1) for _ in range(64)]
        conn.execute(
            "insert into assets values (?,?,?,?)",
            (aid, f"Title {i}", f"store/thumbs/{aid}.jpg", "image"),
        )
        conn.execute(
            "insert into asset_embeddings values (?,?,?,?,?,?,?,?)",
            (f"emb-{i}", aid, "gemini", "text-embedding", None, json.dumps(vec), 64, "2024-01-01"),
        )
        # Add a couple labels per asset
        for j, lbl in enumerate(rng.choices(labels_pool, k=2)):
            conn.execute(
                "insert into asset_labels values (?,?,?,?,?,?,?,?)",
                (f"lbl-{i}-{j}", aid, lbl, 0.9, "ai", "gemini", None, "2024-01-01"),
            )

    if collection_id:
        # Put first 8 assets in the collection
        for i in range(8):
            aid = f"asset-{i:04d}"
            conn.execute(
                "insert into collection_items values (?,?,?,?)",
                (f"ci-{i}", collection_id, aid, i),
            )

    conn.commit()
    return conn


class TestComputeLayout(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_basic_shape(self):
        conn = _make_db(20)
        result = compute_layout(conn, self.data_dir, method="pca")
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
        conn = _make_db(20)
        result = compute_layout(conn, self.data_dir, method="pca")
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
        conn = _make_db(20)
        result = compute_layout(conn, self.data_dir, method="pca")
        # At least one cluster should have a label from our labels_pool (not just "Cluster N")
        labels = [c["label"] for c in result["clusters"]]
        has_real_label = any("/" in label or any(w in label for w in ["Kitchen", "Oak", "Warm", "Living Room"]) for label in labels)
        self.assertTrue(has_real_label, f"Expected real labels, got: {labels}")

    def test_empty_embeddings(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(
            """
            create table asset_embeddings (id text, asset_id text, vector_json text);
            create table assets (id text, title text, thumb_path text);
            create table asset_labels (id text, asset_id text, label text, confidence real, source text, model text, run_id text, created_at text);
            create table collection_items (id text, collection_id text, asset_id text, position integer);
            """
        )
        result = compute_layout(conn, self.data_dir)
        self.assertEqual(result["nodes"], [])
        self.assertEqual(result["clusters"], [])

    def test_caching(self):
        conn = _make_db(20)
        result1 = compute_layout(conn, self.data_dir, method="pca")

        # Corrupt the cache to verify second call reads from cache
        ids = [n["id"] for n in result1["nodes"]]
        cache_file = self.data_dir / f"{_cache_key(ids)}.json"
        self.assertTrue(cache_file.exists(), "Cache file should be created")

        # Overwrite cache with sentinel value
        cache_file.write_text(json.dumps({"nodes": [{"id": "sentinel"}], "clusters": []}))

        result2 = compute_layout(conn, self.data_dir, method="pca")
        self.assertEqual(result2["nodes"][0]["id"], "sentinel", "Should return cached result")

    def test_refresh_bypasses_cache(self):
        conn = _make_db(20)
        result1 = compute_layout(conn, self.data_dir, method="pca")

        ids = [n["id"] for n in result1["nodes"]]
        cache_file = self.data_dir / f"{_cache_key(ids)}.json"
        cache_file.write_text(json.dumps({"nodes": [{"id": "sentinel"}], "clusters": []}))

        result2 = compute_layout(conn, self.data_dir, method="pca", refresh=True)
        node_ids = [n["id"] for n in result2["nodes"]]
        self.assertNotIn("sentinel", node_ids, "refresh=True should recompute")
        self.assertEqual(len(result2["nodes"]), 20)

    def test_collection_id_filtering(self):
        cid = "col-001"
        conn = _make_db(20, collection_id=cid)

        result_all = compute_layout(conn, self.data_dir / "all", method="pca")
        result_col = compute_layout(conn, self.data_dir / "col", method="pca", collection_id=cid)

        self.assertEqual(len(result_all["nodes"]), 20)
        self.assertEqual(len(result_col["nodes"]), 8)

        # All nodes in filtered result should be from first 8 assets
        col_ids = {n["id"] for n in result_col["nodes"]}
        expected_ids = {f"asset-{i:04d}" for i in range(8)}
        self.assertEqual(col_ids, expected_ids)

    def test_thumb_url_set(self):
        conn = _make_db(5)
        result = compute_layout(conn, self.data_dir, method="pca")
        for node in result["nodes"]:
            self.assertTrue(
                node["thumb_url"].startswith("/media/"),
                f"Expected /media/... thumb_url, got {node['thumb_url']}",
            )


if __name__ == "__main__":
    unittest.main()
