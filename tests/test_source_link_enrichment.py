import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from inspirations.db import Db, ensure_schema
from inspirations.source_link_enrichment import (
    _fetch_source_page_browser,
    _parse_html_payload,
    capture_source_link_candidate_for_asset,
    list_pending_media_repairs,
    mark_media_repair_evidence_refreshed,
    media_repair_gallery_for_asset,
    promote_media_repair_candidate_for_asset,
    run_source_link_enrichment,
)


class TestSourceLinkEnrichment(unittest.TestCase):
    def _seed_media_repair_asset(self, db):
        db.exec(
            """
            insert into assets (id, source, source_ref, title, imported_at, stored_path)
            values (?, ?, ?, ?, ?, ?)
            """,
            (
                "repair-a1",
                "facebook",
                "https://www.facebook.com/groups/builderbrigade/permalink/1/",
                "Let us talk about grass",
                "2026-03-08T05:00:00+00:00",
                "/tmp/original-wrong-image.jpg",
            ),
        )
        db.exec(
            """
            insert into classification_runs
              (id, schema_version, run_type, model_provider, model_name, prompt_version, config_json, created_at, notes)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "repair-run-1",
                "curation_v2",
                "source_link_enrichment",
                "heuristic",
                "test",
                "",
                "{}",
                "2026-03-08T05:01:00+00:00",
                "",
            ),
        )
        db.exec(
            """
            insert into asset_source_link_enrichment
              (id, run_id, asset_id, text_excerpt, media_candidates_json, fetch_status, created_at)
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "repair-enrichment-1",
                "repair-run-1",
                "repair-a1",
                "Let us talk about grass. Has anyone done hydro-seeding themselves?",
                '[{"url":"https://cdn.example.com/post-image.jpg","label":"Post image 1"}]',
                "fetched",
                "2026-03-08T05:01:00+00:00",
            ),
        )

    def test_media_repair_gallery_lists_current_source_image_and_text_card(self):
        with tempfile.TemporaryDirectory() as td:
            with Db(Path(td) / "t.sqlite") as db:
                ensure_schema(db)
                self._seed_media_repair_asset(db)
                with patch("inspirations.source_link_enrichment.is_safe_public_url", return_value=True):
                    gallery = media_repair_gallery_for_asset(db, asset_id="repair-a1")

        self.assertEqual([item["kind"] for item in gallery], ["current_media", "post_image", "text_card"])
        self.assertFalse(gallery[0]["selectable"])
        self.assertTrue(gallery[1]["selectable"])
        self.assertEqual(gallery[2]["id"], "text-card")
        self.assertEqual(gallery[2]["text"], "Let us talk about grass")

    def test_promote_media_repair_candidate_can_generate_text_card(self):
        with tempfile.TemporaryDirectory() as td:
            store_dir = Path(td) / "store"
            with Db(Path(td) / "t.sqlite") as db:
                ensure_schema(db)
                self._seed_media_repair_asset(db)
                with patch("inspirations.source_link_enrichment.generate_thumbnails"):
                    report = promote_media_repair_candidate_for_asset(
                        db,
                        asset_id="repair-a1",
                        candidate_id="text-card",
                        store_dir=store_dir,
                    )
                asset = dict(db.query("select stored_path, media_status from assets where id='repair-a1'")[0])
                provenance = dict(
                    db.query(
                        """
                        select field_value, origin_type
                        from asset_field_provenance
                        where asset_id='repair-a1' and field_name='media_representation' and is_current=1
                        """
                    )[0]
                )
                stored_path = Path(str(asset["stored_path"]))
                self.assertTrue(stored_path.exists())
                gallery = media_repair_gallery_for_asset(db, asset_id="repair-a1")

        self.assertTrue(report["promoted"])
        self.assertIn(stored_path.suffix, {".png", ".svg"})
        self.assertEqual(str(asset["media_status"]), "image")
        self.assertEqual(str(provenance["field_value"]), "generated_text_card")
        self.assertEqual(str(provenance["origin_type"]), "generated_text_card")
        self.assertEqual(gallery[0]["label"], "In use: Generated text card")
        self.assertEqual(gallery[0]["representation"], "generated_text_card")
        self.assertEqual(gallery[0]["evidence_status"], "refresh_required:generated_text_card")
        self.assertIn("&v=", gallery[0]["preview_url"])

    def test_media_repair_gallery_can_restore_saved_media_after_text_card_and_empty_source_search(self):
        with tempfile.TemporaryDirectory() as td:
            store_dir = Path(td) / "store"
            original = store_dir / "originals" / "facebook" / "original-saved-image.jpg"
            original.parent.mkdir(parents=True, exist_ok=True)
            original.write_bytes(b"original saved image")
            with Db(Path(td) / "t.sqlite") as db:
                ensure_schema(db)
                self._seed_media_repair_asset(db)
                db.exec(
                    "update assets set image_url=?, stored_path=?, sha256=? where id='repair-a1'",
                    ("https://cdn.example.com/original-saved-image.jpg", str(original), "original-saved-image-sha"),
                )
                with patch("inspirations.source_link_enrichment.generate_thumbnails"):
                    promote_media_repair_candidate_for_asset(
                        db,
                        asset_id="repair-a1",
                        candidate_id="text-card",
                        store_dir=store_dir,
                    )
                db.exec(
                    """
                    update asset_source_link_enrichment
                    set text_excerpt=?, media_candidates_json=?, fetch_status=?, created_at=?
                    where id='repair-enrichment-1'
                    """,
                    ("Let us talk about grass.", "[]", "fetched", "2026-03-08T06:00:00+00:00"),
                )
                gallery = media_repair_gallery_for_asset(db, asset_id="repair-a1", store_dir=store_dir)
                saved = next(item for item in gallery if item["kind"] == "saved_media")
                with patch("inspirations.source_link_enrichment.generate_thumbnails"):
                    report = promote_media_repair_candidate_for_asset(
                        db,
                        asset_id="repair-a1",
                        candidate_id=str(saved["id"]),
                        store_dir=store_dir,
                    )
                restored_path = db.query_value("select stored_path from assets where id='repair-a1'")
                restored_image_url = db.query_value("select image_url from assets where id='repair-a1'")
                restored_image_url_provenance = db.query_value(
                    """
                    select origin_type
                    from asset_field_provenance
                    where asset_id='repair-a1' and field_name='image_url' and is_current=1
                    """
                )
                restored_gallery = media_repair_gallery_for_asset(db, asset_id="repair-a1", store_dir=store_dir)

        self.assertEqual([item["kind"] for item in gallery], ["current_media", "saved_media", "text_card"])
        self.assertEqual(saved["label"], "Previously used: Saved image")
        self.assertTrue(str(saved["preview_url"]).startswith("/store/originals/facebook/original-saved-image.jpg"))
        self.assertEqual(report["kind"], "saved_media")
        self.assertEqual(Path(str(restored_path)).resolve(), original.resolve())
        self.assertEqual(restored_image_url, "https://cdn.example.com/original-saved-image.jpg")
        self.assertEqual(restored_image_url_provenance, "media_repair_restore")
        self.assertEqual(restored_gallery[0]["label"], "In use: Saved image")

    def test_promote_text_card_archives_and_invalidates_stale_machine_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            store_dir = Path(td) / "store"
            with Db(Path(td) / "t.sqlite") as db:
                ensure_schema(db)
                self._seed_media_repair_asset(db)
                db.exec(
                    """
                    insert into asset_ai (id, asset_id, provider, model, summary, json, created_at)
                    values ('ai1', 'repair-a1', 'gemini', 'gemini-2.5-flash', 'Wrong portrait', '{}', datetime('now'))
                    """
                )
                db.exec("update assets set ai_summary='Wrong portrait' where id='repair-a1'")
                db.exec(
                    """
                    insert into asset_labels (id, asset_id, label, source, created_at)
                    values ('label-ai', 'repair-a1', 'portrait', 'ai', datetime('now'))
                    """
                )
                db.exec(
                    """
                    insert into asset_labels (id, asset_id, label, source, created_at)
                    values ('label-human', 'repair-a1', 'landscaping', 'human', datetime('now'))
                    """
                )
                db.exec(
                    """
                    insert into asset_embeddings
                      (id, asset_id, provider, model, input_text, vector_json, dimensions, created_at)
                    values ('embedding1', 'repair-a1', 'gemini', 'gemini-embedding-001',
                            'summary: Wrong portrait', '[0.1,0.2]', 2, datetime('now'))
                    """
                )
                db.exec(
                    """
                    insert into asset_track_assessments
                      (id, run_id, asset_id, track, confidence, is_ambiguous, decision_source, reason, created_at)
                    values ('track1', 'repair-run-1', 'repair-a1', 'style_product_decor', 0.8, 0, 'merged',
                            'wrong image evidence', datetime('now'))
                    """
                )
                db.exec(
                    """
                    insert into asset_axis_memberships
                      (id, run_id, asset_id, track, axis_name, axis_value, confidence, created_at)
                    values ('axis1', 'repair-run-1', 'repair-a1', 'style_product_decor',
                            'design_facets', 'metal', 0.8, datetime('now'))
                    """
                )
                db.exec(
                    """
                    insert into asset_axis_evidence
                      (id, run_id, asset_id, track, axis_name, axis_value, evidence_type, created_at)
                    values ('evidence1', 'repair-run-1', 'repair-a1', 'style_product_decor',
                            'design_facets', 'metal', 'asset_ai_json', datetime('now'))
                    """
                )
                db.exec(
                    """
                    insert into asset_overrides
                      (id, asset_id, track, axis_name, axis_value, operation, actor, created_at)
                    values ('override1', 'repair-a1', 'construction_concern', 'track',
                            'construction_concern', 'set', 'jim', datetime('now'))
                    """
                )
                with patch("inspirations.source_link_enrichment.generate_thumbnails"):
                    report = promote_media_repair_candidate_for_asset(
                        db,
                        asset_id="repair-a1",
                        candidate_id="text-card",
                        store_dir=store_dir,
                    )

                self.assertEqual(db.query_value("select count(*) from asset_ai where asset_id='repair-a1'"), 0)
                self.assertEqual(db.query_value("select count(*) from asset_embeddings where asset_id='repair-a1'"), 0)
                self.assertEqual(db.query_value("select count(*) from asset_track_assessments where asset_id='repair-a1'"), 0)
                self.assertEqual(db.query_value("select count(*) from asset_axis_memberships where asset_id='repair-a1'"), 0)
                self.assertEqual(db.query_value("select count(*) from asset_axis_evidence where asset_id='repair-a1'"), 0)
                self.assertEqual(db.query_value("select ai_summary from assets where id='repair-a1'"), None)
                self.assertEqual(
                    [str(row["label"]) for row in db.query("select label from asset_labels where asset_id='repair-a1' order by label")],
                    ["landscaping"],
                )
                self.assertEqual(db.query_value("select count(*) from asset_overrides where asset_id='repair-a1'"), 1)
                audit_json = str(
                    db.query_value("select stale_evidence_json from asset_media_repair_audit where asset_id='repair-a1'")
                )

        self.assertEqual(report["refresh_required"], ["embedding", "classification"])
        self.assertIn("Wrong portrait", audit_json)
        self.assertIn("portrait", audit_json)

    def test_media_repair_refresh_queue_tracks_pending_and_completed_items(self):
        with tempfile.TemporaryDirectory() as td:
            store_dir = Path(td) / "store"
            with Db(Path(td) / "t.sqlite") as db:
                ensure_schema(db)
                self._seed_media_repair_asset(db)
                with patch("inspirations.source_link_enrichment.generate_thumbnails"):
                    promote_media_repair_candidate_for_asset(
                        db,
                        asset_id="repair-a1",
                        candidate_id="text-card",
                        store_dir=store_dir,
                    )
                pending = list_pending_media_repairs(db)
                mark_media_repair_evidence_refreshed(
                    db,
                    asset_id="repair-a1",
                    repair_kind="generated_text_card",
                    origin_ref="test",
                )
                completed = list_pending_media_repairs(db)

        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["asset_id"], "repair-a1")
        self.assertEqual(pending[0]["repair_kind"], "generated_text_card")
        self.assertEqual(completed, [])

    def test_promote_source_image_reports_retag_refresh_requirement(self):
        with tempfile.TemporaryDirectory() as td:
            store_dir = Path(td) / "store"
            downloaded = store_dir / "originals" / "facebook" / "repair-a1.jpg"
            downloaded.parent.mkdir(parents=True, exist_ok=True)
            downloaded.write_bytes(b"replacement")
            with Db(Path(td) / "t.sqlite") as db:
                ensure_schema(db)
                self._seed_media_repair_asset(db)
                with patch("inspirations.source_link_enrichment.is_safe_public_url", return_value=True), patch(
                    "inspirations.source_link_enrichment.download_url_to_store",
                    return_value=(downloaded, "replacement-sha", len(b"replacement")),
                ), patch("inspirations.source_link_enrichment.generate_thumbnails"):
                    gallery = media_repair_gallery_for_asset(db, asset_id="repair-a1")
                    source_candidate = next(item for item in gallery if item["kind"] == "post_image")
                    report = promote_media_repair_candidate_for_asset(
                        db,
                        asset_id="repair-a1",
                        candidate_id=str(source_candidate["id"]),
                        store_dir=store_dir,
                    )
                repair_kind = db.query_value(
                    "select repair_kind from asset_media_repair_audit where asset_id='repair-a1'"
                )
                representation = db.query_value(
                    """
                    select field_value
                    from asset_field_provenance
                    where asset_id='repair-a1' and field_name='media_representation' and is_current=1
                    """
                )

        self.assertEqual(report["refresh_required"], ["image_tagging", "embedding", "classification"])
        self.assertEqual(str(repair_kind), "source_image")
        self.assertEqual(str(representation), "source_image")

    def test_promote_linked_page_image_records_direct_source_url(self):
        with tempfile.TemporaryDirectory() as td:
            store_dir = Path(td) / "store"
            downloaded = store_dir / "originals" / "facebook" / "repair-a1.jpg"
            downloaded.parent.mkdir(parents=True, exist_ok=True)
            downloaded.write_bytes(b"replacement")
            with Db(Path(td) / "t.sqlite") as db:
                ensure_schema(db)
                self._seed_media_repair_asset(db)
                db.exec(
                    """
                    update asset_source_link_enrichment
                    set media_candidates_json=?
                    where asset_id='repair-a1'
                    """,
                    (
                        '[{"url":"https://cdn.example.com/linked.jpg","label":"Linked page image 1",'
                        '"source_page_url":"https://example.com/article","source_page_label":"Linked source page"}]',
                    ),
                )
                with patch("inspirations.source_link_enrichment.is_safe_public_url", return_value=True), patch(
                    "inspirations.source_link_enrichment.download_url_to_store",
                    return_value=(downloaded, "replacement-sha", len(b"replacement")),
                ), patch("inspirations.source_link_enrichment.generate_thumbnails"):
                    gallery = media_repair_gallery_for_asset(db, asset_id="repair-a1")
                    source_candidate = next(item for item in gallery if item["kind"] == "post_image")
                    report = promote_media_repair_candidate_for_asset(
                        db,
                        asset_id="repair-a1",
                        candidate_id=str(source_candidate["id"]),
                        store_dir=store_dir,
                    )
                asset = db.query("select source_url, source_domain from assets where id='repair-a1'")[0]

        self.assertEqual(str(asset["source_url"]), "https://example.com/article")
        self.assertEqual(str(asset["source_domain"]), "example.com")
        self.assertEqual(report["promoted_source_url"], "https://example.com/article")

    def test_run_source_link_enrichment_can_scope_to_collection(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into classification_runs
                      (id, schema_version, run_type, model_provider, model_name, prompt_version, config_json, created_at, notes)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "track1",
                        "curation_v2",
                        "track_gate",
                        "heuristic",
                        "test",
                        "",
                        "{}",
                        "2026-03-08T05:00:00+00:00",
                        "",
                    ),
                )
                db.exec("insert into collections (id, name, created_at, updated_at) values ('c1', 'Scope', datetime('now'), datetime('now'))")
                for idx in range(2):
                    asset_id = f"a{idx}"
                    db.exec(
                        """
                        insert into assets (id, source, source_ref, title, imported_at)
                        values (?, ?, ?, ?, ?)
                        """,
                        (
                            asset_id,
                            "facebook",
                            f"https://example.com/{asset_id}",
                            f"Asset {idx}",
                            f"2026-03-08T05:0{idx}:00+00:00",
                        ),
                    )
                    db.exec(
                        """
                        insert into asset_track_assessments
                          (id, run_id, asset_id, track, confidence, is_ambiguous, decision_source, reason, created_at)
                        values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            f"ta{idx}",
                            "track1",
                            asset_id,
                            "style_product_decor",
                            0.8,
                            0,
                            "merged",
                            "winner=style",
                            f"2026-03-08T05:0{idx}:30+00:00",
                        ),
                    )
                db.exec("insert into collection_items (collection_id, asset_id, position) values ('c1', 'a1', 1)")

                with patch(
                    "inspirations.source_link_enrichment._fetch_source_page",
                    side_effect=lambda **kwargs: {
                        "input_url": kwargs["url"],
                        "final_url": kwargs["url"],
                        "final_domain": "example.com",
                        "canonical_url": kwargs["url"],
                        "og_image_url": "",
                        "page_title": kwargs["url"].rsplit("/", 1)[-1],
                        "og_title": "",
                        "meta_description": "",
                        "og_description": "",
                        "text_excerpt": "",
                        "hero_image_url": "",
                        "hero_image_alt": "",
                        "hero_text_excerpt": "",
                        "content_type": "text/html",
                        "http_status": 200,
                        "redirect_count": 0,
                        "truncated": 0,
                        "fetch_status": "fetched",
                        "error": "",
                        "content_hash": "abc123",
                    },
                ):
                    report = run_source_link_enrichment(
                        db,
                        track_run_id="track1",
                        only_ambiguous=False,
                        collection_id="c1",
                        notes="test",
                    )

                rows = db.query(
                    "select asset_id from asset_source_link_enrichment where run_id=?",
                    (report["run_id"],),
                )

            self.assertEqual(report["candidate_count"], 1)
            self.assertEqual([str(rows[0]["asset_id"])], ["a1"])

    def test_run_source_link_enrichment_sanitizes_surrogates_before_insert(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into classification_runs
                      (id, schema_version, run_type, model_provider, model_name, prompt_version, config_json, created_at, notes)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "track1",
                        "curation_v2",
                        "track_gate",
                        "heuristic",
                        "test",
                        "",
                        "{}",
                        "2026-03-08T05:00:00+00:00",
                        "",
                    ),
                )
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, imported_at)
                    values (?, ?, ?, ?, ?)
                    """,
                    (
                        "a1",
                        "pinterest",
                        "https://www.pinterest.com/pin/123/",
                        "Unknown pin",
                        "2026-03-08T05:00:00+00:00",
                    ),
                )
                db.exec(
                    """
                    insert into asset_track_assessments
                      (id, run_id, asset_id, track, confidence, is_ambiguous, decision_source, reason, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "ta1",
                        "track1",
                        "a1",
                        "style_product_decor",
                        0.55,
                        0,
                        "merged",
                        "winner=style_product_decor. top evidence: assets.category=home_design",
                        "2026-03-08T05:01:00+00:00",
                    ),
                )

                with patch(
                    "inspirations.source_link_enrichment._fetch_source_page_browser",
                    return_value={
                        "input_url": "https://www.pinterest.com/pin/123/",
                        "final_url": "https://www.pinterest.com/pin/123/",
                        "final_domain": "pinterest.com",
                        "canonical_url": "",
                        "og_image_url": "",
                        "page_title": "Bad \ud83d title",
                        "og_title": "",
                        "meta_description": "",
                        "og_description": "",
                        "text_excerpt": "Excerpt with lone surrogate \ud83d in body",
                        "hero_image_url": "",
                        "hero_image_alt": "",
                        "hero_text_excerpt": "",
                        "content_type": "browser/document",
                        "http_status": 200,
                        "redirect_count": 0,
                        "truncated": 0,
                        "fetch_status": "fetched",
                        "error": "",
                        "content_hash": "abc123",
                    },
                ), patch(
                    "inspirations.source_link_enrichment._close_playwright_session"
                ):
                    report = run_source_link_enrichment(
                        db,
                        track_run_id="track1",
                        only_ambiguous=False,
                        include_platform_hosts=True,
                        browser_platform_hosts=True,
                        notes="test",
                    )

                row = db.query(
                    """
                    select page_title, text_excerpt
                    from asset_source_link_enrichment
                    where run_id=?
                    """,
                    (report["run_id"],),
                )[0]

            self.assertEqual(report["counts"]["fetched"], 1)
            self.assertIn("?", str(row["page_title"]))
            self.assertIn("?", str(row["text_excerpt"]))

    def test_run_source_link_enrichment_respects_limit_and_offset(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into classification_runs
                      (id, schema_version, run_type, model_provider, model_name, prompt_version, config_json, created_at, notes)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "track1",
                        "curation_v2",
                        "track_gate",
                        "heuristic",
                        "test",
                        "",
                        "{}",
                        "2026-03-08T05:00:00+00:00",
                        "",
                    ),
                )
                for idx in range(3):
                    asset_id = f"a{idx}"
                    db.exec(
                        """
                        insert into assets (id, source, source_ref, title, imported_at)
                        values (?, ?, ?, ?, ?)
                        """,
                        (
                            asset_id,
                            "facebook",
                            f"https://example.com/{asset_id}",
                            f"Asset {idx}",
                            f"2026-03-08T05:0{idx}:00+00:00",
                        ),
                    )
                    db.exec(
                        """
                        insert into asset_track_assessments
                          (id, run_id, asset_id, track, confidence, is_ambiguous, decision_source, reason, created_at)
                        values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            f"ta{idx}",
                            "track1",
                            asset_id,
                            "style_product_decor",
                            0.8,
                            0,
                            "merged",
                            "winner=style",
                            f"2026-03-08T05:0{idx}:30+00:00",
                        ),
                    )

                with patch(
                    "inspirations.source_link_enrichment._fetch_source_page",
                    side_effect=lambda **kwargs: {
                        "input_url": kwargs["url"],
                        "final_url": kwargs["url"],
                        "final_domain": "example.com",
                        "canonical_url": kwargs["url"],
                        "og_image_url": "",
                        "page_title": kwargs["url"].rsplit("/", 1)[-1],
                        "og_title": "",
                        "meta_description": "",
                        "og_description": "",
                        "text_excerpt": "",
                        "hero_image_url": "",
                        "hero_image_alt": "",
                        "hero_text_excerpt": "",
                        "content_type": "text/html",
                        "http_status": 200,
                        "redirect_count": 0,
                        "truncated": 0,
                        "fetch_status": "fetched",
                        "error": "",
                        "content_hash": "abc123",
                    },
                ):
                    report = run_source_link_enrichment(
                        db,
                        track_run_id="track1",
                        only_ambiguous=False,
                        limit=1,
                        offset=1,
                        notes="test",
                    )

                rows = db.query(
                    "select asset_id, input_url from asset_source_link_enrichment where run_id=?",
                    (report["run_id"],),
                )

            self.assertEqual(report["candidate_count"], 1)
            self.assertEqual(len(rows), 1)
            self.assertEqual(str(rows[0]["asset_id"]), "a1")

    def test_run_source_link_enrichment_writes_results_for_ambiguous_assets(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into classification_runs
                      (id, schema_version, run_type, model_provider, model_name, prompt_version, config_json, created_at, notes)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "track1",
                        "curation_v2",
                        "track_gate",
                        "heuristic",
                        "test",
                        "",
                        "{}",
                        "2026-03-08T05:00:00+00:00",
                        "",
                    ),
                )
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, imported_at)
                    values (?, ?, ?, ?, ?)
                    """,
                    (
                        "a1",
                        "facebook",
                        "https://example.com/greige-paint-colors",
                        "Best Greige Paint Colors",
                        "2026-03-08T05:00:00+00:00",
                    ),
                )
                db.exec(
                    """
                    insert into asset_track_assessments
                      (id, run_id, asset_id, track, confidence, is_ambiguous, decision_source, reason, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "ta1",
                        "track1",
                        "a1",
                        "style_product_decor",
                        0.55,
                        1,
                        "merged",
                        "winner=style_product_decor. top evidence: assets.category=home_design",
                        "2026-03-08T05:01:00+00:00",
                    ),
                )

                with patch(
                    "inspirations.source_link_enrichment._fetch_source_page",
                    return_value={
                        "input_url": "https://example.com/greige-paint-colors",
                        "final_url": "https://example.com/greige-paint-colors",
                        "final_domain": "example.com",
                        "canonical_url": "https://example.com/greige-paint-colors",
                        "og_image_url": "https://example.com/hero.jpg",
                        "page_title": "Best Greige Paint Colors",
                        "og_title": "Best Greige Paint Colors",
                        "meta_description": "Interior paint color and greige home decor guide.",
                        "og_description": "",
                        "text_excerpt": "Interior paint color and greige home decor guide.",
                        "hero_image_url": "",
                        "hero_image_alt": "",
                        "hero_text_excerpt": "",
                        "content_type": "text/html; charset=utf-8",
                        "http_status": 200,
                        "redirect_count": 0,
                        "truncated": 0,
                        "fetch_status": "fetched",
                        "error": "",
                        "content_hash": "abc123",
                    },
                ):
                    report = run_source_link_enrichment(
                        db,
                        track_run_id="track1",
                        only_ambiguous=True,
                        notes="test",
                        promote_best_source_url=True,
                    )

                row = db.query(
                    """
                    select asset_id, fetch_status, page_title, final_domain, http_status
                    from asset_source_link_enrichment
                    where run_id=?
                    """,
                    (report["run_id"],),
                )[0]
                asset = db.query("select source_url, source_domain from assets where id=?", ("a1",))[0]
                provenance = db.query(
                    """
                    select field_name, field_value, origin_type, origin_ref, is_current
                    from asset_field_provenance
                    where asset_id=? and field_name='source_url'
                    """,
                    ("a1",),
                )[0]

            self.assertEqual(report["candidate_count"], 1)
            self.assertEqual(report["counts"]["fetched"], 1)
            self.assertEqual(report["promoted_source_url_count"], 1)
            self.assertEqual(str(row["asset_id"]), "a1")
            self.assertEqual(str(row["fetch_status"]), "fetched")
            self.assertEqual(str(row["page_title"]), "Best Greige Paint Colors")
            self.assertEqual(str(row["final_domain"]), "example.com")
            self.assertEqual(int(row["http_status"]), 200)
            self.assertEqual(str(asset["source_url"]), "https://example.com/greige-paint-colors")
            self.assertEqual(str(asset["source_domain"]), "example.com")
            self.assertEqual(str(provenance["field_name"]), "source_url")
            self.assertEqual(str(provenance["field_value"]), "https://example.com/greige-paint-colors")
            self.assertEqual(str(provenance["origin_type"]), "source_link_enrichment")
            self.assertEqual(str(provenance["origin_ref"]), report["run_id"])
            self.assertEqual(int(provenance["is_current"]), 1)

    def test_run_source_link_enrichment_skips_platform_wrappers_by_default(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into classification_runs
                      (id, schema_version, run_type, model_provider, model_name, prompt_version, config_json, created_at, notes)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "track1",
                        "curation_v2",
                        "track_gate",
                        "heuristic",
                        "test",
                        "",
                        "{}",
                        "2026-03-08T05:00:00+00:00",
                        "",
                    ),
                )
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, imported_at)
                    values (?, ?, ?, ?, ?)
                    """,
                    (
                        "a1",
                        "pinterest",
                        "https://www.pinterest.com/pin/123/",
                        "Unknown pin",
                        "2026-03-08T05:00:00+00:00",
                    ),
                )
                db.exec(
                    """
                    insert into asset_track_assessments
                      (id, run_id, asset_id, track, confidence, is_ambiguous, decision_source, reason, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "ta1",
                        "track1",
                        "a1",
                        "style_product_decor",
                        0.55,
                        1,
                        "merged",
                        "winner=style_product_decor. top evidence: assets.category=home_design",
                        "2026-03-08T05:01:00+00:00",
                    ),
                )

                with patch("inspirations.source_link_enrichment._fetch_source_page") as mocked:
                    report = run_source_link_enrichment(db, track_run_id="track1", only_ambiguous=True, notes="test")
                    mocked.assert_not_called()

                row = db.query(
                    """
                    select fetch_status, final_domain, error
                    from asset_source_link_enrichment
                    where run_id=?
                    """,
                    (report["run_id"],),
                )[0]

            self.assertEqual(report["counts"]["platform_wrapper_skipped"], 1)
            self.assertEqual(str(row["fetch_status"]), "platform_wrapper_skipped")
            self.assertEqual(str(row["final_domain"]), "pinterest.com")
            self.assertIn("platform wrapper", str(row["error"]).lower())

    def test_run_source_link_enrichment_uses_browser_for_platform_wrappers_when_enabled(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into classification_runs
                      (id, schema_version, run_type, model_provider, model_name, prompt_version, config_json, created_at, notes)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "track1",
                        "curation_v2",
                        "track_gate",
                        "heuristic",
                        "test",
                        "",
                        "{}",
                        "2026-03-08T05:00:00+00:00",
                        "",
                    ),
                )
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, imported_at)
                    values (?, ?, ?, ?, ?)
                    """,
                    (
                        "a1",
                        "pinterest",
                        "https://www.pinterest.com/pin/123/",
                        "Unknown pin",
                        "2026-03-08T05:00:00+00:00",
                    ),
                )
                db.exec(
                    """
                    insert into asset_track_assessments
                      (id, run_id, asset_id, track, confidence, is_ambiguous, decision_source, reason, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "ta1",
                        "track1",
                        "a1",
                        "style_product_decor",
                        0.55,
                        0,
                        "merged",
                        "winner=style_product_decor. top evidence: assets.category=home_design",
                        "2026-03-08T05:01:00+00:00",
                    ),
                )

                with patch(
                    "inspirations.source_link_enrichment._fetch_source_page_browser",
                    return_value={
                        "input_url": "https://www.pinterest.com/pin/123/",
                        "final_url": "https://www.pinterest.com/pin/123/",
                        "final_domain": "pinterest.com",
                        "canonical_url": "",
                        "og_image_url": "",
                        "page_title": "Pin by Someone on Home Decor",
                        "og_title": "Home Decor",
                        "meta_description": "",
                        "og_description": "",
                        "text_excerpt": "Home decor bedroom vanity bathroom kitchen ideas.",
                        "hero_image_url": "https://cdn.example.com/hero.jpg",
                        "hero_image_alt": "Pinned bedroom inspiration",
                        "hero_text_excerpt": "Which vanity style would you choose?",
                        "content_type": "browser/document",
                        "http_status": 200,
                        "redirect_count": 0,
                        "truncated": 0,
                        "fetch_status": "fetched",
                        "error": "",
                        "content_hash": "abc123",
                    },
                ) as browser_fetcher, patch(
                    "inspirations.source_link_enrichment._close_playwright_session"
                ) as close_browser:
                    report = run_source_link_enrichment(
                        db,
                        track_run_id="track1",
                        only_ambiguous=False,
                        include_platform_hosts=True,
                        browser_platform_hosts=True,
                        notes="test",
                    )
                    browser_fetcher.assert_called_once()
                    close_browser.assert_called_once()

                row = db.query(
                    """
                    select fetch_status, page_title, content_type
                    from asset_source_link_enrichment
                    where run_id=?
                    """,
                    (report["run_id"],),
                )[0]

            self.assertEqual(report["counts"]["fetched"], 1)
            self.assertEqual(str(row["fetch_status"]), "fetched")
            self.assertEqual(str(row["page_title"]), "Pin by Someone on Home Decor")
            self.assertEqual(str(row["content_type"]), "browser/document")

    def test_run_source_link_enrichment_can_promote_browser_hero_image(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            store_dir = Path(td) / "store"
            store_dir.mkdir(parents=True, exist_ok=True)
            hero_file = Path(td) / "hero.jpg"
            hero_file.write_bytes(b"\xff\xd8\xff\xdbfakejpeg")
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into classification_runs
                      (id, schema_version, run_type, model_provider, model_name, prompt_version, config_json, created_at, notes)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "track1",
                        "curation_v2",
                        "track_gate",
                        "heuristic",
                        "test",
                        "",
                        "{}",
                        "2026-03-08T05:00:00+00:00",
                        "",
                    ),
                )
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, imported_at)
                    values (?, ?, ?, ?, ?)
                    """,
                    (
                        "a1",
                        "facebook",
                        "https://www.facebook.com/some/wrapper",
                        "Building Brigade post",
                        "2026-03-08T05:00:00+00:00",
                    ),
                )
                db.exec(
                    """
                    insert into asset_track_assessments
                      (id, run_id, asset_id, track, confidence, is_ambiguous, decision_source, reason, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "ta1",
                        "track1",
                        "a1",
                        "construction_concern",
                        0.7,
                        0,
                        "merged",
                        "winner=construction_concern",
                        "2026-03-08T05:01:00+00:00",
                    ),
                )

                with patch(
                    "inspirations.source_link_enrichment._fetch_source_page_browser",
                    return_value={
                        "input_url": "https://www.facebook.com/some/wrapper",
                        "final_url": "https://www.facebook.com/some/wrapper",
                        "final_domain": "facebook.com",
                        "canonical_url": "",
                        "og_image_url": "",
                        "page_title": "Building Brigade",
                        "og_title": "Building Brigade",
                        "meta_description": "",
                        "og_description": "",
                        "text_excerpt": "Builder discussion and checklist.",
                        "hero_image_url": "https://cdn.example.com/building-brigade-hero.jpg",
                        "hero_image_alt": "Building Brigade hero",
                        "hero_text_excerpt": "What is the best wall assembly?",
                        "content_type": "browser/document",
                        "http_status": 200,
                        "redirect_count": 0,
                        "truncated": 0,
                        "fetch_status": "fetched",
                        "error": "",
                        "content_hash": "abc123",
                    },
                ), patch(
                    "inspirations.source_link_enrichment.download_url_to_store",
                    return_value=(hero_file, "sha-hero", len(hero_file.read_bytes())),
                ), patch(
                    "inspirations.source_link_enrichment.generate_thumbnails",
                    return_value={"attempted": 1, "generated": 1, "errors": []},
                ), patch(
                    "inspirations.source_link_enrichment._close_playwright_session"
                ):
                    report = run_source_link_enrichment(
                        db,
                        track_run_id="track1",
                        only_ambiguous=False,
                        include_platform_hosts=True,
                        browser_platform_hosts=True,
                        promote_hero_image=True,
                        store_dir=store_dir,
                        notes="test",
                    )

                row = db.query(
                    """
                    select hero_image_url, hero_image_alt, hero_text_excerpt
                    from asset_source_link_enrichment
                    where run_id=?
                    """,
                    (report["run_id"],),
                )[0]
                asset = db.query(
                    "select image_url, stored_path, sha256, media_status from assets where id='a1'"
                )[0]

            self.assertEqual(report["promoted_hero_image_count"], 1)
            self.assertEqual(str(row["hero_image_url"]), "https://cdn.example.com/building-brigade-hero.jpg")
            self.assertEqual(str(row["hero_image_alt"]), "Building Brigade hero")
            self.assertEqual(str(row["hero_text_excerpt"]), "What is the best wall assembly?")
            self.assertEqual(str(asset["image_url"]), "https://cdn.example.com/building-brigade-hero.jpg")
            self.assertEqual(str(asset["sha256"]), "sha-hero")
            self.assertEqual(str(asset["media_status"]), "image")

    def test_run_source_link_enrichment_passes_browser_profile_dir(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            profile_dir = Path(td) / "profile"
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into classification_runs
                      (id, schema_version, run_type, model_provider, model_name, prompt_version, config_json, created_at, notes)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "track1",
                        "curation_v2",
                        "track_gate",
                        "heuristic",
                        "test",
                        "",
                        "{}",
                        "2026-03-08T05:00:00+00:00",
                        "",
                    ),
                )
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, imported_at)
                    values (?, ?, ?, ?, ?)
                    """,
                    (
                        "a1",
                        "facebook",
                        "https://www.facebook.com/groups/builderbrigade/permalink/1/",
                        "Builder Brigade post",
                        "2026-03-08T05:00:00+00:00",
                    ),
                )
                db.exec(
                    """
                    insert into asset_track_assessments
                      (id, run_id, asset_id, track, confidence, is_ambiguous, decision_source, reason, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "ta1",
                        "track1",
                        "a1",
                        "construction_concern",
                        0.7,
                        0,
                        "merged",
                        "winner=construction_concern",
                        "2026-03-08T05:01:00+00:00",
                    ),
                )

                with patch(
                    "inspirations.source_link_enrichment._fetch_source_page_browser",
                    return_value={
                        "input_url": "https://www.facebook.com/groups/builderbrigade/permalink/1/",
                        "final_url": "https://www.facebook.com/groups/builderbrigade/permalink/1/",
                        "final_domain": "facebook.com",
                        "canonical_url": "",
                        "og_image_url": "",
                        "page_title": "Builder Brigade",
                        "og_title": "",
                        "meta_description": "",
                        "og_description": "",
                        "text_excerpt": "",
                        "hero_image_url": "",
                        "hero_image_alt": "",
                        "hero_text_excerpt": "",
                        "content_type": "browser/document",
                        "http_status": 200,
                        "redirect_count": 0,
                        "truncated": 0,
                        "fetch_status": "fetched",
                        "error": "",
                        "content_hash": "abc123",
                    },
                ) as browser_fetcher, patch(
                    "inspirations.source_link_enrichment._close_playwright_session"
                ):
                    run_source_link_enrichment(
                        db,
                        track_run_id="track1",
                        only_ambiguous=False,
                        include_platform_hosts=True,
                        browser_platform_hosts=True,
                        browser_profile_dir=profile_dir,
                        notes="test",
                    )

                self.assertEqual(browser_fetcher.call_args.kwargs.get("profile_dir"), profile_dir)

    def test_capture_source_link_candidate_passes_browser_profile_dir(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            store_dir = Path(td) / "store"
            profile_dir = Path(td) / "profile"
            store_dir.mkdir(parents=True, exist_ok=True)
            with Db(db_path) as db:
                ensure_schema(db)
                db.exec(
                    """
                    insert into assets (id, source, source_ref, title, imported_at)
                    values (?, ?, ?, ?, ?)
                    """,
                    (
                        "a1",
                        "facebook",
                        "https://www.facebook.com/groups/builderbrigade/permalink/1/",
                        "Builder Brigade post",
                        "2026-03-08T05:00:00+00:00",
                    ),
                )

                with patch(
                    "inspirations.source_link_enrichment._fetch_source_page_browser",
                    return_value={
                        "input_url": "https://www.facebook.com/groups/builderbrigade/permalink/1/",
                        "final_url": "https://www.facebook.com/groups/builderbrigade/permalink/1/",
                        "final_domain": "facebook.com",
                        "canonical_url": "",
                        "og_image_url": "",
                        "page_title": "Builder Brigade",
                        "og_title": "",
                        "meta_description": "",
                        "og_description": "",
                        "text_excerpt": "",
                        "hero_image_url": "",
                        "hero_image_alt": "",
                        "hero_text_excerpt": "",
                        "content_type": "browser/document",
                        "http_status": 200,
                        "redirect_count": 0,
                        "truncated": 0,
                        "fetch_status": "fetched",
                        "error": "",
                        "content_hash": "abc123",
                    },
                ) as browser_fetcher, patch(
                    "inspirations.source_link_enrichment._close_playwright_session"
                ):
                    capture_source_link_candidate_for_asset(
                        db,
                        asset_id="a1",
                        store_dir=store_dir,
                        browser=True,
                        include_platform_hosts=True,
                        browser_profile_dir=profile_dir,
                    )

                self.assertEqual(browser_fetcher.call_args.kwargs.get("profile_dir"), profile_dir)

    def test_fetch_source_page_browser_falls_back_to_page_title_when_body_is_ui_noise(self):
        eval_payload = {
            "url": "https://www.facebook.com/groups/builderbrigade/permalink/1/",
            "title": "Home Building Help | What am I missing as far as electrical outlets | Facebook",
            "h1": [],
            "text": "OK Not Now Stories Feed posts Facebook Facebook Facebook",
            "heroImageUrl": "",
            "heroImageAlt": "",
            "heroText": "",
        }

        def fake_run(args, **kwargs):
            if args[0] in {"open", "goto", "run-code"}:
                return ""
            if args[0] == "eval":
                return "### Result\n" + __import__("json").dumps(eval_payload) + "\n### Ran Playwright code\n"
            raise AssertionError(args)

        with patch("inspirations.source_link_enrichment._run_playwright_cli", side_effect=fake_run):
            result = _fetch_source_page_browser(
                url="https://www.facebook.com/groups/builderbrigade/permalink/1/",
                timeout_s=8.0,
                session_name="media-repair-auth",
                profile_dir=Path("/tmp/fake-profile"),
            )

        self.assertEqual(
            result["text_excerpt"],
            "What am I missing as far as electrical outlets",
        )

    def test_fetch_source_page_browser_scopes_candidate_images_to_primary_content(self):
        eval_payload = {
            "url": "https://www.facebook.com/groups/builderbrigade/permalink/1/",
            "title": "Home Building Help | Text-only post | Facebook",
            "h1": [],
            "text": "Text-only post",
            "heroImageUrl": "",
            "heroImageAlt": "",
            "heroText": "",
        }
        eval_scripts = []

        def fake_run(args, **kwargs):
            if args[0] in {"open", "goto", "run-code"}:
                return ""
            if args[0] == "eval":
                eval_scripts.append(args[1])
                return "### Result\n" + __import__("json").dumps(eval_payload) + "\n### Ran Playwright code\n"
            raise AssertionError(args)

        with patch("inspirations.source_link_enrichment._run_playwright_cli", side_effect=fake_run):
            _fetch_source_page_browser(
                url="https://www.facebook.com/groups/builderbrigade/permalink/1/",
                timeout_s=8.0,
                session_name="media-repair-auth",
                profile_dir=Path("/tmp/fake-profile"),
            )

        self.assertEqual(len(eval_scripts), 1)
        self.assertIn("imageScope.querySelectorAll('img')", eval_scripts[0])
        self.assertIn("isNearPrimaryPost", eval_scripts[0])
        self.assertIn("Comment image", eval_scripts[0])
        self.assertIn("Scrolled comment image", eval_scripts[0])
        self.assertNotIn("Array.from(document.images || [])", eval_scripts[0])

    def test_parse_html_payload_collects_page_images(self):
        result = _parse_html_payload(
            '<html><head><title>Linked page</title></head><body>'
            '<img src="/images/example.jpg" alt="Example image"></body></html>',
            final_url="https://example.com/post",
        )

        self.assertEqual(
            result["media_candidates"],
            [{"url": "https://example.com/images/example.jpg", "alt": "Example image", "label": "Page image 1"}],
        )

    def test_fetch_source_page_browser_follows_pinterest_visit_site_link(self):
        eval_payload = {
            "url": "https://www.pinterest.com/pin/123/",
            "title": "Pinned idea",
            "h1": [],
            "text": "Visit site",
            "heroImageUrl": "https://i.pinimg.com/736x/pin.jpg",
            "heroImageAlt": "Pinned image",
            "heroText": "",
            "mediaCandidates": [{"url": "https://i.pinimg.com/736x/pin.jpg", "label": "Post image 1"}],
            "outboundLinks": [
                {
                    "url": "http://linked-example.blogspot.com/post",
                    "text": "Visit site",
                },
            ],
        }

        def fake_run(args, **kwargs):
            if args[0] in {"open", "goto", "run-code"}:
                return ""
            if args[0] == "eval":
                return "### Result\n" + __import__("json").dumps(eval_payload) + "\n### Ran Playwright code\n"
            raise AssertionError(args)

        with patch("inspirations.source_link_enrichment.is_safe_public_url", return_value=True), patch(
            "inspirations.source_link_enrichment._run_playwright_cli",
            side_effect=fake_run,
        ), patch(
            "inspirations.source_link_enrichment._fetch_source_page",
            return_value={
                "final_url": "https://linked-example.blogspot.com/post",
                "media_candidates": [{"url": "https://cdn.example.com/linked.jpg", "label": "Page image 1"}],
            },
        ) as linked_fetcher:
            result = _fetch_source_page_browser(
                url="https://www.pinterest.com/pin/123/",
                timeout_s=8.0,
                session_name="media-repair-auth",
                profile_dir=Path("/tmp/fake-profile"),
            )

        self.assertEqual(linked_fetcher.call_args.kwargs["url"], "https://linked-example.blogspot.com/post")
        self.assertEqual([item["label"] for item in result["media_candidates"]], ["Post image 1", "Linked page image 1 · Linked"])
        self.assertEqual(result["media_candidates"][1]["source_page_url"], "https://linked-example.blogspot.com/post")

    def test_fetch_source_page_browser_explains_how_to_start_authenticated_session(self):
        with patch(
            "inspirations.source_link_enrichment._run_playwright_cli",
            side_effect=subprocess.CalledProcessError(
                1,
                ["playwright-cli", "goto"],
                stderr="The browser 'media-repair-auth' is not open, please run open first",
            ),
        ):
            result = _fetch_source_page_browser(
                url="https://www.facebook.com/groups/builderbrigade/permalink/1/",
                timeout_s=8.0,
                session_name="media-repair-auth",
                profile_dir=Path("/tmp/fake-profile"),
            )

        self.assertEqual(result["fetch_status"], "browser_error")
        self.assertIn("tools/open_media_repair_auth_browser.sh", result["error"])
        self.assertIn("leave that window open", result["error"])
        self.assertNotIn("please run open first", result["error"])


if __name__ == "__main__":
    unittest.main()
