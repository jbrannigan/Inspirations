# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Local-first inspiration library for home design research. The project is undergoing a **scrape-first rebuild** (Feb 2026): browser-scraping Pinterest and Facebook directly for richer metadata, rebuilding the database, and adding a keeper/hidden triage workflow with natural-language collection management. The frontend is a vanilla JS web app served by Python's standard library HTTP server.

## Current State: Rebuild In Progress

The project is transitioning from ZIP-import-based ingestion to browser-scrape-based ingestion. The implementation spec for the rebuild is at `docs/SCRAPE_REBUILD_SPEC.md`. Old documentation is archived in `docs/archive/`.

### What's happening:
1. **Opus** (browser agent) scrapes Pinterest boards and Facebook saved items into JSON files in `data/scrape/`
2. **Sonnet** implements code from the spec: new importers, schema changes, triage backend/frontend, dead code cleanup
3. After both finish, `inspirations rebuild-db` nukes and reimports everything

### Key files for the rebuild:
- `docs/SCRAPE_REBUILD_SPEC.md` — Complete implementation spec (Parts 0-7)
- `data/scrape/pinterest_scrape.json` — Scraped Pinterest data (Opus produces this)
- `data/scrape/facebook_scrape_*.json` — Scraped Facebook data (Opus produces this)
- `data/scrape/pinterest_image_map.json` — Maps image URLs to existing stored files

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
PYTHONPATH=src python3 -m inspirations serve --host 0.0.0.0 --port 8000
```
Then open `http://<hostname>.local:8000` or `http://<lan-ip>:8000`.

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

Vanilla HTML/CSS/JS, no build step. The app has two main workflows:
1. **Collection browsing + triage** — View collections as tile grids, natural-language collection management via chat prompt, keeper/hidden/skip review workflow with annotation marking
2. **Share export** — Generate HTML artifacts for sharing curated collections with designers

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

## Project-Specific Conventions

- All CLI commands produce JSON output.
- No external Python dependencies beyond optional Pillow — the project uses only the standard library.
- Gemini API key is passed via `--api-key` flag or `GEMINI_API_KEY` environment variable.
- Tests use Python's built-in `unittest` (no pytest).
- The package is run via `PYTHONPATH=src python3 -m inspirations` (or editable install via `pip install -e .`).
- `data/`, `store/`, `imports/` are local-only and never committed.

## Future Work (TODO)

- **Consuming UX**: Design the experience for people receiving shared collections (the decorator/designer view). How they browse, filter, and interact with curated inspiration sets. This is a separate concern from the curation app.
- **Natural-language collection management**: Chat-style prompt in the app to manage collections ("move all kitchen items to a new collection", "combine these two collections", etc.)
- **Annotation workflow**: After triage, mark items for annotation/comment, then walk through commenting on marked items.
