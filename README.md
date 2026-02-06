# Inspirations (Home Build Moodboard)

This repo contains a local, dependency-free HTML mockup plus a professional product/architecture spec for a tool that:
- Ingests Pinterest pins, Facebook saves, and scanned magazine clippings
- Auto-tags/classifies images (e.g., via Gemini or similar)
- Lets you curate collections and annotate images
- Exports shareable collections (HTML/ZIP/PDF later) and can evolve into a web app (Vercel-ready)

## Quick start (mockup)

1. Open `mockup/index.html` in a browser.
2. Open `mockup/curation.html` for curated-workflow screens.
3. Open `mockup/cards.html` for Pinterest/Facebook card layouts.
4. Open `mockup/badges.html` for badge color options.
5. Click **Import** to load a sample dataset or import your own JSON.
6. Try searching, tagging, creating collections, and adding image annotations.

## Quick start (local ingestion CLI)

This repo now includes a small Python-based ingestion CLI (SQLite + secure downloader).

```sh
PYTHONPATH=src python3 -m inspirations init
PYTHONPATH=src python3 -m inspirations import pinterest --zip imports/raw/dataset_pinterest-crawler_*.zip
PYTHONPATH=src python3 -m inspirations import facebook --zip imports/raw/facebook-*.zip
PYTHONPATH=src python3 -m inspirations list
```

Download originals (requires network/DNS access):

```sh
PYTHONPATH=src python3 -m inspirations import pinterest --zip imports/raw/dataset_pinterest-crawler_*.zip --download
PYTHONPATH=src python3 -m inspirations import facebook --zip imports/raw/facebook-*.zip --download
```

If some Facebook items are HTML pages, retry with preview-image extraction:

```sh
PYTHONPATH=src python3 -m inspirations import facebook --zip imports/raw/facebook-*.zip --download --retry-non-image
```

Scan PDF inbox (page-splitting) and generate thumbnails:

```sh
python3 scripts/make_mock_scans.py
PYTHONPATH=src python3 -m inspirations import scans --inbox imports/scans/inbox --format jpg
PYTHONPATH=src python3 -m inspirations thumbs --size 512
```

Get a session snapshot (counts, model coverage, latest run):

```sh
PYTHONPATH=src python3 tools/session_sync.py
```

Run AI tagging:

```sh
PYTHONPATH=src python3 -m inspirations ai tag --provider mock
GEMINI_API_KEY="YOUR_KEY" PYTHONPATH=src \
python3 -m inspirations ai tag --provider gemini --source pinterest --image-kind thumb
```

Gemini defaults:
- Primary model: `gemini-2.5-flash`
- Automatic fallback for `finishReason=RECITATION`: `gemini-2.0-flash`

Override or disable fallback:

```sh
GEMINI_API_KEY="YOUR_KEY" PYTHONPATH=src \
python3 -m inspirations ai tag --provider gemini --recitation-fallback-model gemini-2.0-flash

GEMINI_API_KEY="YOUR_KEY" PYTHONPATH=src \
python3 -m inspirations ai tag --provider gemini --recitation-fallback-model ""
```

Preflight + auto-select batch vs interactive (recommended):

```sh
GEMINI_API_KEY="YOUR_KEY" PYTHONPATH=src \
python3 tools/tagging_pipeline.py --mode auto --limit 0
```

The pipeline/runner skip assets already tagged by provider (`gemini`) across any model, so reruns no-op once provider coverage is complete.

## Run the local app

```sh
PYTHONPATH=src python3 -m inspirations serve --host 127.0.0.1 --port 8000
```

Then open http://127.0.0.1:8000

The app grid now renders AI summaries + tag buckets (compact by default, expand on click).

Run tests:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Docs

- `docs/PRODUCT_SPEC.md`
- `docs/ARCHITECTURE.md`
- `docs/BUILD_TEST_PLAN.md`
- `docs/EXPORT_IMPRESSIONS.md`
- `docs/WORKFLOWS.md`
- `docs/AI_TAGGING_PLAN.md`
- `docs/SEARCH_STRATEGY.md`
- `docs/tagging_pipeline.md`
- `docs/next_steps.md`
