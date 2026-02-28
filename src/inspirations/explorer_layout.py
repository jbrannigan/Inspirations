from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

from .db import Db


CLUSTER_PALETTE = [
    "#b8860b",
    "#8b6914",
    "#6b8e23",
    "#7b68ee",
    "#cd853f",
    "#2e8b57",
    "#b05050",
    "#4682b4",
    "#d2691e",
    "#708090",
    "#9b59b6",
    "#1abc9c",
    "#e67e22",
    "#c0392b",
    "#7f8c8d",
]


def _table_exists(db: Db, table_name: str) -> bool:
    row = db.query_value(
        "select 1 from sqlite_master where type='table' and name=? limit 1",
        (table_name,),
    )
    return bool(row)


def _assets_has_column(db: Db, column_name: str) -> bool:
    rows = db.query("pragma table_info(assets)")
    return any(str(r["name"]) == column_name for r in rows)


def _cache_key(asset_ids: list[str]) -> str:
    joined = ",".join(sorted(asset_ids))
    return hashlib.sha256(joined.encode()).hexdigest()[:16]


def _load_embeddings(
    db: Db,
    collection_id: str | None,
    *,
    include_hidden: bool = False,
) -> tuple[list[str], list[list[float]]]:
    joins: list[str] = ["join assets a on a.id = ae.asset_id"]
    clauses: list[str] = []
    params: list[str] = []

    if collection_id:
        joins.append("join collection_items ci on ci.asset_id = ae.asset_id")
        clauses.append("ci.collection_id = ?")
        params.append(collection_id)

    if not include_hidden:
        if _assets_has_column(db, "triage_status"):
            clauses.append("(a.triage_status is null or a.triage_status != 'hidden')")
        hidden_col_id = None
        if _table_exists(db, "collections"):
            hidden_col_id = db.query_value(
                "select id from collections where lower(name)='hidden' limit 1"
            )
        if (
            hidden_col_id
            and collection_id != hidden_col_id
            and _table_exists(db, "collection_items")
        ):
            clauses.append(
                "a.id not in (select asset_id from collection_items where collection_id = ?)"
            )
            params.append(str(hidden_col_id))

    where_sql = f"where {' and '.join(clauses)}" if clauses else ""
    join_sql = " ".join(joins)
    rows = db.query(
        f"select ae.asset_id, ae.vector_json from asset_embeddings ae {join_sql} {where_sql} order by ae.asset_id",
        tuple(params),
    )

    ids: list[str] = []
    vectors: list[list[float]] = []
    for row in rows:
        try:
            vec = json.loads(row["vector_json"])
        except Exception:
            continue
        ids.append(row["asset_id"])
        vectors.append(vec)
    return ids, vectors


def _load_asset_meta(db: Db, asset_ids: list[str]) -> dict[str, dict]:
    if not asset_ids:
        return {}
    placeholders = ",".join("?" * len(asset_ids))
    rows = db.query(
        f"select id, title, thumb_path from assets where id in ({placeholders})",
        tuple(asset_ids),
    )
    return {r["id"]: {"title": r["title"] or "", "thumb_path": r["thumb_path"] or ""} for r in rows}


def _load_cluster_labels(
    db: Db, cluster_members: dict[int, list[str]]
) -> dict[int, str]:
    result: dict[int, str] = {}
    for cid, member_ids in cluster_members.items():
        if not member_ids:
            result[cid] = f"Cluster {cid}"
            continue
        placeholders = ",".join("?" * len(member_ids))
        rows = db.query(
            f"""
            select label, count(*) as cnt
            from asset_labels
            where asset_id in ({placeholders})
            group by label
            order by cnt desc
            limit 3
            """,
            tuple(member_ids),
        )
        if rows:
            result[cid] = " / ".join(r["label"] for r in rows)
        else:
            result[cid] = f"Cluster {cid}"
    return result


def _project_umap(vectors: list[list[float]]) -> list[list[float]] | None:
    try:
        import umap  # type: ignore
        import numpy as np  # type: ignore
    except Exception:
        return None
    X = np.array(vectors, dtype=float)
    n_neighbors = min(15, len(vectors) - 1)
    reducer = umap.UMAP(n_components=3, random_state=42, n_neighbors=n_neighbors)
    return reducer.fit_transform(X).tolist()


def _project_pca(vectors: list[list[float]]) -> list[list[float]] | None:
    n = len(vectors)
    if n == 0:
        return []
    d = len(vectors[0]) if vectors[0] else 0
    try:
        from sklearn.decomposition import PCA  # type: ignore
        import numpy as np  # type: ignore
    except Exception:
        # Pure-Python fallback when sklearn/numpy are unavailable:
        # center vectors and project on the top-variance dimensions.
        if d == 0:
            return [[0.0, 0.0, 0.0] for _ in range(n)]
        mean = [sum(v[j] for v in vectors) / n for j in range(d)]
        var = [sum((v[j] - mean[j]) ** 2 for v in vectors) / n for j in range(d)]
        ranked = sorted(range(d), key=lambda j: var[j], reverse=True)
        top = ranked[:3]
        while len(top) < 3:
            top.append(-1)
        out: list[list[float]] = []
        for v in vectors:
            out.append([
                (v[top[0]] - mean[top[0]]) if top[0] >= 0 else 0.0,
                (v[top[1]] - mean[top[1]]) if top[1] >= 0 else 0.0,
                (v[top[2]] - mean[top[2]]) if top[2] >= 0 else 0.0,
            ])
        return out
    X = np.array(vectors, dtype=float)
    n_components = min(3, X.shape[0], X.shape[1])
    coords = PCA(n_components=n_components, random_state=42).fit_transform(X)
    if coords.shape[1] < 3:
        import numpy as np  # type: ignore  # noqa: F811
        pad = np.zeros((coords.shape[0], 3 - coords.shape[1]))
        coords = np.hstack([coords, pad])
    return coords.tolist()


