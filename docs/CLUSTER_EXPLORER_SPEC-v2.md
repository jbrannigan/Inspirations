# Cluster Explorer - Implementation Spec v2

> Document type: implementation roadmap.
> Scope: cluster exploration for curation and removal of weak/outlier choices.
> This version resolves remaining spec issues found in prior review.

## 1. Goal

Provide a fast visual tool to:

1. Discover semantic groupings of inspiration assets.
2. Identify outliers and weak fits.
3. Curate a tighter collection shortlist.

Primary audience: non-technical curators using visual review, not raw embeddings.

## 2. Current State

Existing artifacts:

- `tools/export_clusters.py` (exists, partial)
- `tools/cluster_explorer.html` (exists, partial)

Missing artifacts:

- `tools/serve_explorer.py` (new)
- CLI integration in `src/inspirations/cli.py` (new)

## 3. Hard Prerequisites

Before export:

1. Assets imported (`inspirations import ...`)
2. AI tagging run (`inspirations ai tag ...`)
3. Embeddings generated (`inspirations ai embed ...`)
4. Thumbnails generated (`inspirations thumbs ...`)

If embeddings are missing, export must:

- Continue with embedded assets only.
- Print explicit counts for skipped assets.

## 4. Canonical Paths And Defaults

- Active DB default: `data/inspirations.sqlite`
- Cluster JSON default output: `tools/cluster_data.json`
- Explorer HTML path: `tools/cluster_explorer.html`

All command examples in this spec must use `data/inspirations.sqlite`.

## 5. Export Script Contract (`tools/export_clusters.py`)

### 5.1 Required CLI

- `--db` (default: `data/inspirations.sqlite`)
- `--out` (default: `tools/cluster_data.json`)
- `--similarity-threshold` (default: `0.72`)
- `--max-neighbors` (default: `6`)
- `--clusters` (`auto|none|<int>`, default: `auto`)
- `--collection-id` (optional, stable collection ID)
- `--include-neighbors` (optional int, default: `15` when `--collection-id` is set; otherwise `0`)
- `--api-base` (optional URL, e.g. `http://minime.local:8000`)
- `--serve` (optional bool; if set, starts `serve_explorer.py` after export)

Note: `--collection-id` is the only supported collection selector. Do not add a name-based selector.

### 5.2 Required Node Fields

Each node must include:

- `id`
- `title`
- `board`
- `source`
- `source_url`
- `collections` (display names)
- `collection_ids` (stable IDs)
- `labels`
- `summary`
- `thumb_url_local` (project-relative path under `store/` when available)
- `image_url_local` (project-relative path under `store/` when available)
- `image_url_remote` (from original source URL when available)
- `cluster`
- `is_centroid`
- `neighbor_count`
- `isolation_score`
- `bridge_score`
- `is_outlier`

`source_url` is required as a field, but may be an empty string when no openable origin URL exists.

Source URL derivation rules:

1. If `assets.source_ref` starts with `http://` or `https://`, use it as-is.
2. If source is Pinterest and `source_ref` is a non-URL pin token, normalize to:
   `https://www.pinterest.com/pin/{source_ref}`.
3. If source is Facebook and `source_ref` is synthetic (e.g., `facebook://saved/...`) or non-openable, set `source_url` to empty string.
4. For scan/local-only assets, set `source_url` to empty string.

### 5.3 Outlier Metrics

- `isolation_score`: `1 - mean(similarity to k nearest neighbors)`, where `k=min(5, neighbor_count)` and score clamped to `[0,1]`.
- `bridge_score`: `cross_cluster_edge_count / total_edge_count` (0 when no edges).
- `is_outlier`: top 10% by `isolation_score` among exported nodes.

### 5.4 Path Rules

Local media paths must be normalized to project-relative paths, never absolute filesystem paths.

Current DB reality (observed): most rows store absolute paths like
`/Users/.../Projects/Inspirations/store/...`, with a minority already relative (`store/...`).
Exporter must normalize both forms.

- Allowed local prefixes: `store/`
- Normalize absolute `/.../store/...` to `store/...`
- If a local path is outside project root, drop it from output.
- Remote fallback remains in `image_url_remote`.

## 6. Output Schema (`cluster_data.json`)

