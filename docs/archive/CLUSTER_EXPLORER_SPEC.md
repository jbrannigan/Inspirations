# Cluster Explorer — Feature Specification

> Status: superseded by `docs/CLUSTER_EXPLORER_SPEC-v2.md` for active implementation work.
> Keep this file as historical context only.

> **Document type**: Implementation spec (roadmap).
> Items marked **[EXISTS]** are already implemented. All other items are **new work**.
> This spec was reviewed by Codex and revised to fix P1/P2 findings.

## Overview

A browser-based visual exploration tool for Leslie's curated inspiration collections.
Renders semantic clusters as a force-directed graph where **nodes are actual thumbnail
images** (not colored dots), draggable and zoomable, with three distinct interaction modes.

**Primary operating mode**: The explorer is served locally via a lightweight Python HTTP
server (`tools/serve_explorer.py`). This is required because browsers block `file://`
cross-origin image loading. The explorer HTML and JSON data can be distributed as static
files, but images must be served over HTTP.

## Prerequisites

Before running the explorer pipeline, the following must be complete:

1. **Assets imported** — `python3 -m inspirations import` (pins, scans, etc.)
2. **AI tagging done** — `python3 -m inspirations ai tag` (generates labels + summaries)
3. **Embeddings generated** — `python3 -m inspirations ai embed` (populates `asset_embeddings`)
4. **Thumbnails generated** — `python3 -m inspirations thumbs` (populates `thumb_path`)

If embeddings are missing for some assets, the export script will silently skip them
and report the count.

## Data Pipeline

### Export Script: `tools/export_clusters.py` [EXISTS — needs updates]

Current state: reads embeddings, clusters via KMeans with silhouette scoring, computes
cosine similarity edges, outputs JSON with nodes + links.

#### Required changes:

1. **Fix DB path default.** The repo's active database is `data/inspirations.sqlite`
   (not `inspirations.db`). Update `--db` default and all documentation examples.

2. **Include `source_url`** — pull from `assets.source_ref` or reconstruct from
   `assets.source` + `assets.source_ref` (Pinterest: `https://pinterest.com/pin/{source_ref}`).

3. **Resolve image paths as relative to a known base.**
   - `thumb_url`: relative path from the DB's `thumb_path` column
   - `image_url`: either the remote URL from `assets.image_url` or the local
     `stored_path` — prefer local if it exists
   - Add `meta.image_base_path` to the output JSON, set to the absolute path of the
     Inspirations data directory. The serve script uses this to locate images.

4. **Compute outlier scores** per node:
   - `isolation_score`: `1.0 - mean_similarity_to_k_nearest_neighbors` (higher = weirder)
   - `bridge_score`: count of this node's edges that cross cluster boundaries,
     divided by total edge count for the node (0.0 = fully within cluster, 1.0 = all
     edges cross clusters)
   - `is_outlier`: true if `isolation_score` is in the top 10%

5. **Add `--collection` filter** flag. Accepts a collection **ID** (not name — names
   are mutable and not unique). Exports only that collection's items plus their
   `--include-neighbors N` nearest uncategorized neighbors by embedding similarity.

6. **Add `--serve` flag.** When set, after exporting JSON, automatically start
   `serve_explorer.py` and open the browser.

### Output Schema: `cluster_data.json`

```jsonc
{
  "meta": {
    "source_db": "data/inspirations.sqlite",
    "exported_at": "2026-02-14T12:00:00Z",
    "total_assets": 3661,
    "total_links": 10924,
    "clusters": 14,
    "similarity_threshold": 0.72,
    "image_base_path": "/Users/minime/Projects/Inspirations"
    // serve_explorer.py uses this as the static file root for images
  },
  "nodes": [
    {
      "id": "asset_abc123",
      "title": "White oak kitchen with brass hardware",
      "board": "Kitchen Remodel",
      "source": "pinterest",
      "source_url": "https://pinterest.com/pin/123456",
      "collections": ["CB: Kitchen"],       // collection names for display
      "collection_ids": ["coll_xyz"],        // stable IDs for write-back
      "labels": ["kitchen", "white oak", "brass", "island", "marble"],
      "summary": "Bright kitchen with white oak cabinets, brass pulls...",
      "image_url": "data/images/abc123.jpg",          // local path (preferred)
      "image_url_remote": "https://i.pinimg.com/...", // remote fallback
      "thumb_url": "data/thumbs/abc123_240.jpg",      // local relative path
      "cluster": 3,
      "is_centroid": false,
      "is_outlier": false,
      "isolation_score": 0.34,
      "bridge_score": 0.0,
      "neighbor_count": 4
    }
  ],
  "links": [
    { "source": "asset_abc123", "target": "asset_def456", "similarity": 0.84 }
  ]
}
```

