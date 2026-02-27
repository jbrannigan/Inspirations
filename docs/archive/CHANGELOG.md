# Changelog

All notable changes to the Inspirations project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/). Versioning
follows [Semantic Versioning](https://semver.org/) per `STANDARDS.md`.

---

## [Unreleased] — Explorer UI Overhaul

### Added
- **Attractor Explorer** — 2D force-directed semantic visualization with D3
  - Toggleable attractor chips (rooms, styles, materials, colors) pull items toward semantic poles
  - Strength / Spread / Size sliders for tuning the force layout
  - Focus mode (filters non-matching items out of simulation) — now ON by default
  - Live mode for real-time simulation vs pre-computed settle
  - Thumbnail billboards on visible nodes with lazy loading
  - Overlap indicators showing multi-attractor item counts
- **3D Attractor Explorer** — Three.js WebGL variant with same chip UI
  - Custom 3D force simulation (attractor pull, return-to-rest, velocity damping, grid-hash collision)
  - OrbitControls camera with billboard textures
  - Spread slider wired to collision pass (scales cell size and min distance)
  - Fibonacci-sphere pole placement for multiple attractors
- **Explorer control panel** — sliders always visible at top; attractor chips revealed on hover
- **3D checkbox** in control panel replaces toolbar button — matches Focus/Live toggle pattern
- **Sidebar stays visible** in both grid and explorer modes — tree clicks filter the explorer
- **CSS pre-zoom feedback** — instant CSS transform on scroll-zoom while canvas repaints
- Show All reset for filters
- AI tag Any/All matching toggle
- Primary add-to-active-collection workflow
- Inspect modal Hide/Print actions
- Hidden collection exclusion from default views
- Photo upload path (app/server/importer)
- Safe `/store` route for local media fallbacks
- Cluster Explorer duplicate-review UX (graph thumbnails, 3-lane keeper/candidate/loser flow)

### Fixed
- **3D texture dropout** — `_clearScene()` now clears `_texCache` object after disposing GPU textures, preventing stale cache references on mode switch

### Changed
- Focus mode defaults to ON in both 2D and 3D explorers (better performance with large datasets)
- Explorer layout keeps two-column grid (sidebar + content) instead of going full-width
- 3D toggle moved from toolbar button to control panel checkbox (consistent with Focus/Live)
- Control panel chips hidden by default, revealed on hover/focus-within (less visual clutter)
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
