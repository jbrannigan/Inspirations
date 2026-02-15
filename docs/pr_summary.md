# PR Summary

## Update (February 12, 2026)

### Summary
- Added a Facebook salvage import path so reference-only saved items are preserved instead of dropped.
- Added new asset metadata dimensions (`media_status`, `content_kind`, `creator_name`, `source_domain`, `source_name`) and surfaced them in API facets/UI filters.
- Added Facebook collection-name ingestion into `source_collections` for source taxonomy retention.
- Fixed scan import to recurse through nested inbox folders and improved idempotent telemetry (`duplicates_skipped`, accurate `created_assets`).
- Added HTML share export CLI (`inspirations export html`) that writes a gallery artifact.
- Improved main canvas quality:
  - Added incremental loading ("Load More") for full-catalog browsing.
  - Improved annotation coordinate accuracy by mapping to the displayed image geometry (not the full stage box).
  - Semantic search source filter now supports multiple selected sources.
- Removed machine-specific default DB paths in tagging tools.

### Stability + UX Follow-Up (Later February 12, 2026)
- Fixed a main-canvas startup regression that could leave the UI stuck on loading placeholders.
  - Why: a runtime error in `setStats()` could abort initialization and make desktop appear broken.
- Added `Cache-Control: no-store` headers for API and static app assets.
  - Why: stale cached `app.js` was able to reintroduce older client-side breakage after fixes were deployed.
- Added explicit app-init fatal-error handling.
  - Why: when startup fails, the UI now shows a clear message instead of silently remaining in loading state.
- Refined filter and title UX:
  - Filters are rendered as accordions with only Source open by default.
  - Facebook card title cleanup now strips saved-item boilerplate (`Leslie Brannigan saved a link/product/video ...`).
  - Why: reduce visual noise and improve comprehension for non-technical users.
- Revised search and narrative copy for clarity:
  - Search placeholder changed to plain language (`Search ideas ...`).
  - `sem:` guidance moved from persistent text to hover help (`?`) in the search row.
  - Unfiltered/default narrative now reads: `The canvas is showing all items filtered by those that have an image or a link.`
  - Why: make the interface self-explanatory for non-technical reviewers.
- Updated LAN/mobile test workflow:
  - Documented serving on `0.0.0.0` and browsing via `.local` hostname / LAN IP.
  - Why: local loopback binding (`127.0.0.1`) blocks iPhone/iPad access.

### Share UX Follow-Up (February 13, 2026)
- Simplified shared HTML output to be reviewer-friendly instead of curator-focused.
  - Removed AI summary/description block from exported cards.
  - Added `Show Details` modal with larger preview, read-only annotation list, and annotation markers.
  - Added annotation count badges on cards so commented items are visually flagged.
  - Kept `Open Source` actions explicit and new-tab by default.
  - Added plain-language "How to save this idea" guidance in header and modal.
- Collection share guidance now recommends one collection per export file.
  - Why: lowers cognitive load versus bundling multi-collection share sets.

### Cluster Explorer Workflow Docs (February 13, 2026)
- Documented venv-based cluster export workflow in `README.md`.
  - Added explicit dependency install (`scikit-learn`) in an isolated venv.
  - Corrected operational DB path to `data/inspirations.sqlite`.
  - Added practical guidance: use `cluster_explorer.html` + `cluster_data.json` to identify outliers and eliminate bad choices.

### Cluster Explorer Spec Hardening + Resume Alignment (February 13, 2026, late)
- Added a revised implementation spec: `docs/CLUSTER_EXPLORER_SPEC-v2.md`.
- Incorporated review-driven clarifications:
  - Path normalization rules for absolute and relative local media paths.
  - Explicit `source_url` derivation rules by source type.
  - Phase 1 includes a minimal outlier action (`Remove from this collection`) in the detail panel.
  - `--include-neighbors` default now depends on mode (`15` with `--collection-id`, otherwise `0`).
  - Explicit served-mode requirement in acceptance criteria (avoid false `file://` bug reports).
- Added resume-oriented documentation updates in `docs/next_steps.md` and `docs/handoff.md` so implementation status is clear:
  - what is implemented now (`export_clusters.py` + `cluster_explorer.html`),
  - what remains spec-only for future implementation.

