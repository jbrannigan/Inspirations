#!/usr/bin/env python3
"""
Export cluster data from Inspirations DB for the Cluster Explorer.

This script produces the v2 cluster JSON schema documented in:
  docs/CLUSTER_EXPLORER_SPEC-v2.md
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = "data/inspirations.sqlite"
DEFAULT_OUT = "tools/cluster_data.json"


def is_http_url(value: str) -> bool:
    lower = (value or "").strip().lower()
    return lower.startswith("http://") or lower.startswith("https://")


def normalize_store_path(raw_path: str, project_root: Path) -> str:
    value = (raw_path or "").strip()
    if not value or is_http_url(value):
        return ""

    root_resolved = project_root.resolve()
    p = Path(value)

    if p.is_absolute():
        try:
            rel = p.resolve().relative_to(root_resolved)
        except ValueError:
            return ""
        rel_str = rel.as_posix()
    else:
        rel_str = p.as_posix().lstrip("./")

    if rel_str.startswith("store/"):
        return rel_str
    return ""


def derive_source_url(source: str, source_ref: str) -> str:
    ref = (source_ref or "").strip()
    src = (source or "").strip().lower()

    if is_http_url(ref):
        return ref

    if src == "pinterest" and ref:
        token = ref
        if token.startswith("pin://"):
            token = token[len("pin://") :]
        token = token.strip("/")
        if token:
            return f"https://www.pinterest.com/pin/{token}"

    if src in {"facebook", "scan"}:
        return ""
    return ""


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def try_import_numpy():
    try:
        import numpy as np  # type: ignore

        return np
    except Exception:
        return None


def pick_k_silhouette(vectors: list[list[float]], k_range: tuple[int, int] = (3, 20)) -> int | None:
    try:
        from sklearn.cluster import KMeans  # type: ignore
        from sklearn.metrics import silhouette_score  # type: ignore
        import numpy as np  # type: ignore
    except Exception:
        print("scikit-learn not installed; auto-k disabled.")
        return None

    if len(vectors) < 4:
        return None

    X = np.array(vectors, dtype=float)
    k_min, k_max = k_range
    upper = min(k_max, len(X) - 1)
    if upper < k_min:
        return None

    best_k = k_min
    best_score = -1.0
    for k in range(k_min, upper + 1):
        km = KMeans(n_clusters=k, n_init=10, random_state=42, max_iter=200)
        labels = km.fit_predict(X)
        score = silhouette_score(X, labels, sample_size=min(2000, len(X)))
        if score > best_score:
            best_score = float(score)
            best_k = k
    print(f"Selected k={best_k} (silhouette={best_score:.3f})")
    return best_k


def cluster_vectors(vectors: list[list[float]], ids: list[str], k: str) -> tuple[dict[str, int], set[str]]:
    if not vectors:
        return {}, set()
    if k == "none" or len(vectors) < 4:
        return {asset_id: 0 for asset_id in ids}, set()

    try:
        from sklearn.cluster import KMeans  # type: ignore
        import numpy as np  # type: ignore
    except Exception:
        print("scikit-learn not available; using a single cluster.")
        return {asset_id: 0 for asset_id in ids}, set()

    X = np.array(vectors, dtype=float)

    if k == "auto":
        chosen_k = pick_k_silhouette(vectors) or 8
    else:
        chosen_k = int(k)
    chosen_k = max(1, min(chosen_k, len(X) - 1 if len(X) > 1 else 1))

    km = KMeans(n_clusters=chosen_k, n_init=10, random_state=42, max_iter=300)
    labels = km.fit_predict(X)
    assignments = {ids[i]: int(labels[i]) for i in range(len(ids))}

    centroids: set[str] = set()
    for cluster_idx in range(chosen_k):
        member_indices = np.where(labels == cluster_idx)[0]
        if len(member_indices) == 0:
            continue
        center = km.cluster_centers_[cluster_idx]
        cluster_points = X[member_indices]
        dists = np.linalg.norm(cluster_points - center, axis=1)
        local_min = int(np.argmin(dists))
        centroids.add(ids[int(member_indices[local_min])])

    return assignments, centroids


def load_assets(conn: sqlite3.Connection) -> dict[str, dict]:
    assets: dict[str, dict] = {}
    for row in conn.execute(
        """
        select
          a.id,
          a.title,
          a.board,
          a.source,
          a.source_ref,
          a.image_url,
          a.stored_path,
          a.thumb_path,
          a.ai_summary,
          a.media_status
        from assets a
        where a.media_status='image'
        """
    ):
        assets[str(row["id"])] = dict(row)
    return assets


def load_labels(conn: sqlite3.Connection, allowed_ids: set[str]) -> dict[str, list[str]]:
    labels_map: dict[str, list[str]] = defaultdict(list)
    for row in conn.execute("select asset_id, label from asset_labels"):
        asset_id = str(row["asset_id"])
        if asset_id in allowed_ids:
            labels_map[asset_id].append(str(row["label"]))
    return labels_map


def load_collections(conn: sqlite3.Connection, allowed_ids: set[str]) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    names_map: dict[str, list[str]] = defaultdict(list)
    ids_map: dict[str, list[str]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()
    for row in conn.execute(
        """
        select
          ci.asset_id as asset_id,
          c.id as collection_id,
          c.name as collection_name
        from collection_items ci
        join collections c on c.id = ci.collection_id
        order by c.name collate nocase asc
        """
    ):
        asset_id = str(row["asset_id"])
        if asset_id not in allowed_ids:
            continue
        collection_id = str(row["collection_id"])
        key = (asset_id, collection_id)
        if key in seen:
            continue
        seen.add(key)
        names_map[asset_id].append(str(row["collection_name"]))
        ids_map[asset_id].append(collection_id)
    return names_map, ids_map


def load_embeddings(conn: sqlite3.Connection, allowed_ids: set[str]) -> dict[str, list[float]]:
    embeddings: dict[str, list[float]] = {}
    for row in conn.execute(
        """
        select asset_id, vector_json
        from asset_embeddings
        where asset_id in (select id from assets where media_status='image')
        """
    ):
        asset_id = str(row["asset_id"])
        if asset_id not in allowed_ids:
            continue
        try:
            vector = json.loads(row["vector_json"])
        except Exception:
            continue
        if isinstance(vector, list) and vector:
            try:
                embeddings[asset_id] = [float(v) for v in vector]
            except Exception:
                continue
    return embeddings


def select_collection_scope(
    conn: sqlite3.Connection,
    *,
    valid_ids: list[str],
    embeddings: dict[str, list[float]],
    collection_id: str,
    include_neighbors: int,
) -> list[str]:
    selected_raw = {
        str(row["asset_id"])
        for row in conn.execute("select asset_id from collection_items where collection_id=?", (collection_id,))
    }
    selected = [asset_id for asset_id in valid_ids if asset_id in selected_raw]

    if not selected:
        print(f"Collection {collection_id} has no embedded image assets to export.")
        return []

    if include_neighbors <= 0:
        return selected

    valid_set = set(valid_ids)
    selected_set = set(selected)
    candidates = [asset_id for asset_id in valid_ids if asset_id in valid_set and asset_id not in selected_set]
    if not candidates:
        return selected

    np = try_import_numpy()
    best_scores: dict[str, float] = {}

    if np is not None:
        all_vectors = np.array([embeddings[asset_id] for asset_id in valid_ids], dtype=float)
        norms = np.linalg.norm(all_vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        all_norm = all_vectors / norms

        idx_by_id = {asset_id: i for i, asset_id in enumerate(valid_ids)}
        sel_idx = [idx_by_id[asset_id] for asset_id in selected]
        cand_idx = [idx_by_id[asset_id] for asset_id in candidates]

        sim_matrix = all_norm[cand_idx] @ all_norm[sel_idx].T
        max_scores = sim_matrix.max(axis=1)
        for i, score in enumerate(max_scores):
            best_scores[candidates[i]] = float(score)
    else:
        print("numpy not available; neighbor inclusion will use slower python scoring.")
        for candidate_id in candidates:
            candidate_vec = embeddings[candidate_id]
            best = -1.0
            for selected_id in selected:
                sim = cosine_similarity(candidate_vec, embeddings[selected_id])
                if sim > best:
                    best = sim
            best_scores[candidate_id] = best

    ranked = sorted(best_scores.items(), key=lambda item: item[1], reverse=True)
    neighbor_ids = [asset_id for asset_id, _ in ranked[:include_neighbors]]
    return selected + neighbor_ids


def compute_similarity_edges(
    *,
    export_ids: list[str],
    embeddings: dict[str, list[float]],
    assignments: dict[str, int],
    sim_threshold: float,
    max_neighbors: int,
) -> tuple[list[tuple[str, str, float]], dict[str, int]]:
    if len(export_ids) < 2:
        return [], {asset_id: 0 for asset_id in export_ids}

    if max_neighbors <= 0:
        return [], {asset_id: 0 for asset_id in export_ids}

    np = try_import_numpy()
    neighbor_counts: dict[str, int] = defaultdict(int)
    edge_scores: dict[tuple[str, str], float] = {}

    if np is not None:
        vectors = np.array([embeddings[asset_id] for asset_id in export_ids], dtype=float)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        vectors = vectors / norms
        sim = vectors @ vectors.T
        n = len(export_ids)
        per_node_scan = max_neighbors * 4

        for i in range(n):
            row = sim[i]
            row[i] = -1.0
            candidates = np.where(row >= sim_threshold)[0]
            if len(candidates) == 0:
                continue
            ordered = sorted(candidates, key=lambda idx: float(row[idx]), reverse=True)[:per_node_scan]
            for j in ordered:
                if i == j:
                    continue
                a_idx, b_idx = (i, j) if i < j else (j, i)
                key = (export_ids[a_idx], export_ids[b_idx])
                score = float(row[j])
                prev = edge_scores.get(key)
                if prev is None or score > prev:
                    edge_scores[key] = score
    else:
        if len(export_ids) <= 800:
            for i in range(len(export_ids)):
                a_id = export_ids[i]
                a_vec = embeddings[a_id]
                for j in range(i + 1, len(export_ids)):
                    b_id = export_ids[j]
                    score = cosine_similarity(a_vec, embeddings[b_id])
                    if score >= sim_threshold:
                        edge_scores[(a_id, b_id)] = score
        else:
            members: dict[int, list[str]] = defaultdict(list)
            for asset_id in export_ids:
                members[assignments.get(asset_id, 0)].append(asset_id)
            max_cluster_size = max(len(ids) for ids in members.values())
            if max_cluster_size > 800:
                raise RuntimeError(
                    "numpy is required for large exports. "
                    "Install scikit-learn in the active venv (it includes numpy), "
                    "or run a smaller collection-scoped export."
                )
            print("numpy not available; using cluster-local edge generation for this dataset size.")
            for ids in members.values():
                for i in range(len(ids)):
                    a_id = ids[i]
                    a_vec = embeddings[a_id]
                    for j in range(i + 1, len(ids)):
                        b_id = ids[j]
                        score = cosine_similarity(a_vec, embeddings[b_id])
                        if score >= sim_threshold:
                            edge_scores[(a_id, b_id)] = score

    ranked_edges = sorted(edge_scores.items(), key=lambda item: item[1], reverse=True)
    links: list[tuple[str, str, float]] = []
    for (a_id, b_id), score in ranked_edges:
        if neighbor_counts[a_id] >= max_neighbors or neighbor_counts[b_id] >= max_neighbors:
            continue
        neighbor_counts[a_id] += 1
        neighbor_counts[b_id] += 1
        links.append((a_id, b_id, round(float(score), 4)))

    for asset_id in export_ids:
        neighbor_counts.setdefault(asset_id, 0)
    return links, dict(neighbor_counts)


def compute_outlier_metrics(
    *,
    export_ids: list[str],
    links: list[tuple[str, str, float]],
    assignments: dict[str, int],
) -> tuple[dict[str, float], dict[str, float], set[str]]:
    adjacency: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for a_id, b_id, score in links:
        adjacency[a_id].append((b_id, score))
        adjacency[b_id].append((a_id, score))

    isolation_scores: dict[str, float] = {}
    bridge_scores: dict[str, float] = {}

    for asset_id in export_ids:
        neighbors = adjacency.get(asset_id, [])
        if not neighbors:
            isolation = 1.0
            bridge = 0.0
        else:
            top_scores = sorted((score for _, score in neighbors), reverse=True)
            k = min(5, len(top_scores))
            mean_top = sum(top_scores[:k]) / k
            isolation = max(0.0, min(1.0, 1.0 - mean_top))

            cross_cluster = 0
            my_cluster = assignments.get(asset_id, 0)
            for neighbor_id, _ in neighbors:
                if assignments.get(neighbor_id, 0) != my_cluster:
                    cross_cluster += 1
            bridge = cross_cluster / len(neighbors)

        isolation_scores[asset_id] = round(isolation, 4)
        bridge_scores[asset_id] = round(bridge, 4)

    if not export_ids:
        return isolation_scores, bridge_scores, set()

    outlier_count = max(1, math.ceil(len(export_ids) * 0.10))
    ranked = sorted(export_ids, key=lambda asset_id: isolation_scores.get(asset_id, 0.0), reverse=True)
    outliers = set(ranked[:outlier_count])
    return isolation_scores, bridge_scores, outliers


def export_clusters(
    *,
    db_path: str,
    out_path: str,
    sim_threshold: float,
    max_neighbors: int,
    clusters: str,
    collection_id: str,
    include_neighbors: int,
    api_base: str,
    project_root: Path,
) -> dict:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        assets = load_assets(conn)
        total_assets = len(assets)
        print(f"Loaded {total_assets} image assets.")

        labels_map = load_labels(conn, set(assets))
        collection_names, collection_ids = load_collections(conn, set(assets))
        embeddings = load_embeddings(conn, set(assets))

        embedded_ids = [asset_id for asset_id in assets if asset_id in embeddings]
        skipped_embeddings = total_assets - len(embedded_ids)
        print(f"Loaded embeddings for {len(embedded_ids)} assets; skipped {skipped_embeddings} without embeddings.")

        if len(embedded_ids) < 2:
            raise RuntimeError("Not enough embedded assets to export clusters.")

        vectors = [embeddings[asset_id] for asset_id in embedded_ids]
        assignments, centroids = cluster_vectors(vectors, embedded_ids, clusters)

        if collection_id:
            scoped_ids = select_collection_scope(
                conn,
                valid_ids=embedded_ids,
                embeddings=embeddings,
                collection_id=collection_id,
                include_neighbors=include_neighbors,
            )
            print(
                f"Collection scope enabled: {collection_id}; exporting {len(scoped_ids)} assets "
                f"(include_neighbors={include_neighbors})."
            )
        else:
            scoped_ids = embedded_ids

        if len(scoped_ids) < 1:
            raise RuntimeError("No assets matched the requested export scope.")

        links, neighbor_counts = compute_similarity_edges(
            export_ids=scoped_ids,
            embeddings=embeddings,
            assignments=assignments,
            sim_threshold=sim_threshold,
            max_neighbors=max_neighbors,
        )

        isolation_scores, bridge_scores, outlier_ids = compute_outlier_metrics(
            export_ids=scoped_ids,
            links=links,
            assignments=assignments,
        )

        nodes = []
        for asset_id in scoped_ids:
            asset = assets[asset_id]
            names = collection_names.get(asset_id) or ["Uncategorized"]
            ids = collection_ids.get(asset_id) or []
            thumb_local = normalize_store_path(asset.get("thumb_path") or "", project_root)
            image_local = normalize_store_path(asset.get("stored_path") or "", project_root)
            source_url = derive_source_url(asset.get("source") or "", asset.get("source_ref") or "")
            image_remote = (asset.get("image_url") or "").strip()

            nodes.append(
                {
                    "id": asset_id,
                    "title": asset.get("title") or asset_id[:32],
                    "board": asset.get("board") or "",
                    "source": asset.get("source") or "",
                    "source_url": source_url,
                    "collections": names,
                    "collection_ids": ids,
                    "labels": labels_map.get(asset_id, [])[:12],
                    "summary": asset.get("ai_summary") or "",
                    "thumb_url_local": thumb_local,
                    "image_url_local": image_local,
                    "image_url_remote": image_remote,
                    "cluster": assignments.get(asset_id, 0),
                    "is_centroid": asset_id in centroids,
                    "neighbor_count": int(neighbor_counts.get(asset_id, 0)),
                    "isolation_score": isolation_scores.get(asset_id, 1.0),
                    "bridge_score": bridge_scores.get(asset_id, 0.0),
                    "is_outlier": asset_id in outlier_ids,
                }
            )

        payload = {
            "meta": {
                "source_db": db_path,
                "exported_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                "total_assets": len(nodes),
                "total_links": len(links),
                "clusters": len({assignments.get(asset_id, 0) for asset_id in scoped_ids}),
                "similarity_threshold": sim_threshold,
                "project_root": str(project_root.resolve()),
                "api_base": api_base or "",
                "collection_id": collection_id or "",
                "include_neighbors": include_neighbors,
            },
            "nodes": nodes,
            "links": [
                {"source": source, "target": target, "similarity": similarity}
                for source, target, similarity in links
            ],
        }

        out_file = Path(out_path)
        if not out_file.is_absolute():
            out_file = Path.cwd() / out_file
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        print(
            f"Exported cluster data: nodes={len(nodes)} links={len(links)} "
            f"clusters={payload['meta']['clusters']} out={out_file}"
        )
        return payload
    finally:
        conn.close()


def launch_server(*, out_path: str, project_root: Path) -> None:
    script = project_root / "tools" / "serve_explorer.py"
    cmd = [
        sys.executable,
        str(script),
        "--data",
        out_path,
        "--project-root",
        str(project_root),
    ]
    print("Starting Cluster Explorer server on http://127.0.0.1:8080")
    subprocess.run(cmd, check=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export cluster data for Cluster Explorer")
    parser.add_argument("--db", default=DEFAULT_DB, help=f"Path to DB (default: {DEFAULT_DB})")
    parser.add_argument("--out", default=DEFAULT_OUT, help=f"Output JSON path (default: {DEFAULT_OUT})")
    parser.add_argument(
        "--similarity-threshold",
        type=float,
        default=0.72,
        help="Minimum cosine similarity for edges (default: 0.72)",
    )
    parser.add_argument(
        "--max-neighbors",
        type=int,
        default=6,
        help="Maximum graph edges per node (default: 6)",
    )
    parser.add_argument(
        "--clusters",
        default="auto",
        help='Cluster count: "auto", "none", or integer (default: auto)',
    )
    parser.add_argument("--collection-id", default="", help="Optional collection id to export")
    parser.add_argument(
        "--include-neighbors",
        type=int,
        default=None,
        help="Neighbors to include when --collection-id is used (default: 15 with collection, else 0)",
    )
    parser.add_argument("--api-base", default="", help="Optional API base (for explorer actions/media)")
    parser.add_argument("--serve", action="store_true", help="Start explorer server after export")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = (Path.cwd() / out_path).resolve()

    include_neighbors = args.include_neighbors
    if include_neighbors is None:
        include_neighbors = 15 if args.collection_id else 0

    api_base = (args.api_base or "").strip().rstrip("/")
    if args.clusters not in {"auto", "none"}:
        try:
            int(args.clusters)
        except ValueError:
            print('Invalid --clusters value; use "auto", "none", or integer.', file=sys.stderr)
            return 2

    try:
        export_clusters(
            db_path=args.db,
            out_path=str(out_path),
            sim_threshold=args.similarity_threshold,
            max_neighbors=args.max_neighbors,
            clusters=args.clusters,
            collection_id=(args.collection_id or "").strip(),
            include_neighbors=max(0, int(include_neighbors)),
            api_base=api_base,
            project_root=REPO_ROOT,
        )
    except Exception as exc:
        print(f"Export failed: {exc}", file=sys.stderr)
        return 1

    if args.serve:
        launch_server(out_path=str(out_path), project_root=REPO_ROOT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