```jsonc
{
  "meta": {
    "source_db": "data/inspirations.sqlite",
    "exported_at": "2026-02-14T21:00:00Z",
    "total_assets": 3661,
    "total_links": 10924,
    "clusters": 14,
    "similarity_threshold": 0.72,
    "project_root": "/Users/minime/Projects/Inspirations",
    "api_base": "http://minime.local:8000", // optional
    "collection_id": "4910b982-a939-41bc-a6eb-d4d6ab108616", // optional
    "collection_name": "CB: Kitchen", // optional
    "include_neighbors": 15, // optional
    "focus_count": 80, // optional
    "nearby_count": 15 // optional
  },
  "nodes": [
    {
      "id": "asset_abc123",
      "title": "White oak kitchen with brass hardware",
      "board": "Kitchen Remodel",
      "source": "pinterest",
      "source_url": "https://pinterest.com/pin/123456",
      "collections": ["CB: Kitchen"],
      "collection_ids": ["4910b982-a939-41bc-a6eb-d4d6ab108616"],
      "labels": ["kitchen", "white oak", "brass"],
      "summary": "Bright kitchen with white oak cabinets...",
      "thumb_url_local": "store/thumbs/abc123_240.jpg",
      "image_url_local": "store/originals/abc123.jpg",
      "image_url_remote": "https://i.pinimg.com/...",
      "cluster": 3,
      "is_centroid": false,
      "neighbor_count": 4,
      "isolation_score": 0.34,
      "bridge_score": 0.0,
      "is_outlier": false,
      "in_focus_collection": true, // true if selected by --collection-id
      "is_nearby_context": false // true if added by --include-neighbors
    }
  ],
  "links": [
    { "source": "asset_abc123", "target": "asset_def456", "similarity": 0.84 }
  ]
}
```

## 7. Serving Contract (`tools/serve_explorer.py`)

### 7.1 Required CLI

- `--port` (default `8080`)
- `--data` (default `tools/cluster_data.json`)
- `--project-root` (default current repo root)

Unsupported mode (explicit): opening `tools/cluster_explorer.html` directly via `file://`.
Supported mode: served over HTTP via `serve_explorer.py`.

### 7.2 Security Rules (mandatory)

Server must not trust `meta.project_root` from JSON for filesystem access.

Allowed routes:

1. `/` -> `tools/cluster_explorer.html`
2. `/cluster_data.json` -> file from `--data`
3. `/store/...` -> files under `<project-root>/store/` only

Denied:

- Any `..` traversal.
- Any non-allowlisted top-level path.
- Any absolute path request.

This prevents accidental exposure of repo files, secrets, or home-directory content.

### 7.3 Caching

- Static images under `/store/...`: `Cache-Control: max-age=3600`
- HTML/JSON: `Cache-Control: no-store`

## 8. Image Resolution Priority In Explorer

When rendering a node:

1. If `meta.api_base` exists: use `{api_base}/media/{asset_id}?kind=thumb`
2. Else use `thumb_url_local` via local server (`/store/...`)
3. Else use `{api_base}/media/{asset_id}?kind=original` if `api_base` exists
4. Else use `image_url_local`
5. Else use `image_url_remote`
6. Else show fallback placeholder

## 9. Explorer UI Scope (`tools/cluster_explorer.html`)

### Phase 1 (required)

- Mode 1: Discover
- Mode 2: Outliers (basic threshold and highlight)
- Global Grid/Graph view switch in review modes (Discover, Outliers, Duplicates).
- Node detail panel
- Collection filter legend
- Search by title/labels/board
- Collection-scoped review defaults to focus-only; nearby context is optional via explicit toggle.
- In Graph view, focused/visible items should auto-center in the viewport after scope/filter/mode changes.
- Minimal action path for outliers in collection-focused runs:
  - If `--collection-id` is active and `meta.api_base` is set, detail panel supports
    `Remove from this collection` using existing endpoint:
    `POST /api/collections/{collection_id}/items/remove` with `asset_ids`.
  - If no API is configured, explorer can export a `remove_candidates.json` list.

### Phase 2 (optional)

- Mode 3 advanced curation tools (lasso, tray, batch actions)
- Write-back shortcuts

## 10. Renderer Decision Rule

Avoid contradictory requirements:

- Default implementation: SVG first.
- Add Canvas only if perf tests fail threshold:
  - dataset >= 3000 nodes
  - interaction FPS < 30 on baseline test machine

If threshold fails, implement canvas renderer as a follow-up.

## 11. Write-Back Scope

Not required for initial release.

If implemented later:

- Use existing collection endpoints only.
- Use stable `collection_ids`.
- No new DB tables required for first write-back slice.

## 12. CLI Integration (optional convenience)

Future command:

```bash
python3 -m inspirations explore \
  --db data/inspirations.sqlite \
  --out tools/cluster_data.json \
  --port 8080 \
  --collection-id <id> \
  --include-neighbors 20
```

Behavior:

1. Validate embeddings exist.
2. Run cluster export.
3. Start `serve_explorer.py --data <out>`.
4. Open browser.

This is convenience only; standalone script workflow remains supported.

## 13. Acceptance Criteria

1. Export runs successfully against `data/inspirations.sqlite` with no path edits.
2. Explorer loads JSON automatically when served.
3. When run via `serve_explorer.py` (`http://localhost:8080`), images render without CORS errors.
4. No filesystem paths outside `store/` are web-accessible from explorer server.
5. Outlier mode can filter/highlight by `isolation_score`.
6. `--collection-id` export returns only selected collection plus optional neighbors.
7. In Graph view, changing focus scope re-centers the currently focused item set.
8. `file://` opening is documented as unsupported to prevent false bug reports.

## 14. Implementation Priority

1. `serve_explorer.py` with strict allowlist routing
2. `export_clusters.py` schema/flag updates
3. Explorer Mode 1 + Outliers using new schema
4. Optional CLI `inspirations explore`
5. Optional advanced curate mode and write-back
