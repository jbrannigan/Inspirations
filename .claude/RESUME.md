# Session Resume — 3D Explorer Performance + Source Chips

## What Was Completed (This Session)

All work on branch `fix/grid-detail-view-fixes`.

### 3D Explorer: Phase 1 Quick Wins

**File**: `app/attractor-explorer-3d.js`

1. **Shared geometry** — One `PlaneGeometry(1,1)` instance shared across all ~4,600 meshes instead of creating one per node. Saves ~4,600 GPU allocations.

2. **`_meshMap`** — Added `Map<id, entry>` for O(1) mesh lookup. Replaced `_meshes.find()` (O(n)) in `_applyTexToMesh()`.

3. **Billboard camera skip** — Track `_lastCameraQuat`, skip the per-mesh quaternion copy loop entirely when camera hasn't moved. Near-zero cost on idle frames.

4. **Numeric collision keys** — Replaced string template literal keys `"${cx},${cy},${cz}"` with packed integer `(cx+512)*1025²+(cy+512)*1025+(cz+512)`. Eliminates hot-path string allocation.

### Bug Fixes

- **`const _texQueue` reassignment** — Declaration was `const` but `_rebuildForFocusedMode()` tried to reassign it. Changed to `let`; reassignment changed to `_texQueue.length = 0`.

- **ResizeObserver crash** — `TypeError: Cannot read properties of null (reading 'setSize')` when observer fired after destroy(). Fixed: added `if (!_renderer || !_camera) return;` guard, stored as `_resizeObserver`, call `_resizeObserver.disconnect()` in `destroy()`.

### Source Chips + Thumbs Toggle

**Files**: `app/attractor-explorer-3d.js`, `app/styles.css`

- **Source chips** — Added a "Source" attractor group in the control panel hover-reveal area (before Rooms/Styles). Shows Pinterest / Facebook / Houzz / Scan as toggleable attractor chips with colored dot indicators. Source attractors pull matching nodes toward the poles in the force sim; Focus mode filters to only nodes matching active source attractors.

- **Thumbs toggle** — Added "Thumbs" checkbox to the always-visible sliders row (far right). When unchecked, strips texture maps from all meshes and shows pure source-colored squares. Re-checking re-applies cached textures and re-queues visible nodes.

- **`.src-dot`** — CSS rule in `styles.css` for the colored circle indicators on source chips.

- **Cache-busting** — Added `?v=2` query string to `<script src="/app/attractor-explorer-3d.js" type="module">` in `index.html`. ES module cache in Chrome doesn't flush on hard-reload; versioned URL forces re-fetch.

### Key State Additions

```js
let _meshMap = new Map();      // O(1) id → entry lookup
let _texQueue = [];            // was const, now let
let _sharedGeo = null;         // shared PlaneGeometry(1,1)
let _lastCameraQuat = null;    // sentinel for billboard skip
let _resizeObserver = null;    // stored for disconnect on destroy
let _showThumbs = true;        // thumbs toggle state
```

---

### 3D Explorer: Phase 2 — Nearest-First Queue

**File**: `app/attractor-explorer-3d.js` — `index.html` currently at `?v=10`

- **`_queueNearTextures()`** replaces `_queueVisibleTextures()`. Queues all unloaded nodes sorted nearest-first (camera distance) so foreground nodes load before background.
- Frustum culling was attempted and abandoned — THREE.Frustum approach failed because camera matrices aren't reliable before the first render frame, causing ~zero nodes to pass. Reverted to queue-all-sorted.
- `cursor: wait` added to `switchExplorerMode()` in `app.js` (wraps `await loadExplorerView()` in try/finally).

## RESOLVED: 3D thumbnails showing correctly

**Symptom**: In 3D explorer, Thumbs checkbox checked, but tiles show only source colors (no images). 2D works perfectly.

### What was verified this session

