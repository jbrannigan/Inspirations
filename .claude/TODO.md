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

## Sprint Buckets (updated Mar 2, 2026)

### Observation Intake (Mar 2, 2026) — Consolidated Plan

This plan merges the latest observation list with existing backlog items and
removes duplicate entries (Dave multiline/follow-up appeared twice).

#### Sprint 0 — P1 Stabilization + backlog carryover

1. **[x] Header view-toggle icon polish (Grid + Explorer)**
   - Existing backlog item #6; execute first.
   - Matched visual weight, no Safari clipping, legible at standard + Retina scales.
   - Implemented (Mar 2, 2026): replaced both icons with matched 16px SVG pair + Safari-safe stroke/padding styling.
2. **[x] 3D canvas bogus side scrollbar / resize interference**
   - Fix layout/overflow issue that blocks right-side window resize drag while Explorer is open.
   - Implemented (Mar 2, 2026): Explorer mode content now uses flex + overflow containment; 3D controls use border-box width to avoid right-edge spill.
3. **[x] Explorer count mismatch in 3D**
   - Remove stale/paged count behavior (`240 of xxx`) in Explorer mode; show scope-accurate counts.
   - Implemented (Mar 2, 2026): stats now show Explorer scope/filter counts instead of paged Grid counts while Explorer is active.
4. **[x] Owner modal print-button placement verification**
   - Confirm `Print` placement in owner mode with collaborator utility actions; adjust if still split.
   - Implemented (Mar 2, 2026): moved modal `Print` into the share/utility action group row.
5. **[→ Deferred] iPhone Explorer rotate crash triage**
   - Reproduce/report path for `view=explore` repeat-crash on rotate/drag gesture.
   - Capture diagnostics and containment fix scope for a future mobile sprint.
   - Scope decision (Mar 2, 2026): active target platform is iPad + desktop only; phone reliability/UX is explicitly deprioritized for now.

#### Sprint 1 — P1 IA harmonization + collaborator-first browsing

1. **[ ] Review UX unification (Grid + Explorer + role model)**
   - Existing backlog item #5.
   - Active scope/acceptance doc: `docs/SPRINT1_AGENDA_NEXT.md`
2. **[x] Collaborator default entry = Collections-first shared scope**
   - Open collaborators directly into shared-collections scope (no per-collaborator custom workflow).
   - Implemented (Mar 2, 2026): collaborator init now defaults to `Shared Collections` scope and starts with broader browse tree locked.
3. **[x] Explicit secondary browse affordance**
   - Add `Browse Leslie's collection` action to reveal the rest of the browse tree on demand.
   - Implemented (Mar 2, 2026): added collaborator-only `Browse Leslie's collection` button that reveals source/dimension tree while preserving shared-collections scope until the collaborator explicitly changes filters.
   - Follow-up fix (Mar 2, 2026): added short post-unlock click guard to prevent accidental immediate scope-drop taps while the tree rerenders.
4. **[x] Collaborator hidden-item leak after browse unlock**
   - Hidden items should never appear for collaborator roles while browsing unlocked source/dimension folders.
   - Implemented (Mar 2, 2026): server now role-gates `include_hidden` on `/api/assets`, `/api/asset-ids`, `/api/catalog/items`, and `/api/catalog/asset-ids` (owner-only).
   - Added regression coverage in `tests/test_server_api.py` for both generic and catalog include-hidden endpoints.
5. **[ ] Harmonize Inspirations IA with new Home websites**
   - Align naming, flow, and shared IA conventions across properties.
6. **[x] Upgrade `Add Scan` / `Add Clip` to unified `Add Media` intake**
   - Single owner entry point for media ingestion (`Add Media`).
   - Include photos and video upload/import paths in the same flow (not scan-only).
   - Keep current scan ingest capability while expanding to multi-media support.
   - Implemented (Mar 2, 2026):
     - Replaced separate header actions with one owner-facing `Add Media` launcher.
     - Added upload paths for clip PDF, photo, and video in one flow.
     - Per user direction, all three ingest paths now land in the `Clip` (`source='scan'`) bucket while preserving media subtype (`content_kind` = `scan` / `photo` / `video`).
     - Added optional ingest metadata fields (`Title`, `Tags`) with quick-pick chips from existing system label facets.
   - Active scope/acceptance doc: `docs/SPRINT1_AGENDA_NEXT.md`

#### Sprint 2 — P1 Dave conversation upgrade

1. **[ ] Multiline compose**
   - `Shift+Enter` inserts newline, `Enter` sends.
2. **[ ] Follow-up conversation continuity**
   - Preserve short-lived conversation context so clarifying Q/A works across turns.
3. **[ ] Threaded visible chat history**
   - Replace transient one-line response bar with usable conversation thread.

#### Sprint 3 — P1 shared user/role admin for 8499 site

1. **[ ] Named user admin (email proxy identity)**
2. **[ ] Multi-role management**
   - Extend roles beyond current owner/collaborator model (for example builder, architect).
3. **[ ] Cross-site admin scope**
   - Serve entire `8499timberbridgeln.com` role/user administration from one interface/API.

#### Sprint 4 — P2 Explorer clarity + interaction cleanup

1. **[ ] Side panel vs control panel overlap audit**
   - Decide if both are needed; remove redundancy.
2. **[ ] Attractor/anchor clarity + spacing controls**
   - Clarify terminology and improve controls for more distinct cluster balls.
