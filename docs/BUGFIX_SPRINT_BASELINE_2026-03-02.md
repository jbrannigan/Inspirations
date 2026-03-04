# Bug-Fix Sprint Baseline (Mar 2, 2026)

## Scope Freeze
- Pause net-new product work.
- Focus on stabilization for iPad + desktop.
- Keep phone-specific issues deferred unless a fix is trivial and low risk.

## Operational Runbooks
- Dave/Anthropic key setup and keychain service name: `docs/LOCAL_DAVE_API_KEY.md`.

## Known Features and Workflows (Current System)

### 1) Identity, roles, and authorization
- Actor identity via magic-link token (`owner`, `collaborator`).
- Owner-only hidden visibility and owner-only administrative actions.
- Admin token flow for destructive asset deletion.
- Primary coverage: `tests/test_server_api.py`, `docs/AUTH_SPEC.md`.

### 2) Browse, filtering, and tree navigation
- Source/board/catalog/collection/status filtering.
- Recursive catalog and collection scope handling.
- Hidden-asset exclusion by default for non-owner contexts.
- Primary coverage: `tests/test_store.py`, `tests/test_tree_contract.py`, `tests/test_server_api.py`, `tests/test_triage.py`.

### 3) Collaboration context links
- Shared context link resolution (`collection_id` + `item_id`).
- Role-gated hidden-item behavior in shared contexts.
- Primary coverage: `tests/test_server_api.py`.

### 4) Grid + modal curation workflows
- Detail modal open/navigation.
- Triage actions (keep/hide/reset), flag/tag actions, annotation permissions.
- Print/media open behavior for scan docs.
- Primary coverage: `tests/test_server_api.py`, `tests/test_triage.py`, `tests/test_store.py`.

### 5) Explorer workflows
- Explorer attractor payloads and layout generation.
- Include-hidden owner gating.
- Cluster review payload export.
- Primary coverage: `tests/test_explorer_layout.py`, `tests/test_server_api.py`, `tests/test_export_clusters.py`.

### 6) Ingestion workflows (clip-bucket)
- Clip PDF upload (`/api/import/scans`).
- Photo upload (`/api/import/photos`) into clip source bucket.
- Video upload (`/api/import/videos`) into clip source bucket.
- Ingest metadata capture (`title`, `tags`) and application to imported batch.
- Primary coverage: `tests/test_scans_import.py`, `tests/test_server_api.py`.

### 7) Thumbnail and media serving
- Thumbnail generation/fallback behavior.
- `/media/<id>` serving and PDF routing behavior.
- Primary coverage: `tests/test_thumbnails.py`, `tests/test_server_api.py`, `tests/test_serve_explorer.py`.

### 8) AI and semantic workflows
- Embedding generation and semantic search endpoint.
- AI title-audit dry-run/stage/review/apply/undo flows.
- AI parsing and recitation fallback behavior.
- Primary coverage: `tests/test_ai_semantic.py`, `tests/test_title_audit.py`, `tests/test_ai_gemini_parse.py`, `tests/test_ai_recitation_fallback.py`.

### 9) Export workflows
- Cluster export JSON.
- HTML export and collaborator portal export.
- Primary coverage: `tests/test_export_clusters.py`, `tests/test_export_html.py`, `tests/test_export_portal.py`.

### 10) Scrape import adapters and pipeline utilities
- Pinterest/Facebook scrape importer normalization and idempotency.
- Storage backfill and preview extraction.
- Primary coverage: `tests/test_pinterest_scrape_import.py`, `tests/test_facebook_scrape_import.py`, `tests/test_storage_backfill.py`, `tests/test_preview_extract.py`.

### 11) Chat routing and CLI serve lifecycle
- Chat action extraction and routing behavior.
- Serve/reload process behavior.
- Primary coverage: `tests/test_chat.py`, `tests/test_cli_serve.py`, `tests/test_devserver.py`.

### 12) Security and transport guardrails
- URL safety and private-IP protections.
- Static/store serving allowlist and cache policy constraints.
- Primary coverage: `tests/test_security.py`, `tests/test_serve_explorer.py`, `tests/test_server_api.py`.