- Server returns correct thumbnails: `GET /media/UUID?kind=thumb` → `200 image/jpeg` (99KB)
- API returns correct `t` field for all 4,662 assets: `"t": "/media/UUID?kind=thumb"`
- Code structure (material, mesh, geometry, UVs) is all correct
- `_applyTexToMesh()` logic correct: sets `material.map`, `material.color(0xffffff)`, `material.needsUpdate`

### Root cause and fix

**Hypothesis**: `_rebuildForFocusedMode()` is called synchronously by `app.js` immediately after `loadData()` via `syncExplorerFilter()` → `setFilter(null)` (because `_focusedMode = true` by default). It clears `_texQueue` and resets `_texLoading = 0`, but leaves `node._texQueued = true` on all nodes (set by the first `_queueNearTextures()` in `loadData()`). The second `_queueNearTextures()` at the end of `_rebuildForFocusedMode()` then skips all nodes because they already have `_texQueued = true`, leaving the queue permanently empty.

**Fix applied** (`app/attractor-explorer-3d.js`, inside `_rebuildForFocusedMode()`):
```js
_texQueue.length = 0;
_texLoading = 0;
for (const node of _allNodes) {    // reset so nodes can be re-queued after rebuild
  if (!node._tex) node._texQueued = false;
}
```

### Verification (2026-02-27, Playwright + real browser)

- Loaded explorer in 3D mode on the full dataset (4,662 assets): thumbnail textures rendered correctly.
- Toggled **Thumbs OFF**: nodes switched to pure source-color squares.
- Toggled **Thumbs ON**: textures re-applied correctly.
- Toggled **Focus OFF/ON** (triggers focused rebuild path): textures remained visible after rebuild.
- No texture warnings/errors observed in console (only favicon 404).

Result: the `_texQueued` reset in `_rebuildForFocusedMode()` resolved the queue-empty condition that was preventing texture application.

---

## Completed: Phase 3 — InstancedMesh + Overlay Textures

**File**: `app/attractor-explorer-3d.js`

Implemented:
1. Replaced per-node base meshes with one `THREE.InstancedMesh` (`_instanceMesh`).
2. Billboarding now uses instance matrices with camera quaternion.
3. Added near-camera textured overlay meshes (`_overlayMeshes`) only for the nearest visible subset.
4. Added per-node visibility dimming via instance scale + color lerp toward background.
5. Updated click picking to support `instanceId` raycast on `InstancedMesh` + overlay fallback.
6. Focused-mode rebuild now re-creates the instanced mesh and overlays (no per-node mesh churn).
7. Tween/live updates now drive `_syncInstanceMesh()` instead of per-mesh position copies.

Validation (Playwright, full dataset):
- 3D loads with thumbnails.
- Thumbs OFF/ON works (source colors ↔ textures).
- Focus OFF/ON rebuild keeps textures working.
- Click on node opens detail modal.
- Drag-release click suppression still prevents accidental modal opens.

## Phase 4: Render Loop Dirty Flags

Implemented in `app/attractor-explorer-3d.js`:
- Added `_needsVisualUpdate`, `_needsInstanceUpdate`, `_needsOverlaySync`.
- `_updateNodeVisuals()` now runs only when visual filter/search/highlight state changes.
- Overlay sync is event-driven with min interval throttling (`OVERLAY_SYNC_MIN_MS`) instead of periodic every frame.
- Render loop now avoids full-node visual recompute and overlay sort work while idle.

## Completed: Explorer Busy Feedback

Files: `app/index.html`, `app/styles.css`, `app/app.js`

Implemented:
- Added an in-canvas Explorer busy overlay (`Building your 3D map…` / `Loading your map…`) with spinner.
- Kept global wait cursor handling and layered overlay state with depth-safe begin/end helpers.
- Added a `requestAnimationFrame` paint yield before heavy Explorer load work so busy UI renders immediately before synchronous map build.
- Added phase-progress copy during load (`Fetching your 3D map…` → `Arranging your 3D tiles…`).
- Disabled repeat Explorer-toggle clicks while an Explorer load is in flight.

