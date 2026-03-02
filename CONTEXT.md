# Inspirations — Context Preservation Document
## Last updated: 2026-03-01

---

## Quick Start

```bash
cd /Users/minime/Projects/Inspirations
PYTHONPATH=src python3 -m inspirations serve --port 8001 --reload
```

### Magic Links (current actors — verified 2026-02-23)
- **Leslie (owner):** http://localhost:8001/?actor=XrwPmWFGtESoUGjvUiCJPw
- **Jim (owner):** http://localhost:8001/?actor=t8-kNrGYcdQSCRPGbxDVSA
- **Mark (collaborator):** http://localhost:8001/?actor=XqzueF-yfsLUiEmlGbWyPg

> **Note:** Tokens are regenerated if the actors table is recreated. Always verify with:
> `PYTHONPATH=src python3 -c "from inspirations.db import Db, ensure_schema; db=Db('data/inspirations.sqlite'); ensure_schema(db); [print(f\"{r['name']} ({r['role']}): http://localhost:8001/?actor={r['token']}\") for r in db.query('select name, token, role from actors')]"`

### Tests
```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v  # 153 tests
```

---

## Architecture Summary

- **Backend:** Python stdlib only (no Flask/Django), SQLite, raw SQL
- **Frontend:** Vanilla JS SPA, no build step, Three.js for 3D explorer
- **AI:** Gemini for image tagging/video analysis/embeddings, Claude Sonnet for chat routing
- **Auth:** Magic link tokens → `X-Actor-Token` header, two roles (owner/collaborator)
- **Port:** 8001, local-only (D003)
- **DB:** `data/inspirations.sqlite`, **6,295 assets** (Pinterest, Facebook, scans)

---

## Key UX Features Implemented This Session

### 1. Keeper Badge Iconography
- Gold star ★ badge replaces small green dot on keeper cards
- Keepers sort to top of grid via SQL: `case when a.triage_status = 'keeper' then 0 else 1 end asc`
- Keeper star shows in modal header (`#modalKeeperStar`)
- Keeper star prefix on review card titles

### 2. Flag-for-Review Feature
- 🚩 flag button in modal — any actor can flag items (wrong thumbnail, needs attention)
- DB columns: `flagged`, `flagged_by`, `flagged_note` on assets table
- API: `POST /api/assets/{id}/flag` (single), `POST /api/assets/flag/bulk` (bulk)
- Sidebar "Flagged" chip appears when flagged items exist (`#flaggedChip`)
- Chat: `bulk_flag` action added to ALLOWED_ACTIONS

### 3. Canvas Review Mode (multi-select grid)
- **Default review mode** — click Review → grid gets checkbox overlays on cards
- Action bar appears in header: Keep / Hide / Flag / Clear / One-by-one / Exit Review
- Click cards to select (gold outline), Ctrl+A selects all
- Bulk actions call `/api/assets/triage/bulk` and `/api/assets/flag/bulk`
- Chat ("Ask Dave") is selection-aware: "keep these" operates on selected items
- State: `canvasReview: false, canvasSelected: new Set()`
- CSS class `canvas-review-active` on `#browseView` shows checkboxes without re-render
- Grid view toggle button pulses gold when canvas review is active

### 4. One-by-One ↔ Grid Flow
- One-by-one button switches to existing card-by-card triage
- Back button says "← Back to grid" and returns to canvas review (not exit)
- Grid button highlighted with gold pulse animation when reviewing

### 5. Logo: "Yellow Under Black" Edison Bulb
- 7 major vector rays + 6 accent rays: fat yellow line + thin dark line on top
- Yellow glow shape behind white glass bulb with dark stroke
- Edison screw base with ridge lines, zigzag filament between support wires
- CSS warm backdrop: `background: var(--accent-soft)` on `.logo-svg`
- "Inspirations!" word logo with yellow text-shadow glow
- Evolution page: `/app/logo-preview.html` shows all 7 design iterations

### 6. Action Bar Position
- Canvas review action bar is inside `<header>` element (sticky)
- Full-width row that appears below the topbar, scrolls with header (stays fixed)

### 7. Admin Page Cleanup
- Added proper padding, card styling, nav button styling
- `.adminShell`, `.section`, `.adminNav`, `.subtitle` CSS classes

### 8. Tag System (Jim's Anomaly Markers) — Separate from Flag
Two separate systems:
- **Flag** (Leslie) — "Come back to this to add comments." Owner-only 🚩 badge + sidebar chip + modal button.
- **Tag** (Jim) — "This tile has an anomaly (bad thumbnail, miscategorized)." 🏷️ badge + hover button on cards.

