# Inspirations

Local-first inspiration library for home design research.

Inspirations scrapes Pinterest boards and Facebook saved items directly from the browser, enriches them with AI tagging (Gemini), and provides Jim's local curation/QC app for triaging, organizing, exploring, and exporting designer-ready collection PDFs.

## What The Project Does

1. **Scrape** — Browser-scrapes Pinterest boards and Facebook saved items, capturing rich metadata (titles, descriptions, hashtags, creator names, engagement data, high-res images)
2. **Import** — Normalizes scraped data into a single SQLite catalog with local media storage
3. **Tag** — Runs Gemini AI tagging for searchable labels, summaries, and embeddings
4. **Curate** — Browse the usable corpus, optionally review focused scopes, flag or discard problem items, and build collections visually
5. **Organize** — Natural-language collection management ("move all kitchen items to a new collection")
6. **Export** — Export one curated collection at a time as a standalone PDF with embedded local images and visible/clickable source URLs

## Data Sources

- **Pinterest** — Full account scrape of all boards and pins
- **Facebook** — Full account scrape of saved items (posts, links, photos, videos, reels)
- **Scans** — Local images and PDFs (magazine clippings, printouts)

## Tech Stack

- Python 3.11+ (standard library only, no framework dependencies)
- SQLite
- Local filesystem storage (`store/`)
- Standard-library HTTP server for local app/API
- Vanilla HTML/CSS/JS frontend (no build step)
- Google Gemini API for AI tagging and embeddings
- Optional: `sips` (macOS) or ImageMagick for thumbnails, Pillow fallback

## Quick Start

1. Initialize DB + store directories:
```sh
PYTHONPATH=src python3 -m inspirations init
```

2. Import scraped data (after browser scraping is complete):
```sh
PYTHONPATH=src python3 -m inspirations import pinterest-scrape --json data/scrape/pinterest_scrape.json
PYTHONPATH=src python3 -m inspirations import facebook-scrape --dir data/scrape/
```

3. Generate thumbnails:
```sh
PYTHONPATH=src python3 -m inspirations thumbs --size 512
```

4. Configure Dave chat key (Anthropic):
```sh
security add-generic-password -U \
  -a "$USER" \
  -s inspirations_anthropic_api_key \
  -w 'sk-ant-REPLACE_WITH_REAL_KEY'
```

Or for a one-off shell session:
```sh
export ANTHROPIC_API_KEY='sk-ant-REPLACE_WITH_REAL_KEY'
```

See `docs/LOCAL_DAVE_API_KEY.md` for verification and troubleshooting.

