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

## Next Sprint: Phase 2 — Distance-Based Texture Culling

**File**: `app/attractor-explorer-3d.js`
**Reference**: 2D explorer's `_updateVisibleThumbs()` at `attractor-explorer.js:579`

- Only queue textures for nodes within `TEX_LOAD_DISTANCE` of camera
- Priority-sort by distance (nearest first)
- Periodically re-cull from render loop (throttled, camera-moved check)
- **Impact**: 95% fewer texture requests on initial load

## Phase 3: InstancedMesh (biggest win)

Replace 5,300 individual meshes with 1 `THREE.InstancedMesh` for colored squares + individual texture overlay meshes for nodes near camera.

Sub-steps:
1. Core InstancedMesh with per-instance color via `InstancedBufferAttribute`
2. Billboard via instance matrix
3. Texture overlay meshes (separate individual meshes near camera only)
4. Visibility: color lerp toward background for dimmed + smaller scale
5. Click detection: Raycaster supports InstancedMesh → `instanceId`
6. Focus mode rebuild: Destroy+recreate InstancedMesh with new count
7. Tween: Same interpolation, call `_syncInstancePositions()`

**Draw calls: 5,300 → ~100-200** (25-50x reduction)

## Phase 4: Render Loop Dirty Flags

- `_needsInstanceUpdate`, `_needsVisualUpdate`, `_needsTexOverlayUpdate`
- Only work when flags are set
- Near-zero JS cost on idle frames

---

## Environment Notes

- DB: `data/inspirations.sqlite` (78MB, ~4,662 visible assets)
- Dev server: `PYTHONPATH=src python3 -m inspirations serve --port 8001 --reload`
- Gemini API key: `security find-generic-password -s inspirations_gemini_api_key -w`
- Branch: `fix/grid-detail-view-fixes`
- All 155 tests pass
- Three.js v0.160.0 via importmap from unpkg CDN
- ES module cache tip: bump `?v=N` in `index.html` script tag when Chrome caches stale module