**Tag workflow:**
- Hover card → 🏷️ button at bottom-right → click to tag → 🏷️ badge appears
- DB: `tagged`, `tagged_by`, `tagged_note` columns on assets (separate from `flagged`)
- API: `POST /api/assets/{id}/tag`, `POST /api/assets/tag/bulk`, `GET /api/assets?tagged=1`
- Tag button stays visible during canvas review (Jim tags while reviewing)
- Tagged items are later reviewed interactively in Claude Code sessions
- CSS: `.card-quick-tag` (blue theme), `.triage-badge.tagged` (blue badge with white border)

---

## 4-Phase Collaboration System (from prior session)

### Phase 1: Actors & Auth
- `actors` table with magic link tokens
- `_seed_default_actors()` creates Jim + Leslie on empty DB
- `_resolve_actor()` checks header then URL param
- Role-based UI via `applyRoleVisibility()`

### Phase 2: Annotations
- Pin-drop notes and questions on images (normalized x,y coordinates)
- `annotations` table with `annotation_type` ('note'|'question'), `resolved` flag
- Question dashboard for owners (`/api/questions/dashboard`)
- Visual markers on images with click-to-edit

### Phase 3: Triage Workflow
- Three states: pending (null), keeper, hidden
- Single-item: modal buttons, review card arrows
- Bulk: canvas review with multi-select, chat-driven ("keep these")
- Stats: `/api/triage/stats` with per-board progress

### Phase 4: Collections & Chat
- Natural-language collection management via Claude chat
- Two-pass routing: index → catalog files → item IDs
- Tray system for staging items before creating collections
- Chat actions: filter, search, semantic_search, create/show collection, bulk_triage, etc.

---

## Deployment Aspirations — Moving to Fly.io or Similar

**Current state:** Local-only (D003). No Dockerfile, no fly.toml, no Procfile.

**What's needed to go public:**
1. **Dockerfile** — Python 3.11+, copy src/ + app/ + tools/, PYTHONPATH=src
2. **fly.toml** — Single machine, persistent volume for SQLite + store/
3. **Auth hardening** — Magic links work but need HTTPS + secure cookies for public
4. **Static assets** — Consider CDN for images, or serve from Fly volume
5. **Environment variables** — API keys (Gemini, Claude/Anthropic) need secrets management
6. **Data migration** — Copy SQLite DB + store/ directory to persistent volume
7. **CORS/security** — Currently wide open for localhost; need proper headers
8. **Media storage** — 6,295 assets with originals + thumbs could be large; may need S3/R2

**Key decision:** D003 says local-only, but the UX is getting mature enough to share. The consuming UX for shared collections (OQ001 in OPEN-QUESTIONS.md) is a prerequisite for public deployment.

---

## File Map

### Source (`src/inspirations/`)
| File | Purpose |
|------|---------|
| `server.py` | HTTP server, all API endpoints |
| `store.py` | All SQL query builders |
| `db.py` | SQLite wrapper, schema, migrations |
| `chat.py` | Two-pass Claude chat routing |
| `ai.py` | Gemini AI pipeline (tagging, embeddings, search) |
| `catalog.py` | Markdown catalog generator for chat |
| `cli.py` | CLI entry point with subcommands |
| `security.py` | SSRF protection for URL downloads |
| `storage.py` | Image download + SHA256 dedup |
| `thumbnails.py` | Thumbnail generation (sips/magick/Pillow) |
| `export.py` | HTML gallery + static portal export |
| `explorer_layout.py` | UMAP layout for 3D explorer |
| `devserver.py` | File-watching auto-reload |

### Frontend (`app/`)
| File | Purpose |
|------|---------|
| `index.html` | Main SPA shell |
| `app.js` | Main app logic (~2728 lines) |
| `shared.js` | API helper, toast, escapeHtml |
| `explorer.js` | Three.js 3D cluster explorer |
| `styles.css` | All styles (~1507 lines) |
| `admin.html` | Admin panel |
| `admin.js` | Admin logic |
| `logo-preview.html` | Logo evolution showcase |

### Importers (`src/inspirations/importers/`)
| File | Purpose |
|------|---------|
| `scans.py` | Local scan/PDF importer |
| `pinterest_scrape.py` | Pinterest JSON scrape importer |
| `facebook_scrape.py` | Facebook JSON scrape importer |
| `houzz.py` | Houzz ideabook importer (legacy) |

### Tests (`tests/`) — 153 tests, all passing
20 test files covering server API, store, chat, AI, importers, export, security, triage.

---

## CSS Design System

```css
--bg: #faf8f5;           /* Page background */
--panel: #ffffff;         /* Card/panel background */
--text: #2c2825;          /* Primary text */
--text-secondary: #6b6560;
--accent: #b8860b;        /* Gold accent (user notes: reads muddy on calibrated monitors) */
--accent-soft: rgba(184, 134, 11, 0.12);  /* Warm gold tint */
--keep-green: #22c55e;
--hide-red: #ef4444;
```

Logo line art uses `#44403c` (dark charcoal) and `#fde047` (bright yellow).
Title text: `color: #44403c; text-shadow: 0 0 6px rgba(253, 224, 71, 0.6), 0 0 12px rgba(253, 224, 71, 0.3);`

