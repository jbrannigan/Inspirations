# Inspirations UX Redesign Plan

## Context

Inspirations has evolved from an ingestion/tagging tool into a **consumption and curation** app. The current UI exposes too much ingestion plumbing (raw AI model names, 6 filter groups, dark developer-tool aesthetic). The audit-driven technical fixes (shared.js, toasts, grid perf, skeletons, empty states) are being completed separately and are nearly done.

This plan covers the **design and interaction redesign**:
1. Light, feminine, creative visual theme
2. Unified "Groups" model (boards + collections = groups)
3. Consumption-first layout (de-emphasize filters, elevate images and search)
4. Image zoom levels (S/M/L/XL grid + modal progressive loading)
5. 3D semantic explorer designed for visual cluster discovery (not just the old graph in 3D)
6. Simplified curation and sharing workflows
7. Admin/ingestion panel (separate from the creative workspace)

---

## Phase 1: Light Creative Theme

### The Problem
The current dark theme (`--bg: #0b0f14`, navy/charcoal everywhere) feels like a developer tool, not an interior design inspiration board. The audience is someone curating home design images to share with their designer.

### Design Direction
Warm, light, airy. Think Pinterest's cream/white, mixed with a sophisticated interior-design magazine feel.

### New Color System

```css
:root {
  /* Surfaces */
  --bg: #faf8f5;              /* warm off-white, paper-like */
  --panel: #ffffff;            /* clean white panels */
  --panel-hover: #f5f2ee;     /* warm hover */
  --surface-subtle: #f0ede8;  /* subtle section backgrounds */

  /* Text */
  --text: #2c2825;            /* warm near-black */
  --text-secondary: #6b6560;  /* warm gray for secondary text */
  --muted: #9c9590;           /* muted labels, counts */

  /* Borders */
  --border: rgba(44, 40, 37, 0.10);   /* warm subtle borders */
  --border-hover: rgba(44, 40, 37, 0.20);

  /* Accents */
  --accent: #b8860b;          /* antique gold / warm brass */
  --accent-soft: rgba(184, 134, 11, 0.12);
  --accent-2: #8b6f5c;        /* warm taupe for secondary actions */
  --accent-rose: #c4787a;     /* dusty rose for highlights */
  --accent-sage: #7a9b8a;     /* sage green for success states */

  /* Shadows */
  --shadow-sm: 0 1px 3px rgba(44, 40, 37, 0.06);
  --shadow-md: 0 4px 12px rgba(44, 40, 37, 0.08);
  --shadow-lg: 0 12px 32px rgba(44, 40, 37, 0.12);

  /* Typography (keep existing scale) */
  --fs-xs: 10px;
  --fs-sm: 12px;
  --fs-base: 14px;
  --fs-md: 16px;
  --fs-lg: 18px;
  --fs-xl: 22px;
}
```

### Typography
- Switch to warmer font stack: `"DM Sans", ui-sans-serif, system-ui, -apple-system, sans-serif`
- Load DM Sans from Google Fonts (light + regular + semibold)
- The brand "Inspirations" should feel editorial, not technical

### Card Treatment
- White cards with subtle warm shadow instead of dark glass-panel
- Rounded corners stay (12px), softer feel
- Card hover: gentle lift shadow + slight border warmth
- Remove dark gradient backgrounds on thumbnails
- Source badges: warm taupe pill instead of dark overlay

### Topbar
- White/cream background, thin warm border bottom
- Logo gradient: gold to sage (instead of cyan to green)

### Buttons
- Default: warm off-white with border
- Primary: gold/brass accent background, white text
- Danger: dusty rose
- Success: sage green

### Modals
- White background with warm shadow
- Light frosted backdrop (`background: rgba(250, 248, 245, 0.85); backdrop-filter: blur(8px)`)

