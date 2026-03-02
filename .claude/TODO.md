# TODO — Inspirations App

## Current State (Feb 28, 2026)

### What just shipped
- **Bulk Facebook reel analysis pipeline** — 951 reels processed through yt-dlp download → Gemini 2.5 Flash video analysis → auto-triage
  - 640 hidden (irrelevant: cooking, exercise, finance, makeup, pets, comedy)
  - 246 kept with Gemini-assigned titles, boards, and categories
  - 16 tagged by Jim — preserved for interactive review, not auto-triaged
  - 45 download errors (private/deleted reels), 4 analysis errors
- **UX fixes**: total item count in grid header, tree expand persistence, (uncategorized) board filter

### Completed this sprint (3D Fine Tune)
- Added dataset-size tuning profiles for live calm/damping/collision behavior.
- Recalibrated default 3D node sizes by collection size for better first-open readability.
- Added 3D Looks presets (save/apply/delete + startup preset).
- Revalidated 3D click-to-modal reliability and hard-refresh module cache busting.

### DB location
`data/inspirations.sqlite` (CLI default: `--db data/inspirations.sqlite`)

---

## Sprint Buckets (updated Feb 28, 2026)

### Next Sprint — Implementation (easiest-first)

1. **[x] Side tree header/folder click filters both Grid + Explorer**
   - Clicking a side-tree main header or folder must apply a filter.
   - Filter scope is recursive descendants (all nested children under that node).
   - Grid and Explorer canvas should reflect the same filtered scope.
   - Implemented (Feb 28, 2026):
     - Header clicks now apply filters; arrow click handles expand/collapse.
     - Dimension and collection headers apply recursive descendant scopes.
     - Explorer sync now uses full catalog scope via `/api/catalog/asset-ids` (not paged Grid IDs).

2. **[x] Hidden visibility rule in Explorer (role-gated)**
   - Hidden assets render only for owner/Jim role when Hidden status is explicitly active.
   - Collaborators never see hidden assets in Explorer.
   - If Focus is unchecked, hidden still must not appear unless hidden view is active for owner/Jim.
   - Implemented (Feb 28, 2026):
     - Explorer payloads request hidden data only when owner + `Hidden` status is active.
     - Server gates `include_hidden=1` on `/api/explorer/attractor-data` and `/api/explorer/layout` to owner role.
     - Explorer auto-reloads payload scope when entering/exiting hidden status so hidden nodes are never present outside hidden view.

3. **[x] Header button to hide/show side panel**
   - Add side panel toggle in header (header button only).
   - Persist state locally per browser via localStorage.
   - Implemented (Feb 28, 2026):
     - Added `Hide Panel`/`Show Panel` header button.
     - Sidebar visibility now toggles in both Grid and Explorer layouts.
     - Preference is persisted via localStorage key `inspirations.ui.sidebar.hidden.v1`.

4. **[x] PDF source-link bug fix**
   - Current issue: PDF items link back to the master PDF instead of the individual source item.
   - Fix link mapping so each PDF item opens its own original source context.
   - Preserve multipage UX (existing page-through behavior on multipage scans).
   - Implemented (Feb 28, 2026):
     - Scan source links now include absolute `#page=` anchors from each item's `source_ref`.
     - Multipage modal navigation now preserves absolute PDF page mapping instead of resetting to relative page numbers.
     - Source actions in modal (Open PDF / Print) now refresh correctly as user pages through a multi-page scan document.

