from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from .db import Db


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_assets(
    db: Db,
    *,
    q: str = "",
    source: str = "",
    collection_id: str = "",
    limit: int = 200,
    offset: int = 0,
) -> list[dict[str, Any]]:
    clauses = []
    params: list[Any] = []
    if source:
        clauses.append("a.source = ?")
        params.append(source)
    if q:
        clauses.append("(a.title like ? or a.description like ? or a.board like ? or a.source_ref like ?)")
        qv = f"%{q}%"
        params += [qv, qv, qv, qv]
    if collection_id:
        clauses.append("ci.collection_id = ?")
        params.append(collection_id)
    where = "where " + " and ".join(clauses) if clauses else ""

    sql = f"""
    select a.id, a.source, a.source_ref, a.title, a.description, a.board,
           a.created_at, a.imported_at, a.image_url, a.stored_path, a.thumb_path
    from assets a
    left join collection_items ci on ci.asset_id = a.id
    {where}
    order by a.imported_at desc
    limit ? offset ?;
    """
    params += [limit, offset]
    rows = db.query(sql, tuple(params))
    return [dict(r) for r in rows]


def list_collections(db: Db) -> list[dict[str, Any]]:
    rows = db.query(
        "select id, name, description, created_at, updated_at from collections order by updated_at desc"
    )
    out = []
    for r in rows:
        count = db.query_value("select count(*) from collection_items where collection_id=?", (r["id"],))
        d = dict(r)
        d["count"] = count
        out.append(d)
    return out


def create_collection(db: Db, *, name: str, description: str = "") -> dict[str, Any]:
    cid = str(uuid.uuid4())
    now = _now_iso()
    db.exec(
        "insert into collections (id, name, description, created_at, updated_at) values (?, ?, ?, ?, ?)",
        (cid, name, description or None, now, now),
    )
    return {"id": cid, "name": name, "description": description or "", "created_at": now, "updated_at": now, "count": 0}


def add_items_to_collection(db: Db, *, collection_id: str, asset_ids: list[str]) -> int:
    if not asset_ids:
        return 0
    pos = db.query_value(
        "select coalesce(max(position), 0) from collection_items where collection_id=?",
        (collection_id,),
    )
    rows = []
    for i, aid in enumerate(asset_ids, start=1):
        rows.append((collection_id, aid, int(pos) + i))
    db.executemany(
        "insert or ignore into collection_items (collection_id, asset_id, position) values (?, ?, ?)",
        rows,
    )
    db.exec("update collections set updated_at=? where id=?", (_now_iso(), collection_id))
    return len(rows)


def set_collection_order(db: Db, *, collection_id: str, asset_ids: list[str]) -> None:
    for idx, aid in enumerate(asset_ids):
        db.exec(
            "update collection_items set position=? where collection_id=? and asset_id=?",
            (idx + 1, collection_id, aid),
        )
    db.exec("update collections set updated_at=? where id=?", (_now_iso(), collection_id))


def remove_item_from_collection(db: Db, *, collection_id: str, asset_id: str) -> None:
    db.exec("delete from collection_items where collection_id=? and asset_id=?", (collection_id, asset_id))
    db.exec("update collections set updated_at=? where id=?", (_now_iso(), collection_id))


def list_collection_items(db: Db, *, collection_id: str) -> list[dict[str, Any]]:
    rows = db.query(
        """
        select a.id, a.source, a.source_ref, a.title, a.description, a.board,
               a.created_at, a.imported_at, a.image_url, a.stored_path, a.thumb_path,
               ci.position
        from collection_items ci
        join assets a on a.id = ci.asset_id
        where ci.collection_id=?
        order by ci.position asc;
        """,
        (collection_id,),
    )
    return [dict(r) for r in rows]


def list_annotations(db: Db, *, asset_id: str) -> list[dict[str, Any]]:
    rows = db.query(
        "select id, asset_id, x, y, text, created_at, updated_at from annotations where asset_id=? order by created_at asc",
        (asset_id,),
    )
    return [dict(r) for r in rows]


def create_annotation(db: Db, *, asset_id: str, x: float, y: float, text: str = "") -> dict[str, Any]:
    ann_id = str(uuid.uuid4())
    now = _now_iso()
    db.exec(
        "insert into annotations (id, asset_id, x, y, text, created_at, updated_at) values (?, ?, ?, ?, ?, ?, ?)",
        (ann_id, asset_id, x, y, text or None, now, now),
    )
    return {"id": ann_id, "asset_id": asset_id, "x": x, "y": y, "text": text, "created_at": now, "updated_at": now}


def update_annotation(db: Db, *, annotation_id: str, x: float | None = None, y: float | None = None, text: str | None = None) -> None:
    sets = []
    params: list[Any] = []
    if x is not None:
        sets.append("x=?")
        params.append(x)
    if y is not None:
        sets.append("y=?")
        params.append(y)
    if text is not None:
        sets.append("text=?")
        params.append(text)
    sets.append("updated_at=?")
    params.append(_now_iso())
    params.append(annotation_id)
    db.exec(f"update annotations set {', '.join(sets)} where id=?", tuple(params))


def delete_annotation(db: Db, *, annotation_id: str) -> None:
    db.exec("delete from annotations where id=?", (annotation_id,))

