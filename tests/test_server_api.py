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

    def _request(self, path: str, *, method: str = "GET", payload: dict | None = None, headers: dict | None = None):
        req_headers = dict(headers or {})
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            req_headers.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(f"{self.base_url}{path}", method=method, data=data, headers=req_headers)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                raw = resp.read().decode("utf-8")
                body = json.loads(raw) if raw else {}
                return resp.status, body
        except urllib.error.HTTPError as e:
            try:
                raw = e.read().decode("utf-8")
                try:
                    body = json.loads(raw) if raw else {}
                except json.JSONDecodeError:
                    body = {"error": raw}
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
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": ""}, clear=False):
            status, body = self._request("/api/search/similar?q=oak")
        self.assertEqual(status, 503)
        self.assertIn("GEMINI_API_KEY", body.get("error", ""))

    def test_semantic_search_endpoint(self):
        fake_report = {
            "query": "oak kitchen",
            "provider": "gemini",
            "model": "gemini-embedding-001",
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
                status, body = self._request("/api/search/similar?q=oak%20kitchen&source=pinterest&limit=10")
        self.assertEqual(status, 200)
        self.assertEqual(body.get("results", [])[0].get("id"), "a1")
        mocked.assert_called_once()


if __name__ == "__main__":
    unittest.main()
