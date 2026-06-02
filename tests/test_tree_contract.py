"""Tree contract test: every node the browse tree displays must deliver items.

The browse tree presents the user with a hierarchy of clickable nodes, each
showing a label and a count. The **contract** is:

    "Click a group to see those items. The count tells you how many."

If a node has count > 0 but clicking it returns zero items, the contract is
broken. This test enforces that invariant end-to-end by:

  1. Seeding a database with realistic multi-source, multi-board data
     (including some hidden items to exercise triage filtering).
  2. Generating a catalog (the same pipeline the real app uses).
  3. Starting a real HTTP server with both db_path and catalog_dir.
  4. Fetching /api/catalog/tree.
  5. For EVERY node with count > 0, hitting the same API the frontend would
     use and asserting items come back:
       - Source boards (regular): /api/assets?source=X&board=Y
       - Source subtype branches: /api/assets?source=X&content_kind=Y
       - Source boards (synthetic/catch-all): /api/catalog/items?file=X
       - Dimension children: /api/catalog/items?file=X
"""

import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import HTTPServer
from pathlib import Path

from inspirations.catalog import generate_catalog
from inspirations.db import Db, ensure_schema
from inspirations.server import ApiHandler


def _seed_assets(db: Db) -> None:
    """Seed realistic multi-source data with boards and some hidden items.

    IDs must be valid hex UUIDs so the catalog's 8-char prefix regex
    (``[0-9a-f]{8}``) can match them in catalog files.
    """
    assets = [
        # Pinterest — kitchen (20 items, all visible)
        *[
            (f"aa00{i:04x}-1000-4000-a000-000000000000", "pinterest", f"Pin Kitchen {i}", "kitchen", None)
            for i in range(20)
        ],
        # Pinterest — bathroom (18 items, all visible)
        *[
            (f"bb00{i:04x}-1000-4000-a000-000000000000", "pinterest", f"Pin Bathroom {i}", "bathroom", None)
            for i in range(18)
        ],
        # Pinterest — small board "tile" (5 items, will merge into _small.md)
        *[
            (f"cc00{i:04x}-1000-4000-a000-000000000000", "pinterest", f"Pin Tile {i}", "tile", None)
            for i in range(5)
        ],
        # Pinterest — 3 hidden items in kitchen (should reduce visible count)
        *[
            (f"dd00{i:04x}-1000-4000-a000-000000000000", "pinterest", f"Pin Hidden {i}", "kitchen", "hidden")
            for i in range(3)
        ],
        # Facebook — kitchen (18 items, all visible)
        *[
            (f"ee00{i:04x}-1000-4000-a000-000000000000", "facebook", f"FB Kitchen {i}", "kitchen", None)
            for i in range(18)
        ],
        # Facebook — no board / unsorted (10 items, will land in _unboarded)
        *[
            (f"ff00{i:04x}-1000-4000-a000-000000000000", "facebook", f"FB Unsorted {i}", None, None)
            for i in range(10)
        ],
        # Scan — no board (15 items, all visible)
        *[
            (f"ab00{i:04x}-1000-4000-a000-000000000000", "scan", f"Scan {i}", None, None)
            for i in range(15)
        ],
    ]
    for aid, source, title, board, triage in assets:
        db.exec(
            """insert into assets (id, source, source_ref, title, board,
                   triage_status, imported_at)
               values (?, ?, ?, ?, ?, ?, datetime('now'))""",
            (aid, source, f"ref://{aid}", title, board, triage),
        )

    # Clip subtype rows under source=scan to validate JIM-2 branches.
    for i in range(4):
        aid = f"a100{i:04x}-1000-4000-a000-000000000000"
        db.exec(
            """insert into assets (id, source, source_ref, title, board,
                   triage_status, imported_at, content_kind)
               values (?, ?, ?, ?, ?, ?, datetime('now'), ?)""",
            (aid, "scan", f"clip-photo://{aid}", f"Scan Photo {i}", None, None, "photo"),
        )
    for i in range(3):
        aid = f"a200{i:04x}-1000-4000-a000-000000000000"
        db.exec(
            """insert into assets (id, source, source_ref, title, board,
                   triage_status, imported_at, content_kind)
               values (?, ?, ?, ?, ?, ?, datetime('now'), ?)""",
            (aid, "scan", f"clip-video://{aid}", f"Scan Video {i}", None, None, "video"),
        )


