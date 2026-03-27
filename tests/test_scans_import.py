import base64
import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from inspirations.db import Db, ensure_schema
from inspirations.importers.scans import (
    audit_scan_separator_pages,
    repair_scan_document_grouping,
    _choose_regroup_base_title,
    _delimiter_candidates_from_metrics,
    purge_scan_separator_pages,
    _split_asset_pages_for_regrouping,
    _split_pages_into_documents,
    import_scans_inbox,
    import_videos_inbox,
)


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

    def test_delimiter_candidates_detect_uniform_separator_sheets(self):
        metrics = [
            (1, 0.996358, 51.146, 8.400),
            (8, 0.995648, 46.058, 10.809),
            (10, 1.0, 24.056, 0.728),
            (16, 0.999888, 29.749, 1.758),
            (19, 1.0, 16.664, 0.625),
            (28, 0.999853, 26.959, 1.033),
            (35, 0.997538, 58.670, 9.200),
        ]
        self.assertEqual(_delimiter_candidates_from_metrics(metrics), {10, 19, 28})

    def test_split_asset_pages_for_regrouping_respects_delimiters_and_exclusions(self):
        docs = _split_asset_pages_for_regrouping(
            list(range(1, 13)),
            delimiter_pages={5, 10},
            excluded_pages={8},
        )
        self.assertEqual(docs, [[1, 2, 3, 4], [6, 7], [9], [11, 12]])

    def test_choose_regroup_base_title_skips_generic_repeated_titles(self):
        rows = [
            {"title": "Book Mar 4, 2026 - doc 11"},
            {"title": "Modern farmhouse kitchen featuring a large stainless steel range - doc 12"},
            {"title": "Book Mar 4, 2026 - doc 13"},
        ]
        base = _choose_regroup_base_title(rows, generic_bases={"Book Mar 4, 2026"})
        self.assertEqual(base, "Modern farmhouse kitchen featuring a large stainless steel range")

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

    def test_audit_scan_separator_pages_reports_and_applies_overrides(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            store = base / "store"
            pdf_dir = store / "originals" / "scan"
            pdf_dir.mkdir(parents=True)
            pdf = pdf_dir / ("a" * 64 + ".pdf")
            pdf.write_text("%PDF-1.4 mock")

            db_path = base / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.executemany(
                    """
                    insert into assets
                      (id, source, source_ref, title, imported_at, image_url, stored_path, sha256, media_status, content_kind)
                    values (?, 'scan', ?, ?, '2026-03-21T00:00:00+00:00', ?, ?, ?, 'image', 'scan')
                    """,
                    [
                        ("asset-p1", f"scan://{'a' * 64}#p1", "batch - doc 1", "/tmp/p1.jpg", "/tmp/p1.jpg", "a" * 64),
                        ("asset-p2", f"scan://{'a' * 64}#p2", "batch - doc 2", "/tmp/p2.jpg", "/tmp/p2.jpg", "a" * 64),
                        ("asset-p3", f"scan://{'a' * 64}#p3", "batch - doc 3", "/tmp/p3.jpg", "/tmp/p3.jpg", "a" * 64),
                    ],
                )
                with mock.patch("inspirations.importers.scans._select_pdf_renderer", return_value="pdftoppm"), \
                     mock.patch("inspirations.importers.scans._detect_pdf_delimiter_pages", return_value={2, 3}):
                    report = audit_scan_separator_pages(db, store_dir=store)
                    applied = audit_scan_separator_pages(db, store_dir=store, apply=True, actor="scan_test")
                overrides = db.query(
                    """
                    select asset_id, axis_value, actor, note
                    from asset_overrides
                    where axis_name='track' and operation='set'
                    order by asset_id asc
                    """
                )

            self.assertEqual(report["candidate_pages"], 2)
            self.assertEqual(applied["applied_irrelevant_overrides"], 2)
            self.assertEqual(
                [str(row["asset_id"]) for row in overrides],
                ["asset-p2", "asset-p3"],
            )
            self.assertTrue(all(str(row["axis_value"]) == "irrelevant" for row in overrides))
            self.assertTrue(all(str(row["actor"]) == "scan_test" for row in overrides))

    def test_repair_scan_document_grouping_uses_delimiters_and_irrelevant_pages(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            store = base / "store"
            pdf_dir = store / "originals" / "scan"
            pdf_dir.mkdir(parents=True)
            sha = "b" * 64
            pdf = pdf_dir / f"{sha}.pdf"
            pdf.write_text("%PDF-1.4 mock")

            db_path = base / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                rows = []
                for idx, title in [
                    (1, "Kitchen cover story - doc 1"),
                    (2, "Kitchen spread - doc 2"),
                    (3, "Book Mar 4, 2026 - doc 3"),
                    (4, "Range detail - doc 4"),
                    (5, "Book Mar 4, 2026 - doc 5"),
                    (6, "Kitchen island detail - doc 6"),
                ]:
                    rows.append(
                        (
                            f"asset-{idx}",
                            "scan",
                            f"scan://{sha}#p{idx}",
                            title,
                            "2026-03-22T00:00:00+00:00",
                            f"/tmp/page-{idx}.jpg",
                            f"/tmp/page-{idx}.jpg",
                            sha,
                            "image",
                            "scan",
                        )
                    )
                db.executemany(
                    """
                    insert into assets
                      (id, source, source_ref, title, imported_at, image_url, stored_path, sha256, media_status, content_kind)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
                db.exec(
                    """
                    insert into asset_overrides
                      (id, asset_id, track, axis_name, axis_value, operation, actor, note, created_at, expires_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "ovr-5",
                        "asset-5",
                        "irrelevant",
                        "track",
                        "irrelevant",
                        "set",
                        "Jim",
                        "exclude ad page",
                        "2026-03-22T00:00:00+00:00",
                        None,
                    ),
                )
                with mock.patch("inspirations.importers.scans._select_pdf_renderer", return_value="pdftoppm"), \
                     mock.patch("inspirations.importers.scans._detect_pdf_delimiter_pages", return_value={3}):
                    preview = repair_scan_document_grouping(db, store_dir=store, pdf_sha256=sha, apply=False)
                    applied = repair_scan_document_grouping(db, store_dir=store, pdf_sha256=sha, apply=True)
                titles = {
                    str(r["source_ref"]): str(r["title"])
                    for r in db.query("select source_ref, title from assets where source='scan' order by source_ref asc")
                }

            self.assertEqual(preview["delimiter_pages"], [3])
            self.assertEqual(preview["excluded_pages"], [5])
            self.assertEqual(
                [doc["pages"] for doc in preview["documents"]],
                [[1, 2], [4], [6]],
            )
            self.assertEqual(
                titles[f"scan://{sha}#p1"],
                "Kitchen cover story - doc 1 p1",
            )
            self.assertEqual(
                titles[f"scan://{sha}#p2"],
                "Kitchen cover story - doc 1 p2",
            )
            self.assertEqual(
                titles[f"scan://{sha}#p4"],
                "Range detail - doc 2",
            )
            self.assertEqual(
                titles[f"scan://{sha}#p5"],
                "Book Mar 4, 2026 - doc 5",
            )
            self.assertEqual(
                titles[f"scan://{sha}#p6"],
                "Kitchen island detail - doc 3",
            )
            self.assertTrue(applied["apply"])

    def test_purge_scan_separator_pages_deletes_assets_and_files(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            store = base / "store"
            pdf_dir = store / "originals" / "scan"
            pages_dir = store / "pages" / "scan" / ("c" * 64)
            pdf_dir.mkdir(parents=True)
            pages_dir.mkdir(parents=True)
            sha = "c" * 64
            pdf = pdf_dir / f"{sha}.pdf"
            pdf.write_text("%PDF-1.4 mock")
            page2 = pages_dir / "page-2.jpg"
            page3 = pages_dir / "page-3.jpg"
            page2.write_bytes(b"p2")
            page3.write_bytes(b"p3")

            db_path = base / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.executemany(
                    """
                    insert into assets
                      (id, source, source_ref, title, imported_at, image_url, stored_path, sha256, media_status, content_kind)
                    values (?, 'scan', ?, ?, '2026-03-22T00:00:00+00:00', ?, ?, ?, 'image', 'scan')
                    """,
                    [
                        ("asset-p1", f"scan://{sha}#p1", "batch - doc 1", str(page2), str(page2), sha),
                        ("asset-p2", f"scan://{sha}#p2", "blank separator - doc 2", str(page2), str(page2), sha),
                        ("asset-p3", f"scan://{sha}#p3", "blank separator - doc 3", str(page3), str(page3), sha),
                    ],
                )
                db.exec(
                    """
                    insert into collections (id, name, created_at, updated_at, hidden)
                    values (?, ?, '2026-03-22T00:00:00+00:00', '2026-03-22T00:00:00+00:00', 0)
                    """,
                    ("col-1", "Test Collection"),
                )
                db.exec(
                    """
                    insert into collection_items (collection_id, asset_id, position)
                    values (?, ?, 1)
                    """,
                    ("col-1", "asset-p2"),
                )
                with mock.patch("inspirations.importers.scans._select_pdf_renderer", return_value="pdftoppm"), \
                     mock.patch("inspirations.importers.scans._detect_pdf_delimiter_pages", return_value={2, 3}):
                    report = purge_scan_separator_pages(db, store_dir=store, pdf_sha256s=[sha], apply=True)
                remaining = [str(r["id"]) for r in db.query("select id from assets order by id asc")]

            self.assertEqual(report["deleted_assets"], 2)
            self.assertEqual(remaining, ["asset-p1"])
            self.assertFalse(page2.exists())
            self.assertFalse(page3.exists())

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
