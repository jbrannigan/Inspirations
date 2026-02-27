# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Local-first inspiration library for home design research. Browser-scraped data from Pinterest and Facebook, plus local scans, with a keeper/hidden triage workflow and natural-language collection management. The frontend is a vanilla JS web app served by Python's standard library HTTP server.

## Current State: Post-Rebuild (Feb 2026)

The scrape-first rebuild is complete. The database has been rebuilt from browser-scraped data:

- **6,295 assets total**: 3,783 Pinterest pins, 2,405 Facebook saved items, 107 scans
- **6,070 thumbnails** generated
- **92 collections** auto-created from board names
- **986 bad Facebook images** nulled (duplicate SHA256 captures replaced with thumbnail_url fallback)

### Recent changes:
- **Attractor Explorer** — 2D (D3 force-directed) and 3D (Three.js WebGL) semantic visualizations
  - Semantic attractor poles (rooms, styles, materials, colors) with toggleable chips
  - Control panel: sliders always visible, chips hover-reveal, 3D/Focus/Live checkboxes
  - Sidebar tree stays visible in explorer for filtering; Focus defaults ON
  - CSS pre-zoom for instant scroll feedback in 2D; texture cache fix in 3D
  - Spread slider in 3D scales collision pass cell size and min distance
- Pagination (`has_more` flag) — all 6,295 items accessible via Load More
- Collections auto-created from `board` values during rebuild
- Pinterest title fallback to `seo_alt_text` (fixes "(untitled)" tiles)
- Facebook `thumbnail_url` stored as `image_url` fallback for bad captures
- Post-rebuild step nulls out bad Facebook images (SHA256 appearing 5+ times)
- Search now includes `seo_alt_text` and `post_text`, excludes `source_ref`
- Detail modal shows: content kind badge, creator, description, hashtags, engagement stats, dimensions
- Tiles show board name and content kind badge
- "View Source" hidden for social items, renamed "View Original" for scans
- Default dev server port changed to 8001

### Known issues / limitations:
- **~174 Pinterest images failed download** — these show thumbnail fallback only
- **Facebook images rely on thumbnail_url** — ~800 items had wrong captures (login screens, group covers); they now fall back to the live thumbnail URL which requires internet
- **Chat parser has limited regex coverage** — many natural phrases don't match; fallback message shows help text for 12s
- **Annotation save errors** — now logged and surfaced via toast, but root cause (intermittent failures) not fully diagnosed

### Key data files (not committed):
- `data/scrape/pinterest_scrape.json` — Scraped Pinterest data
- `data/scrape/facebook_scrape_*.json` — Scraped Facebook data
- `data/scrape/pinterest_image_map.json` — Maps image URLs to existing stored files
- `docs/SCRAPE_REBUILD_SPEC.md` — Original implementation spec (Parts 0-7)

## Common Commands

### Run all tests
```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

### Run lint
```bash
ruff check src tests
```

### Run a single test file
```bash
PYTHONPATH=src python3 -m unittest tests.test_store -v
```

### Run the CLI
```bash
PYTHONPATH=src python3 -m inspirations <subcommand>
```
Subcommands: `init`, `list`, `import pinterest-scrape`, `import facebook-scrape`, `rebuild-db`, `thumbs`, `ai tag`, `ai errors`, `ai embed`, `ai similar`, `export html`, `export portal`, `serve`

### Start the dev server with auto-reload
```bash
PYTHONPATH=src python3 -m inspirations serve --reload
```

### Start the server for phone/tablet LAN testing
```bash
PYTHONPATH=src python3 -m inspirations serve --host 0.0.0.0 --port 8001
```
Then open `http://<hostname>.local:8001` or `http://<lan-ip>:8001`.

### AI tagging (Gemini)
```bash
PYTHONPATH=src python3 -m inspirations ai tag --provider gemini --api-key "$GEMINI_API_KEY"
```

## Architecture

### Python Package (`src/inspirations/`)

