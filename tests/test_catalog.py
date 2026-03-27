"""Tests for catalog generation and helpers."""

import json
import tempfile
import unittest
from pathlib import Path

from inspirations.catalog import (
    generate_catalog,
    load_catalog_files,
    load_catalog_index,
    load_manifest,
    resolve_short_ids,
)
from inspirations.db import Db, ensure_schema


def _seed_db(db):
    """Insert test assets spanning multiple sources and boards."""
    assets = [
        # Pinterest kitchen items
        *[(f"pk{i:04d}-0000-0000-0000-000000000000", "pinterest", f"Kitchen item {i}", "kitchen")
          for i in range(30)],
        # Pinterest bathroom items
        *[(f"pb{i:04d}-0000-0000-0000-000000000000", "pinterest", f"Bathroom item {i}", "bathroom")
          for i in range(20)],
        # Pinterest small board (fewer than 15)
        *[(f"ps{i:04d}-0000-0000-0000-000000000000", "pinterest", f"Tile item {i}", "tile")
          for i in range(5)],
        # Facebook items
        *[(f"fk{i:04d}-0000-0000-0000-000000000000", "facebook", f"FB Kitchen {i}", "kitchen")
          for i in range(18)],
        # Scan items (no board)
        *[(f"sc{i:04d}-0000-0000-0000-000000000000", "scan", f"Scan page {i}", None)
          for i in range(10)],
    ]
    for aid, source, title, board in assets:
        db.exec(
            """insert into assets (id, source, source_ref, title, board, imported_at)
               values (?, ?, ?, ?, ?, datetime('now'))""",
            (aid, source, f"ref://{aid}", title, board),
        )
    # Add some labels
    import uuid as _uuid
    for i in range(30):
        db.exec(
            "insert into asset_labels (id, asset_id, label, source, created_at) values (?, ?, ?, ?, datetime('now'))",
            (str(_uuid.uuid4()), f"pk{i:04d}-0000-0000-0000-000000000000", "kitchen", "test"),
        )
        db.exec(
            "insert into asset_labels (id, asset_id, label, source, created_at) values (?, ?, ?, ?, datetime('now'))",
            (str(_uuid.uuid4()), f"pk{i:04d}-0000-0000-0000-000000000000", "cabinets", "test"),
        )
    # Add a collection
    db.exec(
        "insert into collections (id, name, created_at, updated_at) values (?, ?, datetime('now'), datetime('now'))",
        ("col1", "Test Kitchen"),
    )
    db.exec(
        "insert into collection_items (collection_id, asset_id, position) values (?, ?, ?)",
        ("col1", "pk0000-0000-0000-0000-000000000000", 0),
    )