### Implementation
The theme is largely in CSS custom properties, so updating `:root` handles most of it. But there are ~50 hardcoded `rgba(15,22,32,...)` dark values throughout styles.css that need to become variable references or warm equivalents.

**Files:** `app/styles.css` (full theme pass), `app/index.html` (Google Fonts link), cluster explorer and admin page may need matching theme updates

---

## Phase 2: Unified Groups + Consumption Layout

### 2a. Groups sidebar (replaces Filters + Collections)

**Current:** Left sidebar has "Filters" (6 checkbox groups) and "Collections" (list + New/Delete). Users just think "groups of things."

**New design:**

```
LEFT SIDEBAR
─────────────────────────
GROUPS

  [Search groups...]

  From Pinterest
    Kitchen Ideas          342
    Bathroom Inspo         187
    Exterior                94
    Hardware + Fixtures     73

  My Collections
    CB: Kitchen             47  ★
    CB: Primary Bath        23
    Round 1 Draft           12

  [+ New Group]

─────────────────────────
▸ Filters (2 active)
    Source ▸
    AI Tags ▸
    Media Type ▸
    Record Type ▸
    Creator ▸
```

- Boards and collections listed together, separated by origin headers
- Clicking a board filters the grid (read-only)
- Clicking a collection filters AND enables curation tools
- Collections show subtle edit affordance; boards don't
- Filters collapse into a single accordion at bottom, closed by default, badge shows active count

**Data model:** Boards are `assets.board` string values. Collections are `collections` + `collection_items` tables. They query differently but display identically. Existing `renderFilters()` + `renderCollections()` merge into `renderGroups()`.

**Files:** `app/index.html`, `app/app.js`, `app/styles.css`

### 2b. Simplified toolbar

**Always visible:** Stats count, Show All, Select All, Zoom control
**Contextual (when selected):** "N selected" + "Add to Group" dropdown + Remove + Clear
**Hidden:** Tray actions to tray sidebar, AI Tags toggle to Filters accordion, Review Collection to group context menu

### 2c. De-emphasize tags on cards

- **Default card:** Image + title only. No tag chips.
- **Expanded card:** Title + summary + source link. Tags behind "Show tags" toggle.
- Card footer: just annotation count + Annotate button (subtle)

**Files:** `app/app.js`, `app/styles.css`

---

## Phase 3: Image Zoom Levels

### 3a. Grid zoom control

Toolbar zoom: `[−] S M L XL [+]`

| Level | Grid `minmax()` | Card shows |
|-------|----------------|------------|
| S | `minmax(140px, 1fr)` | Image only |
| M (default) | `minmax(220px, 1fr)` | Image + title |
| L | `minmax(340px, 1fr)` | Image + title + summary |
| XL | `minmax(480px, 1fr)` | Image dominant, minimal text overlay |

- CSS classes `.grid.zoom-s` through `.grid.zoom-xl`
- `state.gridZoom` persisted to `localStorage`
- At XL, images fill most of the card — text overlaid or below

**Files:** `app/styles.css`, `app/app.js`, `app/index.html`

### 3b. Modal progressive loading

1. Show 512px thumb instantly (cached)
2. Background-load original, swap when ready
3. "View Source" button: Pinterest → opens source_ref, Scan → opens PDF, Photo → opens original in new tab

**Files:** `app/app.js`, `app/styles.css`

### 3c. Future: multi-resolution thumbnails (backend, not blocking)

Generate 256/512/1024px. Backend change in `thumbnails.py` + `server.py`. Can be done independently.

---

## Phase 4: 3D Semantic Explorer

### Why Not Just "Old Graph in 3D"

The current D3 cluster explorer is a **force-directed graph**: nodes connected by similarity edges, positions determined by spring physics. This is useful for finding duplicates and outliers but doesn't help with **visual discovery of semantic clusters**. It's a network diagram, not a spatial map of meaning.