Validation (2026-02-28, Playwright):
- Clicking Explorer on full dataset shows busy overlay text during load.
- Timed flow (Grid → Explorer): overlay visible at ~22ms after click, hidden at ~2387ms.
- Overlay clears after load and Explorer interaction resumes.
- Existing console output unchanged (favicon 404 only).

## Sprint-End Review Checklist

- [x] 3D orbit drag-release should not open detail modal (spin/pan, release over node, no click-through).
- [x] 2D → 3D switch responsiveness on full dataset should feel clearly busy (visible wait cursor) and complete within an acceptable delay.

## Post-Sprint Follow-Up

- [ ] Review the dedupe work for potential quality and performance improvements after this sprint is committed.

## Elaboration Progress: AI Title Audit Baseline

- Added draft report: `docs/AI_TITLE_AUDIT_BASELINE_2026-03-01.md`.
- Dataset scanned: 5,306 assets (`data/inspirations.sqlite`).
- Top findings:
  - 72 empty titles
  - 54 junk short-domain titles
  - 40 Facebook generic saved-link titles (25 dynamic-link risk, 15 title-check)
- Includes initial replacement workflow proposal and open decisions for morning.

## Completed: AI Title Audit Dry-Run Workflow

Files: `src/inspirations/title_audit.py`, `src/inspirations/cli.py`, `tests/test_title_audit.py`

Implemented:
- Added reusable title-audit engine with concise-title rules aligned to current review feedback.
- Added CLI command: `inspirations ai title-audit` (JSON output only).
- Added optional markdown table export via `--table-out`.
- Added unit tests for concise formatting, saved-link cleanup, hidden filtering, and CLI wiring.

Validation:
- `PYTHONPATH=src python3 -m unittest -q tests.test_title_audit` (pass)
- `PYTHONPATH=src python3 -m unittest -q tests.test_ai_semantic` (pass)
- CLI smoke test on real DB produced 112 candidates and wrote `docs/AI_TITLE_IMPACT_TABLE_AUTOGEN.md`.

## Perf Follow-Up: Option 2 (Deferred 3D Settle)

Files: `app/attractor-explorer-3d.js`, `app/app.js`

Implemented:
- Added deferred-settle window on 3D load (`deferSettle` hint from app view switch).
- Reworked settle/tween path to support frame-chunked settle computation before tween target commit.
- Added cancellation guards for deferred settle on rebuild/destroy to avoid stale async runs.

Validation (2026-03-01, Playwright):
- Grid -> Explorer, full dataset, 3 runs:
  - overlay first-visible: 57ms / 36ms / 42ms
  - overlay hidden (load complete): 4619ms / 2250ms / 2411ms
- Console remained clean except favicon 404.

## Completed: AI Title Audit Staging/Apply CLI Workflow

Files: `src/inspirations/db.py`, `src/inspirations/title_audit.py`, `src/inspirations/cli.py`, `tests/test_title_audit.py`

Implemented:
- Added DB-backed batch workflow tables for title audits (`title_audit_batches`, `title_audit_candidates`, `title_audit_applied`).
- Added title-audit lifecycle functions:
  - stage batch,
  - review batch rows,
  - mark rows approved/rejected/pending,
  - edit row title (marks edited),
  - apply approved/edited rows with drift protection (`--force` override),
  - undo applied batch rows with drift protection (`--force` override).
- Added CLI commands:
  - `inspirations ai title-audit-stage`
  - `inspirations ai title-audit-review`
  - `inspirations ai title-audit-mark`
  - `inspirations ai title-audit-edit`
  - `inspirations ai title-audit-apply`
  - `inspirations ai title-audit-undo`
- Kept existing dry-run command (`inspirations ai title-audit`) intact.

Validation:
- `PYTHONPATH=src python3 -m unittest -q tests.test_title_audit` (pass; 8 tests)
- `PYTHONPATH=src python3 -m unittest -q tests.test_server_api tests.test_storage_backfill` (pass; 32 tests)

