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

3. **Header button to hide/show side panel**
   - Add side panel toggle in header (header button only).
   - Persist state locally per browser via localStorage.

4. **PDF source-link bug fix**
   - Current issue: PDF items link back to the master PDF instead of the individual source item.
   - Fix link mapping so each PDF item opens its own original source context.
   - Preserve multipage UX (existing page-through behavior on multipage scans).

### Explore Sprint — UX responsiveness + interactive validation

1. **Slow-render feedback behavior**
   - User should see immediate UI acknowledgment for expensive Explorer actions.
   - Explore small busy indicator/hourglass behavior while canvas recompute/render is in progress.
   - Goal is responsiveness perception, then finalize implementation details.

2. **3D hover preview experiment (interactive test with Jim first)**
   - Test a non-modal hover enlarge behavior for crowded 3D thumbnails.
   - Not a committed feature until validated interactively.

3. **Re-evaluate additional 2D/3D perf work after current gains**
   - Reassess whether separate 3D button, 2D precompute parity, and background thumb cache are still necessary.
   - Keep as exploratory unless profiling proves need.

### Elaboration Sprint — define before build

1. **AI title quality audit + replacement workflow**
   - Treat AI titles as suspect pending audit.
   - Produce count, quality trend/reason breakdown, and candidate replacement strategy.
   - Evaluate source click-through + DOM title extraction as background workflow, then human vet.

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

- **Deployment auth** (before public exposure): email whitelist + magic links.
- **Detail modal context expansion**: post text, AI labels, video analysis context.
- **Sidebar state persistence** when closing/reopening modal.
- **Small boards UX** refinements.
- **Jim's 16 tagged items** interactive review workflow.
- **45 failed reel downloads** retry/mark-unavailable decision.

## Tag System (Jim's Anomaly Markers)

Tags are separate from Flags. Tags mark items where Jim noticed something unusual (for example thumbnail label mismatch). The 16 tagged reels have video analysis stored but were intentionally not auto-triaged; they are preserved for collaborative review.
