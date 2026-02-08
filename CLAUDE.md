# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Local-first inspiration library for home design research. Ingests Pinterest exports, Facebook saved items, and scanned pages into a single SQLite-backed catalog with local media storage. Features AI tagging via Gemini, search/filtering, collections, tray workflows, and per-image annotations. The frontend is a vanilla JS web app served by Python's standard library HTTP server.

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
Subcommands: `init`, `list`, `import pinterest`, `import facebook`, `import scans`, `thumbs`, `ai tag`, `ai errors`, `ai embed`, `ai similar`, `serve`

### Start the dev server with auto-reload
```bash
PYTHONPATH=src python3 -m inspirations serve --reload
```

### AI tagging (Gemini)
```bash
PYTHONPATH=src python3 -m inspirations ai tag --provider gemini --api-key "$GEMINI_API_KEY"
```

## Architecture

### Python Package (`src/inspirations/`)

- **`cli.py`** — Argparse-based CLI entry point. All commands output JSON.
- **`db.py`** — Thin SQLite3 wrapper with context manager, row factories, schema creation and migration.
- **`store.py`** — Query builders for assets, collections, tray items. Multi-source filtering, full-text search, AI field aggregation.
- **`storage.py`** — Download originals from URLs. Safe URL validation (blocks private IPs), content-type detection, SHA256 deduplication.
- **`security.py`** — URL validation helpers used by the download pipeline.
- **`thumbnails.py`** — Auto-detects system tools (`sips` on macOS, `magick` on Linux), Pillow fallback.
- **`ai.py`** — AI tagging pipeline. Mock labeler (keyword heuristic) and Gemini integration. Primary model: `gemini-2.5-flash`, fallback to `gemini-2.0-flash` on `RECITATION` errors. Includes preflight checks and label flattening.
- **`server.py`** — Standard library `HTTPServer`. REST API endpoints (`/api/assets`, `/api/search/similar`, `/api/facets`, `/api/collections`, `/api/tray`, `/api/annotations`) plus media serving and static files.
- **`devserver.py`** — File-watching wrapper for auto-reload during development.
- **`importers/`** — Adapter pattern: `pinterest_crawler.py`, `facebook_saved.py`, `scans.py`. Each normalizes source data into consistent `Asset` records. Imports are idempotent.

### Frontend (`app/`)

Vanilla HTML/CSS/JS, no build step. Three-column layout: sidebar filters/collections, asset grid, tray sidebar. `app.js` handles all API communication, grid rendering, modals with annotations, and collection management. `admin.html`/`admin.js` for password-protected delete operations.

### Operational Tools (`tools/`)

`tagging_pipeline.py` (orchestration with preflight/cost estimation), `tagging_runner.py` (interactive concurrent runner), `tagging_batch.py` (batch job management), `session_sync.py` (status snapshot for handoff).

### Data Model (SQLite)

Core tables: `assets` (source, URLs, stored paths, SHA256, notes, AI summary), `collections` + `collection_items` (curated sets with position ordering), `annotations` (point-based x/y notes on images), `tray_items` (temporary staging). AI tables: `asset_ai` (full responses), `asset_labels` (flattened labels with confidence), `asset_ai_errors` (failed attempts), `ai_runs` (batch metadata).

### Data Directories (not committed)

- `data/` — SQLite database and batch artifacts
- `store/` — Downloaded originals and thumbnails
- `imports/` — Local input datasets

## CI/CD

GitHub Actions runs on every push and PR with a Python version matrix (`3.11`, `3.12`, `3.13`), runs `ruff check src tests`, then runs the full unittest suite. All required checks must pass before merge.

## PR & Contribution Policy

- Feature branches required for major features; no direct merges to `main`.
- `README.md` must be updated in the same PR when features are added, removed, or substantially changed.
- `docs/pr_summary.md` must be updated when behavior changes.
- PR template requires: summary, testing evidence, and a checklist covering scope, tests, README, and secrets.

## Key Conventions

- All CLI commands produce JSON output.
- No external Python dependencies beyond optional Pillow — the project uses only the standard library.
- Gemini API key is passed via `--api-key` flag or `GEMINI_API_KEY` environment variable.
- Tests use Python's built-in `unittest` (no pytest).
- The package is run via `PYTHONPATH=src python3 -m inspirations` (or editable install via `pip install -e .`).
