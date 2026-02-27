# Session Resume — Ontology Harmonization + Explorer Performance Sprint

## What Was Completed (PR #55: fix/grid-detail-view-fixes)

### Grid/Detail View Fixes
- **Card footer layout**: Changed from horizontal flex to vertical flex (title + category label stacked)
- **Labels in modal**: Added `/api/assets/{id}/labels` endpoint + label chips in detail modal
- **Houzz source link**: Fixed variable scoping for source URLs
- **Scan page view**: Changed button text "View Original" → "View Page", `?kind=pdf` → `?kind=original`

### Ontology Harmonization
- **CLAUDE.md**: Added "Ontology & Classification" section documenting trust hierarchy, Leslie's curation motivations, all classification dimensions, data tables, catalog system
- **ai.py**: Added rate limiting (0.15s sleep) + progress logging every 50 items to `run_gemini_image_labeler()`
- **chat.py**: Updated Dave's routing prompt with trust hierarchy (Collections > Boards > AI rooms/styles > AI labels) and answer prompt with provenance awareness

### AI Labeling Runs (overnight)
- **Pinterest**: 3,777/3,783 labeled (99.8%), 6 MAX_TOKENS errors, 12 fallback model uses
- **Houzz**: 226/226 labeled (100%), 0 errors
- **Final coverage**: 4,615/5,306 assets labeled (87%), 150,821 total label tags, 5,248/5,306 have AI data (99%)

### Catalog Regeneration
- Regenerated via `PYTHONPATH=src python3 -m inspirations catalog generate`
- Room uncategorized: 2,761 → 2,137 (-624 items)
- Style assignments: ~1,100 → 11,454 (10x growth, across 52 style files)
- Kitchen room: 586 items from 4 sources. Farmhouse style: 1,137 items
- Catalog files in `data/catalog/` (gitignored, regenerated from DB)

### 3D Explorer Texture Fix
- **Bug**: When switching sidebar branches in 3D mode, thumbnails disappeared (colored squares only)
- **Root cause**: `_rebuildForFocusedMode()` disposed texture maps that were shared via `_texCache` and still referenced by `node._tex`, causing `_queueVisibleTextures()` to skip re-queuing
- **Fix**: Detach textures from materials without disposing, clear tex queue, re-apply cached textures immediately to new meshes

### Files Modified (all on branch fix/grid-detail-view-fixes)
| File | Changes |
|------|---------|
| `app/styles.css` | Card footer layout, label chip styles |
| `app/app.js` | Labels fetch in modal, Houzz link fix, scan PDF fix |
| `app/index.html` | modalLabels div |
| `app/attractor-explorer-3d.js` | Texture disposal fix in `_rebuildForFocusedMode()` |
| `src/inspirations/server.py` | `/api/assets/{id}/labels` endpoint |
| `src/inspirations/store.py` | `list_asset_labels()` function |
| `CLAUDE.md` | Ontology & Classification documentation |
| `src/inspirations/ai.py` | Rate limiting + progress logging |
| `src/inspirations/chat.py` | Dave's system prompt with trust hierarchy |

---

## Next Sprint: 3D Explorer Performance

### Problem
The 3D explorer renders ~5,300 items with individual Three.js meshes — 5,300 draw calls/frame, no texture culling, expensive per-frame billboard updates.

### Phase 1: Quick Wins (single commit)

**File**: `app/attractor-explorer-3d.js`

1. **Shared geometry**: Replace 5,300 identical `PlaneGeometry(1,1)` with one shared instance
2. **Mesh-by-ID map**: Replace `_meshes.find()` O(n) lookup (line 638) with `Map` for O(1)
3. **Billboard camera check**: Track `_lastCameraQuat`, skip quaternion copy when unchanged (lines 554-558)
4. **Collision grid keys**: Replace string keys `"${cx},${cy},${cz}"` with numeric hash (lines 339-348)

### Phase 2: Distance-Based Texture Culling (single commit)

**File**: `app/attractor-explorer-3d.js`
**Reference**: 2D explorer's `_updateVisibleThumbs()` at `attractor-explorer.js:579`

- Only queue textures for nodes within `TEX_LOAD_DISTANCE` of camera
- Priority-sort by distance (nearest first)
- Periodically re-cull from render loop (throttled, camera-moved check)
- **Impact**: 95% fewer texture requests on initial load

### Phase 3: InstancedMesh (biggest win, single commit)

**File**: `app/attractor-explorer-3d.js`

Replace 5,300 individual meshes with 1 `THREE.InstancedMesh` for colored squares + individual texture overlay meshes for nodes near camera.

Sub-steps:
1. Core InstancedMesh with per-instance color via `InstancedBufferAttribute`
2. Billboard via instance matrix (camera quaternion in each instance's matrix)
3. Texture overlay meshes (separate individual meshes near camera only)
4. Visibility: color lerp toward background for dimmed nodes + smaller scale
5. Click detection: Raycaster supports InstancedMesh → `instanceId`
6. Focus mode rebuild: Destroy+recreate InstancedMesh with new count
7. Tween: Same interpolation, call `_syncInstancePositions()` instead

**Draw calls: 5,300 → ~100-200** (25-50x reduction)

### Phase 4: Render Loop Optimization (single commit)

- Dirty-flag system: `_needsInstanceUpdate`, `_needsVisualUpdate`, `_needsTexOverlayUpdate`
- Only work when flags are set
- Pre-allocate reusable `Object3D`/`Vector3`
- Near-zero JS cost on idle frames

### Verification
1. Visual: Source colors + thumbnails display correctly
2. Interaction: Click nodes, toggle attractors, sidebar filter, search dim
3. Texture culling: Only nearby nodes get thumbnails, progressive on orbit
4. Performance: Chrome DevTools — frame time ~5-8ms vs current ~15-20ms
5. Tests: `PYTHONPATH=src python3 -m unittest discover -s tests -v` (155 pass)

### Key Technical Details
- Three.js loaded via importmap from unpkg CDN (v0.160.0)
- InstancedMesh raycasting supported since r132
- Public API contract unchanged: `init, loadData, setFilter, setSearch, setFocusedMode, highlight, onSelect, onClickNode, on3DToggle, pause, resume, destroy`
- Only file modified: `app/attractor-explorer-3d.js`

---

## Environment Notes
- DB: `data/inspirations.sqlite` (78MB, 5,306 assets)
- Dev server: `PYTHONPATH=src python3 -m inspirations serve --port 8001 --reload`
- Gemini API key: `security find-generic-password -s inspirations_gemini_api_key -w`
- Branch: `fix/grid-detail-view-fixes` → PR #55
- All 155 tests pass
