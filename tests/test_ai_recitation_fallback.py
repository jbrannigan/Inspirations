import unittest
from unittest.mock import patch

from inspirations.ai import _maybe_retry_with_recitation_fallback


class TestRecitationFallback(unittest.TestCase):
    def test_retries_on_recitation_with_empty_text(self):
        primary = {"candidates": [{"finishReason": "RECITATION", "content": {"parts": []}}]}
        fallback = {
            "candidates": [
                {
                    "finishReason": "STOP",
                    "content": {"parts": [{"text": '{"summary": "ok"}'}]},
                }
            ]
        }

        with patch("inspirations.ai._gemini_generate", side_effect=[primary, fallback]) as mocked:
            resp, used_model = _maybe_retry_with_recitation_fallback(
                api_key="k",
                primary_model="gemini-2.5-flash",
                fallback_model="gemini-2.0-flash",
                prompt="p",
                image_b64="img",
                mime_type="image/jpeg",
                timeout_s=5,
            )

        self.assertEqual(used_model, "gemini-2.0-flash")
        self.assertEqual(resp, fallback)
        self.assertEqual(mocked.call_count, 2)

    def test_no_retry_when_primary_has_json(self):
        primary = {
            "candidates": [
                {
                    "finishReason": "RECITATION",
                    "content": {"parts": [{"text": '{"summary": "ok"}'}]},
                }
            ]
        }

        with patch("inspirations.ai._gemini_generate", return_value=primary) as mocked:
            resp, used_model = _maybe_retry_with_recitation_fallback(
                api_key="k",
                primary_model="gemini-2.5-flash",
                fallback_model="gemini-2.0-flash",
                prompt="p",
                image_b64="img",
                mime_type="image/jpeg",
                timeout_s=5,
            )

        self.assertEqual(used_model, "gemini-2.5-flash")
        self.assertEqual(resp, primary)
        self.assertEqual(mocked.call_count, 1)


if __name__ == "__main__":
    unittest.main()
