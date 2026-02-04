# Product Spec — Inspirations Library + Collections

## 1) Problem statement
You have thousands of inspiration images spread across Pinterest, Facebook saves, and physical magazine clippings. You need a single place to:
- See everything as “cards”
- Quickly find categories (e.g., “cabinets”, “backsplash”, “exterior”, “lighting”)
- Curate and share collections with a decorator
- Add precise, point-based annotations directly on an image

## 2) Target users & roles
- **Primary curator (your wife):** collects, searches, tags, curates, annotates, exports.
- **Co-curator (you):** handles imports, classification runs, storage/backup, sharing links.
- **Decorator/designer (external):** view-only access to selected collections; optionally comment later.

## 3) Core objects (data model)
**Asset**
- `id` (stable UUID)
- `source` (`pinterest` | `facebook` | `scan` | `upload` | `url`)
- `source_ref` (original URL or export identifier)
- `image_url` (canonical) + `thumb_url` (optional)
- `title`, `description` (optional)
- `created_at`, `imported_at`
- `tags[]` (human + AI)
- `ai` fields: `labels[]`, `confidence`, `model`, `run_id`, `embedding` (later)
- `notes` (freeform per-asset, optional)
- `annotations[]` (see below)
- `dedupe` fields: `sha256`, `phash` (optional)

**Annotation**
- `id`
- `asset_id`
- `x`, `y` in normalized coordinates (0..1) relative to the image
- `label` (auto-numbered per asset)
- `text` (note)
- `created_at`, `updated_at`

**Collection**
- `id`
- `name`, `description`
- `cover_asset_id` (optional)
- `item_ids[]` with per-collection ordering
- `created_at`, `updated_at`
- `shared` (visibility settings; later)

**Share**
- `id`
- `collection_id`
- `mode` (`link` | `zip` | `pdf`)
- `expires_at` (optional)
- `viewer_permissions` (`view` now; comment later)

## 4) Primary workflows
### 4.1 Ingest
1. **Import source exports** (Pinterest pins export, Facebook export) and **uploads/scans**.
2. Normalize into `Asset` records with consistent fields.
3. (Optional) Dedupe by URL + image hash.
4. Generate thumbnails for fast browsing.

### 4.2 Classify / tag
1. Select “Run AI on new items” (batch).
2. Produce:
   - Structured labels (e.g., `kitchen`, `cabinet`, `white oak`, `shaker`, `brass hardware`)
   - A short caption/summary (optional)
   - An embedding vector for semantic search (later)
3. Save AI results with provenance (`model`, `timestamp`, `prompt/version`).

### 4.3 Browse and search
Must support:
- Keyword search across title/notes/tags/AI labels
- Faceted filtering by tags + source
- Sorting (recent import, most annotated, etc.)
- Fast UI even at ~4,000–10,000 assets

Later:
- Natural-language retrieval (“show all pictures with white oak cabinets and brass pulls”)
- Similar-image search (“find images like this”)

### 4.4 Annotate
- Click on image to add a numbered marker
- Edit text per marker; drag to reposition
- Persist annotations with the asset (not with collection)

### 4.5 Curate collections
- Select assets → add to a collection
- Reorder items within a collection
- Add a collection description and cover image

### 4.6 Share
Minimum viable:
- Export a **shareable HTML gallery** (single file)
- Export a **ZIP** (gallery + data + optionally thumbnails) — later
- Export a **PDF** — later

Long-term:
- Share via a secure link with login (designer view).

## 5) UX requirements (non-negotiables)
- “Feels lightweight”: fast scrolling, instant filtering.
- Minimal steps to:
  - add an annotation
  - create and share a collection
- Works on laptop; iPad-friendly later is a plus.

## 6) Non-functional requirements
- **Privacy:** treat imports and scans as personal data; default private.
- **Data ownership:** easy export of raw assets + metadata JSON.
- **Performance:** handle 4k+ assets without freezing; use thumbnails.
- **Reliability:** storage backups; idempotent imports.
- **Cost controls:** AI runs should be batchable, resumable, and incremental.

## 7) Constraints & open questions
### Confirmed decisions (Feb 2026)
1. **Download and store images** (durable; enables export-by-zip later).
2. **Cloud AI is allowed** (Gemini/OpenAI/etc.).
3. **Share-by-export first** (HTML/ZIP/PDF later), not live designer login initially.

### Still open
1. New pins workflow: how often do you want to re-export Pinterest (daily/weekly/on-demand)?
2. Scan intake: do scans land as JPG/PNG, or do you primarily have PDFs that need page extraction?
3. Facebook update: are you expecting “new saves since last export”, or do you want a periodic re-export + idempotent import approach?
