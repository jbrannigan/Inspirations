# inspirations — backend package

Loads when working under `src/inspirations/`. Project-wide invariants are in the
repo root `CLAUDE.md`.

## Module responsibilities

`cli.py` argparse entry point · `db.py` SQLite wrapper + **the migration system**
· `store.py` query builders · `storage.py` original downloads with SHA256 dedup ·
`security.py` safe-URL validation · `thumbnails.py` sips/magick/Pillow ·
`ai.py` Gemini tagging · `catalog.py` markdown catalog for Dave ·
`export.py` collection PDF (plus legacy HTML/portal) · `server.py` the HTTP
server · `devserver.py` reload wrapper · `importers/` one adapter per source.

## Data model

Core tables: `assets` (source, URLs, stored paths, SHA256, scraped metadata —
`seo_alt_text`, `post_text`, `hashtags`, `dominant_color` — plus `triage_status`
/ `triage_at`), `collections` + `collection_items`, `annotations`, `tray_items`,
`source_collections`, `triage_log`. AI tables: `asset_ai`, `asset_labels`,
`asset_ai_errors`, `ai_runs`. Full-text: `asset_search_fts` (FTS5 over title,
description, board, notes, AI summary, source text, labels).

## Classification — the trust hierarchy

This is the part that isn't derivable from the code, and getting it wrong
produces confidently wrong categorization. Highest to lowest authority:

1. **Source boards** (`assets.board`) — Leslie's own curation on Pinterest,
   Facebook, and Houzz. She saved each item to a board deliberately. **Board
   assignment always beats an AI tag on conflict.**
2. **Human triage decisions** — durable intent from Jim and Leslie in the app.
   Don't override casually.
3. **Collections** — a `CB:` prefix means AI-derived from high-confidence
   descriptions for creative-brief themes. Useful hypotheses, *not* human-curated
   selections. The old `pins:` source-board mirrors were retired; read live
   `assets.board` for source-board browsing.
4. **AI rooms/styles** (`asset_ai.json → rooms`, `styles`) — Gemini analysis.
   Enrichment, secondary to human curation.
5. **AI labels** (`asset_labels`) — flattened tags. Good for search and filter
   chips. Lowest authority for categorization.

**Why Leslie saved things — two motivations, and they look different.** Some
items are *stylistically attractive* (design inspiration). Others are *items of
practical concern* — construction choices, materials, maintenance problems. The
second kind is often not "pretty" and gets misfiled as noise by anything
optimizing for aesthetics. Both matter.

### Dimensions

| Dimension | Source of truth | Assignment |
|---|---|---|
| Source/Board | `assets.source` + `assets.board` | Sacred — Leslie's curation |
| Room | Board→room first, AI second | `BOARD_TO_ROOM` in `catalog.py`; AI rooms added via `AI_ROOM_MAP`. 17 canonical rooms. |
| Style | `asset_ai.json → styles` | Purely Gemini. 14+ styles. |
| Magazine | `asset_ai.json → text_in_image` | OCR keyword detection. Scan-only. 7 magazines. |
| Category | `assets.category` | `home_design` (~91%), `other`, `construction`, `diy`, `product_review` — separates design from exercise/food/personal |
| Content kind | `assets.content_kind` | `pin`, `reel`, `post`, `houzz_photo`, `scan`, `video` |

## AI pipeline

`ai tag --provider gemini [--source pinterest|facebook|houzz|scan]` sends the
thumbnail or original to Gemini 2.5 Flash and stores JSON with 11 categorical
buckets in `asset_ai`; `_flatten_ai_labels()` derives `asset_labels` rows from
the same response (source `ai`, confidence 0.7; `ai-video` at 0.8). Idempotent —
skips tagged items unless `--force`. Video (Facebook reels): `ai reels`.

## Catalog (`data/catalog/`)

Generated markdown that Dave (the chat AI) reads. `_index.md` is what Dave sees
in pass 1 to choose files. `_manifest.json` carries `id_map` (8-char prefix →
full UUID) to resolve Dave's picks back to real asset IDs. Per-line format:
`- {id8} | {description} | [{labels}]`, description falling through
title → ai_summary → seo_alt_text → board → "(untitled)".
Regenerate: `catalog generate`.

## Performance notes

- `/api/explorer/attractor-data` and `/api/explorer/layout` use an in-process
  cache keyed on endpoint params + SQLite mtime. `refresh=1` bypasses it.
- Dynamic JSON gzip is tuned for local/LAN latency, not maximum compression.