### Cluster Explorer Phase 1 Implementation (February 13, 2026, late)
- Implemented served-mode explorer stack:
  - Added `tools/serve_explorer.py` with strict allowlisted routes:
    - `/` -> `cluster_explorer.html`
    - `/cluster_data.json`
    - `/store/...` under project root only
  - Added cache policy:
    - HTML/JSON => `Cache-Control: no-store`
    - store media => `Cache-Control: max-age=3600`
  - Added `HEAD` support for header checks and browser probes.
- Upgraded `tools/export_clusters.py` to v2 contract:
  - New defaults: `--db data/inspirations.sqlite`, `--out tools/cluster_data.json`
  - Added flags: `--collection-id`, `--include-neighbors`, `--api-base`, `--serve`
  - Added schema fields: `source_url`, `collection_ids`, `thumb_url_local`, `image_url_local`, `image_url_remote`, `isolation_score`, `bridge_score`, `is_outlier`
  - Added local path normalization to project-relative `store/...`
  - Added collection-scoped export and neighbor inclusion behavior.
- Rebuilt `tools/cluster_explorer.html` for Phase 1 UX:
  - Auto-loads `/cluster_data.json` when served.
  - Discover/Outliers mode toggle with isolation-score threshold slider.
  - Search by title/labels/board and collection legend filtering.
  - Detail panel shows metrics + source URL and nearest neighbors.
  - Detail-panel action `Remove from this collection` when `collection_id` + `api_base` are present.
  - Fallback `remove_candidates.json` download when API write-back is not available.
- Added regression tests:
  - `tests/test_export_clusters.py`
  - `tests/test_serve_explorer.py`

### Cluster Explorer UX Iteration - Duplicate Review Workflow (February 14, 2026, early)
- Upgraded graph readability for review sessions:
  - nodes render as thumbnails (instead of dot glyphs)
  - stronger edge contrast and thickness
  - stronger cluster separation forces
  - weak bridge-link declutter toggle
- Expanded Duplicate mode into a corpus-review workflow:
  - duplicate groups with previous/next navigation
  - per-group keeper selection (`Mark as keeper`)
  - loser marking (`Mark loser` / `Unmark loser`) with visual state
  - queue losers + apply controls:
    - `Delete this group`
    - `Delete queued`
  - in session-only mode (no `api_base`) actions are safe preview/hide only
  - with `api_base + collection_id`, actions apply real collection removes via existing endpoint
- Added safe “fake remove” behavior for collection-scoped walkthroughs without API write-back.

### Cluster Explorer Duplicate Group Quality Pass (February 15, 2026)
- Tightened duplicate grouping to reduce weak chain effects:
  - groups are now formed from mutual-strong duplicate pairs (local reciprocal-strength gate), not any threshold-connected path.
  - duplicate links highlighted in Duplicate mode now reflect only strict in-group links.
- Added group quality scoring and visibility filtering:
  - each duplicate group now computes density, average similarity, minimum similarity, and a cohesion score.
  - groups are sorted best-to-worst by cohesion.
  - low-cohesion groups are hidden by default via a new `Cohesion >=` slider in Duplicate mode.
- Duplicate controls now show hidden-group count and per-group cohesion to make review trustworthiness explicit.

### Cluster Explorer Keeper-First Duplicate Review (February 15, 2026, later)
- Pivoted Duplicate mode from graph-first/delete-first toward keeper-first review:
  - dedicated keeper-review panel with larger image cards per duplicate group.
  - one-click keeper selection (`Set keeper`) per group with immediate visual confirmation.
  - optional `Show All Dupes` view to browse all groups without stepping next/previous.
  - `Download Keepers` export (`duplicate_keepers.json`) to carry keeper decisions forward.
- Reduced destructive affordances in duplicate review UI:
  - loser/delete controls are hidden in Duplicate mode to focus the task on keeper selection.
  - detail panel in Duplicate mode now emphasizes keeper/candidate role rather than delete queue state.