class TestCatalogGeneration(unittest.TestCase):
    """Test catalog generation from DB."""

    def test_generate_creates_files(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            catalog_dir = Path(td) / "catalog"
            with Db(db_path) as db:
                ensure_schema(db)
                _seed_db(db)
                report = generate_catalog(db, catalog_dir)

            # Check report
            self.assertGreater(report["total_items"], 0)
            self.assertGreater(report["files_written"], 0)

            # Check index exists
            self.assertTrue((catalog_dir / "_index.md").exists())

            # Check manifest exists and is valid JSON
            manifest_path = catalog_dir / "_manifest.json"
            self.assertTrue(manifest_path.exists())
            manifest = json.loads(manifest_path.read_text())
            self.assertIn("id_map", manifest)
            self.assertGreater(len(manifest["id_map"]), 0)

    def test_boards_grouped_by_source(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            catalog_dir = Path(td) / "catalog"
            with Db(db_path) as db:
                ensure_schema(db)
                _seed_db(db)
                generate_catalog(db, catalog_dir)

            # Pinterest kitchen board should exist (>=15 items)
            self.assertTrue((catalog_dir / "pinterest" / "kitchen.md").exists())
            # Pinterest bathroom should exist (>=15 items)
            self.assertTrue((catalog_dir / "pinterest" / "bathroom.md").exists())
            # Facebook kitchen should exist (>=15 items)
            self.assertTrue((catalog_dir / "facebook" / "kitchen.md").exists())

    def test_small_boards_merged(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            catalog_dir = Path(td) / "catalog"
            with Db(db_path) as db:
                ensure_schema(db)
                _seed_db(db)
                generate_catalog(db, catalog_dir)

            # Pinterest tile board has only 5 items — should be merged into _small.md
            self.assertFalse((catalog_dir / "pinterest" / "tile.md").exists())
            self.assertTrue((catalog_dir / "pinterest" / "_small.md").exists())

    def test_unboarded_items_collected(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            catalog_dir = Path(td) / "catalog"
            with Db(db_path) as db:
                ensure_schema(db)
                _seed_db(db)
                generate_catalog(db, catalog_dir)

            # Scan items have no board — should be in scan/_unboarded.md
            self.assertTrue((catalog_dir / "scan" / "_unboarded.md").exists())

    def test_index_contains_source_sections(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            catalog_dir = Path(td) / "catalog"
            with Db(db_path) as db:
                ensure_schema(db)
                _seed_db(db)
                generate_catalog(db, catalog_dir)

            index = load_catalog_index(catalog_dir)
            self.assertIn("Pinterest", index)
            self.assertIn("Facebook", index)
            self.assertIn("Scan", index)
            self.assertIn("kitchen", index.lower())

    def test_hidden_collections_excluded_from_index(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            catalog_dir = Path(td) / "catalog"
            with Db(db_path) as db:
                ensure_schema(db)
                _seed_db(db)
                db.exec(
                    "insert into collections (id, name, hidden, created_at, updated_at) values (?, ?, 1, datetime('now'), datetime('now'))",
                    ("col_hidden", "Hidden Collection"),
                )
                generate_catalog(db, catalog_dir)

            index = load_catalog_index(catalog_dir) or ""
            self.assertIn("Test Kitchen", index)
            self.assertNotIn("Hidden Collection", index)

    def test_manifest_id_map(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            catalog_dir = Path(td) / "catalog"
            with Db(db_path) as db:
                ensure_schema(db)
                _seed_db(db)
                generate_catalog(db, catalog_dir)

            manifest = load_manifest(catalog_dir)
            self.assertIsNotNone(manifest)
            id_map = manifest["id_map"]
            # Check that 8-char prefix maps to full UUID
            full_id = "pk0000-0000-0000-0000-000000000000"
            self.assertEqual(id_map.get(full_id[:8]), full_id)


class TestCatalogLoading(unittest.TestCase):
    """Test catalog file loading and ID resolution."""

    def _setup_catalog(self):
        td = tempfile.mkdtemp()
        db_path = Path(td) / "t.sqlite"
        catalog_dir = Path(td) / "catalog"
        with Db(db_path) as db:
            ensure_schema(db)
            _seed_db(db)
            generate_catalog(db, catalog_dir)
        return td, catalog_dir

    def test_load_catalog_files(self):
        td, catalog_dir = self._setup_catalog()
        content = load_catalog_files(catalog_dir, ["pinterest/kitchen.md"])
        self.assertIn("Kitchen item", content)

    def test_load_nonexistent_file(self):
        td, catalog_dir = self._setup_catalog()
        content = load_catalog_files(catalog_dir, ["nonexistent/board.md"])
        self.assertEqual(content, "")

    def test_resolve_short_ids(self):
        td, catalog_dir = self._setup_catalog()
        manifest = load_manifest(catalog_dir)
        full_id = "pk0000-0000-0000-0000-000000000000"
        short = full_id[:8]
        resolved = resolve_short_ids(manifest, [short])
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0], full_id)

    def test_resolve_unknown_short_id(self):
        td, catalog_dir = self._setup_catalog()
        manifest = load_manifest(catalog_dir)
        resolved = resolve_short_ids(manifest, ["zzzzzzzz"])
        # Unknown IDs are dropped
        self.assertEqual(resolved, [])

    def test_load_index_missing_dir(self):
        result = load_catalog_index(Path("/nonexistent/catalog"))
        self.assertIsNone(result)


class TestResolveShortIds(unittest.TestCase):
    """Test resolve_short_ids with a synthetic manifest."""

    def test_basic_resolution(self):
        manifest = {
            "id_map": {
                "a1b2c3d4": "a1b2c3d4-5678-9012-3456-789012345678",
                "deadbeef": "deadbeef-1234-5678-9abc-def012345678",
            }
        }
        result = resolve_short_ids(manifest, ["a1b2c3d4", "deadbeef"])
        self.assertEqual(result, [
            "a1b2c3d4-5678-9012-3456-789012345678",
            "deadbeef-1234-5678-9abc-def012345678",
        ])

    def test_mixed_known_unknown(self):
        manifest = {
            "id_map": {
                "a1b2c3d4": "a1b2c3d4-full-uuid",
            }
        }
        result = resolve_short_ids(manifest, ["a1b2c3d4", "unknown1"])
        # Unknown IDs are dropped (they can't match anything in the DB)
        self.assertEqual(result, ["a1b2c3d4-full-uuid"])


if __name__ == "__main__":
    unittest.main()