## Image Loading

### Primary: Local HTTP server (`tools/serve_explorer.py`) [NEW]

A ~40-line Python script using `http.server`:

```bash
python3 tools/serve_explorer.py --port 8080
```

Behavior:
1. Reads `meta.image_base_path` from `tools/cluster_data.json` to determine the
   project root directory
2. Serves `tools/cluster_explorer.html` at `http://localhost:8080/`
3. Serves `tools/cluster_data.json` at `http://localhost:8080/cluster_data.json`
   (auto-loaded by the explorer on page open — no file picker required)
4. Serves all files under the project root (images, thumbs) at their relative paths
   (e.g., `http://localhost:8080/data/thumbs/abc123_240.jpg`)
5. Sets `Cache-Control: max-age=3600` on image responses for snappy reloads

### Fallback: Existing Inspirations server

The Inspirations app already serves at `http://minime.local:8000`. The existing
endpoint for images is:

```
GET /media/<asset_id>?kind=thumb     → thumbnail
GET /media/<asset_id>?kind=original  → full image
```

If the explorer detects `meta.api_base` in the JSON, it fetches images from
`{api_base}/media/{asset_id}?kind=thumb` instead of using relative paths.

To enable this, the export script accepts `--api-base http://minime.local:8000`
which writes the URL into `meta.api_base`. The Inspirations server may need CORS
headers added if the explorer is served from a different origin (localhost:8080 vs
minime.local:8000).

### Not recommended: data URI embedding

Encoding 3,600 thumbnails as base64 in the JSON would produce a ~200-400MB file.
This is not viable at scale. Mentioned only to document why it was rejected.

## Explorer UI: `tools/cluster_explorer.html` [EXISTS — needs rewrite]

Single self-contained HTML file. Dependencies loaded from CDN:
- D3.js v7 (force simulation, zoom, drag)
- No build step, no framework

### Image Nodes

Replace colored circles with actual thumbnails:
- Render each node as a `<clipPath>` circle masking the thumbnail image
- Circle diameter: 40px default, 56px for centroids, 32px for low-neighbor nodes
- Border color = collection color (from palette)
- Border width: 3px for centroids, 2px for selected, 1px default
- Fallback: if image fails to load, show colored circle with first letter of title
- Hover: scale up 1.5x with CSS transition, show tooltip

### Performance for 3,600+ Nodes

- Use `<canvas>` renderer instead of SVG for the main graph when node count > 500
  (D3 force simulation works the same, just draw to canvas instead of DOM)
- Lazy-load images: only load thumbnails for nodes currently in the viewport
  (track visible bounds from the zoom/pan transform, load images within bounds + margin)
