from __future__ import annotations

import re
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any

from .db import Db, infer_collection_provenance
from .feature_vectors import EXPLORER_LEGACY_SPECS, build_legacy_facet_memberships
from .title_workflow import enrich_assets_with_title_info

_SCAN_REF_RE = re.compile(r"^scan://([a-f0-9]{64})(?:#p(\d+))?$", re.IGNORECASE)
_SCAN_DOC_RE = re.compile(r"\s-\sdoc\s+(\d+)(?:\s+p(\d+))?$", re.IGNORECASE)
_SCAN_DOC_SUFFIX_RE = re.compile(r"\s-\sdoc\s+\d+(?:\s+p\d+)?\s*$", re.IGNORECASE)
_SCAN_AUTOGEN_NUMERIC_PREFIX_RE = re.compile(
    r"^(?:img|image|scan|photo|document|doc|file|dsc|pxl)[\s_-]*\d+(?:[\s_-]*\d+)*$",
    re.IGNORECASE,
)
_SCAN_AUTOGEN_HASHLIKE_RE = re.compile(r"^[a-f0-9]{20,}$", re.IGNORECASE)
_SCAN_AUTOGEN_EXACT = {
    "scan",
    "scans",
    "scan upload",
    "scan uploads",
    "uploaded scan",
    "uploaded file",
    "batch import",
    "inbox import",
    "document",
    "documents",
    "new document",
    "untitled",
    "image",
    "images",
    "photo",
    "photos",
    "pdf",
    "file",
    "files",
}
_SCAN_AUTOGEN_TOKENS = {
    "scan",
    "scans",
    "upload",
    "uploads",
    "uploaded",
    "batch",
    "import",
    "inbox",
    "document",
    "documents",
    "doc",
    "docs",
    "file",
    "files",
    "image",
    "images",
    "img",
    "photo",
    "photos",
    "picture",
    "pictures",
    "page",
    "pages",
    "pdf",
    "new",
    "untitled",
}
_MAX_SCAN_DOC_COLLAPSE_PAGES = 6
_COLLECTION_PROVENANCE_LABELS = {
    "human_curated": "Human-curated",
    "source_mirror": "Mirrored source",
    "ai_derived_representative": "AI-derived representative",
    "workflow_review": "Workflow review",
    "workflow_cohort": "Workflow cohort",
    "system_hidden": "System",
}
_COLLECTION_PROVENANCE_BADGES = {
    "source_mirror": "Mirror",
    "ai_derived_representative": "AI set",
    "workflow_review": "Review",
    "workflow_cohort": "Workflow",
    "system_hidden": "System",
}
_COLLECTION_INTENTS = {"working", "shared"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def collection_provenance_label(kind: str) -> str:
    key = str(kind or "").strip()
    return _COLLECTION_PROVENANCE_LABELS.get(key, "Collection")


def collection_provenance_badge(kind: str) -> str:
    key = str(kind or "").strip()
    return _COLLECTION_PROVENANCE_BADGES.get(key, "")


def _collection_workflow_variant(record: dict[str, Any]) -> tuple[str, str, str]:
    kind = str(record.get("provenance_kind") or "").strip()
    name = str(record.get("name") or "").strip()
    if kind != "workflow_cohort":
        return (
            collection_provenance_label(kind),
            collection_provenance_badge(kind),
            str(record.get("provenance_note") or "").strip(),
        )
    lower = name.lower()
    if lower.endswith("(cleaned)"):
        return (
            "Working cohort",
            "Working",
            "Cleaned working subset kept for active use.",
        )
    if lower.endswith("(excluded)"):
        return (
            "Excluded cohort",
            "Excluded",
            "Excluded provenance subset preserved for reversibility.",
        )
    return (
        "Imported cohort",
        "Raw",
        "Raw imported batch preserved for provenance.",
    )


def decorate_collection_record(record: dict[str, Any]) -> dict[str, Any]:
    kind = str(record.get("provenance_kind") or "").strip() or "human_curated"
    record["provenance_kind"] = kind
    record["provenance_note"] = str(record.get("provenance_note") or "").strip()
    label, badge, note = _collection_workflow_variant(record)
    record["provenance_label"] = label
    record["provenance_badge"] = badge
    if note:
        record["provenance_note"] = note
    record["curator"] = str(record.get("curator") or "").strip()
    intent = str(record.get("intent") or "").strip().lower()
    if intent not in _COLLECTION_INTENTS:
        intent = "working"
    record["intent"] = intent
    record["shared_actor_id"] = str(record.get("shared_actor_id") or "").strip()
    record["shared_actor_name"] = str(record.get("shared_actor_name") or "").strip()
    shared_actor_ids = record.get("shared_actor_ids") or []
    if not isinstance(shared_actor_ids, list):
        shared_actor_ids = []
    shared_actor_names = record.get("shared_actor_names") or []
    if not isinstance(shared_actor_names, list):
        shared_actor_names = []
    record["shared_actor_ids"] = [str(v).strip() for v in shared_actor_ids if str(v).strip()]
    record["shared_actor_names"] = [str(v).strip() for v in shared_actor_names if str(v).strip()]
    return record


def _normalize_collection_intent(intent: str) -> str:
    text = str(intent or "").strip().lower()
    return text if text in _COLLECTION_INTENTS else "working"


def _normalize_shared_actor_ids(shared_actor_id: str = "", shared_actor_ids: list[str] | tuple[str, ...] | None = None) -> list[str]:
    values: list[str] = []
    first = str(shared_actor_id or "").strip()
    if first:
        values.append(first)
    for raw in list(shared_actor_ids or []):
        text = str(raw or "").strip()
        if text:
            values.append(text)
    out: list[str] = []
    seen: set[str] = set()
    for actor_id in values:
        if actor_id in seen:
            continue
        seen.add(actor_id)
        out.append(actor_id)
    return out


def _validate_shared_collection_actor_ids(db: Db, actor_ids: list[str]) -> list[dict[str, Any]]:
    ids = [str(v).strip() for v in actor_ids if str(v).strip()]
    if not ids:
        return []
    placeholders = ",".join(["?"] * len(ids))
    rows = db.query(
        f"select id, name, role from actors where id in ({placeholders})",
        tuple(ids),
    )
    by_id = {str(r["id"]): dict(r) for r in rows}
    missing = [actor_id for actor_id in ids if actor_id not in by_id]
    if missing:
        raise ValueError("shared collaborator not found")
    ordered = [by_id[actor_id] for actor_id in ids]
    if any(str(row.get("role") or "").strip().lower() == "owner" for row in ordered):
        raise ValueError("shared collaborator must not be an owner")
    return ordered


def _replace_collection_shares(db: Db, *, collection_id: str, actor_ids: list[str]) -> None:
    db.exec("delete from collection_shares where collection_id=?", (collection_id,))
    rows = [
        (str(uuid.uuid4()), collection_id, actor_id, _now_iso())
        for actor_id in actor_ids
    ]
    if rows:
        db.executemany(
            """
            insert into collection_shares (id, collection_id, actor_id, created_at)
            values (?, ?, ?, ?)
            """,
            rows,
        )


def _csv_values(raw: str) -> list[str]:
    return [s.strip() for s in (raw or "").split(",") if s.strip()]


_LEGACY_CLASSIFICATION_AXES = {axis_name for axis_name, _label, _values, _weight in EXPLORER_LEGACY_SPECS}


def _classification_filter_values(raw: object) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, (list, tuple, set)):
        values: list[str] = []
        for item in raw:
            values.extend(_classification_filter_values(item))
        return values
    text = str(raw or "").strip()
    if not text:
        return []
    return [text]


def _parse_classification_facets(
    *,
    classification_axis: str = "",
    classification_value: str = "",
    classification_filters: object = None,
) -> dict[str, list[str]]:
    facets: dict[str, list[str]] = {}

    def add(axis: str, values: list[str]) -> None:
        clean_axis = str(axis or "").strip().lower()
        if not clean_axis:
            return
        clean_values = [str(value or "").strip() for value in values if str(value or "").strip()]
        if clean_axis not in facets:
            facets[clean_axis] = []
        for value in clean_values:
            if value not in facets[clean_axis]:
                facets[clean_axis].append(value)

    add(classification_axis, _csv_values(classification_value))
    for raw in _classification_filter_values(classification_filters):
        if ":" in raw:
            axis, value = raw.split(":", 1)
        elif "=" in raw:
            axis, value = raw.split("=", 1)
        else:
            axis, value = raw, ""
        add(axis, _csv_values(value))

    return facets


