# Changelog

All notable changes to the Inspirations project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/). Versioning
follows [Semantic Versioning](https://semver.org/) per `STANDARDS.md`.

---

## [Unreleased] — codex/ux-simplification-pass

### Added
- Show All reset for filters
- AI tag Any/All matching toggle
- Primary add-to-active-collection workflow
- Inspect modal Hide/Print actions
- Hidden collection exclusion from default views
- Photo upload path (app/server/importer)
- Safe `/store` route for local media fallbacks
- Cluster Explorer duplicate-review UX (graph thumbnails, 3-lane keeper/candidate/loser flow)

### Changed
- Toolbar wrap and mobile affordance tweaks
- Print fallback behavior improved
- Hide action safety wording refined
- Collection CTA and faster cluster review launch

---

## [0.1.0] — 2026-02-08

Initial working release. Core pipeline from import through AI tagging, curation,
semantic search, and cluster exploration is functional.

### Added
- **Import pipeline**: Pinterest HTML export parser, Facebook HTML parser, scan
  importer with thumbnail generation
- **Storage layer**: local file store with originals + thumbnails, BMP/WebP support
- **Database**: SQLite schema — assets, collections, collection_items, annotations,
  asset_ai, asset_ai_errors, ai_runs, asset_embeddings
- **AI tagging**: Gemini integration (interactive + Batch API), automatic
  RECITATION fallback (gemini-2.5-flash → gemini-2.0-flash), full Pinterest
  coverage (3661/3661)
- **Embeddings**: Gemini text-embedding-001, cosine similarity search
- **Semantic search**: API endpoint (`/api/search/similar`), app `sem:` query mode,
  hybrid ranking controls
- **Error triage**: `inspirations ai errors` CLI with actionable vs historical
  classification
- **Web app**: vanilla JS grid UI with compact/expand cards, accordion filters,
  faceted search, curate tray, annotation system (movable markers + notes),
  collection management, admin delete workflow
- **Cluster Explorer**: `export_clusters.py`, `serve_explorer.py`,
  `cluster_explorer.html` — Discover/Outliers modes, collection-scoped review,
  duplicate-review workflow (grouped sets, keeper/loser marking, queue/apply)
- **Share export**: `inspirations export html` for reviewer-focused card pages
- **Session tooling**: `session_sync.py`, `session_checkpoint.py`, post-merge
  git hook for automatic checkpoints
- **CI**: GitHub Actions with ruff lint gate
- **Tagging pipeline**: `tagging_pipeline.py` (preflight, estimate, auto
  batch/interactive), `tagging_batch.py` (Batch API submit/watch/ingest),
  `tagging_runner.py` (interactive concurrent tagger)
- **Docs**: README, STATUS, handoff, next_steps, fast_path, tagging_pipeline,
  AI_TAGGING_PLAN, SEARCH_STRATEGY, ARCHITECTURE, CLUSTER_EXPLORER_SPEC-v2,
  potential_future_options

### Infrastructure
- Python stdlib + SQLite (no framework dependencies)
- Gemini API for AI tagging and embeddings
- scikit-learn (isolated venv) for clustering
- Local-only deployment on port 8001
