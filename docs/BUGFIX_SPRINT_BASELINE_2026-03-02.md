# Bug-Fix Sprint Baseline (Mar 2, 2026)

## Scope Freeze
- Pause net-new product work.
- Focus on stabilization for iPad + desktop.
- Keep phone-specific issues deferred unless a fix is trivial and low risk.

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
- Unit tests: `PASS` (`212` tests)

## Clear Fixes Applied During Sprint Kickoff
- Fixed CI lint failure in `src/inspirations/server.py` by importing `uuid` for ingest-label inserts.
- Added automated ingest-metadata coverage for scan/photo/video upload workflows.

## Queue for Jim (Unclear Workflow/Feature Decisions)

1. `JIM-1` Tag-chip source set for ingest UI.
- Current behavior: uses top label facets (`/api/facets` labels).
- Decision needed: should ingest chips be limited to a curated “system type tags” subset only?

2. `JIM-2` Clip-bucket taxonomy visibility.
- Current behavior: scan/photo/video uploads all land in `source='scan'` (Clip), subtype tracked in `content_kind`.
- Decision needed: should sidebar/source counts expose subtype branches (`Clip > Scan/Photo/Video`) or remain unified?

3. `JIM-3` Scan title override semantics for multi-page docs.
- Current behavior: title override keeps existing doc suffix (` - doc N pM`) for scan pages.
- Decision needed: keep suffix-preserving behavior or flatten to exact owner title for all pages?

4. `JIM-4` Video poster/thumb strategy.
- Current behavior: video assets render with `<video>` in grid/modal; no generated poster policy is enforced here.
- Decision needed: require poster generation, or accept runtime first-frame behavior?

5. `JIM-5` Manual acceptance gate for bug-fix closure.
- Decision needed: confirm minimum manual regression list for sign-off (owner view, collaborator view, iPad explorer, import modals).
