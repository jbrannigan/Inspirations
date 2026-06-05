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

**Why:** Zero-config, portable, sufficient for ~5k assets. Backups are just
file copies.

**Consequence:** No concurrent write scaling. Batch operations need careful
transaction handling to avoid lock contention.

---

## D003 — Local-first deployment with optional LAN access (2026-02-03, revised 2026-06-03)

**Decision:** Inspirations remains a local-first Mac mini app. Bind to
`127.0.0.1` for shell-only development when LAN access is unnecessary, and bind
to `0.0.0.0:8001` for iPad/iPhone/LAN use. The preferred persistent local/LAN
runtime is the logged-user launchd service documented in
`docs/INSPIRATIONS_SERVICE_RUNBOOK.md`.

**Why:** Personal tool running on Mac Mini. Assets are local files, not
suitable for cloud hosting without a storage migration. LAN visibility is
useful for device testing without changing the local-first product model.

**Port:** 8001 (registered in STANDARDS.md port allocation table).

**Consequence:** DevLauncher is not the uptime mechanism. If public access is
ever revived, use launchd plus the shared Cloudflare tunnel rather than relying
on a developer shell or DevLauncher process.

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

---

## D008 — Provider-level deduplication (2026-02-05)

**Decision:** Skip already-tagged assets at the provider level (any model),
not just model-specific.

**Why:** Prevents re-tagging assets that were successfully handled by a
fallback model.

---

## D009 — Gemini text-embedding-001 for embeddings (2026-02-08)

**Decision:** Use Gemini's text-embedding-001 model for asset embeddings,
stored in `asset_embeddings` table.

**Why:** Same API ecosystem as tagging. Enables cosine similarity search
without adding a vector database.

**Consequence:** Embeddings stored as JSON arrays in SQLite. Similarity
computation is in-process Python (numpy-free, pure math).

---

## D014 — Scrape-first rebuild (2026-02-22)

**Decision:** Nuke the database and rebuild from browser-scraped data instead
of continuing with ZIP-export-based imports.

**Why:** Browser scraping captures much richer metadata (post text, hashtags,
creator names, engagement data, high-res images for Facebook) than the
pre-exported ZIP files. Pinterest images are already stored locally and will
be matched via an image map. Facebook images will be re-captured at full
resolution during scraping.

**Consequence:** Old importers (`pinterest_crawler.py`, `facebook_saved.py`)
are deleted. New importers (`pinterest_scrape.py`, `facebook_scrape.py`)
consume JSON produced by browser scraping. The `rebuild-db` command
orchestrates a clean reimport. Old documentation archived to `docs/archive/`.

**Spec:** `docs/SCRAPE_REBUILD_SPEC.md`

---

## D015 — Triage-first curation workflow (2026-02-22)

**Status:** Superseded by D023 for the everyday UX. The triage schema, audit
history, and focused review tools remain useful.

**Decision:** The primary curation UX is a keeper/hidden triage workflow,
not the previous filter-and-collect approach.

**Why:** With ~5,000 items from multiple sources, the user needs to quickly
separate "house stuff" from everything else. A card-by-card review with
keyboard shortcuts (keep/hide/skip) is faster than manual collection building.

**Consequence:** New `triage_status` column on assets (null=pending, 'keeper',
'hidden'). Triage dashboard shows stats. Review mode walks through items one
at a time. Collections are managed via natural-language prompts rather than
complex UI.

---

## D016 — Natural-language collection management (2026-02-22)

**Decision:** Use a chat-style prompt in the app for collection operations
instead of building complex collection UI widgets.

**Why:** "Move all kitchen items to a new collection" is faster than
select-all + drag + create-collection UI flows. Reduces frontend complexity
and makes the app feel friendly rather than techy.

**Consequence:** Backend needs a flexible collection-operations API. Frontend
needs a text input that sends natural-language requests to the backend (or
processes them client-side with simple pattern matching).

---

## D017 — Attractor Explorer as in-app view mode (2026-02-26)

**Status:** Partially superseded by D019 and D023. Explorer remains an in-app
view mode, but current controls and scope semantics are defined by those later
decisions.

**Decision:** The attractor explorer (2D and 3D) is an in-app view mode,
toggled via toolbar buttons (Grid / Explorer) with 3D as a checkbox inside
the explorer control panel alongside Focus and Live.

**Why:** Keeps the explorer tightly integrated with the sidebar tree and
existing filter state. Sidebar clicks auto-filter the explorer via
`syncExplorerFilter()`. The 3D toggle is a visualization option (like Focus
or Live), not a separate view — so it belongs in the control panel, not the
toolbar.

**Consequence:** Both 2D (`attractor-explorer.js`) and 3D
(`attractor-explorer-3d.js`) share the same public API shape and
`on3DToggle(callback)` interface. `app.js` wires the callback to
`switchExplorerMode()`. Explorer layout keeps the two-column grid
(sidebar + content) rather than going full-width.