### Cluster Explorer Outlier Keeper Review (February 15, 2026, later)
- Extended keeper-first review pattern to Outliers mode:
  - outlier mode now opens a card-based review panel instead of relying on graph-only inspection.
  - reviewers mark `keep` for outlier candidates to remove them from the candidate list (session-safe, non-destructive).
  - added `Reset Keeps` and `Download Outlier Keeps` actions for iteration and handoff.
- In review modes (Outliers and Duplicates), graph/legend are visually de-emphasized to keep attention on curation cards.

### Cluster Explorer Collection-First Progression (February 15, 2026, later)
- Added explicit collection progression controls in top bar:
  - previous/next collection navigation and direct collection selector.
  - collections are ordered by item count for practical review sequencing.
- Duplicate grouping now scopes to the selected collection and is ordered strongest-to-weakest by a dominance score (size + similarity + density), so reviewers can work down from predominant groups.
- Left legend/sidebar is removed from the active review workflow to reduce visual noise.

### Cluster Explorer Focus vs Nearby Context Clarification (February 15, 2026, late)
- Clarified collection-scoped exports at the data level:
  - each node now carries `in_focus_collection` and `is_nearby_context`
  - `meta` now includes `collection_name`, `focus_count`, and `nearby_count`
- Updated review UX to match the collection-first mental model:
  - collection-scoped sessions now pin review to the current focus collection
  - added a default-off `Show nearby (...)` toggle to optionally include neighbor context
  - duplicate/outlier review copy and group labels now explicitly indicate focus-only vs focus+nearby scope

### Cluster Explorer Discover UX Alignment (February 15, 2026, late)
- Discover mode now uses the same review-panel card UX as Outliers/Duplicates instead of graph-first inspection.
- Similar items are grouped into theme sections using similarity-link connected components at a configurable threshold.
- Theme sections are ordered strongest-to-weakest by dominance, with loose/single items shown afterward.
- Added a Discover threshold control (`Theme similarity >= ...`) to tighten or loosen grouping.
- Added explicit Discover curation actions:
  - `Mark keeper` / `Mark loser` on cards and in detail panel
  - visual state for keeper/loser picks
  - `Reset Picks` and `Download Picks` actions for session handoff
- Added Discover `Review` / `Graph` tabbing:
  - review tab keeps the grouped card workflow
  - graph tab restores full network interaction
  - graph now overlays pick-state badges per node (`K` keeper, `L` loser, `?` undecided) with corresponding border colors
- Made Discover slider behavior explicit and interactive:
  - `Theme similarity` control now appears only in Discover Graph view
  - moving the slider now immediately updates graph-link emphasis/visibility and threshold link counts
- Promoted Grid/Graph switching to all review modes:
  - Discover, Outliers, and Duplicates now all support grid review and graph inspection using icon-based view controls.
- Clarified context controls:
  - `Show nearby` was renamed/rewired to explicit `Include Nearby Context (+N)` vs `Focus Collection Only`.
  - weak-bridge toggle now shows affected-link count and hides weak links completely when off.
- Added focus-centering behavior in graph view:
  - when scope/filter/mode changes, the currently focused visible set is auto-centered in the viewport.

### In-App Scan PDF Import (February 15, 2026, late)
- Added a direct scan-ingestion action in the main app top bar:
  - New `Add Scan PDF` button opens a native file picker for `.pdf`.
  - Upload runs end-to-end ingestion server-side (PDF -> scan assets) and then thumbnail generation.
  - UI refreshes filters/canvas after completion and surfaces import counts (created assets, detected docs, skipped delimiter pages).
- Added new API endpoint:
  - `POST /api/import/scans` accepts `multipart/form-data` with `file=<pdf>`.
  - Stores upload under `imports/scans/inbox/uploads/<timestamp-random>/`.
  - Runs `import_scans_inbox(...)` and `generate_thumbnails(..., source='scan')`.
  - Returns JSON report payload with upload path/size + import/thumb reports.
- Added server regression coverage for multipart scan upload in `tests/test_server_api.py`.

