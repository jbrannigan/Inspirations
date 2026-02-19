# Decisions

Permanent record of architectural and design decisions. Check here before
proposing something that may already be decided.

---

## D001 — Python stdlib only (2026-02-03)

**Decision:** No web framework. Use Python stdlib (`http.server`, `sqlite3`,
`json`, `pathlib`) for the entire backend.

**Why:** Minimal dependencies, fast startup, easy to understand. This is a
personal tool — no need for Flask/Django overhead.

**Consequence:** Custom routing in `server.py`, manual JSON serialization,
`unittest` instead of pytest.

---

## D002 — SQLite for storage (2026-02-03)

**Decision:** Single SQLite file at `data/inspirations.sqlite`.

**Why:** Zero-config, portable, sufficient for ~4k assets. Backups are just
file copies.

**Consequence:** No concurrent write scaling. Batch operations need careful
transaction handling to avoid lock contention.

---

## D003 — Local-only deployment (2026-02-03)

**Decision:** Serve on localhost only. No cloud deployment planned.

**Why:** Personal tool running on Mac Mini. Assets are local files, not
suitable for cloud hosting without a storage migration.

**Port:** 8001 (registered in STANDARDS.md port allocation table).

---

## D004 — Vanilla JS frontend (2026-02-03)

**Decision:** No React/Vue/Svelte. Plain HTML + vanilla JavaScript in `app/`.

**Why:** Keeps the stack simple. Single `app.js` file. No build step, no
bundler, no node_modules.

**Consequence:** Manual DOM manipulation, no component model, CSS in a
single `styles.css`.

---

## D005 — Gemini for AI tagging (2026-02-05)

**Decision:** Use Google Gemini (gemini-2.5-flash primary, gemini-2.0-flash
fallback) for image tagging.

**Why:** Good vision quality, Batch API support for bulk processing (~50%
cost reduction), generous rate limits.

**Consequence:** Requires `GEMINI_API_KEY` in environment. Batch API has 24h
SLO. RECITATION responses need automatic fallback to alternate model.

---

## D006 — Thumbnails for AI input (2026-02-05)

**Decision:** Send thumbnail images (not originals) to Gemini for tagging.

**Why:** Faster, cheaper, sufficient quality for tag extraction. Originals
are 2-10x larger with no meaningful quality gain for labeling.

---

## D007 — Batch API for bulk tagging (2026-02-05)

**Decision:** Use Gemini Batch API for initial bulk tagging (>500 assets),
interactive mode for small batches and retries.

**Why:** Batch API is ~50% cheaper and avoids rate limit pressure. Interactive
is better for immediate feedback and retry workflows.

**Tooling:** `tools/tagging_batch.py` (batch), `tools/tagging_runner.py`
(interactive), `tools/tagging_pipeline.py` (auto-chooses).

---

## D008 — Provider-level deduplication (2026-02-05)

**Decision:** Skip already-tagged assets at the provider level (any model),
not just model-specific.

**Why:** Prevents re-tagging assets that were successfully handled by a
fallback model. The 7 RECITATION fallback assets tagged by gemini-2.0-flash
should not be re-attempted by gemini-2.5-flash.

---

## D009 — Gemini text-embedding-001 for embeddings (2026-02-08)

**Decision:** Use Gemini's text-embedding-001 model for asset embeddings,
stored in `asset_embeddings` table.

**Why:** Same API ecosystem as tagging. Enables cosine similarity search
without adding a vector database.

**Consequence:** Embeddings stored as JSON arrays in SQLite. Similarity
computation is in-process Python (numpy-free, pure math). Scales to ~4k
assets comfortably.

---

## D010 — scikit-learn in isolated venv for clustering (2026-02-13)

**Decision:** Use scikit-learn for KMeans/silhouette clustering, installed in
a temporary isolated venv (`/private/tmp/inspirations-cluster-venv`).

**Why:** Keeps the main project dependency-free. Clustering is a batch
offline operation, not a runtime dependency.

---

## D011 — Cluster Explorer as standalone HTML tool (2026-02-13)

**Decision:** Cluster Explorer is a separate HTML page (`tools/cluster_explorer.html`)
served by a dedicated server (`tools/serve_explorer.py`), not integrated
into the main app.

**Why:** Different use case (spatial graph exploration vs grid curation).
Keeps the main app simple. Explorer reads a static JSON snapshot, not
the live database.

**Spec:** `docs/CLUSTER_EXPLORER_SPEC-v2.md`

---

## D012 — Accessibility Tier C (2026-02-18)

**Decision:** Inspirations is Tier C (Personal) per STANDARDS.md accessibility
tiers.

**Why:** Solo use only — Jim on Mac Mini and iPad. No external users planned.

---

## D013 — Session-only delete in Explorer (2026-02-14)

**Decision:** Cluster Explorer duplicate-review operates in session-only mode
by default (hides items in UI, no DB writes). API-backed removal requires
explicit `api_base` parameter.

**Why:** Safe default for review workflows. Prevents accidental data loss
during exploratory duplicate identification.
