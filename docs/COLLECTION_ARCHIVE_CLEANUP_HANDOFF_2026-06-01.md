# Collection Archive Cleanup Handoff - 2026-06-01

## Product Meaning

Collection folders and hidden assets are separate concepts:

- Asset triage `hidden` removes an item from normal corpus browsing.
- Collection-folder archiving removes an obsolete or completed folder from the
  active Collections tree without hiding or deleting its member assets.

The UI uses `Archived Collections` and `Manage Collection Archive` to keep
those concepts distinct.

## Cleanup Executed

Before deletion, a local SQLite backup and JSON manifest were written:

- `data/backups/inspirations-backup-before-collection-archive-cleanup-20260602T031426Z.sqlite`
- `data/exports/collection-archive-cleanup-20260602T031426Z.json`

Both files are intentionally local-only under ignored `data/`.

Deleted collection folders:

- 48 obsolete `pins:` source-board mirrors
- 17 completed archived `Review:` workflow folders
- 10 legacy archived folders
- 1 active `Review: Media Reliability Residual - 2026-06-01` working folder

Total deleted: 76 folders.

SQLite `pragma quick_check` returned `ok` before and after cleanup.

## Current Active Collection Baseline

15 collection folders remain:

- 12 `CB:` AI-derived representative starting sets
- 3 architect first-meeting scan cohorts

The `CB:` folders are useful working hypotheses, not human-curated final
designer collections.

## UX Behavior

If collection folders are archived later, the Collections tree groups them
under:

- `Archived Collections`
  - `Completed Reviews`
  - `Imported Board Mirrors`
  - `Legacy Folders`

The archive manager uses the same grouping and makes the non-destructive folder
semantics explicit.

The retired CLI `promote-boards` path was removed. `rebuild-db` also leaves
source boards as metadata instead of recreating mirror collections.

## Next UX Issue

The next branch should focus on creating deliberate curator-owned collections:

- make new-collection creation obvious from the canvas workflow
- clarify whether creation starts empty, from selected items, or from current
  scope
- preserve manual item ordering for designer PDF export
- avoid reviving obsolete `pins:` source mirrors as collections

## Browse-First Follow-Up

The everyday curation surface was simplified after the archive cleanup:

- removed the prominent legacy review-queue dropdown
- ordinary browsing treats legacy null=`pending` and `keeper` assets as usable
- added a persistent canvas curation bar with text search, active filters, and a
  `Show` selector for usable, all, keeper, flagged, and discarded item views
- added direct restore actions for discarded cards and context-aware restore in
  focused review mode

The underlying triage schema and audit log remain for compatibility and
diagnostics. They are no longer presented as a corpus-wide backlog for Leslie.

In grid Review mode, the shared `Show` selector and the card interactions have
deliberately different meanings:

- `Keepers`, `Flagged`, and `Discarded` item views revisit durable curation decisions
  within the current collection, text-search, and tree-filter scope
- clicking a card always opens the same full detail/QC modal, regardless of the
  selected `Show` item view
- that full detail/QC modal always keeps compact `Keep`, `Discard / Restore`,
  and `Flag / Unflag` actions available
- the explicit `One-by-one` action opens the fast triage screen
- one-by-one review offers `Edit title / media` to open the full detail/QC modal
  for title repair, media repair, annotations, and notes
- clicking its checkbox selects it for bulk keep, discard, restore, or flag
- Make Collection remains selection-first, so clicking a card there selects it

These are simple, mutually exclusive scope filters, not a return of the retired
review-queue dropdown. Removing a star, unflagging an item, or restoring a
discarded item while its filter is active removes it from the visible result
set.

## Collection-Building Follow-Up

The browse-first collection workflow is now implemented:

- `Make Collection` is a separate canvas mode beside `Review`
- cards receive visible selection checkboxes while that mode is active
- its contextual row in the shared sticky curation bar can create a collection
  from selected cards, add cards to an existing collection, or remove cards
  when one collection is in scope
- entering Explorer closes the grid-based collection selection mode
- the grid auto-loads the next asset page when scrolling near the bottom;
  `Load More` remains as a fallback
- automatic loading uses an `IntersectionObserver` on the Load More sentinel,
  with scroll-distance checks as a fallback for desktop and narrow layouts; it
  begins several screenfuls early and gives the asset-page request high priority
- append-load failures keep already visible cards on screen and report the
  failure as a toast instead of replacing the grid
- the fallback button changes to `Loading…` as soon as automatic or manual
  pagination begins, and the top item count also reports `loading more…`, so
  slower iPad/LAN requests do not look inert
- `Load More` now reliably re-enables after an asset page fetch; the frontend
  must clear `state.loadingAssets` before refreshing that button state
- scope changes queued during an automatic append load now trigger a full reload
  after the append finishes, so the `Show` selector cannot disagree with the
  visible cards

This intentionally keeps creative collection building separate from Review/QC.
The next collection UX pass can focus on ordering items for the PDF and
polishing empty-folder creation if it remains useful.

## Service Reliability Follow-Up

Intermittent asset-page and thumbnail failures were traced to request-time
`ensure_schema()` calls in the threaded HTTP server. Concurrent API and media
requests could each perform migration/backfill writes and trigger
`sqlite3.OperationalError: database is locked`.

The server now runs schema assurance once during startup, before accepting
requests. Normal API, catalog, media, and scan-PDF requests remain read-oriented
and must not reintroduce migration writes. SQLite connections also use a
30-second busy timeout, and the launchd service logs remain the first place to
inspect unexplained service or loading failures.