### Record Type Filter Fixes (February 15, 2026, late)
- Fixed Pinterest record typing consistency:
  - Backfill now sets `assets.content_kind='pin'` for legacy Pinterest rows missing `content_kind`.
  - Import regression test now asserts new Pinterest rows persist as `content_kind='pin'`.
- Made Record Type facet context-aware to Source + Media filters:
  - `GET /api/facets` now accepts `source` and `media_status`.
  - Response now includes `content_kinds_context` for current Source/Media context.
- Updated frontend filter UX:
  - Renamed filter label from `Content Type` to `Record Type`.
  - Record Type options now show context counts and visually de-emphasize zero-result options.
  - Source/Media checkbox changes now trigger facet reload so Record Type options stay in sync.

### Scan Dialog Flags + Record Type Zero-Count Guard (February 15, 2026, late)
- Extended the in-app `Add Scan PDF` flow from simple file picker to a modal with explicit import flags:
  - `Detect blank separator pages for multi-page document splitting` (default on)
  - `Use Form Parser` (experimental request flag)
  - UI note now marks backfill of older scans as a nice-to-have, while new-upload flow is the active path.
- Wired scan flags through upload API:
  - `POST /api/import/scans` now reads multipart fields `split_on_delimiters` and `use_form_parser`.
  - `split_on_delimiters` is passed through to `import_scans_inbox(...)`.
  - API response now echoes selected options under `options`.
- Importer update:
  - `import_scans_inbox(...)` accepts `split_on_delimiters` (default `True`).
  - When disabled, delimiter detection is skipped and pages import without delimiter-page removal.
  - Import report includes `delimiter_detection_enabled`.
- Fixed Record Type all-zero edge case in UI:
  - If contextual record-type counts are not present in facet payload (for example stale backend response),
    UI now falls back to global record-type counts instead of rendering all options as `(0)`.
- Added regression coverage:
  - `tests/test_scans_import.py`: delimiter detection disabled path.
  - `tests/test_server_api.py`: multipart scan flags are parsed and forwarded to importer.

### UX Simplification Pass (February 15, 2026, late night)
- Simplified curation actions around an active destination collection:
  - `Add Selected to "<active collection>"` is now the primary action in the main toolbar.
  - Tray add remains available as a secondary/optional action.
  - `Add Filtered` now targets active collection when selected; otherwise it falls back to tray.
- Reset behavior:
  - `Show All` now resets search, filters, selection, and returns to main canvas (clean start behavior).
- AI tag matching control:
  - Added `AI Tags: Any/All` toggle in toolbar.
  - Backend now supports `label_mode=any|all` on `/api/assets`.
- Inspect/annotate modal actions:
  - Added `Hide` button that moves item into a `Hidden` collection (auto-created on first use).
  - Hidden items are excluded from normal canvas queries by default.
  - Added `Print` button that opens a print-friendly card view in a new window.
- New API behavior:
  - Added `POST /api/assets/{id}/hide`.
  - `/api/assets` now accepts `label_mode` and `include_hidden`.
- Regression coverage added:
  - `tests/test_store.py`: label all-match semantics and hidden-default exclusion.
  - `tests/test_server_api.py`: `/api/assets?label_mode=all` and `/api/assets/{id}/hide`.

### Key Changes
- Facebook importer:
  - `src/inspirations/importers/facebook_saved.py`
  - Imports URL-backed and metadata-only rows (stable synthetic `source_ref` for reference-only records).
  - Parses `content_kind`, `creator_name`, `source_domain`, and `source_name`.
  - Imports collection names from `collections.json` into `source_collections`.
  - Returns richer telemetry (`imported_assets`, `media_status_counts`, `content_kind_counts`, `collections`, `existing_assets`, `skip_reasons`).
- Schema/data model:
  - `src/inspirations/db.py`
  - Added `assets` columns: `media_status`, `content_kind`, `creator_name`, `source_domain`, `source_name`.
  - Added `source_collections` table and indexes.
  - Added idempotent metadata backfill for existing rows.
- Store/API filters + facets:
  - `src/inspirations/store.py`
  - `src/inspirations/server.py`
  - New `/api/assets` filters: `media_status`, `content_kind`, `creator`.
  - `/api/facets` now returns `media_statuses`, `content_kinds`, `creators`.
