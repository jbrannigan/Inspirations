# Inspirations

Local-first inspiration library for home design research.

Inspirations ingests Pinterest saves, Facebook saves, and scanned pages into a single SQLite-backed catalog with local media storage, AI tagging, search/filtering, collections, tray workflows, and per-image annotations.

## What The Project Does Today

- Ingests data from:
  - Pinterest crawler ZIP exports
  - Facebook saved-items ZIP exports
  - Local scan inbox (images and PDFs)
- Downloads and stores originals locally with safe URL validation.
- Resolves preview images from saved link pages (Open Graph/Twitter tags with `<img>` fallback) to backfill missing thumbnails.
- Generates thumbnails for fast UI browsing.
- Falls back to SVG originals for card previews when local raster thumbnail conversion is unavailable.
- Runs AI image tagging with Gemini and stores:
  - Full JSON payloads
  - Searchable `ai_summary`
  - Normalized labels/facets
  - Structured error rows for retry analysis
- Serves a local web app with:
  - Search, source/board/label filtering
  - Compact card grid + expand-on-click tag details
  - Preview-aware ordering (thumbs/originals/image URLs before link-only items)
  - Smart preview fitting for extreme-aspect images to reduce over-cropping in cards
  - Link-style placeholders for non-image/broken-image cards (no broken thumbnail icon)
  - Notes and visual annotations
  - Collections and tray-to-collection workflows
- Provides interactive and batch tagging pipelines plus status tooling for resumable work.

## Current AI Tagging Behavior

- Primary model: `gemini-2.5-flash`
- Automatic fallback for `finishReason=RECITATION`: `gemini-2.0-flash`
- Candidate selection dedupes by Gemini provider (any model), so completed coverage does not get reprocessed repeatedly.

Check current coverage and run state at any time:

```sh
PYTHONPATH=src python3 tools/session_sync.py
```

## Tech Stack

- Python 3.11+
- SQLite
- Local filesystem storage (`store/`)
- Standard-library HTTP server for local app/API
- Optional external tools:
  - `sips` (macOS) or ImageMagick (`magick`) for thumbnails
  - Pillow fallback for formats unsupported by `sips`
  - `pdftoppm` or `mutool` for PDF page rendering

## Repository Layout

- `src/inspirations/` - CLI, DB layer, importers, AI pipeline, server
- `app/` - local web app assets
- `tools/` - operational scripts (pipeline, batch, runner, sync, dashboard)
- `tests/` - unit tests
- `docs/` - architecture, plans, handoff, runbooks
- `imports/` - local input datasets
- `store/` - downloaded originals and generated thumbnails
- `data/` - SQLite DB and batch artifacts

## Setup

### Option A: Run from source with `PYTHONPATH`

```sh
PYTHONPATH=src python3 -m inspirations --help
```

### Option B: Editable install

```sh
python3 -m pip install -e .
inspirations --help
```

## Quick Start

1. Initialize DB + store directories:

```sh
PYTHONPATH=src python3 -m inspirations init
```

2. Import Pinterest and Facebook exports:

```sh
PYTHONPATH=src python3 -m inspirations import pinterest --zip imports/raw/dataset_pinterest-crawler_*.zip
PYTHONPATH=src python3 -m inspirations import facebook --zip imports/raw/facebook-*.zip
PYTHONPATH=src python3 -m inspirations list
```

3. Download originals (network required):

```sh
PYTHONPATH=src python3 -m inspirations import pinterest --zip imports/raw/dataset_pinterest-crawler_*.zip --download
PYTHONPATH=src python3 -m inspirations import facebook --zip imports/raw/facebook-*.zip --download
```

4. Generate thumbnails:

```sh
PYTHONPATH=src python3 -m inspirations thumbs --size 512
```

5. Start the app:

```sh
PYTHONPATH=src python3 -m inspirations serve --host 127.0.0.1 --port 8000 --app app --store store
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

## Scan Import Workflow

Generate mock scans (optional), then import images/PDF pages:

```sh
python3 scripts/make_mock_scans.py
PYTHONPATH=src python3 -m inspirations import scans --inbox imports/scans/inbox --format jpg
PYTHONPATH=src python3 -m inspirations thumbs --size 512 --source scan
```

## AI Tagging Workflows

### Mock tagger

```sh
PYTHONPATH=src python3 -m inspirations ai tag --provider mock
```

### Gemini CLI tagger

```sh
GEMINI_API_KEY="YOUR_KEY" PYTHONPATH=src \
python3 -m inspirations ai tag --provider gemini --source pinterest --image-kind thumb
```

Useful flags:

```sh
# Disable/override recitation fallback
GEMINI_API_KEY="YOUR_KEY" PYTHONPATH=src \
python3 -m inspirations ai tag --provider gemini --recitation-fallback-model ""

