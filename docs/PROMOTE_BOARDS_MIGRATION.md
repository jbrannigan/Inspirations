# Promote Boards to Collections — One-Time Migration

## Before You Start

Read these files first:
- `CLAUDE.md` — project conventions, common commands
- `DECISIONS.md` — architectural constraints
- `src/inspirations/store.py` lines 511-537 — `create_collection()` and `add_items_to_collection()` (reuse these, don't write new ones)
- `src/inspirations/cli.py` — existing CLI subcommands (follow the pattern)
- `app/app.js` — `renderGroups()` at ~line 659, `renderFilters()` at ~line 1900

## What This Is

A one-time data migration that converts every Pinterest board into a real collection. Currently boards are just a string column on `assets.board` — they can't be reviewed, curated, reordered, or starred. Collections can. So we promote them.

A board named "Kitchen Ideas" becomes a collection named "pins: Kitchen Ideas". All assets with that board get added as collection items. After this, the sidebar drops the "Boards" section — everything is just a collection. The `assets.board` column stays (metadata), but the boards facet moves into the Filters accordion.

Existing `cb:` collections (creative brief selections) are untouched.

## Part 1: New CLI Command `promote-boards`

**File:** `src/inspirations/cli.py`

Add a new subcommand `promote-boards` following the pattern of existing commands like `cmd_init`, `cmd_list`, etc.

```python
def cmd_promote_boards(args: argparse.Namespace) -> int:
    db_path = _p(args.db)
    with Db(db_path) as db:
        ensure_schema(db)

        # Get all distinct board names
        boards = db.query(
            "select distinct board from assets where board is not null and board != '' order by board"
        )

        created = 0
        skipped = 0
        total_items = 0

        for row in boards:
            board_name = row["board"]
            collection_name = f"pins: {board_name}"

            # Check if collection already exists (idempotent)
            existing = db.query(
                "select id from collections where name = ?", (collection_name,)
            )
            if existing:
                skipped += 1
                continue

            # Create the collection (reuse existing store function)
            col = create_collection(db, name=collection_name)
            cid = col["id"]

            # Get all asset IDs for this board
            asset_rows = db.query(
                "select id from assets where board = ?", (board_name,)
            )
            asset_ids = [r["id"] for r in asset_rows]

            # Add items to collection (reuse existing store function — handles
            # scan page expansion and duplicate prevention via INSERT OR IGNORE)
            n = add_items_to_collection(db, collection_id=cid, asset_ids=asset_ids)

            created += 1
            total_items += n
            print(f"  Created '{collection_name}' with {n} items")

    print(f"\nDone. Created {created} collections, skipped {skipped} existing, {total_items} total items linked.")
    return 0
```

Wire it into argparse in the `main()` function alongside other subcommands:
```python
sp = sub.add_parser("promote-boards", help="Convert boards to collections (one-time migration)")
sp.add_argument("--db", required=True)
sp.set_defaults(func=cmd_promote_boards)
```

Make sure to import `create_collection` and `add_items_to_collection` from `.store` at the top of cli.py (they may already be imported — check first).

## Part 2: Remove Boards from Groups Sidebar

**File:** `app/app.js` — `renderGroups()` at ~line 659

Currently this function renders two sections:
1. **"Boards"** header + board facet items (from `state.facets.boards`) — lines ~667-690
2. **"My Collections"** header + collection items (from `state.collections`) — lines ~697-714

**Changes:**

1. **Remove the entire boards section** — delete the `if (boards.length)` block that renders the "Boards" header and board facet list items. Boards are now collections; they'll show up in the collections list.

2. **Remove the "My Collections" header** — all collections are now peers (both `pins:` and `cb:` prefixed). Just list them all without section headers. If you want a single header, use "Groups".

3. **Remove the `boards` variable filtering** from the top of the function (it filters `state.facets.boards`). The group search should now only filter `state.collections`.

4. **The empty state** at the bottom should just check collections, not boards.

After this change, `renderGroups()` only renders collections from `state.collections`. The `pins: Kitchen Ideas` collections created by the migration will appear alongside `cb: Kitchen` collections.

## Part 3: Move Board Facet to Filters Accordion

**File:** `app/app.js` — `renderFilters()` at ~line 1900

The boards facet data (`state.facets.boards`) currently powers the sidebar boards section. Since we removed boards from the sidebar, add a "Board" filter group in the Filters accordion.

Add it as a new filter group using the exact same pattern as existing groups (Source, AI Tags, Media Type, Record Type, Creator). Look at how those are rendered — each is a collapsible group with checkboxes that toggle Set entries in state.

For the Board filter group:
- Data source: `state.facets.boards` (already loaded from `/api/facets`)
- State: `state.boards` Set (already exists)
- On checkbox toggle: update `state.boards`, call `loadFacets()` then `loadAssets()` (same as current board click behavior)
- Display: board name + count, like other facet groups

Place it after Source and before AI Tags (or wherever makes sense in the filter order).

## Part 4: Nothing Else Changes

- **Review** works automatically — promoted boards are real collections, `selectCollection()` sets `viewCollectionId`, Review button enables
- **Curation** (add/remove items, tray) works automatically on the new collections
- **`assets.board` column** stays populated — still useful as filterable metadata
- **No schema changes** — just data and UI
- **No server.py changes**

## Files Summary

**Modify:**
- `src/inspirations/cli.py` — add `promote-boards` subcommand
- `app/app.js` — simplify `renderGroups()` (remove boards section + headers), add board filter group to `renderFilters()`

**Do NOT modify:**
- `src/inspirations/store.py` — reuse existing functions as-is
- `src/inspirations/db.py` — no schema changes
- `src/inspirations/server.py` — no endpoint changes
- `app/styles.css` — no style changes needed
- `app/index.html` — no HTML changes needed

## Verification

```bash
# Run the migration
PYTHONPATH=src python3 -m inspirations promote-boards --db data/inspirations.db

# Start server
PYTHONPATH=src python3 -m inspirations serve --reload

# Open http://127.0.0.1:8000 and verify:
# - Sidebar shows all collections flat (pins: and cb: mixed together)
# - No "Boards" / "My Collections" section headers
# - Click "pins: Kitchen Ideas" → Review button enables, says 'Review "pins: Kitchen Ideas"'
# - Click Review → cluster explorer opens with that collection's assets
# - Filters accordion has a "Board" group with checkboxes
# - Checking a board filter works (filters the grid)
# - Existing cb: collections work exactly as before

# Tests + lint
PYTHONPATH=src python3 -m unittest discover -s tests -v
ruff check src tests
```