def _apply_legacy_facet_filter(
    db: Db,
    clauses: list[str],
    params: list[Any],
    legacy_facets: dict[str, list[str]],
) -> None:
    if not legacy_facets:
        return

    memberships = build_legacy_facet_memberships(db)
    matching_ids: list[str] = []
    for asset_id, axes in memberships.items():
        matched = True
        for axis_name, wanted_values in legacy_facets.items():
            asset_values = axes.get(axis_name, set())
            if wanted_values:
                if not asset_values.intersection(wanted_values):
                    matched = False
                    break
            elif not asset_values:
                matched = False
                break
        if matched:
            matching_ids.append(asset_id)

    if not matching_ids:
        clauses.append("1 = 0")
        return

    matching_ids = sorted(set(matching_ids))
    if len(matching_ids) > 500:
        db.exec("drop table if exists _legacy_facet_filter")
        db.exec("create temp table _legacy_facet_filter (asset_id text primary key)")
        db.executemany(
            "insert into _legacy_facet_filter (asset_id) values (?)",
            [(asset_id,) for asset_id in matching_ids],
        )
        clauses.append("a.id in (select asset_id from _legacy_facet_filter)")
    else:
        placeholders = ",".join(["?"] * len(matching_ids))
        clauses.append(f"a.id in ({placeholders})")
        params.extend(matching_ids)


def _scan_ref_parts(source_ref: str) -> tuple[str, int | None] | None:
    m = _SCAN_REF_RE.match((source_ref or "").strip())
    if not m:
        return None
    sha = str(m.group(1) or "").strip().lower()
    page_idx = int(m.group(2)) if m.group(2) else None
    return (sha, page_idx)


def _scan_doc_parts(title: str) -> tuple[int | None, int | None]:
    m = _SCAN_DOC_RE.search((title or "").strip())
    if not m:
        return (None, None)
    doc_idx = int(m.group(1)) if m.group(1) else None
    doc_page = int(m.group(2)) if m.group(2) else None
    return (doc_idx, doc_page)


def _scan_doc_key_from_values(source_ref: str, title: str) -> tuple[str, int] | None:
    ref = _scan_ref_parts(source_ref)
    if not ref:
        return None
    sha, _ = ref
    doc_idx, _ = _scan_doc_parts(title)
    return (sha, int(doc_idx or 1))


def _scan_doc_page_from_values(source_ref: str, title: str) -> int:
    _, title_page = _scan_doc_parts(title)
    ref = _scan_ref_parts(source_ref)
    ref_page = ref[1] if ref else None
    return int(title_page or ref_page or 1)


def _scan_doc_group_has_explicit_pages(rows: list[dict[str, Any]] | list[Any]) -> bool:
    if len(rows) <= 1:
        return False
    pages: list[int] = []
    for row in rows:
        title = str(row.get("title") or "") if isinstance(row, dict) else str(row["title"] or "")
        _doc_idx, doc_page = _scan_doc_parts(title)
        if doc_page is None:
            return False
        pages.append(int(doc_page))
    if len(set(pages)) != len(rows):
        return False
    ordered = sorted(pages)
    return ordered == list(range(1, len(rows) + 1))


def _scan_doc_display_title(title: str) -> str:
    text = (title or "").strip()
    text = _SCAN_DOC_SUFFIX_RE.sub("", text).strip()
    if _looks_autogenerated_scan_title(text):
        return "Scanned inspiration"
    return text


def _looks_autogenerated_scan_title(title: str) -> bool:
    base = _SCAN_DOC_SUFFIX_RE.sub("", (title or "").strip()).strip()
    lowered = base.lower()
    if not lowered:
        return True
    normalized = re.sub(r"[_-]+", " ", lowered)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized:
        return True
    if normalized in _SCAN_AUTOGEN_EXACT:
        return True
    if _SCAN_AUTOGEN_NUMERIC_PREFIX_RE.match(lowered):
        return True
    compact_hex = re.sub(r"[^a-f0-9]", "", lowered)
    if compact_hex and _SCAN_AUTOGEN_HASHLIKE_RE.match(compact_hex):
        return True
    tokens = [t for t in re.split(r"[^a-z0-9]+", normalized) if t]
    if tokens and all(t.isdigit() or t in _SCAN_AUTOGEN_TOKENS for t in tokens):
        return True
    return False


