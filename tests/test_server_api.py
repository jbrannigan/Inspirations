import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import HTTPServer
from pathlib import Path
from unittest import mock

from inspirations.db import Db, ensure_schema
from inspirations.server import ApiHandler


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

    def test_assets_endpoint_supports_media_status_filter(self):
        status, body = self._request("/api/assets?media_status=metadata_only")
        self.assertEqual(status, 200)
        self.assertEqual([a["id"] for a in body["assets"]], ["a2"])

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

    def test_server_disables_caching_for_app_and_api(self):
        status, body, headers = self._request("/api/collections", return_headers=True)
        self.assertEqual(status, 200)
        self.assertIn("collections", body)
        self.assertEqual(headers.get("Cache-Control"), "no-store")

        req = urllib.request.Request(f"{self.base_url}/app/app.js", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.headers.get("Cache-Control"), "no-store")

    def test_store_files_route_serves_media(self):
        req = urllib.request.Request(f"{self.base_url}/store/originals/pinterest/a1.jpg", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = resp.read()
            self.assertEqual(resp.status, 200)
            self.assertEqual(data, b"img")

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
        thumbs_kwargs = mocked_thumbs.call_args.kwargs
        self.assertEqual(thumbs_kwargs.get("source"), "photo")


if __name__ == "__main__":
    unittest.main()
