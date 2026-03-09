import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import HTTPServer
from pathlib import Path
from unittest import mock

from inspirations.db import Db, ensure_schema
from inspirations.server import ApiHandler, run_server


class TestServerApi(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.db_path = self.tmp_path / "t.sqlite"
        self.store_dir = self.tmp_path / "store"
        self.app_dir = Path(__file__).resolve().parent.parent / "app"
        self.original = self.store_dir / "originals" / "pinterest" / "a1.jpg"
        self.thumb = self.store_dir / "thumbs" / "pinterest" / "a1.jpg"
        self.original.parent.mkdir(parents=True, exist_ok=True)
        self.thumb.parent.mkdir(parents=True, exist_ok=True)
        self.original.write_bytes(b"img")
        self.thumb.write_bytes(b"th")

        with Db(self.db_path) as db:
            ensure_schema(db)
            db.exec(
                """
                insert into assets (id, source, source_ref, title, imported_at, stored_path, thumb_path, notes)
                values (?, ?, ?, ?, datetime('now'), ?, ?, ?)
                """,
                ("a1", "pinterest", "pin://1", "Asset One", str(self.original), str(self.thumb), "remove me"),
            )
            db.exec(
                "insert into assets (id, source, source_ref, title, imported_at) values (?, ?, ?, ?, datetime('now'))",
                ("a2", "pinterest", "pin://2", "Asset Two"),
            )
            db.exec(
                """
                insert into collections (id, name, description, created_at, updated_at)
                values (?, ?, ?, datetime('now'), datetime('now'))
                """,
                ("c1", "Kitchen", ""),
            )
            db.exec("insert into collection_items (collection_id, asset_id, position) values (?, ?, ?)", ("c1", "a1", 1))
            db.exec("insert into collection_items (collection_id, asset_id, position) values (?, ?, ?)", ("c1", "a2", 2))
            db.exec(
                """
                insert into annotations (id, asset_id, x, y, text, created_at, updated_at)
                values (?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                """,
                ("ann1", "a1", 0.2, 0.3, "test"),
            )

        self.server = HTTPServer(("127.0.0.1", 0), ApiHandler)
        self.server.db_path = self.db_path
        self.server.app_dir = self.app_dir
        self.server.store_dir = self.store_dir
        self.server.imports_dir = self.tmp_path / "imports"
        self.server.admin_tokens = {}
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                status, _ = self._request("/api/assets")
                if status == 200:
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

    def _request(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict | None = None,
        raw_data: bytes | None = None,
        headers: dict | None = None,
        return_headers: bool = False,
    ):
        req_headers = dict(headers or {})
        data = None
        if payload is not None and raw_data is not None:
            raise ValueError("payload and raw_data are mutually exclusive")
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            req_headers.setdefault("Content-Type", "application/json")
        elif raw_data is not None:
            data = raw_data
        req = urllib.request.Request(f"{self.base_url}{path}", method=method, data=data, headers=req_headers)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                raw = resp.read().decode("utf-8")
                body = json.loads(raw) if raw else {}
                if return_headers:
                    return resp.status, body, dict(resp.headers.items())
                return resp.status, body
        except urllib.error.HTTPError as e:
            try:
                raw = e.read().decode("utf-8")
                try:
                    body = json.loads(raw) if raw else {}
                except json.JSONDecodeError:
                    body = {"error": raw}
                if return_headers:
                    return e.code, body, dict((e.headers or {}).items())
                return e.code, body
            finally:
                e.close()

    def _insert_asset(
        self,
        *,
        asset_id: str,
        source: str,
        source_ref: str,
        title: str,
        imported_at: str,
    ) -> None:
        with Db(self.db_path) as db:
            ensure_schema(db)
            db.exec(
                """
                insert into assets (id, source, source_ref, title, imported_at)
                values (?, ?, ?, ?, ?)
                """,
                (asset_id, source, source_ref, title, imported_at),
            )

    def _labels_for_asset(self, asset_id: str) -> list[str]:
        with Db(self.db_path) as db:
            ensure_schema(db)
            rows = db.query(
                "select label from asset_labels where asset_id=? order by label",
                (asset_id,),
            )
        return [str(r["label"]) for r in rows]

    def _seed_v2_classification(self) -> None:
        with Db(self.db_path) as db:
            ensure_schema(db)
            db.exec(
                """
                insert into classification_runs
                  (id, schema_version, run_type, model_provider, model_name, prompt_version, config_json, created_at, notes)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "track-run-test",
                    "curation_v2",
                    "track_gate",
                    "heuristic",
                    "test",
                    "",
                    "{}",
                    "2026-03-07T06:00:00+00:00",
                    "test seed",
                ),
            )
            db.exec(
                """
                insert into classification_runs
                  (id, schema_version, run_type, model_provider, model_name, prompt_version, config_json, created_at, notes)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "axis-run-test",
                    "curation_v2",
                    "multi_axis_inference",
                    "heuristic",
                    "test",
                    "",
                    "{}",
                    "2026-03-07T06:01:00+00:00",
                    "test seed",
                ),
            )
            db.exec(
                """
                insert into asset_track_assessments
                  (id, run_id, asset_id, track, confidence, is_ambiguous, decision_source, reason, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "track-a1",
                    "track-run-test",
                    "a1",
                    "style_product_decor",
                    0.96,
                    0,
                    "test",
                    "seed style",
                    "2026-03-07T06:00:01+00:00",
                ),
            )
            db.exec(
                """
                insert into asset_track_assessments
                  (id, run_id, asset_id, track, confidence, is_ambiguous, decision_source, reason, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "track-a2",
                    "track-run-test",
                    "a2",
                    "construction_concern",
                    0.91,
                    0,
                    "test",
                    "seed construction",
                    "2026-03-07T06:00:02+00:00",
                ),
            )
            memberships = [
                ("axis-a1-track", "a1", "style_product_decor", "track", "style_product_decor", 0.96, 1, 1),
                ("axis-a1-space", "a1", "style_product_decor", "space_context", "interior_room", 0.92, 1, 1),
                ("axis-a1-subject", "a1", "style_product_decor", "subject_type", "full_space_scene", 0.9, 1, 1),
                ("axis-a1-room", "a1", "style_product_decor", "room", "kitchen", 0.94, 1, 1),
                ("axis-a1-product", "a1", "style_product_decor", "product_focus", "sink", 0.85, 1, 1),
                ("axis-a2-track", "a2", "construction_concern", "track", "construction_concern", 0.91, 1, 1),
                ("axis-a2-space", "a2", "construction_concern", "space_context", "non_spatial", 0.7, 1, 1),
                ("axis-a2-subject", "a2", "construction_concern", "subject_type", "architectural_detail", 0.74, 1, 1),
                ("axis-a2-concern", "a2", "construction_concern", "concern_domain", "envelope", 0.89, 1, 1),
                ("axis-a2-system", "a2", "construction_concern", "product_system_focus", "window_system", 0.82, 1, 1),
            ]
            for row_id, asset_id, track, axis_name, axis_value, confidence, rank, is_primary in memberships:
                db.exec(
                    """
                    insert into asset_axis_memberships
                      (id, run_id, asset_id, track, axis_name, axis_value, confidence, rank, is_primary, is_ambiguous, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row_id,
                        "axis-run-test",
                        asset_id,
                        track,
                        axis_name,
                        axis_value,
                        confidence,
                        rank,
                        is_primary,
                        0,
                        "2026-03-07T06:01:01+00:00",
                    ),
                )

    def test_remove_items_from_collection_endpoint(self):
        status, body = self._request(
            "/api/collections/c1/items/remove",
            method="POST",
            payload={"asset_ids": ["a2"]},
        )
        self.assertEqual(status, 200)
        self.assertEqual(body.get("removed"), 1)

        status, body = self._request("/api/collections/c1/items")
        self.assertEqual(status, 200)
        self.assertEqual([item["id"] for item in body["items"]], ["a1"])

    def test_admin_delete_requires_token(self):
        status, body = self._request(
            "/api/admin/assets/delete",
            method="POST",
            payload={"admin_mode": True, "confirm": "DELETE", "asset_ids": ["a1"]},
        )
        self.assertEqual(status, 403)
        self.assertEqual(body.get("error"), "missing admin token")

    def test_admin_delete_cleans_db_and_files(self):
        with mock.patch.dict(os.environ, {"INSPIRATIONS_ADMIN_PASSWORD": "secret"}, clear=False):
            status, body = self._request("/api/admin/login", method="POST", payload={"password": "secret"})
            self.assertEqual(status, 200)
            token = body.get("token")
            self.assertTrue(token)

            status, body = self._request(
                "/api/admin/assets/delete",
                method="POST",
                payload={"admin_mode": True, "confirm": "DELETE", "asset_ids": ["a1"]},
                headers={"X-Admin-Token": token},
            )
            self.assertEqual(status, 200)
            self.assertEqual(body.get("deleted"), 1)
            self.assertEqual(body.get("files_deleted"), 2)
            self.assertTrue(Path(body.get("backup_path", "")).exists())

        self.assertFalse(self.original.exists())
        self.assertFalse(self.thumb.exists())

        status, body = self._request("/api/assets")
        self.assertEqual(status, 200)
        self.assertEqual([a["id"] for a in body["assets"]], ["a2"])

        with Db(self.db_path) as db:
            remaining_collection_rows = db.query_value("select count(*) from collection_items where asset_id='a1'")
            remaining_annotations = db.query_value("select count(*) from annotations where asset_id='a1'")
        self.assertEqual(remaining_collection_rows, 0)
        self.assertEqual(remaining_annotations, 0)

    def test_semantic_search_requires_api_key(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": ""}, clear=False), \
             mock.patch("inspirations.server._keychain_get", return_value=""):
            status, body = self._request("/api/search/similar?q=oak")
        self.assertEqual(status, 503)
        self.assertIn("GEMINI_API_KEY", body.get("error", ""))

    def test_semantic_search_endpoint(self):
        fake_report = {
            "query": "oak kitchen",
            "provider": "gemini",
            "model": "gemini-embedding-001",
            "semantic_weight": 0.7,
            "lexical_weight": 0.3,
            "min_score": 0.25,
            "compared_assets": 1,
            "skipped_dimension_mismatch": 0,
            "results": [
                {
                    "id": "a1",
                    "source": "pinterest",
                    "title": "Asset One",
                    "score": 0.93,
                }
            ],
        }
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "fake"}, clear=False):
            with mock.patch("inspirations.server.run_similarity_search", return_value=fake_report) as mocked:
                status, body = self._request(
                    "/api/search/similar?q=oak%20kitchen&source=pinterest&limit=10&semantic_weight=0.7&lexical_weight=0.3&min_score=0.25"
                )
        self.assertEqual(status, 200)
        self.assertEqual(body.get("results", [])[0].get("id"), "a1")
        mocked.assert_called_once()
        self.assertEqual(mocked.call_args.kwargs["semantic_weight"], 0.7)
        self.assertEqual(mocked.call_args.kwargs["lexical_weight"], 0.3)
        self.assertEqual(mocked.call_args.kwargs["min_score"], 0.25)

    def test_semantic_search_rejects_non_numeric_weights(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "fake"}, clear=False):
            status, body = self._request("/api/search/similar?q=oak&semantic_weight=fast")
        self.assertEqual(status, 400)
        self.assertEqual(body.get("error"), "semantic_weight must be number")

    def test_explorer_attractor_data_include_hidden_requires_owner(self):
        with Db(self.db_path) as db:
            ensure_schema(db)
            db.exec("update assets set triage_status='hidden' where id='a2'")
            db.exec(
                "insert into actors (id, name, token, role, created_at) values (?, ?, ?, ?, datetime('now'))",
                ("owner-1", "Owner", "owner-token-1", "owner"),
            )
            db.exec(
                "insert into actors (id, name, token, role, created_at) values (?, ?, ?, ?, datetime('now'))",
                ("collab-1", "Collab", "collab-token-1", "collaborator"),
            )

        status, body = self._request("/api/explorer/attractor-data?dims=2&include_hidden=1")
        self.assertEqual(status, 200)
        ids_public = {a["id"] for a in body.get("assets", [])}
        self.assertEqual(ids_public, {"a1"})

        status, body = self._request(
            "/api/explorer/attractor-data?dims=2&include_hidden=1",
            headers={"X-Actor-Token": "collab-token-1"},
        )
        self.assertEqual(status, 200)
        ids_collab = {a["id"] for a in body.get("assets", [])}
        self.assertEqual(ids_collab, {"a1"})

        status, body = self._request(
            "/api/explorer/attractor-data?dims=2&include_hidden=1",
            headers={"X-Actor-Token": "owner-token-1"},
        )
        self.assertEqual(status, 200)
        ids_owner = {a["id"] for a in body.get("assets", [])}
        self.assertEqual(ids_owner, {"a1", "a2"})

    def test_assets_endpoint_filters_by_classification_axis(self):
        self._seed_v2_classification()

        status, body = self._request("/api/assets?classification_axis=room&classification_value=kitchen&include_hidden=1")
        self.assertEqual(status, 200)
        self.assertEqual([a["id"] for a in body.get("assets", [])], ["a1"])
        self.assertEqual(body.get("total"), 1)

    def test_catalog_tree_includes_classification_sections(self):
        self._seed_v2_classification()
        catalog_dir = self.tmp_path / "catalog"
        catalog_dir.mkdir(parents=True, exist_ok=True)
        (catalog_dir / "_index.md").write_text("", encoding="utf-8")
        self.server.catalog_dir = catalog_dir

        status, body = self._request("/api/catalog/tree")
        self.assertEqual(status, 200)
        tree = body.get("tree", [])
        classification_nodes = {node.get("label"): node for node in tree if node.get("type") == "classification"}
        self.assertIn("Track", classification_nodes)
        self.assertIn("Rooms", classification_nodes)
        self.assertIn("Construction Concerns", classification_nodes)
        self.assertIn("Style / Decor", [child.get("label") for child in classification_nodes["Track"].get("children", [])])
        self.assertIn("Kitchen", [child.get("label") for child in classification_nodes["Rooms"].get("children", [])])

    def test_catalog_tree_track_counts_include_non_home_irrelevant_items(self):
        self._seed_v2_classification()
        catalog_dir = self.tmp_path / "catalog-track"
        catalog_dir.mkdir(parents=True, exist_ok=True)
        (catalog_dir / "_index.md").write_text("", encoding="utf-8")
        self.server.catalog_dir = catalog_dir

        with Db(self.db_path) as db:
            ensure_schema(db)
            db.exec(
                """
                insert into assets (id, source, source_ref, title, imported_at, category)
                values (?, ?, ?, ?, datetime('now'), ?)
                """,
                ("a3", "facebook", "fb://offtopic", "Off-topic item", "other"),
            )
            db.exec(
                """
                insert into asset_track_assessments
                  (id, run_id, asset_id, track, confidence, is_ambiguous, decision_source, reason, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "track-a3",
                    "track-run-test",
                    "a3",
                    "irrelevant",
                    0.93,
                    0,
                    "test",
                    "seed irrelevant",
                    "2026-03-07T06:00:03+00:00",
                ),
            )

        status, body = self._request("/api/catalog/tree")
        self.assertEqual(status, 200)
        tree = body.get("tree", [])
        track_node = next((node for node in tree if node.get("type") == "classification" and node.get("axis_name") == "track"), None)
        self.assertIsNotNone(track_node)
        by_label = {child.get("label"): int(child.get("count") or 0) for child in track_node.get("children", [])}
        self.assertEqual(by_label.get("Irrelevant"), 1)

    def test_explorer_attractor_data_uses_v2_classification_groups(self):
        self._seed_v2_classification()
        with Db(self.db_path) as db:
            ensure_schema(db)
            for asset_id, title, track_id_base, axis_id_base in [
                ("a3", "Asset Three", "track-a3", "axis-a3"),
                ("a4", "Asset Four", "track-a4", "axis-a4"),
            ]:
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, imported_at)
                    values (?, ?, ?, ?, datetime('now'))
                    """,
                    (asset_id, "pinterest", f"pin://{asset_id}", title),
                )
                db.exec(
                    """
                    insert into asset_track_assessments
                      (id, run_id, asset_id, track, confidence, is_ambiguous, decision_source, reason, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        track_id_base,
                        "track-run-test",
                        asset_id,
                        "style_product_decor",
                        0.95,
                        0,
                        "test",
                        "seed style",
                        "2026-03-07T06:00:03+00:00",
                    ),
                )
                for suffix, axis_name, axis_value, confidence in [
                    ("track", "track", "style_product_decor", 0.95),
                    ("space", "space_context", "interior_room", 0.92),
                    ("subject", "subject_type", "full_space_scene", 0.9),
                    ("room", "room", "kitchen", 0.94),
                    ("product", "product_focus", "sink", 0.85),
                ]:
                    db.exec(
                        """
                        insert into asset_axis_memberships
                          (id, run_id, asset_id, track, axis_name, axis_value, confidence, rank, is_primary, is_ambiguous, created_at)
                        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            f"{axis_id_base}-{suffix}",
                            "axis-run-test",
                            asset_id,
                            "style_product_decor",
                            axis_name,
                            axis_value,
                            confidence,
                            1,
                            1,
                            0,
                            "2026-03-07T06:01:02+00:00",
                        ),
                    )

        status, body = self._request("/api/explorer/attractor-data?dims=2")
        self.assertEqual(status, 200)
        categories = body.get("categories", {})
        attractors = body.get("attractors", {})
        self.assertIn("track", categories)
        self.assertIn("room", categories)
        self.assertIn("product_focus", categories)
        self.assertNotIn("rooms", attractors)
        self.assertIn("track", attractors)
        self.assertIn("room", attractors)
        self.assertIn("Kitchen", [opt.get("name") for opt in attractors.get("room", [])])

    def test_explorer_layout_include_hidden_requires_owner(self):
        with Db(self.db_path) as db:
            ensure_schema(db)
            db.exec("update assets set triage_status='hidden' where id='a2'")
            db.exec(
                """
                insert into asset_embeddings
                  (id, asset_id, provider, model, input_text, vector_json, dimensions, created_at)
                values (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                ("emb-a1", "a1", "gemini", "gemini-embedding-001", "a1", "[0.1,0.2,0.3]", 3),
            )
            db.exec(
                """
                insert into asset_embeddings
                  (id, asset_id, provider, model, input_text, vector_json, dimensions, created_at)
                values (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                ("emb-a2", "a2", "gemini", "gemini-embedding-001", "a2", "[0.2,0.3,0.4]", 3),
            )
            db.exec(
                "insert into actors (id, name, token, role, created_at) values (?, ?, ?, ?, datetime('now'))",
                ("owner-2", "Owner", "owner-token-2", "owner"),
            )
            db.exec(
                "insert into actors (id, name, token, role, created_at) values (?, ?, ?, ?, datetime('now'))",
                ("collab-2", "Collab", "collab-token-2", "collaborator"),
            )

        status, body = self._request("/api/explorer/layout?method=pca&refresh=1&include_hidden=1")
        self.assertEqual(status, 200)
        ids_public = {n["id"] for n in body.get("nodes", [])}
        self.assertEqual(ids_public, {"a1"})

        status, body = self._request(
            "/api/explorer/layout?method=pca&refresh=1&include_hidden=1",
            headers={"X-Actor-Token": "collab-token-2"},
        )
        self.assertEqual(status, 200)
        ids_collab = {n["id"] for n in body.get("nodes", [])}
        self.assertEqual(ids_collab, {"a1"})

        status, body = self._request(
            "/api/explorer/layout?method=pca&refresh=1&include_hidden=1",
            headers={"X-Actor-Token": "owner-token-2"},
        )
        self.assertEqual(status, 200)
        ids_owner = {n["id"] for n in body.get("nodes", [])}
        self.assertEqual(ids_owner, {"a1", "a2"})

    def test_asset_detail_endpoint_returns_exact_asset(self):
        status, body = self._request("/api/assets/a1")
        self.assertEqual(status, 200)
        asset = body.get("asset") or {}
        self.assertEqual(asset.get("id"), "a1")
        self.assertEqual(asset.get("title"), "Asset One")
        self.assertEqual(asset.get("notes"), "remove me")
        self.assertTrue(asset.get("thumb_path"))
        self.assertEqual((asset.get("title_info") or {}).get("working_title"), "Asset One")
        self.assertEqual(asset.get("display_title"), "Asset One")

    def test_asset_detail_exposes_best_original_title_when_title_audit_changed_current_title(self):
        with Db(self.db_path) as db:
            ensure_schema(db)
            db.exec(
                """
                insert into assets (id, source, source_ref, title, imported_at)
                values (?, ?, ?, ?, datetime('now'))
                """,
                ("fb-audit", "facebook", "https://example.com/original-post", "Edited title"),
            )
            db.exec(
                """
                insert into title_audit_batches
                  (id, actor, created_at, status)
                values (?, ?, datetime('now'), 'applied')
                """,
                ("batch-1", "Jim"),
            )
            db.exec(
                """
                insert into title_audit_applied
                  (batch_id, asset_id, old_title, new_title, applied_at)
                values (?, ?, ?, ?, datetime('now'))
                """,
                ("batch-1", "fb-audit", "Original imported title", "Edited title"),
            )

        status, body = self._request("/api/assets/fb-audit")
        self.assertEqual(status, 200)
        asset = body.get("asset") or {}
        title_info = asset.get("title_info") or {}
        self.assertEqual(title_info.get("best_original_title"), "Original imported title")
        self.assertEqual(title_info.get("best_original_origin_type"), "title_audit_old")

    def test_asset_detail_include_hidden_requires_owner(self):
        with Db(self.db_path) as db:
            ensure_schema(db)
            db.exec("update assets set triage_status='hidden' where id='a2'")
            db.exec(
                "insert into actors (id, name, token, role, created_at) values (?, ?, ?, ?, datetime('now'))",
                ("owner-asset", "Owner", "owner-asset-token", "owner"),
            )
            db.exec(
                "insert into actors (id, name, token, role, created_at) values (?, ?, ?, ?, datetime('now'))",
                ("collab-asset", "Collab", "collab-asset-token", "collaborator"),
            )

        status, _ = self._request("/api/assets/a2?include_hidden=1")
        self.assertEqual(status, 404)

        status, _ = self._request(
            "/api/assets/a2?include_hidden=1",
            headers={"X-Actor-Token": "collab-asset-token"},
        )
        self.assertEqual(status, 404)

        status, body = self._request(
            "/api/assets/a2?include_hidden=1",
            headers={"X-Actor-Token": "owner-asset-token"},
        )
        self.assertEqual(status, 200)
        self.assertEqual((body.get("asset") or {}).get("id"), "a2")

    def test_assets_and_asset_ids_include_hidden_require_owner(self):
        with Db(self.db_path) as db:
            ensure_schema(db)
            db.exec("update assets set triage_status='hidden' where id='a2'")
            db.exec(
                "insert into actors (id, name, token, role, created_at) values (?, ?, ?, ?, datetime('now'))",
                ("owner-list", "Owner", "owner-list-token", "owner"),
            )
            db.exec(
                "insert into actors (id, name, token, role, created_at) values (?, ?, ?, ?, datetime('now'))",
                ("collab-list", "Collab", "collab-list-token", "collaborator"),
            )

        status, body = self._request("/api/assets?include_hidden=1")
        self.assertEqual(status, 200)
        self.assertEqual({a["id"] for a in body.get("assets", [])}, {"a1"})

        status, body = self._request(
            "/api/assets?include_hidden=1",
            headers={"X-Actor-Token": "collab-list-token"},
        )
        self.assertEqual(status, 200)
        self.assertEqual({a["id"] for a in body.get("assets", [])}, {"a1"})

        status, body = self._request(
            "/api/assets?include_hidden=1",
            headers={"X-Actor-Token": "owner-list-token"},
        )
        self.assertEqual(status, 200)
        self.assertEqual({a["id"] for a in body.get("assets", [])}, {"a1", "a2"})

        status, body = self._request("/api/asset-ids?include_hidden=1")
        self.assertEqual(status, 200)
        self.assertEqual(set(body.get("ids", [])), {"a1"})

        status, body = self._request(
            "/api/asset-ids?include_hidden=1",
            headers={"X-Actor-Token": "collab-list-token"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(set(body.get("ids", [])), {"a1"})

        status, body = self._request(
            "/api/asset-ids?include_hidden=1",
            headers={"X-Actor-Token": "owner-list-token"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(set(body.get("ids", [])), {"a1", "a2"})

    def test_collections_include_hidden_requires_owner(self):
        with Db(self.db_path) as db:
            ensure_schema(db)
            db.exec(
                "insert into collections (id, name, description, created_at, updated_at) values (?, ?, ?, datetime('now'), datetime('now'))",
                ("c2", "Bathroom", ""),
            )
            db.exec("update collections set hidden=1, hidden_at=datetime('now') where id='c1'")
            db.exec(
                "insert into actors (id, name, token, role, created_at) values (?, ?, ?, ?, datetime('now'))",
                ("owner-cols", "Owner", "owner-cols-token", "owner"),
            )
            db.exec(
                "insert into actors (id, name, token, role, created_at) values (?, ?, ?, ?, datetime('now'))",
                ("collab-cols", "Collab", "collab-cols-token", "collaborator"),
            )

        status, body = self._request("/api/collections?include_hidden=1")
        self.assertEqual(status, 200)
        self.assertEqual({c["id"] for c in body.get("collections", [])}, {"c2"})

        status, body = self._request(
            "/api/collections?include_hidden=1",
            headers={"X-Actor-Token": "collab-cols-token"},
        )
        self.assertEqual(status, 200)
        self.assertEqual({c["id"] for c in body.get("collections", [])}, {"c2"})

        status, body = self._request(
            "/api/collections?include_hidden=1",
            headers={"X-Actor-Token": "owner-cols-token"},
        )
        self.assertEqual(status, 200)
        hidden_map = {c["id"]: int(c.get("hidden") or 0) for c in body.get("collections", [])}
        self.assertEqual(set(hidden_map.keys()), {"c1", "c2"})
        self.assertEqual(hidden_map["c1"], 1)
        self.assertEqual(hidden_map["c2"], 0)

    def test_collection_bulk_hide_restore_and_delete_require_owner(self):
        with Db(self.db_path) as db:
            ensure_schema(db)
            db.exec(
                "insert into collections (id, name, description, created_at, updated_at) values (?, ?, ?, datetime('now'), datetime('now'))",
                ("c2", "Bathroom", ""),
            )
            db.exec(
                "insert into actors (id, name, token, role, created_at) values (?, ?, ?, ?, datetime('now'))",
                ("owner-bulk-cols", "Owner", "owner-bulk-cols-token", "owner"),
            )
            db.exec(
                "insert into actors (id, name, token, role, created_at) values (?, ?, ?, ?, datetime('now'))",
                ("collab-bulk-cols", "Collab", "collab-bulk-cols-token", "collaborator"),
            )

        status, body = self._request(
            "/api/collections/bulk-hide",
            method="POST",
            payload={"collection_ids": ["c2"], "hidden": True},
            headers={"X-Actor-Token": "collab-bulk-cols-token"},
        )
        self.assertEqual(status, 403)
        self.assertEqual(body.get("error"), "owner access required")

        status, body = self._request(
            "/api/collections/bulk-hide",
            method="POST",
            payload={"collection_ids": ["c2"], "hidden": True},
            headers={"X-Actor-Token": "owner-bulk-cols-token"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(body.get("updated"), 1)
        self.assertEqual(body.get("hidden"), 1)

        with Db(self.db_path) as db:
            hidden_value = db.query_value("select coalesce(hidden, 0) from collections where id='c2'")
        self.assertEqual(int(hidden_value or 0), 1)

        status, body = self._request(
            "/api/collections/bulk-hide",
            method="POST",
            payload={"collection_ids": ["c2"], "hidden": False},
            headers={"X-Actor-Token": "owner-bulk-cols-token"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(body.get("updated"), 1)
        self.assertEqual(body.get("hidden"), 0)

        with Db(self.db_path) as db:
            hidden_value = db.query_value("select coalesce(hidden, 0) from collections where id='c2'")
        self.assertEqual(int(hidden_value or 0), 0)

        status, body = self._request(
            "/api/collections/bulk-hide",
            method="POST",
            payload={"collection_ids": ["c2"], "hidden": True},
            headers={"X-Actor-Token": "owner-bulk-cols-token"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(body.get("updated"), 1)

        status, body = self._request(
            "/api/collections/bulk-delete",
            method="POST",
            payload={"collection_ids": ["c2", "c1"]},
            headers={"X-Actor-Token": "owner-bulk-cols-token"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(body.get("deleted"), 1)
        self.assertEqual(body.get("skipped"), 1)

        with Db(self.db_path) as db:
            exists_c2 = db.query_value("select count(*) from collections where id='c2'")
            exists_c1 = db.query_value("select count(*) from collections where id='c1'")
        self.assertEqual(int(exists_c2 or 0), 0)
        self.assertEqual(int(exists_c1 or 0), 1)

    def test_collections_count_reflects_visible_items(self):
        with Db(self.db_path) as db:
            ensure_schema(db)
            db.exec("update assets set triage_status='hidden' where id='a2'")
            db.exec(
                "insert into collections (id, name, description, created_at, updated_at) values (?, ?, ?, datetime('now'), datetime('now'))",
                ("hidden-col", "Hidden", "",),
            )
            db.exec(
                "insert into collection_items (collection_id, asset_id, position) values (?, ?, ?)",
                ("hidden-col", "a1", 1),
            )

        status, body = self._request("/api/collections")
        self.assertEqual(status, 200)
        c1 = next((c for c in body.get("collections", []) if c.get("id") == "c1"), None)
        self.assertIsNotNone(c1)
        self.assertEqual(int(c1.get("count") or 0), 0)
        self.assertEqual(int(c1.get("count_visible") or 0), 0)
        self.assertEqual(int(c1.get("count_total") or 0), 2)

    def test_catalog_endpoints_include_hidden_require_owner(self):
        visible_id = "feedface-0000-0000-0000-000000000000"
        hidden_id = "deadbeef-0000-0000-0000-000000000000"
        with Db(self.db_path) as db:
            ensure_schema(db)
            db.exec(
                """
                insert into assets (id, source, source_ref, title, imported_at)
                values (?, ?, ?, ?, datetime('now'))
                """,
                (visible_id, "pinterest", "pin://visible", "Visible Catalog Asset"),
            )
            db.exec(
                """
                insert into assets (id, source, source_ref, title, imported_at, triage_status)
                values (?, ?, ?, ?, datetime('now'), 'hidden')
                """,
                (hidden_id, "pinterest", "pin://hidden", "Hidden Catalog Asset"),
            )
            db.exec(
                "insert into actors (id, name, token, role, created_at) values (?, ?, ?, ?, datetime('now'))",
                ("owner-cat", "Owner", "owner-cat-token", "owner"),
            )
            db.exec(
                "insert into actors (id, name, token, role, created_at) values (?, ?, ?, ?, datetime('now'))",
                ("collab-cat", "Collab", "collab-cat-token", "collaborator"),
            )

        catalog_dir = self.tmp_path / "catalog"
        room_dir = catalog_dir / "room"
        room_dir.mkdir(parents=True, exist_ok=True)
        rel_file = "room/test.md"
        (catalog_dir / rel_file).write_text(
            "- feedface | visible\n- deadbeef | hidden\n",
            encoding="utf-8",
        )
        self.server.catalog_dir = catalog_dir
        rel_q = urllib.parse.quote(rel_file, safe="/")

        status, body = self._request(f"/api/catalog/items?file={rel_q}&limit=100")
        self.assertEqual(status, 200)
        self.assertEqual({a["id"] for a in body.get("assets", [])}, {visible_id})

        status, body = self._request(
            f"/api/catalog/items?file={rel_q}&limit=100&include_hidden=1",
            headers={"X-Actor-Token": "collab-cat-token"},
        )
        self.assertEqual(status, 200)
        self.assertEqual({a["id"] for a in body.get("assets", [])}, {visible_id})

        status, body = self._request(
            f"/api/catalog/items?file={rel_q}&limit=100&include_hidden=1",
            headers={"X-Actor-Token": "owner-cat-token"},
        )
        self.assertEqual(status, 200)
        self.assertEqual({a["id"] for a in body.get("assets", [])}, {visible_id, hidden_id})

        status, body = self._request(f"/api/catalog/asset-ids?file={rel_q}")
        self.assertEqual(status, 200)
        self.assertEqual(set(body.get("ids", [])), {visible_id})

        status, body = self._request(
            f"/api/catalog/asset-ids?file={rel_q}&include_hidden=1",
            headers={"X-Actor-Token": "collab-cat-token"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(set(body.get("ids", [])), {visible_id})

        status, body = self._request(
            f"/api/catalog/asset-ids?file={rel_q}&include_hidden=1",
            headers={"X-Actor-Token": "owner-cat-token"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(set(body.get("ids", [])), {visible_id, hidden_id})

    def test_collaborator_default_browse_scope_excludes_non_home_category(self):
        with Db(self.db_path) as db:
            ensure_schema(db)
            db.exec("update assets set category='other' where id='a2'")
            db.exec(
                "insert into actors (id, name, token, role, created_at) values (?, ?, ?, ?, datetime('now'))",
                ("owner-scope-1", "Owner", "owner-scope-token-1", "owner"),
            )
            db.exec(
                "insert into actors (id, name, token, role, created_at) values (?, ?, ?, ?, datetime('now'))",
                ("collab-scope-1", "Collab", "collab-scope-token-1", "collaborator"),
            )

        status, body = self._request(
            "/api/assets?limit=20",
            headers={"X-Actor-Token": "collab-scope-token-1"},
        )
        self.assertEqual(status, 200)
        self.assertEqual({a["id"] for a in body.get("assets", [])}, {"a1"})

        status, body = self._request(
            "/api/asset-ids",
            headers={"X-Actor-Token": "collab-scope-token-1"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(set(body.get("ids", [])), {"a1"})

        status, body = self._request(
            "/api/assets?collection_id=c1&limit=20",
            headers={"X-Actor-Token": "collab-scope-token-1"},
        )
        self.assertEqual(status, 200)
        self.assertEqual({a["id"] for a in body.get("assets", [])}, {"a1", "a2"})

    def test_collaborator_catalog_tree_hides_other_dimension(self):
        with Db(self.db_path) as db:
            ensure_schema(db)
            db.exec(
                "insert into actors (id, name, token, role, created_at) values (?, ?, ?, ?, datetime('now'))",
                ("owner-tree-1", "Owner", "owner-tree-token-1", "owner"),
            )
            db.exec(
                "insert into actors (id, name, token, role, created_at) values (?, ?, ?, ?, datetime('now'))",
                ("collab-tree-1", "Collab", "collab-tree-token-1", "collaborator"),
            )

        catalog_dir = self.tmp_path / "catalog-tree"
        catalog_dir.mkdir(parents=True, exist_ok=True)
        (catalog_dir / "room").mkdir(parents=True, exist_ok=True)
        (catalog_dir / "other").mkdir(parents=True, exist_ok=True)
        (catalog_dir / "_index.md").write_text(
            "\n".join(
                [
                    "# Inspirations Catalog",
                    "",
                    "## By Room (1 item-assignments)",
                    "",
                    "| File | Category | Items | Topics |",
                    "|------|----------|-------|--------|",
                    "| room/kitchen.md | kitchen | 1 | kitchen |",
                    "",
                    "## Other / Non-Home-Design (1 items)",
                    "",
                    "| File | Category | Items | Topics |",
                    "|------|----------|-------|--------|",
                    "| other/exercise.md | exercise | 1 | exercise |",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        self.server.catalog_dir = catalog_dir

        status, body = self._request(
            "/api/catalog/tree",
            headers={"X-Actor-Token": "owner-tree-token-1"},
        )
        self.assertEqual(status, 200)
        owner_ids = {str(n.get("id") or "") for n in body.get("tree", [])}
        self.assertIn("dimension:other", owner_ids)

        status, body = self._request(
            "/api/catalog/tree",
            headers={"X-Actor-Token": "collab-tree-token-1"},
        )
        self.assertEqual(status, 200)
        collab_ids = {str(n.get("id") or "") for n in body.get("tree", [])}
        self.assertNotIn("dimension:other", collab_ids)

    def test_collaborator_catalog_endpoints_hide_other_files(self):
        other_id = "bead0001-0000-0000-0000-000000000000"
        with Db(self.db_path) as db:
            ensure_schema(db)
            db.exec(
                """
                insert into assets (id, source, source_ref, title, imported_at, category)
                values (?, ?, ?, ?, datetime('now'), ?)
                """,
                (other_id, "pinterest", "pin://other", "Other Asset", "other"),
            )
            db.exec(
                "insert into actors (id, name, token, role, created_at) values (?, ?, ?, ?, datetime('now'))",
                ("owner-other-1", "Owner", "owner-other-token-1", "owner"),
            )
            db.exec(
                "insert into actors (id, name, token, role, created_at) values (?, ?, ?, ?, datetime('now'))",
                ("collab-other-1", "Collab", "collab-other-token-1", "collaborator"),
            )

        catalog_dir = self.tmp_path / "catalog-other"
        other_dir = catalog_dir / "other"
        other_dir.mkdir(parents=True, exist_ok=True)
        rel_file = "other/exercise.md"
        (catalog_dir / "_index.md").write_text(
            "\n".join(
                [
                    "# Inspirations Catalog",
                    "",
                    "## Other / Non-Home-Design (1 items)",
                    "",
                    "| File | Category | Items | Topics |",
                    "|------|----------|-------|--------|",
                    "| other/exercise.md | exercise | 1 | exercise |",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        (catalog_dir / rel_file).write_text(
            "- bead0001 | other\n",
            encoding="utf-8",
        )
        self.server.catalog_dir = catalog_dir
        rel_q = urllib.parse.quote(rel_file, safe="/")

        status, body = self._request(
            f"/api/catalog/items?file={rel_q}&limit=100",
            headers={"X-Actor-Token": "owner-other-token-1"},
        )
        self.assertEqual(status, 200)
        self.assertEqual({a["id"] for a in body.get("assets", [])}, {other_id})

        status, body = self._request(
            f"/api/catalog/items?file={rel_q}&limit=100",
            headers={"X-Actor-Token": "collab-other-token-1"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(body.get("assets", []), [])

        status, body = self._request(
            f"/api/catalog/asset-ids?file={rel_q}",
            headers={"X-Actor-Token": "owner-other-token-1"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(set(body.get("ids", [])), {other_id})

        status, body = self._request(
            f"/api/catalog/asset-ids?file={rel_q}",
            headers={"X-Actor-Token": "collab-other-token-1"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(body.get("ids", []), [])

    def test_assets_endpoint_supports_media_status_filter(self):
        status, body = self._request("/api/assets?media_status=metadata_only")
        self.assertEqual(status, 200)
        self.assertEqual([a["id"] for a in body["assets"]], ["a2"])

    def test_assets_endpoint_ids_accepts_exact_full_ids(self):
        full_id = "11111111-2222-3333-4444-555555555555"
        with Db(self.db_path) as db:
            ensure_schema(db)
            db.exec(
                """
                insert into assets (id, source, source_ref, title, imported_at)
                values (?, ?, ?, ?, datetime('now'))
                """,
                (full_id, "facebook", "facebook://saved/full", "Full ID Asset"),
            )

        status, body = self._request(f"/api/assets?ids={full_id}&include_hidden=1")
        self.assertEqual(status, 200)
        ids = [a["id"] for a in body.get("assets", [])]
        self.assertEqual(ids, [full_id])

    def test_explorer_attractor_title_fallback_for_saved_link_posts(self):
        with Db(self.db_path) as db:
            ensure_schema(db)
            db.exec(
                """
                insert into assets (id, source, source_ref, title, imported_at)
                values (?, ?, ?, ?, datetime('now'))
                """,
                (
                    "fb-generic-1",
                    "facebook",
                    "https://example.com/alpha-beta-guide",
                    "Leslie Brannigan saved a link from Wisebird's post.",
                ),
            )

        status, body = self._request("/api/explorer/attractor-data?dims=2")
        self.assertEqual(status, 200)
        titles = {a["id"]: (a.get("title") or "") for a in body.get("assets", [])}
        title = titles.get("fb-generic-1", "")
        self.assertTrue(title)
        self.assertNotIn("saved a link from", title.lower())
        self.assertIn("Alpha Beta Guide", title)

    def test_assets_endpoint_exposes_display_title_without_overwriting_raw_generic_saved_link_title(self):
        with Db(self.db_path) as db:
            ensure_schema(db)
            db.exec(
                """
                insert into assets (id, source, source_ref, title, imported_at)
                values (?, ?, ?, ?, datetime('now'))
                """,
                (
                    "fb-generic-2",
                    "facebook",
                    "https://example.com/alpha-beta-guide",
                    "Leslie Brannigan saved a link from Wisebird's post.",
                ),
            )

        status, body = self._request("/api/assets?source=facebook&include_hidden=1")
        self.assertEqual(status, 200)
        assets = {a["id"]: a for a in body.get("assets", [])}
        asset = assets.get("fb-generic-2") or {}
        self.assertEqual(asset.get("title"), "Leslie Brannigan saved a link from Wisebird's post.")
        self.assertEqual(asset.get("display_title"), "Wisebird: Alpha Beta Guide")
        self.assertEqual(((asset.get("title_info") or {}).get("display_source") or ""), "suggested_title")

    def test_owner_can_apply_suggested_working_title(self):
        with Db(self.db_path) as db:
            ensure_schema(db)
            db.exec(
                """
                insert into actors (id, name, token, role, created_at)
                values (?, ?, ?, ?, datetime('now'))
                """,
                ("owner-title", "Owner", "owner-title-token", "owner"),
            )
            db.exec(
                """
                insert into assets (id, source, source_ref, title, imported_at)
                values (?, ?, ?, ?, datetime('now'))
                """,
                (
                    "fb-title-1",
                    "facebook",
                    "https://example.com/alpha-beta-guide",
                    "Leslie Brannigan saved a link from Wisebird's post.",
                ),
            )

        status, body = self._request(
            "/api/assets/fb-title-1/title",
            method="PUT",
            payload={
                "use_suggested": True,
                "expected_title": "Leslie Brannigan saved a link from Wisebird's post.",
            },
            headers={"X-Actor-Token": "owner-title-token"},
        )
        self.assertEqual(status, 200)
        asset = body.get("asset") or {}
        self.assertEqual(asset.get("title"), "Wisebird: Alpha Beta Guide")
        self.assertEqual((asset.get("title_info") or {}).get("working_origin_type"), "manual_working")
        with Db(self.db_path) as db:
            ensure_schema(db)
            live_title = db.query_value("select title from assets where id='fb-title-1'")
            current_origin = db.query_value(
                """
                select origin_type
                from asset_field_provenance
                where asset_id='fb-title-1' and field_name='title' and is_current=1
                limit 1
                """
            )
        self.assertEqual(str(live_title), "Wisebird: Alpha Beta Guide")
        self.assertEqual(str(current_origin), "manual_working")

    def test_title_apply_requires_owner(self):
        with Db(self.db_path) as db:
            ensure_schema(db)
            db.exec(
                """
                insert into actors (id, name, token, role, created_at)
                values (?, ?, ?, ?, datetime('now'))
                """,
                ("collab-title", "Collab", "collab-title-token", "collaborator"),
            )
            db.exec(
                """
                insert into assets (id, source, source_ref, title, imported_at)
                values (?, ?, ?, ?, datetime('now'))
                """,
                ("fb-title-2", "facebook", "https://example.com/alpha-beta-guide", "Generic saved link"),
            )

        status, body = self._request(
            "/api/assets/fb-title-2/title",
            method="PUT",
            payload={"title": "Better title"},
            headers={"X-Actor-Token": "collab-title-token"},
        )
        self.assertEqual(status, 403)
        self.assertIn("owner access required", body.get("error", "").lower())

    def test_asset_detail_includes_classification_review_payload(self):
        self._seed_v2_classification()
        with Db(self.db_path) as db:
            ensure_schema(db)
            db.exec(
                """
                insert into classification_runs
                  (id, schema_version, run_type, model_provider, model_name, prompt_version, config_json, created_at, notes)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "source-qc-run-test",
                    "curation_v2",
                    "source_link_qc",
                    "heuristic",
                    "test",
                    "",
                    "{}",
                    "2026-03-08T01:00:00+00:00",
                    "test seed",
                ),
            )
            db.exec(
                """
                insert into asset_source_link_qc
                  (id, run_id, asset_id, track, inferred_track, verdict, confidence, reason, fetch_status, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "source-qc-a1",
                    "source-qc-run-test",
                    "a1",
                    "style_product_decor",
                    "construction_concern",
                    "conflicting",
                    0.81,
                    "Source page suggests construction",
                    "fetched",
                    "2026-03-08T01:00:01+00:00",
                ),
            )
            db.exec(
                """
                insert into asset_overrides
                  (id, asset_id, track, axis_name, axis_value, operation, actor, note, created_at, expires_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "focus-a1",
                    "a1",
                    "construction_concern",
                    "review_focus",
                    "landscaping",
                    "set",
                    "Jim",
                    "",
                    "2026-03-08T01:00:02+00:00",
                    None,
                ),
            )

        status, body = self._request("/api/assets/a1")
        self.assertEqual(status, 200)
        review = (body.get("asset") or {}).get("classification_review") or {}
        self.assertEqual(review.get("current_track"), "style_product_decor")
        self.assertEqual(review.get("source_qc_inferred_track"), "construction_concern")
        self.assertEqual(review.get("source_qc_verdict"), "conflicting")
        self.assertEqual(review.get("active_review_focus"), "landscaping")

    def test_owner_can_save_modal_classification_review(self):
        self._seed_v2_classification()
        with Db(self.db_path) as db:
            ensure_schema(db)
            db.exec(
                """
                insert into actors (id, name, token, role, created_at)
                values (?, ?, ?, ?, datetime('now'))
                """,
                ("owner-class-review", "Jim", "owner-class-review-token", "owner"),
            )
            db.exec(
                """
                insert into asset_overrides
                  (id, asset_id, track, axis_name, axis_value, operation, actor, note, created_at, expires_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "old-override-a1",
                    "a1",
                    "irrelevant",
                    "track",
                    "irrelevant",
                    "set",
                    "Jim",
                    "old decision",
                    "2026-03-07T00:00:00+00:00",
                    None,
                ),
            )

        status, body = self._request(
            "/api/assets/a1/classification-review",
            method="PUT",
            payload={"track": "construction_concern", "review_focus": "inspection", "note": "Keep for builder checklist"},
            headers={"X-Actor-Token": "owner-class-review-token"},
        )
        self.assertEqual(status, 200)
        review = (body.get("asset") or {}).get("classification_review") or {}
        self.assertEqual(review.get("active_override_track"), "construction_concern")
        self.assertEqual(review.get("active_override_note"), "Keep for builder checklist")
        self.assertEqual(review.get("active_review_focus"), "inspection")

        with Db(self.db_path) as db:
            ensure_schema(db)
            rows = db.query(
                """
                select axis_value, note, expires_at
                from asset_overrides
                where asset_id='a1' and axis_name='track'
                order by created_at asc
                """
            )
            focus_rows = db.query(
                """
                select axis_value, expires_at
                from asset_overrides
                where asset_id='a1' and axis_name='review_focus'
                order by created_at asc
                """
            )
        self.assertEqual(str(rows[-1]["axis_value"]), "construction_concern")
        self.assertEqual(str(rows[-1]["note"]), "Keep for builder checklist")
        self.assertTrue(str(rows[0]["expires_at"] or "").strip())
        self.assertEqual(str(focus_rows[-1]["axis_value"]), "inspection")
        self.assertFalse(str(focus_rows[-1]["expires_at"] or "").strip())

    def test_owner_can_clear_modal_classification_review(self):
        self._seed_v2_classification()
        with Db(self.db_path) as db:
            ensure_schema(db)
            db.exec(
                """
                insert into actors (id, name, token, role, created_at)
                values (?, ?, ?, ?, datetime('now'))
                """,
                ("owner-class-clear", "Jim", "owner-class-clear-token", "owner"),
            )
            db.exec(
                """
                insert into asset_overrides
                  (id, asset_id, track, axis_name, axis_value, operation, actor, note, created_at, expires_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "active-override-a1",
                    "a1",
                    "style_product_decor",
                    "track",
                    "style_product_decor",
                    "set",
                    "Jim",
                    "keep current track (modal review)",
                    "2026-03-07T00:00:00+00:00",
                    None,
                ),
            )
            db.exec(
                """
                insert into asset_overrides
                  (id, asset_id, track, axis_name, axis_value, operation, actor, note, created_at, expires_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "active-focus-a1",
                    "a1",
                    "style_product_decor",
                    "review_focus",
                    "landscaping",
                    "set",
                    "Jim",
                    "",
                    "2026-03-07T00:00:00+00:00",
                    None,
                ),
            )

        status, body = self._request(
            "/api/assets/a1/classification-review",
            method="PUT",
            payload={"clear": True},
            headers={"X-Actor-Token": "owner-class-clear-token"},
        )
        self.assertEqual(status, 200)
        review = (body.get("asset") or {}).get("classification_review") or {}
        self.assertEqual(review.get("active_override_track"), "")
        self.assertEqual(review.get("active_review_focus"), "")

        with Db(self.db_path) as db:
            ensure_schema(db)
            expires_at = db.query_value(
                """
                select expires_at
                from asset_overrides
                where id='active-override-a1'
                """
            )
            focus_expires_at = db.query_value(
                """
                select expires_at
                from asset_overrides
                where id='active-focus-a1'
                """
            )
        self.assertTrue(str(expires_at or "").strip())
        self.assertTrue(str(focus_expires_at or "").strip())

    def test_classification_review_requires_owner(self):
        self._seed_v2_classification()
        with Db(self.db_path) as db:
            ensure_schema(db)
            db.exec(
                """
                insert into actors (id, name, token, role, created_at)
                values (?, ?, ?, ?, datetime('now'))
                """,
                ("collab-class-review", "Collab", "collab-class-review-token", "collaborator"),
            )

        status, body = self._request(
            "/api/assets/a1/classification-review",
            method="PUT",
            payload={"track": "style_product_decor", "note": "keep"},
            headers={"X-Actor-Token": "collab-class-review-token"},
        )
        self.assertEqual(status, 403)
        self.assertIn("owner access required", body.get("error", "").lower())

    def test_collection_filter_supports_multiple_collection_ids(self):
        with Db(self.db_path) as db:
            ensure_schema(db)
            db.exec(
                "insert into assets (id, source, source_ref, title, imported_at) values (?, ?, ?, ?, datetime('now'))",
                ("a3", "facebook", "facebook://saved/3", "Asset Three"),
            )
            db.exec(
                """
                insert into collections (id, name, description, created_at, updated_at)
                values (?, ?, ?, datetime('now'), datetime('now'))
                """,
                ("c2", "Bathroom", ""),
            )
            db.exec("insert into collection_items (collection_id, asset_id, position) values (?, ?, ?)", ("c2", "a3", 1))

        status, ids_body = self._request("/api/asset-ids?collection_id=c1,c2")
        self.assertEqual(status, 200)
        self.assertEqual(set(ids_body.get("ids", [])), {"a1", "a2", "a3"})

        status, body = self._request("/api/assets?collection_id=c1,c2&limit=10")
        self.assertEqual(status, 200)
        self.assertEqual({a["id"] for a in body.get("assets", [])}, {"a1", "a2", "a3"})

    def test_context_resolve_requires_authentication(self):
        status, body = self._request("/api/context/resolve?collection_id=c1&item_id=a1")
        self.assertEqual(status, 401)
        self.assertEqual(body.get("error"), "authentication required")

    def test_context_resolve_found_and_missing_states(self):
        with Db(self.db_path) as db:
            ensure_schema(db)
            db.exec(
                "insert into actors (id, name, token, role, created_at) values (?, ?, ?, ?, datetime('now'))",
                ("collab-ctx-1", "Collab", "collab-ctx-token-1", "collaborator"),
            )

        status, body = self._request(
            "/api/context/resolve?collection_id=c1&item_id=a1",
            headers={"X-Actor-Token": "collab-ctx-token-1"},
        )
        self.assertEqual(status, 200)
        self.assertTrue(body.get("found"))
        self.assertEqual(body.get("collection_id"), "c1")
        self.assertEqual(body.get("item_id"), "a1")

        with Db(self.db_path) as db:
            ensure_schema(db)
            db.exec("delete from collection_items where collection_id='c1' and asset_id='a1'")

        status, body = self._request(
            "/api/context/resolve?collection_id=c1&item_id=a1",
            headers={"X-Actor-Token": "collab-ctx-token-1"},
        )
        self.assertEqual(status, 200)
        self.assertFalse(body.get("found"))
        self.assertEqual(body.get("reason"), "item_not_in_collection")

    def test_context_resolve_hidden_item_is_owner_only(self):
        with Db(self.db_path) as db:
            ensure_schema(db)
            db.exec("update assets set triage_status='hidden' where id='a2'")
            db.exec(
                "insert into actors (id, name, token, role, created_at) values (?, ?, ?, ?, datetime('now'))",
                ("owner-ctx-1", "Owner", "owner-ctx-token-1", "owner"),
            )
            db.exec(
                "insert into actors (id, name, token, role, created_at) values (?, ?, ?, ?, datetime('now'))",
                ("collab-ctx-2", "Collab", "collab-ctx-token-2", "collaborator"),
            )

        status, body = self._request(
            "/api/context/resolve?collection_id=c1&item_id=a2",
            headers={"X-Actor-Token": "collab-ctx-token-2"},
        )
        self.assertEqual(status, 200)
        self.assertFalse(body.get("found"))
        self.assertEqual(body.get("reason"), "item_hidden_for_role")

        status, body = self._request(
            "/api/context/resolve?collection_id=c1&item_id=a2",
            headers={"X-Actor-Token": "owner-ctx-token-1"},
        )
        self.assertEqual(status, 200)
        self.assertTrue(body.get("found"))
        self.assertTrue(body.get("item_hidden"))

    def test_me_prefers_query_actor_over_header_token(self):
        with Db(self.db_path) as db:
            ensure_schema(db)
            db.exec(
                "insert into actors (id, name, token, role, created_at) values (?, ?, ?, ?, datetime('now'))",
                ("owner-me-1", "Owner", "owner-me-token", "owner"),
            )
            db.exec(
                "insert into actors (id, name, token, role, created_at) values (?, ?, ?, ?, datetime('now'))",
                ("collab-me-1", "Collab", "collab-me-token", "collaborator"),
            )

        status, body = self._request(
            "/api/me?actor=owner-me-token",
            headers={"X-Actor-Token": "collab-me-token"},
        )
        self.assertEqual(status, 200)
        actor = body.get("actor") or {}
        self.assertEqual(actor.get("name"), "Owner")
        self.assertEqual(actor.get("role"), "owner")
        self.assertEqual(actor.get("token"), "owner-me-token")

    def test_annotation_edit_and_delete_permissions(self):
        with Db(self.db_path) as db:
            ensure_schema(db)
            db.exec(
                "insert into actors (id, name, token, role, created_at) values (?, ?, ?, ?, datetime('now'))",
                ("owner-ann-1", "Owner", "owner-ann-token-1", "owner"),
            )
            db.exec(
                "insert into actors (id, name, token, role, created_at) values (?, ?, ?, ?, datetime('now'))",
                ("collab-ann-1", "Collab A", "collab-ann-token-1", "collaborator"),
            )
            db.exec(
                "insert into actors (id, name, token, role, created_at) values (?, ?, ?, ?, datetime('now'))",
                ("collab-ann-2", "Collab B", "collab-ann-token-2", "collaborator"),
            )
            db.exec(
                """
                insert into annotations
                  (id, asset_id, x, y, text, created_at, updated_at, actor_id, actor_name, annotation_type, resolved)
                values (?, ?, ?, ?, ?, datetime('now'), datetime('now'), ?, ?, 'note', 0)
                """,
                ("ann-own-1", "a1", 0.1, 0.2, "mine", "collab-ann-1", "Collab A"),
            )
            db.exec(
                """
                insert into annotations
                  (id, asset_id, x, y, text, created_at, updated_at, actor_id, actor_name, annotation_type, resolved)
                values (?, ?, ?, ?, ?, datetime('now'), datetime('now'), ?, ?, 'note', 0)
                """,
                ("ann-own-2", "a1", 0.3, 0.4, "theirs", "collab-ann-2", "Collab B"),
            )

        status, _ = self._request(
            "/api/annotations/ann-own-1",
            method="PUT",
            payload={"text": "updated by owner"},
            headers={"X-Actor-Token": "owner-ann-token-1"},
        )
        self.assertEqual(status, 200)

        status, body = self._request(
            "/api/annotations/ann-own-2",
            method="PUT",
            payload={"text": "unauthorized edit"},
            headers={"X-Actor-Token": "collab-ann-token-1"},
        )
        self.assertEqual(status, 403)
        self.assertEqual(body.get("error"), "not allowed to edit this annotation")

        status, _ = self._request(
            "/api/annotations/ann-own-1",
            method="PUT",
            payload={"text": "updated by self"},
            headers={"X-Actor-Token": "collab-ann-token-1"},
        )
        self.assertEqual(status, 200)

        status, body = self._request(
            "/api/annotations/ann-own-2",
            method="DELETE",
            headers={"X-Actor-Token": "collab-ann-token-1"},
        )
        self.assertEqual(status, 403)
        self.assertEqual(body.get("error"), "not allowed to delete this annotation")

        status, _ = self._request(
            "/api/annotations/ann-own-2",
            method="DELETE",
            headers={"X-Actor-Token": "owner-ann-token-1"},
        )
        self.assertEqual(status, 200)

        with Db(self.db_path) as db:
            ensure_schema(db)
            own_text = db.query_value("select text from annotations where id='ann-own-1'")
            remaining_other = db.query_value("select count(*) from annotations where id='ann-own-2'")
        self.assertEqual(own_text, "updated by self")
        self.assertEqual(remaining_other, 0)

    def test_annotation_create_prefers_query_actor_over_header(self):
        with Db(self.db_path) as db:
            ensure_schema(db)
            db.exec(
                "insert into actors (id, name, token, role, created_at) values (?, ?, ?, ?, datetime('now'))",
                ("owner-ann-3", "Owner", "owner-ann-token-3", "owner"),
            )
            db.exec(
                "insert into actors (id, name, token, role, created_at) values (?, ?, ?, ?, datetime('now'))",
                ("collab-ann-4", "Collab", "collab-ann-token-4", "collaborator"),
            )

        status, body = self._request(
            "/api/annotations?actor=owner-ann-token-3",
            method="POST",
            payload={"asset_id": "a1", "x": 0.25, "y": 0.45, "text": "query wins"},
            headers={"X-Actor-Token": "collab-ann-token-4"},
        )
        self.assertEqual(status, 201)
        ann = body.get("annotation") or {}
        self.assertEqual(ann.get("actor_name"), "Owner")
        self.assertEqual(ann.get("actor_id"), "owner-ann-3")

        with Db(self.db_path) as db:
            ensure_schema(db)
            actor_name = db.query_value("select actor_name from annotations where id=?", (ann.get("id"),))
        self.assertEqual(actor_name, "Owner")

    def test_annotation_resolve_requires_owner(self):
        with Db(self.db_path) as db:
            ensure_schema(db)
            db.exec(
                "insert into actors (id, name, token, role, created_at) values (?, ?, ?, ?, datetime('now'))",
                ("owner-ann-2", "Owner", "owner-ann-token-2", "owner"),
            )
            db.exec(
                "insert into actors (id, name, token, role, created_at) values (?, ?, ?, ?, datetime('now'))",
                ("collab-ann-3", "Collab C", "collab-ann-token-3", "collaborator"),
            )
            db.exec(
                """
                insert into annotations
                  (id, asset_id, x, y, text, created_at, updated_at, actor_id, actor_name, annotation_type, resolved)
                values (?, ?, ?, ?, ?, datetime('now'), datetime('now'), ?, ?, 'question', 0)
                """,
                ("ann-q-1", "a1", 0.2, 0.2, "question", "collab-ann-3", "Collab C"),
            )

        status, body = self._request(
            "/api/annotations/ann-q-1",
            method="PUT",
            payload={"resolved": 1},
            headers={"X-Actor-Token": "collab-ann-token-3"},
        )
        self.assertEqual(status, 403)
        self.assertEqual(body.get("error"), "owner access required to resolve questions")

        status, _ = self._request(
            "/api/annotations/ann-q-1",
            method="PUT",
            payload={"resolved": 1},
            headers={"X-Actor-Token": "owner-ann-token-2"},
        )
        self.assertEqual(status, 200)

        with Db(self.db_path) as db:
            ensure_schema(db)
            resolved = db.query_value("select resolved from annotations where id='ann-q-1'")
        self.assertEqual(resolved, 1)

    def test_questions_dashboard_owner_only_and_lists_open_questions(self):
        with Db(self.db_path) as db:
            ensure_schema(db)
            db.exec(
                "insert into actors (id, name, token, role, created_at) values (?, ?, ?, ?, datetime('now'))",
                ("owner-qdash-1", "Leslie", "owner-qdash-token-1", "owner"),
            )
            db.exec(
                "insert into actors (id, name, token, role, created_at) values (?, ?, ?, ?, datetime('now'))",
                ("collab-qdash-1", "Mark", "collab-qdash-token-1", "collaborator"),
            )
            db.exec(
                """
                insert into annotations
                  (id, asset_id, x, y, text, created_at, updated_at, actor_id, actor_name, annotation_type, resolved)
                values (?, ?, ?, ?, ?, datetime('now'), datetime('now'), ?, ?, 'question', 0)
                """,
                ("ann-qdash-1", "a1", 0.12, 0.18, "Is this the right vanity?", "collab-qdash-1", "Mark"),
            )
            db.exec(
                """
                insert into annotations
                  (id, asset_id, x, y, text, created_at, updated_at, actor_id, actor_name, annotation_type, resolved)
                values (?, ?, ?, ?, ?, datetime('now'), datetime('now'), ?, ?, 'question', 1)
                """,
                ("ann-qdash-2", "a1", 0.35, 0.41, "Resolved question", "collab-qdash-1", "Mark"),
            )

        status, body = self._request("/api/questions/dashboard")
        self.assertEqual(status, 403)
        self.assertEqual(body.get("error"), "owner access required")

        status, body = self._request(
            "/api/questions/dashboard",
            headers={"X-Actor-Token": "collab-qdash-token-1"},
        )
        self.assertEqual(status, 403)
        self.assertEqual(body.get("error"), "owner access required")

        status, body = self._request(
            "/api/questions/dashboard",
            headers={"X-Actor-Token": "owner-qdash-token-1"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(int(body.get("total") or 0), 1)
        questions = body.get("questions") or []
        self.assertEqual(len(questions), 1)
        q = questions[0]
        self.assertEqual(q.get("id"), "ann-qdash-1")
        self.assertEqual(q.get("actor_name"), "Mark")
        self.assertEqual(q.get("asset_id"), "a1")
        self.assertEqual(q.get("annotation_type"), "question")
        self.assertEqual(int(q.get("resolved") or 0), 0)

    def test_flag_is_owner_only_and_tag_workflow_retired(self):
        with Db(self.db_path) as db:
            ensure_schema(db)
            db.exec(
                "insert into actors (id, name, token, role, created_at) values (?, ?, ?, ?, datetime('now'))",
                ("owner-leslie-1", "Leslie", "leslie-token-1", "owner"),
            )
            db.exec(
                "insert into actors (id, name, token, role, created_at) values (?, ?, ?, ?, datetime('now'))",
                ("owner-jim-1", "Jim", "jim-token-1", "owner"),
            )
            db.exec(
                "insert into actors (id, name, token, role, created_at) values (?, ?, ?, ?, datetime('now'))",
                ("builder-mark-1", "Mark (Builder)", "mark-token-1", "builder"),
            )

        status, body = self._request(
            "/api/assets/a1/flag",
            method="POST",
            payload={"flagged": 1},
        )
        self.assertEqual(status, 403)
        self.assertEqual(body.get("error"), "flagging is restricted to owners")

        status, body = self._request(
            "/api/assets/a1/flag",
            method="POST",
            payload={"flagged": 1},
            headers={"X-Actor-Token": "jim-token-1"},
        )
        self.assertEqual(status, 200)

        status, body = self._request(
            "/api/assets/a1/flag",
            method="POST",
            payload={"flagged": 1},
            headers={"X-Actor-Token": "mark-token-1"},
        )
        self.assertEqual(status, 403)
        self.assertEqual(body.get("error"), "flagging is restricted to owners")

        status, _ = self._request(
            "/api/assets/a1/flag",
            method="POST",
            payload={"flagged": 1},
            headers={"X-Actor-Token": "leslie-token-1"},
        )
        self.assertEqual(status, 200)

        status, body = self._request(
            "/api/assets/a1/tag",
            method="POST",
            payload={"tagged": 1},
        )
        self.assertEqual(status, 410)
        self.assertEqual(body.get("error"), "tag workflow retired")

        status, body = self._request(
            "/api/assets/a1/tag",
            method="POST",
            payload={"tagged": 1},
            headers={"X-Actor-Token": "leslie-token-1"},
        )
        self.assertEqual(status, 410)
        self.assertEqual(body.get("error"), "tag workflow retired")

        status, body = self._request(
            "/api/assets/a1/tag",
            method="POST",
            payload={"tagged": 1},
            headers={"X-Actor-Token": "mark-token-1"},
        )
        self.assertEqual(status, 410)
        self.assertEqual(body.get("error"), "tag workflow retired")

        status, body = self._request(
            "/api/assets/a1/tag",
            method="POST",
            payload={"tagged": 1},
            headers={"X-Actor-Token": "jim-token-1"},
        )
        self.assertEqual(status, 410)
        self.assertEqual(body.get("error"), "tag workflow retired")

        status, body = self._request(
            "/api/assets/flag/bulk",
            method="POST",
            payload={"ids": ["a1", "a2"], "flagged": 1},
            headers={"X-Actor-Token": "mark-token-1"},
        )
        self.assertEqual(status, 403)
        self.assertEqual(body.get("error"), "flagging is restricted to owners")

        status, body = self._request(
            "/api/assets/tag/bulk",
            method="POST",
            payload={"ids": ["a1", "a2"], "tagged": 1},
            headers={"X-Actor-Token": "mark-token-1"},
        )
        self.assertEqual(status, 410)
        self.assertEqual(body.get("error"), "tag workflow retired")

        status, body = self._request(
            "/api/assets/flag/bulk",
            method="POST",
            payload={"ids": ["a1", "a2"], "flagged": 1},
            headers={"X-Actor-Token": "leslie-token-1"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(int(body.get("updated") or 0), 2)

        status, body = self._request(
            "/api/assets/flag/bulk",
            method="POST",
            payload={"ids": ["a1", "a2"], "flagged": 1},
            headers={"X-Actor-Token": "jim-token-1"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(int(body.get("updated") or 0), 2)

        with Db(self.db_path) as db:
            flagged_by = db.query_value("select flagged_by from assets where id='a1'")
        self.assertEqual(flagged_by, "Jim")

    def test_assets_endpoint_supports_label_mode_all(self):
        with Db(self.db_path) as db:
            ensure_schema(db)
            db.exec(
                """
                insert into asset_labels (id, asset_id, label, confidence, source, model, run_id, created_at)
                values (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                ("l1", "a1", "oak", 0.8, "ai", "test", "r1"),
            )
            db.exec(
                """
                insert into asset_labels (id, asset_id, label, confidence, source, model, run_id, created_at)
                values (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                ("l2", "a1", "white", 0.7, "ai", "test", "r1"),
            )
            db.exec(
                """
                insert into asset_labels (id, asset_id, label, confidence, source, model, run_id, created_at)
                values (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                ("l3", "a2", "oak", 0.9, "ai", "test", "r1"),
            )

        status, body = self._request("/api/assets?label=oak,white&label_mode=all")
        self.assertEqual(status, 200)
        self.assertEqual([a["id"] for a in body["assets"]], ["a1"])

    def test_hide_asset_moves_to_hidden_collection_and_excludes_from_main_canvas(self):
        status, body = self._request("/api/assets/a2/hide", method="POST", payload={})
        self.assertEqual(status, 200)
        hidden_id = body.get("hidden_collection_id")
        self.assertTrue(hidden_id)

        status, body = self._request("/api/assets")
        self.assertEqual(status, 200)
        self.assertEqual([a["id"] for a in body["assets"]], ["a1"])

        status, body = self._request(f"/api/assets?collection_id={hidden_id}")
        self.assertEqual(status, 200)
        self.assertEqual([a["id"] for a in body["assets"]], ["a2"])

    def test_scan_doc_pdf_endpoint_returns_doc_scoped_pdf(self):
        try:
            from PIL import Image  # type: ignore
        except Exception:
            self.skipTest("Pillow not available")

        sha = "a" * 64
        pages_dir = self.store_dir / "pages" / "scan" / sha
        pages_dir.mkdir(parents=True, exist_ok=True)
        p1 = pages_dir / "page-001.jpg"
        p2 = pages_dir / "page-002.jpg"
        p3 = pages_dir / "page-003.jpg"
        Image.new("RGB", (40, 40), (220, 80, 80)).save(p1, format="JPEG")
        Image.new("RGB", (40, 40), (80, 220, 80)).save(p2, format="JPEG")
        Image.new("RGB", (40, 40), (80, 80, 220)).save(p3, format="JPEG")

        with Db(self.db_path) as db:
            ensure_schema(db)
            db.exec(
                """
                insert into assets
                  (id, source, source_ref, title, imported_at, stored_path, thumb_path)
                values (?, ?, ?, ?, datetime('now'), ?, ?)
                """,
                ("s1", "scan", f"scan://{sha}#p1", "Doc one - doc 1", str(p1), str(p1)),
            )
            db.exec(
                """
                insert into assets
                  (id, source, source_ref, title, imported_at, stored_path, thumb_path)
                values (?, ?, ?, ?, datetime('now'), ?, ?)
                """,
                ("s2", "scan", f"scan://{sha}#p2", "Doc two - doc 2 p1", str(p2), str(p2)),
            )
            db.exec(
                """
                insert into assets
                  (id, source, source_ref, title, imported_at, stored_path, thumb_path)
                values (?, ?, ?, ?, datetime('now'), ?, ?)
                """,
                ("s3", "scan", f"scan://{sha}#p3", "Doc two - doc 2 p2", str(p3), str(p3)),
            )

        with urllib.request.urlopen(
            urllib.request.Request(f"{self.base_url}/api/scan/doc-pdf?asset_id=s1", method="GET"),
            timeout=5,
        ) as resp:
            body1 = resp.read()
            self.assertEqual(resp.status, 200)
            self.assertIn("application/pdf", (resp.headers.get("Content-Type") or ""))
            self.assertTrue(body1.startswith(b"%PDF"))

        with urllib.request.urlopen(
            urllib.request.Request(f"{self.base_url}/api/scan/doc-pdf?asset_id=s2", method="GET"),
            timeout=5,
        ) as resp:
            body2 = resp.read()
            self.assertEqual(resp.status, 200)
            self.assertIn("application/pdf", (resp.headers.get("Content-Type") or ""))
            self.assertTrue(body2.startswith(b"%PDF"))

        doc1 = self.store_dir / "originals" / "scan_docs" / sha / "asset-s1.pdf"
        doc2 = self.store_dir / "originals" / "scan_docs" / sha / "doc-0002.pdf"
        self.assertTrue(doc1.exists())
        self.assertTrue(doc2.exists())
        self.assertGreater(len(body2), len(body1))
        self.assertNotEqual(body1, body2)

    def test_scan_doc_pdf_endpoint_prefers_source_pdf_on_disk(self):
        sha = "b" * 64
        source_pdf = self.store_dir / "originals" / "scan" / f"{sha}.pdf"
        source_pdf.parent.mkdir(parents=True, exist_ok=True)
        pdf_bytes = b"%PDF-1.4\n%scan-source\n%%EOF\n"
        source_pdf.write_bytes(pdf_bytes)

        with Db(self.db_path) as db:
            ensure_schema(db)
            db.exec(
                """
                insert into assets
                  (id, source, source_ref, title, imported_at)
                values (?, ?, ?, ?, datetime('now'))
                """,
                ("s_src", "scan", f"scan://{sha}#p12", "Source PDF scan",),
            )

        with urllib.request.urlopen(
            urllib.request.Request(f"{self.base_url}/api/scan/doc-pdf?asset_id=s_src", method="GET"),
            timeout=5,
        ) as resp:
            body = resp.read()
            self.assertEqual(resp.status, 200)
            self.assertIn("application/pdf", (resp.headers.get("Content-Type") or ""))
            self.assertEqual(body, pdf_bytes)

    def test_media_pdf_for_scan_prefers_source_pdf_on_disk(self):
        sha = "c" * 64
        source_pdf = self.store_dir / "originals" / "scan" / f"{sha}.pdf"
        source_pdf.parent.mkdir(parents=True, exist_ok=True)
        pdf_bytes = b"%PDF-1.4\n%media-source\n%%EOF\n"
        source_pdf.write_bytes(pdf_bytes)

        with Db(self.db_path) as db:
            ensure_schema(db)
            db.exec(
                """
                insert into assets
                  (id, source, source_ref, title, imported_at)
                values (?, ?, ?, ?, datetime('now'))
                """,
                ("s_media", "scan", f"scan://{sha}#p3", "Media PDF scan",),
            )

        with urllib.request.urlopen(
            urllib.request.Request(f"{self.base_url}/media/s_media?kind=pdf", method="GET"),
            timeout=5,
        ) as resp:
            body = resp.read()
            self.assertEqual(resp.status, 200)
            self.assertIn("application/pdf", (resp.headers.get("Content-Type") or ""))
            self.assertEqual(body, pdf_bytes)

    def test_scan_doc_pdf_prefers_doc_scoped_pdf_when_doc_pages_exist(self):
        try:
            from PIL import Image  # type: ignore
        except Exception:
            self.skipTest("Pillow not available")

        sha = "d" * 64
        source_pdf = self.store_dir / "originals" / "scan" / f"{sha}.pdf"
        source_pdf.parent.mkdir(parents=True, exist_ok=True)
        source_pdf_bytes = b"%PDF-1.4\n%batch-source\n%%EOF\n"
        source_pdf.write_bytes(source_pdf_bytes)

        pages_dir = self.store_dir / "pages" / "scan" / sha
        pages_dir.mkdir(parents=True, exist_ok=True)
        p1 = pages_dir / "page-001.jpg"
        p2 = pages_dir / "page-002.jpg"
        Image.new("RGB", (40, 40), (220, 80, 80)).save(p1, format="JPEG")
        Image.new("RGB", (40, 40), (80, 220, 80)).save(p2, format="JPEG")

        with Db(self.db_path) as db:
            ensure_schema(db)
            db.exec(
                """
                insert into assets
                  (id, source, source_ref, title, imported_at, stored_path, thumb_path)
                values (?, ?, ?, ?, datetime('now'), ?, ?)
                """,
                ("s_doc1", "scan", f"scan://{sha}#p1", "Clip sample - doc 88 p1", str(p1), str(p1)),
            )
            db.exec(
                """
                insert into assets
                  (id, source, source_ref, title, imported_at, stored_path, thumb_path)
                values (?, ?, ?, ?, datetime('now'), ?, ?)
                """,
                ("s_doc2", "scan", f"scan://{sha}#p2", "Clip sample - doc 88 p2", str(p2), str(p2)),
            )

        with urllib.request.urlopen(
            urllib.request.Request(f"{self.base_url}/api/scan/doc-pdf?asset_id=s_doc1", method="GET"),
            timeout=5,
        ) as resp:
            body = resp.read()
            self.assertEqual(resp.status, 200)
            self.assertIn("application/pdf", (resp.headers.get("Content-Type") or ""))
            self.assertTrue(body.startswith(b"%PDF"))
            self.assertNotEqual(body, source_pdf_bytes)

        with urllib.request.urlopen(
            urllib.request.Request(f"{self.base_url}/media/s_doc1?kind=pdf", method="GET"),
            timeout=5,
        ) as resp:
            body = resp.read()
            self.assertEqual(resp.status, 200)
            self.assertIn("application/pdf", (resp.headers.get("Content-Type") or ""))
            self.assertTrue(body.startswith(b"%PDF"))
            self.assertNotEqual(body, source_pdf_bytes)

    def test_large_scan_doc_groups_are_not_collapsed_in_assets_list(self):
        try:
            from PIL import Image  # type: ignore
        except Exception:
            self.skipTest("Pillow not available")

        sha = "e" * 64
        source_pdf = self.store_dir / "originals" / "scan" / f"{sha}.pdf"
        source_pdf.parent.mkdir(parents=True, exist_ok=True)
        source_pdf_bytes = b"%PDF-1.4\n%big-doc-source\n%%EOF\n"
        source_pdf.write_bytes(source_pdf_bytes)

        pages_dir = self.store_dir / "pages" / "scan" / sha
        pages_dir.mkdir(parents=True, exist_ok=True)

        with Db(self.db_path) as db:
            ensure_schema(db)
            for idx in range(1, 8):
                page = pages_dir / f"page-{idx:03d}.jpg"
                Image.new("RGB", (40, 40), (20 * idx, 30 * idx, 40 * idx)).save(page, format="JPEG")
                db.exec(
                    """
                    insert into assets
                      (id, source, source_ref, title, imported_at, stored_path, thumb_path)
                    values (?, ?, ?, ?, datetime('now'), ?, ?)
                    """,
                    (
                        f"s_big_{idx}",
                        "scan",
                        f"scan://{sha}#p{idx}",
                        f"Big doc sample - doc 77 p{idx}",
                        str(page),
                        str(page),
                    ),
                )

        status, body = self._request("/api/assets?source=scan&limit=20&include_hidden=1")
        self.assertEqual(status, 200)
        ids = [a["id"] for a in body.get("assets", [])]
        for idx in range(1, 8):
            self.assertIn(f"s_big_{idx}", ids)

        with urllib.request.urlopen(
            urllib.request.Request(f"{self.base_url}/media/s_big_1?kind=pdf", method="GET"),
            timeout=5,
        ) as resp1:
            body1 = resp1.read()
            self.assertEqual(resp1.status, 200)
            self.assertTrue(body1.startswith(b"%PDF"))
            self.assertNotEqual(body1, source_pdf_bytes)
        with urllib.request.urlopen(
            urllib.request.Request(f"{self.base_url}/media/s_big_7?kind=pdf", method="GET"),
            timeout=5,
        ) as resp2:
            body2 = resp2.read()
            self.assertEqual(resp2.status, 200)
            self.assertTrue(body2.startswith(b"%PDF"))
            self.assertNotEqual(body2, source_pdf_bytes)
        self.assertNotEqual(body1, body2)

    def test_cluster_review_endpoint_exports_collection_payload(self):
        with Db(self.db_path) as db:
            ensure_schema(db)
            db.exec(
                """
                insert into assets (id, source, source_ref, title, imported_at, media_status, content_kind, stored_path)
                values (?, ?, ?, ?, datetime('now'), ?, ?, ?)
                """,
                ("i1", "pinterest", "pin://i1", "Image 1", "image", "pin", str(self.original)),
            )
            db.exec(
                """
                insert into assets (id, source, source_ref, title, imported_at, media_status, content_kind, stored_path)
                values (?, ?, ?, ?, datetime('now'), ?, ?, ?)
                """,
                ("i2", "pinterest", "pin://i2", "Image 2", "image", "pin", str(self.original)),
            )
            db.exec(
                """
                insert or ignore into collection_items (collection_id, asset_id, position)
                values (?, ?, ?)
                """,
                ("c1", "i1", 3),
            )
            db.exec(
                """
                insert or ignore into collection_items (collection_id, asset_id, position)
                values (?, ?, ?)
                """,
                ("c1", "i2", 4),
            )
            db.exec(
                """
                insert into asset_embeddings (id, asset_id, provider, model, input_text, vector_json, dimensions, created_at)
                values (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                ("e1", "i1", "gemini", "gemini-embedding-001", "img1", "[0.1,0.2,0.3]", 3),
            )
            db.exec(
                """
                insert into asset_embeddings (id, asset_id, provider, model, input_text, vector_json, dimensions, created_at)
                values (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                ("e2", "i2", "gemini", "gemini-embedding-001", "img2", "[0.11,0.21,0.31]", 3),
            )

        status, body = self._request("/api/cluster/review?collection_id=c1&include_neighbors=0")
        self.assertEqual(status, 200)
        self.assertIn("nodes", body)
        self.assertIn("meta", body)
        self.assertEqual(body.get("meta", {}).get("collection_id"), "c1")

    def test_tools_cluster_explorer_route_serves_html(self):
        req = urllib.request.Request(f"{self.base_url}/tools/cluster_explorer.html", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read().decode("utf-8")
            self.assertEqual(resp.status, 200)
            self.assertIn("Cluster Explorer", body)

    def test_facets_endpoint_contextualizes_content_kinds(self):
        with Db(self.db_path) as db:
            ensure_schema(db)
            db.exec(
                """
                insert into assets
                  (id, source, source_ref, title, imported_at, media_status, content_kind)
                values (?, ?, ?, ?, datetime('now'), ?, ?)
                """,
                ("p1", "pinterest", "pin://3", "Pin", "image", "pin"),
            )
            db.exec(
                """
                insert into assets
                  (id, source, source_ref, title, imported_at, media_status, content_kind)
                values (?, ?, ?, ?, datetime('now'), ?, ?)
                """,
                ("f1", "facebook", "facebook://saved/f1", "FB post", "metadata_only", "post"),
            )

        status, body = self._request("/api/facets?source=pinterest&media_status=image")
        self.assertEqual(status, 200)
        facets = body.get("facets", {})
        all_kinds = {r["content_kind"] for r in facets.get("content_kinds", [])}
        context_kinds = {r["content_kind"] for r in facets.get("content_kinds_context", [])}
        self.assertIn("post", all_kinds)
        self.assertIn("pin", all_kinds)
        self.assertEqual(context_kinds, {"pin"})

    def test_server_cache_policy_for_app_and_api(self):
        status, body, headers = self._request("/api/collections", return_headers=True)
        self.assertEqual(status, 200)
        self.assertIn("collections", body)
        self.assertEqual(headers.get("Cache-Control"), "no-store")

        req = urllib.request.Request(f"{self.base_url}/app/app.js", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.headers.get("Cache-Control"), "public, max-age=300")

        req = urllib.request.Request(f"{self.base_url}/app/app.js?v=6", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.headers.get("Cache-Control"), "public, max-age=300")

    def test_head_requests_supported_for_api_and_static_assets(self):
        status, body, headers = self._request("/api/assets?limit=1", method="HEAD", return_headers=True)
        self.assertEqual(status, 200)
        self.assertEqual(body, {})
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        self.assertEqual(headers.get("Content-Type"), "application/json")

        status, body, headers = self._request("/app/app.js", method="HEAD", return_headers=True)
        self.assertEqual(status, 200)
        self.assertEqual(body, {})
        self.assertEqual(headers.get("Cache-Control"), "public, max-age=300")
        self.assertEqual(headers.get("Content-Type"), "application/javascript")

    def test_store_files_route_serves_media(self):
        req = urllib.request.Request(f"{self.base_url}/store/originals/pinterest/a1.jpg", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = resp.read()
            self.assertEqual(resp.status, 200)
            self.assertEqual(data, b"img")

    def test_triage_rollback_requires_owner_and_restores_cutoff_state(self):
        with Db(self.db_path) as db:
            ensure_schema(db)
            db.exec(
                "insert into actors (id, name, token, role, created_at) values (?, ?, ?, ?, datetime('now'))",
                ("owner-rb-1", "Owner", "owner-rb-token-1", "owner"),
            )
            db.exec(
                "insert into actors (id, name, token, role, created_at) values (?, ?, ?, ?, datetime('now'))",
                ("collab-rb-1", "Collab", "collab-rb-token-1", "collaborator"),
            )

        status, body = self._request(
            "/api/assets/triage/bulk",
            method="POST",
            payload={"ids": ["a1", "a2"], "status": "hidden"},
            headers={"X-Actor-Token": "owner-rb-token-1"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(body.get("updated"), 2)

        status, _ = self._request(
            "/api/triage/rollback",
            method="POST",
            payload={"days_ago": 2},
            headers={"X-Actor-Token": "collab-rb-token-1"},
        )
        self.assertEqual(status, 403)

        status, body = self._request(
            "/api/triage/rollback",
            method="POST",
            payload={"days_ago": 2},
            headers={"X-Actor-Token": "owner-rb-token-1"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(body.get("updated"), 2)

        with Db(self.db_path) as db:
            rows = db.query("select id, triage_status from assets where id in ('a1','a2') order by id")
        self.assertEqual([(r["id"], r["triage_status"]) for r in rows], [("a1", None), ("a2", None)])

    def test_run_server_uses_threaded_runtime_server(self):
        created: list[object] = []

        class FakeServer:
            def __init__(self, address, handler_cls):
                self.address = address
                self.handler_cls = handler_cls
                self.serve_forever_called = False
                created.append(self)

            def serve_forever(self):
                self.serve_forever_called = True

        with mock.patch("inspirations.server.InspirationsHTTPServer", FakeServer), \
             mock.patch("inspirations.server._seed_default_actors") as seed:
            run_server(
                host="127.0.0.1",
                port=9999,
                db_path=self.db_path,
                app_dir=self.app_dir,
                store_dir=self.store_dir,
            )

        self.assertEqual(len(created), 1)
        srv = created[0]
        self.assertEqual(srv.address, ("127.0.0.1", 9999))
        self.assertIs(srv.handler_cls, ApiHandler)
        self.assertEqual(srv.db_path, self.db_path)
        self.assertEqual(srv.app_dir, self.app_dir)
        self.assertEqual(srv.store_dir, self.store_dir)
        self.assertEqual(srv.imports_dir, self.app_dir.resolve().parent / "imports")
        self.assertEqual(srv.admin_tokens, {})
        self.assertTrue(srv.serve_forever_called)
        seed.assert_called_once_with(self.db_path, "127.0.0.1", 9999)

    def test_scan_pdf_upload_runs_import_and_thumbs(self):
        boundary = "----insp-test-boundary"
        pdf_data = b"%PDF-1.4\nmock\n%%EOF\n"
        body = (
            (
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="split_on_delimiters"\r\n\r\n'
                "0\r\n"
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="use_form_parser"\r\n\r\n'
                "1\r\n"
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="file"; filename="batch.pdf"\r\n'
                "Content-Type: application/pdf\r\n\r\n"
            ).encode("utf-8")
            + pdf_data
            + f"\r\n--{boundary}--\r\n".encode("utf-8")
        )
        fake_import = {
            "source": "scan",
            "created_assets": 3,
            "delimiter_pages_skipped": 1,
            "detected_documents": 2,
            "errors": [],
        }
        fake_thumbs = {"tool": "sips", "attempted": 3, "generated": 3, "errors": []}
        with (
            mock.patch("inspirations.server.import_scans_inbox", return_value=fake_import) as mocked_import,
            mock.patch("inspirations.server.generate_thumbnails", return_value=fake_thumbs) as mocked_thumbs,
        ):
            status, payload = self._request(
                "/api/import/scans",
                method="POST",
                raw_data=body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            )

        self.assertEqual(status, 200)
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("upload_size_bytes"), len(pdf_data))
        self.assertFalse(payload.get("options", {}).get("split_on_delimiters", True))
        self.assertTrue(payload.get("options", {}).get("use_form_parser"))
        self.assertEqual(payload.get("import", {}).get("created_assets"), 3)
        self.assertEqual(payload.get("thumbs", {}).get("generated"), 3)

        uploaded_file = Path(payload.get("uploaded_file", ""))
        self.assertTrue(uploaded_file.exists())
        self.assertIn("/imports/scans/inbox/uploads/", str(uploaded_file).replace("\\", "/"))

        self.assertTrue(mocked_import.called)
        self.assertTrue(mocked_thumbs.called)
        import_kwargs = mocked_import.call_args.kwargs
        self.assertEqual(import_kwargs.get("format"), "jpg")
        self.assertEqual(import_kwargs.get("renderer"), "auto")
        self.assertEqual(import_kwargs.get("max_pages"), 0)
        self.assertFalse(import_kwargs.get("split_on_delimiters"))

    def test_photo_upload_runs_import_and_thumbs(self):
        boundary = "----insp-photo-boundary"
        jpg_data = b"\xff\xd8\xff\xe0" + b"mockjpegdata" + b"\xff\xd9"
        body = (
            (
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="file"; filename="kitchen.jpg"\r\n'
                "Content-Type: image/jpeg\r\n\r\n"
            ).encode("utf-8")
            + jpg_data
            + f"\r\n--{boundary}--\r\n".encode("utf-8")
        )
        fake_import = {
            "source": "photo",
            "created_assets": 1,
            "errors": [],
        }
        fake_thumbs = {"tool": "sips", "attempted": 1, "generated": 1, "errors": []}
        with (
            mock.patch("inspirations.server.import_photos_inbox", return_value=fake_import) as mocked_import,
            mock.patch("inspirations.server.generate_thumbnails", return_value=fake_thumbs) as mocked_thumbs,
        ):
            status, payload = self._request(
                "/api/import/photos",
                method="POST",
                raw_data=body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            )

        self.assertEqual(status, 200)
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("upload_size_bytes"), len(jpg_data))
        self.assertEqual(payload.get("import", {}).get("created_assets"), 1)
        self.assertEqual(payload.get("thumbs", {}).get("generated"), 1)

        uploaded_file = Path(payload.get("uploaded_file", ""))
        self.assertTrue(uploaded_file.exists())
        self.assertIn("/imports/photos/inbox/uploads/", str(uploaded_file).replace("\\", "/"))

        self.assertTrue(mocked_import.called)
        self.assertTrue(mocked_thumbs.called)
        import_kwargs = mocked_import.call_args.kwargs
        self.assertEqual(import_kwargs.get("limit"), 0)
        self.assertEqual(import_kwargs.get("source"), "scan")
        self.assertEqual(import_kwargs.get("content_kind"), "photo")
        thumbs_kwargs = mocked_thumbs.call_args.kwargs
        self.assertEqual(thumbs_kwargs.get("source"), "scan")

    def test_video_upload_runs_import(self):
        boundary = "----insp-video-boundary"
        mp4_data = b"\x00\x00\x00\x18ftypmp42mock"
        body = (
            (
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="file"; filename="walkthrough.mp4"\r\n'
                "Content-Type: video/mp4\r\n\r\n"
            ).encode("utf-8")
            + mp4_data
            + f"\r\n--{boundary}--\r\n".encode("utf-8")
        )
        fake_import = {
            "source": "scan",
            "created_assets": 1,
            "errors": [],
        }
        with mock.patch("inspirations.server.import_videos_inbox", return_value=fake_import) as mocked_import:
            status, payload = self._request(
                "/api/import/videos",
                method="POST",
                raw_data=body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            )

        self.assertEqual(status, 200)
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("upload_size_bytes"), len(mp4_data))
        self.assertEqual(payload.get("import", {}).get("created_assets"), 1)

        uploaded_file = Path(payload.get("uploaded_file", ""))
        self.assertTrue(uploaded_file.exists())
        self.assertIn("/imports/videos/inbox/uploads/", str(uploaded_file).replace("\\", "/"))

        self.assertTrue(mocked_import.called)
        import_kwargs = mocked_import.call_args.kwargs
        self.assertEqual(import_kwargs.get("limit"), 0)
        self.assertEqual(import_kwargs.get("source"), "scan")
        self.assertEqual(import_kwargs.get("content_kind"), "video")

    def test_scan_upload_applies_title_and_tags_to_import_batch(self):
        imported_at = "2026-03-02T15:45:00+00:00"
        self._insert_asset(
            asset_id="scan-meta-1",
            source="scan",
            source_ref="scan://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa#p3",
            title="Old Batch - doc 2 p1",
            imported_at=imported_at,
        )

        boundary = "----insp-scan-meta-boundary"
        pdf_data = b"%PDF-1.4\nmock\n%%EOF\n"
        body = (
            (
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="title"\r\n\r\n'
                "Kitchen Batch\r\n"
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="tags"\r\n\r\n'
                "kitchen, lighting, kitchen\r\n"
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="file"; filename="batch.pdf"\r\n'
                "Content-Type: application/pdf\r\n\r\n"
            ).encode("utf-8")
            + pdf_data
            + f"\r\n--{boundary}--\r\n".encode("utf-8")
        )
        fake_import = {
            "source": "scan",
            "imported_at": imported_at,
            "created_assets": 1,
            "delimiter_pages_skipped": 0,
            "detected_documents": 1,
            "errors": [],
        }
        fake_thumbs = {"tool": "sips", "attempted": 1, "generated": 1, "errors": []}
        with (
            mock.patch("inspirations.server.import_scans_inbox", return_value=fake_import),
            mock.patch("inspirations.server.generate_thumbnails", return_value=fake_thumbs),
        ):
            status, payload = self._request(
                "/api/import/scans",
                method="POST",
                raw_data=body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            )

        self.assertEqual(status, 200)
        self.assertEqual(payload.get("options", {}).get("title"), "Kitchen Batch")
        self.assertEqual(payload.get("options", {}).get("tags"), ["kitchen", "lighting"])
        self.assertEqual(payload.get("options", {}).get("auto_tags"), ["actor:unknown", f"ingested_at:{imported_at}"])
        self.assertEqual(payload.get("ingest_metadata", {}).get("updated_titles"), 1)
        self.assertEqual(payload.get("ingest_metadata", {}).get("applied_tags"), 4)

        with Db(self.db_path) as db:
            ensure_schema(db)
            title = db.query_value("select title from assets where id='scan-meta-1'")
        self.assertEqual(str(title), "Kitchen Batch - doc 2 p1")
        self.assertCountEqual(
            self._labels_for_asset("scan-meta-1"),
            [f"ingested_at:{imported_at}", "actor:unknown", "kitchen", "lighting"],
        )

    def test_photo_upload_applies_title_and_tags_to_import_batch(self):
        imported_at = "2026-03-02T15:46:00+00:00"
        self._insert_asset(
            asset_id="photo-meta-1",
            source="scan",
            source_ref="clip-photo://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            title="Old Photo Title",
            imported_at=imported_at,
        )

        boundary = "----insp-photo-meta-boundary"
        jpg_data = b"\xff\xd8\xff\xe0" + b"mockjpegdata" + b"\xff\xd9"
        body = (
            (
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="title"\r\n\r\n'
                "Mudroom Concept\r\n"
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="tags"\r\n\r\n'
                "mudroom, storage\r\n"
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="file"; filename="kitchen.jpg"\r\n'
                "Content-Type: image/jpeg\r\n\r\n"
            ).encode("utf-8")
            + jpg_data
            + f"\r\n--{boundary}--\r\n".encode("utf-8")
        )
        fake_import = {
            "source": "scan",
            "imported_at": imported_at,
            "created_assets": 1,
            "errors": [],
        }
        fake_thumbs = {"tool": "sips", "attempted": 1, "generated": 1, "errors": []}
        with (
            mock.patch("inspirations.server.import_photos_inbox", return_value=fake_import),
            mock.patch("inspirations.server.generate_thumbnails", return_value=fake_thumbs),
        ):
            status, payload = self._request(
                "/api/import/photos",
                method="POST",
                raw_data=body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            )

        self.assertEqual(status, 200)
        self.assertEqual(payload.get("options", {}).get("title"), "Mudroom Concept")
        self.assertEqual(payload.get("options", {}).get("tags"), ["mudroom", "storage"])
        self.assertEqual(payload.get("options", {}).get("auto_tags"), ["actor:unknown", f"ingested_at:{imported_at}"])
        self.assertEqual(payload.get("ingest_metadata", {}).get("updated_titles"), 1)
        self.assertEqual(payload.get("ingest_metadata", {}).get("applied_tags"), 4)

        with Db(self.db_path) as db:
            ensure_schema(db)
            title = db.query_value("select title from assets where id='photo-meta-1'")
        self.assertEqual(str(title), "Mudroom Concept")
        self.assertCountEqual(
            self._labels_for_asset("photo-meta-1"),
            [f"ingested_at:{imported_at}", "actor:unknown", "mudroom", "storage"],
        )

    def test_scan_upload_auto_actor_tag_uses_authenticated_actor_name(self):
        imported_at = "2026-03-02T15:46:30+00:00"
        self._insert_asset(
            asset_id="scan-meta-actor-1",
            source="scan",
            source_ref="scan://bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb#p1",
            title="Old Batch - doc 3 p1",
            imported_at=imported_at,
        )
        with Db(self.db_path) as db:
            ensure_schema(db)
            db.exec(
                "insert into actors (id, name, token, role, created_at) values (?, ?, ?, ?, datetime('now'))",
                ("owner-ingest-1", "Jim", "owner-ingest-token-1", "owner"),
            )

        boundary = "----insp-scan-meta-actor-boundary"
        pdf_data = b"%PDF-1.4\nmock\n%%EOF\n"
        body = (
            (
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="file"; filename="batch.pdf"\r\n'
                "Content-Type: application/pdf\r\n\r\n"
            ).encode("utf-8")
            + pdf_data
            + f"\r\n--{boundary}--\r\n".encode("utf-8")
        )
        fake_import = {
            "source": "scan",
            "imported_at": imported_at,
            "created_assets": 1,
            "delimiter_pages_skipped": 0,
            "detected_documents": 1,
            "errors": [],
        }
        fake_thumbs = {"tool": "sips", "attempted": 1, "generated": 1, "errors": []}
        with (
            mock.patch("inspirations.server.import_scans_inbox", return_value=fake_import),
            mock.patch("inspirations.server.generate_thumbnails", return_value=fake_thumbs),
        ):
            status, payload = self._request(
                "/api/import/scans",
                method="POST",
                raw_data=body,
                headers={
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                    "X-Actor-Token": "owner-ingest-token-1",
                },
            )

        self.assertEqual(status, 200)
        self.assertEqual(payload.get("options", {}).get("auto_tags"), ["actor:Jim", f"ingested_at:{imported_at}"])
        self.assertEqual(payload.get("ingest_metadata", {}).get("applied_tags"), 2)
        self.assertCountEqual(
            self._labels_for_asset("scan-meta-actor-1"),
            ["actor:Jim", f"ingested_at:{imported_at}"],
        )

    def test_video_upload_applies_title_and_tags_to_import_batch(self):
        imported_at = "2026-03-02T15:47:00+00:00"
        self._insert_asset(
            asset_id="video-meta-1",
            source="scan",
            source_ref="clip-video://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            title="Old Video Title",
            imported_at=imported_at,
        )

        boundary = "----insp-video-meta-boundary"
        mp4_data = b"\x00\x00\x00\x18ftypmp42mock"
        body = (
            (
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="title"\r\n\r\n'
                "Pantry Walkthrough\r\n"
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="tags"\r\n\r\n'
                "pantry, storage, pantry\r\n"
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="file"; filename="walkthrough.mp4"\r\n'
                "Content-Type: video/mp4\r\n\r\n"
            ).encode("utf-8")
            + mp4_data
            + f"\r\n--{boundary}--\r\n".encode("utf-8")
        )
        fake_import = {
            "source": "scan",
            "imported_at": imported_at,
            "created_assets": 1,
            "errors": [],
        }
        with mock.patch("inspirations.server.import_videos_inbox", return_value=fake_import):
            status, payload = self._request(
                "/api/import/videos",
                method="POST",
                raw_data=body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            )

        self.assertEqual(status, 200)
        self.assertEqual(payload.get("options", {}).get("title"), "Pantry Walkthrough")
        self.assertEqual(payload.get("options", {}).get("tags"), ["pantry", "storage"])
        self.assertEqual(payload.get("options", {}).get("auto_tags"), ["actor:unknown", f"ingested_at:{imported_at}"])
        self.assertEqual(payload.get("ingest_metadata", {}).get("updated_titles"), 1)
        self.assertEqual(payload.get("ingest_metadata", {}).get("applied_tags"), 4)

        with Db(self.db_path) as db:
            ensure_schema(db)
            title = db.query_value("select title from assets where id='video-meta-1'")
        self.assertEqual(str(title), "Pantry Walkthrough")
        self.assertCountEqual(
            self._labels_for_asset("video-meta-1"),
            [f"ingested_at:{imported_at}", "actor:unknown", "pantry", "storage"],
        )


if __name__ == "__main__":
    unittest.main()
