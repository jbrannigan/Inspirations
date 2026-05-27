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
  - Sidebar filters and text search define the base Explorer item scope
  - Category chips now have explicit `Filter / Group` semantics: filter narrows the visible set; group arranges the current scope without changing global/sidebar filters
  - 3D includes a `Group by` shortcut, visible active grouping chips, and restored `Categories` drawer
  - Explorer controls live in the top stats toolbar, with editable numeric values beside tuning sliders for iPad usability
  - iPad/mobile-constrained broad sets use `iPad lite: 2D map`; filtered subsets switch back to 3D when a measured per-session WebGL budget allows it
  - The mode/count hint now updates when filters are applied, including 2D iPad fallback mode
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

### Browse tree sanity test (UI)
Start the dev server, open http://localhost:8001, paste `tools/sanity_browse_tree_explorer.js`
into the DevTools console. All 16 checks should pass. Run this before any PR that touches
explorer, sidebar, or browse-tree code.

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

### Start the server behind a reverse proxy (New Home site)
```bash
BASE_PATH=/inspirations-app PYTHONPATH=src python3 -m inspirations serve --port 8001
```
When `BASE_PATH` is set, the server strips that prefix from incoming request paths and injects `window.__BASE_PATH` into the HTML so all frontend asset/API/media URLs are prefixed accordingly. The New Home Next.js app rewrites `/inspirations-app/:path*` to `http://127.0.0.1:8001/:path*`.

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
- **`server.py`** — Standard library `HTTPServer`. REST API endpoints plus media serving and static files. Supports optional `BASE_PATH` env var for reverse-proxy deployments (strips prefix from incoming requests, injects `window.__BASE_PATH` into HTML).
- **`devserver.py`** — File-watching wrapper for auto-reload during development.
- **`importers/`** — Adapter pattern. Each normalizes source data into consistent `Asset` records. Imports are idempotent.
  - `pinterest_scrape.py` — Imports browser-scraped Pinterest JSON (new)
  - `facebook_scrape.py` — Imports browser-scraped Facebook JSON with base64 images (new)
  - `scans.py` — Imports local scan inbox (images and PDFs)

### Frontend (`app/`)

Vanilla HTML/CSS/JS, no build step. The app has three main workflows:
1. **Collection browsing + triage** — View collections as tile grids, natural-language collection management via chat prompt, keeper/hidden/skip review workflow with annotation marking
2. **Attractor Explorer** — Semantic visualization (2D canvas with D3 forces, or 3D WebGL with Three.js). Toggle between Grid and Explorer via toolbar buttons. Sidebar filters and text search define the base scope. Category chips use explicit `Filter / Group` semantics, and 3D also offers `Group by` shortcuts that arrange the current scope without changing global/sidebar filters. Explorer controls are mounted in the top stats toolbar, with editable numeric tuning values for desktop and iPad. Mobile-constrained broad sets use `iPad lite: 2D map`; filtered subsets can switch back to 3D when the measured WebGL budget allows it.
3. **Share export** — Generate HTML artifacts for sharing curated collections with designers

Key explorer files:
- `attractor-explorer.js` — 2D canvas + D3 force simulation, text/category filtering, Filter/Group category controls, CSS pre-zoom feedback
- `attractor-explorer-3d.js` — Three.js WebGL, custom 3D force sim, billboard textures, category drawer, grouping shortcuts
- `app.js` — View switching (grid/explorer), sidebar/text filter sync, iPad 2D/3D fallback budgeting, Explorer mode/count hint

### Data Model (SQLite)

Core tables: `assets` (source, URLs, stored paths, SHA256, scraped metadata like `seo_alt_text`, `post_text`, `hashtags`, `dominant_color`, plus `triage_status`/`triage_at`), `collections` + `collection_items`, `annotations`, `tray_items`, `source_collections`. AI tables: `asset_ai`, `asset_labels`, `asset_ai_errors`, `ai_runs`.

### Ontology & Classification

This project uses a layered classification system. Understanding the trust hierarchy is essential for any code that categorizes, filters, or describes items.

**Trust hierarchy** (highest → lowest priority):

1. **Source boards** (`assets.board`) — Leslie's personal curation on Pinterest, Facebook, and Houzz. She saved items to specific boards intentionally. Board assignments always take precedence over AI tags when there is a conflict.
2. **Human review / triage decisions** — Jim and Leslie's decisions in the app are durable intent signals and should not be overridden casually.
3. **Collections** — `pins:` prefix = mirrored source boards. `CB:` prefix = AI-derived representative collections created from high-confidence descriptions/tagging for creative-brief themes. They are useful starting hypotheses, but they are not human-curated highest-intent selections.
4. **AI-assigned rooms/styles** (`asset_ai.json` → `rooms`, `styles`) — Gemini image analysis. Good for enrichment and cross-cutting dimensions, but secondary to human curation.
5. **AI labels** (`asset_labels` table) — Flattened tags from Gemini. Useful for search, filtering, and the detail view label chips. Lowest priority for categorization decisions.

