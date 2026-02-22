from __future__ import annotations

import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from inspirations.db import Db, ensure_schema
from inspirations.importers.facebook_docx import import_facebook_docx


# ─── Helpers to build synthetic DOCX ────────────────────────────────────────

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_R_OFF = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_PIC = "http://schemas.openxmlformats.org/drawingml/2006/picture"
_WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"

ET.register_namespace("w", _W)
ET.register_namespace("r", _R_OFF)
ET.register_namespace("a", _A)
ET.register_namespace("pic", _PIC)
ET.register_namespace("wp", _WP)


def _w(tag: str) -> str:
    return f"{{{_W}}}{tag}"


def _r(tag: str) -> str:
    return f"{{{_R_OFF}}}{tag}"


def _a(tag: str) -> str:
    return f"{{{_A}}}{tag}"


def _pic(tag: str) -> str:
    return f"{{{_PIC}}}{tag}"


def _make_text_para(text: str) -> ET.Element:
    p = ET.Element(_w("p"))
    r = ET.SubElement(p, _w("r"))
    t = ET.SubElement(r, _w("t"))
    t.text = text
    return p


def _make_hyperlink_para(text: str, rid: str) -> ET.Element:
    p = ET.Element(_w("p"))
    hl = ET.SubElement(p, _w("hyperlink"))
    hl.set(f"{{{_R_OFF}}}id", rid)
    r = ET.SubElement(hl, _w("r"))
    t = ET.SubElement(r, _w("t"))
    t.text = text
    return p


def _make_image_and_title_para(text: str, title_rid: str, img_rid: str) -> ET.Element:
    """Paragraph with both a hyperlink title and an embedded image."""
    p = ET.Element(_w("p"))
    # Hyperlink
    hl = ET.SubElement(p, _w("hyperlink"))
    hl.set(f"{{{_R_OFF}}}id", title_rid)
    r = ET.SubElement(hl, _w("r"))
    t = ET.SubElement(r, _w("t"))
    t.text = text
    # Drawing with blip
    drawing = ET.SubElement(p, _w("drawing"))
    inline = ET.SubElement(drawing, f"{{{_WP}}}inline")
    graphic = ET.SubElement(inline, f"{{{_A}}}graphic")
    gd = ET.SubElement(graphic, f"{{{_A}}}graphicData")
    pic_el = ET.SubElement(gd, f"{{{_PIC}}}pic")
    bf = ET.SubElement(pic_el, f"{{{_PIC}}}blipFill")
    blip = ET.SubElement(bf, f"{{{_A}}}blip")
    blip.set(f"{{{_R_OFF}}}embed", img_rid)
    return p


def _build_document_xml(entries: list[dict]) -> bytes:
    """Build word/document.xml from a list of entry spec dicts.

    Each dict may have:
      title, title_rid, img_rid, content_type, collection, saved_from, duration
    """
    root = ET.Element(_w("document"))
    body = ET.SubElement(root, _w("body"))

    for e in entries:
        # Optional duration line
        if e.get("duration"):
            body.append(_make_text_para(e["duration"]))

        # Title line (with hyperlink and optionally image)
        if e.get("img_rid"):
            body.append(
                _make_image_and_title_para(e["title"], e["title_rid"], e["img_rid"])
            )
        else:
            body.append(_make_hyperlink_para(e["title"], e["title_rid"]))

        # "Saved to" line
        content_type = e.get("content_type", "Post")
        collection = e.get("collection", "kitchen")
        body.append(_make_text_para(f"{content_type} • Saved to {collection}"))

        # "Saved from" line
        saved_from = e.get("saved_from", "Some Creator")
        body.append(_make_text_para(f"Saved from {saved_from}'s post"))

    return ET.tostring(root, encoding="unicode").encode("utf-8")


def _build_rels_xml(hyperlinks: dict[str, str], images: dict[str, str]) -> bytes:
    """Build word/_rels/document.xml.rels."""
    rels_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    root = ET.Element(f"{{{rels_ns}}}Relationships")
    hl_type = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"
    img_type = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
    for rid, url in hyperlinks.items():
        rel = ET.SubElement(root, f"{{{rels_ns}}}Relationship")
        rel.set("Id", rid)
        rel.set("Type", hl_type)
        rel.set("Target", url)
        rel.set("TargetMode", "External")
    for rid, path in images.items():
        rel = ET.SubElement(root, f"{{{rels_ns}}}Relationship")
        rel.set("Id", rid)
        rel.set("Type", img_type)
        rel.set("Target", path)
    return ET.tostring(root, encoding="unicode").encode("utf-8")


# Minimal valid JPEG bytes (9-byte JPEG)
_FAKE_JPEG = bytes(
    [0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46, 0x00, 0x01, 0xFF, 0xD9]
)
# Second fake JPEG (different content = different sha256)
_FAKE_JPEG2 = bytes(
    [0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x47, 0x00, 0x02, 0xFF, 0xD9]
)


