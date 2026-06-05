"""Claude-powered natural language chat for the Inspirations library.

Two-pass architecture:
  Pass 1 (Route): Claude reads the catalog index, decides which files to read
                  OR short-circuits to a direct action (filter, clear, review, etc.)
  Pass 2 (Answer): Claude reads the selected catalog files and picks specific items
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .catalog import load_catalog_files, load_catalog_index, load_manifest, resolve_short_ids
from .db import Db
from .store import bulk_set_triage_status

DEFAULT_CLAUDE_MODEL = "claude-sonnet-4-20250514"

ALLOWED_ACTIONS = frozenset([
    "filter",
    "search",
    "semantic_search",
    "create_collection",
    "show_collection",
    "show_items",
    "show_sidebar",
    "enter_review",
    "clear_filters",
    "bulk_triage",
    "bulk_flag",
    "triage_by_query",
    "message",
])

_FALLBACK_RESPONSE: dict[str, Any] = {
    "action": "message",
    "params": {},
    "message": "I couldn't understand that request. Try things like "
    '"show keepers", "find subway tile", "show collections", or "review".',
}

_LOCAL_SEARCH_STOP_WORDS = {
    "show", "me", "the", "a", "an", "and", "or", "to", "for", "of", "in",
    "on", "at", "with", "from", "my", "our", "your", "please", "can", "you",
    "find", "look", "browse", "give", "items", "item", "inspiration", "inspirations",
    "that", "this", "these", "those", "all", "just", "top", "best", "reflect",
    "corpus", "database",
}


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def _build_routing_prompt(index_content: str) -> str:
    """Build the Pass 1 system prompt: route the query to catalog files or a direct action."""
    return f"""\
You are the assistant for Jim and Leslie's home design inspiration library.

CONTEXT:
This is a personal library of ~5,300 items saved from Pinterest, Facebook, Houzz, \
magazine scans, and photos. Jim and Leslie are building a house and have been collecting \
design inspiration. Your job is to help them browse, search, and organize their collection.

TRUST HIERARCHY (most reliable → least reliable):
1. Source boards (assets.board) — Leslie's personal curation on Pinterest/Facebook/Houzz. \
She saved items to boards intentionally. Board assignments always take precedence over \
AI tags when they conflict.
2. Human review and triage decisions — Jim/Leslie decisions made in the app are durable \
intent signals and should not be overridden casually.
3. Collections — "CB:" prefix = AI-derived representative groupings built from \
high-confidence descriptions/tagging for creative-brief \
themes (e.g., "CB: Kitchen", "CB: Master Bath"). These are useful starting points, but \
they are not deliberate human-curated highest-intent selections.
4. AI-assigned rooms/styles — Gemini analyzed the images and tagged rooms, styles, \
materials, etc. Good for enrichment and finding items across sources, but secondary \
to human curation.
5. AI labels (tags) — Useful for search but lowest priority for categorization.

Why Leslie saved things — two motivations:
1. Stylistically attractive — caught her eye for design inspiration.
2. Items of practical concern — construction choices, materials, maintenance. Not always \
"pretty" but important decisions when building a house.

When answering queries:
- Combine all sources: board items + AI-tagged items + collection items.
- Items can belong to multiple rooms — the board gives one, AI may suggest others. Both valid.
- CB: collections are AI-derived representative sets. Use them as helpful groupings, not \
as proof of deliberate human selection.

Triage vocabulary (users may say any of these — map to the right status):
- "keeper" / "thumbs up" / "love it" / "star" / "like" / "yes" → status: keeper
- "hidden" / "thumbs down" / "not interested" / "reject" / "nope" / "trash" → status: hidden
- "pending" / "undecided" / "reset" → status: pending (null)

Organization:
- Sources: pinterest, facebook, houzz, scan (clips)
- Clip subtypes under source=scan: scan, photo, video (use content_kind filter for subtype)
- Dimensions: room (kitchen, bathroom, bedroom…), style (modern, farmhouse…), \
magazine, other (non-home items like exercise, food, workout)
- Collections are deliberate working subsets. "CB:" prefix = AI-derived representative \
sets for creative-brief themes. Browse source boards through assets.board metadata, not \
through historical mirror collections.
- Most items have AI labels (rooms, styles, materials, colors) from Gemini image analysis. \
The AI description is often more useful than the original pin title.