- Thumbnail size: 240px (already generated by Inspirations' thumb pipeline)
- Consider WebGL (via regl or pixi.js) only if canvas is still slow at 3,600 nodes

### Three Modes

#### Mode 1: Discover ("How cool is this")

The default view. Full graph, all nodes visible, force simulation running.

- **Layout**: Force-directed with similarity-based attraction
- **Interaction**: Drag nodes, zoom/pan, click for detail panel
- **Legend**: Collection colors, click to toggle visibility
- **Search**: Filter by label/title/board text — matching nodes brighten, others fade
- **Fun feature**: "Shake" button that reheats the simulation so everything bobbles

This is essentially what exists today, but with images instead of dots.

#### Mode 2: Outliers ("Explore the weirdos")

Activated via toolbar button. Highlights unusual items.

- **Sort/filter by isolation score**: Slider to control "weirdness threshold"
- **Visual treatment**: Outliers glow (pulsing animation), non-outliers fade to 20% opacity
- **Bridge nodes**: Nodes connecting different clusters get a distinct ring (gold)
- **"Lonely items" list**: Sidebar showing the most isolated items as a scrollable
  thumbnail grid, sorted by isolation score descending
- **Suggested actions**: "This doesn't belong anywhere" → flag for removal;
  "This could be its own theme" → seed a new collection from it + neighbors

#### Mode 3: Curate ("Focus on a collection")

Activated by clicking a collection in the legend (or toolbar dropdown).

- **Isolation view**: Only shows the selected collection's items + optionally their
  nearest uncategorized neighbors (toggle: "Show nearby uncategorized")
- **Layout**: Re-runs force simulation with just the filtered set for tighter grouping
- **Sub-clusters**: Within the collection, show internal groupings
  (e.g., within "CB: Kitchen": white kitchens, dark kitchens, rustic kitchens)
  as labeled regions or subtle background halos
- **Selection tools**:
  - Click to select/deselect individual items
  - Lasso select (click-drag on empty space draws a freeform selection)
  - "Select cluster" button to select all items in a sub-cluster
- **Tray**: Selected items drop into a tray at the bottom of the screen
  - Shows selected thumbnails as a horizontal strip
  - Count display: "12 of 80 selected"
  - Actions: "Keep selected (remove rest)", "Remove selected", "Export selection"
- **Result**: The final curated set — Leslie's actual top picks per theme
- **Export**: Save selection as a new collection in the DB (via POST to
  the Inspirations server's existing collection endpoints if `meta.api_base` is set,
  or export as JSON file for offline import)

### Toolbar

Persistent across all modes. Left-aligned items:

```
[Discover] [Outliers] [Curate ▾]  |  Search: [________]  |  3,661 items  10,924 links  14 clusters
```

- Mode buttons are radio-style (one active at a time)
- "Curate ▾" shows dropdown of collections (displays name, uses stable ID internally)
- Search is always available

### Detail Panel (Right Sidebar)

Slides in on node click. Shows:
- Full-size image (loaded from `image_url` or remote fallback)
- Title, board, source
- Collection membership badges
- AI summary
- All labels as chips
- Nearest neighbors as thumbnail strip (clickable to navigate)
- Isolation score bar
- "Open original" link (source_url — Pinterest/Facebook)
- In Curate mode: "Select" / "Remove" buttons

### Tooltip (Hover)

- Thumbnail preview (larger than node, ~160px)
- Title
- Collection name
- Top 5 labels

## CLI Integration [ALL NEW — none of this exists yet]

### New subcommand: `inspirations explore`

```bash
# Export + serve in one step
python3 -m inspirations explore \
  --similarity-threshold 0.72 \
  --max-neighbors 6 \
  --clusters auto \
  --port 8080

# Export a single collection for focused curation (by collection ID)
python3 -m inspirations explore \
  --collection-id coll_abc123 \
  --include-neighbors 20 \
  --port 8080
```

This:
1. Checks that `asset_embeddings` table has rows (warns if empty, suggests running
   `ai embed` first)
2. Runs the export (same logic as `export_clusters.py`)
3. Writes JSON to `tools/cluster_data.json`
4. Starts `serve_explorer.py`
5. Opens the browser to `http://localhost:8080/`

### Write-back from Curate mode [FUTURE — lowest priority]

When Leslie/Jim finishes curating in Mode 3 and clicks "Save selection":

- **If `meta.api_base` is set**: POST to Inspirations server's existing collection
  management endpoints
- **If standalone**: Export selection as JSON file. A future `inspirations curate --import`
  command would consume this file and update the DB. This command does not exist yet.

## File Changes

| File | Status | Action | Description |
|------|--------|--------|-------------|
| `tools/cluster_explorer.html` | EXISTS | Rewrite | Image nodes, three modes, canvas renderer |
| `tools/export_clusters.py` | EXISTS | Update | Fix DB path default, add outlier scores, source URLs, image paths, `--collection-id` filter, `--serve` flag |
| `tools/serve_explorer.py` | NEW | Create | ~40-line HTTP server for local image + JSON serving |
| `src/inspirations/cli.py` | EXISTS | Update | Add `explore` subcommand |
| `src/inspirations/server.py` | EXISTS | Update | Add CORS headers if needed for cross-origin explorer |

## Implementation Priority

1. **`serve_explorer.py`** — minimum to get images loading in the browser
2. **`export_clusters.py` fixes** — correct DB path, add image paths, outlier scores
3. **`cluster_explorer.html` rewrite: Mode 1 (Discover)** with image nodes — the wow factor
4. **Mode 3 (Curate)** with selection tools — the actual workflow Leslie needs
5. **Mode 2 (Outliers)** — nice to have, can come later
6. **Canvas renderer** — only if SVG is too slow at 3,600 nodes (test first)
7. **CLI `explore` subcommand** — convenience wrapper, not essential early
8. **Write-back from Curate mode** — last, since collection editing via web UI works today
