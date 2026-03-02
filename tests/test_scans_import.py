import base64
import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from inspirations.db import Db, ensure_schema
from inspirations.importers.scans import import_scans_inbox, import_videos_inbox, _split_pages_into_documents


TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="
)


class TestScansImport(unittest.TestCase):
    def test_import_single_image_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            inbox = base / "inbox"
            store = base / "store"
            inbox.mkdir()
            img = inbox / "scan1.png"
            img.write_bytes(TINY_PNG)

            db_path = base / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                report1 = import_scans_inbox(db, inbox_dir=inbox, store_dir=store)
                report2 = import_scans_inbox(db, inbox_dir=inbox, store_dir=store)
                n = db.query_value("select count(*) from assets where source='scan'")

            self.assertEqual(n, 1)
            self.assertEqual(report1["created_assets"], 1)
            self.assertEqual(report2["created_assets"], 0)
            self.assertEqual(report2["duplicates_skipped"], 1)

    def test_import_nested_inbox_paths(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            inbox = base / "inbox"
            store = base / "store"
            nested = inbox / "recipes"
            nested.mkdir(parents=True)
            img = nested / "scan1.png"
            img.write_bytes(TINY_PNG)

            db_path = base / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                report = import_scans_inbox(db, inbox_dir=inbox, store_dir=store)
                n = db.query_value("select count(*) from assets where source='scan'")

            self.assertEqual(n, 1)
            self.assertEqual(report["parsed_files"], 1)
            self.assertEqual(report["created_assets"], 1)

    def test_pdf_skips_when_no_renderer(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            inbox = base / "inbox"
            store = base / "store"
            inbox.mkdir()
            pdf = inbox / "scan1.pdf"
            pdf.write_text("%PDF-1.4 mock")

            db_path = base / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                with mock.patch("inspirations.importers.scans._select_pdf_renderer", return_value=None):
                    report = import_scans_inbox(db, inbox_dir=inbox, store_dir=store)

            self.assertEqual(report["created_assets"], 0)
            self.assertTrue(report["errors"])

    def test_split_pages_into_documents_no_delimiters(self):
        page_map, doc_count = _split_pages_into_documents(4, set())
        self.assertEqual(doc_count, 4)
        self.assertEqual(page_map[1], (1, 1, 1))
        self.assertEqual(page_map[4], (4, 1, 1))

    def test_split_pages_into_documents_with_trailing_delimiters(self):
        page_map, doc_count = _split_pages_into_documents(9, {4, 8, 9})
        self.assertEqual(doc_count, 4)
        self.assertEqual(page_map[1], (1, 1, 1))
        self.assertEqual(page_map[2], (2, 1, 1))
        self.assertEqual(page_map[3], (3, 1, 1))
        self.assertEqual(page_map[5], (4, 1, 3))
        self.assertEqual(page_map[7], (4, 3, 3))
        self.assertEqual(page_map[6], (4, 2, 3))

    def test_pdf_delimiters_are_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            inbox = base / "inbox"
            store = base / "store"
            inbox.mkdir()
            pdf = inbox / "batch.pdf"
            pdf.write_text("%PDF-1.4 mock")
            sha = hashlib.sha256(pdf.read_bytes()).hexdigest()

            fake_pages = []
            for n in range(1, 7):
                p = base / f"page-{n}.jpg"
                p.write_bytes(b"fake")
                fake_pages.append(p)

            db_path = base / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                with (
                    mock.patch("inspirations.importers.scans._select_pdf_renderer", return_value="pdftoppm"),
                    mock.patch("inspirations.importers.scans._render_pdf", return_value=fake_pages),
                    mock.patch("inspirations.importers.scans._detect_pdf_delimiter_pages", return_value={3, 6}),
                ):
                    report = import_scans_inbox(db, inbox_dir=inbox, store_dir=store)
                refs = [
                    str(r["source_ref"])
                    for r in db.query("select source_ref from assets where source='scan' order by source_ref asc")
                ]

            self.assertEqual(report["created_assets"], 4)
            self.assertEqual(report["delimiter_pages_skipped"], 2)
            self.assertEqual(report["detected_documents"], 3)
            self.assertEqual(
                refs,
                [
                    f"scan://{sha}#p1",
                    f"scan://{sha}#p2",
                    f"scan://{sha}#p4",
                    f"scan://{sha}#p5",
                ],
            )

    def test_pdf_delimiter_detection_can_be_disabled(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            inbox = base / "inbox"
            store = base / "store"
            inbox.mkdir()
            pdf = inbox / "batch.pdf"
            pdf.write_text("%PDF-1.4 mock")
            sha = hashlib.sha256(pdf.read_bytes()).hexdigest()

            fake_pages = []
            for n in range(1, 5):
                p = base / f"page-{n}.jpg"
                p.write_bytes(b"fake")
                fake_pages.append(p)

            db_path = base / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                with (
                    mock.patch("inspirations.importers.scans._select_pdf_renderer", return_value="pdftoppm"),
                    mock.patch("inspirations.importers.scans._render_pdf", return_value=fake_pages),
                    mock.patch("inspirations.importers.scans._detect_pdf_delimiter_pages") as mocked_detect,
                ):
                    report = import_scans_inbox(
                        db,
                        inbox_dir=inbox,
                        store_dir=store,
                        split_on_delimiters=False,
                    )
                refs = [
                    str(r["source_ref"])
                    for r in db.query("select source_ref from assets where source='scan' order by source_ref asc")
                ]

            self.assertEqual(report["created_assets"], 4)
            self.assertEqual(report["delimiter_pages_skipped"], 0)
            self.assertEqual(report["detected_documents"], 4)
            self.assertFalse(report["delimiter_detection_enabled"])
            self.assertFalse(mocked_detect.called)
            self.assertEqual(
                refs,
                [
                    f"scan://{sha}#p1",
                    f"scan://{sha}#p2",
                    f"scan://{sha}#p3",
                    f"scan://{sha}#p4",
                ],
            )

    def test_import_single_video_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            inbox = base / "inbox"
            store = base / "store"
            inbox.mkdir()
            vid = inbox / "walkthrough.mp4"
            vid.write_bytes(b"\x00\x00\x00\x18ftypmp42mock")

            db_path = base / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                report1 = import_videos_inbox(db, inbox_dir=inbox, store_dir=store)
                report2 = import_videos_inbox(db, inbox_dir=inbox, store_dir=store)
                n = db.query_value("select count(*) from assets where source='video'")
                row = db.query("select media_status, content_kind, stored_video_path from assets where source='video' limit 1")[0]

            self.assertEqual(n, 1)
            self.assertEqual(report1["created_assets"], 1)
            self.assertEqual(report2["created_assets"], 0)
            self.assertEqual(report2["duplicates_skipped"], 1)
            self.assertEqual(str(row["media_status"]), "video")
            self.assertEqual(str(row["content_kind"]), "video")
            self.assertTrue(str(row["stored_video_path"]).endswith(".mp4"))

    def test_import_single_video_generates_poster_when_ffmpeg_available(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            inbox = base / "inbox"
            store = base / "store"
            inbox.mkdir()
            vid = inbox / "walkthrough.mp4"
            vid.write_bytes(b"\x00\x00\x00\x18ftypmp42mock")

            def _fake_ffmpeg(args, **kwargs):
                poster = Path(str(args[-1]))
                poster.parent.mkdir(parents=True, exist_ok=True)
                poster.write_bytes(b"jpg")
                return subprocess.CompletedProcess(args=args, returncode=0)

            db_path = base / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                with (
                    mock.patch("inspirations.importers.scans.shutil.which", side_effect=lambda cmd: "/usr/bin/ffmpeg" if cmd == "ffmpeg" else None),
                    mock.patch("inspirations.importers.scans.subprocess.run", side_effect=_fake_ffmpeg),
                ):
                    report = import_videos_inbox(db, inbox_dir=inbox, store_dir=store)
                row = db.query(
                    "select thumb_path, stored_video_path from assets where source='video' limit 1"
                )[0]

            self.assertEqual(report["created_assets"], 1)
            self.assertEqual(report["poster"]["tool"], "ffmpeg")
            self.assertEqual(report["poster"]["generated"], 1)
            self.assertEqual(report["poster"]["errors"], [])
            self.assertTrue(str(row["stored_video_path"]).endswith(".mp4"))
            self.assertTrue(str(row["thumb_path"]).endswith(".jpg"))
            self.assertTrue(Path(str(row["thumb_path"])).exists())

    def test_import_single_video_poster_failure_does_not_block_ingest(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            inbox = base / "inbox"
            store = base / "store"
            inbox.mkdir()
            vid = inbox / "walkthrough.mp4"
            vid.write_bytes(b"\x00\x00\x00\x18ftypmp42mock")

            db_path = base / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                with (
                    mock.patch("inspirations.importers.scans.shutil.which", side_effect=lambda cmd: "/usr/bin/ffmpeg" if cmd == "ffmpeg" else None),
                    mock.patch("inspirations.importers.scans.subprocess.run", side_effect=RuntimeError("ffmpeg failed")),
                ):
                    report = import_videos_inbox(db, inbox_dir=inbox, store_dir=store)
                row = db.query(
                    "select thumb_path, stored_video_path from assets where source='video' limit 1"
                )[0]

            self.assertEqual(report["created_assets"], 1)
            self.assertEqual(report["poster"]["tool"], "ffmpeg")
            self.assertEqual(report["poster"]["generated"], 0)
            self.assertTrue(report["poster"]["errors"])
            self.assertTrue(str(row["stored_video_path"]).endswith(".mp4"))
            self.assertIsNone(row["thumb_path"])


if __name__ == "__main__":
    unittest.main()
