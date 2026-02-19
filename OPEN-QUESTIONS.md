# Open Questions

Unresolved questions and decisions that need input. Check here before starting
new work — your question might already be captured.

---

## OQ001 — Recipe split: when and how?

**Context:** `docs/next_steps.md` section 7 outlines a scanned-recipe intake
flow and a future split where Inspirations excludes recipes by default, with a
separate iPad-first recipe UX.

**Questions:**
- When should the recipe split happen (after v0.2.0 or later)?
- Should recipes be a separate SQLite database or a filtered view of the same DB?
- Does the recipe UX need OCR-backed text search from day one?

---

## OQ002 — API response envelope alignment

**Context:** STANDARDS.md defines an API envelope `{ data, meta?, error? }`.
Current Inspirations endpoints return flat arrays or ad-hoc shapes.

**Questions:**
- Should existing endpoints be migrated to the standard envelope?
- Is this worth the breaking change for a personal-use app?
- If yes, do it all at once or incrementally?

---

## OQ003 — Structured logging adoption

**Context:** STANDARDS.md requires Python `logging` module with structured
output. Current code uses `print()` statements throughout.

**Questions:**
- Migrate all at once or file-by-file as code is touched?
- Log to file, stdout, or both?
- Is JSON-structured logging worth it for a personal tool?

---

## OQ004 — Facebook asset import quality

**Context:** 74 Facebook assets imported. HTML parsing extracts previews but
quality varies. Some cards show as link-only without useful thumbnails.

**Question:** Is it worth investing in better Facebook import, or are Pinterest
assets the primary focus going forward?

---

## OQ005 — Advanced curation mode (lasso/tray)

**Context:** CLUSTER_EXPLORER_SPEC-v2 describes a future "curate mode" with
lasso selection and batch tray operations in the explorer. Not yet implemented.

**Question:** Is this needed, or does the current keeper/loser workflow in
duplicate-review mode cover the use case?

---

## OQ006 — Synology NAS backup for SQLite

**Context:** STANDARDS.md Backup & Recovery section specifies rsync to Synology
NAS for database files. Not yet configured for Inspirations.

**Question:** Set up rsync cron job now, or wait until other projects are
configured too?

---

## ~~OQ-RESOLVED: Batch vs interactive tagging~~ ✅

Resolved in D007. Batch API for bulk (>500), interactive for retries.

## ~~OQ-RESOLVED: Embedding model choice~~ ✅

Resolved in D009. Gemini text-embedding-001.

## ~~OQ-RESOLVED: Cluster Explorer architecture~~ ✅

Resolved in D011. Standalone HTML tool with dedicated server.