def _make_docx(path: Path, entries: list[dict]) -> None:
    """Write a synthetic DOCX ZIP with the given entries."""
    # Collect all rIds
    hyperlinks: dict[str, str] = {}
    images: dict[str, str] = {}
    image_data: dict[str, bytes] = {}

    for e in entries:
        rid = e["title_rid"]
        url = e.get("url", f"https://www.facebook.com/reel/{rid}")
        hyperlinks[rid] = url
        if e.get("img_rid"):
            img_rid = e["img_rid"]
            img_filename = f"media/image_{img_rid}.jpeg"
            images[img_rid] = img_filename
            image_data[img_rid] = e.get("img_bytes", _FAKE_JPEG)

    doc_xml = _build_document_xml(entries)
    rels_xml = _build_rels_xml(hyperlinks, images)

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", doc_xml)
        z.writestr("word/_rels/document.xml.rels", rels_xml)
        for img_rid, img_bytes in image_data.items():
            img_filename = f"media/image_{img_rid}.jpeg"
            z.writestr(f"word/{img_filename}", img_bytes)


# ─── Tests ────────────────────────────────────────────────────────────────────


class TestFacebookDocxImport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.td = Path(self.tmp.name)
        self.db_path = self.td / "test.sqlite"
        self.store_dir = self.td / "store"
        self.store_dir.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, docx_path: Path, collections_filter: str = "home-design") -> dict:
        with Db(self.db_path) as db:
            ensure_schema(db)
            return import_facebook_docx(
                db=db,
                docx_path=docx_path,
                store_dir=self.store_dir,
                collections_filter=collections_filter,
            )

    def _query(self, sql: str, params: tuple = ()) -> list:
        with Db(self.db_path) as db:
            ensure_schema(db)
            return db.query(sql, params)

    def test_entry_parsing_title_url_collection_creator(self):
        entries = [
            {
                "title": "Beautiful Kitchen Remodel",
                "title_rid": "rId10",
                "url": "https://www.facebook.com/reel/12345",
                "content_type": "Reels",
                "collection": "kitchen",
                "saved_from": "Home Design Daily",
            }
        ]
        docx = self.td / "test.docx"
        _make_docx(docx, entries)
        report = self._run(docx)

        self.assertEqual(report["total_entries_parsed"], 1)
        self.assertEqual(report["filtered_home_design"], 1)
        self.assertEqual(report["imported_assets"], 1)

        rows = self._query("select title, source_ref, board, content_kind, creator_name from assets where source='facebook'")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["title"], "Beautiful Kitchen Remodel")
        self.assertEqual(row["source_ref"], "https://www.facebook.com/reel/12345")
        self.assertEqual(row["board"], "kitchen")
        self.assertEqual(row["content_kind"], "reel")
        self.assertEqual(row["creator_name"], "Home Design Daily")

    def test_collection_filtering_home_design_passes_recipe_skipped(self):
        entries = [
            {
                "title": "Kitchen Cabinets",
                "title_rid": "rId1",
                "content_type": "Post",
                "collection": "kitchen",
                "saved_from": "Designer A",
            },
            {
                "title": "Pasta Recipe",
                "title_rid": "rId2",
                "content_type": "Reels",
                "collection": "recipe",
                "saved_from": "Chef B",
            },
            {
                "title": "Workout Video",
                "title_rid": "rId3",
                "content_type": "Reels",
                "collection": "exercise",
                "saved_from": "Trainer C",
            },
        ]
        docx = self.td / "test.docx"
        _make_docx(docx, entries)
        report = self._run(docx, collections_filter="home-design")

        self.assertEqual(report["total_entries_parsed"], 3)
        self.assertEqual(report["filtered_home_design"], 1)
        self.assertEqual(report["imported_assets"], 1)

        rows = self._query("select title from assets where source='facebook'")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "Kitchen Cabinets")

    def test_collection_filter_all_imports_everything(self):
        entries = [
            {
                "title": "Kitchen Cabinets",
                "title_rid": "rId1",
                "content_type": "Post",
                "collection": "kitchen",
                "saved_from": "Designer A",
            },
            {
                "title": "Pasta Recipe",
                "title_rid": "rId2",
                "content_type": "Reels",
                "collection": "recipe",
                "saved_from": "Chef B",
            },
        ]
        docx = self.td / "test.docx"
        _make_docx(docx, entries)
        report = self._run(docx, collections_filter="all")
        self.assertEqual(report["imported_assets"], 2)

    def test_image_extracted_saved_to_store(self):
        entries = [
            {
                "title": "Open Floor Plan",
                "title_rid": "rId20",
                "img_rid": "rId21",
                "img_bytes": _FAKE_JPEG,
                "content_type": "Post",
                "collection": "floor plans",
                "saved_from": "Architect Y",
            }
        ]
        docx = self.td / "test.docx"
        _make_docx(docx, entries)
        report = self._run(docx)

        self.assertEqual(report["images_extracted"], 1)
        self.assertEqual(report["metadata_only"], 0)

        rows = self._query("select stored_path, sha256, media_status from assets where source='facebook'")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["media_status"], "image")
        self.assertIsNotNone(row["stored_path"])
        self.assertIsNotNone(row["sha256"])
        # File should exist on disk
        self.assertTrue(Path(row["stored_path"]).exists())
        # File name should be sha256.jpg
        fname = Path(row["stored_path"]).name
        self.assertEqual(fname, f"{row['sha256']}.jpg")

    def test_dedup_idempotent(self):
        entries = [
            {
                "title": "Bathroom Tile Ideas",
                "title_rid": "rId30",
                "url": "https://www.facebook.com/post/999",
                "img_rid": "rId31",
                "img_bytes": _FAKE_JPEG,
                "content_type": "Post",
                "collection": "bathroom",
                "saved_from": "Tile World",
            }
        ]
        docx = self.td / "test.docx"
        _make_docx(docx, entries)

        report1 = self._run(docx)
        report2 = self._run(docx)

        self.assertEqual(report1["imported_assets"], 1)
        self.assertEqual(report2["imported_assets"], 0)
        self.assertEqual(report2["existing_assets"], 1)

        rows = self._query("select count(*) as n from assets where source='facebook'")
        self.assertEqual(rows[0]["n"], 1)

    def test_collection_suffix_stripping(self):
        entries = [
            {
                "title": "Cabinet Hardware",
                "title_rid": "rId40",
                "content_type": "Post",
                "collection": "kitchen 2 + 1 other",
                "saved_from": "Hardware Store",
            },
            {
                "title": "Paint Colors",
                "title_rid": "rId41",
                "content_type": "Post",
                "collection": "paint + 2 other",
                "saved_from": "Paint Brand",
            },
        ]
        docx = self.td / "test.docx"
        _make_docx(docx, entries)
        report = self._run(docx, collections_filter="home-design")

        # "kitchen 2" is NOT in HOME_DESIGN_COLLECTIONS (only "kitchen" is)
        # "paint" IS — the suffix is stripped to "paint"
        self.assertEqual(report["filtered_home_design"], 1)
        rows = self._query("select board from assets where source='facebook'")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["board"], "paint")

    def test_no_url_falls_back_to_hash(self):
        entries = [
            {
                "title": "Lighting Ideas",
                "title_rid": "rId50",
                # No URL in rels — just a text link without a valid http URL
                "content_type": "Post",
                "collection": "lighting",
                "saved_from": "Lamp Shop",
            }
        ]
        # Override _make_docx to not put any URL in rels for this entry
        # (the make_docx helper uses rId as fallback URL, so let's manually build)
        doc_xml = _build_document_xml(entries)
        rels_xml = _build_rels_xml({}, {})  # empty hyperlinks dict → no URL
        docx = self.td / "nurl.docx"
        with zipfile.ZipFile(docx, "w") as z:
            z.writestr("word/document.xml", doc_xml)
            z.writestr("word/_rels/document.xml.rels", rels_xml)

        report = self._run(docx)
        self.assertEqual(report["imported_assets"], 1)

        rows = self._query("select source_ref from assets where source='facebook'")
        self.assertEqual(len(rows), 1)
        # Should be a hex sha256, not a URL
        ref = rows[0]["source_ref"]
        self.assertFalse(ref.startswith("http"), f"Expected hash, got: {ref}")
        self.assertEqual(len(ref), 64)

    def test_content_kind_mapping(self):
        entries = [
            {
                "title": "A Reel",
                "title_rid": "rId60",
                "content_type": "Reels",
                "collection": "kitchen",
                "saved_from": "Creator A",
            },
            {
                "title": "A Post",
                "title_rid": "rId61",
                "content_type": "Post",
                "collection": "kitchen",
                "saved_from": "Creator B",
            },
            {
                "title": "A Link",
                "title_rid": "rId62",
                "content_type": "Link",
                "collection": "kitchen",
                "saved_from": "Creator C",
            },
        ]
        docx = self.td / "kinds.docx"
        _make_docx(docx, entries)
        report = self._run(docx)

        self.assertEqual(report["imported_assets"], 3)
        self.assertEqual(report["content_kind_counts"].get("reel", 0), 1)
        self.assertEqual(report["content_kind_counts"].get("post", 0), 1)
        self.assertEqual(report["content_kind_counts"].get("link", 0), 1)


if __name__ == "__main__":
    unittest.main()
