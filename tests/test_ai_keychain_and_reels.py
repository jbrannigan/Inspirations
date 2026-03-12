import argparse
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from inspirations.ai import download_facebook_reels, get_gemini_api_key, run_ai_labeler
from inspirations.cli import cmd_ai_embed
from inspirations.db import Db, ensure_schema


class TestAIKeychainAndReels(unittest.TestCase):
    def setUp(self) -> None:
        from inspirations import ai as ai_module

        ai_module._keychain_cache.clear()

    def test_get_gemini_api_key_falls_back_to_keychain(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": ""}, clear=False):
            with mock.patch("inspirations.ai.subprocess.check_output", return_value="keychain-secret\n") as check_output:
                self.assertEqual(get_gemini_api_key(""), "keychain-secret")
                self.assertEqual(get_gemini_api_key(""), "keychain-secret")
        check_output.assert_called_once()

    def test_run_ai_labeler_uses_keychain_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                with mock.patch("inspirations.ai.get_gemini_api_key", return_value="keychain-secret"):
                    with mock.patch("inspirations.ai.run_gemini_image_labeler", return_value={"ok": True}) as labeler:
                        report = run_ai_labeler(db, provider="gemini")
        self.assertEqual(report, {"ok": True})
        self.assertEqual(labeler.call_args.kwargs["api_key"], "keychain-secret")

    def test_download_facebook_reels_retries_with_progressive_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            store_dir = Path(td) / "store"
            reels_dir = store_dir / "reels" / "facebook"
            reels_dir.mkdir(parents=True, exist_ok=True)

            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, content_kind, imported_at)
                    values (?, ?, ?, ?, datetime('now'))
                    """,
                    ("reel-1", "facebook", "https://facebook.example/reel/1", "reel"),
                )

                calls: list[list[str]] = []

                def fake_run(cmd, capture_output, text, timeout):
                    calls.append(cmd)
                    info_path = reels_dir / "reel-1.info.json"
                    info_path.write_text(
                        json.dumps(
                            {
                                "duration": 12.5,
                                "title": "Working reel",
                                "description": "Useful description",
                                "uploader": "Builder Brigade",
                            }
                        ),
                        encoding="utf-8",
                    )
                    if "-f" in cmd:
                        (reels_dir / "reel-1.mp4").write_bytes(b"video")
                    else:
                        (reels_dir / "reel-1.m4a").write_bytes(b"audio")
                    return subprocess.CompletedProcess(cmd, 0, "", "")

                with mock.patch("inspirations.ai.subprocess.run", side_effect=fake_run):
                    report = download_facebook_reels(db, store_dir, limit=1, force=True)
                    stored_video_path = db.query_value(
                        "select stored_video_path from assets where id=?", ("reel-1",)
                    )

        self.assertEqual(report["downloaded"], 1)
        self.assertEqual(report["total_errors"], 0)
        self.assertTrue(str(stored_video_path).endswith(".mp4"))
        self.assertEqual(len(calls), 2)
        self.assertIn("-f", calls[1])
        self.assertIn("hd/sd/best", calls[1])
        self.assertIn("--merge-output-format", calls[1])
        self.assertIn("mp4", calls[1])

    def test_cmd_ai_embed_uses_keychain_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
            args = argparse.Namespace(
                provider="gemini",
                api_key="",
                db=str(db_path),
                model="",
                source="",
                limit=0,
                force=False,
            )
            stdout = io.StringIO()
            with mock.patch("inspirations.cli.get_gemini_api_key", return_value="keychain-secret"):
                with mock.patch("inspirations.cli.run_gemini_text_embedder", return_value={"ok": True}) as embedder:
                    with mock.patch("sys.stdout", stdout):
                        rc = cmd_ai_embed(args)

        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(stdout.getvalue()), {"ok": True})
        self.assertEqual(embedder.call_args.kwargs["api_key"], "keychain-secret")


if __name__ == "__main__":
    unittest.main()