What we want is a **semantic landscape** where:
- Position = meaning (embeddings projected to 3D)
- Clusters emerge naturally as visible spatial groupings
- You navigate through a field of images like walking through a gallery
- Close things look alike; far things don't
- You discover unexpected neighborhoods and relationships

### Design: Immersive Image Landscape

**Metaphor:** A gallery in space. Images float as cards arranged by meaning. You orbit, zoom, fly through.

**Core visualization:**
- Each image is a textured billboard (flat plane facing camera) in 3D space
- Position from embedding vectors projected to 3D via UMAP (preserves local structure better than t-SNE for navigation)
- **No edges/links by default** — this is a point cloud of images, not a graph
- Cluster membership shown by subtle color-coded halos or soft ground-plane tinting beneath each cluster
- Camera: orbit controls (drag rotate, scroll zoom, right-drag pan)

**Level of Detail (distance-based):**
- **Far (overview):** Soft colored dots at cluster centroids with floating labels ("Kitchen / Oak / Warm")
- **Medium (neighborhood):** Small thumbnails (64-128px) appear as billboards
- **Close (browsing):** Full thumbnails (256-512px) with title labels. Hover → image grows, border glows
- **Click:** Opens detail panel without leaving the 3D scene

**Key Interactions:**
- **Search highlight:** Type a term → matching images glow/pulse, non-matching fade to low opacity. The semantic landscape becomes a spotlight tool.
- **Lasso/box select:** Draw to select a spatial region → feeds into curation ("Add these to Group")
- **Filter by group:** Select a group in sidebar → only those items visible, rest fades or hides
- **Cluster labels:** Auto-generated from top AI tags per cluster. Float above centroids.
- **Similarity edges (toggleable):** Optional — turn on to see the graph view overlaid on the spatial layout

**Controls:**
- Point spread slider (scale positions to separate or compact clusters)
- Cluster count (if manual KMeans) or auto-detect
- Show/hide cluster labels
- Show/hide similarity edges
- LOD distance thresholds
- Reset camera

### Technical Architecture

**Backend (new endpoint):**
```
GET /api/explorer/layout?collection_id=...&method=umap&dimensions=3
```
Returns:
```json
{
  "nodes": [
    {"id": "...", "x": 1.23, "y": -0.45, "z": 0.78, "cluster_id": 2, "thumb_url": "/media/...?kind=thumb", "title": "..."},
    ...
  ],
  "clusters": [
    {"id": 0, "label": "Kitchen / Oak / Warm", "centroid": [0.5, -0.2, 0.3], "color": "#b8860b", "count": 47},
    ...
  ]
}
```

**Python layout computation:**
- Load embeddings from `asset_embeddings` table
- Run UMAP with `n_components=3` (via scikit-learn in isolated venv per D010)
- Run KMeans for cluster assignment (auto-K via silhouette score or user-specified)
- Generate cluster labels from top AI tags per cluster
- Cache result as JSON in `data/explorer_layouts/`
- Recompute only when embeddings change or user requests refresh

**Frontend module: `app/explorer.js`**
```javascript
window.Explorer = {
  init(containerId, config) { /* Three.js scene, camera, renderer, controls */ },
  loadData(data) { /* create billboards from node data, position in 3D */ },
  setFilter(nodeIds) { /* show subset, fade rest */ },
  highlight(nodeIds) { /* glow/pulse matching nodes */ },
  onSelect(callback) { /* lasso-select fires callback with node IDs */ },
  resetCamera() { /* fly back to overview */ },
  destroy() { /* cleanup */ }
};
```

**Dependencies (CDN only):**
- Three.js r160+ (ES module from CDN)
- OrbitControls from Three.js examples CDN

**Integration in main app:**
- View toggle: `[Grid] [Explore]` in toolbar area
- Explore replaces the grid area, sidebar stays
- Selection syncs between views (`state.selected`)
- Group selection in sidebar filters both views