**Why Leslie saved things** — two motivations:
1. *Stylistically attractive* — caught her eye for design inspiration
2. *Items of practical concern* — construction choices, materials, maintenance issues. Not always "pretty" but important decisions when building a house.

**Classification dimensions** (used in sidebar tree and catalog):

| Dimension | Source of truth | How assigned |
|-----------|----------------|--------------|
| Source/Board | `assets.source` + `assets.board` | Original source platform grouping. Sacred — Leslie's curation. |
| Room | Board→room mapping first, AI rooms second | `BOARD_TO_ROOM` dict in `catalog.py` maps board names to canonical rooms (e.g., "kitchen" → "Kitchen"). AI rooms from `asset_ai.json → rooms` are added as secondary assignments via `AI_ROOM_MAP`. 17 canonical rooms. |
| Style | `asset_ai.json → styles` | Purely from Gemini image analysis. 14+ styles (Modern, Farmhouse, Traditional, Transitional, Contemporary, etc.). |
| Magazine | `asset_ai.json → text_in_image` (OCR) | Keyword detection from scanned pages. 7 magazines. Scan-only dimension. |
| Category | `assets.category` | `home_design` (91%), `other` (5%), `construction`, `diy`, `product_review`. Separates home-design from exercise/food/personal items. |
| Content Kind | `assets.content_kind` | `pin`, `reel`, `post`, `houzz_photo`, `scan`, `video` |

**AI data tables**:
- `asset_ai` — Full Gemini JSON per asset: `{summary, image_type, rooms[], elements[], materials[], colors[], styles[], lighting[], fixtures[], appliances[], text_in_image[], brands_products[], tags[]}`. Provider is `gemini` (image) or `gemini-video` (video).
- `asset_labels` — Flattened tag rows (one per label per asset). Source: `ai` (image, confidence 0.7), `ai-video` (video, confidence 0.8). Generated by `_flatten_ai_labels()` from the same Gemini response stored in `asset_ai`.
- `triage_log` — Audit trail for every triage status change: asset_id, old_status, new_status, reason, actor, created_at.

**Catalog system** (`data/catalog/`):
- Generated markdown files that Dave (chat AI) reads to answer user questions.
- `_index.md` — Table of contents with file paths, item counts, topics per file. This is what Dave sees in Pass 1 to decide which files to read.
- `_manifest.json` — Machine-readable metadata with `id_map` (8-char prefix → full UUID) for resolving Dave's item selections back to real asset IDs.
- Per-file format: `- {id8} | {description} | [{labels}]`. Description falls through: title → ai_summary → seo_alt_text → board → "(untitled)".
- Regenerate with: `PYTHONPATH=src python3 -m inspirations catalog generate`

**AI labeling pipeline** (populates both `asset_ai` and `asset_labels`):
- Run with: `PYTHONPATH=src python3 -m inspirations ai tag --provider gemini [--source pinterest|facebook|houzz|scan]`
- Sends thumbnail/original to Gemini 2.5 Flash, gets JSON with 11 categorical buckets
- Idempotent — skips already-tagged items unless `--force` is used
- Video labeling (Facebook reels): `PYTHONPATH=src python3 -m inspirations ai reels`

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
This project is registered in `/Users/minime/Projects/DevLauncher/config/projects.json`.
If the dev server command, port, or startup requirements change, update that config file too.

For public sharing, DevLauncher is only the local-dev launcher. Reboot-safe
hosting should use `launchd` plus the shared Cloudflare runbook:
`/Users/minime/Projects/DevLauncher/docs/launchd-cloudflared-standard.md`.

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
- `BASE_PATH` env var enables reverse-proxy mode. Frontend JS uses `Shared.prefixPath(path)` (or `Shared.basePath` for template literals) to prefix absolute URLs. When adding new `fetch()` calls or `/media/` URLs in the frontend, always use these helpers.

## Future Work (TODO)

- **Consuming UX**: Design the experience for people receiving shared collections (the decorator/designer view). How they browse, filter, and interact with curated inspiration sets. This is a separate concern from the curation app.
- **Natural-language collection management**: Chat-style prompt in the app to manage collections ("move all kitchen items to a new collection", "combine these two collections", etc.)
- **Annotation workflow**: After triage, mark items for annotation/comment, then walk through commenting on marked items.
