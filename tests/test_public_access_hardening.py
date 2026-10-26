"""Covers the hardening added for reverse-proxied public access.

Range support, streamed media, security headers, rate limiting, and the
console-only guard on first-run admin setup.
"""

import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import HTTPServer
from pathlib import Path
from unittest import mock

from inspirations import server as server_module
from inspirations.db import Db, ensure_schema, remove_database_sidecars
from inspirations.security import RateLimiter
from inspirations.server import ApiHandler

MEDIA_BYTES = bytes(range(256)) * 8  # 2048 bytes, non-compressible-ish


class TestRateLimiter(unittest.TestCase):
    def test_allows_up_to_limit_then_blocks(self) -> None:
        limiter = RateLimiter(limit=3, window_seconds=60.0)
        for _ in range(3):
            allowed, retry = limiter.check("k", now=1000.0)
            self.assertTrue(allowed)
            self.assertEqual(retry, 0.0)
        allowed, retry = limiter.check("k", now=1000.0)
        self.assertFalse(allowed)
        self.assertAlmostEqual(retry, 60.0, places=3)

    def test_window_slides(self) -> None:
        limiter = RateLimiter(limit=1, window_seconds=10.0)
        self.assertTrue(limiter.check("k", now=100.0)[0])
        self.assertFalse(limiter.check("k", now=105.0)[0])
        # Once the first hit ages out of the window the caller is allowed again.
        self.assertTrue(limiter.check("k", now=110.1)[0])

    def test_keys_are_independent(self) -> None:
        limiter = RateLimiter(limit=1, window_seconds=60.0)
        self.assertTrue(limiter.check("a", now=1.0)[0])
        self.assertTrue(limiter.check("b", now=1.0)[0])
        self.assertFalse(limiter.check("a", now=1.0)[0])

    def test_key_table_stays_bounded(self) -> None:
        limiter = RateLimiter(limit=5, window_seconds=60.0, max_keys=8)
        for i in range(50):
            limiter.check(f"k{i}", now=1000.0)
        self.assertLessEqual(len(limiter._hits), 8)

    def test_rejects_invalid_construction(self) -> None:
        with self.assertRaises(ValueError):
            RateLimiter(limit=0, window_seconds=60.0)
        with self.assertRaises(ValueError):
            RateLimiter(limit=1, window_seconds=0)


class TestWalMode(unittest.TestCase):
    def test_connection_enables_wal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "wal.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                mode = db.query_value("pragma journal_mode;")
            self.assertEqual(str(mode).lower(), "wal")


class TestWalSafeBackup(unittest.TestCase):
    """A file copy of a WAL database can miss committed rows; the backup API cannot."""

    def test_backup_captures_rows_still_in_the_wal(self) -> None:
        import shutil
        import sqlite3

        from inspirations.db import backup_database

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "src.sqlite"
            with Db(src) as db:
                db.exec("create table t (v text);")
                db.exec("insert into t (v) values ('committed');")
                self.assertEqual(str(db.query_value("pragma journal_mode;")).lower(), "wal")

            # A plain copy of the main file alone is the unsafe pattern.
            naive = root / "naive.sqlite"
            shutil.copy2(src, naive)

            proper = root / "proper.sqlite"
            backup_database(src, proper)

            conn = sqlite3.connect(proper)
            try:
                self.assertEqual(conn.execute("select v from t").fetchall(), [("committed",)])
            finally:
                conn.close()

            # The naive copy is not asserted wrong — SQLite may have checkpointed
            # already — only that the backup API is correct regardless.
            self.assertTrue(naive.exists())

    def test_remove_sidecars_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "x.sqlite"
            with Db(db_path) as db:
                db.exec("create table t (v text);")
            Path(str(db_path) + "-wal").touch()
            remove_database_sidecars(db_path)
            self.assertFalse(Path(str(db_path) + "-wal").exists())
            remove_database_sidecars(db_path)  # must not raise


