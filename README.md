# Inspirations (Home Build Moodboard)

This repo contains a local, dependency-free HTML mockup plus a professional product/architecture spec for a tool that:
- Ingests Pinterest pins, Facebook saves, and scanned magazine clippings
- Auto-tags/classifies images (e.g., via Gemini or similar)
- Lets you curate collections and annotate images
- Exports shareable collections (HTML/ZIP/PDF later) and can evolve into a web app (Vercel-ready)

## Quick start (mockup)

1. Open `mockup/index.html` in a browser.
2. Open `mockup/curation.html` for curated-workflow screens.
2. Click **Import** to load a sample dataset or import your own JSON.
3. Try searching, tagging, creating collections, and adding image annotations.

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

Scan PDF inbox (page-splitting) and generate thumbnails:

```sh
python3 scripts/make_mock_scans.py
PYTHONPATH=src python3 -m inspirations import scans --inbox imports/scans/inbox --format jpg
PYTHONPATH=src python3 -m inspirations thumbs --size 512
```

Run AI tagging (mock provider for now):

```sh
PYTHONPATH=src python3 -m inspirations ai tag --provider mock
```

## Run the local app

```sh
PYTHONPATH=src python3 -m inspirations serve --host 127.0.0.1 --port 8000
```

Then open http://127.0.0.1:8000

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
