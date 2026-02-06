import unittest

from inspirations.ai import (
    _extract_finish_reasons,
    _extract_json_object,
    _has_finish_reason,
    _no_json_error_message,
    _flatten_ai_labels,
)


class TestGeminiParsing(unittest.TestCase):
    def test_extract_json_object_with_fence(self):
        text = "```json\n{\"summary\": \"hi\", \"rooms\": [\"kitchen\"]}\n```"
        obj = _extract_json_object(text)
        self.assertIsNotNone(obj)
        self.assertEqual(obj["summary"], "hi")

    def test_extract_json_object_with_prefix(self):
        text = "Here is the result:\n{\"summary\": \"ok\", \"tags\": [\"oak\"]}"
        obj = _extract_json_object(text)
        self.assertIsNotNone(obj)
        self.assertEqual(obj["tags"][0], "oak")

    def test_flatten_ai_labels(self):
        payload = {
            "image_type": "interior",
            "rooms": ["kitchen"],
            "materials": ["white oak"],
            "colors": ["navy"],
            "tags": ["open shelving"],
        }
        labels = _flatten_ai_labels(payload)
        self.assertIn("kitchen", labels)
        self.assertIn("white oak", labels)
        self.assertIn("navy", labels)
        self.assertIn("open shelving", labels)
        self.assertIn("interior", labels)

    def test_finish_reason_helpers(self):
        resp = {"candidates": [{"finishReason": "RECITATION"}, {"finishReason": "MAX_TOKENS"}]}
        reasons = _extract_finish_reasons(resp)
        self.assertEqual(reasons, ["RECITATION", "MAX_TOKENS"])
        self.assertTrue(_has_finish_reason(resp, "RECITATION"))
        self.assertTrue(_has_finish_reason(resp, "max_tokens"))
        self.assertFalse(_has_finish_reason(resp, "STOP"))

    def test_no_json_error_message_includes_finish_reason(self):
        resp = {"candidates": [{"finishReason": "RECITATION"}]}
        msg = _no_json_error_message(resp)
        self.assertIn("RECITATION", msg)
        self.assertIn("No JSON object", msg)


if __name__ == "__main__":
    unittest.main()
