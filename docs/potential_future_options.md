# Potential Future Options

Last updated: February 8, 2026

## Current Baseline (Verified)

- Pinterest ZIP in this repo (`dataset_pinterest-crawler_2026-01-30_02-07-52-338.zip`) contains exactly `3661` JSON records.
- Pinterest imported assets in DB: `3661`.
- Pinterest embedding rows in DB: `3661` (model `gemini-embedding-001`).
- Facebook export (`facebook-lesliebrannigan-2026-01-30-RCSuQaKZ.zip`) contains `8535` saved items.
- In that Facebook export, only `75` items contained a usable HTTP URL path currently targeted by importer; `74` unique URLs.

## 1) Pinterest Update Strategy (If More Pins Are Added)

### Option A: Export-Delta Sync (Recommended Immediate Path)
- Continue periodic Pinterest export + re-import.
- Keep idempotent upsert key as `(source='pinterest', source_ref=<pin_url>)`.
- Add an import report showing:
  - raw export count
  - parsed candidate count
  - new inserts
  - already-existing rows
  - skipped reasons
- Trigger post-import pipeline:
  - originals download for new rows
  - thumbs generation for new rows
  - AI tagging for new rows
  - embeddings for new rows

Pros:
- No new auth complexity.
- Fully compatible with current architecture.

Cons:
- Manual export step.
- Snapshot, not near-real-time sync.

### Option B: Browser Capture Assist
- Add bookmarklet/extension to save current pin URL into app directly.
- Use as a fallback for one-off saves between exports.

Pros:
- Immediate, user-controlled capture.

Cons:
- Manual interaction per pin.

### Option C: Official OAuth/API Connector
- Build connector around official Pinterest APIs for boards/pins.
- Introduce scheduled incremental sync with persisted checkpoint cursors.

Pros:
- Better incremental updates.
- Better user experience if policy/compliance allows.

Cons:
- Higher engineering complexity.
- Must pass platform policy/compliance gates for storage/usage.

## 2) Facebook Saved Items Strategy (Updates + Better Coverage)

### Current Constraint
- Export structure is heterogeneous. Most saved entries do not expose a downloadable media URL.
- Current importer intentionally ingests only entries with `attachments[0].data[0].external_context.source`.

### Improvement Options

1. Reference-only ingest mode (Recommended)
- Import non-media items as metadata-only assets:
  - title
  - timestamp
  - source domain/name
  - optional link if present
- Mark `media_status='none'` (or equivalent field) so UI can filter these records.

2. URL enrichment pass
- For reference-only items with a resolvable URL, attempt metadata preview extraction.
- Attach thumbnail/title if available and safe.

3. Export cadence + delta sync
- Re-run export on cadence and use source key dedupe.
- Same reporting pattern as Pinterest (new vs existing vs skipped).

## 3) Commercialization Path (Multi-User, Mostly Pinterest)

### Product/Platform Building Blocks

1. Multi-tenant auth and org/user model.
2. Connector token storage with encryption-at-rest and rotation.
3. Job queue + worker pool for ingestion/sync pipelines.
4. Object storage for media and generated derivatives.
5. Source-aware dedupe:
- logical dedupe by `(source, source_ref)`
- binary dedupe by `sha256`.
6. Observable sync engine:
- run records
- checkpoint cursors
- error taxonomy
- retries with backoff.
7. Compliance controls:
- consent logs
- user data export
- user data deletion.

### Ingestion/Sync Mechanism (Target Design)

1. Connector setup
- User links source (OAuth if available, else export upload).

2. Initial backfill
- Full pull/import, normalize to canonical asset schema.

3. Incremental sync
- Scheduled jobs per user+source using checkpoint cursor/watermark.
- Idempotent upsert and deterministic conflict policy.

4. Post-processing pipeline
- media fetch -> thumbnails -> AI tags -> embeddings.

5. End-user visibility
- Sync status page with per-source health, last run, next run, error details.

### High-Risk Areas (Do Early)

1. Platform policy/legal validation for Pinterest data retention and commercial usage.
2. Rate-limit and cost modeling for API + AI pipelines at multi-tenant scale.
3. Abuse controls (malicious URLs, oversized media, prompt abuse, spam accounts).

## 4) Recommended Work To Implement Now

1. Add `sync_runs` + `source_checkpoints` tables.
2. Build a generic incremental sync driver (`start_run`, `fetch_delta`, `upsert`, `checkpoint`).
3. Improve import telemetry for both Pinterest and Facebook.
4. Add Facebook reference-only ingest mode.
5. Add a manual capture path (bookmarklet/browser helper) for gaps between exports.
6. Add reboot-safe development continuity workflow (below).

## 5) Reboot/Update Continuity Workflow (To Avoid Lost Progress)

Use this every time before stopping work:

```bash
PYTHONPATH=src python3 tools/session_checkpoint.py \
  --note "short summary of what changed" \
  --next "explicit next action 1" \
  --next "explicit next action 2"
```

What this does:
- Captures current branch/commit/dirty state.
- Captures dataset progress and run status (via `tools/session_sync.py` snapshot logic).
- Captures embedding coverage.
- Appends a structured checkpoint entry into `docs/handoff.md`.

On resume after reboot/update:
- Read `docs/next_steps.md`.
- Read the latest checkpoint section in `docs/handoff.md`.
- Run:
  - `PYTHONPATH=src python3 tools/session_sync.py`
- Continue from the explicit `Next actions` list recorded in the last checkpoint.
