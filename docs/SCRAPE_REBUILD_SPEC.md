# Scrape-First Rebuild — Implementation Spec for Sonnet

## What This Is

We're rebuilding the Inspirations database from scratch using browser-scraped data as the primary source. Opus (the other agent) will scrape Leslie's Pinterest and Facebook accounts via the browser and produce JSON data files. Your job is to:

0. Delete dead code from the old import pipeline
1. Add new DB columns for the richer scraped metadata
2. Write two new importers that consume Opus's JSON output
3. Add CLI commands to orchestrate the rebuild
4. Build a triage UI for keeper/hide curation

**Constraint reminder:** stdlib-only Python (D001), vanilla JS frontend, unittest (no pytest).

## Part 0: Dead Code Cleanup

The old importers (Apify ZIP, Facebook data export ZIP, Word doc) are replaced by the new browser-scrape importers. Remove all dead code first so there's no confusion.

### Delete these files entirely:

| File | What it was | Lines |
|---|---|---|
| `src/inspirations/importers/pinterest_crawler.py` | Pinterest Apify ZIP importer | 121 |
| `src/inspirations/importers/facebook_saved.py` | Facebook data export ZIP importer | 308 |
| `src/inspirations/importers/facebook_docx.py` | Facebook Word doc importer | 410 |
| `tests/test_pinterest_import.py` | Tests for Apify importer | 44 |
| `tests/test_facebook_import.py` | Tests for FB ZIP importer | 159 |
| `tests/test_facebook_docx_import.py` | Tests for DOCX importer | 442 |

### Prune `src/inspirations/cli.py`:

1. **Delete imports** for old importers (near top of file):
   - `from .importers.facebook_docx import import_facebook_docx`
   - `from .importers.facebook_saved import import_facebook_saved_zip`
   - `from .importers.pinterest_crawler import import_pinterest_crawler_zip`

2. **Delete the 3 old command functions:**
   - `cmd_import_pinterest()` — the function that calls `import_pinterest_crawler_zip`
   - `cmd_import_facebook()` — the function that calls `import_facebook_saved_zip`
   - `cmd_import_facebook_docx()` — the function that calls `import_facebook_docx`

3. **Delete the 3 old subparser definitions** (in the argparse setup section):
   - The `import pinterest` subparser and its `--zip`, `--download`, `--limit` arguments
   - The `import facebook` subparser and its `--zip`, `--download`, `--retry-non-image`, `--limit` arguments
   - The `import-facebook-docx` subparser and its `--docx`, `--collections-filter`, `--limit` arguments

4. **Delete the dispatch entries** in the `main()` function that route to the deleted command functions.

### Prune `src/inspirations/server.py`:

Remove the import of the old facebook_saved module if it exists. Check for any references to the deleted importers — there shouldn't be any, but verify.

### Update `src/inspirations/importers/__init__.py`:

If this file imports from the deleted modules, remove those imports. If it's empty or doesn't exist, no action needed.

### Update `CLAUDE.md`:

In the "Common Commands" section, remove the old `import pinterest`, `import facebook` subcommands from the subcommand list. In the "Architecture" section under `importers/`, update to say:
- `scans.py` — scan/PDF import (unchanged)
- `pinterest_scrape.py` — Pinterest import from browser scrape JSON (new)
- `facebook_scrape.py` — Facebook import from browser scrape JSON (new)

### Verify after cleanup:

```bash
# All tests should still pass (only old importer tests were deleted)
PYTHONPATH=src python3 -m unittest discover -s tests -v

# Lint should pass
ruff check src tests

# CLI should still work (scan import, serve, ai, thumbs, export commands all unaffected)
PYTHONPATH=src python3 -m inspirations --help
```

### Keep these (still needed):

- `src/inspirations/storage.py` — image download utilities (used by new Pinterest importer)
- `src/inspirations/ai.py` — Gemini tagging/embedding (used post-import)
- `src/inspirations/export.py` — HTML gallery export
- `src/inspirations/explorer_layout.py` — graph/cluster layout
- `src/inspirations/importers/scans.py` — scan import (unchanged)
- `tools/*` — all operational scripts (9 files, all still valid)
- All other `tests/test_*.py` files not listed above

## Part 1: Schema Changes

**File:** `src/inspirations/db.py`

Add these columns to the `assets` table via `_ensure_columns()` in `ensure_schema()`:

```python
_ensure_columns(db, "assets", {
    # Rich metadata from page scrapes
    "source_url": "text",           # external URL the pin/post links to
    "seo_alt_text": "text",         # Pinterest's AI-generated image description
    "closeup_desc": "text",         # Pinterest's extended description from source site
    "hashtags": "text",             # comma-separated hashtag strings
    "dominant_color": "text",       # hex color code (e.g. "#cbc1b4")
    "image_width": "integer",       # original image pixel width
    "image_height": "integer",      # original image pixel height
    "post_text": "text",            # full Facebook post body
    "engagement_json": "text",      # JSON string: {"likes":N,"comments":N,"shares":N,"repins":N,"views":N}
    "scrape_json": "text",          # overflow JSON blob for fields we don't have columns for

    # Triage workflow
    "triage_status": "text",        # null = pending, 'keeper', 'hidden'
    "triage_at": "text",            # ISO timestamp of last triage action
    "needs_annotation": "integer",  # 0 or 1; set during triage review when user checks "Comment later"
})
```

Add index after table creation:

```python
db.exec("create index if not exists ix_assets_triage on assets(triage_status);")
```

Also add `triage_status` and `triage_at` to `_backfill_metadata()` skip list (they're user-set, not auto-derived).

## Part 2: Pinterest Scrape Importer

**Create:** `src/inspirations/importers/pinterest_scrape.py`

### Input Format

Reads `data/scrape/pinterest_scrape.json` — a JSON array of pin objects. Each pin:

```json
{
  "pin_id": "87116574018913475",
  "pin_url": "https://www.pinterest.com/pin/87116574018913475/",
  "board_name": "furniture",
  "title": "Lee Industries: 1601-03 Sofa",
  "description": "Lee Industries - Sofa",
  "seo_alt_text": "a white couch with four pillows on it's back...",
  "closeup_desc": "Lee is a manufacturer that reveres quality...",
  "source_url": "http://www.leeindustries.com/style_detail/lee/...",
  "source_domain": "leeindustries.com",
  "rich_metadata": {"site_name": "Lee Industries", "type": "richpindataview"},
  "dominant_color": "#cbc1b4",
  "hashtags": ["furniture", "sofa"],
  "created_at": "Thu, 13 Sep 2012 11:41:35 +0000",
  "image_url": "https://i.pinimg.com/originals/1b/d3/85/1bd385a83de043b0c83ec1087c8846b6.jpg",
  "image_width": 150,
  "image_height": 100,
  "repin_count": 42,
  "comment_count": 3
}
```

### Image Matching

Also reads an optional `data/scrape/pinterest_image_map.json`:

```json
{
  "https://i.pinimg.com/originals/1b/d3/85/1bd385a83de043b0c83ec1087c8846b6.jpg": {
    "stored_path": "store/originals/pinterest/c1ca090f-5ff3-44b7-8ad6-13d362628c36.jpg",
    "sha256": "abc123..."
  }
}
```

If the scraped pin's `image_url` exists in the image map, **reuse the existing file** — set `stored_path` and `sha256` from the map. If not in the map, download via `storage.download_url_to_store()` (existing function).

### Function Signature

```python
def import_pinterest_scrape(
    db: Db,
    json_path: Path,
    store_dir: Path,
    image_map_path: Path | None = None,
    download_missing: bool = True,
    limit: int = 0,
) -> dict[str, Any]:
    """Import pins from browser scrape JSON, matching existing images by URL."""
```

### Field Mapping

| Scrape field | → Asset column | Notes |
|---|---|---|
| `pin_url` | `source_ref` | Primary key for dedup |
| `"pinterest"` | `source` | Hardcoded |
| `title` | `title` | |
| `description` | `description` | |
| `board_name` | `board` | |
| `created_at` | `created_at` | |
| `image_url` | `image_url` | |
| `source_url` | `source_url` | **NEW** — external link |
| `source_domain` | `source_domain` | |
| `seo_alt_text` | `seo_alt_text` | **NEW** |
| `closeup_desc` | `closeup_desc` | **NEW** |
| `dominant_color` | `dominant_color` | **NEW** |
| `hashtags` (array) | `hashtags` | Join with `,` — **NEW** |
| `image_width` | `image_width` | **NEW** |
| `image_height` | `image_height` | **NEW** |
| `{repin_count, comment_count}` | `engagement_json` | JSON string — **NEW** |
| `rich_metadata` (object) | `scrape_json` | JSON string — **NEW** |
| `"image"` | `media_status` | Always image for Pinterest |
| `"pin"` | `content_kind` | |

Use `insert or ignore` with `(source, source_ref)` uniqueness, same pattern as `pinterest_crawler.py`.

### Return Value

```python
return {
    "source": "pinterest",
    "json_path": str(json_path),
    "total_in_json": N,
    "imported": N,
    "skipped_no_url": N,
    "images_matched": N,      # from image map
    "images_downloaded": N,    # newly fetched
    "images_failed": N,        # download errors
    "total_assets_for_source": N,
}
```

## Part 3: Facebook Scrape Importer

**Create:** `src/inspirations/importers/facebook_scrape.py`

### Input Format

Reads all `data/scrape/facebook_scrape_*.json` files (glob pattern). Each file is a JSON array:

```json
[{
  "post_url": "https://www.facebook.com/watch/?ref=saved&v=898670132731451",
  "collection_name": "furniture",
  "post_text": "Replying to allie.kerryn — here are my top furniture sourcing tips...",
  "creator_name": "Paul Perez",
  "creator_url": "https://www.facebook.com/paulperez",
  "hashtags": ["interiordesigntips", "furnitureshopping"],
  "date": "December 18, 2025",
  "content_type": "reel",
  "engagement": {"likes": 687, "comments": 16, "views": 61000},
  "images": [
    {
      "base64": "data:image/jpeg;base64,/9j/4AAQ...",
      "width": 720,
      "height": 1280
    }
  ],
  "unavailable": false
}]
```

### Image Handling

For each item with `images` array:
1. Take the **first** image (primary)
2. Strip the `data:image/jpeg;base64,` prefix
3. Decode base64 → bytes
4. Compute SHA256 of the bytes
5. Save to `store/originals/facebook/{sha256}.jpg`
6. If file already exists (same hash), skip writing but still set `stored_path`
7. Set `media_status = "image"`

For items with `images: []` or `images: null` or `unavailable: true`:
- Set `media_status = "metadata_only"` if there's post_text
- Set `media_status = "metadata_only"` if unavailable (post was deleted)

### Function Signature

```python
def import_facebook_scrape(
    db: Db,
    json_dir: Path,
    store_dir: Path,
    limit: int = 0,
) -> dict[str, Any]:
    """Import Facebook saved items from browser scrape JSON files with base64 images."""
```

### Field Mapping

| Scrape field | → Asset column | Notes |
|---|---|---|
| `post_url` | `source_ref` | Primary key for dedup |
| `"facebook"` | `source` | Hardcoded |
| First 200 chars of `post_text` | `title` | Truncate with `...` if longer |
| `post_text` | `description` | Full text for search |
| `post_text` | `post_text` | **NEW** — full body |
| `collection_name` | `board` | |
| `date` | `created_at` | Parse "December 18, 2025" → ISO |
| `creator_name` | `creator_name` | |
| `hashtags` (array) | `hashtags` | Join with `,` — **NEW** |
| `engagement` (object) | `engagement_json` | JSON string — **NEW** |
| `content_type` | `content_kind` | reel / post / link |
| image base64 decoded | → file on disk, path in `stored_path` | |
| SHA256 of image bytes | `sha256` | |
| `images[0].width` | `image_width` | **NEW** |
| `images[0].height` | `image_height` | **NEW** |
| `"facebook.com"` | `source_domain` | Hardcoded |

### Date Parsing

Facebook dates come as "December 18, 2025" or "January 3, 2026" etc. Parse with:
```python
from datetime import datetime
dt = datetime.strptime(date_str, "%B %d, %Y")
```
Store as ISO format. If parsing fails, set `created_at = None`.

### Return Value

```python
return {
    "source": "facebook",
    "json_dir": str(json_dir),
    "files_read": N,
    "total_in_json": N,
    "imported": N,
    "images_saved": N,
    "metadata_only": N,
    "unavailable": N,
    "total_assets_for_source": N,
}
```

## Part 4: CLI Commands

**File:** `src/inspirations/cli.py`

### `import pinterest-scrape`

```
PYTHONPATH=src python3 -m inspirations import pinterest-scrape \
  --json data/scrape/pinterest_scrape.json \
  [--image-map data/scrape/pinterest_image_map.json] \
  [--no-download] \
  [--limit N]
```

Implementation: Call `import_pinterest_scrape()` from the new importer, print JSON result.

### `import facebook-scrape`

```
PYTHONPATH=src python3 -m inspirations import facebook-scrape \
  --json-dir data/scrape/ \
  [--limit N]
```

Implementation: Call `import_facebook_scrape()` from the new importer, print JSON result.

### `rebuild-db`

```
PYTHONPATH=src python3 -m inspirations rebuild-db \
  [--pinterest-json data/scrape/pinterest_scrape.json] \
  [--pinterest-image-map data/scrape/pinterest_image_map.json] \
  [--facebook-json-dir data/scrape/] \
  [--scan-inbox imports/scans/inbox/]
```

Orchestration command that:
1. Backs up current DB to `data/backups/pre-rebuild-{timestamp}.sqlite`
2. Deletes current DB
3. Calls `ensure_schema()` to create fresh DB
4. If `--scan-inbox` provided: runs scan import from existing inbox directory
5. If `--pinterest-json` provided: runs Pinterest scrape import
6. If `--facebook-json-dir` provided: runs Facebook scrape import
7. Runs `generate_thumbnails()` for all sources
8. Prints summary JSON

Each step prints progress to stderr so the user sees what's happening.

## Part 5: Triage Backend

### Store layer changes

**File:** `src/inspirations/store.py`

#### Modify `list_assets()`

Add parameter: `triage_status: str = ""`

```python
if triage_status:
    statuses = [s.strip() for s in triage_status.split(",") if s.strip()]
    if "pending" in statuses:
        # pending = NULL triage_status
        others = [s for s in statuses if s != "pending"]
        if others:
            clauses.append(
                "(a.triage_status is null or a.triage_status in (%s))"
                % ",".join(["?"] * len(others))
            )
            params.extend(others)
        else:
            clauses.append("a.triage_status is null")
    else:
        clauses.append("a.triage_status in (%s)" % ",".join(["?"] * len(statuses)))
        params.extend(statuses)
```

Also: when `include_hidden` is False (default), exclude items with `triage_status = 'hidden'` in addition to the existing Hidden collection logic:

```python
if not include_hidden:
    clauses.append("(a.triage_status is null or a.triage_status != 'hidden')")
    # existing Hidden collection exclusion stays too
```

#### Add `set_triage_status()`

```python
def set_triage_status(db: Db, asset_id: str, status: str, needs_annotation: int | None = None) -> None:
    """Set triage status for a single asset. status: 'keeper' | 'hidden' | None (resets to pending).
    needs_annotation: 0 or 1, set when user checks 'Comment later' during review."""
    now = datetime.now(timezone.utc).isoformat()
    if status is None:
        db.exec("update assets set triage_status = null, triage_at = ?, needs_annotation = 0 where id = ?",
                (now, asset_id))
    else:
        annotation_val = needs_annotation if needs_annotation is not None else 0
        db.exec("update assets set triage_status = ?, triage_at = ?, needs_annotation = ? where id = ?",
                (status, now, annotation_val, asset_id))
```

#### Add `bulk_set_triage_status()`

```python
def bulk_set_triage_status(db: Db, asset_ids: list[str], status: str) -> int:
    """Set triage status for multiple assets. Returns count updated."""
    now = datetime.now(timezone.utc).isoformat()
    if not asset_ids:
        return 0
    placeholders = ",".join(["?"] * len(asset_ids))
    if status is None:
        db.exec(f"update assets set triage_status = null, triage_at = ? where id in ({placeholders})",
                (now, *asset_ids))
    else:
        db.exec(f"update assets set triage_status = ?, triage_at = ? where id in ({placeholders})",
                (status, now, *asset_ids))
    return len(asset_ids)
```

#### Add `triage_stats()`

```python
def triage_stats(db: Db) -> dict[str, Any]:
    """Return triage progress stats, overall and per-board."""
    rows = db.query("""
        select
            board,
            count(*) as total,
            sum(case when triage_status = 'keeper' then 1 else 0 end) as keepers,
            sum(case when triage_status = 'hidden' then 1 else 0 end) as hidden,
            sum(case when triage_status is null then 1 else 0 end) as pending,
            sum(case when needs_annotation = 1 then 1 else 0 end) as needs_comment
        from assets
        group by board
        order by count(*) desc
    """)
    boards = [dict(r) for r in rows]
    totals = db.query("""
        select
            count(*) as total,
            sum(case when triage_status = 'keeper' then 1 else 0 end) as keepers,
            sum(case when triage_status = 'hidden' then 1 else 0 end) as hidden,
            sum(case when triage_status is null then 1 else 0 end) as pending,
            sum(case when needs_annotation = 1 then 1 else 0 end) as needs_comment
        from assets
    """)
    overall = dict(totals[0]) if totals else {}
    return {"overall": overall, "boards": boards}
```

#### Modify `list_facets()`

Add `triage_statuses` to the facets response, same pattern as `media_statuses`:

```python
triage_rows = db.query(
    f"""select coalesce(a.triage_status, 'pending') as val, count(*) as cnt
        from assets a {join_sql}
        {where}
        group by coalesce(a.triage_status, 'pending')
        order by cnt desc""",
    params,
)
facets["triage_statuses"] = [{"value": r["val"], "count": r["cnt"]} for r in triage_rows]
```

### Server layer changes

**File:** `src/inspirations/server.py`

Add these endpoints:

#### `POST /api/assets/{id}/triage`

```python
# In do_POST handler:
m = re.match(r"^/api/assets/([^/]+)/triage$", path)
if m:
    asset_id = m.group(1)
    body = _json_body(self)
    status = body.get("status")  # "keeper" | "hidden" | None
    needs_annotation = body.get("needs_annotation")  # 0 | 1 | None
    if status not in ("keeper", "hidden", None):
        self._json_error(400, "status must be 'keeper', 'hidden', or null")
        return
    set_triage_status(db, asset_id, status, needs_annotation=needs_annotation)
    self._json_response({"ok": True})
    return
```

#### `POST /api/assets/triage/bulk`

```python
# Body: {"ids": ["uuid1", "uuid2", ...], "status": "keeper"|"hidden"|null}
if path == "/api/assets/triage/bulk":
    body = _json_body(self)
    ids = body.get("ids", [])
    status = body.get("status")
    if status not in ("keeper", "hidden", None):
        self._json_error(400, "status must be 'keeper', 'hidden', or null")
        return
    count = bulk_set_triage_status(db, ids, status)
    self._json_response({"updated": count})
    return
```

#### `GET /api/triage/stats`

```python
if path == "/api/triage/stats":
    stats = triage_stats(db)
    self._json_response(stats)
    return
```

#### Modify existing `GET /api/assets`

Add `triage_status` query parameter support, passing through to `list_assets()`.

#### Modify existing `GET /api/facets`

The modified `list_facets()` already returns `triage_statuses` — just ensure the server passes it through.

## Part 6: Frontend — Collection Browsing, Review, and Collection Chat

### Design Philosophy

The app should feel **friendly and warm, not techy**. Think of it as a design inspiration tool for someone who doesn't want to think about databases or filters. The three core experiences are:

1. **Browse** — See your collections as beautiful tile grids
2. **Review** — Card-by-card triage with simple keep/hide/skip actions
3. **Chat** — A natural-language prompt to manage collections conversationally

### Visual Direction

- **Warm light theme** — cream/off-white backgrounds (`#faf8f5`), warm gold accents (`#b8860b`), soft shadows
- **Clean card grid** — images are the hero, minimal chrome
- **Friendly typography** — DM Sans or similar rounded sans-serif, generous spacing
- **No jargon** — no "assets", "triage status", "facets". Use "items", "collections", "keep", "hide"
- **Responsive** — works well on laptop and iPad

### Color Palette (CSS variables)

```css
:root {
    --bg: #faf8f5;
    --panel: #ffffff;
    --text: #2c2c2c;
    --text-muted: #888;
    --accent: #b8860b;       /* warm gold */
    --accent-hover: #9a7209;
    --keep-green: #22c55e;
    --hide-red: #ef4444;
    --border: #e8e4de;
    --shadow-sm: 0 1px 3px rgba(0,0,0,0.06);
    --shadow-md: 0 4px 12px rgba(0,0,0,0.08);
    --radius: 12px;
    --font: 'DM Sans', system-ui, sans-serif;
}
```

Load DM Sans from Google Fonts: `@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600&display=swap');`

### App Layout

Two-column layout (not three). Simpler than the old app.

```
┌─────────────────────────────────────────────┐
│  Logo/Title              [chat prompt bar]   │
├──────────┬──────────────────────────────────┤
│          │                                   │
│ Sidebar  │   Main content area               │
│          │   (tile grid or review card)       │
│ Sources  │                                   │
│ Boards   │                                   │
│ Status   │                                   │
│          │                                   │
│          │                                   │
│          │                                   │
│          │                                   │
│          │                                   │
│          │                                   │
│          │                                   │
└──────────┴──────────────────────────────────┘
```

### State (`app.js`)

```javascript
const state = {
    // Navigation
    view: "browse",            // "browse" | "review"
    currentBoard: null,        // board filter (or null = all)
    currentSource: null,       // source filter

    // Review mode
    reviewItems: [],           // assets to review
    reviewIndex: 0,            // current position
    reviewHistory: [],         // undo stack

    // Collections chat
    chatHistory: [],           // [{role: "user"|"system", text: "..."}]

    // Filter state
    triageFilter: "all",       // "all" | "pending" | "keeper" | "hidden"
};
```

### The Chat Prompt

A text input bar in the top header area. This is the primary way to manage collections:

```html
<div class="chat-bar">
    <input type="text" id="chatInput"
        placeholder="Try: 'make a new collection called Kitchen Favorites' or 'move all bathroom items here'"
    />
    <button id="chatSend" class="chat-send-btn">→</button>
</div>
```

**Chat operations to support (pattern matching, not AI):**

| Intent | Example phrases | Action |
|---|---|---|
| Create collection | "make a new collection called Kitchen" | `POST /api/collections` with name |
| Show collection | "show me Kitchen Favorites" | Filter grid to that collection |
| Move items | "move all kitchen items to Kitchen Favorites" | Bulk add items matching board to collection |
| Combine | "combine Bathrooms and Powder Rooms" | Merge collection items into one |
| Rename | "rename this to Master Bath" | `PUT /api/collections/{id}` |
| Delete collection | "delete the Test collection" | `DELETE /api/collections/{id}` (with confirm) |
| Filter | "show me only keepers" | Set triage filter |
| Search | "find subway tile" | Keyword search across titles/descriptions/tags |

**Implementation approach:** Parse the input with simple keyword/intent matching on the client side. Show the result as a brief response in the chat area ("Created collection 'Kitchen Favorites' with 0 items"). Keep it conversational but don't overthink it — basic pattern matching is fine for v1.

```javascript
function processChat(text) {
    const lower = text.toLowerCase().trim();

    // "make/create a collection called X"
    const createMatch = lower.match(/(?:make|create)\s+(?:a\s+)?(?:new\s+)?collection\s+(?:called\s+)?["']?(.+?)["']?$/);
    if (createMatch) {
        return createCollection(createMatch[1].trim());
    }

    // "move all X items to Y" / "put X into Y"
    const moveMatch = lower.match(/(?:move|put)\s+(?:all\s+)?(?:the\s+)?(.+?)\s+(?:items?\s+)?(?:to|into)\s+["']?(.+?)["']?$/);
    if (moveMatch) {
        return moveItemsToCollection(moveMatch[1].trim(), moveMatch[2].trim());
    }

    // "show me X" / "show X"
    const showMatch = lower.match(/(?:show|open)\s+(?:me\s+)?["']?(.+?)["']?$/);
    if (showMatch) {
        return showCollection(showMatch[1].trim());
    }

    // "find X" / "search for X"
    const searchMatch = lower.match(/(?:find|search(?:\s+for)?)\s+(.+)/);
    if (searchMatch) {
        return searchItems(searchMatch[1].trim());
    }

    // Fallback
    return addChatMessage("system", "I didn't quite understand that. Try something like 'make a new collection called Kitchen' or 'show me all keepers'.");
}
```

### Browse View (default)

The main grid view showing collection tiles and items.

**Sidebar (left, ~240px):**

```html
<div class="sidebar">
    <div class="sidebar-section">
        <h3>Sources</h3>
        <button class="filter-chip active">All</button>
        <button class="filter-chip">Pinterest</button>
        <button class="filter-chip">Facebook</button>
        <button class="filter-chip">Scans</button>
    </div>
    <div class="sidebar-section">
        <h3>Status</h3>
        <button class="filter-chip active">All items</button>
        <button class="filter-chip">Pending</button>
        <button class="filter-chip">Keepers ✓</button>
        <button class="filter-chip">Hidden</button>
    </div>
    <div class="sidebar-section">
        <h3>Boards</h3>
        <!-- Scrollable list of boards with item counts -->
        <div class="board-list">
            <button class="board-chip" data-board="kitchen">Kitchen <span class="count">268</span></button>
            <button class="board-chip" data-board="bathroom">Bathroom <span class="count">142</span></button>
            ...
        </div>
    </div>
    <div class="sidebar-section">
        <h3>Collections</h3>
        <div class="collection-list">
            <!-- User-created collections -->
        </div>
    </div>
</div>
```

**Tile grid cards (simple, image-forward):**

```html
<div class="card" data-id="{asset.id}">
    <div class="card-image">
        <img src="/media/{asset.id}?kind=thumb" loading="lazy" />
        <!-- Triage badge (small dot, top-right) -->
        <span class="triage-badge keeper"></span>
    </div>
    <div class="card-footer">
        <span class="card-title">{title, truncated}</span>
        <span class="card-source">{source icon}</span>
    </div>
</div>
```

**Card CSS:**
```css
.card {
    background: var(--panel);
    border-radius: var(--radius);
    box-shadow: var(--shadow-sm);
    overflow: hidden;
    cursor: pointer;
    transition: box-shadow 0.2s, transform 0.15s;
}
.card:hover {
    box-shadow: var(--shadow-md);
    transform: translateY(-2px);
}
.card-image img {
    width: 100%;
    aspect-ratio: 4/3;
    object-fit: cover;
}
.card-footer {
    padding: 8px 12px;
    font-size: 0.85rem;
    color: var(--text);
    display: flex;
    justify-content: space-between;
    align-items: center;
}
.triage-badge {
    position: absolute;
    top: 8px;
    right: 8px;
    width: 12px;
    height: 12px;
    border-radius: 50%;
    border: 2px solid white;
}
.triage-badge.keeper { background: var(--keep-green); }
.triage-badge.hidden { background: var(--hide-red); opacity: 0.7; }
```

**Grid:**
```css
.grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 16px;
    padding: 20px;
}
```

Clicking a card opens a **detail modal** (see below).

### Detail Modal

When you click a card, a modal slides up with the full image and metadata:

```html
<div class="modal-overlay">
    <div class="modal-content">
        <button class="modal-close">×</button>
        <div class="modal-image">
            <img src="/media/{id}?kind=original" />
        </div>
        <div class="modal-details">
            <h2>{title}</h2>
            <p class="modal-description">{description or seo_alt_text}</p>
            <div class="modal-meta">
                <span>{board} · {source}</span>
                <span>{created_at formatted}</span>
            </div>
            <div class="modal-links">
                <a href="{source_ref}" target="_blank" class="source-link">
                    View on {Pinterest/Facebook} ↗
                </a>
                <a href="{source_url}" target="_blank" class="source-link" if-exists>
                    Original site ↗
                </a>
            </div>
            <div class="modal-actions">
                <button class="btn-keep">✓ Keep</button>
                <button class="btn-hide">✗ Hide</button>
            </div>
        </div>
    </div>
</div>
```

### Review Mode

The core curation experience. When the user clicks **"Review"** (button in the header, or types "review" in the chat), whatever is currently in scope (filtered grid) enters card-by-card review.

**Header button:**
```html
<button id="reviewBtn" class="review-btn">Review</button>
```

**Review triggers:** Clicking "Review" takes whatever the current grid is showing (a board, a collection, filtered items, all pending items) and enters card-by-card review on those items.

**Review card layout (takes over main content area):**

```html
<div class="review-view">
    <div class="review-header">
        <button class="review-back">← Back to browsing</button>
        <span class="review-counter">23 of 185</span>
        <div class="review-progress">
            <div class="review-progress-bar" style="width: 12%"></div>
        </div>
    </div>

    <div class="review-card">
        <div class="review-image">
            <img src="/media/{id}?kind=original" />
        </div>
        <div class="review-info">
            <h2>{title}</h2>
            <p>{board} · {source}</p>
            <p class="review-description">{seo_alt_text or ai_summary}</p>
            <a href="{source_ref}" target="_blank">View on {source} ↗</a>
        </div>
    </div>

    <div class="review-actions">
        <button class="review-btn-hide" title="Hide (← or S)">
            <span class="btn-icon">✗</span>
            <span class="btn-label">Hide</span>
        </button>
        <button class="review-btn-skip" title="Skip (↓ or Space)">
            <span class="btn-icon">→</span>
            <span class="btn-label">Skip</span>
        </button>
        <button class="review-btn-keep" title="Keep (→ or K)">
            <span class="btn-icon">♥</span>
            <span class="btn-label">Love it</span>
            <label class="comment-later">
                <input type="checkbox" id="commentLater" />
                Comment later
            </label>
        </button>
    </div>

    <button class="review-undo" title="Undo (Z)">↩ Undo</button>
</div>
```

**The "Love it" button has a "Comment later" checkbox** attached to it. When checked and the user keeps the item, the asset gets a `needs_comment` flag (stored in `triage_status` as `'keeper_comment'` or via a separate `needs_annotation` column — see schema note below).

**Schema addition for annotation marking:**

Add to Part 1 schema changes:
```python
"needs_annotation": "integer",  # 0 or 1; set during triage review
```

When the user clicks "Love it" with "Comment later" checked:
- `triage_status = 'keeper'`
- `needs_annotation = 1`

### Keyboard Shortcuts (Review Mode)

| Key | Action |
|---|---|
| `→` or `K` | Love it (keep), advance |
| `←` or `S` | Hide, advance |
| `↓` or `Space` | Skip (no change), advance |
| `Z` | Undo last action |
| `C` | Toggle "Comment later" checkbox |
| `Escape` | Exit review, back to grid |

### Review JS

```javascript
async function reviewAction(action) {
    const item = state.reviewItems[state.reviewIndex];
    if (!item) return;

    state.reviewHistory.push({
        id: item.id,
        previousStatus: item.triage_status || null,
        previousAnnotation: item.needs_annotation || 0,
    });

    if (action === "keep") {
        const commentLater = document.getElementById("commentLater")?.checked || false;
        await fetch(`/api/assets/${item.id}/triage`, {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                status: "keeper",
                needs_annotation: commentLater ? 1 : 0,
            }),
        });
    } else if (action === "hide") {
        await fetch(`/api/assets/${item.id}/triage`, {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({status: "hidden"}),
        });
    }
    // "skip" does nothing — just advances

    // Reset checkbox for next card
    const cb = document.getElementById("commentLater");
    if (cb) cb.checked = false;

    state.reviewIndex++;
    if (state.reviewIndex >= state.reviewItems.length) {
        showReviewComplete();
        return;
    }
    renderReviewCard();
}

function showReviewComplete() {
    // Show a friendly completion message
    // "All done! You reviewed 185 items. 92 keepers, 71 hidden, 22 skipped."
    // Offer: "Review skipped items" | "Back to browsing"
}
```

### Review completion screen

```html
<div class="review-complete">
    <h2>All done! 🎉</h2>
    <p>You reviewed 185 items in Kitchen</p>
    <div class="review-stats">
        <span class="stat keeper">92 keepers</span>
        <span class="stat hidden">71 hidden</span>
        <span class="stat skipped">22 skipped</span>
    </div>
    <div class="review-complete-actions">
        <button onclick="startReview('skipped')">Review skipped items</button>
        <button onclick="exitReview()">Back to browsing</button>
    </div>
</div>
```

### Annotation Queue (future, but wire it now)

After triage, items marked "Comment later" (`needs_annotation = 1`) should be accessible. Add a sidebar filter:

```html
<button class="filter-chip" data-filter="needs-comment">Needs comment 💬</button>
```

This filters to `needs_annotation = 1`. Clicking a card from this filtered view opens the annotation modal (existing functionality from the pre-rebuild codebase — the point-based annotation system still works).

### Triage filter in sidebar

The Status section in the sidebar lets you filter by triage state:

```javascript
// When "Keepers" chip is clicked:
state.triageFilter = "keeper";
loadAssets();  // GET /api/assets?triage_status=keeper

// When "Pending" chip is clicked:
state.triageFilter = "pending";
loadAssets();  // GET /api/assets?triage_status=pending
```

### Grid card triage badges

On each tile in browse mode, show a subtle indicator:

```css
.card-image { position: relative; }

.triage-badge {
    position: absolute;
    top: 8px;
    right: 8px;
    width: 12px;
    height: 12px;
    border-radius: 50%;
    border: 2px solid white;
    box-shadow: 0 1px 3px rgba(0,0,0,0.2);
}
.triage-badge.keeper { background: var(--keep-green); }
.triage-badge.hidden { background: var(--hide-red); opacity: 0.7; }
.triage-badge.needs-comment {
    background: var(--accent);
    /* Small chat bubble icon or just gold dot */
}
```

## Part 7: Tests

### `tests/test_pinterest_scrape_import.py`

Test with synthetic JSON:
- Test basic import (3 pins → 3 assets)
- Test dedup (re-import same JSON → no duplicates)
- Test image map matching (provide map, verify stored_path reused)
- Test missing fields (pin without title, without image_url → skipped)
- Test new columns populated (seo_alt_text, closeup_desc, hashtags, etc.)

### `tests/test_facebook_scrape_import.py`

Test with synthetic JSON:
- Test basic import with base64 image
- Test dedup
- Test metadata-only items (no images)
- Test date parsing ("December 18, 2025" → ISO)
- Test unavailable items
- Test title truncation (post_text > 200 chars)

### `tests/test_triage.py`

Test triage store functions:
- Test `set_triage_status()` — set keeper, verify column
- Test `set_triage_status(None)` — reset to pending
- Test `set_triage_status("keeper", needs_annotation=1)` — verify needs_annotation flag
- Test `bulk_set_triage_status()` — multiple assets
- Test `triage_stats()` — verify counts including needs_comment
- Test `list_assets(triage_status="pending")` — filters correctly
- Test `list_assets(include_hidden=False)` — excludes triage_status='hidden'
- Test `list_facets()` includes triage_statuses

## Execution Order

0. **Dead code cleanup** — delete old importers, prune CLI, verify tests pass
1. Schema changes in `db.py`
2. Pinterest scrape importer + tests
3. Facebook scrape importer + tests
4. CLI commands (`import pinterest-scrape`, `import facebook-scrape`, `rebuild-db`)
5. Triage backend (store + server)
6. Triage frontend (dashboard + card view + keyboard + filters)
7. Run full test suite + ruff

Step 0 should be done first and committed separately. Steps 1-4 can be done next (Opus needs time to scrape). Steps 5-7 can be done while Opus is scraping.

## Verification

```bash
# Tests
PYTHONPATH=src python3 -m unittest discover -s tests -v
ruff check src tests

# After Opus provides scrape data:
PYTHONPATH=src python3 -m inspirations rebuild-db \
  --pinterest-json data/scrape/pinterest_scrape.json \
  --pinterest-image-map data/scrape/pinterest_image_map.json \
  --facebook-json-dir data/scrape/

# Check counts
PYTHONPATH=src python3 -m inspirations list
# Expected: pinterest ~3,661+, facebook ~1,304+, scan 107

# Start server
PYTHONPATH=src python3 -m inspirations serve --reload

# Manual checks in browser:
# 1. Grid → Pinterest items show seo_alt_text in detail modal
# 2. Grid → Facebook items have full-size images (not tiny thumbnails)
# 3. Detail modal → "View on Pinterest/Facebook" link opens source in new tab
# 4. Triage view → board dashboard with progress bars
# 5. Click "Start" on a board → card-by-card triage with K/S keyboard
# 6. Undo (Z) works
# 7. Filter sidebar → Triage accordion shows pending/keeper/hidden counts
# 8. Grid cards show green/red dots for keeper/hidden
```