PERSONALITY:
Be warm, concise, and enthusiastic about their project. You're a helpful design \
librarian who genuinely enjoys their collection. Keep responses to 1-2 sentences. \
When finding items, you might add a brief encouraging note like "Great taste!" or \
"These are lovely." Don't be over-the-top — just friendly and helpful.

Given the user's query, decide what to do. Return ONLY a JSON object.

If the query is a NAVIGATION action (filter, triage, review, create, clear, sidebar), \
return the action directly — no catalog files needed:

{{"action": "<action_name>", "params": {{...}}, "message": "..."}}

Available direct actions:
- filter: Set browse filters. params: source?, board?, content_kind? ("scan"|"photo"|"video"), triage_status? ("keeper"|"hidden"|"pending"|"needs-comment"), q?, collection_id?
- search: Keyword search. params: q (1-2 words max)
- semantic_search: AI similarity search (requires Gemini API — use sparingly). params: q \
ONLY as a last resort for abstract queries with NO matching catalog category. \
NEVER use for room/style queries — ALWAYS route to catalog files instead (room/*.md, style/*.md).
- create_collection: Create collection. params: name
- show_collection: Show a collection. params: name (fuzzy match)
- show_sidebar: Populate sidebar. params: type ("collections"|"boards"|"sources"), source? (for boards)
- enter_review: Start triage review. No params.
- clear_filters: Reset all filters. No params.
- bulk_triage: Mark all currently visible/selected items. params: status ("keeper"|"hidden"|null). \
Use when user says "keep these", "keep selected", "hide these", "hide selected", "love these", etc.
- bulk_flag: Flag currently visible/selected items for review (e.g. wrong thumbnail). No params. \
Use when user says "flag these", "flag selected", "mark for review", "flag these for review".
- triage_by_query: Find items from catalog AND set their triage status in one step. \
Use when the user says things like "mark all exercise items as hidden" or "thumbs down everything in miscellaneous." \
Return: {{"route": true, "triage_status": "hidden", "files": ["other/exercise.md"], "message": "Marking exercise items as hidden…"}}
- message: Just respond with text. Use this for greetings, questions about the library, \
explanations, or when the user is just chatting. Do NOT change the grid — only talk back.

If the query needs ITEM-LEVEL search (find specific items, pick items matching criteria), \
return a routing response telling us which catalog files to read:

{{"route": true, "files": ["pinterest/kitchen.md"], "message": "Looking through kitchen items…"}}

Rules:
- Pick at most 3 catalog files. Choose the most relevant based on the topics column.
- ALWAYS route to catalog files when the query mentions a room (kitchen, bathroom, bedroom, etc.) \
or style (modern, farmhouse, traditional, etc.) — the catalog has dedicated files for these.
- For queries like "kitchen style" → route to room/kitchen.md + style files. \
For "modern bathrooms" → route to room/bathroom.md + style/modern.md. NEVER use semantic_search for these.
- The ENTIRE library is home design inspiration. Generic requests like "show home design" → clear_filters.
- For "show collections" / "what collections do you have" → show_sidebar with type=collections.
- For "show boards" / "what boards are there" → show_sidebar with type=boards.
- For source-specific requests ("show pinterest", "facebook items") → filter with source.
- For triage requests ("show keepers", "hidden items") → filter with triage_status.
- Only use "route" when the user wants to find SPECIFIC items by content/description.
- Keep search queries to 1-2 specific words.
- For conversational messages ("hi", "thanks", "how many items?", "what can you do?") → use "message" action.
- Include a friendly, concise message in every response.

{index_content}"""


def _build_answer_prompt() -> str:
    """Build the Pass 2 system prompt: pick items from catalog data."""
    return """\
You are a design librarian helping Jim and Leslie find items in their inspiration collection.

Each item is formatted as:
- {id8} | {description} | [{labels}]

The 8-character code at the start is the item ID.

Your job: scan the items and return the ones matching the user's request.
Return ONLY a JSON object:

{"action": "show_items", "params": {"ids": ["a7ae6384", "b9c64c0b", ...]}, "message": "Found N items — nice picks!"}

Rules:
- Return at most 50 item IDs.
- Match items by their description text and labels.
- If many items match, pick the most relevant ones and mention the total in your message.
- If nothing matches, say so and suggest what IS available.
- Keep your message warm and concise (1-2 sentences).
- Items may appear in both a personal board AND an AI-assigned room/style. \
Board placement is Leslie's intentional curation; AI tags are enrichment.
- Return ONLY the JSON object. No markdown, no extra text."""


def _build_triage_answer_prompt(triage_status: str) -> str:
    """Build the Pass 2 system prompt for triage-by-query: find ALL matching items."""
    status_label = {"keeper": "keepers", "hidden": "hidden"}.get(triage_status, triage_status)
    return f"""\
You are a design librarian helping organize Jim and Leslie's inspiration collection.

Each item is formatted as:
- {{id8}} | {{description}} | [{{labels}}]

The 8-character code at the start is the item ID.

Your job: find ALL items matching the user's criteria and return their IDs so they \
can be marked as {status_label}. Be thorough — include every match you can find.

Return ONLY a JSON object:

{{"action": "triage_by_query", "params": {{"ids": ["a7ae6384", "b9c64c0b", ...]}}, "message": "Found N items to mark as {status_label}."}}

Rules:
- Return ALL matching item IDs (up to 500). Be thorough, not selective.
- Match items by their description text and labels.
- If nothing matches, say so in the message and return an empty ids list.
- Return ONLY the JSON object. No markdown, no extra text."""


# ---------------------------------------------------------------------------
# Claude API helper
# ---------------------------------------------------------------------------

def _claude_messages(
    *,
    api_key: str,
    model: str,
    system_prompt: str,
    user_message: str,
    max_tokens: int = 1024,
    timeout_s: float = 15.0,
) -> dict[str, Any]:
    """Call the Claude Messages API via raw urllib."""
    url = "https://api.anthropic.com/v1/messages"
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_message}],
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", errors="ignore")
        except Exception:
            pass
        raise RuntimeError(f"Claude HTTP {e.code}: {detail}") from e


def _is_timeout_error(err: Exception) -> bool:
    msg = str(err).lower()
    return "timed out" in msg or "timeout" in msg


def _claude_messages_with_retry(
    *,
    api_key: str,
    model: str,
    system_prompt: str,
    user_message: str,
    max_tokens: int,
    timeout_s: float,
) -> dict[str, Any]:
    timeouts = [max(1.0, float(timeout_s)), max(float(timeout_s) + 10.0, float(timeout_s) * 1.7)]
    last_err: Exception | None = None
    for i, attempt_timeout in enumerate(timeouts):
        try:
            return _claude_messages(
                api_key=api_key,
                model=model,
                system_prompt=system_prompt,
                user_message=user_message,
                max_tokens=max_tokens,
                timeout_s=attempt_timeout,
            )
        except Exception as e:  # pragma: no cover - covered via process_chat_message fallback behavior
            last_err = e
            if not _is_timeout_error(e) or i == len(timeouts) - 1:
                raise
    if last_err:
        raise last_err
    raise RuntimeError("Claude call failed unexpectedly")


def _clean_local_search_terms(user_message: str) -> str:
    words = re.findall(r"[a-z0-9]+", (user_message or "").lower())
    kept = [
        w for w in words
        if len(w) > 1 and not w.isdigit() and w not in _LOCAL_SEARCH_STOP_WORDS
    ]
    if not kept:
        return ""
    return " ".join(kept[:4]).strip()


def _local_chat_fallback(user_message: str, *, error: str = "") -> dict[str, Any]:
    text = " ".join((user_message or "").strip().lower().split())
    if not text:
        return dict(_FALLBACK_RESPONSE)

    source_hint = ""
    if "pinterest" in text:
        source_hint = "pinterest"
    elif "facebook" in text:
        source_hint = "facebook"
    elif "houzz" in text:
        source_hint = "houzz"
    elif any(tok in text for tok in ("clip", "clips", "scan", "scans", "photo", "photos", "video", "videos")):
        source_hint = "scan"

    if any(p in text for p in ("clear filters", "clear filter", "reset filters", "show all items", "show everything")):
        return {"action": "clear_filters", "params": {}, "message": "I reset your filters."}

    if any(p in text for p in ("show collections", "list collections", "what collections")):
        return {
            "action": "show_sidebar",
            "params": {"type": "collections"},
            "message": "Showing collections.",
        }

    if any(p in text for p in ("show boards", "list boards", "what boards")):
        params: dict[str, Any] = {"type": "boards"}
        if source_hint:
            params["source"] = source_hint
        return {
            "action": "show_sidebar",
            "params": params,
            "message": "Showing boards.",
        }

    if any(p in text for p in ("show sources", "list sources", "what sources")):
        return {"action": "show_sidebar", "params": {"type": "sources"}, "message": "Showing sources."}

    if "review" in text:
        return {"action": "enter_review", "params": {}, "message": "Starting review mode."}

    if ("keeper" in text or "keepers" in text) and any(p in text for p in ("show", "view", "filter")):
        return {"action": "filter", "params": {"triage_status": "keeper"}, "message": "Showing keepers."}

    if ("hidden" in text) and any(p in text for p in ("show", "view", "filter")):
        return {"action": "filter", "params": {"triage_status": "hidden"}, "message": "Showing hidden items."}

    if ("pending" in text) and any(p in text for p in ("show", "view", "filter")):
        return {"action": "filter", "params": {"triage_status": "pending"}, "message": "Showing pending items."}

    if "needs comment" in text:
        return {"action": "filter", "params": {"triage_status": "needs-comment"}, "message": "Showing items that need comment."}

    if any(tok in text for tok in ("video", "videos")):
        return {
            "action": "filter",
            "params": {"source": "scan", "content_kind": "video"},
            "message": "Showing clip videos.",
        }
    if any(tok in text for tok in ("photo", "photos")):
        return {
            "action": "filter",
            "params": {"source": "scan", "content_kind": "photo"},
            "message": "Showing clip photos.",
        }
    if any(tok in text for tok in ("scan", "scans", "clip", "clips")):
        return {
            "action": "filter",
            "params": {"source": "scan"},
            "message": "Showing clips.",
        }

    if source_hint and any(p in text for p in ("show", "view", "filter")):
        return {
            "action": "filter",
            "params": {"source": source_hint},
            "message": f"Showing {source_hint} items.",
        }

    create_match = re.search(r"create collection(?: called| named)?\s+(.+)$", text)
    if create_match:
        name = create_match.group(1).strip().strip("\"'")
        if name:
            return {
                "action": "create_collection",
                "params": {"name": name[:80]},
                "message": f'Creating collection "{name[:80]}".',
            }

    show_collection_match = re.search(r"(?:show|open|browse)\s+collection\s+(.+)$", text)
    if show_collection_match:
        name = show_collection_match.group(1).strip().strip("\"'")
        if name:
            return {
                "action": "show_collection",
                "params": {"name": name[:80]},
                "message": f'Showing collection "{name[:80]}".',
            }

    if ("top" in text and "reflect" in text) or ("best" in text and "library" in text):
        return {
            "action": "clear_filters",
            "params": {},
            "message": "Showing the full library so you can browse representative items.",
        }

    q = _clean_local_search_terms(user_message)
    reason = f" Dave is unavailable ({error.strip()})." if error.strip() else ""
    if not q:
        return {
            "action": "message",
            "params": {},
            "message": f"{reason} I could not extract useful keywords from that request. "
            "Try naming a room, style, source, or collection.".strip(),
        }
    return {
        "action": "search",
        "params": {"q": q},
        "message": f'{reason} Using keyword search for "{q}".'.strip(),
    }


def _extract_response_text(resp: dict[str, Any]) -> str:
    """Extract text content from a Claude API response."""
    for block in resp.get("content", []):
        if block.get("type") == "text":
            return block.get("text", "")
    return ""


def _extract_json_from_text(text: str) -> dict[str, Any] | None:
    """Extract a JSON object from Claude's response text, tolerating code fences."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        first_nl = cleaned.find("\n")
        if first_nl >= 0:
            cleaned = cleaned[first_nl + 1:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

    decoder = json.JSONDecoder()
    try:
        obj, _ = decoder.raw_decode(cleaned)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    for i, ch in enumerate(cleaned):
        if ch == "{":
            try:
                obj, _ = decoder.raw_decode(cleaned[i:])
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                continue
    return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def process_chat_message(
    db: Db,
    *,
    api_key: str,
    user_message: str,
    catalog_dir: Path | None = None,
    model: str = DEFAULT_CLAUDE_MODEL,
    timeout_s: float = 25.0,
) -> dict[str, Any]:
    """Send a chat message through the two-pass catalog flow.

    If catalog_dir is None or the catalog doesn't exist, falls back to a
    single-pass routing call (no item-level search capability).
    """
    if not user_message.strip():
        raise ValueError("Message cannot be empty")

    user_msg = user_message.strip()
    if not api_key:
        return _local_chat_fallback(user_msg, error="missing Anthropic API key")

    # Load catalog index
    index_content = None
    if catalog_dir:
        index_content = load_catalog_index(Path(catalog_dir))

    if not index_content:
        # No catalog — fall back to routing-only (no item search)
        index_content = "(Catalog not available. Only navigation actions are supported.)"

    # --- Pass 1: Route ---
    routing_prompt = _build_routing_prompt(index_content)
    try:
        resp = _claude_messages_with_retry(
            api_key=api_key,
            model=model,
            system_prompt=routing_prompt,
            user_message=user_msg,
            max_tokens=512,
            timeout_s=timeout_s,
        )
    except Exception as e:
        return _local_chat_fallback(user_msg, error=str(e))

    text = _extract_response_text(resp)
    if not text:
        return dict(_FALLBACK_RESPONSE)

    parsed = _extract_json_from_text(text)
    if not parsed:
        return {"action": "message", "params": {}, "message": text.strip()[:500]}

    # Check if this is a direct action (short-circuit — no Pass 2 needed)
    if "action" in parsed and not parsed.get("route"):
        action = parsed.get("action", "message")
        if action not in ALLOWED_ACTIONS:
            action = "message"
        return {
            "action": action,
            "params": parsed.get("params", {}),
            "message": parsed.get("message", ""),
        }

    # --- Pass 2: Read catalog files and answer ---
    routing_message = parsed.get("message", "")
    triage_status = parsed.get("triage_status")  # set for triage_by_query

    files_to_read = parsed.get("files", [])
    if not files_to_read or not catalog_dir:
        # Routing said to read files but none specified or no catalog
        return {
            "action": "message",
            "params": {},
            "message": parsed.get("message", "I couldn't find the right catalog files for that query."),
        }

    catalog_content = load_catalog_files(Path(catalog_dir), files_to_read)
    if not catalog_content:
        return {
            "action": "message",
            "params": {},
            "message": "The catalog files for that query don't exist yet.",
        }

    # Choose answer prompt based on whether this is a triage operation
    if triage_status:
        answer_prompt = _build_triage_answer_prompt(triage_status)
        max_answer_tokens = 2048  # more room for large ID lists
    else:
        answer_prompt = _build_answer_prompt()
        max_answer_tokens = 1024

    # Pass the catalog content + user question together
    answer_user_msg = f"Catalog data:\n\n{catalog_content}\n\nUser question: {user_msg}"

    try:
        resp2 = _claude_messages_with_retry(
            api_key=api_key,
            model=model,
            system_prompt=answer_prompt,
            user_message=answer_user_msg,
            max_tokens=max_answer_tokens,
            timeout_s=timeout_s,
        )
    except Exception as e:
        return _local_chat_fallback(user_msg, error=str(e))

    text2 = _extract_response_text(resp2)
    if not text2:
        return dict(_FALLBACK_RESPONSE)

    parsed2 = _extract_json_from_text(text2)
    if not parsed2:
        return {"action": "message", "params": {}, "message": text2.strip()[:500]}

    action = parsed2.get("action", "message")
    if action not in ALLOWED_ACTIONS:
        action = "message"

    result = {
        "action": action,
        "params": parsed2.get("params", {}),
        "message": parsed2.get("message", ""),
    }

    # Include routing_message for two-phase UX feedback
    if routing_message:
        result["routing_message"] = routing_message

    # Resolve short IDs to full UUIDs
    if action in ("show_items", "triage_by_query") and catalog_dir:
        manifest = load_manifest(Path(catalog_dir))
        if manifest:
            short_ids = result["params"].get("ids", [])
            full_ids = resolve_short_ids(manifest, short_ids)
            result["params"]["ids"] = full_ids

    # Execute triage_by_query server-side: mark matching items
    if action == "triage_by_query" and triage_status:
        full_ids = result["params"].get("ids", [])
        if full_ids:
            count = bulk_set_triage_status(
                db, full_ids, triage_status,
                reason=f"chat triage: {result.get('message', '')[:200]}",
                actor="ai-chat",
            )
            status_label = {"keeper": "keepers", "hidden": "hidden"}.get(triage_status, triage_status)
            result["message"] = f"Done! Marked {count} item{'s' if count != 1 else ''} as {status_label}."
        else:
            result["action"] = "message"
            result["message"] = result.get("message") or "I couldn't find items matching that criteria."

    return result