## Session Update (Mar 2, 2026)

### Sidebar / tree behavior
- `Collections` is now treated as a peer root directly under `All Items` in Browse.
- Collaborator default remains collapsed-under-All-Items behavior for non-collection branches; collections stay visible.
- Owner/collaborator IA requirements were captured in backlog:
  - owner roots + default-expanded rules (`Status > All`, `All Items`),
  - collaborator roots (`Collections` then `All Items`, no Status).

### Modal UX fixes
- Removed visible UUID from modal header; kept `Copy ID` button only.
- Reworked modal header layout so title/meta are not squeezed by action buttons.
- Fixed clip modal `Print` to open a dedicated print shell that reliably calls print in Safari-style flows.
- Removed `View Page` from modal actions as redundant; clip/source flow is now `Open PDF` + `Print`.

### Header icon work
- Explorer toggle icon was iterated toward a perspective cube with internal dots.
- Added explicit next-sprint item to finish a matched icon redesign (Grid + Explorer) with Safari clipping/legibility validation.

---

## Environment Notes

- DB: `data/inspirations.sqlite` (78MB, ~4,662 visible assets)
- Dev server: `PYTHONPATH=src python3 -m inspirations serve --port 8001 --reload`
- Gemini API key: `security find-generic-password -s inspirations_gemini_api_key -w`
- Branch: `fix/grid-detail-view-fixes`
- All 160 tests pass
- Three.js v0.160.0 via importmap from unpkg CDN
- ES module cache tip: bump `?v=N` in `index.html` script tag when Chrome caches stale module

## Session Update (Mar 2, 2026 — Sprint 0 Wrap + Sprint 1 Handoff)

Files changed:
- `.claude/TODO.md`
- `app/index.html`
- `app/styles.css`
- `app/app.js`

Implemented (Sprint 0 prioritized items):
- Header Grid/Explorer view-toggle icon pair was polished as a matched 16px SVG set.
- Explorer layout overflow/scroll behavior was tightened to remove right-edge scrollbar/resize interference.
- Explorer stats now display scope-accurate Explorer counts (instead of paged Grid counts).
- Modal `Print` action was moved into the share/utility action group.

Planning/docs updates:
- Added consolidated observation intake and sprint structure in `.claude/TODO.md` (Sprints 0-5).

## Session Update (Mar 2, 2026 — Sprint 0/1 Regression Recheck)

Branch: `codex/sprint1-collaborator-collections-default`

### Fixes finalized on branch

- `app/app.js`:
  - Collaborator root order now renders `Collections` before `All Items`.
  - Collaborator locked mode keeps `Collections` expanded by default.
  - `Browse Leslie's collection` reliably unlocks the broader tree without clearing shared-collections scope.
  - Collaborator/context-link entry defaults to Grid unless URL explicitly sets `view=explorer`.
- `app/index.html`:
  - Bumped app script cache-buster to `app.js?v=15` to force delivery of latest collaborator IA logic.

### QA verification (Playwright, Mar 2, 2026)

- Sprint 0 checks:
  - Header view-toggle icons present (`Grid`, `Explorer`).
  - Explorer stats show scope count format (`N items`) with no stale `X of Y`.
  - Explorer content container reports zero horizontal overflow in tested desktop viewport (`overflowX: 0`).
  - Owner modal `Print` button exists and is inside `#modalShareGroup`.
- Sprint 1 checks:
  - Collaborator opens in Grid by default on plain actor link.
  - Collaborator root order is `Collections`, then `All Items`.
  - `Collections` is expanded by default with visible child leaves (`70` in test dataset).
  - Default filter indicator shows shared collections scope.
  - Clicking `Browse Leslie's collection` reveals broader tree (`By Room`, `By Style`, etc.) and preserves shared-collections filter indicator.
  - Context-link URL (`collection_id` + `item_id`) also opens in Grid by default unless `view=` is explicitly set.

