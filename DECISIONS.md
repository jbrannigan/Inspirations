# Decisions

Permanent record of architectural and design decisions. Check here before
proposing something that may already be decided.

---

## D001 — Python stdlib only (2026-02-03)

**Decision:** No web framework. Use Python stdlib (`http.server`, `sqlite3`,
`json`, `pathlib`) for the entire backend.

**Why:** Minimal dependencies, fast startup, easy to understand. This is a
personal tool — no need for Flask/Django overhead.

**Consequence:** Custom routing in `server.py`, manual JSON serialization,
`unittest` instead of pytest.

---

## D002 — SQLite for storage (2026-02-03)

**Decision:** Single SQLite file at `data/inspirations.sqlite`.

**Why:** Zero-config, portable, sufficient for ~5k assets. Backups are just
file copies.

**Consequence:** No concurrent write scaling. Batch operations need careful
transaction handling to avoid lock contention.

---

## D003 — Local-only deployment (2026-02-03)

**Decision:** Serve on localhost only. No cloud deployment planned.

**Why:** Personal tool running on Mac Mini. Assets are local files, not
suitable for cloud hosting without a storage migration.

**Port:** 8001 (registered in STANDARDS.md port allocation table).

---

## D004 — Vanilla JS frontend (2026-02-03)

**Decision:** No React/Vue/Svelte. Plain HTML + vanilla JavaScript in `app/`.

**Why:** Keeps the stack simple. Single `app.js` file. No build step, no
bundler, no node_modules.

**Consequence:** Manual DOM manipulation, no component model, CSS in a
single `styles.css`.

---

## D005 — Gemini for AI tagging (2026-02-05)

**Decision:** Use Google Gemini (gemini-2.5-flash primary, gemini-2.0-flash
fallback) for image tagging.

**Why:** Good vision quality, Batch API support for bulk processing (~50%
cost reduction), generous rate limits.

**Consequence:** Requires `GEMINI_API_KEY` in environment. Batch API has 24h
SLO. RECITATION responses need automatic fallback to alternate model.

---

## D006 — Thumbnails for AI input (2026-02-05)

**Decision:** Send thumbnail images (not originals) to Gemini for tagging.

**Why:** Faster, cheaper, sufficient quality for tag extraction. Originals
are 2-10x larger with no meaningful quality gain for labeling.

---

## D007 — Batch API for bulk tagging (2026-02-05)

**Decision:** Use Gemini Batch API for initial bulk tagging (>500 assets),
interactive mode for small batches and retries.

**Why:** Batch API is ~50% cheaper and avoids rate limit pressure. Interactive
is better for immediate feedback and retry workflows.

---

## D008 — Provider-level deduplication (2026-02-05)

**Decision:** Skip already-tagged assets at the provider level (any model),
not just model-specific.

**Why:** Prevents re-tagging assets that were successfully handled by a
fallback model.

---

## D009 — Gemini text-embedding-001 for embeddings (2026-02-08)

**Decision:** Use Gemini's text-embedding-001 model for asset embeddings,
stored in `asset_embeddings` table.

**Why:** Same API ecosystem as tagging. Enables cosine similarity search
without adding a vector database.

**Consequence:** Embeddings stored as JSON arrays in SQLite. Similarity
computation is in-process Python (numpy-free, pure math).

---

## D014 — Scrape-first rebuild (2026-02-22)

**Decision:** Nuke the database and rebuild from browser-scraped data instead
of continuing with ZIP-export-based imports.

**Why:** Browser scraping captures much richer metadata (post text, hashtags,
creator names, engagement data, high-res images for Facebook) than the
pre-exported ZIP files. Pinterest images are already stored locally and will
be matched via an image map. Facebook images will be re-captured at full
resolution during scraping.

**Consequence:** Old importers (`pinterest_crawler.py`, `facebook_saved.py`)
are deleted. New importers (`pinterest_scrape.py`, `facebook_scrape.py`)
consume JSON produced by browser scraping. The `rebuild-db` command
orchestrates a clean reimport. Old documentation archived to `docs/archive/`.

**Spec:** `docs/SCRAPE_REBUILD_SPEC.md`

---

## D015 — Triage-first curation workflow (2026-02-22)

**Decision:** The primary curation UX is a keeper/hidden triage workflow,
not the previous filter-and-collect approach.

**Why:** With ~5,000 items from multiple sources, the user needs to quickly
separate "house stuff" from everything else. A card-by-card review with
keyboard shortcuts (keep/hide/skip) is faster than manual collection building.

**Consequence:** New `triage_status` column on assets (null=pending, 'keeper',
'hidden'). Triage dashboard shows stats. Review mode walks through items one
at a time. Collections are managed via natural-language prompts rather than
complex UI.

---

## D016 — Natural-language collection management (2026-02-22)

**Decision:** Use a chat-style prompt in the app for collection operations
instead of building complex collection UI widgets.

**Why:** "Move all kitchen items to a new collection" is faster than
select-all + drag + create-collection UI flows. Reduces frontend complexity
and makes the app feel friendly rather than techy.

**Consequence:** Backend needs a flexible collection-operations API. Frontend
needs a text input that sends natural-language requests to the backend (or
processes them client-side with simple pattern matching).

---

## D017 — Attractor Explorer as in-app view mode (2026-02-26)

**Decision:** The attractor explorer (2D and 3D) is an in-app view mode,
toggled via toolbar buttons (Grid / Explorer) with 3D as a checkbox inside
the explorer control panel alongside Focus and Live.

**Why:** Keeps the explorer tightly integrated with the sidebar tree and
existing filter state. Sidebar clicks auto-filter the explorer via
`syncExplorerFilter()`. The 3D toggle is a visualization option (like Focus
or Live), not a separate view — so it belongs in the control panel, not the
toolbar.

**Consequence:** Both 2D (`attractor-explorer.js`) and 3D
(`attractor-explorer-3d.js`) share the same public API shape and
`on3DToggle(callback)` interface. `app.js` wires the callback to
`switchExplorerMode()`. Explorer layout keeps the two-column grid
(sidebar + content) rather than going full-width.

---

## D018 — CSS pre-zoom for 2D scroll feedback (2026-02-26)

**Decision:** Apply an instant CSS `transform` on the canvas during D3 zoom
events, then clear it when `_render()` completes the real canvas repaint.

**Why:** Canvas repaints for 4,600+ nodes take multiple frames. Without
pre-zoom, scroll-zoom feels unresponsive — the user can't tell if their
input was received. The CSS transform gives immediate (blurry) visual
feedback while the crisp repaint catches up, matching the pattern used by
Leaflet and Google Maps.

**Consequence:** `_lastRenderedTransform` tracks the transform at last
repaint. Zoom handler computes the delta and applies it as CSS
`translate() + scale()`. `_render()` clears `canvas.style.transform` and
updates the tracking state.

---

## Archived Decisions (pre-rebuild)

Decisions D010–D013 (cluster explorer, accessibility tier, session-only delete)
were specific to the pre-rebuild system. They are documented in
`docs/archive/` for reference but no longer apply to active development.
