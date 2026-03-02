import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from inspirations.db import Db, ensure_schema
from inspirations.storage import backfill_previews_from_source_ref, download_url_to_store


class _FakeBinaryResponse:
    def __init__(self, content_type: str, body: bytes):
        self.headers = {
            "Content-Type": content_type,
            "Content-Length": str(len(body)),
        }
        self._body = body
        self._cursor = 0

    def read(self, n: int = -1) -> bytes:
        if n < 0:
            n = len(self._body) - self._cursor
        out = self._body[self._cursor : self._cursor + n]
        self._cursor += len(out)
        return out

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class TestStorageBackfill(unittest.TestCase):
    def test_download_url_to_store_writes_stream_once(self):
        data = (b"A" * 70000) + (b"B" * 90000)
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "store"
            with mock.patch("inspirations.storage.is_safe_public_url", return_value=True), mock.patch(
                "inspirations.storage.urllib.request.urlopen",
                return_value=_FakeBinaryResponse("image/jpeg", data),
            ):
                out_path, sha, nbytes = download_url_to_store(
                    url="https://img.example.com/photo.jpg",
                    dest_dir=out_dir,
                    filename_stem="asset-a1",
                )
            self.assertTrue(out_path.exists())
            self.assertEqual(out_path.read_bytes(), data)
            self.assertEqual(sha, hashlib.sha256(data).hexdigest())
            self.assertEqual(nbytes, len(data))

    def test_backfill_updates_placeholder_asset_and_regenerates_thumbs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "t.sqlite"
            store_dir = root / "store"
            old_image = store_dir / "originals" / "facebook" / "old.jpg"
            old_thumb = store_dir / "thumbs" / "facebook" / "a1.jpg"
            old_image.parent.mkdir(parents=True, exist_ok=True)
            old_thumb.parent.mkdir(parents=True, exist_ok=True)
            old_image.write_bytes(b"old")
            old_thumb.write_bytes(b"thumb")
            downloaded_tmp = store_dir / "originals" / "facebook" / "a1.jpg"
            downloaded_tmp.write_bytes(b"new-image")

            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets
                      (id, source, source_ref, title, imported_at, image_url, stored_path, thumb_path, sha256, media_status)
                    values (?, ?, ?, ?, datetime('now'), ?, ?, ?, ?, ?)
                    """,
                    (
                        "a1",
                        "facebook",
                        "https://example.com/post/1",
                        "Saved item",
                        "https://placeholder.example.com/card.jpg",
                        str(old_image),
                        str(old_thumb),
                        "oldsha",
                        "placeholder",
                    ),
                )
                with mock.patch("inspirations.storage.is_safe_public_url", return_value=True), mock.patch(
                    "inspirations.storage.resolve_image_url",
                    return_value="https://cdn.example.com/real.jpg",
                ), mock.patch(
                    "inspirations.storage.download_url_to_store",
                    return_value=(downloaded_tmp, "newsha", 9),
                ), mock.patch(
                    "inspirations.storage.generate_thumbnails",
                    return_value={"generated": 1, "attempted": 1},
                ) as mocked_thumbs:
                    report = backfill_previews_from_source_ref(
                        db,
                        store_dir=store_dir,
                        source="facebook",
                        media_status="placeholder",
                    )

                row = db.query(
                    "select image_url, stored_path, thumb_path, sha256, media_status from assets where id='a1'"
                )[0]

            self.assertEqual(report["updated"], 1)
            self.assertEqual(report["downloaded"], 1)
            self.assertEqual(report["resolved"], 1)
            self.assertEqual(report["cleaned_orphan_files"], 1)
            self.assertEqual(report["thumbnails"].get("generated"), 1)
            mocked_thumbs.assert_called_once()
            self.assertEqual(row["image_url"], "https://cdn.example.com/real.jpg")
            self.assertEqual(row["sha256"], "newsha")
            self.assertEqual(row["media_status"], "image")
            self.assertIsNone(row["thumb_path"])
            self.assertTrue(str(row["stored_path"]).endswith("newsha.jpg"))
            self.assertTrue(Path(row["stored_path"]).exists())
            self.assertFalse(old_image.exists())

    def test_backfill_excludes_hidden_items_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "t.sqlite"
            store_dir = root / "store"

            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets
                      (id, source, source_ref, title, imported_at, media_status, triage_status)
                    values (?, ?, ?, ?, datetime('now'), ?, ?)
                    """,
                    (
                        "hidden-a1",
                        "facebook",
                        "https://example.com/post/hidden",
                        "Hidden item",
                        "placeholder",
                        "hidden",
                    ),
                )
                with mock.patch("inspirations.storage.resolve_image_url") as mocked_resolve:
                    report = backfill_previews_from_source_ref(
                        db,
                        store_dir=store_dir,
                        source="facebook",
                        media_status="placeholder",
                    )
            self.assertEqual(report["candidates"], 0)
            self.assertEqual(report["attempted"], 0)
            self.assertEqual(report["updated"], 0)
            mocked_resolve.assert_not_called()

    def test_backfill_dry_run_reports_changes_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "t.sqlite"
            store_dir = root / "store"
            old_image = store_dir / "originals" / "facebook" / "old.jpg"
            old_thumb = store_dir / "thumbs" / "facebook" / "a1.jpg"
            old_image.parent.mkdir(parents=True, exist_ok=True)
            old_thumb.parent.mkdir(parents=True, exist_ok=True)
            old_image.write_bytes(b"old")
            old_thumb.write_bytes(b"thumb")

            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets
                      (id, source, source_ref, title, imported_at, image_url, stored_path, thumb_path, media_status)
                    values (?, ?, ?, ?, datetime('now'), ?, ?, ?, ?)
                    """,
                    (
                        "a1",
                        "facebook",
                        "https://example.com/post/1",
                        "Saved item",
                        "https://placeholder.example.com/card.jpg",
                        str(old_image),
                        str(old_thumb),
                        "placeholder",
                    ),
                )
                with mock.patch("inspirations.storage.is_safe_public_url", return_value=True), mock.patch(
                    "inspirations.storage.resolve_image_url",
                    return_value="https://cdn.example.com/real.jpg",
                ), mock.patch("inspirations.storage.download_url_to_store") as mocked_download:
                    report = backfill_previews_from_source_ref(
                        db,
                        store_dir=store_dir,
                        source="facebook",
                        media_status="placeholder",
                        dry_run=True,
                    )
                    row = db.query("select media_status, stored_path, thumb_path from assets where id='a1'")[0]

            mocked_download.assert_not_called()
            self.assertEqual(report["updated"], 0)
            self.assertEqual(report["downloaded"], 0)
            self.assertEqual(report["would_update"], 1)
            self.assertEqual(row["media_status"], "placeholder")
            self.assertEqual(row["stored_path"], str(old_image))
            self.assertEqual(row["thumb_path"], str(old_thumb))


if __name__ == "__main__":
    unittest.main()
