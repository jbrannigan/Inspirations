"""Tests for the two-pass Claude-powered chat module."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from inspirations.catalog import generate_catalog
from inspirations.chat import (
    ALLOWED_ACTIONS,
    _build_routing_prompt,
    _extract_json_from_text,
    process_chat_message,
)
from inspirations.db import Db, ensure_schema


def _seed_db(db):
    """Insert test assets (>=15 per board for catalog board files)."""
    for i in range(20):
        db.exec(
            """insert into assets (id, source, source_ref, title, board, imported_at)
               values (?, ?, ?, ?, ?, datetime('now'))""",
            (f"pk{i:04d}aaaa-0000-0000-0000-000000000000", "pinterest", f"ref://pk{i}", f"Kitchen item {i}", "kitchen"),
        )
    for i in range(3):
        db.exec(
            """insert into assets (id, source, source_ref, title, board, imported_at)
               values (?, ?, ?, ?, ?, datetime('now'))""",
            (f"fb{i:04d}aaaa-0000-0000-0000-000000000000", "facebook", f"ref://fb{i}", f"FB item {i}", "misc"),
        )
    db.exec(
        "insert into collections (id, name, created_at, updated_at) values (?, ?, datetime('now'), datetime('now'))",
        ("c1", "Kitchen Faves"),
    )
    db.exec(
        "insert into collection_items (collection_id, asset_id, position) values (?, ?, ?)",
        ("c1", "pk0000aaaa-0000-0000-0000-000000000000", 0),
    )


class TestExtractJson(unittest.TestCase):
    """Test the JSON extraction helper."""

    def test_plain_json(self):
        result = _extract_json_from_text('{"action": "search", "params": {"q": "tile"}, "message": "ok"}')
        self.assertEqual(result["action"], "search")
        self.assertEqual(result["params"]["q"], "tile")

    def test_json_with_code_fences(self):
        text = '```json\n{"action": "filter", "params": {}, "message": "done"}\n```'
        result = _extract_json_from_text(text)
        self.assertEqual(result["action"], "filter")

    def test_json_with_leading_text(self):
        text = 'Here is the result:\n{"action": "message", "params": {}, "message": "hi"}'
        result = _extract_json_from_text(text)
        self.assertEqual(result["action"], "message")

    def test_no_json(self):
        result = _extract_json_from_text("I don't know what you mean")
        self.assertIsNone(result)

    def test_empty_string(self):
        result = _extract_json_from_text("")
        self.assertIsNone(result)


class TestBuildRoutingPrompt(unittest.TestCase):
    """Test that the routing prompt includes catalog context."""

    def test_prompt_contains_catalog_content(self):
        index_content = "## Pinterest (100 items)\n| File | Category | Items | Topics |"
        prompt = _build_routing_prompt(index_content)
        self.assertIn("Pinterest", prompt)
        self.assertIn("inspiration library", prompt.lower())
        self.assertIn("filter", prompt)
        self.assertIn("show_sidebar", prompt)

    def test_prompt_contains_action_list(self):
        prompt = _build_routing_prompt("(empty)")
        self.assertIn("filter", prompt)
        self.assertIn("content_kind", prompt)
        self.assertIn("search", prompt)
        self.assertIn("create_collection", prompt)
        self.assertIn("show_sidebar", prompt)
        self.assertIn("enter_review", prompt)
        self.assertIn("clear_filters", prompt)
        self.assertIn("bulk_triage", prompt)


class TestProcessChatMessage(unittest.TestCase):
    """Test the main chat function with mocked Claude API."""

    def _make_claude_response(self, action_dict):
        """Build a mock Claude Messages API response."""
        return {
            "content": [{"type": "text", "text": json.dumps(action_dict)}],
            "model": "claude-sonnet-4-20250514",
            "role": "assistant",
            "stop_reason": "end_turn",
        }

    def _mock_urlopen(self, response_dict):
        """Create a mock for urllib.request.urlopen."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(response_dict).encode("utf-8")
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    def test_short_circuit_filter_action(self):
        """Navigation queries should short-circuit (no Pass 2)."""
        action = {"action": "filter", "params": {"triage_status": "keeper"}, "message": "Showing keepers."}
        mock_resp = self._mock_urlopen(self._make_claude_response(action))

        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                _seed_db(db)
                with patch("inspirations.chat.urllib.request.urlopen", return_value=mock_resp):
                    result = process_chat_message(db, api_key="test-key", user_message="show keepers")

        self.assertEqual(result["action"], "filter")
        self.assertEqual(result["params"]["triage_status"], "keeper")
        self.assertEqual(result["message"], "Showing keepers.")

    def test_two_pass_item_search(self):
        """Item-level queries should use two passes when catalog exists."""
        routing = {"route": True, "files": ["pinterest/kitchen.md"], "message": "Looking..."}
        answer = {"action": "show_items", "params": {"ids": ["pk0000aa"]}, "message": "Found 1 item."}

        call_count = [0]

        def mock_urlopen_side_effect(req, timeout=None):
            resp = MagicMock()
            if call_count[0] == 0:
                resp.read.return_value = json.dumps(self._make_claude_response(routing)).encode()
            else:
                resp.read.return_value = json.dumps(self._make_claude_response(answer)).encode()
            call_count[0] += 1
            resp.__enter__ = lambda s: s
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            catalog_dir = Path(td) / "catalog"
            with Db(db_path) as db:
                ensure_schema(db)
                _seed_db(db)
                generate_catalog(db, catalog_dir)
                with patch("inspirations.chat.urllib.request.urlopen", side_effect=mock_urlopen_side_effect):
                    result = process_chat_message(
                        db, api_key="test-key", user_message="find white kitchen cabinets",
                        catalog_dir=catalog_dir,
                    )

        self.assertEqual(call_count[0], 2)
        self.assertEqual(result["action"], "show_items")

    def test_no_catalog_falls_back(self):
        """Without catalog, only routing-only mode works."""
        action = {"action": "clear_filters", "params": {}, "message": "Showing all items."}
        mock_resp = self._mock_urlopen(self._make_claude_response(action))

        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                _seed_db(db)
                with patch("inspirations.chat.urllib.request.urlopen", return_value=mock_resp):
                    result = process_chat_message(db, api_key="test-key", user_message="show everything")

        self.assertEqual(result["action"], "clear_filters")

    def test_malformed_response_falls_back(self):
        """When Claude returns non-JSON, wrap it as a message."""
        bad_resp = {
            "content": [{"type": "text", "text": "I don't understand what you mean."}],
            "role": "assistant",
            "stop_reason": "end_turn",
        }
        mock_resp = self._mock_urlopen(bad_resp)

        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                _seed_db(db)
                with patch("inspirations.chat.urllib.request.urlopen", return_value=mock_resp):
                    result = process_chat_message(db, api_key="test-key", user_message="blah blah")

        self.assertEqual(result["action"], "message")
        self.assertIn("understand", result["message"].lower())

    def test_unknown_action_normalized(self):
        """Unknown actions should be normalized to 'message'."""
        action = {"action": "teleport", "params": {}, "message": "Teleporting!"}
        mock_resp = self._mock_urlopen(self._make_claude_response(action))

        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                _seed_db(db)
                with patch("inspirations.chat.urllib.request.urlopen", return_value=mock_resp):
                    result = process_chat_message(db, api_key="test-key", user_message="teleport me")

        self.assertEqual(result["action"], "message")

    def test_empty_api_key_uses_local_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                result = process_chat_message(db, api_key="", user_message="show collections")
        self.assertEqual(result["action"], "show_sidebar")
        self.assertEqual((result.get("params") or {}).get("type"), "collections")

    def test_timeout_falls_back_to_local_router(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                _seed_db(db)
                with patch("inspirations.chat.urllib.request.urlopen", side_effect=TimeoutError("read operation timed out")):
                    result = process_chat_message(db, api_key="test-key", user_message="show collections")
        self.assertEqual(result["action"], "show_sidebar")
        self.assertEqual((result.get("params") or {}).get("type"), "collections")

    def test_top_reflect_query_fallback_clears_filters(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                _seed_db(db)
                result = process_chat_message(
                    db,
                    api_key="",
                    user_message="Show the top 50 items that best reflect the corpus and the database",
                )
        self.assertEqual(result["action"], "clear_filters")

    def test_keywordless_fallback_returns_message_not_empty_search(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                _seed_db(db)
                result = process_chat_message(
                    db,
                    api_key="",
                    user_message="Please show the corpus and database",
                )
        self.assertEqual(result["action"], "message")
        self.assertIn("could not extract useful keywords", result.get("message", "").lower())

    def test_empty_message_raises(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "t.sqlite"
            with Db(db_path) as db:
                ensure_schema(db)
                with self.assertRaises(ValueError):
                    process_chat_message(db, api_key="test-key", user_message="   ")

    def test_allowed_actions_complete(self):
        """Verify all documented actions are in the allowed set."""
        expected = {
            "filter", "search", "semantic_search", "create_collection",
            "show_collection", "show_items", "show_sidebar",
            "enter_review", "clear_filters", "bulk_triage", "bulk_flag",
            "triage_by_query", "message",
        }
        self.assertEqual(ALLOWED_ACTIONS, expected)


if __name__ == "__main__":
    unittest.main()