class TestPublicAccessHardening(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.db_path = self.tmp_path / "t.sqlite"
        self.store_dir = self.tmp_path / "store"
        self.app_dir = Path(__file__).resolve().parent.parent / "app"
        self.original = self.store_dir / "originals" / "pinterest" / "a1.bin"
        self.original.parent.mkdir(parents=True, exist_ok=True)
        self.original.write_bytes(MEDIA_BYTES)

        with Db(self.db_path) as db:
            ensure_schema(db)
            db.exec(
                """
                insert into assets (id, source, source_ref, title, imported_at, stored_path)
                values (?, ?, ?, ?, datetime('now'), ?)
                """,
                ("a1", "pinterest", "pin://1", "Asset One", str(self.original)),
            )
            ensure_schema(db)

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
                if self._get("/api/assets")[0] == 200:
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

    def _get(self, path: str, *, headers: dict | None = None, method: str = "GET"):
        req = urllib.request.Request(f"{self.base_url}{path}", method=method, headers=dict(headers or {}))
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, resp.read(), dict(resp.headers)
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(), dict(exc.headers)

    def _post(self, path: str, payload: dict, *, headers: dict | None = None):
        req_headers = {"Content-Type": "application/json", **dict(headers or {})}
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            method="POST",
            data=json.dumps(payload).encode("utf-8"),
            headers=req_headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, resp.read(), dict(resp.headers)
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(), dict(exc.headers)

    # --- security headers ---

    def _assert_security_headers(self, headers: dict) -> None:
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(headers.get("Referrer-Policy"), "strict-origin-when-cross-origin")

    def test_security_headers_on_api_response(self) -> None:
        status, _, headers = self._get("/api/assets")
        self.assertEqual(status, 200)
        self._assert_security_headers(headers)

    def test_security_headers_on_media_response(self) -> None:
        status, _, headers = self._get("/media/a1?kind=original")
        self.assertEqual(status, 200)
        self._assert_security_headers(headers)

    def test_security_headers_on_error_response(self) -> None:
        status, _, headers = self._get("/media/does-not-exist?kind=original")
        self.assertEqual(status, 404)
        self._assert_security_headers(headers)

    def test_security_headers_on_static_app_file(self) -> None:
        status, _, headers = self._get("/app/shared.js")
        self.assertEqual(status, 200)
        self._assert_security_headers(headers)

    # --- range support ---

    def test_full_media_response_advertises_ranges(self) -> None:
        status, body, headers = self._get("/media/a1?kind=original")
        self.assertEqual(status, 200)
        self.assertEqual(body, MEDIA_BYTES)
        self.assertEqual(headers.get("Accept-Ranges"), "bytes")
        self.assertEqual(headers.get("Content-Length"), str(len(MEDIA_BYTES)))

    def test_range_returns_partial_content(self) -> None:
        status, body, headers = self._get("/media/a1?kind=original", headers={"Range": "bytes=10-19"})
        self.assertEqual(status, 206)
        self.assertEqual(body, MEDIA_BYTES[10:20])
        self.assertEqual(headers.get("Content-Range"), f"bytes 10-19/{len(MEDIA_BYTES)}")
        self.assertEqual(headers.get("Content-Length"), "10")

    def test_open_ended_range(self) -> None:
        start = len(MEDIA_BYTES) - 16
        status, body, headers = self._get("/media/a1?kind=original", headers={"Range": f"bytes={start}-"})
        self.assertEqual(status, 206)
        self.assertEqual(body, MEDIA_BYTES[start:])
        self.assertEqual(headers.get("Content-Range"), f"bytes {start}-{len(MEDIA_BYTES) - 1}/{len(MEDIA_BYTES)}")

    def test_suffix_range(self) -> None:
        status, body, _ = self._get("/media/a1?kind=original", headers={"Range": "bytes=-16"})
        self.assertEqual(status, 206)
        self.assertEqual(body, MEDIA_BYTES[-16:])

    def test_range_past_end_is_unsatisfiable(self) -> None:
        offset = len(MEDIA_BYTES) + 500
        status, _, headers = self._get("/media/a1?kind=original", headers={"Range": f"bytes={offset}-"})
        self.assertEqual(status, 416)
        self.assertEqual(headers.get("Content-Range"), f"bytes */{len(MEDIA_BYTES)}")

    def test_multi_range_falls_back_to_whole_body(self) -> None:
        status, body, _ = self._get("/media/a1?kind=original", headers={"Range": "bytes=0-9,20-29"})
        self.assertEqual(status, 200)
        self.assertEqual(body, MEDIA_BYTES)

    def test_unknown_range_unit_ignored(self) -> None:
        status, body, _ = self._get("/media/a1?kind=original", headers={"Range": "items=0-9"})
        self.assertEqual(status, 200)
        self.assertEqual(body, MEDIA_BYTES)

    def test_head_on_media_sends_no_body(self) -> None:
        status, body, headers = self._get("/media/a1?kind=original", method="HEAD")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"")
        self.assertEqual(headers.get("Content-Length"), str(len(MEDIA_BYTES)))

    # --- rate limiting ---

    def test_admin_login_is_rate_limited(self) -> None:
        pw_file = self.db_path.parent / "admin_password.txt"
        pw_file.write_text("correct horse\n", encoding="utf-8")
        tight = RateLimiter(limit=2, window_seconds=60.0)
        with mock.patch.object(server_module, "ADMIN_LOGIN_RATE_LIMIT", tight):
            first = self._post("/api/admin/login", {"password": "wrong"})
            second = self._post("/api/admin/login", {"password": "wrong"})
            third = self._post("/api/admin/login", {"password": "wrong"})
        self.assertEqual(first[0], 403)
        self.assertEqual(second[0], 403)
        self.assertEqual(third[0], 429)
        self.assertTrue(int(third[2]["Retry-After"]) >= 1)
        self._assert_security_headers(third[2])

    def test_rate_limited_response_does_not_check_password(self) -> None:
        """A 429 must preempt verification, or the limiter buys nothing."""
        pw_file = self.db_path.parent / "admin_password.txt"
        pw_file.write_text("correct horse\n", encoding="utf-8")
        exhausted = RateLimiter(limit=1, window_seconds=60.0)
        with mock.patch.object(server_module, "ADMIN_LOGIN_RATE_LIMIT", exhausted):
            self._post("/api/admin/login", {"password": "wrong"})
            status, _, _ = self._post("/api/admin/login", {"password": "correct horse"})
        self.assertEqual(status, 429)

    def test_mutating_verbs_are_rate_limited(self) -> None:
        tight = RateLimiter(limit=1, window_seconds=60.0)
        with mock.patch.object(server_module, "MUTATION_RATE_LIMIT", tight):
            self._post("/api/collections", {"name": "First"})
            status, _, _ = self._post("/api/collections", {"name": "Second"})
        self.assertEqual(status, 429)

    def test_reads_are_not_rate_limited(self) -> None:
        tight = RateLimiter(limit=1, window_seconds=60.0)
        with mock.patch.object(server_module, "MUTATION_RATE_LIMIT", tight):
            for _ in range(5):
                status, _, _ = self._get("/api/assets")
                self.assertEqual(status, 200)

    # --- console-only admin setup ---

    def test_setup_rejected_when_request_looks_forwarded(self) -> None:
        """Loopback + Host alone cannot prove a request is local behind a proxy."""
        for header in ("CF-Connecting-IP", "CF-Ray", "X-Forwarded-For", "X-Forwarded-Host"):
            with self.subTest(header=header):
                status, _, _ = self._post(
                    "/api/admin/setup",
                    {"password": "hunter2hunter2"},
                    headers={"Host": "localhost", header: "203.0.113.9"},
                )
                self.assertNotEqual(status, 200)

    def test_setup_rejected_for_public_host_header(self) -> None:
        status, _, _ = self._post(
            "/api/admin/setup",
            {"password": "hunter2hunter2"},
            headers={"Host": "inspirations.8499timberbridgeln.com"},
        )
        self.assertNotEqual(status, 200)


if __name__ == "__main__":
    unittest.main()
