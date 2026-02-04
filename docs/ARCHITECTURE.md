# Architecture Options (MVP → Web-ready)

This document proposes three viable architectures, from fastest local MVP to a production-grade web app.

## Option A — Local-first (fastest MVP, most private)
**Best when:** you want a working system quickly on one machine; you value privacy; you can tolerate “share via export”.

**Components**
- Local web UI (static app) or desktop wrapper (Tauri/Electron later)
- Local database: SQLite
- Local file store: a folder of **downloaded originals** + thumbnails
- Optional AI: cloud API calls from your machine (Gemini/etc.) or local vision model later

**Pros**
- Simple, low cost, private
- No auth, no hosting, no ops

**Cons**
- Harder to share “live”; exports are the sharing mechanism
- Multi-device sync is extra work later

## Option B — Web app on Vercel (professional, share-by-link)
**Best when:** you want designer login + shareable links + access from anywhere.

**Suggested stack**
- Frontend: Next.js (App Router) deployed on Vercel
- Auth: Auth.js or Clerk
- DB: Postgres (Neon/Supabase) with `pgvector` for semantic search
- Object storage: S3/R2 for images + thumbnails
- Background jobs: queue + worker (e.g., managed queue; or a separate worker service)
- AI classification: server-side calls to Gemini/OpenAI/etc.

**Key design choices**
- Store originals in object storage; generate thumbnails on upload/import.
- Run AI classification asynchronously; UI shows “processing” states.
- Persist embeddings in Postgres (`pgvector`) for natural-language and similarity search.

**Pros**
- Share-by-link with permissions
- Scales to many assets and collaborators

**Cons**
- More moving parts (auth, storage, queues)
- Higher cost and operational complexity

## Option C — Hybrid (local ingestion + cloud viewing)
**Best when:** you want privacy and easy ingestion locally, but also want a hosted portal.

**Flow**
1. Local “ingestion + dedupe + thumbnails” runs on your machine.
2. You publish selected assets/collections to the web portal.
3. The designer logs in to view curated collections only.

**Pros**
- Keeps raw imports private
- Cloud contains only what you intentionally share

**Cons**
- Two environments to maintain

## Canonical data flow (recommended for all options)
1. **Ingest** (Pinterest/Facebook/scans/uploads) → normalize to `Asset`.
2. **Dedupe** by URL + hashes (SHA-256 for exact; pHash for near-dup).
3. **Thumbnailing** for UI performance.
4. **AI pipeline** (batch, resumable):
   - Labels/tags
   - Caption/summary (optional)
   - Embedding vector (optional but recommended)
5. **Indexing**:
   - Keyword: title/notes/tags/labels
   - Semantic: embedding similarity

## Integration notes (imports)
Because exports vary and can be noisy:
- Design imports as **adapters** that produce a consistent `Asset` record.
- Keep the **raw source files** for audit/reprocessing.
- Make imports **idempotent** (re-import doesn’t duplicate).

## Share-by-export (confirmed MVP path)
For MVP, the sharing mechanism is a generated artifact:
- **HTML export** for quick review
- **ZIP export** (HTML + images + JSON) once originals are downloaded and stored
- **PDF export** later (optional)

## Security & privacy baseline (even for MVP)
- Default private, explicit sharing.
- Record AI provider + time + prompt version per run.
- Make it easy to delete assets and regenerate AI outputs.
