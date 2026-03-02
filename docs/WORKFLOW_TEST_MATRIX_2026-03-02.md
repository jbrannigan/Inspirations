# Workflow Test Matrix (Mar 2, 2026)

This matrix ties known workflows to automated validation and manual checks for the bug-fix sprint.

## Automated Matrix

| Workflow Area | Key Behaviors | Automated Coverage | Status |
|---|---|---|---|
| Auth + role gates | actor token resolution, owner-only hidden access, admin token checks | `tests/test_server_api.py`, `tests/test_security.py` | Covered |
| Browse/filter/tree | source/board/catalog/collection filters, hidden exclusion | `tests/test_store.py`, `tests/test_tree_contract.py`, `tests/test_server_api.py` | Covered |
| Collaboration context links | resolve states, hidden-role behavior | `tests/test_server_api.py` | Covered |
| Modal triage/annotation | keep/hide/reset, flag/tag, annotation permissions | `tests/test_server_api.py`, `tests/test_triage.py` | Covered |
| Explorer API/layout | attractor data/layout, include-hidden owner gate | `tests/test_explorer_layout.py`, `tests/test_server_api.py` | Covered |
| Import: clip PDF | upload endpoint, renderer wiring, thumbs trigger | `tests/test_server_api.py`, `tests/test_scans_import.py` | Covered |
| Import: photo/video to clip bucket | source mapping (`scan`), subtype content_kind | `tests/test_server_api.py`, `tests/test_scans_import.py` | Covered |
| Import metadata | title/tags parsing, batch apply, scan suffix preservation | `tests/test_server_api.py` | Covered |
| Media serving | `/media` original/thumb/pdf behavior | `tests/test_server_api.py`, `tests/test_serve_explorer.py` | Covered |
| AI semantic/title workflows | embedding/search and title-audit lifecycle | `tests/test_ai_semantic.py`, `tests/test_title_audit.py`, `tests/test_ai_gemini_parse.py` | Covered |
| Export workflows | cluster, html, collaborator portal exports | `tests/test_export_clusters.py`, `tests/test_export_html.py`, `tests/test_export_portal.py` | Covered |
| Scrape adapters/backfill | pinterest/facebook importers, backfill, preview extraction | `tests/test_pinterest_scrape_import.py`, `tests/test_facebook_scrape_import.py`, `tests/test_storage_backfill.py`, `tests/test_preview_extract.py` | Covered |
| Chat routing + serve lifecycle | action parse/routing, serve reload behavior | `tests/test_chat.py`, `tests/test_cli_serve.py`, `tests/test_devserver.py` | Covered |

## Manual Matrix (Required for Bug-Fix Sign-Off)

| Workflow | Device/Role | Why Manual |
|---|---|---|
| Grid/Explorer mode switch behavior | iPad + desktop, owner + collaborator | Rendering/perf/UX timing are not fully captured in unit tests |
| Collaborator tree unlock (`Browse Leslie's collection`) | iPad + desktop, collaborator | Interaction sequencing and visual tree integrity are UI-level |
| Add Media modal UX | desktop + iPad, owner | Input ergonomics, chips behavior, and modal transitions are browser UX concerns |
| Video card/modal playback | iPad + desktop | Browser codec/policy differences not deterministic in unit tests |
| Print flow from modal | Safari + Chrome | Print-window behavior is browser-specific |

## Canonical Suite Commands

- Full suite runner: `tools/run_bugfix_suite.py`
- Direct parity commands:
  - `ruff check src tests`
  - `PYTHONPATH=src python -m unittest discover -s tests -v`

## Current Baseline

- Lint: PASS
- Unit tests: PASS (`212` tests)
- Manual matrix: pending owner acceptance
