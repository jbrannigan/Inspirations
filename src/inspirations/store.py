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
    board: str = "",
    label: str = "",
    collection_id: str = "",
    limit: int = 200,
    offset: int = 0,
) -> list[dict[str, Any]]:
    clauses = []
    params: list[Any] = []
    joins: list[str] = []
    if source:
        sources = [s.strip() for s in source.split(",") if s.strip()]
        clauses.append("a.source in (%s)" % ",".join(["?"] * len(sources)))
        params.extend(sources)
    if board:
        boards = [s.strip() for s in board.split(",") if s.strip()]
        clauses.append("a.board in (%s)" % ",".join(["?"] * len(boards)))
        params.extend(boards)
    if label:
        labels = [s.strip() for s in label.split(",") if s.strip()]
        joins.append("left join asset_labels al on al.asset_id = a.id")
        clauses.append("al.label in (%s)" % ",".join(["?"] * len(labels)))
        params.extend(labels)
    if q:
        if not any(j.startswith("left join asset_labels") for j in joins):
            joins.append("left join asset_labels al on al.asset_id = a.id")
        clauses.append(
            "(a.title like ? or a.description like ? or a.board like ? or a.source_ref like ? or a.notes like ? or a.ai_summary like ? or al.label like ?)"
        )
        qv = f"%{q}%"
        params += [qv, qv, qv, qv, qv, qv, qv]
    if collection_id:
        joins.append("join collection_items ci on ci.asset_id = a.id")
        clauses.append("ci.collection_id = ?")
        params.append(collection_id)
    where = "where " + " and ".join(clauses) if clauses else ""
    join_sql = "\n    " + "\n    ".join(joins) if joins else ""

    sql = f"""
    select distinct a.id, a.source, a.source_ref, a.title, a.description, a.board, a.notes,
           coalesce(
             (select ai.summary from asset_ai ai where ai.asset_id=a.id order by ai.created_at desc limit 1),
             a.ai_summary
           ) as ai_summary,
           (select ai.json from asset_ai ai where ai.asset_id=a.id order by ai.created_at desc limit 1) as ai_json,
           (select ai.model from asset_ai ai where ai.asset_id=a.id order by ai.created_at desc limit 1) as ai_model,
           (select ai.provider from asset_ai ai where ai.asset_id=a.id order by ai.created_at desc limit 1) as ai_provider,
           (select ai.created_at from asset_ai ai where ai.asset_id=a.id order by ai.created_at desc limit 1) as ai_created_at,
           a.created_at, a.imported_at, a.image_url, a.stored_path, a.thumb_path
    from assets a
    {join_sql}
    {where}
    order by a.imported_at desc
    limit ? offset ?;
    """
    params += [limit, offset]
    rows = db.query(sql, tuple(params))
    return [dict(r) for r in rows]


def list_facets(db: Db) -> dict[str, Any]:
    sources = db.query("select source, count(*) as n from assets group by source order by n desc")
    boards = db.query(
        "select board, count(*) as n from assets where board is not null and board != '' group by board order by n desc limit 50"
    )
    labels = db.query(
        "select label, count(*) as n from asset_labels group by label order by n desc limit 50"
    )
    return {
        "sources": [dict(r) for r in sources],
        "boards": [dict(r) for r in boards],
        "labels": [dict(r) for r in labels],
    }


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


def remove_items_from_collection(db: Db, *, collection_id: str, asset_ids: list[str]) -> int:
    if not asset_ids:
        return 0
    unique_ids: list[str] = []
    seen: set[str] = set()
    for aid in asset_ids:
        aid_s = str(aid or "").strip()
        if not aid_s or aid_s in seen:
            continue
        seen.add(aid_s)
        unique_ids.append(aid_s)
    if not unique_ids:
        return 0

    placeholders = ",".join(["?"] * len(unique_ids))
    params = [collection_id, *unique_ids]
    removed = db.query_value(
        f"select count(*) from collection_items where collection_id=? and asset_id in ({placeholders})",
        tuple(params),
    )
    db.exec(
        f"delete from collection_items where collection_id=? and asset_id in ({placeholders})",
        tuple(params),
    )
    db.exec("update collections set updated_at=? where id=?", (_now_iso(), collection_id))
    return int(removed or 0)


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


def delete_collection(db: Db, *, collection_id: str) -> None:
    db.exec("delete from collections where id=?", (collection_id,))


def delete_assets(db: Db, *, asset_ids: list[str]) -> dict[str, Any]:
    unique_ids: list[str] = []
    seen: set[str] = set()
    for aid in asset_ids:
        aid_s = str(aid or "").strip()
        if not aid_s or aid_s in seen:
            continue
        seen.add(aid_s)
        unique_ids.append(aid_s)
    if not unique_ids:
        return {"deleted": 0, "paths": []}

    placeholders = ",".join(["?"] * len(unique_ids))
    rows = db.query(
        f"select id, stored_path, thumb_path from assets where id in ({placeholders})",
        tuple(unique_ids),
    )
    paths: list[str] = []
    for r in rows:
        if r["stored_path"]:
            paths.append(r["stored_path"])
        if r["thumb_path"]:
            paths.append(r["thumb_path"])

    db.exec(f"delete from assets where id in ({placeholders})", tuple(unique_ids))
    return {"deleted": len(rows), "paths": paths}


def update_asset_notes(db: Db, *, asset_id: str, notes: str) -> None:
    db.exec("update assets set notes=? where id=?", (notes or None, asset_id))


def list_tray(db: Db) -> list[dict[str, Any]]:
    rows = db.query(
        """
        select a.id, a.source, a.source_ref, a.title, a.description, a.board,
               a.created_at, a.imported_at, a.image_url, a.stored_path, a.thumb_path,
               t.added_at
        from tray_items t
        join assets a on a.id = t.asset_id
        order by t.added_at asc;
        """
    )
    return [dict(r) for r in rows]


def add_to_tray(db: Db, *, asset_ids: list[str]) -> int:
    if not asset_ids:
        return 0
    rows = []
    now = _now_iso()
    for aid in asset_ids:
        rows.append((aid, now))
    db.executemany("insert or ignore into tray_items (asset_id, added_at) values (?, ?)", rows)
    return len(rows)


def remove_from_tray(db: Db, *, asset_ids: list[str]) -> None:
    if not asset_ids:
        return
    for aid in asset_ids:
        db.exec("delete from tray_items where asset_id=?", (aid,))


def clear_tray(db: Db) -> None:
    db.exec("delete from tray_items")


def create_collection_from_tray(db: Db, *, name: str, description: str = "") -> dict[str, Any]:
    col = create_collection(db, name=name, description=description)
    items = db.query("select asset_id from tray_items order by added_at asc")
    asset_ids = [r["asset_id"] for r in items]
    add_items_to_collection(db, collection_id=col["id"], asset_ids=asset_ids)
    clear_tray(db)
    return col

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
