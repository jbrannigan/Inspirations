# Inspirations

Local-first inspiration library for home design research.

Inspirations ingests Pinterest saves, Facebook saves, and scanned pages into a single SQLite-backed catalog with local media storage, AI tagging, search/filtering, collections, tray workflows, and per-image annotations.

## What The Project Does Today

- Ingests data from:
  - Pinterest crawler ZIP exports
  - Facebook saved-items ZIP exports
  - Local scan inbox (images and PDFs)
- Preserves Facebook records even when media URLs are missing (reference-only rows with content/creator metadata).
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
  - Media-type/record-type/creator filtering (helpful for Facebook reference rows)
  - Record Type facet now context-aware to selected Source + Media filters, with zero-result options visually de-emphasized
  - Record Type gracefully falls back to global counts if contextual facet payload is unavailable (prevents all-zero display on stale server responses)
  - `Show All` now acts as a true reset (search + filters + selection), returning canvas to a clean starting state
  - AI tag matching now supports `Any` (OR) and `All` (AND) modes
  - Primary add flow is now direct-to-active-collection; tray remains optional as a secondary holding area
  - Annotate modal now includes `Hide` (moves to Hidden collection) and `Print` actions
  - Hide flow is explicit and non-destructive (`Hide to Hidden` / `Unhide`)
  - Print now falls back to an embedded print frame when popup windows are blocked
  - Header actions now include both `Add Scan PDF` and `Add Photos` (single-file upload paths)
  - Hidden items are excluded from main canvas by default, but remain available when viewing the Hidden collection
  - Accordion filters (only Source open by default) to keep high-cardinality filter sets manageable
  - Plain-language canvas narrative text in the header describing what is currently shown
  - `Review Collection` opens Cluster Explorer from the active canvas collection (collection-only by default; nearby context optional in explorer)
  - Compact card grid + expand-on-click tag details
  - Incremental "load more" browsing for full-catalog navigation
  - Search prompt simplified for non-technical users, with semantic `sem:` help moved to hover tooltip
  - Source facet includes imported `photo` items alongside Pinterest/Facebook/Scan
- Multipage scan PDFs are presented as one document card in canvas/tray (not one card per page), while still keeping per-page media under the hood
  - Document cards now use content-only scan titles in the main app (no `- doc X` suffix in the visible title)
  - Facebook title cleanup in cards (drops boilerplate like `Leslie Brannigan saved a ...`)
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

5. Start the app (local machine only):

```sh
PYTHONPATH=src python3 -m inspirations serve --host 127.0.0.1 --port 8000 --app app --store store
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

For iPhone/iPad/LAN testing, bind to all interfaces:

```sh
PYTHONPATH=src python3 -m inspirations serve --host 0.0.0.0 --port 8000 --app app --store store
```

Then open either:

- `http://<your-local-hostname>.local:8000` (for example `http://minime.local:8000`)
- `http://<your-lan-ip>:8000` (for example `http://192.168.0.136:8000`)

## Scan Import Workflow

Generate mock scans (optional), then import images/PDF pages:

```sh
python3 scripts/make_mock_scans.py
PYTHONPATH=src python3 -m inspirations import scans --inbox imports/scans/inbox --format jpg
PYTHONPATH=src python3 -m inspirations thumbs --size 512 --source scan
```

Scan import now walks nested folders under `--inbox` (for example `imports/scans/inbox/recipes` and `imports/scans/inbox/inspirations`).

You can also import scans directly from the main web app:

1. Open the app top bar and click `Add Scan PDF`.
2. Pick a PDF from your computer.
3. Choose options in the import dialog:
   - `Detect blank separator pages...` (default on): supports one-upload multipage splitting with blank-page delimiters.
   - `Use Form Parser` (experimental): request structured extraction mode (currently a forward-compatible flag; OCR-first remains default behavior).
4. The app uploads the PDF, runs scan ingestion, and generates thumbnails automatically.
5. Refreshes happen in-place, so newly imported scan pages are immediately available in canvas/filtering.

## Share Export Workflow

Generate a shareable HTML gallery artifact:

```sh
PYTHONPATH=src python3 -m inspirations export html --out data/exports/gallery.html
```

Optional filters:

```sh
# one source only
PYTHONPATH=src python3 -m inspirations export html --source pinterest --out data/exports/pinterest.html

# one collection only
PYTHONPATH=src python3 -m inspirations export html --collection-id <COLLECTION_ID> --out data/exports/collection.html
```

What the shared HTML includes now:

- Review-focused cards (no AI tag buckets or AI summary text)
- `Show Details` modal with larger preview and read-only annotations
- Annotation count badge on cards when notes exist
- `Open Source` links that open in a new tab
- Plain-language "How to save this idea" guidance in the page header and modal

Recommended sharing workflow:

1. Curate in-app: shop into tray, then create/finalize a collection
2. Export one collection per share file (`--collection-id`)
3. If you need to share multiple collections, run export once per collection

### Protected Static Share (MVP, `sem:` disabled)

Generate a friendlier browse-only static portal (single HTML file):

```sh
PYTHONPATH=src python3 -m inspirations export portal --out data/exports/portal.html
```

Optional scoping:

```sh
# restrict to one or more collections
PYTHONPATH=src python3 -m inspirations export portal \
  --collection-id <COLLECTION_ID_1> \
  --collection-id <COLLECTION_ID_2> \
  --out data/exports/portal_collections.html

# restrict to one source
PYTHONPATH=src python3 -m inspirations export portal --source pinterest --out data/exports/portal_pinterest.html
```

Portal behavior:

- Browse-only: no editing, no tray, no curation actions
- Search/filter by keyword, source, media type, and collection
- Grid and Graph views are both available for exploration
- Graph view now includes live sliders (similarity, max nodes, node size, height) and resizes with viewport/orientation changes
- Graph nodes are draggable for manual inspection in graph view
- Supports multiple collections in one share artifact
- `sem:` is explicitly disabled in portal search (falls back to keyword search with notice)
- Works without Gemini API key during browsing
- Default export scope is collection-assigned items only (fits sharing workflow)
- Large exports automatically write previews into a sibling folder named `<export-file-stem>_media/`; keep that folder next to the HTML when hosting/sharing
- Scan items now include multipage context in cards/details (for example, "page 2 of 6")
- Scan detail view uses higher-resolution page media when available and exposes an `Open Scan PDF` action when the source PDF exists
- Detail modal now prefers higher-resolution stored media for all sources when available, so popup previews are not limited to thumbnail quality
- Because detail media now prefers higher-resolution files, `<export-file-stem>_media/` may be substantially larger than before

Include unassigned items when needed:

```sh
PYTHONPATH=src python3 -m inspirations export portal \
  --include-unassigned \
  --out data/exports/portal_with_unassigned.html
```

Two-phase build plan:

1. **Phase 1 (implemented now):** static export + external access gate (for example Cloudflare Access / password-protected static hosting) with all selected collections visible to authenticated viewers.
2. **Phase 2 (next):** invite-aware publishing rules (per-invitee collection visibility, invite/revoke workflow in Inspirations, and optional server-assisted auditing).

## Cluster Refinement Workflow

Use the cluster explorer to quickly spot weak outliers and remove bad fits from collections.

