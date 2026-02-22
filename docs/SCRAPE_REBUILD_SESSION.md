# Session Log: Scrape-First Rebuild (Parts 0–7)

**Date:** 2026-02-22
**Branch:** `feat/scrape-rebuild-part0`
**PRs:** pending

## Summary

Full scrape-first rebuild of the Inspirations app per `docs/SCRAPE_REBUILD_SPEC.md`.
Replaced ZIP/DOCX importers with browser-scraped JSON importers, added a triage
workflow to the data model and frontend, and rewrote the entire frontend.

## Parts Completed

### Part 0 — Dead code cleanup
- Deleted `importers/pinterest_crawl.py`, `importers/apify_zip.py`, `importers/facebook_docx.py`
- Deleted matching test files
- Pruned stale CLI sub-commands (`import pinterest`, `import facebook` ZIP/DOCX variants)

### Part 1 — Schema changes (`db.py`)
Added 13 new columns to `assets`:

| Column | Type | Purpose |
|---|---|---|
| `triage_status` | TEXT | null=pending, 'keeper', 'hidden' |
| `triage_at` | TEXT | ISO timestamp of last triage action |
| `needs_annotation` | INT | 1 when "Comment later" checked in review |
| `scrape_raw` | TEXT | JSON blob of raw scrape input |
| `source_url` | TEXT | Canonical URL of source item page |
| `seo_alt_text` | TEXT | Scraped alt/title text from source |
| `creator_handle` | TEXT | @handle from scrape |
| `board_section` | TEXT | Sub-board section (Pinterest) |
| `reaction_count` | INT | Like/reaction count from source |
| `comment_count` | INT | Comment count from source |
| `save_count` | INT | Save/bookmark count from source |
| `scrape_date` | TEXT | ISO date the scrape was captured |
| `scrape_version` | TEXT | Scraper tool version tag |

Added `ix_assets_triage` index on `(triage_status, triage_at)`.

### Part 2 — Pinterest scrape importer (`importers/pinterest_scrape.py`)
- `import_pinterest_scrape(db, json_path, store_dir, image_map_path=None, download_missing=True, limit=0)`
- Reads a JSON array of pin objects from a browser-scraped export
- Maps fields: `id`, `title`, `description`, `link`, `board_name`, `board_section`, `image_url`, `creator_handle`, `save_count`, `scrape_date`
- Supports an optional `image_map` JSON for pre-downloaded local files (avoids re-downloading)
- Idempotent: updates existing records if `source_id` matches

### Part 3 — Facebook scrape importer (`importers/facebook_scrape.py`)
- `import_facebook_scrape(db, json_dir, store_dir, limit=0)`
- Reads a directory of per-collection JSON files from a browser-scraped Facebook Saved export
- Parses saved posts: title, URL, description, image_url, reaction/save counts, date
- Uses collection filename as `board_name`; upserts `source_collections` rows
- Idempotent on `source_id = sha256(url + title)`

### Part 4 — CLI commands (`cli.py`)
- `import pinterest-scrape` → `cmd_import_pinterest_scrape`
- `import facebook-scrape` → `cmd_import_facebook_scrape`
- `rebuild-db` → `cmd_rebuild_db` (drop + recreate schema, re-import from store)

### Part 5 — Triage backend (`store.py`, `server.py`)
- `list_assets()` gains `triage_status`, `needs_annotation` filter params
- SELECT extended: `triage_status`, `needs_annotation`, `source_url`, `seo_alt_text`
- `PATCH /api/assets/{id}/triage` endpoint: `{ "status": "keeper"|"hidden"|null, "needs_annotation": 0|1 }`
- Server parses `needs_annotation` boolean query param via `_parse_bool_param()`

### Part 6 — Frontend full rewrite
Complete rewrite of `app/index.html`, `app/styles.css`, `app/app.js`.

**Layout changes:**
- Two-column layout (240px sidebar + 1fr main) replacing old three-column with tray
- Tray sidebar removed; Explorer view removed from main page (standalone URL if needed)

**New sidebar:**
- Sources chips (dynamic from facets API)
- Status chips: All / Pending / Keepers ✓ / Hidden / Needs comment 💬
- Boards list (chips)
- Collections list (chips) + New Collection button

**Browse view:**
- Grid of cards with triage badges (green dot=keeper, red=hidden, gold=needs-comment)
- Load More pagination

**Review mode (card-by-card triage):**
- Triggered via Review button or `[Review]` chat command
- Shows full image + metadata one item at a time
- Actions: Keep (♥), Hide (✗), Skip (→)
- "Comment later" checkbox sets `needs_annotation=1`
- Keyboard shortcuts: `→`/`K` keep, `←`/`S` hide, `Space`/`↓` skip, `Z` undo, `C` toggle comment
- Undo stack (last 20 actions)
- Completion screen with session stats + "Review skipped" option

**Chat bar:**
- Pattern-matching intent detection (no AI dependency)
- Supports: create collection, show keepers/pending/hidden, show collection by name, search/find, enter review

**Detail modal:**
- Keep ✓ / Hide ✗ triage buttons (toggle: click active = reset to pending)
- Source site link row (if `source_url` present)
- Full point-based annotation system preserved (same DOM IDs)
- Scan page navigation preserved
- Print button preserved

**Design:**
- Warm cream theme: `--bg: #faf8f5`, `--panel: #f5f2ed`, gold accent `#b8860b`
- DM Sans font (Google Fonts)
- Rounded cards (12px radius)

### Part 7 — Tests
- `tests/test_pinterest_scrape_import.py` — 8 tests covering import, dedup, image_map, limit
- `tests/test_facebook_scrape_import.py` — 7 tests covering import, multi-collection, dedup, limit
- `tests/test_triage.py` — 9 tests covering triage API (keep, hide, reset, needs_annotation, unknown ID)

## Test Results

```
125 tests, 0 failures, 0 errors
ruff: no issues
```

## Commits

```
2ad5361 feat: Part 0 — delete old importers and prune CLI (scrape rebuild)
b296ac9 feat: scrape-first rebuild — Parts 1–7
```