5. Start the app:
```sh
PYTHONPATH=src python3 -m inspirations serve --host 127.0.0.1 --port 8001
```
Open [http://127.0.0.1:8001](http://127.0.0.1:8001).

For iPhone/iPad/LAN testing:
```sh
./tools/run_review_server.sh
```
This binds to `0.0.0.0:8001` by default so iPads/iPhones on the same LAN can
open `http://<mac-lan-ip>:8001`.

For logged, login-persistent service mode on the Mac mini:
```sh
./tools/inspirations_service.sh install
./tools/inspirations_service.sh status
./tools/inspirations_service.sh logs
```
This installs a user LaunchAgent named `com.jimbrannigan.inspirations` with
`KeepAlive`, still bound to `0.0.0.0:8001`. Logs are written under
`data/logs/` and are intentionally local-only.

Behind a reverse proxy (e.g., New Home Next.js site at `/inspirations-app`):
```sh
BASE_PATH=/inspirations-app PYTHONPATH=src python3 -m inspirations serve --port 8001
```

## App Workflows

### Collection Browsing
- Browse collections as tile grids showing pins, photos, PDFs, and Facebook saves
- Click **Make Collection**, select cards, then create a new collection or add the selection to an existing one
- When browsing exactly one collection, **Make Collection** can also remove selected cards from that collection
- Natural-language prompt to manage collections ("take all the things from this collection and put them into that collection")
- Filter by source, board, tags, and more

### Attractor Explorer
- Semantic visualization of your entire collection as a force-directed map
- **2D mode** — Canvas-based D3 force layout with scroll-zoom and CSS pre-zoom feedback
- **3D mode** — Three.js WebGL with OrbitControls, billboard thumbnails, and custom 3D force simulation
- Sidebar filters and text search define the base item scope
- Category chips have explicit **Filter** and **Group** modes: Filter narrows the visible items; Group arranges the current scope around selected category poles
- 3D adds a `Group by` shortcut for Source, Room, Style, Material, Color, and Product grouping without changing sidebar scope
- Sliders include editable numeric fields so tuning works on iPad as well as desktop
- Broad iPad/mobile-constrained sets use `iPad lite: 2D map`; filtered subsets can switch back to 3D when the measured WebGL budget allows it

### Browse and Optional Review
- Ordinary browsing shows the usable corpus; legacy `pending` and `keeper` states do not imply that Leslie must re-review the library
- Use **Browse → Review Status** in the sidebar to revisit keepers, flagged items, needs-comment items, or discarded/irrelevant items and restore any mistakes
- Hit **Review** when a focused scope benefits from selection actions: keep, discard, restore, flag, or remove from the active collection
- One-by-one review remains available for focused QC work

### Annotation
- After triage, walk through items marked for annotation
- Add point-based notes directly on images
- Notes persist with the asset across collections

### Admin Maintenance
- Open **Admin** from the app header
- On first use, open `http://localhost:8001/app/admin.html` on the Mac and choose an admin password
- Replacement media is applied immediately; use **Refresh Search Evidence** in Admin to retag replacement photos, rebuild semantic embeddings, and refresh Explorer classification evidence in a deliberate batch
- Generated text cards skip visual retagging and receive text embeddings only

### Collection PDF Export
- Use **+ New Collection** to create a collection
- Use **Make Collection** for the primary visual workflow: select cards from the current browse scope, then create a new collection or add them to an existing one
- Use **Manage Collections** to rename collections and edit their descriptions
- Use **Manage Collection Archive** to archive, restore, or permanently delete obsolete collection folders. Archiving a folder does not hide or delete its items.
- Select exactly one collection in the sidebar, then click **Export Collection PDF** in the persistent curation bar
- CLI equivalent:
```sh
PYTHONPATH=src python3 -m inspirations export collection-pdf \
  --collection-id <id> \
  --out data/exports/<name>.pdf
```
- The exporter writes both `data/exports/<name>.md` and `data/exports/<name>.pdf`
- Local images/previews are copied under `data/exports/<name>_media/` so the PDF does not depend on the running app or `store/`
- Source URLs are visible and clickable, but only external `http`/`https` links are included; local app/media/store links are omitted
- The PDF uses one item per page, with the image, source details, labels, notes, and annotation markers kept together
- Requires local `pandoc` and `tectonic` for PDF rendering

## AI Tagging (Gemini)

```sh
GEMINI_API_KEY="YOUR_KEY" PYTHONPATH=src \
python3 -m inspirations ai tag --provider gemini --source pinterest --image-kind thumb
```

Primary model: `gemini-2.5-flash`. Automatic fallback to `gemini-2.0-flash` on RECITATION errors.

## Repository Layout

- `src/inspirations/` — CLI, DB layer, importers, AI pipeline, server
- `app/` — Local web app assets (vanilla HTML/CSS/JS, including attractor explorer 2D/3D)
- `tools/` — Operational scripts
- `tests/` — Unit tests
- `docs/` — Current specs and plans
- `docs/archive/` — Archived documentation from pre-rebuild era
- `imports/` — Local input datasets (scans)
- `store/` — Downloaded originals and generated thumbnails
- `data/` — SQLite DB, scrape JSON files, batch artifacts

## Testing

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
ruff check src tests
```

## Current Status

The scrape-first rebuild is complete. Inspirations is a local-first corpus
curation and QC app with browse-first collection making, optional focused
review, Grid and Explorer views, Dave, source/media repair, annotations, and
one-collection standalone PDF handoffs. The live collaborator/magic-link layer
is retired from the active product; legacy schema remains for compatibility but
is not presented in the UI. Obsolete `pins:` source-board mirrors and completed
`Review:` workflow folders were removed after a local SQLite backup; live source
board browsing now uses `assets.board` metadata directly.

## Future Work

- Improve PDF layout quality, ordering controls, and source-link completeness for designer handoffs.
- Keep static HTML/portal exports as legacy/debug utilities unless intentionally revived.

## Docs

- `docs/SCRAPE_REBUILD_SPEC.md` — Current implementation spec
- `docs/CURRENT_HANDOFF.md` — Authoritative reboot/resume checkpoint
- `docs/INSPIRATIONS_SERVICE_RUNBOOK.md` — Logged launchd service and LAN uptime runbook
- `docs/EXPLORER_CONTROL_HANDOFF_2026-05-24.md` — Current Explorer control semantics and latest smoke-test notes
- `docs/COLLECTION_PDF_EXPORT_HANDOFF_2026-05-27.md` — Current PDF export and live-sharing retirement handoff
- `docs/TODO_CONSUMING_UX.md` — Legacy consuming-UX notes, superseded by PDF handoff direction
- `docs/archive/` — Historical documentation from the pre-rebuild system
- `CLAUDE.md` — AI assistant guidance for working in this repo
- `DECISIONS.md` — Architectural decision records
- `AGENTS.md` — Project-specific agent notes

## License

Proprietary.
