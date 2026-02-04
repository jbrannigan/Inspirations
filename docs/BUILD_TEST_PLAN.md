# Design / Build / Test Plan

## Phase 0 — Mockup (now)
**Goal:** confirm UX before committing to a stack.
- Card grid browse + search + filter
- Collections panel
- Image annotation (click to add marker; edit text; drag marker)
- Export: basic HTML/JSON (ZIP/PDF later)

Deliverable: `mockup/index.html` (no dependencies).

## Phase 1 — Local MVP (2–4 weeks)
**Goal:** real data ingestion + durable storage on one machine.

**Build**
- Local UI (could start as a small local web app)
- SQLite schema for Assets/Annotations/Collections
- File store layout:
  - `store/originals/<asset_id>.*`
  - `store/thumbs/<asset_id>.jpg`
- Import adapters:
  - Pinterest export adapter (pins → assets; idempotent re-import to pick up new pins)
  - Facebook export adapter (best-effort; only ingest entries with retrievable media URLs)
  - Scan intake adapter (folder-based “inbox” workflow; idempotent by hash)
- Dedupe: URL + exact hash; near-dup later
- Basic export: HTML gallery + JSON metadata

**Test**
- Unit tests for each import adapter (fixtures)
- Idempotency test: run import twice → same counts
- UI smoke tests for annotation persistence
- Performance test: load 5,000 assets with thumbs

## Phase 2 — AI tagging + semantic search (2–6 weeks)
**Goal:** “type cabinets” and get the right set, even when not manually tagged.

**Build**
- Background “AI run” job:
  - batch size controls, retries, resumable checkpoints
  - store structured labels and confidence
  - generate embeddings (if using semantic search)
- Search:
  - keyword (fast baseline)
  - semantic (embedding similarity) with fallbacks

**Test**
- Golden tests for AI parsing (validate JSON structure, not content)
- Rate-limit/backoff tests (mocked)
- Re-run tests: new model version doesn’t break old data

## Phase 3 — Web portal (optional)
**Goal:** designer login + share-by-link.

**Build**
- Hosted Next.js UI
- Auth + permissions
- Hosted storage for images/thumbnails
- Shared collection links with viewer access
- Optional commenting

**Test**
- E2E flows: login → view collection → download export
- Security checks: access control enforced server-side

## Definition of done (MVP)
- Imports real Pinterest pins and produces browsable cards
- Annotations persist reliably
- Collections can be created/edited
- Export creates a shareable artifact without manual steps

## Operational checklist (MVP)
- Keep raw exports and scans under `imports/` (gitignored) for reproducibility.
- Keep downloaded images under `store/` (gitignored) with backup to external drive/cloud.
- Prefer “re-export + idempotent import” for Pinterest/Facebook to capture updates without fragile scraping.
