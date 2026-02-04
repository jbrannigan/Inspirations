import base64
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from inspirations.db import Db, ensure_schema
from inspirations.importers.scans import import_scans_inbox


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
            self.assertGreaterEqual(report2["created_assets"], 1)

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


if __name__ == "__main__":
    unittest.main()
