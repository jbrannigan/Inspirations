import base64
import tempfile
import unittest
from pathlib import Path

from inspirations.db import Db, ensure_schema
from inspirations.export import export_html_gallery
from inspirations.store import add_items_to_collection, create_collection


TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="
)


class TestExportHtml(unittest.TestCase):
    def test_export_html_gallery_counts_and_output(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / "t.sqlite"
            thumb = root / "thumb.png"
            thumb.write_bytes(TINY_PNG)
            out = root / "export" / "gallery.html"

            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, imported_at, thumb_path)
                    values (?, ?, ?, ?, datetime('now'), ?)
                    """,
                    ("a1", "pinterest", "pin://1", "Local thumb", str(thumb)),
                )
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, imported_at, image_url)
                    values (?, ?, ?, ?, datetime('now'), ?)
                    """,
                    ("a2", "facebook", "https://example.com/p/2", "Remote image", "https://img.example.com/p.jpg"),
                )
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, imported_at)
                    values (?, ?, ?, ?, datetime('now'))
                    """,
                    ("a3", "facebook", "facebook://saved/3", "No preview"),
                )
                report = export_html_gallery(db, out_path=out)

            self.assertTrue(out.exists())
            text = out.read_text(encoding="utf-8")
            self.assertIn("Local thumb", text)
            self.assertIn("Remote image", text)
            self.assertIn("No preview", text)
            self.assertIn("Show Details", text)
            self.assertIn("How to save this idea", text)
            self.assertEqual(report["exported_assets"], 3)
            self.assertEqual(report["embedded_previews"], 1)
            self.assertEqual(report["remote_previews"], 1)
            self.assertEqual(report["no_preview"], 1)

    def test_export_html_gallery_collection_filter(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / "t.sqlite"
            out = root / "gallery.html"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    "insert into assets (id, source, source_ref, title, imported_at) values (?, ?, ?, ?, datetime('now'))",
                    ("a1", "pinterest", "pin://1", "One"),
                )
                db.exec(
                    "insert into assets (id, source, source_ref, title, imported_at) values (?, ?, ?, ?, datetime('now'))",
                    ("a2", "pinterest", "pin://2", "Two"),
                )
                col = create_collection(db, name="Kitchen")
                add_items_to_collection(db, collection_id=col["id"], asset_ids=["a1"])
                report = export_html_gallery(db, out_path=out, collection_id=col["id"])

            self.assertEqual(report["exported_assets"], 1)
            text = out.read_text(encoding="utf-8")
            self.assertIn("One", text)
            self.assertNotIn("Two", text)

    def test_export_html_gallery_details_modal_without_ai_summary(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / "t.sqlite"
            out = root / "gallery.html"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, description, ai_summary, imported_at)
                    values (?, ?, ?, ?, ?, ?, datetime('now'))
                    """,
                    (
                        "a1",
                        "facebook",
                        "https://example.com/post/1",
                        "Stoffer Home Cabinetry's post.",
                        "Fallback description text",
                        "Generated AI summary text",
                    ),
                )
                db.exec(
                    """
                    insert into annotations (id, asset_id, x, y, text, created_at, updated_at)
                    values (?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                    """,
                    ("ann-1", "a1", 0.42, 0.66, "Pendant spacing reference"),
                )
                report = export_html_gallery(db, out_path=out)

            self.assertEqual(report["exported_assets"], 1)
            text = out.read_text(encoding="utf-8")
            self.assertIn("Show Details", text)
            self.assertIn("Open Source", text)
            self.assertIn("1 note", text)
            self.assertIn("Pendant spacing reference", text)
            self.assertNotIn("Generated AI summary text", text)
            self.assertNotIn("Fallback description text", text)


if __name__ == "__main__":
    unittest.main()