Current implementation status:
- Implemented now:
  - `tools/export_clusters.py` exports v2 cluster JSON (outlier metrics, collection scope, neighbor inclusion, local media path normalization).
  - Collection-scoped exports now tag each node as `in_focus_collection` vs `is_nearby_context`, and include `collection_name`, `focus_count`, and `nearby_count` in `meta`.
  - `tools/serve_explorer.py` serves explorer HTML + JSON + `store/` media with strict route allowlisting.
  - `tools/cluster_explorer.html` supports Discover/Outliers modes, collection filtering, served auto-load, and detail-panel actions.
  - Discover mode now uses the same card-review UX as Outliers/Duplicates: similar items are grouped into theme sections (grid cards), ordered strongest-to-weakest by dominance.
  - Discover supports explicit `keeper`/`loser` picks per card (plus reset/download) for representative selection workflows.
  - A global Grid/Graph view switch is available in Discover, Outliers, and Duplicates.
  - Graph view shows pick state per node with visual badges (`K` keeper, `L` loser, `?` undecided) and matching border colors.
  - Discover's similarity slider is now graph-only and fully interactive: it updates link prominence/visibility live in Graph view.
  - Collection-by-collection review controls are built into the top bar (previous/next + selector), and the left legend/sidebar is removed from the active review workflow.
  - In collection-scoped review, the current collection is the default focus and nearby neighbors are hidden by default behind `Show nearby (...)`.
  - Outlier mode now supports card-based review with keeper marking, reset, and JSON export of outlier keep decisions.
  - Duplicate mode uses stricter mutual-strong pair grouping, group cohesion scoring, and a cohesion threshold slider that hides weak duplicate groups by default.
  - Duplicate mode is keeper-first and sorted strongest-to-weakest by dominance within the selected collection: large per-group image cards, keeper selection, optional all-groups view, and JSON keeper export.
  - Collection-focused exports can remove single outliers directly from a collection when `meta.api_base` and `meta.collection_id` are set.
- Not implemented yet:
  - advanced curate mode (lasso/tray batch actions) in the explorer
- Canonical implementation plan: `docs/CLUSTER_EXPLORER_SPEC-v2.md`

1. Create and activate an isolated Python environment:

```sh
python3 -m venv /private/tmp/inspirations-cluster-venv
source /private/tmp/inspirations-cluster-venv/bin/activate
```

2. Install clustering dependency in that venv:

```sh
python -m pip install scikit-learn
```

3. Export cluster graph data from the active project database:

```sh
python tools/export_clusters.py \
  --db data/inspirations.sqlite \
  --out tools/cluster_data.json \
  --clusters auto \
  --similarity-threshold 0.72 \
  --max-neighbors 6
```

4. Serve and open the explorer (supported mode):

```sh
python3 tools/serve_explorer.py \
  --port 8080 \
  --data tools/cluster_data.json \
  --project-root .
```

Open:
- `http://127.0.0.1:8080`

5. Optional: collection-focused export with in-explorer remove action:

```sh
python tools/export_clusters.py \
  --db data/inspirations.sqlite \
  --out tools/cluster_data.json \
  --collection-id <COLLECTION_ID> \
  --include-neighbors 15 \
  --api-base http://127.0.0.1:8000
```

Then re-run `serve_explorer.py` and use **Remove from this collection** in the detail panel.

6. Fallback mode (still supported, less ideal):

- Open `tools/cluster_explorer.html` in a browser.
- Load `tools/cluster_data.json`.
- Use this if served mode is unavailable; local media loading is best in served mode.

Notes:

- Use `data/inspirations.sqlite` (not `data/inspirations.db`) in this repo.
- If `scikit-learn` (and therefore `numpy`) is missing, full-catalog exports may fail fast with a guidance message. Use the cluster venv workflow above.
- `file://` opening is supported only as manual fallback. Primary mode is HTTP via `serve_explorer.py`.

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

In the web app, use semantic mode with the `sem:` prefix, then press `Enter` (the search box `?` hover shows this reminder):

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
- `POST /api/assets/{id}/hide`
- `GET /api/search/similar`
- `GET /api/facets`
- `POST /api/import/scans` (`multipart/form-data`; supports `file`, optional `split_on_delimiters`, optional `use_form_parser`)
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

For scan records, `/api/assets` now returns document-collapsed rows (one row per scan document) with:

- `scan_group_member_ids` (all backing asset IDs for that document)
- `scan_doc_pages`
- `scan_doc_index`

`/api/facets` filter params (optional):

- `source` (comma-separated)
- `media_status` (comma-separated)

`/api/assets` filter params (optional):

- `media_status` (`image|link_only|metadata_only`, comma-separated supported)
- `content_kind` (comma-separated supported)
- `creator` (comma-separated supported)
- `label_mode` (`any|all`) for AI tag matching behavior
- `include_hidden` (`false` by default)
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
