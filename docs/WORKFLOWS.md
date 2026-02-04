# Workflows (practical day-to-day)

## Pinterest — “Find new pins”
Because Pinterest exports are snapshots, the MVP “new pins” workflow is **periodic re-export + idempotent import**:

1. Run your Pinterest export tool (daily/weekly/as-needed).
2. Drop the new ZIP into `imports/raw/` (or a dated subfolder).
3. Run:
   - `PYTHONPATH=src python3 -m inspirations import pinterest --zip imports/raw/dataset_pinterest-crawler_*.zip`
4. The importer uses `(source, source_ref)` as a stable key, so re-importing the same pins does not duplicate.

**Later (optional):** automatic discovery of new pins via Pinterest API/scraping, but that adds auth/session handling and higher break risk; the snapshot workflow is more robust.

## Scans — “Pull in magazine clippings”
Recommended inbox model (local-first, low friction):

1. Pick a scan destination folder (e.g. `imports/scans/inbox/`).
2. Configure your scanner app to drop JPG/PNG there (preferred), or PDFs.
3. Run a scan import command (to be implemented next) that:
   - hashes each file (SHA-256) for idempotency/dedupe
   - copies it into `store/originals/scan/`
   - creates/updates an `Asset` row with `source='scan'`
   - generates thumbnails (Phase 1/2 depending on tooling)

**Later:** a folder watcher can make this automatic.

## Facebook saves — “More considered update”
Facebook’s saved-items export is heterogeneous; many entries don’t include a retrievable URL.

Recommended MVP approach:
1. Re-export periodically (monthly/quarterly) and re-import idempotently.
2. Only ingest items that contain `external_context.source` (often a direct image URL).
3. Log skipped items and iterate on heuristics only if the export adds more useful fields later.

Optional follow-up:
- If you can identify additional Facebook export files that contain richer saved-link metadata (URLs/previews), we can add another adapter and merge them.

