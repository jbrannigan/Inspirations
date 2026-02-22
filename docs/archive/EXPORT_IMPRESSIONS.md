# Export Impressions (Feb 2026)

## Pinterest crawler ZIP
File: `dataset_pinterest-crawler_2026-01-30_02-07-52-338.zip`

**What’s inside**
- One dataset represented in four formats: `.json`, `.csv`, `.html`, `.xlsx`.
- The JSON is a top-level list with **3,661** records (pins).

**Useful fields observed (JSON)**
- `id` (pin id)
- `seo_url` (e.g. `/pin/<id>/`) — can be normalized to `https://www.pinterest.com/pin/<id>/`
- `image.url` — direct image URL (often `i.pinimg.com/.../originals/...jpg`)
- `board` (string or object) — board/category
- `title` / `grid_title` / `seo_title` / `auto_alt_text` (varies)
- `created_at` (string timestamp)

**Recommendation**
- Treat the ZIP as “multi-format mirror”; **use JSON as source of truth**.
- Import should be **idempotent** using `(source='pinterest', source_ref=pin_url)` so you can re-run after future exports and only new pins are added.

## Facebook saved items ZIP
File: `facebook-lesliebrannigan-2026-01-30-RCSuQaKZ.zip`

**What’s inside**
- `your_saved_items.json` with key `saves_v2` (observed **8,535** items)
- `collections.json` with key `collections_v2` (observed **93** collections)

**Gotcha**
- Many saves contain only an `external_context.name` (a domain or place name) and **no retrievable media URL**.
- A subset contain a usable URL at:
  - `attachments[0].data[0].external_context.source` (often a direct image URL)

**Recommendation**
- Import Facebook saves as “best-effort”:
  - ingest only entries with a usable `external_context.source`
  - log/skip the rest
- Treat Facebook as a secondary signal until we add a more robust update workflow.