### Notes

- Console output in checks showed only favicon `404` noise.

## Session Update (Mar 2, 2026 — Collaborator Hidden-Leak Fix)

Issue reported:
- In collaborator mode, after `Browse Leslie's collection`, some globally hidden assets were still visible.

Root cause:
- Server catalog endpoints used by unlocked browse-folder flows were not role-gating hidden access:
  - `/api/catalog/items` forced `include_hidden=True`
  - `/api/catalog/asset-ids` forced `include_hidden=True`
- Also tightened parity hardening for generic endpoints:
  - `/api/assets`
  - `/api/asset-ids`
  - `include_hidden=1` is now owner-only on all four routes.

Implemented:
- `src/inspirations/server.py`
  - Added actor-aware `include_hidden` gating on:
    - `/api/assets`
    - `/api/asset-ids`
    - `/api/catalog/items`
    - `/api/catalog/asset-ids`
  - Non-owner (or unauthenticated) requests now ignore `include_hidden=1`.

Tests added:
- `tests/test_server_api.py`
  - `test_assets_and_asset_ids_include_hidden_require_owner`
  - `test_catalog_endpoints_include_hidden_require_owner`

Validation:
- `PYTHONPATH=src python3 -m unittest -q tests.test_server_api` (pass; 38 tests).
- Isolated server check against real dataset/catalog now shows `leak_files=0` for `/api/catalog/items` default requests (was 4 leak files before patch).

## Night Handoff (Mar 2, 2026)

### Branch / PR

- Branch: `codex/sprint1-collaborator-collections-default`
- PR: `#65` — `Sprint 1 IA: default collaborators to shared collections`

### Commits from this session window (latest first)

- `444339a` — fix: block hidden assets in collaborator browse catalogs
- `6f38c4b` — fix: guard collaborator browse unlock from accidental scope drop
- `8d1c40c` — docs: record sprint 0/1 regression recheck status
- `778c066` — chore: bust app.js cache for collaborator IA order fix
- `29ac2e3` — fix: stabilize collaborator tree order and grid entry
- `f1a6764` — fix: reveal collaborator browse tree without changing scope
- `4b856f1` — feat: default collaborators to shared collections scope

### Current acceptance status

- Sprint 0 checks: pass in automated regression.
- Sprint 1 IA checks: pass in automated regression.
- Reported collaborator hidden-leak during `Browse Leslie's collection`: fixed server-side and covered by tests.

### Morning first-step checklist

1. Start server from this repo root using local source path:
   - `PYTHONPATH=src python3 -m inspirations --db data/inspirations.sqlite --store store serve --host 0.0.0.0 --port 8001`
2. Open collaborator URL with cache-bust query:
   - `http://localhost:8001/?actor=collab-b629bd3ae17e4be9&r=morning-check`
3. Verify flow:
   - `Collections` first, expanded.
   - Click `Browse Leslie's collection`.
   - Confirm hidden items do not appear in unlocked browse folders.

### Known operational note

- If another launcher process auto-starts an old `--reload` server, browser behavior can appear stale even after code fixes. When in doubt, stop existing `:8001` listeners and restart with the command above before validating.

## Session Update (Mar 3, 2026 — Agenda vs Stabilization Split)

User direction:
- Continue with planned agenda work now.
- Queue a dedicated bug-fix sprint immediately after agenda slice completion.

Tracking updates:
- Added queued stabilization sprint in `.claude/TODO.md` as:
  - `Sprint 6 — P1/P2 Stabilization Bug-Fix Sprint`
  - Includes intake, repro, severity-order fix execution, and regression/sign-off steps.
- Marked iPhone Explorer crash work as deferred to a future mobile sprint.
- Explicit scope decision recorded: active platform target is iPad + desktop.

Next sprint entry point:
- Start Sprint 1 IA harmonization with collaborator-first browsing defaults (`Collections` first), then owner review UX unification.

