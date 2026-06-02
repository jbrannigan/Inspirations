import shutil
import subprocess
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

from inspirations.db import Db, ensure_schema
from inspirations.export import PdfRenderError, PdfToolUnavailableError, export_collection_pdf

def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def _solid_png_bytes(width: int = 8, height: int = 8) -> bytes:
    raw = b"".join([b"\x00" + (b"\xf5\xef\xe2" * width) for _ in range(height)])
    return b"\x89PNG\r\n\x1a\n" + b"".join([
        _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)),
        _png_chunk(b"IDAT", zlib.compress(raw)),
        _png_chunk(b"IEND", b""),
    ])


VALID_PNG_BYTES = _solid_png_bytes()


class TestCollectionPdfExport(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.db_path = self.tmp_path / "t.sqlite"
        self.store_dir = self.tmp_path / "store"
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.img1 = self.store_dir / "a1.png"
        self.img2 = self.store_dir / "a2.png"
        self.img_hidden = self.store_dir / "hidden.png"
        for path in (self.img1, self.img2, self.img_hidden):
            path.write_bytes(VALID_PNG_BYTES)

        with Db(self.db_path) as db:
            ensure_schema(db)
            self._insert_asset(
                db,
                asset_id="a1",
                title="First Item",
                source_url="https://example.com/source-one",
                source_ref="https://fallback.example/one",
                stored_path=self.img1,
            )
            self._insert_asset(
                db,
                asset_id="a2",
                title="Second Item",
                source_url="http://127.0.0.1:8001/media/a2",
                source_ref="https://example.com/source-two",
                stored_path=self.img2,
            )
            self._insert_asset(
                db,
                asset_id="a3",
                title="Other Collection Item",
                source_url="https://example.com/other",
                source_ref="",
                stored_path=None,
            )
            self._insert_asset(
                db,
                asset_id="a4",
                title="Hidden Item",
                source_url="https://example.com/hidden",
                source_ref="",
                stored_path=self.img_hidden,
                triage_status="hidden",
            )
            self._insert_asset(
                db,
                asset_id="a5",
                title="No Source Item",
                source_url="http://192.168.0.101:8001/media/a5",
                source_ref="scan://abc",
                stored_path=None,
            )
            db.exec(
                """
                insert into collections (id, name, description, created_at, updated_at)
                values (?, ?, ?, datetime('now'), datetime('now'))
                """,
                ("c1", "Kitchen Ideas", "Designer handoff collection"),
            )
            db.exec(
                """
                insert into collections (id, name, description, created_at, updated_at)
                values (?, ?, ?, datetime('now'), datetime('now'))
                """,
                ("c2", "Other", ""),
            )
            db.exec(
                """
                insert into collections (id, name, description, created_at, updated_at)
                values (?, ?, ?, datetime('now'), datetime('now'))
                """,
                ("hidden-col", "Hidden", ""),
            )
            for pos, aid in enumerate(("a2", "a1", "a5", "a4"), start=1):
                db.exec(
                    "insert into collection_items (collection_id, asset_id, position) values (?, ?, ?)",
                    ("c1", aid, pos),
                )
            db.exec(
                "insert into collection_items (collection_id, asset_id, position) values (?, ?, ?)",
                ("c2", "a3", 1),
            )
            db.exec(
                "insert into collection_items (collection_id, asset_id, position) values (?, ?, ?)",
                ("hidden-col", "a4", 1),
            )
            db.exec(
                """
                insert into annotations (id, asset_id, x, y, text, created_at, updated_at)
                values (?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                """,
                ("ann-a1", "a1", 0.25, 0.75, "Check backsplash detail",),
            )
            db.executemany(
                """
                insert into asset_labels (id, asset_id, label, source, created_at)
                values (?, ?, ?, 'ai', datetime('now'))
                """,
                [
                    (f"label-{idx}", "a1", label)
                    for idx, label in enumerate(
                        (
                            "backsplash",
                            "beige",
                            "cabinetry",
                            "ceramic tile",
                            "countertop",
                            "farmhouse",
                            "interior",
                            "kitchen",
                            "marble",
                            "oak",
                            "shelving",
                            "storage",
                            "warm",
                        ),
                        start=1,
                    )
                ],
            )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _insert_asset(
        self,
        db: Db,
        *,
        asset_id: str,
        title: str,
        source_url: str,
        source_ref: str,
        stored_path: Path | None,
        triage_status: str | None = None,
    ) -> None:
        db.exec(
            """
            insert into assets
              (id, source, source_ref, source_url, title, imported_at, stored_path, triage_status)
            values (?, ?, ?, ?, ?, datetime('now'), ?, ?)
            """,
            (asset_id, "pinterest", source_ref or f"pin://{asset_id}", source_url, title, str(stored_path or ""), triage_status),
        )

    def test_collection_pdf_markdown_scopes_order_media_and_links(self):
        out_path = self.tmp_path / "exports" / "kitchen.pdf"
        with Db(self.db_path) as db:
            ensure_schema(db)
            report = export_collection_pdf(db, collection_id="c1", out_path=out_path, render_pdf=False)

        md_path = Path(report["markdown_path"])
        text = md_path.read_text(encoding="utf-8")
        self.assertEqual(report["exported_assets"], 3)
        self.assertEqual(report["rendered_pdf"], False)
        self.assertIn(r"\begin{titlepage}", text)
        self.assertIn("INSPIRATIONS", text)
        self.assertLess(text.index("ITEM 1"), text.index("ITEM 2"))
        self.assertLess(text.index("Second Item"), text.index("First Item"))
        self.assertNotIn("Other Collection Item", text)
        self.assertNotIn("Hidden Item", text)
        self.assertIn(r"\includegraphics[width=0.96\linewidth,height=", text)
        self.assertIn(r"\usepackage{tikz}", text)
        self.assertIn(r"\usepackage{fancyhdr}", text)
        self.assertIn(r"\setlength{\footskip}{0.20in}", text)
        self.assertIn(r"\fancyfoot[C]{\fontsize{7}{8}\selectfont\color{plateMuted}\thepage}", text)
        self.assertIn(r"\draw[draw=plateRule", text)
        self.assertIn(r"\node[annotationBadge1] at (0.2500,0.2500) {1};", text)
        self.assertIn(r"\url{https://example.com/source-two}", text)
        self.assertIn(r"\url{https://example.com/source-one}", text)
        self.assertIn(r"\textbf{Source URL:} No source URL available", text)
        self.assertNotIn("127.0.0.1", text)
        self.assertNotIn("192.168.0.101", text)
        self.assertIn(r"\plateSection{Labels}", text)
        self.assertIn(r"\plateChip{backsplash}", text)
        self.assertIn(r"\plateMoreChip{+1 more}", text)
        self.assertIn(r"\textbf{\#1} Check backsplash detail\par", text)
        self.assertNotIn(r"(25\%, 75\%)", text)
        self.assertIn(r"\plateSection{Annotations}", text)
        self.assertIn("kitchen_media/", text)
        self.assertEqual(report["embedded_images"], 2)
        self.assertEqual(report["missing_images"], 1)
        self.assertEqual(report["external_links"], 2)
        self.assertEqual(report["missing_links"], 1)
        for copied in report["copied_images"]:
            self.assertTrue((out_path.parent / copied).exists())

    def test_collection_pdf_requires_one_existing_collection(self):
        with Db(self.db_path) as db:
            ensure_schema(db)
            with self.assertRaises(ValueError):
                export_collection_pdf(db, collection_id="", out_path=self.tmp_path / "x.pdf", render_pdf=False)
            with self.assertRaises(FileNotFoundError):
                export_collection_pdf(db, collection_id="missing", out_path=self.tmp_path / "x.pdf", render_pdf=False)

    def test_missing_pdf_tool_reports_clear_error(self):
        with Db(self.db_path) as db, mock.patch("inspirations.export.shutil.which", return_value=None):
            ensure_schema(db)
            with self.assertRaises(PdfToolUnavailableError) as ctx:
                export_collection_pdf(db, collection_id="c1", out_path=self.tmp_path / "x.pdf")
        self.assertIn("Missing PDF tool", str(ctx.exception))

    @unittest.skipUnless(
        shutil.which("pandoc") and shutil.which("tectonic") and shutil.which("pdfimages") and shutil.which("pdfinfo"),
        "pandoc, tectonic, pdfinfo, and pdfimages required for rendered PDF image smoke test",
    )
    def test_rendered_collection_pdf_embeds_local_images(self):
        out_path = self.tmp_path / "exports" / "rendered.pdf"
        with Db(self.db_path) as db:
            ensure_schema(db)
            report = export_collection_pdf(db, collection_id="c1", out_path=out_path)

        self.assertTrue(Path(report["path"]).exists())
        images = subprocess.run(
            ["pdfimages", "-list", str(out_path)],
            check=True,
            capture_output=True,
            text=True,
        )
        image_rows = [line for line in images.stdout.splitlines() if " image " in line]
        self.assertGreaterEqual(len(image_rows), 1, images.stdout)
        info = subprocess.run(
            ["pdfinfo", str(out_path)],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("Pages:           4", info.stdout)

    def test_pandoc_failure_reports_renderer_error(self):
        def fake_which(name: str) -> str:
            return f"/usr/bin/{name}"

        def fake_run(cmd, check, capture_output, text, cwd):
            self.assertIn("--resource-path", cmd)
            self.assertEqual(cmd[cmd.index("--resource-path") + 1], ".")
            self.assertEqual(Path(cwd), (self.tmp_path / "x.md").parent.resolve())
            return subprocess.CompletedProcess(cmd, 2, "", "renderer exploded")

        with Db(self.db_path) as db, \
             mock.patch("inspirations.export.shutil.which", side_effect=fake_which), \
             mock.patch("inspirations.export.subprocess.run", side_effect=fake_run):
            ensure_schema(db)
            with self.assertRaises(PdfRenderError) as ctx:
                export_collection_pdf(db, collection_id="c1", out_path=self.tmp_path / "x.pdf")
        self.assertIn("renderer exploded", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