- Semantic search:
  - `src/inspirations/ai.py`
  - Similarity search now accepts comma-separated multi-source filters.
  - Similarity result payload now includes the new asset metadata fields.
- Frontend:
  - `app/app.js`, `app/index.html`
  - Added new filter groups (media/content/creator), default Facebook metadata-only exclusion, and load-more browsing.
  - Improved marker placement/editing math to use displayed image bounds for accurate annotations.
  - Added accordion filter behavior (Source expanded by default), cleaned Facebook saved-item boilerplate from card titles, and rewrote canvas/search copy for plain English.
  - Added startup error boundary behavior so initialization failures surface as clear UI errors.
- Scan intake:
  - `src/inspirations/importers/scans.py`
  - Recursive inbox traversal and corrected `created_assets` telemetry (inserted rows only).
- Share export:
  - `src/inspirations/export.py`
  - `src/inspirations/cli.py`
  - New command: `PYTHONPATH=src python3 -m inspirations export html --out data/exports/gallery.html`
- Portability:
  - `tools/tagging_runner.py`, `tools/tagging_dashboard.py`
  - Default DB path now repo-relative (`data/inspirations.sqlite`).
- Caching/network delivery hardening:
  - `src/inspirations/server.py`
  - Added `Cache-Control: no-store` to JSON API responses and static app file responses.
  - Prevents stale browser bundles from masking/undoing frontend fixes during rapid iteration.

### Testing
- `PYTHONPATH=src python3 -m unittest discover -s tests -v`
- `ruff check src tests`
- Added/updated tests:
  - `tests/test_facebook_import.py`
  - `tests/test_scans_import.py`
  - `tests/test_export_html.py`
  - `tests/test_ai_semantic.py`
  - `tests/test_store.py`
  - `tests/test_server_api.py`
  - Added API/static cache-header regression coverage in `tests/test_server_api.py`.

## Summary
- Integrated AI tag rendering into the main app grid (compact by default, expand on click).
- Added preflight + auto-mode tagging pipeline and hardened ingestion error tracking.
- Improved image download/thumbnail handling for edge cases (BMP, WebP fallbacks).
- Added a dedicated fast path checklist to speed up restarts and coordination.
- Added a one-command session sync tool for restart baselines.
- Completed remaining Pinterest tagging with an explicit recitation fallback path.
- Added AI error triage and first semantic-search slice (Gemini embeddings + similarity CLI).
- Added hybrid ranking controls for semantic search (semantic + lexical blend with score threshold).
- Added zero-touch local post-merge maintenance (stale branch cleanup + checkpoint snapshot).
- Fixed frontend UX regressions: responsive mobile layout and graceful semantic-search error handling.
- Fixed card expansion visibility for sparse records by showing explicit expanded details on all cards.
- Improved link-card handling for non-image Facebook items (no broken thumbnails) and prioritized media-rich cards in canvas ordering.
- Added smart card preview fitting for extreme-aspect images to reduce over-zoom/cropping on text-heavy cards.
- Improved link preview URL resolution to recover more thumbnails from Facebook saved links.
- Added SVG thumbnail fallback so cards can still render a preview when local tools cannot rasterize SVG.

## Key Changes
- UI: `app/app.js`, `app/styles.css` now render AI summaries + tag buckets; expand-on-click; annotate button opens modal.
- API: `/api/assets` includes `ai_json`, `ai_model`, `ai_provider`, `ai_created_at` via `src/inspirations/store.py`.
- Pipeline: `tools/tagging_pipeline.py` preflight/estimate/auto-selects batch vs interactive.
- Batch ingest: error capture in `asset_ai_errors` + output file lookup; `tools/tagging_batch.py`.
- Storage: BMP support + safer extension sniffing; `src/inspirations/storage.py`.
- Thumbnails: Pillow fallback for WebP; `src/inspirations/thumbnails.py`.
- Docs: updated `README.md`, `docs/STATUS.md`, `docs/AI_TAGGING_PLAN.md`, `docs/tagging_pipeline.md`, `docs/ARCHITECTURE.md`, `docs/handoff.md`.
- Added `docs/fast_path.md` and linked it from `docs/next_steps.md`.
- Added `tools/session_sync.py` and wired it into the restart docs.
- Gemini config hardening in `src/inspirations/ai.py` (higher output budget + JSON response mode fallback).
- Automatic RECITATION fallback path:
  - `src/inspirations/ai.py` retries `gemini-2.0-flash` when `gemini-2.5-flash` returns `finishReason=RECITATION`.
  - `tools/tagging_runner.py` and `tools/tagging_pipeline.py` now pass and use that fallback by default.
  - Candidate selection in pipeline/runner/batch tools now skips assets already tagged by Gemini provider (any model) to prevent duplicate retries.