## Session Update (Mar 2, 2026 — Sprint 1 IA: Collaborator Entry Defaults)

Files changed:
- `app/app.js`
- `app/styles.css`
- `.claude/TODO.md`

Implemented:
- Collaborators now default into shared `Collections` scope on load (`Shared Collections`) instead of opening into broad all-items browsing.
- Added collaborator gate for browse tree expansion: source/dimension branches stay hidden initially.
- Added collaborator-only `Browse Leslie's collection` button to reveal the broader tree while preserving shared-collections scope until collaborators deliberately change filters.

Scope note:
- Phone-specific concerns remain deferred; this IA work targets iPad + desktop flows.

## Session Update (Mar 2, 2026 — Sprint 1 Agenda: Add Media + Ingest Metadata)

Files changed:
- `app/index.html`
- `app/styles.css`
- `app/app.js`
- `src/inspirations/importers/scans.py`
- `src/inspirations/server.py`
- `tests/test_scans_import.py`
- `tests/test_server_api.py`
- `.claude/TODO.md`
- `docs/SPRINT1_AGENDA_NEXT.md`

Implemented:
- Replaced separate owner header actions (`Add Clip`, `Add Photos`) with one `Add Media` action.
- Added a unified media chooser and wired three upload flows:
  - Clip PDF upload (`/api/import/scans`)
  - Photo upload (`/api/import/photos`)
  - Video upload (`/api/import/videos`)
- Per latest product direction, all three ingest flows are stored under Clip source (`source='scan'`) while preserving subtype with `content_kind` (`scan` / `photo` / `video`).
- Added optional ingest metadata on all three flows:
  - `Title` input
  - `Tags` input
  - Clickable quick-pick tag chips sourced from existing label facets (`/api/facets` labels)
- Backend now applies ingest metadata to newly created assets from each upload batch:
  - Updates title on newly imported assets (scan doc suffix preserved for PDF split pages).
  - Inserts user-selected tags into `asset_labels` (`source='owner-upload'`).
- Added video-safe rendering updates in UI:
  - Grid cards render video assets with `<video>` element.
  - Detail modal supports video playback via `#modalVideo`.

Validation:
- `PYTHONPATH=src python3 -m unittest -q tests.test_scans_import tests.test_server_api` (pass, 47 tests).
- `python3 -m py_compile src/inspirations/server.py src/inspirations/importers/scans.py` (pass).

## Session Update (Mar 2, 2026 — Bug-Fix Sprint Kickoff: Inventory + Validation Suite)

User direction:
- Pause new feature work and shift to a dedicated bug-fix sprint.
- Document known features/workflows, define a complete validation suite, run it, and queue unclear decisions for Jim.

Delivered:
- Added bug-fix sprint baseline doc: `docs/BUGFIX_SPRINT_BASELINE_2026-03-02.md`
  - Known feature/workflow inventory across auth, browse, collab links, review, explorer, ingest, media, AI, export, scrape, and security flows.
  - Canonical validation commands and baseline run status.
  - Explicit decision queue for Jim (`JIM-1` ... `JIM-5`).
- Added workflow test matrix: `docs/WORKFLOW_TEST_MATRIX_2026-03-02.md`
  - Automated coverage map by workflow area and current status.
  - Manual-only validation matrix for iPad/desktop sign-off.
- Added canonical runner: `tools/run_bugfix_suite.py`
  - Runs lint + full unit-test discover with JSON output for repeatable sprint validation.

Coverage improvements:
- Added ingest-metadata workflow tests in `tests/test_server_api.py`:
  - scan upload metadata apply (title/tags + scan doc suffix preservation),
  - photo upload metadata apply,
  - video upload metadata apply.

Clear bug fixes applied:
- Fixed CI lint break (`F821 undefined name uuid`) by importing `uuid` in `src/inspirations/server.py`.

Validation run (bug-fix baseline):
- `tools/run_bugfix_suite.py` → PASS
  - lint: PASS
  - full unit discover: PASS (`212` tests)