GEMINI_API_KEY="YOUR_KEY" PYTHONPATH=src \
python3 -m inspirations ai tag --provider gemini --recitation-fallback-model gemini-2.0-flash

# Force re-tagging even if already tagged
GEMINI_API_KEY="YOUR_KEY" PYTHONPATH=src \
python3 -m inspirations ai tag --provider gemini --force
```

### Preflight + auto mode pipeline (recommended)

```sh
GEMINI_API_KEY="YOUR_KEY" PYTHONPATH=src \
python3 tools/tagging_pipeline.py --mode auto --limit 0
```

Pipeline features:

- Repairs missing originals/thumbs (default)
- Preflight validation before API spend
- ETA and optional cost estimation
- Auto-select batch vs interactive
- RECITATION-aware fallback in interactive mode

### AI error triage (actionable vs historical)

```sh
PYTHONPATH=src python3 -m inspirations ai errors --source pinterest --provider gemini --model gemini-2.5-flash
```

Useful flags:

```sh
# last N days only
PYTHONPATH=src python3 -m inspirations ai errors --days 7

# include fewer rows for quick sampling
PYTHONPATH=src python3 -m inspirations ai errors --limit 200 --examples-per-action 2
```

### Embeddings + similarity search (first slice)

Generate Gemini text embeddings for assets:

```sh
GEMINI_API_KEY="YOUR_KEY" PYTHONPATH=src \
python3 -m inspirations ai embed --source pinterest --model gemini-embedding-001
```

Run similarity search against stored embeddings:

```sh
GEMINI_API_KEY="YOUR_KEY" PYTHONPATH=src \
python3 -m inspirations ai similar --query "warm kitchen with white oak cabinets" --source pinterest --limit 20
```

Tune ranking blend (semantic cosine + lexical overlap) and minimum score threshold:

```sh
GEMINI_API_KEY="YOUR_KEY" PYTHONPATH=src \
python3 -m inspirations ai similar \
  --query "warm kitchen with white oak cabinets" \
  --source pinterest \
  --semantic-weight 0.7 \
  --lexical-weight 0.3 \
  --min-score 0.2 \
  --limit 20
```

In the web app, use semantic mode from the search box with the `sem:` prefix, then press `Enter`:

```text
sem: warm kitchen with white oak cabinets
```

### Batch tools

- `tools/tagging_batch.py` - submit/watch/fetch/ingest batch jobs
- `tools/tagging_pipeline.py` - orchestrates preflight + mode selection
- `tools/tagging_runner.py` - concurrent interactive runner
- `tools/session_sync.py` - one-command status snapshot for handoff

## Local API (served by `inspirations serve`)

Core endpoints:

- `GET /api/assets`
- `GET /api/search/similar`
- `GET /api/facets`
- `GET /api/collections`
- `POST /api/collections`
- `GET /api/tray`
- `POST /api/tray/add`
- `POST /api/tray/remove`
- `POST /api/tray/clear`
- `POST /api/tray/create-collection`
- `GET /api/annotations?asset_id=...`
- `POST /api/annotations`
- `PUT /api/annotations/{id}`
- `DELETE /api/annotations/{id}`
- `GET /media/{asset_id}?kind=thumb|original`

`/api/search/similar` query params:

- `q` (required)
- `source`, `model`, `limit` (optional)
- `semantic_weight`, `lexical_weight`, `min_score` (optional ranking controls)

`/api/assets` includes AI fields used by the UI:

- `ai_summary`
- `ai_json`
- `ai_model`
- `ai_provider`
- `ai_created_at`

## Testing

Run all tests:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## GitHub Workflow Requirements

For major features and substantial behavior changes, use a pull request workflow:

- Create a feature branch and open a PR to merge into the main branch.
- Do not merge major features directly to `main` without a PR.
- Include test evidence and a clear change summary in the PR description.
- Keep `docs/pr_summary.md` aligned with the implemented behavior.

README maintenance policy:

- Update this `README.md` whenever a feature is added, removed, or substantially changed.
- If a change affects setup, commands, API behavior, or UI workflows, the README update is required in the same PR.
- If no README update is needed, explicitly state that in the PR checklist/review notes.

## Security And Data Notes

- Downloader enforces safe public URL checks (blocks private/non-public targets).
- API keys are passed via environment variables; do not commit keys.
- AI provider/model metadata is stored for traceability.
- `asset_ai_errors` captures failed tagging attempts for retries and analysis.

## Docs

- `CONTRIBUTING.md`
- `docs/PRODUCT_SPEC.md`
- `docs/ARCHITECTURE.md`
- `docs/AI_TAGGING_PLAN.md`
- `docs/SEARCH_STRATEGY.md`
- `docs/tagging_pipeline.md`
- `docs/handoff.md`
- `docs/next_steps.md`
- `docs/pr_summary.md`

## License

Proprietary.