---

## Ingestion Pipeline Techniques (by source)

### Pinterest (scrape)
- **Import:** `import_pinterest_scrape()` reads browser scrape JSON (`pinterest_scrape.json`)
- **Media:** Downloads pin images via URL, stores in `store/originals/pinterest/`, generates thumbnails
- **Metadata:** Title, description, board, image URL from scrape data
- **AI:** Gemini image labeling — sends thumbnail to Gemini, gets structured JSON (rooms, materials, styles, etc.)
- **Importer:** `src/inspirations/importers/pinterest_scrape.py`

### Facebook Posts (scrape)
- **Import:** `import_facebook_scrape()` reads browser scrape JSON files (`facebook_scrape_*.json`)
- **Media:** Downloads post images via URL, stores in `store/originals/facebook/`
- **Metadata:** Post text, hashtags, engagement data, content_kind (post/reel/video)
- **AI:** Gemini image labeling on thumbnails (same as Pinterest)
- **Importer:** `src/inspirations/importers/facebook_scrape.py`

### Facebook Reels (yt-dlp + Gemini video)
- **Problem:** Reel thumbnails are often misleading — one frame doesn't represent video content. Thumbnail-based AI labels are unreliable for reels.
- **Download:** `yt-dlp` subprocess downloads MP4 from `source_ref` URL (e.g., `https://www.facebook.com/reel/123/`)
  - Stores at `store/reels/facebook/{asset_id}.mp4` + `.info.json`
  - Extracts metadata: title, description, uploader, duration from info.json
  - Flags: `--write-info-json --no-playlist --max-filesize 50m`
- **AI:** Gemini 2.5 Flash **native video analysis** — sends full MP4 (inline base64 if < 20MB, File API if ≥ 20MB)
  - Prompt: "Is this video relevant to home design?" → structured JSON with category, recommendation, suggested title/board
  - Results stored in `asset_ai` with `provider='gemini-video'` (distinct from `provider='gemini'` image labels)
  - Labels stored in `asset_labels` with `source='ai-video'`
  - Replaces unreliable thumbnail-based labels (`source='ai'`)
- **Apply:** `apply_reel_recommendations()` — hides irrelevant reels, retitles/recategorizes relevant ones, skips tagged items
- **Cost:** ~$0.003/reel × 951 reels ≈ $3 total
- **CLI:** `inspirations ai reels [--download-only] [--analyze-only] [--apply-only] [--limit N] [--force]`
- **Functions:** `download_facebook_reels()`, `run_gemini_video_labeler()`, `apply_reel_recommendations()` in `ai.py`

### Houzz (scrape)
- **Import:** `import_houzz_ideabook()` reads scraped ideabook JSON
- **Media:** Downloads images from Houzz CDN
- **Metadata:** Title, description from ideabook entries
- **Importer:** `src/inspirations/importers/houzz.py`

### Scans (PDF import + Gemini image)
- **Import:** `import_scans_inbox()` reads PDF/image files from inbox folder
- **Media:** Renders PDF pages to JPG/PNG via pdftoppm or mutool, stores as individual page assets
- **Scan grouping:** Multi-page docs collapsed into document groups (`_collapse_scan_rows()`)
- **AI:** Gemini image labeling on each page, with smart title suggestion (`_suggest_scan_title()`)
- **Importer:** `src/inspirations/importers/scans.py`

---

## Known Issues / Open Items

1. **`--accent: #b8860b` muddiness** — User noted gold reads muddy on calibrated monitors. May need broader accent color refresh.
2. **OQ001: Consuming UX** — How should shared collections look to recipients? (Prerequisite for public deployment.)
3. **No catalog generated** — Chat routing works in routing-only mode. Run `inspirations catalog generate` to enable full two-pass chat.
4. **Jim's review mode NOT SHOWING — ROOT CAUSE FOUND** — Tokens were regenerated when actors table was recreated. Old tokens from the session summary were stale. **Fix:** Use the correct magic link URLs listed above. Also clear browser localStorage (`localStorage.removeItem("actorToken")`) to flush any cached stale token, then re-visit the correct magic link.
5. **3D Explorer view may not load** — User reports graph button (next to grid button) doesn't work properly. The HTML (`#explorerView`), JS (`explorer.js` with Three.js dynamic import), and API (`/api/explorer/layout`) are all wired up. Possible causes: (a) Three.js CDN import failing, (b) no embeddings in DB (need `inspirations ai embed` first), (c) `compute_layout` error. **Debug steps:** Check browser console, verify `asset_embeddings` table has data, test `/api/explorer/layout` directly.
6. **Deployment to Fly.io** — See "Deployment Aspirations" section above. No deployment files exist yet. Key blocker: D003 says local-only, but UX is maturing. Need Dockerfile, fly.toml, secrets management, auth hardening for public access.
