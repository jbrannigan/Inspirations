# Session Log

Dated entries for every work session. Read this first when resuming.

> See also: `docs/handoff.md` for detailed timestamped execution history from
> the Codex collaboration era (Feb 3–15 2026).

---

## 2026-02-18 — Standards alignment

- Created CHANGELOG.md, SESSION-LOG.md, DECISIONS.md, OPEN-QUESTIONS.md per
  cross-project STANDARDS.md audit
- Project now follows shared standards at `/Users/minime/Projects/STANDARDS.md`

---

## 2026-02-15 — UX simplification pass (Codex)

- Branch: `codex/ux-simplification-pass`
- Added Show All reset, AI tag Any/All toggle, primary add-to-active-collection
- Inspect modal Hide/Print actions, hidden collection exclusion
- Cluster Explorer: graph thumbnails, 3-lane keeper/candidate/loser duplicate review
- Photo upload path added (app/server/importer)
- Safe `/store` route for local media fallbacks
- 30 dirty files at session end — not yet committed to main

## 2026-02-14 — Cluster Explorer Phase 1 + duplicate review

- Completed Cluster Explorer Phase 1 from CLUSTER_EXPLORER_SPEC-v2
- Rewrote `export_clusters.py` to v2 contract (outlier metrics, collection scoping)
- New `serve_explorer.py` with allowlisted routes and cache policy
- Rewrote `cluster_explorer.html` — Discover/Outliers modes, detail panel, search
- Duplicate-review workflow: grouped sets, keeper/loser, queue/apply
- Collection-scoped exports with focus vs nearby context
- Tests: `test_export_clusters.py`, `test_serve_explorer.py` — all passing
- Real-data validation: 3661 nodes, 7 clusters, served on port 8081
- Docs consistency pass across README, STATUS, spec files

## 2026-02-08 — Error triage, embeddings, semantic search, UI polish

- PRs #5–#16 merged to main
- AI error triage CLI (`inspirations ai errors`) with actionable classification
- Embeddings table + CLI (`inspirations ai embed`)
- Semantic search API (`/api/search/similar`) and app `sem:` query mode
- Hybrid ranking controls for semantic relevance tuning
- Session checkpoint tooling (`session_checkpoint.py`, post-merge git hook)
- Future options roadmap doc
- UI fixes: card expansion, link previews, smart thumb fit, SVG fallback
- Scan intake and recipe PWA split roadmap added
- CI dependency bumps (actions/checkout v6, actions/setup-python v6)
- 38 tests passing, lint clean

## 2026-02-07 — Repo hardening, CI, admin workflow, recitation fallback

- PRs #1–#4 merged
- Hardened repo policy, CI ruff gate, server safety controls
- Admin curation workflow (login + asset delete with backup)
- Automatic Gemini RECITATION fallback (2.5-flash → 2.0-flash)
- Provider-level skip logic to avoid re-tagging
- Agent docs and status runbooks refreshed
- README fully rewritten
- 30 tests passing

## 2026-02-05 — Gemini tagging complete, Batch API, UI integration

- Full Gemini tagging pipeline: interactive → Batch API → ingest
- Pinterest tagging complete: 3661/3661 (3654 flash, 7 fallback)
- BMP/WebP image support added, all missing media resolved
- Tagging pipeline preflight + auto mode (`tagging_pipeline.py`)
- UI integrated: compact cards with AI summary, expand for full tags
- Session sync tool, fast path checklist
- Collection tray workflow, annotation system

## 2026-02-03–04 — Project scaffolding and core features

- Initial scaffold: Python stdlib + SQLite architecture
- Pinterest and Facebook HTML import parsers
- Thumbnail generation pipeline
- Web app: grid UI, faceted filters, multi-select, collection management
- Curate tray workflow
- Annotation system (movable markers, notes, badges)
- Badge color standard documented
- Local media serving
