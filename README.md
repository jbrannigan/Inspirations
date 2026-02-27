# Inspirations

Local-first inspiration library for home design research.

Inspirations scrapes Pinterest boards and Facebook saved items directly from the browser, enriches them with AI tagging (Gemini), and provides a local curation app for triaging, organizing, and sharing design inspiration collections.

## What The Project Does

1. **Scrape** — Browser-scrapes Pinterest boards and Facebook saved items, capturing rich metadata (titles, descriptions, hashtags, creator names, engagement data, high-res images)
2. **Import** — Normalizes scraped data into a single SQLite catalog with local media storage
3. **Tag** — Runs Gemini AI tagging for searchable labels, summaries, and embeddings
4. **Triage** — Keeper/hidden workflow to curate collections: review items one-by-one, keep the good stuff, hide the rest
5. **Organize** — Natural-language collection management ("move all kitchen items to a new collection")
6. **Share** — Export curated collections as shareable HTML with clickable source links back to Pinterest/Facebook

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

4. Start the app:
```sh
PYTHONPATH=src python3 -m inspirations serve --host 127.0.0.1 --port 8000
```
Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

For iPhone/iPad/LAN testing:
```sh
PYTHONPATH=src python3 -m inspirations serve --host 0.0.0.0 --port 8000
```

## App Workflows

### Collection Browsing
- Browse collections as tile grids showing pins, photos, PDFs, and Facebook saves
- Natural-language prompt to manage collections ("take all the things from this collection and put them into that collection")
- Filter by source, board, tags, and more

### Attractor Explorer
- Semantic visualization of your entire collection as a force-directed map
- Toggle attractor chips (Bathroom, Kitchen, Modern, Wood…) to pull matching items toward labeled poles
- **2D mode** — Canvas-based D3 force layout with scroll-zoom and CSS pre-zoom feedback
- **3D mode** — Three.js WebGL with OrbitControls, billboard thumbnails, and custom 3D force simulation
- Sliders for Strength, Spread, and Size; Focus mode filters non-matching items for cleaner clouds
- Sidebar tree stays visible for filtering; chips revealed on hover to reduce visual clutter

### Triage Review
- Select a collection and hit "Review" to enter triage mode
- For each item: **Keep** (love it), **Hide** (not relevant), or **Skip** (decide later)
- Optional "comment later" checkbox on keepers to mark items for annotation
- Keyboard-driven for speed (arrow keys or K/S/Z shortcuts)

### Annotation
- After triage, walk through items marked for annotation
- Add point-based notes directly on images
- Notes persist with the asset across collections

### Share Export
- Generate shareable HTML galleries from curated collections
- Clickable source links back to original Pinterest pins and Facebook posts
- Works as a standalone file — no server needed for viewing

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

The project is mid-rebuild. See `docs/SCRAPE_REBUILD_SPEC.md` for the full implementation plan.

## Future Work

- **Consuming UX** — Design the viewing experience for people receiving shared collections (the decorator/designer). How they browse, filter, and interact with curated sets. See `docs/TODO_CONSUMING_UX.md`.

## Docs

- `docs/SCRAPE_REBUILD_SPEC.md` — Current implementation spec
- `docs/TODO_CONSUMING_UX.md` — Future work: shared collection viewer experience
- `docs/archive/` — Historical documentation from the pre-rebuild system
- `CLAUDE.md` — AI assistant guidance for working in this repo
- `DECISIONS.md` — Architectural decision records
- `AGENTS.md` — Project-specific agent notes

## License

Proprietary.