**Modular for sharing portal:**
- `explorer.js` takes a container + pre-computed layout JSON
- Export portal embeds layout data at export time — no live server needed
- Same visual experience for recipients

### Cluster Label Generation
For each cluster, take top 3 most frequent AI tags across members:
- "Kitchen / Oak / Warm"
- "Bathroom / Tile / Modern"
- "Exterior / Stone / Traditional"

Labels float above cluster centroids in 3D. Also shown in a legend panel.

**Files:** `app/explorer.js` (new), `app/styles.css`, `app/index.html`, `app/app.js`, `src/inspirations/server.py`, new Python module for layout computation

---

## Phase 5: Curation Workflow

### 5a. Quick-add to group
Card hover reveals `+` icon. Click → dropdown of user collections → pick → item added, toast confirms. One interaction, not five.

### 5b. Multi-select + "Add to Group" dropdown
Toolbar dropdown lists all user collections. Pick one → selected items added → toast with undo.

### 5c. Drag-to-reorder in collection view
HTML5 drag-and-drop when viewing a collection. `collection_items.position` already supports ordering.
New endpoint: `PUT /api/collections/{id}/reorder`

### 5d. Collection stars (winners vs explored)
Star button on cards when viewing a collection. Starred items sort to top. Export portal shows starred prominently, unstarred in "See more."
New column: `collection_items.starred` (boolean, default false)

**Files:** `app/app.js`, `app/styles.css`, `src/inspirations/db.py`, `src/inspirations/store.py`, `src/inspirations/server.py`

---

## Phase 6: Admin / Ingestion Panel

Expand `admin.html` into a dashboard for ingestion operations:
- Import status (counts per source, last import dates)
- Processing coverage (thumbnails, AI tags, embeddings)
- Upload ZIP for re-import
- Trigger thumbnail/tagging/embedding jobs
- Existing delete functionality preserved

Keep "Add Scan PDF" and "Add Photos" in main app for quick session imports.

**New endpoints:** `GET /api/admin/status`, `POST /api/admin/import/pinterest`, etc.

**Files:** `app/admin.html`, `app/admin.js`, `src/inspirations/server.py`, `src/inspirations/store.py`

---

## Implementation Order

### Round 1 — Visual + Structural (ship first)
1. Phase 1: Light theme (CSS rewrite)
2. Phase 2a: Unified Groups sidebar
3. Phase 2b-2c: Toolbar simplification + card de-emphasis
4. Phase 3a-3b: Grid zoom control + modal progressive loading

### Round 2 — Explorer
5. Phase 4 backend: UMAP 3D layout endpoint
6. Phase 4 frontend: explorer.js (Three.js immersive landscape)
7. Phase 4 integration: view toggle, sidebar sync, search highlight

### Round 3 — Curation + Admin
8. Phase 5: Quick add, drag-to-reorder, stars
9. Phase 6: Admin/ingestion panel
10. Sharing portal upgrade (incorporate explorer.js)

---

## Verification

After each round:
1. `PYTHONPATH=src python3 -m inspirations serve --reload`
2. Open http://127.0.0.1:8000
3. `PYTHONPATH=src python3 -m unittest discover -s tests -v`
4. `ruff check src tests`

### Round 1:
- App feels warm, light, inviting — like a design magazine, not a dev tool
- Groups sidebar shows boards + collections unified
- Filters collapsed with active-count badge
- Grid zoom S/M/L/XL, images scale correctly
- Modal loads full-res, "View Source" opens original material
- Cards: image + title by default, tags hidden

### Round 2:
- [Explore] view shows 3D image landscape
- Clusters emerge as visible spatial groupings
- Hover grows images, click opens detail
- Search highlights matching nodes, non-matching fade
- Group filter shows/hides nodes
- Lasso select feeds curation

### Round 3:
- `+` on cards opens group picker
- Drag-to-reorder in collection view
- Stars, sorted to top
- Admin dashboard with import status and actions