5. **[ ] Review UX unification (Grid + Explorer + role model)**
   - Run a focused UX review of current Grid review mode redundancy.
   - Proposal target: owners always see one consolidated `Review` action bar with grouped controls in both Grid and Explorer (same structure/order).
   - Explorer and Grid should use the same primary review actions (`Keep`, `Hide`, `Flag`, `Tag`, `Clear`), with only view-specific controls separated.
   - Information architecture target (owner view):
     - Root 1: `Status` tree with `All` at root and status children (`Pending`, `Keepers`, `Hidden`, `Needs comment`, `Flagged`) nested under `All`.
     - Default state: `Status > All` is expanded and shows all status children.
     - Root 2: `Collections` (separate peer root).
     - Root 3: `All Items` (separate peer root for corpus browsing facets/sources).
     - Default state: `All Items` is expanded and shows its children.
   - Information architecture target (collaborator view):
     - Hide the entire `Status` block.
     - Show `Collections` first, with `All Items` as peer below it.
     - Default `Collections` to expanded on initial load.
   - Collection lifecycle follow-up:
     - Add `Hide collection` and `Delete collection` actions (owner).
     - Hidden collections should move under a `Hidden` branch within `Collections`.
   - Clarify and enforce scope hierarchy in UX copy and behavior:
     - `Hide in this collection` = remove membership from active collection only.
     - `Hide globally` = corpus-level triage hide.
     - `Keep` remains corpus-level unless a separate collection-local keep concept is approved.
   - Add acceptance notes and screenshots for both views before implementation sign-off.

6. **[ ] Header view-toggle icon polish (Grid + Explorer)**
   - Redo both toggle icons as a matched pair with equal visual weight and no clipping in Safari.
   - Explorer target style: perspective cube with lighter line weight and internal cluster dots.
   - Validate legibility at standard and Retina scaling.

### Explore Sprint — UX responsiveness + interactive validation

1. **[x] Slow-render feedback behavior**
   - User should see immediate UI acknowledgment for expensive Explorer actions.
   - Explore small busy indicator/hourglass behavior while canvas recompute/render is in progress.
   - Goal is responsiveness perception, then finalize implementation details.
   - Implemented (Feb 28, 2026):
     - Added Explorer busy overlay card + spinner inside `#explorerView`.
     - Added depth-safe Explorer busy state in `app.js` with wait cursor + overlay text.
     - Added phase copy updates during load (`Fetching…` then `Arranging…`).
     - Added pre-load paint yield (`requestAnimationFrame`) so busy UI paints before heavy 3D build.
     - Disabled repeat Explorer toggle clicks while load is active.

2. **3D hover preview experiment (interactive test with Jim first)**
   - Test a non-modal hover enlarge behavior for crowded 3D thumbnails.
   - Not a committed feature until validated interactively.
   - Regression to fix first (Mar 1, 2026): 3D hover preview disappeared, and hard-refresh can leave Explorer stuck on loading; restore hover behavior and resolve load-stall.

3. **Re-evaluate additional 2D/3D perf work after current gains**
   - Reassess whether separate 3D button, 2D precompute parity, and background thumb cache are still necessary.
   - Keep as exploratory unless profiling proves need.
   - Baseline (Feb 28, 2026, Playwright full dataset): busy overlay appears in 29-50ms; Explorer load completion varied 2.6s to 8.7s across 3 runs.
   - Option 2 update (Mar 1, 2026): deferred settle enabled on 3D view switch; sample run now 2.25s, 2.41s, 4.62s completion with 36-57ms busy-overlay first paint.
   - TODO: increase 3D Explorer thumbnail rendering speed (prioritize nearest-visible thumbs and reduce time-to-first-texture).
   - Update (Mar 1, 2026): 3D thumbnail pipeline now uses dataset-size budgets + nearest-first texture queue priority (capped prefetch/overlay targets) to improve time-to-first-texture.
   - BUG: 3D view can spontaneously close and return to main page while thumbnail textures are still painting; reproduce and fix unexpected view reset.
   - Mitigation (Mar 1, 2026): persisted view mode (Grid/Explorer) across reloads and hardened `--reload` devserver restart (stop/wait/rebind) to prevent reload races dropping users out of Explorer.

### Elaboration Sprint — define before build

1. **AI title quality audit + replacement workflow**
   - Treat AI titles as suspect pending audit.
   - Produce count, quality trend/reason breakdown, and candidate replacement strategy.
   - Evaluate source click-through + DOM title extraction as background workflow, then human vet.
   - Baseline draft created: `docs/AI_TITLE_AUDIT_BASELINE_2026-03-01.md`.
   - Interview priority (Mar 1, 2026): selected as next item to execute after Explorer perf.
   - Dry-run workflow added: `inspirations ai title-audit --table-out <path>` (JSON + markdown impact table).