- Final coverage status: `gemini-2.5-flash=3654`, `gemini-2.0-flash=7` (recitation fallback), `3661/3661` tagged at provider level.
- Semantic search slice:
  - New `asset_embeddings` table for per-asset vectors.
  - New CLI triage command: `inspirations ai errors` (actionable vs historical).
  - New CLI embedding command: `inspirations ai embed`.
  - New CLI similarity command: `inspirations ai similar`.
  - Similarity command now supports `--semantic-weight`, `--lexical-weight`, and `--min-score`.
  - New API endpoint: `GET /api/search/similar`.
  - Similar endpoint now accepts `semantic_weight`, `lexical_weight`, and `min_score`.
  - App search supports semantic mode via `sem:` prefix (press Enter to run).
  - `tools/session_sync.py` now reports actionable error row count.
- Post-merge continuity automation:
  - New hook file: `.githooks/post-merge`.
  - New script: `tools/post_merge_maintenance.py`.
  - Hook behavior on `main`: prune stale tracking refs, delete merged local branches with gone upstreams, and write local checkpoint snapshots to `data/session_checkpoints/`.
- UX hardening:
  - `app/styles.css`: responsive layout rules for tablet/mobile so sidebars stack instead of overlaying card interactions.
  - `app/app.js`: API error handling for `loadAssets()` and UI messaging for semantic search failures (e.g., missing `GEMINI_API_KEY`) without unhandled client errors.
  - Empty-state rendering now shows a clear error or “no results” message instead of silently failing.
  - Expanded card state now reveals a details panel (source link/import timestamps and no-AI hint) even when AI tags are absent.
  - Non-image/broken-image cards now show an explicit link-style placeholder instead of a broken image icon.
  - Extreme-aspect thumbnails now auto-switch to `contain` fitting in cards, while standard photos stay `cover`.
  - Preview resolver now handles more metadata variants, upgrades `http` image metadata to `https`, skips tracking-pixel URLs, and falls back to first real page `<img>` when OG/Twitter tags are absent.
  - Thumbnail generation now falls back to using the original `.svg` as `thumb_path` when conversion to raster fails.
- Asset ordering:
  - `src/inspirations/store.py` now prioritizes cards with usable preview media (`thumb_path` first, then image-like `stored_path`, then image-like `image_url`) before recency in `/api/assets`.

## Testing
- Unit tests:
  - `PYTHONPATH=src python3 -m unittest -q tests/test_ai_gemini_parse.py tests/test_ai_recitation_fallback.py tests/test_store.py`
- Static checks:
  - `python3 -m py_compile src/inspirations/ai.py src/inspirations/cli.py tools/tagging_runner.py tools/tagging_pipeline.py tools/tagging_batch.py tools/session_sync.py`
- UI/API smoke checks:
  - `GET /api/assets?source=pinterest&limit=5` returned 5 assets with `ai_json` present.
- Additional checks:
  - `python3 -m py_compile tools/post_merge_maintenance.py tools/session_checkpoint.py`
  - Browser UX smoke (Firefox headless, local): desktop + mobile flows passed for search, semantic mode, modal open/close, and tray actions.
  - Added regression test in `tests/test_store.py` verifying preview-quality ordering in `list_assets`.

## Notes / Follow-ups
- Provider-level Pinterest tagging is complete.
- `gemini-2.5-flash` still has 7 RECITATION-blocked assets tracked in `asset_ai_errors`; fallback model coverage is in place.
