import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from inspirations.ai import (
    DEFAULT_GEMINI_EMBEDDING_MODEL,
    _build_embedding_input_text,
    _classify_ai_error,
    _cosine_similarity,
    run_ai_error_triage,
    run_gemini_text_embedder,
    run_similarity_search,
)
from inspirations.db import Db, ensure_schema


class TestAiSemantic(unittest.TestCase):
    def test_build_embedding_input_text_and_truncation(self):
        row = {
            "title": "Kitchen idea",
            "description": "White oak cabinets with brass pulls",
            "board": "renovation",
            "notes": "Save for phase 2",
            "ai_summary": "Warm and modern kitchen composition.",
            "labels_csv": "kitchen|white oak|brass hardware",
        }
        text = _build_embedding_input_text(row)
        self.assertIn("Kitchen idea", text)
        self.assertIn("labels: kitchen, white oak, brass hardware", text)

        long_row = {"title": "x" * 5000}
        short_text = _build_embedding_input_text(long_row)
        self.assertLessEqual(len(short_text), 4000)

    def test_build_embedding_input_text_strips_facebook_engagement_prefix(self):
        row = {
            "source": "facebook",
            "title": "10K views · 266 reactions | We love installing custom herringbone floors",
            "description": "",
            "board": "Flooring Ideas",
            "notes": "",
            "ai_summary": "",
            "labels_csv": "",
        }
        text = _build_embedding_input_text(row)
        self.assertIn("title: We love installing custom herringbone floors", text)
        self.assertNotIn("10K views", text)
        self.assertNotIn("266 reactions", text)

    def test_build_embedding_input_text_keeps_non_facebook_title_intact(self):
        row = {
            "source": "pinterest",
            "title": "10K views · 266 reactions | Keep exact title for non-facebook sources",
            "description": "",
            "board": "",
            "notes": "",
            "ai_summary": "",
            "labels_csv": "",
        }
        text = _build_embedding_input_text(row)
        self.assertIn("title: 10K views · 266 reactions | Keep exact title for non-facebook sources", text)

    def test_cosine_similarity(self):
        self.assertAlmostEqual(_cosine_similarity([1.0, 0.0], [1.0, 0.0]), 1.0, places=6)
        self.assertLess(_cosine_similarity([1.0, 0.0], [0.0, 1.0]), 0.01)
        self.assertEqual(_cosine_similarity([1.0], [1.0, 2.0]), 0.0)

    def test_error_classification(self):
        self.assertEqual(_classify_ai_error("No JSON object in Gemini response"), "no_json_other")
        self.assertEqual(
            _classify_ai_error(
                "No JSON object in Gemini response",
                '{"candidates":[{"finishReason":"RECITATION"}]}',
            ),
            "no_json_recitation",
        )
        self.assertEqual(
            _classify_ai_error("<urlopen error [Errno 8] nodename nor servname provided, or not known>"),
            "network_dns",
        )

    def test_run_ai_error_triage_marks_resolved_vs_actionable(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, imported_at)
                    values (?, ?, ?, ?, datetime('now'))
                    """,
                    ("a1", "pinterest", "pin://1", "Asset One"),
                )
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, imported_at)
                    values (?, ?, ?, ?, datetime('now'))
                    """,
                    ("a2", "pinterest", "pin://2", "Asset Two"),
                )
                db.exec(
                    """
                    insert into asset_ai_errors
                      (id, asset_id, provider, model, error, raw, run_id, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "e1",
                        "a1",
                        "gemini",
                        "gemini-2.5-flash",
                        "No JSON object in Gemini response",
                        '{"candidates":[{"finishReason":"RECITATION"}]}',
                        "r1",
                        "2026-02-06T00:00:00+00:00",
                    ),
                )
                db.exec(
                    """
                    insert into asset_ai_errors
                      (id, asset_id, provider, model, error, raw, run_id, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "e2",
                        "a2",
                        "gemini",
                        "gemini-2.5-flash",
                        "<urlopen error [Errno 8] nodename nor servname provided, or not known>",
                        "",
                        "r2",
                        "2026-02-06T00:10:00+00:00",
                    ),
                )
                # a1 was later successfully tagged, so its error should be triaged as resolved.
                db.exec(
                    """
                    insert into asset_ai (id, asset_id, provider, model, summary, json, created_at)
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "ai1",
                        "a1",
                        "gemini",
                        "gemini-2.0-flash",
                        "summary",
                        json.dumps({"summary": "ok"}),
                        "2026-02-06T01:00:00+00:00",
                    ),
                )

                report = run_ai_error_triage(
                    db,
                    source="pinterest",
                    provider="gemini",
                    model="gemini-2.5-flash",
                )

            self.assertEqual(report["total_errors"], 2)
            self.assertEqual(report["actionable_errors"], 1)
            self.assertEqual(report["actionable_assets"], 1)
            categories = {r["category"]: r for r in report["categories"]}
            self.assertEqual(categories["network_dns"]["actionable"], 1)
            self.assertEqual(categories["no_json_recitation"]["resolved"], 1)

    def test_run_gemini_text_embedder_writes_embeddings(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, description, imported_at)
                    values (?, ?, ?, ?, ?, datetime('now'))
                    """,
                    ("a1", "pinterest", "pin://1", "Kitchen", "Warm oak kitchen"),
                )
                with mock.patch("inspirations.ai._gemini_embed_text", return_value=[0.1, 0.2, 0.3]):
                    report = run_gemini_text_embedder(
                        db,
                        api_key="fake",
                        model=DEFAULT_GEMINI_EMBEDDING_MODEL,
                        source="pinterest",
                    )
                self.assertEqual(report["embedded_assets"], 1)
                row = db.query(
                    "select dimensions from asset_embeddings where asset_id=? and provider=? and model=?",
                    ("a1", "gemini", DEFAULT_GEMINI_EMBEDDING_MODEL),
                )
                self.assertEqual(len(row), 1)
                self.assertEqual(int(row[0]["dimensions"]), 3)

    def test_run_similarity_search_orders_scores(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    "insert into assets (id, source, source_ref, title, imported_at) values (?, ?, ?, ?, datetime('now'))",
                    ("a1", "pinterest", "pin://1", "Asset One"),
                )
                db.exec(
                    "insert into assets (id, source, source_ref, title, imported_at) values (?, ?, ?, ?, datetime('now'))",
                    ("a2", "pinterest", "pin://2", "Asset Two"),
                )
                db.exec(
                    """
                    insert into asset_embeddings
                      (id, asset_id, provider, model, input_text, vector_json, dimensions, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                    """,
                    ("em1", "a1", "gemini", DEFAULT_GEMINI_EMBEDDING_MODEL, "doc one", json.dumps([1.0, 0.0]), 2),
                )
                db.exec(
                    """
                    insert into asset_embeddings
                      (id, asset_id, provider, model, input_text, vector_json, dimensions, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                    """,
                    ("em2", "a2", "gemini", DEFAULT_GEMINI_EMBEDDING_MODEL, "doc two", json.dumps([0.0, 1.0]), 2),
                )
                with mock.patch("inspirations.ai._gemini_embed_text", return_value=[0.9, 0.1]):
                    report = run_similarity_search(
                        db,
                        api_key="fake",
                        query="kitchen island",
                        model=DEFAULT_GEMINI_EMBEDDING_MODEL,
                        source="pinterest",
                        limit=2,
                    )
            self.assertEqual(report["compared_assets"], 2)
            self.assertEqual(report["results"][0]["id"], "a1")

    def test_run_similarity_search_blends_semantic_and_lexical(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, imported_at)
                    values (?, ?, ?, ?, datetime('now'))
                    """,
                    ("a1", "pinterest", "pin://1", "Neutral living room"),
                )
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, imported_at)
                    values (?, ?, ?, ?, datetime('now'))
                    """,
                    ("a2", "pinterest", "pin://2", "Oak kitchen island"),
                )
                db.exec(
                    """
                    insert into asset_embeddings
                      (id, asset_id, provider, model, input_text, vector_json, dimensions, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                    """,
                    ("em1", "a1", "gemini", DEFAULT_GEMINI_EMBEDDING_MODEL, "doc one", json.dumps([0.0, 1.0]), 2),
                )
                db.exec(
                    """
                    insert into asset_embeddings
                      (id, asset_id, provider, model, input_text, vector_json, dimensions, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                    """,
                    ("em2", "a2", "gemini", DEFAULT_GEMINI_EMBEDDING_MODEL, "doc two", json.dumps([1.0, 0.0]), 2),
                )
                with mock.patch("inspirations.ai._gemini_embed_text", return_value=[0.0, 1.0]):
                    semantic_only = run_similarity_search(
                        db,
                        api_key="fake",
                        query="oak kitchen island",
                        model=DEFAULT_GEMINI_EMBEDDING_MODEL,
                        source="pinterest",
                        limit=2,
                        semantic_weight=1.0,
                        lexical_weight=0.0,
                    )
                    blended = run_similarity_search(
                        db,
                        api_key="fake",
                        query="oak kitchen island",
                        model=DEFAULT_GEMINI_EMBEDDING_MODEL,
                        source="pinterest",
                        limit=2,
                        semantic_weight=0.2,
                        lexical_weight=0.8,
                    )
                    filtered = run_similarity_search(
                        db,
                        api_key="fake",
                        query="oak kitchen island",
                        model=DEFAULT_GEMINI_EMBEDDING_MODEL,
                        source="pinterest",
                        limit=2,
                        semantic_weight=0.2,
                        lexical_weight=0.8,
                        min_score=0.5,
                    )
            self.assertEqual(semantic_only["results"][0]["id"], "a1")
            self.assertEqual(blended["results"][0]["id"], "a2")
            self.assertEqual(filtered["compared_assets"], 1)
            self.assertEqual(filtered["results"][0]["id"], "a2")

    def test_run_similarity_search_supports_multi_source_filter(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    "insert into assets (id, source, source_ref, title, imported_at) values (?, ?, ?, ?, datetime('now'))",
                    ("a1", "pinterest", "pin://1", "Asset One"),
                )
                db.exec(
                    "insert into assets (id, source, source_ref, title, imported_at) values (?, ?, ?, ?, datetime('now'))",
                    ("a2", "facebook", "fb://2", "Asset Two"),
                )
                db.exec(
                    "insert into assets (id, source, source_ref, title, imported_at) values (?, ?, ?, ?, datetime('now'))",
                    ("a3", "scan", "scan://3", "Asset Three"),
                )
                for idx, aid in enumerate(("a1", "a2", "a3"), start=1):
                    db.exec(
                        """
                        insert into asset_embeddings
                          (id, asset_id, provider, model, input_text, vector_json, dimensions, created_at)
                        values (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                        """,
                        (f"em{idx}", aid, "gemini", DEFAULT_GEMINI_EMBEDDING_MODEL, "doc", json.dumps([1.0, 0.0]), 2),
                    )
                with mock.patch("inspirations.ai._gemini_embed_text", return_value=[1.0, 0.0]):
                    report = run_similarity_search(
                        db,
                        api_key="fake",
                        query="kitchen",
                        model=DEFAULT_GEMINI_EMBEDDING_MODEL,
                        source="pinterest,facebook",
                        limit=10,
                    )
            self.assertEqual({r["source"] for r in report["results"]}, {"pinterest", "facebook"})


if __name__ == "__main__":
    unittest.main()
