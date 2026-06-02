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