- **`cli.py`** — Argparse-based CLI entry point. All commands output JSON.
- **`db.py`** — Thin SQLite3 wrapper with context manager, row factories, schema creation and migration.
- **`store.py`** — Query builders for assets, collections, tray items. Multi-source filtering, full-text search, AI field aggregation. Includes triage status support.
- **`storage.py`** — Download originals from URLs. Safe URL validation (blocks private IPs), content-type detection, SHA256 deduplication.
- **`security.py`** — URL validation helpers used by the download pipeline.
- **`thumbnails.py`** — Auto-detects system tools (`sips` on macOS, `magick` on Linux), Pillow fallback.
- **`ai.py`** — AI tagging pipeline. Gemini integration. Primary model: `gemini-2.5-flash`, fallback to `gemini-2.0-flash` on `RECITATION` errors.
- **`export.py`** — Share-by-export utilities. Generates single-file HTML galleries and static share portal.
- **`server.py`** — Standard library `HTTPServer`. REST API endpoints plus media serving and static files.
- **`devserver.py`** — File-watching wrapper for auto-reload during development.
- **`importers/`** — Adapter pattern. Each normalizes source data into consistent `Asset` records. Imports are idempotent.
  - `pinterest_scrape.py` — Imports browser-scraped Pinterest JSON (new)
  - `facebook_scrape.py` — Imports browser-scraped Facebook JSON with base64 images (new)
  - `scans.py` — Imports local scan inbox (images and PDFs)

### Frontend (`app/`)

Vanilla HTML/CSS/JS, no build step. The app has three main workflows:
1. **Collection browsing + triage** — View collections as tile grids, natural-language collection management via chat prompt, keeper/hidden/skip review workflow with annotation marking
2. **Attractor Explorer** — Semantic visualization (2D canvas with D3 forces, or 3D WebGL with Three.js). Toggle between Grid and Explorer views via toolbar buttons. In explorer, attractor chips (rooms, styles, materials, colors) pull matching items toward labeled poles. Control panel has sliders (Strength/Spread/Size) always visible, with chips revealed on hover. 3D mode is a checkbox in the control panel alongside Focus and Live toggles. Sidebar tree stays visible in explorer mode for filtering.
3. **Share export** — Generate HTML artifacts for sharing curated collections with designers

Key explorer files:
- `attractor-explorer.js` — 2D canvas + D3 force simulation, CSS pre-zoom feedback
- `attractor-explorer-3d.js` — Three.js WebGL, custom 3D force sim, billboard textures
- `app.js` — View switching (grid/explorer), `switchExplorerMode()` for 2D↔3D, `on3DToggle` callback wiring

### Data Model (SQLite)

Core tables: `assets` (source, URLs, stored paths, SHA256, scraped metadata like `seo_alt_text`, `post_text`, `hashtags`, `dominant_color`, plus `triage_status`/`triage_at`), `collections` + `collection_items`, `annotations`, `tray_items`, `source_collections`. AI tables: `asset_ai`, `asset_labels`, `asset_ai_errors`, `ai_runs`.

### Data Directories (not committed)

- `data/` — SQLite database, scrape JSON files, batch artifacts
- `data/scrape/` — Browser-scraped JSON (Pinterest + Facebook)
- `store/` — Downloaded originals and thumbnails
- `imports/` — Local input datasets (scans)

## Shared Standards

Git workflow, versioning, code conventions, testing philosophy, and documentation duty
are defined in `/Users/minime/Projects/STANDARDS.md`. Agent roles and delegation
patterns are in `/Users/minime/Projects/AGENTS.md`. This file contains only
Inspirations-specific details.

## CI/CD

GitHub Actions runs on every push and PR with a Python version matrix (`3.11`, `3.12`, `3.13`), runs `ruff check src tests`, then runs the full unittest suite. All required checks must pass before merge.

## DevLauncher
This project is registered in `/Users/minime/Projects/Agent Manager/config/projects.json`.
If the dev server command, port, or startup requirements change, update that config file too.

## Working Style

- **Ask clarifying questions before implementing.** When the user describes a feature or change, confirm the intended behavior, scope, and UX details before writing code. Don't assume — especially for anything involving user-facing behavior, toggles, defaults, or architectural decisions.
- Prefer short, focused changes over large rewrites. When unsure about the right approach, present options and let the user pick.

## Project-Specific Conventions

- All CLI commands produce JSON output.
- No external Python dependencies beyond optional Pillow — the project uses only the standard library.
- Gemini API key is passed via `--api-key` flag or `GEMINI_API_KEY` environment variable.
- API keys resolve from environment variables first, then macOS Keychain (`inspirations_anthropic_api_key`, `inspirations_gemini_api_key`) as fallback.
- Tests use Python's built-in `unittest` (no pytest).
- The package is run via `PYTHONPATH=src python3 -m inspirations` (or editable install via `pip install -e .`).
- `data/`, `store/`, `imports/` are local-only and never committed.

## Future Work (TODO)

- **Consuming UX**: Design the experience for people receiving shared collections (the decorator/designer view). How they browse, filter, and interact with curated inspiration sets. This is a separate concern from the curation app.
- **Natural-language collection management**: Chat-style prompt in the app to manage collections ("move all kitchen items to a new collection", "combine these two collections", etc.)
- **Annotation workflow**: After triage, mark items for annotation/comment, then walk through commenting on marked items.
