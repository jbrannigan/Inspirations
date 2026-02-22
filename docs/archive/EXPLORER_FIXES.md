# Explorer Fixes — Cluster Spacing + Keep Both 2D and 3D

## Before You Start

Read these files first:
- `CLAUDE.md` — project conventions
- `src/inspirations/explorer_layout.py` — backend layout computation (271 lines)
- `app/explorer.js` — frontend 3D scene (600 lines)
- `app/app.js` — view toggle integration (~lines 2427-2528)
- `app/index.html` — view toggle buttons (~line 92), explorer container (~line 136)
- `tools/cluster_explorer.html` — existing 2D D3 force-directed explorer

## Problem 1: 3D Clusters Too Close Together

The backend normalizes all UMAP coordinates to ±5 units (`_normalize_coords` in `explorer_layout.py:137`). The frontend spread slider goes 0.5–3.0× (`explorer.js`). So the max scene diameter is ~30 units. With up to 15 clusters, they pile on top of each other.

The issue is in the normalization — UMAP naturally creates well-separated clusters, but then we squeeze everything into a tiny box.

### Fix: Better normalization + wider spread range

**In `src/inspirations/explorer_layout.py` — `_normalize_coords()` (line 137):**

Change the base scale from `10.0` to `30.0`:
```python
scale = 30.0 / max(x_range, y_range, z_range)
```

This gives ±15 units base range instead of ±5. Clusters get 3× more room to breathe.

**In `app/explorer.js` — spread slider and LOD thresholds:**

1. Change spread slider range from `0.5–3.0` to `0.5–5.0` (find the slider setup, likely in the controls panel HTML generation). Default should be `1.5` instead of `1.0`.

2. Update LOD distance thresholds to match the larger scene (find constants near top of file):
   - `LOD_FAR`: `40` → `120` (clusters dots visible at overview distance)
   - `LOD_MED`: `22` → `65` (thumbnails appear at medium distance)
   - `LOD_CLOSE`: `12` → `35` (full-size thumbnails + titles at close range)

3. Update camera starting position from `(0, 0, 25)` to `(0, 0, 75)` so the initial view shows the full landscape.

4. Update `resetCamera()` to match the new starting position.

**After making these changes**, delete the cached layout files so they regenerate with new coordinates:
```bash
rm -f data/explorer_layouts/*.json
```

Then restart the server and switch to Explore view to verify clusters are visually separated.

## Problem 2: Need Both 2D and 3D Explorers

The 2D D3 cluster explorer (`tools/cluster_explorer.html`) is a mature tool with Discover/Outliers/Duplicates modes, similarity thresholds, and a full curation workflow. The 3D explorer is a spatial overview. They serve different purposes and both should be accessible.

Currently:
- The 2D explorer opens via the "Review Collection" button → new window to `tools/cluster_explorer.html`
- The 3D explorer is the `[Explore]` view toggle in the main app

### Fix: Keep both, make access clear

**In `app/index.html` — view toggle area (~line 92):**

The current view toggle has two buttons: `[Grid] [Explore]`. Change to three:
```html
<div class="viewToggle" id="viewToggle" role="group" aria-label="View mode">
  <button type="button" id="viewGrid" class="active" aria-pressed="true">Grid</button>
  <button type="button" id="viewExplore" aria-pressed="false">Explore</button>
  <button type="button" id="viewReview" aria-pressed="false">Review</button>
</div>
```

**In `app/app.js`:**

Wire up the `#viewReview` button. When clicked:
- If a collection is selected (`state.viewCollectionId`), open the 2D cluster explorer with that collection's data (same as current Review button behavior):
  ```javascript
  const dataUrl = `/api/cluster/review?collection_id=${encodeURIComponent(state.viewCollectionId)}&include_neighbors=0`;
  const url = `/tools/cluster_explorer.html?data=${encodeURIComponent(dataUrl)}`;
  window.open(url, "_blank");
  ```
- If no collection is selected, open the 2D cluster explorer with ALL assets:
  ```javascript
  const url = `/tools/cluster_explorer.html`;
  window.open(url, "_blank");
  ```
- This button does NOT change the active view state (it opens a new window). Keep the current view (grid or explore) active.

**Remove the old "Review Collection" button** from the toolbar (`#reviewCollection` at index.html line 101). Its functionality is now in the view toggle as `[Review]`. This declutters the toolbar.

**Update `setStats()` in `app/app.js`** (~line 618): Remove the `reviewBtn` logic since the button no longer exists. The Review view toggle button doesn't need to be disabled — it always works (opens all assets if no collection selected, collection assets if one is selected).

**In `app/styles.css`:** The `.viewToggle` styles should already handle 3 buttons since it's a flex container. Verify it still looks good with 3 items. If the buttons are too cramped, reduce padding slightly.

## Verification

```bash
# Clear cached layouts
rm -f data/explorer_layouts/*.json

# Start server
PYTHONPATH=src python3 -m inspirations serve --reload

# Open http://127.0.0.1:8000 and verify:

# 3D Explorer (click [Explore]):
# - Clusters are visually separated — you can see distinct groupings
# - Spread slider goes up to 5.0
# - Camera starts far enough to see the whole landscape
# - Zooming in shows thumbnails at reasonable distance
# - Cluster labels are readable and don't overlap (at overview distance)
# - LOD transitions feel smooth (dots → small thumbs → large thumbs)

# 2D Review (click [Review]):
# - Opens cluster_explorer.html in new window
# - If viewing a collection: shows that collection's cluster data
# - If no collection: shows all assets
# - Discover/Outliers/Duplicates modes all work

# View toggle:
# - [Grid] and [Explore] toggle between views (mutual exclusive)
# - [Review] opens new window without changing the current view
# - Old "Review Collection" button is gone from toolbar

# Tests + lint
PYTHONPATH=src python3 -m unittest discover -s tests -v
ruff check src tests
```

## Files Summary

**Modify:**
- `src/inspirations/explorer_layout.py` — increase normalization scale from 10 to 30
- `app/explorer.js` — wider spread slider, higher LOD thresholds, farther starting camera
- `app/index.html` — add `[Review]` button to view toggle, remove old `#reviewCollection` from toolbar
- `app/app.js` — wire `#viewReview` click handler, remove old review button logic from `setStats()`
- `app/styles.css` — verify view toggle handles 3 buttons (probably no change needed)