def _project_random(n: int) -> list[list[float]]:
    rng = random.Random(42)
    return [[rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1)] for _ in range(n)]


def _normalize_coords(coords: list[list[float]]) -> list[list[float]]:
    if not coords:
        return coords
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    zs = [c[2] for c in coords]
    x_range = max(xs) - min(xs) or 1.0
    y_range = max(ys) - min(ys) or 1.0
    z_range = max(zs) - min(zs) or 1.0
    scale = 30.0 / max(x_range, y_range, z_range)
    x_mid = (max(xs) + min(xs)) / 2
    y_mid = (max(ys) + min(ys)) / 2
    z_mid = (max(zs) + min(zs)) / 2
    return [
        [(c[0] - x_mid) * scale, (c[1] - y_mid) * scale, (c[2] - z_mid) * scale]
        for c in coords
    ]


def _cluster_coords(coords: list[list[float]]) -> list[int]:
    n = len(coords)
    if n < 4:
        return [0] * n
    try:
        from sklearn.cluster import KMeans  # type: ignore
        from sklearn.metrics import silhouette_score  # type: ignore
        import numpy as np  # type: ignore
    except Exception:
        return [0] * n

    X = np.array(coords, dtype=float)
    k_max = min(15, n - 1)
    if k_max < 2:
        return [0] * n

    best_k = 2
    best_score = -1.0
    for k in range(2, k_max + 1):
        km = KMeans(n_clusters=k, n_init=10, random_state=42, max_iter=200)
        labels = km.fit_predict(X)
        try:
            score = float(silhouette_score(X, labels, sample_size=min(2000, n)))
        except Exception:
            continue
        if score > best_score:
            best_score = score
            best_k = k

    km = KMeans(n_clusters=best_k, n_init=10, random_state=42, max_iter=300)
    return [int(lbl) for lbl in km.fit_predict(X)]


def compute_layout(
    db: Db,
    data_dir: Path,
    collection_id: str | None = None,
    method: str = "umap",
    refresh: bool = False,
    include_hidden: bool = False,
) -> dict:
    data_dir.mkdir(parents=True, exist_ok=True)

    ids, vectors = _load_embeddings(db, collection_id, include_hidden=include_hidden)
    if not ids:
        return {"nodes": [], "clusters": []}

    cache_file = data_dir / f"{_cache_key(ids)}.json"
    if not refresh and cache_file.exists():
        try:
            return json.loads(cache_file.read_text())
        except Exception:
            pass

    # Project to 3D
    coords: list[list[float]] | None = None
    if method == "umap":
        coords = _project_umap(vectors)
    if coords is None:
        coords = _project_pca(vectors)
    if coords is None:
        coords = _project_random(len(ids))

    coords = _normalize_coords(coords)

    # Cluster in 3D space
    labels = _cluster_coords(coords)
    num_clusters = max(labels) + 1 if labels else 1

    cluster_members: dict[int, list[str]] = {i: [] for i in range(num_clusters)}
    for idx, asset_id in enumerate(ids):
        cluster_members[labels[idx]].append(asset_id)

    asset_meta = _load_asset_meta(db, ids)
    label_strings = _load_cluster_labels(db, cluster_members)

    nodes = []
    for idx, asset_id in enumerate(ids):
        meta = asset_meta.get(asset_id, {})
        thumb_url = f"/media/{asset_id}?kind=thumb" if meta.get("thumb_path") else ""
        nodes.append(
            {
                "id": asset_id,
                "x": round(coords[idx][0], 4),
                "y": round(coords[idx][1], 4),
                "z": round(coords[idx][2], 4),
                "cluster_id": labels[idx],
                "thumb_url": thumb_url,
                "title": meta.get("title", ""),
            }
        )

    clusters = []
    for cid in range(num_clusters):
        member_indices = [i for i, lbl in enumerate(labels) if lbl == cid]
        if not member_indices:
            continue
        cx = sum(coords[i][0] for i in member_indices) / len(member_indices)
        cy = sum(coords[i][1] for i in member_indices) / len(member_indices)
        cz = sum(coords[i][2] for i in member_indices) / len(member_indices)
        clusters.append(
            {
                "id": cid,
                "label": label_strings.get(cid, f"Cluster {cid}"),
                "centroid": [round(cx, 4), round(cy, 4), round(cz, 4)],
                "color": CLUSTER_PALETTE[cid % len(CLUSTER_PALETTE)],
                "count": len(member_indices),
            }
        )

    result = {"nodes": nodes, "clusters": clusters}
    try:
        cache_file.write_text(json.dumps(result))
    except Exception:
        pass
    return result
