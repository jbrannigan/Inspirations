import unittest

from inspirations.review_slices import (
    AMBIGUOUS_LOW_SIGNAL_URL,
    AMBIGUOUS_MEDIA_LINK_MISMATCH,
    AMBIGUOUS_MEDIA_WEAK_THUMBNAIL,
    AMBIGUOUS_TRUE_CONTESTED,
    classify_ambiguous_review_bucket,
    suggest_track_for_low_signal_url,
)


class TestReviewSlices(unittest.TestCase):
    def test_low_signal_url_builder_checklist_suggests_construction(self):
        asset = {
            "title": "Association of Professional Builders (APB): Builders Qualifying Checklist",
            "board": "",
            "source_ref": "https://go.associationofprofessionalbuilders.com/builders-qualifying-checklist",
            "source_url": "",
            "source_domain": "",
        }
        track = {
            "track_reason": "winner=style_product_decor. scores: style_product_decor=0.08. top evidence: assets.category=home_design",
        }
        bucket, suggested_track, suggested_reason = classify_ambiguous_review_bucket(asset, track, {})
        self.assertEqual(bucket, AMBIGUOUS_LOW_SIGNAL_URL)
        self.assertEqual(suggested_track, "construction_concern")
        self.assertIn("construction", suggested_reason.lower())

    def test_media_link_mismatch_detects_celebrity_text_card(self):
        asset = {
            "title": "Barry Manilow text statement overlay",
            "board": "",
            "source_ref": "https://www.facebook.com/BeautifulHomeDecorInspiration/posts/abc",
            "source_url": "",
            "source_domain": "",
        }
        track = {
            "track_reason": "winner=style_product_decor. scores: style_product_decor=0.08. top evidence: assets.category=home_design",
        }
        ai = {
            "summary": "This image displays a text-based statement from Barry Manilow.",
            "payload": {
                "image_type": "document",
                "text_in_image": ["a statement from barry manilow"],
            },
        }
        bucket, suggested_track, suggested_reason = classify_ambiguous_review_bucket(asset, track, ai)
        self.assertEqual(bucket, AMBIGUOUS_MEDIA_LINK_MISMATCH)
        self.assertEqual(suggested_track, "")
        self.assertIn("unrelated", suggested_reason.lower())

    def test_media_weak_thumbnail_detects_valid_home_link_with_generic_image(self):
        asset = {
            "title": "Best Greige Paint Colors | Julie Blanner",
            "board": "paint",
            "source_ref": "https://julieblanner.com/greige-paint-colors",
            "source_url": "",
            "source_domain": "",
        }
        track = {
            "track_reason": "winner=style_product_decor. scores: style_product_decor=0.08. top evidence: assets.category=home_design",
        }
        ai = {
            "summary": "A portrait of a woman outdoors.",
            "payload": {
                "image_type": "other",
                "tags": ["portrait", "person", "outdoor"],
            },
        }
        bucket, suggested_track, suggested_reason = classify_ambiguous_review_bucket(asset, track, ai)
        self.assertEqual(bucket, AMBIGUOUS_MEDIA_WEAK_THUMBNAIL)
        self.assertEqual(suggested_track, "")
        self.assertIn("thumbnail", suggested_reason.lower())

    def test_media_weak_thumbnail_detects_anonymous_placeholder_avatar(self):
        asset = {
            "title": "Home Decor Post",
            "board": "",
            "source_ref": "https://example.com/home-decor-post",
            "source_url": "",
            "source_domain": "",
        }
        track = {
            "track_reason": "winner=style_product_decor. scores: style_product_decor=0.08. top evidence: assets.category=home_design",
        }
        ai = {
            "summary": "Fedora and glasses icon on purple background.",
            "payload": {
                "image_type": "other",
                "tags": ["anonymous", "avatar", "purple background"],
            },
        }
        bucket, suggested_track, suggested_reason = classify_ambiguous_review_bucket(asset, track, ai)
        self.assertEqual(bucket, AMBIGUOUS_MEDIA_WEAK_THUMBNAIL)
        self.assertEqual(suggested_track, "")
        self.assertIn("placeholder", suggested_reason.lower())

    def test_true_contested_keeps_mixed_build_scene_for_human_review(self):
        asset = {
            "title": "We got the open cell-foam applied today to exterior walls.",
            "board": "insulation",
            "source_ref": "https://www.facebook.com/reel/abc",
            "source_url": "",
            "source_domain": "",
        }
        track = {
            "track_reason": "winner=style_product_decor. scores: style_product_decor=3.42; construction_concern=3.19. top evidence: vision image_type=interior | vision structured style evidence: under construction | board matched construction terms: insulation",
        }
        ai = {
            "summary": "Interior under construction with insulation.",
            "payload": {
                "image_type": "interior",
                "tags": ["construction", "insulation"],
            },
        }
        bucket, suggested_track, suggested_reason = classify_ambiguous_review_bucket(asset, track, ai)
        self.assertEqual(bucket, AMBIGUOUS_TRUE_CONTESTED)
        self.assertEqual(suggested_track, "")
        self.assertIn("mixed", suggested_reason.lower())

    def test_suggest_track_for_low_signal_url_handles_home_decor(self):
        asset = {
            "title": "Best Greige Paint Colors | Julie Blanner",
            "board": "paint",
            "source_ref": "https://julieblanner.com/greige-paint-colors",
            "source_url": "",
            "source_domain": "",
        }
        track, reason = suggest_track_for_low_signal_url(asset, {})
        self.assertEqual(track, "style_product_decor")
        self.assertIn("decor", reason.lower())

    def test_media_link_mismatch_uses_source_page_when_it_looks_unrelated(self):
        asset = {
            "title": "Charming mudroom ideas",
            "board": "mudroom",
            "source_ref": "https://example.com/post",
            "source_url": "",
            "source_domain": "",
        }
        track = {
            "track_reason": "winner=style_product_decor. scores: style_product_decor=0.08. top evidence: assets.category=home_design",
        }
        ai = {
            "summary": "A bright mudroom with cabinetry and hooks.",
            "payload": {
                "image_type": "interior",
                "tags": ["mudroom", "cabinetry", "hooks"],
            },
        }
        source_link = {
            "fetch_status": "fetched",
            "page_title": "Celebrity protest speech transcript",
            "meta_description": "Concert and protest update from a musician.",
            "final_domain": "example.com",
        }
        bucket, suggested_track, suggested_reason = classify_ambiguous_review_bucket(asset, track, ai, source_link)
        self.assertEqual(bucket, AMBIGUOUS_MEDIA_LINK_MISMATCH)
        self.assertEqual(suggested_track, "")
        self.assertIn("source page", suggested_reason.lower())

    def test_media_weak_thumbnail_uses_source_page_when_it_looks_home_related(self):
        asset = {
            "title": "Unknown pin",
            "board": "misc",
            "source_ref": "https://example.com/post",
            "source_url": "",
            "source_domain": "",
        }
        track = {
            "track_reason": "winner=style_product_decor. scores: style_product_decor=0.08. top evidence: assets.category=home_design",
        }
        ai = {
            "summary": "Portrait thumbnail.",
            "payload": {
                "image_type": "other",
                "tags": ["portrait", "person"],
            },
        }
        source_link = {
            "fetch_status": "fetched",
            "page_title": "Best Greige Paint Colors",
            "meta_description": "Interior paint color and greige home decor guide.",
            "final_domain": "julieblanner.com",
        }
        bucket, suggested_track, suggested_reason = classify_ambiguous_review_bucket(asset, track, ai, source_link)
        self.assertEqual(bucket, AMBIGUOUS_MEDIA_WEAK_THUMBNAIL)
        self.assertEqual(suggested_track, "")
        self.assertIn("source page", suggested_reason.lower())


if __name__ == "__main__":
    unittest.main()