---

## D018 — CSS pre-zoom for 2D scroll feedback (2026-02-26)

**Decision:** Apply an instant CSS `transform` on the canvas during D3 zoom
events, then clear it when `_render()` completes the real canvas repaint.

**Why:** Canvas repaints for 4,600+ nodes take multiple frames. Without
pre-zoom, scroll-zoom feels unresponsive — the user can't tell if their
input was received. The CSS transform gives immediate (blurry) visual
feedback while the crisp repaint catches up, matching the pattern used by
Leaflet and Google Maps.

**Consequence:** `_lastRenderedTransform` tracks the transform at last
repaint. Zoom handler computes the delta and applies it as CSS
`translate() + scale()`. `_render()` clears `canvas.style.transform` and
updates the tracking state.

---

## D019 — Explorer scope, grouping, and iPad fallback semantics (2026-05-25)

**Decision:** Sidebar filters and text search define the base Explorer item
scope. Category chips then have an explicit `Filter / Group` mode: `Filter`
reduces the visible item set, while `Group` arranges the current scope around
selected category poles. In 3D Explorer, `Group by` is an automatic grouping
shortcut and does not change global filters or sidebar state. On
iPad/mobile-constrained layouts, 2D is a lite fallback for broad sets, while
filtered subsets can switch back to 3D when a measured per-session WebGL budget
says the subset is small enough.

**Why:** The previous category-pill surface was ambiguous: users could not tell
whether pills were filtering the collection or grouping visible nodes. iPad
Safari also showed instability on broad 3D sets, but a static node cutoff was
too opaque and device-dependent.

**Consequence:** 3D Explorer shows a `Categories` drawer, a `Filter / Group`
switch, and visible grouping chips for active grouping poles. iPad mode labels
broad sets as `iPad lite: 2D map`; 3D is restored for filtered subsets within
the measured device budget.

---

## D020 — Sidebar Refine By facets are stackable scope refinements (2026-05-26)

**Decision:** Sidebar classification/style/material/color choices are
stackable `Refine By` facets rather than exclusive browse scopes. Source,
collection, and board choices define the browsing scope; Refine By selections
can be layered on top. Multiple selections inside one facet are OR; selections
across different facets are AND.

**Why:** The old sidebar made classification feel like another folder tree,
and the Explorer category drawer showed style/material/color categories that
the sidebar could not reproduce. Silent top-N clipping also hid values such as
`Spanish / Mission`, making the category system feel arbitrary.

**Consequence:** `/api/assets` and `/api/asset-ids` accept repeated
`facet=axis:value` params while preserving legacy `classification_axis` /
`classification_value` queries. The sidebar now exposes Style, Materials, and
Colors using the same legacy facet extraction as Explorer, and Explorer
category drawers no longer silently truncate chips to a top-N subset.

---

## D021 — Standalone collection PDFs replace live collaborator sharing (2026-05-27)

**Decision:** Inspirations remains Jim's local corpus-management app, including
Grid, Explorer, Review/Triage, Dave, imports, annotations, source QC, live
filtering, and collection editing. The external handoff product is now a
standalone PDF for one selected collection at a time. The old live
collaborator layer (magic links, actor chips, collaborator assignment, app
context links, question dashboard/polling, and live shared-collection modal)
is retired from active UI/API behavior.

**Why:** The product no longer needs to host a live app for designers. A
self-contained PDF is easier to share, review, archive, and open without
depending on the Mac, LAN, Cloudflare, app routes, or `store/` paths.

**Consequence:** `export collection-pdf` and
`POST /api/collections/{id}/export/pdf` are the first-class handoff paths.
PDF exports copy local previews under `data/exports/`, keep audit Markdown
beside the PDF, include visible external source URLs, and omit localhost,
LAN, `/api`, `/media`, `/store`, and other app-dependent links. Legacy schema
fields (`actors`, `collection_shares`, `collections.intent`,
`collections.shared_actor_id`, annotation actor/type columns) remain for now
but are treated as compatibility/legacy, not current product surface.

---

## D022 — Collection archives are folders, not hidden items (2026-06-01)

**Decision:** Collection-folder visibility is presented as an archive workflow,
separate from asset triage. The sidebar branch is named `Archived Collections`
and groups archived folders as `Completed Reviews`, `Imported Board Mirrors`,
and `Legacy Folders`. The management surface is named
`Manage Collection Archive`.

Historical `pins:` source-board mirror folders and completed `Review:` workflow
folders were removed after a local SQLite backup. Live source-board browsing
uses `assets.board` metadata directly. Active `CB:` creative-brief starting sets
and architect-scan workflow cohorts remain.

**Why:** The old `Hidden` label described two different concepts: hiding an
asset from the corpus and folding an obsolete collection folder out of the
sidebar. The old `pins:` folders were frozen board snapshots that duplicated
the live source tree and could drift from imported board metadata.