3. **[ ] Anchor de-select persistence bug**
   - Anchors should fully clear after unselect.

#### Sprint 5 — P3 architecture + ingestion harmonization

1. **[ ] Unify Home + Inspirations server architecture (re-architecture sprint)**
   - Backup and rollback plan required before structural changes.
2. **[ ] Ingestion harness plan (nice-to-have)**
   - Idempotent incremental ingest path (skip existing; ingest only new/changed).
3. **[ ] Optional Explorer edges revisit**
   - Evaluate edge rendering as toggle-only experiment (not default).

#### Sprint 6 — P1/P2 Stabilization Bug-Fix Sprint (queued after current agenda)

Context:
- Post-merge validation on real devices surfaced multiple regressions/behavior mismatches.
- Decision: finish the current agenda slice first, then run a focused bug-fix sprint.

Planned workflow:
1. **[x] Bug intake consolidation**
   - Collect all newly observed breakages from iPad + desktop into one numbered list.
   - Deduplicate and tag each as `P1`/`P2`/`P3`.
   - Update (Mar 2, 2026): baseline inventory + scope captured in `docs/BUGFIX_SPRINT_BASELINE_2026-03-02.md`.
2. **[x] Repro + owner assignment**
   - Add clear repro steps and expected vs actual behavior for each issue.
   - Mark owner (`UI`, `API`, `3D`, `IA`, `mobile-deferred`).
   - Update (Mar 2, 2026): workflow/test matrix and manual validation ownership documented in `docs/WORKFLOW_TEST_MATRIX_2026-03-02.md`.
3. **[x] Fix in severity order**
   - Execute P1 blockers first, then P2 UX regressions, then P3 polish.
   - Decision-locked implementation tasks:
     - `JIM-1`: ingest chips align to Explorer groups + auto-tags (`actor`, `ingested_at`).
       - Implemented (Mar 2, 2026):
         - Add Media scan/photo/video modals now render grouped taxonomy chips for `source`, `rooms`, `styles`, `materials`, `types`, `colors`, `elements`.
         - Upload requests now include actor token header so ingest endpoints can resolve authenticated actor.
         - Backend ingest metadata now auto-applies `actor:<name|unknown>` and `ingested_at:<iso8601>` tags with case-insensitive dedupe.
         - Regression coverage added for unknown actor + authenticated actor auto-tag behavior.
     - `JIM-2`: expose `Clip > Scan/Photo/Video` subtype branches in tree/filter UX.
       - Implemented (Mar 2, 2026):
         - `/api/catalog/tree` now injects `source_subtype` children under Clip (`Scan`, `Photo`, `Video`) with counts derived from visible (non-hidden) `content_kind` rows.
         - Sidebar source tree now supports subtype node clicks, applying `source=scan` + `content_kind=<scan|photo|video>` filters.
         - Grid + Explorer filter sync now includes `content_kind` so both views stay aligned.
         - Tree contract tests extended to assert subtype branches exist and each subtype node resolves to items.
     - `JIM-3`: preserve scan doc/page suffix behavior on title override (already aligned; keep regression coverage).
       - Verified (Mar 2, 2026):
         - Upload metadata title override keeps split scan document/page suffix behavior.
         - Regression coverage maintained in ingest metadata upload tests.
     - `JIM-4`: add video poster generation in ingest/display pipeline.
       - Implemented (Mar 2, 2026):
         - Video ingest now generates deterministic asset IDs first, then attempts poster extraction with `ffmpeg` into `store/thumbs/video/<asset_id>.jpg`.
         - Poster extraction is fail-open: video ingest completes even when poster generation fails or `ffmpeg` is unavailable.
         - Import reports now include poster execution metadata (`tool`, `generated`, `errors`) for diagnostics.
         - Grid cards and modal playback now use poster thumbs for videos when available, with existing video playback fallback intact.
         - Added importer regression tests for both poster success and poster failure non-blocking paths.
   - Update (Mar 4, 2026):
     - Collaborator browse toggle copy/behavior clarified and made symmetric (`Browse more from Leslie collection ...` ↔ `Hide extra folders`).
     - Tree hierarchy readability polish shipped (nested branch clarity; removed internal vertical guide lines).
     - 3D unmatched-node spacing regression fixed by centroid fallback placement.
4. **[x] Regression pack**
   - Re-run Sprint 0 + Sprint 1 acceptance checks after each fix batch.
   - Update (Mar 2, 2026): canonical bug-fix suite runner added at `tools/run_bugfix_suite.py` (lint + full unit discover).
   - Update (Mar 2, 2026): re-ran bug-fix suite after `JIM-4`; lint + full unit discover PASS (`216` tests).
   - Update (Mar 4, 2026): `python3 tools/run_bugfix_suite.py` PASS; lint PASS; full unit discover PASS (`232` tests).
5. **[x] Sign-off checklist**
   - iPad + desktop pass list before closing sprint.
   - `JIM-5` gate (approved): no assumed passes; execute manual run log with per-item pass/fail notes.
   - Any failed manual item must be tracked as a bug with owner+repro before sprint closure.
   - Update (Mar 4, 2026):
     - Manual checklist executed on target platforms with owner acceptance.
     - Run log recorded at `docs/MANUAL_SIGNOFF_LOG_2026-03-04.md`.
     - No open manual failures.

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
     - Collaborators should start in shared collections scope by default.
     - Provide explicit `Browse Leslie's collection` affordance to reveal broader tree when needed.
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
