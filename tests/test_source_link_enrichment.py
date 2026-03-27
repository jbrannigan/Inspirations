import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from inspirations.db import Db, ensure_schema
from inspirations.source_link_enrichment import (
    _fetch_source_page_browser,
    capture_source_link_candidate_for_asset,
    run_source_link_enrichment,
)


class TestSourceLinkEnrichment(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
