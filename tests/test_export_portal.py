import base64
import json
import os
import tempfile
import unittest
from pathlib import Path

from inspirations.db import Db, ensure_schema
from inspirations.export import PORTAL_EMBED_PREVIEW_MAX_ITEMS, export_static_share_portal
from inspirations.store import add_items_to_collection, create_collection


TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="
)


def _portal_data(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    marker = '<script id="portal-data" type="application/json">'
    start = text.index(marker) + len(marker)
    end = text.index("</script>", start)
    return json.loads(text[start:end])


class TestExportPortal(unittest.TestCase):
    def test_portal_export_has_semantic_disabled_and_excludes_hidden_by_default(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / "t.sqlite"
            out = root / "portal.html"
            thumb = root / "thumb.png"
            thumb.write_bytes(TINY_PNG)
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, imported_at, thumb_path)
                    values (?, ?, ?, ?, datetime('now'), ?)
                    """,
                    ("a1", "pinterest", "https://example.com/pin/1", "Kitchen Idea", str(thumb)),
                )
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, imported_at, image_url)
                    values (?, ?, ?, ?, datetime('now'), ?)
                    """,
                    ("a2", "facebook", "https://example.com/post/2", "Cabinet Mood", "https://img.example.com/x.jpg"),
                )
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, imported_at)
                    values (?, ?, ?, ?, datetime('now'))
                    """,
                    ("a3", "facebook", "https://example.com/post/3", "Hidden Asset"),
                )
                db.exec(
                    """
                    insert into asset_labels (id, asset_id, label, source, created_at)
                    values (?, ?, ?, ?, datetime('now'))
                    """,
                    ("l1", "a1", "oak kitchen", "gemini"),
                )
                kitchen = create_collection(db, name="Kitchen")
                hidden = create_collection(db, name="Hidden")
                add_items_to_collection(db, collection_id=kitchen["id"], asset_ids=["a1", "a2"])
                add_items_to_collection(db, collection_id=hidden["id"], asset_ids=["a3"])
                report = export_static_share_portal(db, out_path=out, title="Share Portal")

            self.assertTrue(out.exists())
            text = out.read_text(encoding="utf-8")
            self.assertEqual(report["exported_assets"], 2)
            self.assertEqual(report["semantic_enabled"], False)
            self.assertEqual(report["preview_mode"], "embedded")
            self.assertEqual(report["linked_previews"], 0)
            self.assertIn('"semantic_enabled": false', text)
            self.assertIn("Semantic search is not available in shared view", text)
            self.assertNotIn("/api/search/similar", text)
            self.assertIn('id="viewGraph"', text)
            self.assertIn('id="mediaFilters"', text)
            self.assertIn('id="showMoreBtn"', text)
            self.assertIn('id="graphControls"', text)
            self.assertIn('id="graphSimilarity"', text)
            self.assertIn('id="graphMaxNodes"', text)
            self.assertIn('pointerdown', text)
            self.assertIn("Kitchen Idea", text)
            self.assertIn("Cabinet Mood", text)
            self.assertNotIn("Hidden Asset", text)
            self.assertIn("oak kitchen", text)

    def test_portal_export_collection_filter(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / "t.sqlite"
            out = root / "portal.html"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    "insert into assets (id, source, source_ref, title, imported_at) values (?, ?, ?, ?, datetime('now'))",
                    ("a1", "pinterest", "https://example.com/1", "One"),
                )
                db.exec(
                    "insert into assets (id, source, source_ref, title, imported_at) values (?, ?, ?, ?, datetime('now'))",
                    ("a2", "pinterest", "https://example.com/2", "Two"),
                )
                c1 = create_collection(db, name="C1")
                c2 = create_collection(db, name="C2")
                add_items_to_collection(db, collection_id=c1["id"], asset_ids=["a1"])
                add_items_to_collection(db, collection_id=c2["id"], asset_ids=["a2"])
                report = export_static_share_portal(
                    db,
                    out_path=out,
                    collection_ids=[c2["id"]],
                )
            self.assertEqual(report["exported_assets"], 1)
            text = out.read_text(encoding="utf-8")
            self.assertIn("Two", text)
            self.assertNotIn("One", text)

    def test_portal_export_can_include_unassigned(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / "t.sqlite"
            out_default = root / "portal_default.html"
            out_all = root / "portal_all.html"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    "insert into assets (id, source, source_ref, title, imported_at, media_status) values (?, ?, ?, ?, datetime('now'), ?)",
                    ("a1", "pinterest", "https://example.com/1", "In Collection", "image"),
                )
                db.exec(
                    "insert into assets (id, source, source_ref, title, imported_at, media_status) values (?, ?, ?, ?, datetime('now'), ?)",
                    ("a2", "scan", "scan://2", "Unassigned", "image"),
                )
                c1 = create_collection(db, name="C1")
                add_items_to_collection(db, collection_id=c1["id"], asset_ids=["a1"])
                report_default = export_static_share_portal(db, out_path=out_default)
                report_all = export_static_share_portal(db, out_path=out_all, include_unassigned=True)
            self.assertEqual(report_default["exported_assets"], 1)
            self.assertEqual(report_default["include_unassigned"], False)
            self.assertEqual(report_all["exported_assets"], 2)
            self.assertEqual(report_all["include_unassigned"], True)
            self.assertIn("In Collection", out_default.read_text(encoding="utf-8"))
            self.assertNotIn("scan://2", out_default.read_text(encoding="utf-8"))
            self.assertIn("scan://2", out_all.read_text(encoding="utf-8"))

    def test_portal_export_detail_prefers_stored_media_over_thumb(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db_path = root / "t.sqlite"
            out = root / "portal_detail.html"
            thumb = root / "thumb.png"
            stored = root / "stored.jpg"
            thumb.write_bytes(TINY_PNG)
            stored.write_bytes(TINY_PNG)
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, imported_at, thumb_path, stored_path, media_status, content_kind)
                    values (?, ?, ?, ?, datetime('now'), ?, ?, ?, ?)
                    """,
                    (
                        "a1",
                        "pinterest",
                        "https://example.com/1",
                        "Stored Preferred",
                        str(thumb),
                        str(stored),
                        "image",
                        "pin",
                    ),
                )
                c1 = create_collection(db, name="C1")
                add_items_to_collection(db, collection_id=c1["id"], asset_ids=["a1"])
                report = export_static_share_portal(db, out_path=out)
            self.assertEqual(report["exported_assets"], 1)
            payload = _portal_data(out)
            item = next((x for x in payload.get("items", []) if x.get("id") == "a1"), None)
            self.assertIsNotNone(item)
            self.assertTrue(str(item.get("preview_src") or "").startswith("data:image/png"))
            self.assertTrue(str(item.get("detail_src") or "").startswith("data:image/jpeg"))
            self.assertNotEqual(item.get("detail_src"), item.get("preview_src"))

    def test_portal_export_uses_linked_previews_for_large_exports(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as td:
            root = Path(td)
            db_path = root / "t.sqlite"
            out = root / "portal_large.html"
            thumb = root / "thumb.png"
            thumb.write_bytes(TINY_PNG)
            total = PORTAL_EMBED_PREVIEW_MAX_ITEMS + 1
            with Db(db_path) as db:
                ensure_schema(db)
                collection = create_collection(db, name="Large Set")
                ids = []
                for idx in range(total):
                    asset_id = f"a{idx}"
                    ids.append(asset_id)
                    db.exec(
                        """
                        insert into assets (id, source, source_ref, title, imported_at, thumb_path)
                        values (?, ?, ?, ?, datetime('now'), ?)
                        """,
                        (
                            asset_id,
                            "pinterest",
                            f"https://example.com/pin/{idx}",
                            f"Idea {idx}",
                            str(thumb),
                        ),
                    )
                add_items_to_collection(db, collection_id=collection["id"], asset_ids=ids)
                report = export_static_share_portal(db, out_path=out)

            text = out.read_text(encoding="utf-8")
            self.assertEqual(report["exported_assets"], total)
            self.assertEqual(report["preview_mode"], "linked")
            self.assertGreater(report["linked_previews"], 0)
            self.assertNotIn("data:image/", text)
            self.assertIn("portal_large_media/", text)

    def test_portal_export_scan_item_has_detail_and_pdf_metadata(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as td:
            root = Path(td)
            db_path = root / "t.sqlite"
            out = root / "portal_scan.html"
            thumb = root / "thumb.png"
            page1 = root / "page1.jpg"
            page2 = root / "page2.jpg"
            thumb.write_bytes(TINY_PNG)
            page1.write_bytes(TINY_PNG)
            page2.write_bytes(TINY_PNG)
            sha = "a" * 64
            pdf_dir = root / "store" / "originals" / "scan"
            pdf_dir.mkdir(parents=True, exist_ok=True)
            (pdf_dir / f"{sha}.pdf").write_bytes(b"%PDF-1.3\n%%EOF\n")

            old_cwd = Path.cwd()
            os.chdir(root)
            try:
                with Db(db_path) as db:
                    ensure_schema(db)
                    db.exec(
                        """
                        insert into assets (id, source, source_ref, title, imported_at, thumb_path, stored_path, media_status, content_kind)
                        values (?, ?, ?, ?, datetime('now'), ?, ?, ?, ?)
                        """,
                        (
                            "s1",
                            "scan",
                            f"scan://{sha}#p1",
                            "Scan Demo - doc 1 p1",
                            str(thumb),
                            str(page1),
                            "image",
                            "scan",
                        ),
                    )
                    db.exec(
                        """
                        insert into assets (id, source, source_ref, title, imported_at, thumb_path, stored_path, media_status, content_kind)
                        values (?, ?, ?, ?, datetime('now'), ?, ?, ?, ?)
                        """,
                        (
                            "s2",
                            "scan",
                            f"scan://{sha}#p2",
                            "Scan Demo - doc 1 p2",
                            str(thumb),
                            str(page2),
                            "image",
                            "scan",
                        ),
                    )
                    c1 = create_collection(db, name="Scans")
                    add_items_to_collection(db, collection_id=c1["id"], asset_ids=["s1", "s2"])
                    report = export_static_share_portal(db, out_path=out)
            finally:
                os.chdir(old_cwd)

            self.assertEqual(report["exported_assets"], 2)
            payload = _portal_data(out)
            item = next((x for x in payload.get("items", []) if x.get("id") == "s1"), None)
            self.assertIsNotNone(item)
            self.assertEqual(item.get("scan_doc_pages"), 2)
            self.assertEqual(item.get("scan_doc_page"), 1)
            self.assertIn("portal_scan_docs/", str(item.get("scan_pdf_src") or ""))
            self.assertTrue(str(item.get("detail_src") or "").startswith("data:image/"))
            self.assertNotEqual(item.get("detail_src"), item.get("preview_src"))


if __name__ == "__main__":
    unittest.main()
