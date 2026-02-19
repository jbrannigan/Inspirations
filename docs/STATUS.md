# Project Status (Resume Here)

## Current status (February 19, 2026, 01:55 UTC)
- Pinterest provider-level tagging is complete: `3661/3661` tagged for Gemini provider (any model).
- Model split remains: `gemini-2.5-flash=3654`, `gemini-2.0-flash=7` (RECITATION fallback coverage).
- Scan workflow/UX decisions are now stabilized for the main app:
  - multipage scan PDFs are treated as one logical document card in canvas/tray
  - collection add/remove, tray add/remove, and hide/unhide now operate on the full document group (all pages)
  - visible scan card titles are content-first (no `- doc X` / `pY` suffix in main-app card text)
  - per-page scan records remain in storage for ingestion/metadata fidelity, but presentation is document-first
- App/API quality updates shipped:
  - startup loading regression fix + explicit fatal-init UI messaging
  - `Cache-Control: no-store` for API/static responses to prevent stale bundle behavior
  - accordion filters with Source expanded by default
  - Facebook card title cleanup (drops saved-item boilerplate prefix)
  - plain-language canvas narrative + simplified search placeholder copy
  - improved mobile layout behavior (iPhone improved; iPad/tray usability still under active refinement)
- Share export workflow is simplified and reviewer-focused:
  - `inspirations export html` outputs cards without AI tag buckets/summary text
  - shared cards include `Show Details`, annotation visibility, and `Open Source` actions
  - recommended pattern is one collection per exported file
- Cluster explorer Phase 1 is now implemented:
  - canonical spec: `docs/CLUSTER_EXPLORER_SPEC-v2.md`
  - implemented tools: `tools/export_clusters.py`, `tools/serve_explorer.py`, `tools/cluster_explorer.html`
  - exporter now emits v2 schema fields (`source_url`, local/remote media URLs, outlier metrics, collection ids)
  - collection-scoped exports now explicitly mark `in_focus_collection` vs `is_nearby_context` and include `collection_name`, `focus_count`, `nearby_count` in `meta`
  - explorer supports served auto-load (`/cluster_data.json`), Discover/Outliers modes, and detail-panel review
  - collection-scoped review defaults to focus-only with an explicit `Show nearby (...)` toggle (default off)
  - collection-focused runs can remove an item from the collection from the detail panel when `api_base` is supplied
  - duplicate-review flow now includes grouped duplicate sets, keeper/loser marking, queueing, and batch apply buttons
  - latest snapshot (`tools/cluster_data.json`): `nodes=95`, `links=265`, `clusters=8`, scoped to `CB: Kitchen` with neighbors
  - remaining future scope: advanced curate mode (lasso/tray batch operations)
- Missing media paths are resolved: `missing stored_path=0`, `missing thumb_path=0`.

## Where to look
- `docs/AI_TAGGING_PLAN.md` — Gemini tagging workflow and CLI usage
- `docs/SEARCH_STRATEGY.md` — hybrid search + embeddings + knowledge graph plan
- `docs/ARCHITECTURE.md` — end‑to‑end pipeline and options
- `docs/tagging_pipeline.md` — preflight + estimates + auto mode
- `docs/next_steps.md` — quick resume checklist after restart
- `docs/handoff.md` — detailed timestamped execution history
- `docs/CLUSTER_EXPLORER_SPEC-v2.md` — current cluster explorer implementation target

## Next steps (suggested)
1. Continue tray/collection workflow simplification, especially clarity of tray actions and discoverability on iPad.
2. Validate collection-focused outlier removal workflow end-to-end on real curation sessions and tune thresholds.
3. Keep handoff docs current (`docs/handoff.md`, `docs/pr_summary.md`, `docs/next_steps.md`) after each material change.