2. **Collaboration context-link sprint (new)**
   - Sprint spec: `docs/SPRINT_COLLAB_CONTEXT_LINK.md`
   - Generate shareable link for a specific item in collection context ("look at this").
   - Link should restore the same item context for authenticated collaborator.
   - Link policy: durable by default (expiration/revocation policy deferred to later vote).
   - Link opens latest collection state (not historical snapshot), while preserving item reference.
   - Shared links must include a fixed `item_id` anchor so context always lands on the referenced item.
   - Transport targets: email/text/message copy flow from app UI.
   - Collaborator annotations are allowed and should be visually distinct from owner annotations.
   - Distinction style: annotation shows collaborator name + color.
   - Permissions:
     - collaborators can edit/delete their own annotations,
     - owner/Jim can edit/delete collaborator annotations.
   - Access scope: any authenticated collaborator can open shared context links.
   - If target item is no longer in the collection, show explicit "no longer in collection" state.
   - Question/reply workflow is intentionally split to a separate elaboration sprint item.
   - Define auth constraints and context snapshot shape before build:
     - actor role/permissions,
     - collection scope,
     - exact item reference,
     - view state needed for reproducible context.
   - Implemented (Mar 1, 2026):
     - Added `GET /api/context/resolve` with role-aware hidden-item handling.
     - Added modal share helpers (Copy Link, Email, Message/Web Share fallback).
     - Added deep-link restore on app load for `collection_id` + `item_id` (+ optional `open=1`).
     - Added explicit missing-state banner: "This item is no longer in this collection."
     - Enforced annotation edit/delete permissions (owner can manage all; collaborators own-only).
     - Added API tests for context resolve and annotation ownership/resolve rules.
   - Question to resolve: "Is this copy link workflow restricted to collections?"

3. **Collaborator question workflow (separate elaboration sprint)**
   - Sprint spec: `docs/SPRINT_COLLAB_QUESTION_WORKFLOW.md`
   - Define how collaborators ask questions tied to shared context links.
   - Define response/threading behavior in an in-app thread panel.
   - Ensure question context is unambiguous without requiring brittle manual quoting.

4. **Ingestion pipeline harmonization harness (nice-to-have)**
   - Plan idempotent incremental ingestion (skip existing, ingest only new/changed).
   - Move from bulk-only mindset to repeatable incremental updates.

5. **Tagging completeness confidence framework (TBD)**
   - Define if this is needed and, if so, the measurable target by source/pipeline.
   - Set acceptance metric before implementation.

### Deferred / Platform

- **External access via Cloudflare Tunnel** — serve Inspirations at `8499timberbridgeln.com/inspirations` for collaborators. Spec: `docs/DEPLOYMENT_EXTERNAL_ACCESS.md`. Covers: Cloudflare Tunnel from always-on Mac, DNS (Squarespace → Cloudflare), ThreadingHTTPServer + WAL mode, security headers, Secure cookies, Launch Agents for auto-start, rate limiting on admin login.
- **DevLauncher coordination / resilience**: add a `Safe Restart Server` option for projects that expose restart-safe lifecycle hooks, so one project restart does not clobber unrelated services.
- **Detail modal context expansion**: post text, AI labels, video analysis context.
- **Sidebar state persistence** when closing/reopening modal.
- **Small boards UX** refinements.
- **Jim's 16 tagged items** interactive review workflow.
- **45 failed reel downloads** retry/mark-unavailable decision.
- **Future sprint**: UX-driven ingest smoke test for adding photos, scans, and other media end-to-end (deferred from current sprint).

### Technical Debt

- **Rollback control placement**: keep chat-triggered rollback for now, but move rollback controls and history visibility to Admin page UX (owner-only) so operational actions live in one place.

## Tag System (Jim's Anomaly Markers)

Tags are separate from Flags. Tags mark items where Jim noticed something unusual (for example thumbnail label mismatch). The 16 tagged reels have video analysis stored but were intentionally not auto-triaged; they are preserved for collaborative review.
