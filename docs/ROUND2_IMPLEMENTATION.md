# Round 2 Implementation Brief: 3D Semantic Explorer

## Before You Start

Read these files first:
- `CLAUDE.md` — project conventions, common commands
- `DECISIONS.md` — architectural constraints (especially D001, D004, D010)
- `docs/UX_REFACTOR_PLAN.md` — full design context (Phase 4 section)

Round 1 is done and committed (PRs #22-#28). Don't touch the theme, groups sidebar, zoom, or toolbar — they're shipped.

## What You're Building

A 3D semantic image explorer where images float in space positioned by their embedding similarity. This is NOT the old force-directed graph in 3D. It's an immersive image landscape where position equals meaning, clusters emerge as spatial groupings, and you navigate through images like walking through a gallery.

## Constraints

- No npm, no build step — vanilla HTML/CSS/JS only (Decision D004)
- No external Python dependencies in main project (Decision D001)
- scikit-learn goes in isolated venv at `/private/tmp/inspirations-cluster-venv` (Decision D010)
- CDN-only for Three.js
- Match the warm light theme already in styles.css (use existing CSS custom properties)

## Verification After Each Sub-Phase

```bash
PYTHONPATH=src python3 -m inspirations serve --reload
# Open http://127.0.0.1:8000
PYTHONPATH=src python3 -m unittest discover -s tests -v
ruff check src tests
```

---

## Phase 4a — Backend: UMAP 3D Layout Endpoint

### New File: `src/inspirations/explorer_layout.py`

This module computes 3D positions for all assets that have embeddings, clusters them, and labels the clusters.

**Data sources:**
- `asset_embeddings` table — columns: `asset_id`, `embedding` (stored as JSON float arrays)
- `asset_labels` table — used to generate cluster labels from top AI tags
- `assets` table — for titles and thumb paths

**Computation pipeline:**
1. Load all embeddings from `asset_embeddings` for the requested scope (all assets, or filtered by collection_id)
2. Run UMAP with `n_components=3` to project high-dimensional embeddings to 3D coordinates. UMAP preserves local structure better than t-SNE, making it good for spatial navigation.
3. Run KMeans clustering on the 3D coordinates. Auto-detect K using silhouette score, capped at 15 clusters.
4. For each cluster, find the top 3 most frequent AI tags across its member assets (query `asset_labels`). Format as "Kitchen / Oak / Warm".
5. Compute cluster centroids (mean of member positions).
6. Assign a color to each cluster (pick from a palette that works with the warm light theme).

**Caching:**
- Cache the computed layout as a JSON file in `data/explorer_layouts/`
- Key the cache by a hash of the included asset IDs + a version counter
- Return cached result if it exists and `refresh` param is not true
- Create `data/explorer_layouts/` directory if it doesn't exist

**Isolated venv pattern:**
Look at how the existing code handles scikit-learn. The venv lives at `/private/tmp/inspirations-cluster-venv`. You'll need to either:
- Subprocess out to a script that runs in that venv, OR
- Use the same pattern as existing cluster computation code

Search for existing references to `cluster` or `umap` or `venv` or `scikit` in the codebase to find the established pattern. Reuse it.

**Return structure:**
```json
{
  "nodes": [
    {
      "id": "asset-uuid",
      "x": 1.23,
      "y": -0.45,
      "z": 0.78,
      "cluster_id": 2,
      "thumb_url": "/media/asset-uuid?kind=thumb",
      "title": "Kitchen island with oak countertop"
    }
  ],
  "clusters": [
    {
      "id": 0,
      "label": "Kitchen / Oak / Warm",
      "centroid": [0.5, -0.2, 0.3],
      "color": "#b8860b",
      "count": 47
    }
  ]
}
```

### Modify: `src/inspirations/server.py`

Add a new endpoint:

```
GET /api/explorer/layout
```

Query parameters:
- `collection_id` (optional) — scope to a specific collection's assets
- `method` (optional, default `umap`) — layout algorithm
- `dimensions` (optional, default `3`) — number of dimensions
- `refresh` (optional, default `false`) — force recomputation

If no `collection_id`, use all assets that have embeddings. Call the layout module and return the JSON response.

### New File: `tests/test_explorer_layout.py`

Test with mock data:
- Create fake embeddings (random float arrays of length 768 or whatever the embedding dimension is — check `asset_embeddings` table)
- Verify UMAP output has the right shape (N x 3)
- Verify cluster labels are generated correctly
- Verify caching works (second call returns cached, refresh=true recomputes)
- Verify collection_id filtering

---

## Phase 4b — Frontend: `app/explorer.js`

### New File: `app/explorer.js`

A self-contained module exposed as `window.Explorer`. Must be usable both in the main app AND later in the sharing portal (so don't couple it to app.js internals).

**CDN imports** — use importmap or dynamic import for:
- Three.js: `https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js`
- OrbitControls: `https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/controls/OrbitControls.js`

Note: Since this is vanilla JS with no build step, you'll need either a `<script type="importmap">` block in index.html or use dynamic `import()`. Check what approach works best without a bundler.

**Public API:**

```javascript
window.Explorer = {
  // Initialize the 3D scene in a container element
  init(containerId, config) {},

  // Load layout data from the backend and create the visualization
  loadData(data) {},

  // Show only these node IDs, fade/dim everything else
  setFilter(nodeIds) {},

  // Glow/pulse these node IDs, fade non-matching to low opacity
  highlight(nodeIds) {},

  // Register callback for lasso/box selection. Callback receives array of node IDs.
  onSelect(callback) {},

  // Animate camera back to overview position showing all nodes
  resetCamera() {},

  // Clean up Three.js resources (textures, geometry, renderer)
  destroy() {}
};
```

**Scene setup:**
- PerspectiveCamera with OrbitControls (drag to rotate, scroll to zoom, right-drag to pan)
- Soft ambient light + directional light for subtle depth
- Background color matching `--bg` from CSS (`#faf8f5` or read from CSS custom property)
- Renderer with antialiasing, sized to container

**Image billboards:**
- Each node is a PlaneGeometry with a texture loaded from `thumb_url`
- Billboards always face the camera (use `sprite` behavior or update rotation in render loop)
- Position each billboard at its `(x, y, z)` coordinates from the layout data
- Scale positions by a configurable spread factor (default makes the scene navigable)

**Level of Detail (LOD) — based on camera distance to each node:**
- **Far (overview):** Don't show individual images. Show colored spheres/dots at cluster centroids with floating text labels (use Three.js Sprite or CSS2DRenderer for text). Labels show the cluster label string like "Kitchen / Oak / Warm".
- **Medium (approaching):** Replace dots with small thumbnail billboards (scale them to appear 64-128px). Hide cluster labels, or make them smaller/transparent.
- **Close (browsing):** Thumbnails at full size (256-512px apparent). Show title text below each image. On hover (raycasting): image grows slightly, gets a subtle glow/outline.
- **Click (raycasting):** When user clicks a billboard, fire a callback or directly call `openModal()` from app.js to show the asset detail. The 3D scene stays visible behind the modal.

**Cluster visualization:**
- Subtle color-coded halos or translucent ground-plane circles beneath each cluster
- Cluster colors come from the backend response
- Cluster labels as text sprites floating above centroids, visible at far/medium distance

**Search highlighting:**
- `highlight(nodeIds)` makes matching billboards glow (e.g., emissive material, bright outline, or scale up slightly) and fades non-matching to 20% opacity
- Clear highlight by calling `highlight(null)` or `highlight(allNodeIds)`

**Lasso/box select:**
- Hold Shift + drag to draw a selection rectangle on screen
- Use raycasting or screen-space projection to find all nodes within the rectangle
- Call the registered `onSelect` callback with the selected node IDs
- Show a visual indicator (highlighted border) on selected nodes

**Controls panel:**
- Rendered as an HTML overlay (not in Three.js) — a small collapsible panel in the corner of the explorer container
- Point spread slider: scales all node positions by a multiplier (0.5x to 3x)
- Show/hide cluster labels toggle
- Show/hide similarity edges toggle (if edges are implemented)
- Reset camera button
- Style with existing CSS variables to match the warm theme

**Similarity edges (optional/toggleable):**
- If toggled on, draw thin lines between nodes that have high similarity
- This data would need to come from the backend (or be computed client-side from proximity)
- Default: OFF. This is the "graph view" overlay on top of the spatial layout.

### Performance considerations:
- Lazy-load textures: start with colored placeholder planes, load actual thumbnail textures progressively
- Use InstancedMesh or texture atlases if node count exceeds ~500
- Dispose textures when nodes go out of LOD range
- Use requestAnimationFrame render loop, but consider pausing when explorer is not visible
- Throttle raycasting (don't raycast every mousemove, use requestAnimationFrame)

---

## Phase 4c — Integration in Main App

### Modify: `app/index.html`

1. Add script tag for `explorer.js` (after shared.js, before app.js)
2. Add importmap or equivalent for Three.js CDN modules if needed
3. Add a view toggle in the toolbar: two buttons `[Grid]` and `[Explore]`
4. Add an explorer container div (sibling to the grid container, hidden by default):
   ```html
   <div id="explorerContainer" style="display:none; width:100%; height:100%;"></div>
   ```
5. Add a small controls panel div inside or adjacent to the explorer container

### Modify: `app/app.js`

1. Add `state.view = "grid"` (or "explore") to the state object
2. View toggle handler:
   - Switching to "explore": hide grid, show explorerContainer, init Explorer if not already, fetch `/api/explorer/layout`, call `Explorer.loadData()`
   - Switching to "grid": hide explorerContainer, show grid, pause explorer render loop
3. Wire sidebar group selection to also call `Explorer.setFilter()` when in explore view
4. Wire topbar search to also call `Explorer.highlight()` when in explore view
5. Wire `Explorer.onSelect()` callback to update `state.selected` and reflect in grid via `updateCardState()`
6. Wire billboard click to call `openModal()` with the corresponding asset
7. When collections or filters change and we're in explore view, update the explorer accordingly

### Modify: `app/styles.css`

1. Explorer container styles (full height of content area, position relative)
2. View toggle button styles (match existing toolbar button patterns, active state for current view)
3. Explorer controls panel styles (positioned absolute in corner, collapsible, warm theme)
4. Any overlay styles needed for lasso selection rectangle

---

## Files Summary

**Create:**
- `src/inspirations/explorer_layout.py`
- `app/explorer.js`
- `tests/test_explorer_layout.py`

**Modify:**
- `src/inspirations/server.py` — add `/api/explorer/layout` endpoint
- `app/index.html` — add explorer.js script, Three.js imports, view toggle, explorer container
- `app/app.js` — view state, toggle handler, explorer integration wiring
- `app/styles.css` — explorer container, view toggle, controls panel styles

**Do NOT modify** (already done in Round 1):
- Theme colors, Groups sidebar, zoom controls, toolbar structure, toasts, shared.js