## Complete Validation Suite

### Canonical command
- `tools/run_bugfix_suite.py`

### What it runs
- `ruff check src tests`
- `PYTHONPATH=src python -m unittest discover -s tests -v`

### CI parity
- Matches `.github/workflows/ci.yml` lint + unit-test stages.

## Baseline Run (Mar 2, 2026)
- Runner: `tools/run_bugfix_suite.py`
- Result: `PASS`
- Lint: `PASS`
- Unit tests: `PASS` (`232` tests)

## Clear Fixes Applied During Sprint Kickoff
- Fixed CI lint failure in `src/inspirations/server.py` by importing `uuid` for ingest-label inserts.
- Added automated ingest-metadata coverage for scan/photo/video upload workflows.

## Jim Decisions (Captured Mar 2, 2026)

- Decision tickets and final outcomes: `docs/JIM_DECISION_TICKETS_2026-03-02.md`
- Outcome status: all `JIM-1` ... `JIM-5` approved.

Locked outcomes:
1. Ingest tag chips will use Explorer-aligned groups and include actor/date-time auto-tags.
2. Clip subtype branches (`Scan/Photo/Video`) will be exposed in UI now.
3. Scan title override remains suffix-preserving for split doc/page items.
4. Video poster generation is required in this bug-fix sprint.
5. Sprint closure requires a real manual run log (no assumed passes).

## Execution Updates (Mar 2, 2026)

- `JIM-1` implemented: ingest taxonomy chips now match Explorer groups and ingest auto-tags include `actor:*` + `ingested_at:*`.
- `JIM-2` implemented: Clip subtype branches (`Scan/Photo/Video`) are exposed and wired in tree filters.
- `JIM-3` verified: scan title override continues to preserve doc/page suffixes.
- `JIM-4` implemented: video ingest now attempts poster generation and UI uses poster thumbnails when available.

Latest automated validation:
- `tools/run_bugfix_suite.py` → `PASS`
- lint: `PASS`
- unit tests: `PASS` (`232` tests)

## Execution Updates (Mar 4, 2026)

- Collaborator browse UX clarity pass completed:
  - one explicit collaborator toggle now communicates state directly:
    - `Browse more from Leslie collection ...`
    - `Hide extra folders`
  - relock path restores shared-collections scope for collaborators.
- Sidebar/tree visual cleanup completed:
  - clearer nested hierarchy under `All Items` and `Collections`
  - removed internal vertical tree guide lines per UX decision.
- 3D outlier spacing fix completed:
  - when a node is missing from `/api/explorer/layout`, 3D merge now places it near layout centroid (small deterministic jitter) instead of leaving it on mismatched fallback coordinates.

Associated commits:
- `c96ab22` — collaborator toggle clarity + tree hierarchy UI polish
- `d334345` — unmatched 3D node centroid fallback

Latest validation (post-fix):
- Automated: `python3 tools/run_bugfix_suite.py` → `PASS`
  - lint: `PASS`
  - unit tests: `PASS` (`232` tests, `36.028s`)
- Manual: `PASS` on iPad + desktop checklist
  - run log: `docs/MANUAL_SIGNOFF_LOG_2026-03-04.md`

## Technical Debt: Retired Tag Workflow (Mar 2, 2026)

Decision: UI/UX tag workflow is retired and no longer exposed in product flows.

Current stop-state (implemented):
1. Tag actions are removed from modal and canvas-review UI.
2. Quick-tag controls are no longer rendered on cards.
3. Tag API write endpoints now return `410` (`tag workflow retired`).

Remaining cleanup debt to remove in a follow-up refactor:
1. Legacy DB fields on `assets` (`tagged`, `tagged_by`, `tagged_note`) are still present.
2. Legacy store helpers for tag writes remain in `src/inspirations/store.py`.
3. Legacy read-path fields/filters still include `tagged` metadata in some responses.
4. Unused CSS selectors related to removed tag controls remain in `app/styles.css`.
