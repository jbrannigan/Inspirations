import importlib.util
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path


def _load_server_module():
    path = Path(__file__).resolve().parent.parent / "tools" / "serve_explorer.py"
    spec = importlib.util.spec_from_file_location("serve_explorer_tool", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestServeExplorer(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_server_module()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

        (self.root / "tools").mkdir(parents=True, exist_ok=True)
        (self.root / "store" / "thumbs").mkdir(parents=True, exist_ok=True)
        (self.root / "tools" / "cluster_explorer.html").write_text("<html>ok</html>", encoding="utf-8")
        self.data_path = self.root / "tools" / "cluster_data.json"
        self.data_path.write_text(json.dumps({"meta": {}, "nodes": [], "links": []}), encoding="utf-8")
        self.store_file = self.root / "store" / "thumbs" / "a.jpg"
        self.store_file.write_bytes(b"jpg")

        self.server = self.module.make_server(
            host="127.0.0.1",
            port=0,
            project_root=self.root,
            data_path=self.data_path,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

        deadline = time.time() + 4
        while time.time() < deadline:
            try:
                status, _, _ = self._request("/")
                if status == 200:
                    return
            except Exception:
                time.sleep(0.05)
        raise RuntimeError("serve_explorer test server failed to start")

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self._tmp.cleanup()

    def _request(self, path: str):
        req = urllib.request.Request(f"{self.base_url}{path}", method="GET")
        try:
            with urllib.request.urlopen(req, timeout=4) as resp:
                body = resp.read()
                return resp.status, body, dict(resp.headers.items())
        except urllib.error.HTTPError as e:
            try:
                body = e.read()
                return e.code, body, dict((e.headers or {}).items())
            finally:
                e.close()

    def _request_head(self, path: str):
        req = urllib.request.Request(f"{self.base_url}{path}", method="HEAD")
        try:
            with urllib.request.urlopen(req, timeout=4) as resp:
                body = resp.read()
                return resp.status, body, dict(resp.headers.items())
        except urllib.error.HTTPError as e:
            try:
                body = e.read()
                return e.code, body, dict((e.headers or {}).items())
            finally:
                e.close()

    def test_serves_html_and_cluster_json_with_no_store(self):
        status, body, headers = self._request("/")
        self.assertEqual(status, 200)
        self.assertIn(b"<html>ok</html>", body)
        self.assertEqual(headers.get("Cache-Control"), "no-store")

        status, body, headers = self._request("/cluster_data.json")
        self.assertEqual(status, 200)
        parsed = json.loads(body.decode("utf-8"))
        self.assertEqual(parsed["nodes"], [])
        self.assertEqual(headers.get("Cache-Control"), "no-store")

    def test_serves_store_files_and_blocks_path_traversal(self):
        status, body, headers = self._request("/store/thumbs/a.jpg")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"jpg")
        self.assertEqual(headers.get("Cache-Control"), "max-age=3600")

        status, _, _ = self._request("/store/../tools/cluster_explorer.html")
        self.assertEqual(status, 403)

    def test_rejects_non_allowlisted_paths(self):
        status, _, _ = self._request("/api/assets")
        self.assertEqual(status, 404)

    def test_head_requests_are_supported(self):
        status, body, headers = self._request_head("/")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"")
        self.assertEqual(headers.get("Cache-Control"), "no-store")


if __name__ == "__main__":
    unittest.main()