class TestTreeContract(unittest.TestCase):
    """Every tree node with count > 0 must deliver items via the correct API."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.db_path = self.tmp_path / "t.sqlite"
        self.store_dir = self.tmp_path / "store"
        self.store_dir.mkdir()
        self.catalog_dir = self.tmp_path / "catalog"

        with Db(self.db_path) as db:
            ensure_schema(db)
            _seed_assets(db)
            db.exec(
                "insert into actors (id, name, token, role, created_at) values (?, ?, ?, ?, datetime('now'))",
                ("owner-tree", "Owner", "owner-tree-token", "owner"),
            )
            generate_catalog(db, self.catalog_dir)

        self.server = HTTPServer(("127.0.0.1", 0), ApiHandler)
        self.server.db_path = self.db_path
        self.server.app_dir = Path(__file__).resolve().parent.parent / "app"
        self.server.store_dir = self.store_dir
        self.server.catalog_dir = str(self.catalog_dir)
        self.server.imports_dir = self.tmp_path / "imports"
        self.server.admin_tokens = {}
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                self._get("/api/assets")
                break
            except Exception:
                time.sleep(0.05)
        else:
            raise RuntimeError("server did not start in time")

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self._tmp.cleanup()

    def _get(self, path: str, *, headers: dict | None = None) -> dict:
        """GET a JSON endpoint, return parsed body."""
        req = urllib.request.Request(f"{self.base_url}{path}", headers=headers or {})
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))

    # ------------------------------------------------------------------
    # The contract test
    # ------------------------------------------------------------------

    def test_every_visible_tree_node_returns_items(self):
        """For every tree node with count > 0, the API it targets must return items."""
        tree = self._get("/api/catalog/tree")["tree"]
        self.assertGreater(len(tree), 0, "tree should not be empty")

        failures = []

        for node in tree:
            if node.get("type") == "source":
                self._check_source_children(node, failures)
            elif node.get("type") == "dimension":
                self._check_dimension_children(node, failures)

        if failures:
            detail = "\n".join(f"  - {f}" for f in failures)
            self.fail(f"Tree contract violated — nodes with count > 0 returned no items:\n{detail}")

    def _check_source_children(self, node: dict, failures: list[str]) -> None:
        """Check each child of a source node."""
        src_label = node["label"]
        for child in node.get("children", []):
            count = child.get("count", 0)
            if count <= 0:
                continue

            if child.get("type") == "source_subtype":
                kind = str(child.get("content_kind") or "").strip().lower()
                data = self._get(
                    f"/api/assets?source={urllib.parse.quote(src_label.lower())}"
                    f"&content_kind={urllib.parse.quote(kind)}&limit=1"
                )
                items = data.get("assets", [])
                if not items:
                    failures.append(
                        f"{src_label} > {child.get('label', kind)} "
                        f"(count={count}, subtype={kind}): 0 items returned"
                    )
                continue

            board_name = child.get("board_name", "")
            is_catch_all = board_name.startswith("(")

            if is_catch_all and child.get("file"):
                # Synthetic boards use catalog file path (same as frontend)
                data = self._get(
                    f"/api/catalog/items?file={urllib.request.quote(child['file'])}&limit=1"
                )
                items = data.get("assets", [])
            else:
                # Regular boards filter by source + board name
                data = self._get(
                    f"/api/assets?source={urllib.request.quote(src_label.lower())}"
                    f"&board={urllib.request.quote(board_name)}&limit=1"
                )
                items = data.get("assets", [])

            if not items:
                failures.append(
                    f"{src_label} > {child.get('label', board_name)} "
                    f"(count={count}, catch_all={is_catch_all}): 0 items returned"
                )

    def _check_dimension_children(self, node: dict, failures: list[str]) -> None:
        """Check each child of a dimension node."""
        dim_label = node["label"]
        for child in node.get("children", []):
            count = child.get("count", 0)
            if count <= 0 or not child.get("file"):
                continue

            data = self._get(
                f"/api/catalog/items?file={urllib.request.quote(child['file'])}&limit=1"
            )
            items = data.get("assets", [])

            if not items:
                failures.append(
                    f"{dim_label} > {child.get('label', '')} "
                    f"(count={count}, file={child['file']}): 0 items returned"
                )

    # ------------------------------------------------------------------
    # Focused contract checks
    # ------------------------------------------------------------------

    def test_hidden_source_still_shows_if_it_has_items(self):
        """A source with SOME hidden items should still appear in the tree
        with a reduced count (not removed entirely)."""
        tree = self._get("/api/catalog/tree")["tree"]
        sources = {n["label"].lower(): n for n in tree if n.get("type") == "source"}

        # Pinterest has 3 hidden items out of 43 total — should still appear
        self.assertIn("pinterest", sources, "Pinterest should appear in tree")
        pin = sources["pinterest"]
        # Count should reflect visible items (43 total - 3 hidden = 40)
        self.assertGreater(pin["count"], 0, "Pinterest count should be > 0")
        self.assertLess(
            pin["count"], 46,  # 43 + 3 hidden = 46 total
            "Pinterest count should be less than total (some are hidden)",
        )

    def test_all_hidden_source_removed_from_tree(self):
        """If ALL items for a source are hidden, it should not appear in the tree."""
        # Hide every scan item
        with Db(self.db_path) as db:
            db.exec("update assets set triage_status = 'hidden' where source = 'scan'")

        tree = self._get("/api/catalog/tree")["tree"]
        source_labels = [n["label"].lower() for n in tree if n.get("type") == "source"]

        self.assertNotIn("scan", source_labels,
                         "Fully-hidden source should be removed from tree")

    def test_collections_group_is_alphabetized(self):
        """Collections in the browse tree should be stable and alphabetical."""
        with Db(self.db_path) as db:
            ensure_schema(db)
            db.exec(
                """
                insert into collections (id, name, description, created_at, updated_at, hidden)
                values (?, ?, ?, ?, ?, 0)
                """,
                ("c-zebra", "CB: Zebra", "", "2026-03-01T00:00:00+00:00", "2026-03-02T00:00:03+00:00"),
            )
            db.exec(
                """
                insert into collections (id, name, description, created_at, updated_at, hidden)
                values (?, ?, ?, ?, ?, 0)
                """,
                ("c-alpha", "CB: Alpha", "", "2026-03-01T00:00:00+00:00", "2026-03-02T00:00:01+00:00"),
            )
            db.exec(
                """
                insert into collections (id, name, description, created_at, updated_at, hidden)
                values (?, ?, ?, ?, ?, 0)
                """,
                ("c-bath", "Bathroom", "", "2026-03-01T00:00:00+00:00", "2026-03-02T00:00:02+00:00"),
            )
            db.exec(
                """
                insert into collections (id, name, description, created_at, updated_at, hidden, provenance_kind)
                values (?, ?, ?, ?, ?, 1, ?)
                """,
                ("c-hidden", "CB: Hidden", "", "2026-03-01T00:00:00+00:00", "2026-03-02T00:00:04+00:00", "human_curated"),
            )
            db.exec(
                """
                insert into collections (id, name, description, created_at, updated_at, hidden, provenance_kind)
                values (?, ?, ?, ?, ?, 1, ?)
                """,
                ("c-review", "Review: Done", "", "2026-03-01T00:00:00+00:00", "2026-03-02T00:00:05+00:00", "workflow_review"),
            )
            db.exec(
                """
                insert into collections (id, name, description, created_at, updated_at, hidden, provenance_kind)
                values (?, ?, ?, ?, ?, 1, ?)
                """,
                ("c-mirror", "pins: kitchen", "", "2026-03-01T00:00:00+00:00", "2026-03-02T00:00:06+00:00", "source_mirror"),
            )

        tree = self._get("/api/catalog/tree", headers={"X-Actor-Token": "owner-tree-token"})["tree"]
        collections_node = next((n for n in tree if n.get("type") == "collections_group"), None)
        self.assertIsNotNone(collections_node, "collections group should be present")
        labels = [str(c.get("label") or "") for c in collections_node.get("children", [])]
        self.assertEqual(labels, ["Bathroom", "CB: Alpha", "CB: Zebra", "Archived Collections"])
        self.assertEqual(collections_node.get("count"), 6)
        hidden_branch = next((c for c in collections_node.get("children", []) if c.get("type") == "collections_hidden_group"), None)
        self.assertIsNotNone(hidden_branch, "owner tree should expose archived collections under an archive branch")
        self.assertEqual(
            [str(c.get("label") or "") for c in hidden_branch.get("children", [])],
            ["Completed Reviews", "Imported Board Mirrors", "Legacy Folders"],
        )
        self.assertEqual(
            [str(c.get("label") or "") for c in hidden_branch["children"][0].get("children", [])],
            ["Review: Done"],
        )
        self.assertEqual(
            [str(c.get("label") or "") for c in hidden_branch["children"][1].get("children", [])],
            ["pins: kitchen"],
        )
        self.assertEqual(
            [str(c.get("label") or "") for c in hidden_branch["children"][2].get("children", [])],
            ["CB: Hidden"],
        )

    def test_collections_group_counts_only_visible_items(self):
        """Collection counts should match visible items returned by /api/assets."""
        with Db(self.db_path) as db:
            ensure_schema(db)
            db.exec(
                """
                insert into collections (id, name, description, created_at, updated_at, hidden)
                values (?, ?, ?, ?, ?, 0)
                """,
                ("c-visible-check", "Visible Count Check", "", "2026-03-01T00:00:00+00:00", "2026-03-02T00:00:00+00:00"),
            )
            db.exec(
                "insert into collection_items (collection_id, asset_id, position) values (?, ?, ?)",
                ("c-visible-check", "aa000000-1000-4000-a000-000000000000", 1),
            )
            db.exec(
                "insert into collection_items (collection_id, asset_id, position) values (?, ?, ?)",
                ("c-visible-check", "dd000000-1000-4000-a000-000000000000", 2),
            )

        tree = self._get("/api/catalog/tree", headers={"X-Actor-Token": "owner-tree-token"})["tree"]
        collections_node = next((n for n in tree if n.get("type") == "collections_group"), None)
        self.assertIsNotNone(collections_node, "collections group should be present")
        target = next(
            (c for c in collections_node.get("children", []) if str(c.get("collection_id") or "") == "c-visible-check"),
            None,
        )
        self.assertIsNotNone(target, "collection should appear in collections group")
        self.assertEqual(int(target.get("count") or 0), 1)

    def test_collections_group_exposes_collection_provenance(self):
        with Db(self.db_path) as db:
            ensure_schema(db)
            db.exec(
                """
                insert into collections (id, name, description, created_at, updated_at, hidden)
                values (?, ?, ?, ?, ?, 0)
                """,
                (
                    "c-cb",
                    "CB: Kitchen",
                    "Kitchen layouts, cabinets, countertops, appliances.",
                    "2026-03-01T00:00:00+00:00",
                    "2026-03-02T00:00:00+00:00",
                ),
            )
            ensure_schema(db)

        tree = self._get("/api/catalog/tree", headers={"X-Actor-Token": "owner-tree-token"})["tree"]
        collections_node = next((n for n in tree if n.get("type") == "collections_group"), None)
        self.assertIsNotNone(collections_node, "collections group should be present")
        child = next((c for c in collections_node.get("children", []) if c.get("collection_id") == "c-cb"), None)
        self.assertIsNotNone(child, "CB collection should appear in collections group")
        self.assertEqual(child.get("provenance_kind"), "ai_derived_representative")
        self.assertEqual(child.get("provenance_badge"), "AI set")
        self.assertEqual(child.get("provenance_label"), "AI-derived representative")

    def test_scan_source_exposes_subtype_branches(self):
        tree = self._get("/api/catalog/tree")["tree"]
        scan = next((n for n in tree if n.get("type") == "source" and n.get("label", "").lower() == "scan"), None)
        self.assertIsNotNone(scan, "scan source should exist")
        subtype_children = [c for c in scan.get("children", []) if c.get("type") == "source_subtype"]
        by_kind = {str(c.get("content_kind") or ""): c for c in subtype_children}
        self.assertIn("scan", by_kind)
        self.assertIn("photo", by_kind)
        self.assertIn("video", by_kind)
        self.assertGreater(by_kind["scan"].get("count", 0), 0)
        self.assertGreater(by_kind["photo"].get("count", 0), 0)
        self.assertGreater(by_kind["video"].get("count", 0), 0)

    def test_catalog_endpoints_support_multi_file_scope(self):
        """Catalog endpoints should union descendants when multiple files are selected."""
        tree = self._get("/api/catalog/tree")["tree"]
        # Any node type (source or dimension) with ≥2 file children works for this test.
        dim = next(
            (
                n for n in tree
                if len([c for c in n.get("children", []) if c.get("file")]) >= 2
            ),
            None,
        )
        self.assertIsNotNone(dim, "need a node with at least two file children")
        files = [c["file"] for c in dim.get("children", []) if c.get("file")][:2]
        f0 = urllib.parse.quote(files[0])
        f1 = urllib.parse.quote(files[1])

        ids0 = set(self._get(f"/api/catalog/asset-ids?file={f0}").get("ids", []))
        ids1 = set(self._get(f"/api/catalog/asset-ids?file={f1}").get("ids", []))
        ids_combined = set(self._get(f"/api/catalog/asset-ids?file={f0}&file={f1}").get("ids", []))
        self.assertEqual(ids_combined, ids0 | ids1)
        self.assertGreater(len(ids_combined), 0)

        page = self._get(f"/api/catalog/items?file={f0}&file={f1}&limit=1")
        self.assertEqual(len(page.get("assets", [])), 1)


if __name__ == "__main__":
    unittest.main()