**Consequence:** Archiving or deleting a collection folder does not hide or
delete member assets. New collection UX should treat collections as deliberate
curator-created working sets or deliverables, not as a replacement for source
metadata browsing.

---

## D023 — Browse-first curation with a persistent curation bar (2026-06-01, revised 2026-06-02)

**Decision:** Leslie's everyday workflow is browse-first collection making, not
completion of a corpus-wide pending queue. A sticky curation bar remains visible
while the canvas scrolls and owns the item count, text filter, active-filter
summary, contextual collection PDF export, and a friendly `Show` selector for
`Usable items`, `All items, including discarded`, `Keepers`, `Flagged`, and
`Discarded`. Review remains available as an optional focused action mode over
the current scope.

**Why:** Most of the corpus is usable without item-by-item approval. The
database's historical null=`pending` state made almost every usable item look
like unfinished work and would invite Leslie to repeat cleanup that has already
been done.

**Consequence:** Existing triage schema and audit history stay intact for
compatibility and diagnostics. In everyday UX, null and `keeper` both mean
usable, while `hidden` is presented as discarded/irrelevant. The global app
header remains stable when modes change; Review and Make Collection add
contextual action rows inside the curation bar instead. The `Show` selector
changes item visibility only. Browse card clicks open a calmer detail view;
Review card clicks open detail with advanced QC/editing tools. Review
checkboxes are for bulk actions, and the explicit `One-by-one` action is the
route to fast triage. Flagged Grid cards use one stateful quick-action control
as both the visible state indicator and the unflag action, rather than a second
flag badge.

---

## D024 — Collection making is a separate canvas selection mode (2026-06-01)

**Decision:** The primary manual collection workflow begins with a visible
`Make Collection` action beside `Review`. It opens a separate browse-canvas
selection mode with a contextual action row in the shared sticky curation bar.
Selected cards can create a new collection, be added to an existing collection,
or be removed from the one collection currently in scope. Review/QC remains a
distinct mode with triage actions.

**Why:** Leslie's everyday goal is to gather ideas, not classify the corpus.
Reusing Review for collection making would blur creative selection with corpus
cleanup and make both workflows harder to understand. Starting from visible
cards also makes the effect of live filters obvious.

**Consequence:** `Make Collection` and `Review` must not be active at the same
time. Explorer closes collection selection before opening because the first
collection-building workflow is grid-based. Empty-folder creation and advanced
collection editing remain available through the sidebar tools.

---

## D025 — Schema assurance runs before threaded serving (2026-06-02)

**Decision:** `ensure_schema()` runs once in `run_server()` before the threaded
HTTP server starts. Normal API, catalog, media, and scan-PDF requests do not run
schema migrations or metadata backfills.

**Why:** Thumbnail-heavy grid browsing creates many concurrent requests.
Request-time schema maintenance introduced overlapping SQLite writes and caused
`database is locked` failures, which surfaced as missing thumbnails, failed
asset pages, and apparently unreliable automatic loading.

**Consequence:** New schema migrations and backfills remain idempotent but must
complete at startup or in explicit maintenance/import commands. Tests that seed
legacy rows should run schema assurance before starting their server fixture,
not depend on a request to mutate the database.

---

## D026 — Media repair choices remain reversible (2026-06-03)

**Decision:** Replacing an item's media never removes the curator's recovery
path. The detail modal's `Repair media` gallery exposes previously used saved
media from `asset_media_repair_audit` as selectable candidates. A later
`Find source media` result may add or fail to add post images, but it must not
hide recoverable prior media.

**Why:** Source sites, especially Facebook, often return text without usable
images. A successful no-image search previously looked like a failed action,
and choosing a generated text card made the original saved picture disappear
from the UI even though it remained in the audit log.

**Consequence:** Media-repair actions show explicit searching, result, and
failure feedback. Restoring previously used media archives the current choice
in turn, invalidates stale machine evidence, and enters the normal Admin refresh
queue.

---

## D027 — Advanced item editing belongs to Review context (2026-06-04)

**Decision:** Browse detail and Review detail are intentionally not identical.
Browse opens a calmer item detail view. Review context, including grid Review
and one-by-one `Edit title / media`, exposes title repair, media repair, and
Track Review editing.

**Why:** Browse is for looking and lightweight orientation. Review is where Jim
does corpus QC, repairs media/title problems, and records classification
decisions. Showing the same advanced repair UI everywhere makes Browse noisy,
while hiding it for ordinary Review items blocks curation.

**Consequence:** Advanced editing is gated by Review mode, not by whether the
item already has an ambiguity or saved override. The Track Review editor appears
for ordinary Review items too, so Jim can curate items as he finds them.

---

## Archived Decisions (pre-rebuild)

Decisions D010–D013 (cluster explorer, accessibility tier, session-only delete)
were specific to the pre-rebuild system. They are documented in
`docs/archive/` for reference but no longer apply to active development.