def _unique_ids(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        v = str(value or "").strip()
        if not v or v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out


def _expand_scan_asset_ids(db: Db, asset_ids: list[str]) -> list[str]:
    unique_input_ids = _unique_ids(asset_ids)
    if not unique_input_ids:
        return []

    placeholders = ",".join(["?"] * len(unique_input_ids))
    rows = db.query(
        f"select id, source, source_ref, title from assets where id in ({placeholders})",
        tuple(unique_input_ids),
    )
    row_by_id: dict[str, dict[str, Any]] = {
        str(r["id"]): {
            "id": str(r["id"]),
            "source": str(r["source"] or ""),
            "source_ref": str(r["source_ref"] or ""),
            "title": str(r["title"] or ""),
        }
        for r in rows
    }

    expanded: list[str] = []
    seen_expanded: set[str] = set()
    scan_member_cache: dict[tuple[str, int], list[str]] = {}

    for aid in unique_input_ids:
        row = row_by_id.get(aid)
        if not row:
            continue
        source = str(row.get("source") or "").strip().lower()
        if source != "scan":
            if aid not in seen_expanded:
                seen_expanded.add(aid)
                expanded.append(aid)
            continue

        key = _scan_doc_key_from_values(str(row.get("source_ref") or ""), str(row.get("title") or ""))
        if not key:
            if aid not in seen_expanded:
                seen_expanded.add(aid)
                expanded.append(aid)
            continue

        members = scan_member_cache.get(key)
        if members is None:
            sha, _ = key
            candidates = db.query(
                "select id, source_ref, title from assets where source='scan' and source_ref like ?",
                (f"scan://{sha}%",),
            )
            members = _unique_ids(
                [
                    str(c["id"])
                    for c in candidates
                    if _scan_doc_key_from_values(str(c["source_ref"] or ""), str(c["title"] or "")) == key
                ]
            )
            if not members:
                members = [aid]
            elif len(members) > _MAX_SCAN_DOC_COLLAPSE_PAGES:
                # Large inferred scan-doc groups are ambiguous in this dataset;
                # keep item-level behavior instead of expanding to the whole group,
                # unless the stored titles explicitly encode page membership.
                member_rows = [
                    {
                        "id": str(c["id"]),
                        "source_ref": str(c["source_ref"] or ""),
                        "title": str(c["title"] or ""),
                    }
                    for c in candidates
                    if _scan_doc_key_from_values(str(c["source_ref"] or ""), str(c["title"] or "")) == key
                ]
                if not _scan_doc_group_has_explicit_pages(member_rows):
                    members = [aid]
            scan_member_cache[key] = members

        for member_id in members:
            if member_id in seen_expanded:
                continue
            seen_expanded.add(member_id)
            expanded.append(member_id)
    return expanded


def _collapse_scan_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []

    grouped: dict[tuple[Any, ...], dict[str, Any]] = {}
    ordered_keys: list[tuple[Any, ...]] = []
    for idx, row in enumerate(rows):
        source = str(row.get("source") or "").strip().lower()
        if source == "scan":
            doc_key = _scan_doc_key_from_values(str(row.get("source_ref") or ""), str(row.get("title") or ""))
            if doc_key:
                key = ("scan_doc", doc_key[0], int(doc_key[1]))
            else:
                key = ("asset", str(row.get("id") or ""))
        else:
            key = ("asset", str(row.get("id") or ""))
        if key not in grouped:
            grouped[key] = {"rows": [], "first_idx": idx}
            ordered_keys.append(key)
        grouped[key]["rows"].append(row)

    out: list[dict[str, Any]] = []
    for key in ordered_keys:
        bundle = grouped[key]
        group_rows = bundle["rows"]
        if key[0] != "scan_doc":
            out.append(dict(group_rows[0]))
            continue

        sorted_rows = sorted(
            group_rows,
            key=lambda r: (
                _scan_doc_page_from_values(str(r.get("source_ref") or ""), str(r.get("title") or "")),
                str(r.get("id") or ""),
            ),
        )
        member_ids = _unique_ids([str(r.get("id") or "") for r in sorted_rows])
        if len(member_ids) > _MAX_SCAN_DOC_COLLAPSE_PAGES and not _scan_doc_group_has_explicit_pages(sorted_rows):
            # Avoid over-collapsing very large inferred groups; expose items individually.
            for row in sorted_rows:
                item = dict(row)
                item["scan_group_member_ids"] = [str(item.get("id") or "")]
                item["scan_group_id"] = f"scan-doc://{key[1]}#d{key[2]}"
                item["scan_doc_index"] = int(key[2])
                item["scan_doc_pages"] = 1
                item["scan_doc_page"] = 1
                display_title = _scan_doc_display_title(str(item.get("title") or ""))
                if display_title:
                    item["title"] = display_title
                out.append(item)
            continue

        rep = dict(sorted_rows[0])
        rep["scan_group_member_ids"] = member_ids
        rep["scan_group_id"] = f"scan-doc://{key[1]}#d{key[2]}"
        rep["scan_doc_index"] = int(key[2])
        rep["scan_doc_pages"] = len(member_ids)
        rep["scan_doc_page"] = 1 if member_ids else None
        display_title = _scan_doc_display_title(str(rep.get("title") or ""))
        if display_title:
            rep["title"] = display_title

        if not str(rep.get("ai_summary") or "").strip():
            for row in sorted_rows:
                if str(row.get("ai_summary") or "").strip():
                    rep["ai_summary"] = row.get("ai_summary")
                    break
        if not str(rep.get("notes") or "").strip():
            for row in sorted_rows:
                if str(row.get("notes") or "").strip():
                    rep["notes"] = row.get("notes")
                    break
        out.append(rep)

    return out


def _latest_classification_run_id(db: Db, run_type: str) -> str:
    return str(
        db.query_value(
            "select id from classification_runs where run_type=? order by created_at desc limit 1",
            (str(run_type or "").strip(),),
        )
        or ""
    ).strip()


def _build_asset_filter(
    db: Db,
    *,
    ids: str = "",
    q: str = "",
    source: str = "",
    board: str = "",
    label: str = "",
    label_mode: str = "any",
    media_status: str = "",
    content_kind: str = "",
    creator: str = "",
    collection_id: str = "",
    review_status: str = "",
    triage_status: str = "",
    triage_actor: str = "",
    category: str = "",
    needs_annotation: bool = False,
    flagged_only: bool = False,
    tagged_only: bool = False,
    include_hidden: bool = False,
    classification_axis: str = "",
    classification_value: str = "",
    classification_filters: object = None,
    exclude_tracks: str = "",
    viewer_role: str = "",
    viewer_actor_id: str = "",
) -> tuple[str, str, list]:
    """Build WHERE and JOIN clauses for asset queries. Returns (join_sql, where, params)."""
    clauses: list[str] = []
    params: list[Any] = []
    join_params: list[Any] = []
    joins: list[str] = []
    if ids:
        id_list = [s.strip() for s in ids.split(",") if s.strip()]
        if id_list:
            # Use a temp table for large ID lists to avoid SQLite's expression
            # tree depth limit of 1000 (uncategorized rooms can have 2000+ IDs).
            if len(id_list) > 500:
                db.exec("drop table if exists _id_filter")
                db.exec("create temp table _id_filter (value text, exact int)")
                db.executemany(
                    "insert into _id_filter (value, exact) values (?, ?)",
                    [(p, 1 if len(p) > 8 else 0) for p in id_list],
                )
                clauses.append(
                    "("
                    "a.id in (select value from _id_filter where exact = 1)"
                    " or "
                    "substr(a.id, 1, 8) in (select value from _id_filter where exact = 0)"
                    ")"
                )
            else:
                full_ids = [v for v in id_list if len(v) > 8]
                short_ids = [v for v in id_list if len(v) <= 8]
                id_clauses: list[str] = []
                if full_ids:
                    placeholders = ",".join(["?"] * len(full_ids))
                    id_clauses.append(f"a.id in ({placeholders})")
                    params.extend(full_ids)
                if short_ids:
                    placeholders = ",".join(["?"] * len(short_ids))
                    id_clauses.append(f"substr(a.id, 1, 8) in ({placeholders})")
                    params.extend(short_ids)
                if id_clauses:
                    clauses.append("(" + " or ".join(id_clauses) + ")")
    if source:
        sources = [s.strip() for s in source.split(",") if s.strip()]
        clauses.append("a.source in (%s)" % ",".join(["?"] * len(sources)))
        params.extend(sources)
    if board:
        boards = [s.strip() for s in board.split(",") if s.strip()]
        board_conditions = []
        for b in boards:
            if b == "(uncategorized)":
                board_conditions.append("(a.board is null or a.board = '')")
            else:
                board_conditions.append("lower(a.board) = lower(?)")
                params.append(b)
        clauses.append("(" + " or ".join(board_conditions) + ")")
    if label:
        labels = [s.strip() for s in label.split(",") if s.strip()]
        if labels:
            if (label_mode or "").lower() == "all":
                placeholders = ",".join(["?"] * len(labels))
                clauses.append(
                    f"""
                    a.id in (
                      select asset_id
                      from asset_labels
                      where label in ({placeholders})
                      group by asset_id
                      having count(distinct label) = ?
                    )
                    """
                )
                params.extend(labels)
                params.append(len(set(labels)))
            else:
                joins.append("left join asset_labels al on al.asset_id = a.id")
                clauses.append("al.label in (%s)" % ",".join(["?"] * len(labels)))
                params.extend(labels)
    if media_status:
        statuses = [s.strip() for s in media_status.split(",") if s.strip()]
        clauses.append("a.media_status in (%s)" % ",".join(["?"] * len(statuses)))
        params.extend(statuses)
    if content_kind:
        kinds = [s.strip() for s in content_kind.split(",") if s.strip()]
        clauses.append("a.content_kind in (%s)" % ",".join(["?"] * len(kinds)))
        params.extend(kinds)
    if creator:
        creators = [s.strip() for s in creator.split(",") if s.strip()]
        clauses.append("a.creator_name in (%s)" % ",".join(["?"] * len(creators)))
        params.extend(creators)
    if category:
        categories = [s.strip() for s in category.split(",") if s.strip()]
        clauses.append("coalesce(a.category, 'home_design') in (%s)" % ",".join(["?"] * len(categories)))
        params.extend(categories)
    if q:
        if not any(j.startswith("left join asset_labels") for j in joins):
            joins.append("left join asset_labels al on al.asset_id = a.id")
        _search_fields = (
            "a.title", "a.description", "a.board", "a.seo_alt_text",
            "a.post_text", "a.notes", "a.ai_summary", "a.creator_name",
            "a.source_domain", "a.source_name", "al.label",
        )
        terms = q.split()
        for term in terms:
            field_ors = " or ".join(f"{f} like ?" for f in _search_fields)
            clauses.append(f"({field_ors})")
            tv = f"%{term}%"
            params += [tv] * len(_search_fields)
    collection_ids = _csv_values(collection_id)
    if collection_ids:
        joins.append("join collection_items ci on ci.asset_id = a.id")
        clauses.append("ci.collection_id in (%s)" % ",".join(["?"] * len(collection_ids)))
        params.extend(collection_ids)
        role = str(viewer_role or "").strip().lower()
        actor_id = str(viewer_actor_id or "").strip()
        if role != "owner":
            joins.append("join collections cfilter on cfilter.id = ci.collection_id")
            clauses.append("coalesce(cfilter.intent, 'working') = 'shared'")
            if actor_id:
                clauses.append(
                    "("
                    "coalesce(cfilter.shared_actor_id, '') = ? "
                    "or exists (select 1 from collection_shares csv where csv.collection_id = cfilter.id and csv.actor_id = ?)"
                    ")"
                )
                params.extend([actor_id, actor_id])
            else:
                clauses.append("1 = 0")
    classification_facets = _parse_classification_facets(
        classification_axis=classification_axis,
        classification_value=classification_value,
        classification_filters=classification_filters,
    )
    exclude_track_values = [s.strip() for s in str(exclude_tracks or "").split(",") if s.strip()]
    legacy_facets = {
        axis_name: values
        for axis_name, values in classification_facets.items()
        if axis_name in _LEGACY_CLASSIFICATION_AXES
    }
    _apply_legacy_facet_filter(db, clauses, params, legacy_facets)

    sql_facets = {
        axis_name: values
        for axis_name, values in classification_facets.items()
        if axis_name not in _LEGACY_CLASSIFICATION_AXES
    }
    for facet_idx, (axis_name, axis_values) in enumerate(sql_facets.items()):
        if axis_name == "track":
            run_id = _latest_classification_run_id(db, "track_gate")
            if not run_id:
                clauses.append("1 = 0")
                continue
            now_iso = datetime.now(timezone.utc).isoformat()
            value_sql = ""
            if axis_values:
                value_sql = " and coalesce(ato_f{idx}.axis_value, ata_f{idx}.track) in ({placeholders})".format(
                    idx=facet_idx,
                    placeholders=",".join(["?"] * len(axis_values)),
                )
            clauses.append(
                f"""
                exists (
                  select 1
                  from asset_track_assessments ata_f{facet_idx}
                  left join (
                    select ao.asset_id, ao.axis_value
                    from asset_overrides ao
                    join (
                      select asset_id, max(created_at) as max_created_at
                      from asset_overrides
                      where axis_name='track'
                        and operation='set'
                        and (expires_at is null or expires_at > ?)
                      group by asset_id
                    ) latest
                      on latest.asset_id = ao.asset_id
                     and latest.max_created_at = ao.created_at
                    where ao.axis_name='track'
                      and ao.operation='set'
                      and (ao.expires_at is null or ao.expires_at > ?)
                  ) ato_f{facet_idx} on ato_f{facet_idx}.asset_id = ata_f{facet_idx}.asset_id
                  where ata_f{facet_idx}.asset_id = a.id
                    and ata_f{facet_idx}.run_id = ?
                    {value_sql}
                )
                """
            )
            params.extend([now_iso, now_iso, run_id, *axis_values])
        else:
            run_id = _latest_classification_run_id(db, "multi_axis_inference")
            if not run_id:
                clauses.append("1 = 0")
                continue
            value_sql = ""
            if axis_values:
                value_sql = " and aam_f{idx}.axis_value in ({placeholders})".format(
                    idx=facet_idx,
                    placeholders=",".join(["?"] * len(axis_values)),
                )
            clauses.append(
                f"""
                exists (
                  select 1
                  from asset_axis_memberships aam_f{facet_idx}
                  where aam_f{facet_idx}.asset_id = a.id
                    and aam_f{facet_idx}.run_id = ?
                    and aam_f{facet_idx}.axis_name = ?
                    {value_sql}
                )
                """
            )
            params.extend([run_id, axis_name, *axis_values])
    if exclude_track_values:
        run_id = _latest_classification_run_id(db, "track_gate")
        if run_id:
            now_iso = datetime.now(timezone.utc).isoformat()
            joins.append("left join asset_track_assessments atx on atx.asset_id = a.id and atx.run_id = ?")
            join_params.append(run_id)
            joins.append(
                """
                left join (
                  select ao.asset_id, ao.axis_value
                  from asset_overrides ao
                  join (
                    select asset_id, max(created_at) as max_created_at
                    from asset_overrides
                    where axis_name='track'
                      and operation='set'
                      and (expires_at is null or expires_at > ?)
                    group by asset_id
                  ) latest
                    on latest.asset_id = ao.asset_id
                   and latest.max_created_at = ao.created_at
                  where ao.axis_name='track'
                    and ao.operation='set'
                    and (ao.expires_at is null or ao.expires_at > ?)
                ) otx on otx.asset_id = a.id
                """
            )
            join_params.extend([now_iso, now_iso])
            clauses.append(
                "coalesce(otx.axis_value, atx.track, '') not in (%s)"
                % ",".join(["?"] * len(exclude_track_values))
            )
            params.extend(exclude_track_values)
    if str(review_status or "").strip() == "irrelevant_discarded":
        run_id = _latest_classification_run_id(db, "track_gate")
        if run_id:
            now_iso = datetime.now(timezone.utc).isoformat()
            clauses.append(
                """
                (
                  a.triage_status = 'hidden'
                  or exists (
                    select 1
                    from asset_track_assessments atrs
                    left join (
                      select ao.asset_id, ao.axis_value
                      from asset_overrides ao
                      join (
                        select asset_id, max(created_at) as max_created_at
                        from asset_overrides
                        where axis_name='track'
                          and operation='set'
                          and (expires_at is null or expires_at > ?)
                        group by asset_id
                      ) latest
                        on latest.asset_id = ao.asset_id
                       and latest.max_created_at = ao.created_at
                      where ao.axis_name='track'
                        and ao.operation='set'
                        and (ao.expires_at is null or ao.expires_at > ?)
                    ) otrs on otrs.asset_id = atrs.asset_id
                    where atrs.asset_id = a.id
                      and atrs.run_id = ?
                      and coalesce(otrs.axis_value, atrs.track, '') = 'irrelevant'
                  )
                )
                """
            )
            params.extend([now_iso, now_iso, run_id])
        else:
            clauses.append("a.triage_status = 'hidden'")
    if triage_status:
        statuses = [s.strip() for s in triage_status.split(",") if s.strip()]
        if "pending" in statuses:
            others = [s for s in statuses if s != "pending"]
            if others:
                clauses.append(
                    "(a.triage_status is null or a.triage_status in (%s))"
                    % ",".join(["?"] * len(others))
                )
                params.extend(others)
            else:
                clauses.append("a.triage_status is null")
        else:
            clauses.append("a.triage_status in (%s)" % ",".join(["?"] * len(statuses)))
            params.extend(statuses)
    if triage_actor:
        actors = [s.strip() for s in triage_actor.split(",") if s.strip()]
        actor_clauses: list[str] = []
        if "manual" in actors:
            actor_clauses.append("coalesce(tl.actor, '') != 'ai-reel-triage'")
        explicit_actors = [actor for actor in actors if actor != "manual"]
        if explicit_actors:
            actor_clauses.append("tl.actor in (%s)" % ",".join(["?"] * len(explicit_actors)))
            params.extend(explicit_actors)
        if actor_clauses:
            clauses.append(
                """
                exists (
                  select 1
                  from triage_log tl
                  where tl.asset_id = a.id
                    and tl.id = (
                      select tl_latest.id
                      from triage_log tl_latest
                      where tl_latest.asset_id = a.id
                      order by tl_latest.created_at desc, tl_latest.id desc
                      limit 1
                    )
                    and (%s)
                )
                """
                % " or ".join(actor_clauses)
            )
    if needs_annotation:
        clauses.append("a.needs_annotation = 1")
    if flagged_only:
        clauses.append("a.flagged = 1")
    if tagged_only:
        clauses.append("a.tagged = 1")
    if not include_hidden:
        clauses.append("(a.triage_status is null or a.triage_status != 'hidden')")
    hidden_collection_id = db.query_value("select id from collections where lower(name)='hidden' limit 1")
    if hidden_collection_id and not include_hidden and hidden_collection_id not in set(collection_ids):
        clauses.append(
            "a.id not in (select asset_id from collection_items where collection_id = ?)"
        )
        params.append(hidden_collection_id)
    where = "where " + " and ".join(clauses) if clauses else ""
    join_sql = "\n    " + "\n    ".join(joins) if joins else ""
    return join_sql, where, [*join_params, *params]


def list_asset_ids(db: Db, **kwargs) -> list[str]:
    """Return only the IDs of assets matching the given filters (no limit/offset)."""
    join_sql, where, params = _build_asset_filter(db, **kwargs)
    sql = f"select distinct a.id from assets a {join_sql} {where}"
    return [r["id"] for r in db.query(sql, tuple(params))]


def list_assets(
    db: Db,
    *,
    ids: str = "",
    q: str = "",
    source: str = "",
    board: str = "",
    label: str = "",
    label_mode: str = "any",
    media_status: str = "",
    content_kind: str = "",
    creator: str = "",
    collection_id: str = "",
    review_status: str = "",
    triage_status: str = "",
    triage_actor: str = "",
    category: str = "",
    needs_annotation: bool = False,
    flagged_only: bool = False,
    tagged_only: bool = False,
    include_hidden: bool = False,
    classification_axis: str = "",
    classification_value: str = "",
    classification_filters: object = None,
    exclude_tracks: str = "",
    viewer_role: str = "",
    viewer_actor_id: str = "",
    limit: int = 200,
    offset: int = 0,
) -> list[dict[str, Any]]:
    join_sql, where, params = _build_asset_filter(
        db, ids=ids, q=q, source=source, board=board, label=label,
        label_mode=label_mode, media_status=media_status, content_kind=content_kind,
        creator=creator, collection_id=collection_id, review_status=review_status, triage_status=triage_status,
        triage_actor=triage_actor,
        category=category, needs_annotation=needs_annotation, flagged_only=flagged_only,
        tagged_only=tagged_only, include_hidden=include_hidden,
        classification_axis=classification_axis, classification_value=classification_value,
        classification_filters=classification_filters,
        exclude_tracks=exclude_tracks, viewer_role=viewer_role, viewer_actor_id=viewer_actor_id,
    )

    # Total count (same filters, no limit/offset). Collection-scoped views use
    # the same logical scan-document collapse as the grid, so the visible count
    # matches the number of cards the curator sees.
    if _csv_values(collection_id):
        total_rows = [
            dict(r)
            for r in db.query(
                f"""
                select distinct a.id, a.source, a.source_ref, a.title
                from assets a
                {join_sql}
                {where}
                order by a.id asc
                """,
                tuple(params),
            )
        ]
        total_count = len(_collapse_scan_rows(total_rows))
    else:
        count_sql = f"select count(distinct a.id) from assets a {join_sql} {where}"
        total_count = db.query_value(count_sql, tuple(params)) or 0

    sql = f"""
    select distinct a.id, a.source, a.source_ref, a.title, a.description, a.board, a.notes,
           a.media_status, a.content_kind, a.creator_name, a.source_domain, a.source_name,
           coalesce(
             (select ai.summary from asset_ai ai where ai.asset_id=a.id order by ai.created_at desc limit 1),
             a.ai_summary
           ) as ai_summary,
           a.created_at, a.imported_at, a.image_url, a.stored_path, a.stored_video_path, a.thumb_path, a.sha256,
           a.triage_status, a.needs_annotation, a.source_url, a.seo_alt_text,
           a.post_text, a.hashtags, a.engagement_json, a.dominant_color,
           a.image_width, a.image_height, a.closeup_desc,
           a.flagged, a.flagged_by, a.flagged_note,
           a.tagged, a.tagged_by, a.tagged_note
    from assets a
    {join_sql}
    {where}
    order by
      case when a.triage_status = 'keeper' then 0 else 1 end asc,
      case
        when a.thumb_path is not null and a.thumb_path != '' then 1
        when a.stored_path is not null and (
          lower(a.stored_path) like '%.jpg'
          or lower(a.stored_path) like '%.jpeg'
          or lower(a.stored_path) like '%.png'
          or lower(a.stored_path) like '%.webp'
          or lower(a.stored_path) like '%.gif'
          or lower(a.stored_path) like '%.bmp'
          or lower(a.stored_path) like '%.svg'
        ) then 1
        when a.image_url is not null and (
          lower(a.image_url) like '%.jpg%'
          or lower(a.image_url) like '%.jpeg%'
          or lower(a.image_url) like '%.png%'
          or lower(a.image_url) like '%.webp%'
          or lower(a.image_url) like '%.gif%'
          or lower(a.image_url) like '%.bmp%'
          or lower(a.image_url) like '%.svg%'
        ) then 1
        else 0
      end desc,
      a.id asc
    limit ? offset ?;
    """
    params += [limit, offset]
    rows = [dict(r) for r in db.query(sql, tuple(params))]
    enrich_assets_with_title_info(db, rows)
    collapsed = _collapse_scan_rows(rows)
    # Expose the pre-collapse row count so callers can correctly determine
    # has_more when scan rows get collapsed into document groups.
    for item in collapsed:
        item.setdefault("_pre_collapse_count", len(rows))
        item.setdefault("_total_count", total_count)
    return collapsed


def list_facets(db: Db, *, source: str = "", media_status: str = "") -> dict[str, Any]:
    sources = db.query("select source, count(*) as n from assets group by source order by n desc")
    board_clauses = ["board is not null", "board != ''"]
    board_params: list[Any] = []
    if source:
        selected_sources = _csv_values(source)
        if selected_sources:
            board_clauses.append("source in (%s)" % ",".join(["?"] * len(selected_sources)))
            board_params.extend(selected_sources)
    boards = db.query(
        "select board, count(*) as n from assets where %s group by board order by n desc limit 50" % " and ".join(board_clauses),
        tuple(board_params),
    )
    labels = db.query(
        "select label, count(*) as n from asset_labels group by label order by n desc limit 50"
    )
    media_statuses = db.query(
        """
        select media_status, count(*) as n
        from assets
        where media_status is not null and media_status != ''
        group by media_status
        order by n desc
        """
    )
    content_kinds = db.query(
        """
        select content_kind, count(*) as n
        from assets
        where content_kind is not null and content_kind != ''
        group by content_kind
        order by n desc
        limit 50
        """
    )
    creators = db.query(
        """
        select creator_name, count(*) as n
        from assets
        where creator_name is not null and creator_name != ''
        group by creator_name
        order by n desc
        limit 100
        """
    )

    context_clauses = ["content_kind is not null", "content_kind != ''"]
    context_params: list[Any] = []
    if source:
        selected_sources = _csv_values(source)
        if selected_sources:
            context_clauses.append("source in (%s)" % ",".join(["?"] * len(selected_sources)))
            context_params.extend(selected_sources)
    if media_status:
        statuses = _csv_values(media_status)
        if statuses:
            context_clauses.append("media_status in (%s)" % ",".join(["?"] * len(statuses)))
            context_params.extend(statuses)
    context_where = " and ".join(context_clauses)
    content_kinds_context = db.query(
        f"""
        select content_kind, count(*) as n
        from assets
        where {context_where}
        group by content_kind
        order by n desc
        limit 50
        """,
        tuple(context_params),
    )

    triage_rows = db.query(
        """select coalesce(triage_status, 'pending') as val, count(*) as cnt
           from assets
           group by coalesce(triage_status, 'pending')
           order by cnt desc"""
    )

    return {
        "sources": [dict(r) for r in sources],
        "boards": [dict(r) for r in boards],
        "labels": [dict(r) for r in labels],
        "media_statuses": [dict(r) for r in media_statuses],
        "content_kinds": [dict(r) for r in content_kinds],
        "content_kinds_context": [dict(r) for r in content_kinds_context],
        "creators": [dict(r) for r in creators],
        "triage_statuses": [{"value": r["val"], "count": r["cnt"]} for r in triage_rows],
    }


def list_asset_labels(db: Db, asset_id: str) -> list[dict]:
    """Return all labels for a single asset, ordered by label name."""
    rows = db.query(
        "select label, source from asset_labels where asset_id = ? order by label",
        (asset_id,),
    )
    return [dict(r) for r in rows]


def _log_triage(
    db: Db,
    asset_id: str,
    old_status: str | None,
    new_status: str | None,
    *,
    reason: str = "",
    actor: str = "",
) -> None:
    """Append an entry to the triage audit log."""
    db.exec(
        "insert into triage_log (asset_id, old_status, new_status, reason, actor, created_at) "
        "values (?, ?, ?, ?, ?, ?)",
        (asset_id, old_status, new_status, reason, actor,
         datetime.now(timezone.utc).isoformat()),
    )


def _log_triage_bulk(
    db: Db,
    asset_ids: list[str],
    new_status: str | None,
    *,
    reason: str = "",
    actor: str = "",
) -> None:
    """Append audit log entries for a bulk triage operation.

    Fetches current status for each asset so old_status is recorded accurately.
    """
    if not asset_ids:
        return
    now = datetime.now(timezone.utc).isoformat()
    placeholders = ",".join(["?"] * len(asset_ids))
    rows = db.query(
        f"select id, triage_status from assets where id in ({placeholders})",
        asset_ids,
    )
    old_by_id = {r["id"]: r["triage_status"] for r in rows}
    db.executemany(
        "insert into triage_log (asset_id, old_status, new_status, reason, actor, created_at) "
        "values (?, ?, ?, ?, ?, ?)",
        [(aid, old_by_id.get(aid), new_status, reason, actor, now) for aid in asset_ids],
    )


def set_triage_status(
    db: Db,
    asset_id: str,
    status: str | None,
    needs_annotation: int | None = None,
    *,
    reason: str = "",
    actor: str = "",
) -> None:
    """Set triage status for a single asset.

    status: 'keeper' | 'hidden' | None (resets to pending).
    needs_annotation: 0 or 1, set when user checks 'Comment later' during review.
    """
    # Log before updating so we capture old_status
    old = db.query_value("select triage_status from assets where id = ?", (asset_id,))
    _log_triage(db, asset_id, old, status, reason=reason, actor=actor)

    now = datetime.now(timezone.utc).isoformat()
    if status is None:
        db.exec(
            "update assets set triage_status = null, triage_at = ?, needs_annotation = 0 where id = ?",
            (now, asset_id),
        )
    else:
        annotation_val = needs_annotation if needs_annotation is not None else 0
        db.exec(
            "update assets set triage_status = ?, triage_at = ?, needs_annotation = ? where id = ?",
            (status, now, annotation_val, asset_id),
        )


def bulk_set_triage_status(
    db: Db,
    asset_ids: list[str],
    status: str | None,
    *,
    reason: str = "",
    actor: str = "",
) -> int:
    """Set triage status for multiple assets. Returns count updated."""
    if not asset_ids:
        return 0
    # Log before updating so we capture old_status for each
    _log_triage_bulk(db, asset_ids, status, reason=reason, actor=actor)

    now = datetime.now(timezone.utc).isoformat()
    placeholders = ",".join(["?"] * len(asset_ids))
    if status is None:
        db.exec(
            f"update assets set triage_status = null, triage_at = ? where id in ({placeholders})",
            (now, *asset_ids),
        )
    else:
        db.exec(
            f"update assets set triage_status = ?, triage_at = ? where id in ({placeholders})",
            (status, now, *asset_ids),
        )
    return len(asset_ids)


def rollback_triage_since(
    db: Db,
    *,
    since_iso: str,
    reason: str = "",
    actor: str = "",
) -> dict[str, Any]:
    """Rollback triage status to the value before `since_iso`.

    For each asset changed since the cutoff, this restores the `old_status`
    from the first triage_log entry at/after the cutoff.
    """
    cutoff = (since_iso or "").strip()
    if not cutoff:
        return {"cutoff": cutoff, "candidates": 0, "updated": 0}

    first_changes = db.query(
        """
        select t.asset_id, t.old_status
        from triage_log t
        join (
          select asset_id, min(id) as first_id
          from triage_log
          where created_at >= ?
          group by asset_id
        ) firsts on firsts.first_id = t.id
        """,
        (cutoff,),
    )
    if not first_changes:
        return {"cutoff": cutoff, "candidates": 0, "updated": 0}

    candidate_rows = [dict(r) for r in first_changes]
    asset_ids = [str(r.get("asset_id") or "").strip() for r in candidate_rows if str(r.get("asset_id") or "").strip()]
    unique_ids = _unique_ids(asset_ids)
    if not unique_ids:
        return {"cutoff": cutoff, "candidates": 0, "updated": 0}

    placeholders = ",".join(["?"] * len(unique_ids))
    current_rows = db.query(
        f"select id, triage_status from assets where id in ({placeholders})",
        tuple(unique_ids),
    )
    current_by_id = {str(r["id"]): r["triage_status"] for r in current_rows}
    target_by_id = {str(r.get("asset_id") or ""): r.get("old_status") for r in candidate_rows}

    updated = 0
    rollback_reason = (reason or f"triage rollback since {cutoff}").strip()
    for aid in unique_ids:
        if aid not in current_by_id:
            continue
        target = target_by_id.get(aid)
        current = current_by_id.get(aid)
        if current == target:
            continue
        set_triage_status(
            db,
            aid,
            target,
            reason=rollback_reason,
            actor=actor,
        )
        updated += 1
    return {"cutoff": cutoff, "candidates": len(unique_ids), "updated": updated}


def bulk_set_flag(
    db: Db,
    asset_ids: list[str],
    flagged: int,
    *,
    flagged_by: str = "",
    flagged_note: str = "",
) -> int:
    """Set flagged status for multiple assets. Returns count updated."""
    if not asset_ids:
        return 0
    placeholders = ",".join(["?"] * len(asset_ids))
    db.exec(
        f"update assets set flagged=?, flagged_by=?, flagged_note=? where id in ({placeholders})",
        (flagged, flagged_by, flagged_note, *asset_ids),
    )
    return len(asset_ids)


def bulk_set_tag(
    db: Db,
    asset_ids: list[str],
    tagged: int,
    *,
    tagged_by: str = "",
    tagged_note: str = "",
) -> int:
    """Set tagged status for multiple assets (Jim's anomaly markers). Returns count updated."""
    if not asset_ids:
        return 0
    placeholders = ",".join(["?"] * len(asset_ids))
    db.exec(
        f"update assets set tagged=?, tagged_by=?, tagged_note=? where id in ({placeholders})",
        (tagged, tagged_by, tagged_note, *asset_ids),
    )
    return len(asset_ids)


def triage_stats(db: Db) -> dict[str, Any]:
    """Return triage progress stats, overall and per-board."""
    rows = db.query(
        """
        select
            board,
            count(*) as total,
            sum(case when triage_status = 'keeper' then 1 else 0 end) as keepers,
            sum(case when triage_status = 'hidden' then 1 else 0 end) as hidden,
            sum(case when triage_status is null then 1 else 0 end) as pending,
            sum(case when needs_annotation = 1 then 1 else 0 end) as needs_comment,
            sum(case when flagged = 1 then 1 else 0 end) as flagged
        from assets
        group by board
        order by count(*) desc
        """
    )
    boards = [dict(r) for r in rows]
    totals = db.query(
        """
        select
            count(*) as total,
            sum(case when triage_status = 'keeper' then 1 else 0 end) as keepers,
            sum(case when triage_status = 'hidden' then 1 else 0 end) as hidden,
            sum(
              case when triage_status = 'hidden'
                     and coalesce((
                       select tl.actor
                       from triage_log tl
                       where tl.asset_id = assets.id
                       order by tl.created_at desc, tl.id desc
                       limit 1
                     ), '') = 'ai-reel-triage'
                then 1 else 0 end
            ) as hidden_ai_cleanup,
            sum(
              case when triage_status = 'hidden'
                     and coalesce((
                       select tl.actor
                       from triage_log tl
                       where tl.asset_id = assets.id
                       order by tl.created_at desc, tl.id desc
                       limit 1
                     ), '') != 'ai-reel-triage'
                then 1 else 0 end
            ) as hidden_manual,
            sum(case when triage_status is null then 1 else 0 end) as pending,
            sum(case when needs_annotation = 1 then 1 else 0 end) as needs_comment,
            sum(case when flagged = 1 then 1 else 0 end) as flagged
        from assets
        """
    )
    overall = dict(totals[0]) if totals else {}
    return {"overall": overall, "boards": boards}


def list_collections(
    db: Db,
    *,
    include_hidden: bool = False,
    viewer_role: str = "",
    viewer_actor_id: str = "",
) -> list[dict[str, Any]]:
    hidden_collection_id = str(
        db.query_value("select id from collections where lower(name)='hidden' limit 1") or ""
    )
    params: list[Any] = []
    where: list[str] = []
    role = str(viewer_role or "").strip().lower()
    actor_id = str(viewer_actor_id or "").strip()
    if not include_hidden:
        where.append("coalesce(hidden, 0) = 0")
    if role != "owner":
        where.append("coalesce(c.intent, 'working') = 'shared'")
        if actor_id:
            where.append(
                "("
                "coalesce(c.shared_actor_id, '') = ? "
                "or exists (select 1 from collection_shares csv where csv.collection_id = c.id and csv.actor_id = ?)"
                ")"
            )
            params.extend([actor_id, actor_id])
        else:
            where.append("1 = 0")
    sql = """
        select
            c.id,
            c.name,
            c.description,
            c.created_at,
            c.updated_at,
            c.provenance_kind,
            c.provenance_note,
            c.curator,
            coalesce(c.intent, 'working') as intent,
            c.shared_actor_id,
            coalesce(c.hidden, 0) as hidden,
            c.hidden_at,
            0 as count_total,
            0 as count_visible
        from collections c
    """
    if where:
        sql += " where " + " and ".join(where)
    sql += " order by c.name collate nocase asc, c.updated_at desc"
    rows = db.query(sql, tuple(params))
    collection_ids = [str(r["id"] or "").strip() for r in rows if str(r["id"] or "").strip()]
    logical_counts_by_collection: dict[str, dict[str, int]] = {}
    shares_by_collection: dict[str, list[tuple[str, str]]] = {}
    if collection_ids:
        placeholders = ",".join(["?"] * len(collection_ids))
        count_rows = db.query(
            f"""
            select
                ci.collection_id,
                a.id,
                a.source,
                a.source_ref,
                a.title,
                a.triage_status,
                case
                  when ? != ''
                   and exists (
                     select 1
                     from collection_items h
                     where h.collection_id = ?
                       and h.asset_id = a.id
                   )
                  then 1 else 0
                end as in_hidden_collection
            from collection_items ci
            join assets a on a.id = ci.asset_id
            where ci.collection_id in ({placeholders})
            order by ci.collection_id, ci.position, a.id
            """,
            (hidden_collection_id, hidden_collection_id, *collection_ids),
        )
        rows_by_collection: dict[str, list[dict[str, Any]]] = {}
        visible_rows_by_collection: dict[str, list[dict[str, Any]]] = {}
        for row in count_rows:
            item = dict(row)
            cid = str(item.get("collection_id") or "").strip()
            if not cid:
                continue
            rows_by_collection.setdefault(cid, []).append(item)
            if (
                str(item.get("triage_status") or "") != "hidden"
                and int(item.get("in_hidden_collection") or 0) != 1
            ):
                visible_rows_by_collection.setdefault(cid, []).append(item)
        for cid in collection_ids:
            logical_counts_by_collection[cid] = {
                "count_total": len(_collapse_scan_rows(rows_by_collection.get(cid, []))),
                "count_visible": len(_collapse_scan_rows(visible_rows_by_collection.get(cid, []))),
            }
        share_rows = db.query(
            f"""
            select cs.collection_id, cs.actor_id, a.name
            from collection_shares cs
            join actors a on a.id = cs.actor_id
            where cs.collection_id in ({",".join(["?"] * len(collection_ids))})
            order by a.name collate nocase asc, cs.actor_id asc
            """,
            tuple(collection_ids),
        )
        for row in share_rows:
            cid = str(row["collection_id"] or "").strip()
            if not cid:
                continue
            shares_by_collection.setdefault(cid, []).append(
                (str(row["actor_id"] or "").strip(), str(row["name"] or "").strip())
            )
    out = []
    for r in rows:
        d = decorate_collection_record(dict(r))
        shares = shares_by_collection.get(str(d.get("id") or ""), [])
        if shares:
            d["shared_actor_ids"] = [actor_id for actor_id, _ in shares if actor_id]
            d["shared_actor_names"] = [name for _, name in shares if name]
            if not d.get("shared_actor_id"):
                d["shared_actor_id"] = d["shared_actor_ids"][0] if d["shared_actor_ids"] else ""
            if not d.get("shared_actor_name"):
                d["shared_actor_name"] = d["shared_actor_names"][0] if d["shared_actor_names"] else ""
        logical_counts = logical_counts_by_collection.get(str(d.get("id") or ""), {})
        d["count_total"] = int(logical_counts.get("count_total") or 0)
        d["count_visible"] = int(logical_counts.get("count_visible") or 0)
        d["count"] = d["count_visible"]
        d["hidden"] = int(d.get("hidden") or 0)
        out.append(d)
    return out


def create_collection(
    db: Db,
    *,
    name: str,
    description: str = "",
    intent: str = "working",
    shared_actor_id: str = "",
    shared_actor_ids: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    cid = str(uuid.uuid4())
    now = _now_iso()
    provenance_kind, curator, provenance_note = infer_collection_provenance(name)
    normalized_intent = _normalize_collection_intent(intent)
    normalized_shared_actor_ids = _normalize_shared_actor_ids(shared_actor_id, shared_actor_ids)
    shared_id = ""
    shared_actor_name = ""
    shared_actor_names: list[str] = []
    if normalized_intent == "shared":
        if not normalized_shared_actor_ids:
            raise ValueError("shared collections require shared_actor_id")
        shared_rows = _validate_shared_collection_actor_ids(db, normalized_shared_actor_ids)
        shared_id = str(shared_rows[0].get("id") or "").strip()
        shared_actor_name = str(shared_rows[0].get("name") or "").strip()
        shared_actor_names = [str(row.get("name") or "").strip() for row in shared_rows if str(row.get("name") or "").strip()]
    else:
        normalized_shared_actor_ids = []
    db.exec(
        """
        insert into collections
          (
            id, name, description, created_at, updated_at,
            provenance_kind, provenance_note, curator,
            intent, shared_actor_id
          )
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            cid,
            name,
            description or None,
            now,
            now,
            provenance_kind,
            provenance_note,
            curator,
            normalized_intent,
            shared_id or None,
        ),
    )
    if normalized_shared_actor_ids:
        _replace_collection_shares(db, collection_id=cid, actor_ids=normalized_shared_actor_ids)
    return decorate_collection_record(
        {
            "id": cid,
            "name": name,
            "description": description or "",
            "created_at": now,
            "updated_at": now,
            "count": 0,
            "count_total": 0,
            "count_visible": 0,
            "hidden": 0,
            "hidden_at": None,
            "provenance_kind": provenance_kind,
            "provenance_note": provenance_note,
            "curator": curator,
            "intent": normalized_intent,
            "shared_actor_id": shared_id,
            "shared_actor_name": shared_actor_name,
            "shared_actor_ids": normalized_shared_actor_ids,
            "shared_actor_names": shared_actor_names,
        }
    )


def update_collection(
    db: Db,
    *,
    collection_id: str,
    name: str | None = None,
    description: str | None = None,
    intent: str | None = None,
    shared_actor_id: str = "",
    shared_actor_ids: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    rows = db.query("select * from collections where id=?", (collection_id,))
    if not rows:
        raise FileNotFoundError("collection not found")
    current = dict(rows[0])
    next_name = str(name if name is not None else current.get("name") or "").strip()
    if not next_name:
        raise ValueError("name required")
    next_description = str(description if description is not None else current.get("description") or "").strip()
    next_intent = _normalize_collection_intent(intent if intent is not None else str(current.get("intent") or "working"))
    normalized_shared_actor_ids = _normalize_shared_actor_ids(shared_actor_id, shared_actor_ids)
    shared_id = ""
    shared_actor_name = ""
    shared_actor_names: list[str] = []
    if next_intent == "shared":
        if not normalized_shared_actor_ids:
            raise ValueError("shared collections require shared_actor_id")
        shared_rows = _validate_shared_collection_actor_ids(db, normalized_shared_actor_ids)
        shared_id = str(shared_rows[0].get("id") or "").strip()
        shared_actor_name = str(shared_rows[0].get("name") or "").strip()
        shared_actor_names = [str(row.get("name") or "").strip() for row in shared_rows if str(row.get("name") or "").strip()]
    else:
        normalized_shared_actor_ids = []

    now = _now_iso()
    db.exec(
        """
        update collections
        set name=?, description=?, intent=?, shared_actor_id=?, updated_at=?
        where id=?
        """,
        (
            next_name,
            next_description or None,
            next_intent,
            shared_id or None,
            now,
            collection_id,
        ),
    )
    _replace_collection_shares(db, collection_id=collection_id, actor_ids=normalized_shared_actor_ids)
    updated = dict(db.query("select * from collections where id=?", (collection_id,))[0])
    updated["count_total"] = int(current.get("count_total") or 0)
    updated["count_visible"] = int(current.get("count_visible") or current.get("count") or 0)
    updated["count"] = updated["count_visible"]
    updated["shared_actor_id"] = shared_id
    updated["shared_actor_name"] = shared_actor_name
    updated["shared_actor_ids"] = normalized_shared_actor_ids
    updated["shared_actor_names"] = shared_actor_names
    return decorate_collection_record(updated)


def add_items_to_collection(db: Db, *, collection_id: str, asset_ids: list[str]) -> int:
    expanded_ids = _expand_scan_asset_ids(db, asset_ids)
    if not expanded_ids:
        return 0
    pos = db.query_value(
        "select coalesce(max(position), 0) from collection_items where collection_id=?",
        (collection_id,),
    )
    rows = []
    for i, aid in enumerate(expanded_ids, start=1):
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
    expanded_ids = _expand_scan_asset_ids(db, asset_ids)
    unique_ids = _unique_ids(expanded_ids)
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


def set_collections_hidden(db: Db, *, collection_ids: list[str], hidden: bool) -> int:
    ids = _unique_ids(collection_ids)
    if not ids:
        return 0
    placeholders = ",".join(["?"] * len(ids))
    target_hidden = 1 if hidden else 0
    params = [*ids, target_hidden]
    changed = db.query_value(
        (
            "select count(*) from collections "
            f"where id in ({placeholders}) and lower(name) != 'hidden' and coalesce(hidden, 0) != ?"
        ),
        tuple(params),
    )
    if not changed:
        return 0
    now = _now_iso()
    if hidden:
        db.exec(
            (
                "update collections set hidden=1, hidden_at=?, updated_at=? "
                f"where id in ({placeholders}) and lower(name) != 'hidden'"
            ),
            (now, now, *ids),
        )
    else:
        db.exec(
            (
                "update collections set hidden=0, hidden_at=null, updated_at=? "
                f"where id in ({placeholders}) and lower(name) != 'hidden'"
            ),
            (now, *ids),
        )
    return int(changed or 0)


def delete_hidden_collections(db: Db, *, collection_ids: list[str]) -> dict[str, int]:
    ids = _unique_ids(collection_ids)
    if not ids:
        return {"deleted": 0, "skipped": 0}
    placeholders = ",".join(["?"] * len(ids))
    rows = db.query(
        (
            "select id from collections "
            f"where id in ({placeholders}) and lower(name) != 'hidden' and coalesce(hidden, 0) = 1"
        ),
        tuple(ids),
    )
    deletable_ids = [str(r["id"]) for r in rows]
    if deletable_ids:
        del_placeholders = ",".join(["?"] * len(deletable_ids))
        db.exec(f"delete from collections where id in ({del_placeholders})", tuple(deletable_ids))
    deleted = len(deletable_ids)
    skipped = len(ids) - deleted
    return {"deleted": deleted, "skipped": skipped}


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
    return _collapse_scan_rows([dict(r) for r in rows])


def add_to_tray(db: Db, *, asset_ids: list[str]) -> int:
    expanded_ids = _expand_scan_asset_ids(db, asset_ids)
    if not expanded_ids:
        return 0
    rows = []
    now = _now_iso()
    for aid in expanded_ids:
        rows.append((aid, now))
    db.executemany("insert or ignore into tray_items (asset_id, added_at) values (?, ?)", rows)
    return len(rows)


def remove_from_tray(db: Db, *, asset_ids: list[str]) -> None:
    if not asset_ids:
        return
    expanded_ids = _expand_scan_asset_ids(db, asset_ids)
    for aid in expanded_ids:
        db.exec("delete from tray_items where asset_id=?", (aid,))


def clear_tray(db: Db) -> None:
    db.exec("delete from tray_items")


def create_collection_from_tray(
    db: Db,
    *,
    name: str,
    description: str = "",
    intent: str = "working",
    shared_actor_id: str = "",
    shared_actor_ids: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    col = create_collection(
        db,
        name=name,
        description=description,
        intent=intent,
        shared_actor_id=shared_actor_id,
        shared_actor_ids=shared_actor_ids,
    )
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
        """select id, asset_id, x, y, text, created_at, updated_at,
                  actor_id, actor_name, annotation_type, resolved
           from annotations where asset_id=? order by created_at asc""",
        (asset_id,),
    )
    return [dict(r) for r in rows]


def create_annotation(
    db: Db,
    *,
    asset_id: str,
    x: float,
    y: float,
    text: str = "",
    actor_id: str | None = None,
    actor_name: str | None = None,
    annotation_type: str = "note",
) -> dict[str, Any]:
    ann_id = str(uuid.uuid4())
    now = _now_iso()
    db.exec(
        """insert into annotations
           (id, asset_id, x, y, text, created_at, updated_at, actor_id, actor_name, annotation_type, resolved)
           values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
        (ann_id, asset_id, x, y, text or None, now, now, actor_id, actor_name, annotation_type or "note"),
    )
    return {
        "id": ann_id, "asset_id": asset_id, "x": x, "y": y, "text": text,
        "created_at": now, "updated_at": now,
        "actor_id": actor_id, "actor_name": actor_name,
        "annotation_type": annotation_type or "note", "resolved": 0,
    }


def update_annotation(
    db: Db,
    *,
    annotation_id: str,
    x: float | None = None,
    y: float | None = None,
    text: str | None = None,
    resolved: int | None = None,
) -> None:
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
    if resolved is not None:
        sets.append("resolved=?")
        params.append(resolved)
    sets.append("updated_at=?")
    params.append(_now_iso())
    params.append(annotation_id)
    db.exec(f"update annotations set {', '.join(sets)} where id=?", tuple(params))


def delete_annotation(db: Db, *, annotation_id: str) -> None:
    db.exec("delete from annotations where id=?", (annotation_id,))


# ---------------------------------------------------------------------------
# Actors (magic-link collaboration)
# ---------------------------------------------------------------------------

def create_actor(db: Db, *, name: str, role: str = "collaborator") -> dict[str, Any]:
    """Create a new actor with a unique magic-link token."""
    actor_id = str(uuid.uuid4())
    token = secrets.token_urlsafe(16)
    now = _now_iso()
    db.exec(
        "insert into actors (id, name, token, role, created_at) values (?, ?, ?, ?, ?)",
        (actor_id, name, token, role, now),
    )
    return {"id": actor_id, "name": name, "token": token, "role": role, "created_at": now}


def list_actors(db: Db) -> list[dict[str, Any]]:
    rows = db.query("select id, name, token, role, created_at from actors order by created_at asc")
    return [dict(r) for r in rows]


def get_actor_by_token(db: Db, *, token: str) -> dict[str, Any] | None:
    rows = db.query(
        "select id, name, token, role, created_at from actors where token=?",
        (token,),
    )
    return dict(rows[0]) if rows else None


def delete_actor(db: Db, *, actor_id: str) -> None:
    db.exec("delete from actors where id=?", (actor_id,))


def list_open_questions(db: Db, *, limit: int = 50) -> list[dict[str, Any]]:
    """Return unresolved question annotations, newest first, with asset info."""
    rows = db.query(
        """select ann.id, ann.asset_id, ann.x, ann.y, ann.text,
                  ann.actor_id, ann.actor_name, ann.annotation_type,
                  ann.created_at, ann.resolved,
                  a.title as asset_title, a.thumb_path as asset_thumb,
                  a.source as asset_source, a.board as asset_board
           from annotations ann
           join assets a on a.id = ann.asset_id
           where ann.annotation_type = 'question'
             and coalesce(ann.resolved, 0) = 0
           order by ann.created_at desc
           limit ?""",
        (limit,),
    )
    return [dict(r) for r in rows]


def hidden_tree(db: Db) -> dict[str, Any]:
    """Return hidden item counts grouped by source and board for sidebar tree."""
    rows = db.query(
        """select source, board, count(*) as cnt
           from assets
           where triage_status = 'hidden'
           group by source, board
           order by source, board"""
    )
    sources_map: dict[str, dict[str, Any]] = {}
    for r in rows:
        src = str(r["source"] or "unknown")
        if src not in sources_map:
            sources_map[src] = {"source": src, "boards": [], "total": 0}
        board_name = str(r["board"] or "(uncategorized)")
        cnt = int(r["cnt"])
        sources_map[src]["boards"].append({"board": board_name, "count": cnt})
        sources_map[src]["total"] += cnt
    total_hidden = db.query_value(
        "select count(*) from assets where triage_status = 'hidden'"
    ) or 0
    return {"sources": list(sources_map.values()), "total": int(total_hidden)}
