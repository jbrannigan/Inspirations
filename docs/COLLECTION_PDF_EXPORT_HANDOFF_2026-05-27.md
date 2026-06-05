# Collection PDF Export Handoff - 2026-05-27

## Product Direction

Inspirations is now Jim's local corpus-management and QC app. Keep Grid,
Explorer 2D/3D, Review/Triage, Dave/chat/catalog, imports, source-link QC,
annotations, notes, live filtering, and collection management.

The retired surface is the live collaborator product layer:

- magic-link actor UX
- actor/context chips in normal UI
- collaborator assignment and generated app links
- `?actor=...&collection_id=...` context-link sharing
- collaborator question dashboard/polling
- owner "Share Collections" live-link workflow as the primary deliverable
- static browser share portal as the primary designer deliverable

The active designer handoff is a standalone PDF for exactly one collection at a
time.

## Current PDF Export Behavior

CLI:

```bash
PYTHONPATH=src python3 -m inspirations export collection-pdf \
  --collection-id <id> \
  --out data/exports/<name>.pdf
```

App/API:

- Contextual persistent-curation-bar button: `Export Collection PDF` when exactly one collection is selected
- Sidebar button: `Manage Collections` for local name/description editing
- Sidebar button: `Manage Collection Archive` for archiving, restoring, and permanently deleting obsolete collection folders. Folder archiving does not hide or delete member items.
- API: `POST /api/collections/{collection_id}/export/pdf`
- The API returns a PDF attachment.

Generated artifacts:

- `data/exports/<name>.md` is kept for audit/debugging.
- `data/exports/<name>.pdf` is rendered with local `pandoc` and `tectonic`.
- `data/exports/<name>_media/` contains copied local previews used by the Markdown/PDF.

Export rules:

- Exports only the requested collection.
- Preserves `collection_items.position` ordering.
- Excludes hidden triage assets and assets in the legacy `Hidden` collection.
- Uses copied local images/previews, not `/media`, `/store`, localhost, or LAN URLs.
- Includes only external `http`/`https` source URLs.
- Rejects/omits localhost, LAN/private IPs, `.local`, `/api`, `/media`, `/store`, and `/app` links.
- Shows visible clickable URL text for included sources.
- Shows `No source URL available` when no safe external source exists.
- Uses a report cover plus one page per item, keeping the image and its contextual information together.
- Includes notes, labels, and numbered annotation markers with their annotation text.
- Media-repair generated text cards are ordinary stored local images, so they are copied into exports like any other preview.

## Implementation Notes

Main code:

- `src/inspirations/export.py`
  - `export_collection_pdf()`
  - PDF-specific tool errors: `PdfToolUnavailableError`, `PdfRenderError`
  - Markdown/media generation and external-source URL filtering
- `src/inspirations/cli.py`
  - `export collection-pdf`
- `src/inspirations/server.py`
  - `POST /api/collections/{id}/export/pdf`
  - retired live-sharing endpoints return JSON 404s
- `app/index.html`, `app/app.js`, `app/shared.js`
  - contextual `Export Collection PDF` button
  - visible `Manage Collections` local-metadata editor
  - visible `Manage Collection Archive` archive/restore/delete utility
  - local-owner mode by default
  - no actor token headers
  - magic-link URL tokens are stripped rather than persisted
  - question UI and generated link UI are inactive/hidden

Tests:

- `tests/test_export_pdf.py`
  - scoping, ordering, media copy references, external source URLs, local/app URL rejection, missing-source fallback, missing tools, renderer failures
- `tests/test_server_api.py`
  - API PDF attachment smoke test
  - retired endpoint expectations for `/api/me`, `/api/actors`, `/api/context/resolve`, `/api/questions/dashboard`
  - local no-token requests are treated as owner mode

## Legacy Schema

Kept intentionally for now:

- `actors`
- `collection_shares`
- `collections.intent`
- `collections.shared_actor_id`
- annotation `actor_id`, `actor_name`, `annotation_type`, `resolved`

Do not drop these in this pass. Treat them as compatibility fields until there is a separate schema cleanup decision.

## Validation Commands

```bash
node --check app/shared.js
node --check app/app.js
node --check app/attractor-explorer.js
node --check app/attractor-explorer-3d.js
PYTHONPATH=src python3 -m py_compile src/inspirations/export.py src/inspirations/cli.py src/inspirations/server.py src/inspirations/store.py
PYTHONPATH=src python3 -m unittest tests.test_export_pdf tests.test_server_api
```

Recommended broader regression:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

Manual checks:

- Desktop: Grid filtering still works.
- iPad: Grid filtering and Explorer loading still work over LAN.
- Explorer 2D/3D still responds to filters and updates count/mode hint.
- Review/Triage still works.
- Dave still filters/shows items.
- Select one collection, click `Export Collection PDF`, open PDF, confirm images render and source URLs are visible/clickable without the app running.

## Next Improvements

1. Improve PDF visual layout for real designer consumption.
2. Add explicit collection ordering/editing UI if PDF ordering needs manual control beyond current collection positions.
3. Audit source URL completeness before serious handoffs.
4. Decide later whether to delete or migrate legacy collaborator schema and old portal export code.
5. If public hosting returns, use launchd + shared Cloudflare tunnel; do not revive DevLauncher as the uptime solution.
6. Continue media-repair QC with the modal `Repair media` gallery; see `docs/MEDIA_REPAIR_IMPLEMENTATION_PLAN_A_2026-03-10.md`.
