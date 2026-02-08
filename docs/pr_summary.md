# PR Summary

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
