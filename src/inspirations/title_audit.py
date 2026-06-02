from __future__ import annotations

import re
import secrets
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .db import Db

_FB_SAVED_LINK_TITLE_RE = re.compile(r"^\s*[^.]+ saved a link from (.+?)'s post\.?\s*$", re.IGNORECASE)
_JUNK_SHORT_DOMAIN_RE = re.compile(r"^(https?://|www\.)|\.(com|org|net|co)\b", re.IGNORECASE)
_NOISE_PREFIX_RE = re.compile(
    r"^(This image|The image|Image)\s+(shows|depicts|displays|features|illustrates|showcases|is)\s+",
    re.IGNORECASE,
)
_CLOSEUP_PREFIX_RE = re.compile(r"^A close-up\s+(shot|image|outdoor shot)\s+of\s+", re.IGNORECASE)
_AERIAL_PREFIX_RE = re.compile(r"^An aerial view\s+(shows\s+|of\s+)?", re.IGNORECASE)
_PORTRAIT_PREFIX_RE = re.compile(r"^A portrait of\s+", re.IGNORECASE)
_MIXED_ALNUM_RE = re.compile(r"[A-Za-z].*\d|\d.*[A-Za-z]")
_HEXISH_RE = re.compile(r"^[0-9a-f]{8,}$", re.IGNORECASE)
_FACEBOOK_ENGAGEMENT_PREFIX_RE = re.compile(
    r"^\s*(?:(?:\d[\d.,]*\s*[kmb]?)\s*"
    r"(?:views?|reactions?|shares?|comments?|likes?|saves?)\s*(?:[·•\-–—]\s*)?){1,5}\|\s*",
    re.IGNORECASE,
)

_TRAILING_STOPWORDS = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "but",
    "with",
    "in",
    "on",
    "at",
    "to",
    "for",
    "from",
    "of",
    "by",
    "as",
    "is",
    "are",
    "was",
    "were",
    "be",
    "being",
}

_WEAK_TRAILING_WORDS = {
    "over",
    "alongside",
    "paired",
    "indicating",
    "possibly",
    "commonly",
    "dark",
}

_SLUG_NOISE_TOKENS = {
    "amp",
    "utm",
    "ref",
    "www",
    "posts",
    "article",
}

_GENERIC_SLUG_TITLES = {
    "pin",
    "post",
    "reel",
    "photo",
    "image",
    "item",
    "video",
}

REVIEW_STATUS_PENDING = "pending"
REVIEW_STATUS_APPROVED = "approved"
REVIEW_STATUS_REJECTED = "rejected"
REVIEW_STATUS_EDITED = "edited"

REVIEW_STATUSES = {
    REVIEW_STATUS_PENDING,
    REVIEW_STATUS_APPROVED,
    REVIEW_STATUS_REJECTED,
    REVIEW_STATUS_EDITED,
}


@dataclass(frozen=True)
class TitleAuditCandidate:
    asset_id: str
    old_title: str
    new_title: str
    technique_used: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_batch_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"title-audit-{stamp}-{secrets.token_hex(3)}"


def _assert_batch_exists(db: Db, batch_id: str) -> None:
    exists = db.query_value("select 1 from title_audit_batches where id = ? limit 1", (batch_id,))
    if not exists:
        raise ValueError(f"Unknown title-audit batch id: {batch_id}")


def _review_counts_for_batch(db: Db, batch_id: str) -> dict[str, int]:
    rows = db.query(
        """
        select review_status, count(*) as n
        from title_audit_candidates
        where batch_id = ?
        group by review_status
        order by review_status asc
        """,
        (batch_id,),
    )
    out: dict[str, int] = {k: 0 for k in sorted(REVIEW_STATUSES)}
    for row in rows:
        out[str(row["review_status"])] = int(row["n"])
    return out


def _active_apply_count(db: Db, batch_id: str) -> int:
    return int(
        db.query_value(
            """
            select count(*)
            from title_audit_applied
            where batch_id = ? and undone_at is null
            """,
            (batch_id,),
        )
        or 0
    )


def _candidate_filter_sql(status: str) -> tuple[str, tuple[object, ...]]:
    val = str(status or "").strip().lower()
    if not val:
        return "", ()
    if val in REVIEW_STATUSES:
        return " and c.review_status = ?", (val,)
    if val == "applied":
        return " and c.applied_at is not null", ()
    if val == "ready":
        return " and c.review_status in ('approved', 'edited') and c.applied_at is null", ()
    raise ValueError("status must be empty, pending, approved, rejected, edited, ready, or applied")


def _title_case_words(text: str) -> str:
    out: list[str] = []
    for word in str(text or "").split():
        if len(word) <= 2:
            out.append(word.upper())
        else:
            out.append(word[:1].upper() + word[1:].lower())
    return " ".join(out)


def _clean_alt_text(value: str) -> str:
    return re.sub(r"^This may contain:\s*", "", str(value or "").strip(), flags=re.IGNORECASE).strip()


def strip_facebook_engagement_prefix(value: str) -> str:
    text = str(value or "").strip()
    return _FACEBOOK_ENGAGEMENT_PREFIX_RE.sub("", text, count=1).strip()


def _slug_tokens_from_segment(segment: str) -> list[str]:
    value = str(segment or "").strip()
    if not value:
        return []
    value = re.sub(r"\.[a-z0-9]{2,5}$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"[-_+]+", " ", value)
    value = re.sub(r"[^a-z0-9 ]+", " ", value, flags=re.IGNORECASE)
    toks = [t for t in value.lower().split() if t]
    out: list[str] = []
    for tok in toks:
        if tok in _SLUG_NOISE_TOKENS:
            if tok == "amp":
                out.append("and")
            continue
        if tok.isdigit() and len(tok) >= 2:
            continue
        if _HEXISH_RE.fullmatch(tok):
            continue
        if _MIXED_ALNUM_RE.search(tok):
            continue
        out.append(tok)
    while out and out[0].isdigit():
        out = out[1:]
    return out


def _slug_title_from_source_ref(source_ref: str) -> str:
    ref = str(source_ref or "").strip()
    if not ref:
        return ""
    try:
        parsed = urlparse(ref)
    except Exception:
        return ""
    parts = [p for p in parsed.path.split("/") if p]
    if not parts:
        return ""
    best: list[str] = []
    for seg in reversed(parts):
        toks = _slug_tokens_from_segment(seg)
        alpha_count = sum(1 for t in toks if re.search(r"[a-z]", t))
        if alpha_count >= 3:
            best = toks
            break
        if not best and alpha_count >= 1:
            best = toks
    slug = " ".join(best).strip()
    if not slug:
        return ""
    if slug.lower() in _GENERIC_SLUG_TITLES:
        return ""
    return _title_case_words(slug)


def _host_title(source_ref: str) -> str:
    ref = str(source_ref or "").strip()
    if not ref:
        return ""
    try:
        host = (urlparse(ref).hostname or "").strip()
    except Exception:
        host = ""
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return ""
    return _title_case_words(host.replace(".", " "))


def _clean_source_name(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    value = re.sub(r"\.(com|org|net)\b", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+link$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+", " ", value).strip(" -:;,.")
    return value


def _trim_code_like_tokens(text: str) -> str:
    tokens: list[str] = []
    for token in re.split(r"\s+", str(text or "").strip()):
        word = token.strip(" ,;:()[]{}")
        if not word:
            continue
        if _HEXISH_RE.search(word):
            continue
        if _MIXED_ALNUM_RE.search(word):
            continue
        if len(word) > 22:
            continue
        tokens.append(word)
    return " ".join(tokens)


def _trim_to_complete_phrase(text: str, *, max_chars: int = 78) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip(" ,;:-")
    if len(value) <= max_chars:
        return value
    cut = max_chars
    for sep in [", ", "; ", " - ", " -- "]:
        idx = value.rfind(sep, 0, max_chars + 1)
        if idx >= 18:
            cut = idx
            break
    else:
        sp = value.rfind(" ", 0, max_chars + 1)
        if sp >= 18:
            cut = sp
    value = value[:cut].strip(" ,;:-")
    words = value.split()
    while words and (
        words[-1].lower() in _TRAILING_STOPWORDS or words[-1].lower() in _WEAK_TRAILING_WORDS
    ):
        words.pop()
    return " ".join(words).strip()


def concise_title(text: str) -> str:
    value = str(text or "").strip().replace('"', "")
    if not value:
        return ""

    overlay = ""
    if re.search(r"text overlays? related to investment advice", value, re.IGNORECASE):
        overlay = "overlay implies investment advice"
    elif re.search(r"text overlay[^.]*blood pressure", value, re.IGNORECASE):
        overlay = "overlay implies blood pressure"
    elif re.search(r"text overlay[^.]*good idea", value, re.IGNORECASE):
        overlay = "overlay implies risk review"

    first_clause = re.split(r"\.(?:\s+|$)", value)[0].strip()
    first_clause = _NOISE_PREFIX_RE.sub("", first_clause)
    first_clause = _CLOSEUP_PREFIX_RE.sub("", first_clause)
    first_clause = re.sub(r"^A close-up\s+of\s+", "", first_clause, flags=re.IGNORECASE)
    first_clause = _AERIAL_PREFIX_RE.sub("", first_clause)
    first_clause = _PORTRAIT_PREFIX_RE.sub("", first_clause)
    first_clause = re.sub(r"^A woman is\s+", "Woman ", first_clause, flags=re.IGNORECASE)
    first_clause = re.sub(r"^A man is\s+", "Man ", first_clause, flags=re.IGNORECASE)
    first_clause = re.sub(r"^A person is\s+", "Person ", first_clause, flags=re.IGNORECASE)
    first_clause = re.sub(r"^A woman\s+", "Woman ", first_clause, flags=re.IGNORECASE)
    first_clause = re.sub(r"^A man\s+", "Man ", first_clause, flags=re.IGNORECASE)
    first_clause = re.sub(r"^A person\s+", "Person ", first_clause, flags=re.IGNORECASE)

    # Drop non-focal context tails.
    first_clause = re.sub(r"\bIn the background[^.]*", "", first_clause, flags=re.IGNORECASE)
    first_clause = re.sub(r"\bThe background[^.]*", "", first_clause, flags=re.IGNORECASE)
    first_clause = re.sub(r"\bin what appears to be [^.]*", "", first_clause, flags=re.IGNORECASE)
    first_clause = re.sub(r"\bThe (?:room|salon|setting|space|property) [^.]*", "", first_clause, flags=re.IGNORECASE)
    first_clause = re.sub(r"\bthat reads\b.*$", "", first_clause, flags=re.IGNORECASE)

    first_clause = _trim_code_like_tokens(first_clause)
    first_clause = re.sub(r"\s+", " ", first_clause).strip(" ,;:-")
    first_clause = re.sub(r"^(a|an|the)\s+", "", first_clause, flags=re.IGNORECASE)
    first_clause = _trim_to_complete_phrase(first_clause, max_chars=78)

    if len(first_clause.split()) < 3:
        fallback = _trim_code_like_tokens(_NOISE_PREFIX_RE.sub("", re.split(r"\.(?:\s+|$)", value)[0]))
        fallback = _trim_to_complete_phrase(fallback, max_chars=78)
        if fallback:
            first_clause = fallback

    if overlay and overlay.lower() not in first_clause.lower():
        return _trim_to_complete_phrase(f"{first_clause}; {overlay}", max_chars=92)
    return first_clause


def propose_title(
    *,
    source: str,
    old_title: str,
    source_ref: str,
    ai_summary: str,
    seo_alt_text: str,
) -> tuple[str, str] | None:
    old = str(old_title or "").strip()
    src = str(source or "").strip().lower()
    proposed = ""
    technique = ""

    if not old:
        ai = str(ai_summary or "").strip()
        alt = _clean_alt_text(seo_alt_text)
        slug = _slug_title_from_source_ref(source_ref)
        if ai:
            proposed = concise_title(ai)
            technique = "empty_title_ai_summary"
        elif alt:
            proposed = concise_title(alt)
            technique = "empty_title_seo_alt"
        elif slug:
            proposed = slug
            technique = "empty_title_source_slug"
    elif len(old) < 40 and _JUNK_SHORT_DOMAIN_RE.search(old):
        slug = _slug_title_from_source_ref(source_ref)
        if slug and slug.lower() != old.lower():
            proposed = slug
            technique = "junk_domain_source_slug"

    if not proposed and src == "facebook" and _FB_SAVED_LINK_TITLE_RE.search(old):
        match = _FB_SAVED_LINK_TITLE_RE.search(old)
        source_name = _clean_source_name(str(match.group(1) if match else "").strip())
        slug = _trim_code_like_tokens(_slug_title_from_source_ref(source_ref))
        slug = _trim_to_complete_phrase(slug, max_chars=46)
        host = _host_title(source_ref)
        if slug:
            proposed = f"{source_name}: {slug}" if source_name else slug
            technique = "fb_saved_link_slug"
        elif source_name:
            proposed = source_name
            technique = "fb_saved_link_source_name"
        elif host:
            proposed = host
            technique = "fb_saved_link_host"

    proposed = str(proposed or "").strip(" ,;:-")
    if not proposed or proposed == old:
        return None
    return proposed, technique


def generate_candidates(
    db: Db,
    *,
    source: str = "",
    include_hidden: bool = True,
    limit: int = 0,
) -> tuple[int, list[TitleAuditCandidate]]:
    params: list[object] = []
    where: list[str] = []
    src = str(source or "").strip().lower()
    if src:
        where.append("source = ?")
        params.append(src)
    if not include_hidden:
        where.append("coalesce(triage_status, '') != 'hidden'")
    where_sql = f" where {' and '.join(where)}" if where else ""
    limit_sql = ""
    if limit and int(limit) > 0:
        limit_sql = " limit ?"
        params.append(int(limit))
    sql = (
        "select id, source, title, source_ref, ai_summary, seo_alt_text "
        f"from assets{where_sql} order by imported_at asc, id asc{limit_sql}"
    )
    rows = db.query(sql, tuple(params))
    out: list[TitleAuditCandidate] = []
    for row in rows:
        proposal = propose_title(
            source=str(row["source"] or ""),
            old_title=str(row["title"] or ""),
            source_ref=str(row["source_ref"] or ""),
            ai_summary=str(row["ai_summary"] or ""),
            seo_alt_text=str(row["seo_alt_text"] or ""),
        )
        if not proposal:
            continue
        proposed_title, technique = proposal
        out.append(
            TitleAuditCandidate(
                asset_id=str(row["id"]),
                old_title=str(row["title"] or ""),
                new_title=proposed_title,
                technique_used=technique,
            )
        )
    return len(rows), out


def write_markdown_table(path: Path, candidates: list[TitleAuditCandidate]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        f.write("# AI Title Impact Table\n\n")
        f.write(f"Total candidate rows: {len(candidates)}\n\n")
        f.write("| old title | new title | technique_used |\n")
        f.write("|---|---|---|\n")
        for c in candidates:
            old = str(c.old_title or "").replace("|", "\\|").replace("\n", " ").strip()
            new = str(c.new_title or "").replace("|", "\\|").replace("\n", " ").strip()
            tech = str(c.technique_used or "").replace("|", "\\|").strip()
            f.write(f"| {old} | {new} | {tech} |\n")


def run_title_audit(
    db: Db,
    *,
    source: str = "",
    include_hidden: bool = True,
    limit: int = 0,
    table_out: Path | None = None,
) -> dict:
    total_scanned, candidates = generate_candidates(
        db,
        source=source,
        include_hidden=include_hidden,
        limit=limit,
    )
    technique_counts = Counter(c.technique_used for c in candidates)
    if table_out:
        write_markdown_table(table_out, candidates)
    return {
        "ok": True,
        "total_scanned": int(total_scanned),
        "candidate_count": len(candidates),
        "source_filter": str(source or ""),
        "include_hidden": bool(include_hidden),
        "limit": int(limit or 0),
        "table_out": str(table_out) if table_out else "",
        "technique_counts": dict(sorted(technique_counts.items(), key=lambda kv: kv[0])),
        "candidates": [
            {
                "asset_id": c.asset_id,
                "old_title": c.old_title,
                "new_title": c.new_title,
                "technique_used": c.technique_used,
            }
            for c in candidates
        ],
    }


def _batch_summary(db: Db, batch_id: str) -> dict[str, Any]:
    row = db.query(
        """
        select id, created_at, source_filter, include_hidden, limit_requested,
               total_scanned, candidate_count, status, actor, notes, applied_at, undone_at
        from title_audit_batches
        where id = ?
        limit 1
        """,
        (batch_id,),
    )
    if not row:
        raise ValueError(f"Unknown title-audit batch id: {batch_id}")
    batch = row[0]
    review_counts = _review_counts_for_batch(db, batch_id)
    applied_count = _active_apply_count(db, batch_id)
    ready_count = int(
        db.query_value(
            """
            select count(*)
            from title_audit_candidates
            where batch_id = ?
              and review_status in ('approved', 'edited')
              and applied_at is null
            """,
            (batch_id,),
        )
        or 0
    )
    return {
        "batch_id": str(batch["id"]),
        "created_at": str(batch["created_at"]),
        "source_filter": str(batch["source_filter"] or ""),
        "include_hidden": bool(batch["include_hidden"]),
        "limit_requested": int(batch["limit_requested"] or 0),
        "total_scanned": int(batch["total_scanned"] or 0),
        "candidate_count": int(batch["candidate_count"] or 0),
        "status": str(batch["status"] or ""),
        "actor": str(batch["actor"] or ""),
        "notes": str(batch["notes"] or ""),
        "applied_at": str(batch["applied_at"] or ""),
        "undone_at": str(batch["undone_at"] or ""),
        "review_counts": review_counts,
        "ready_count": ready_count,
        "applied_count": applied_count,
    }


def stage_title_audit_batch(
    db: Db,
    *,
    source: str = "",
    include_hidden: bool = True,
    limit: int = 0,
    actor: str = "cli",
    notes: str = "",
    table_out: Path | None = None,
) -> dict[str, Any]:
    total_scanned, candidates = generate_candidates(
        db,
        source=source,
        include_hidden=include_hidden,
        limit=limit,
    )
    batch_id = _new_batch_id()
    created_at = _now_iso()
    technique_counts = Counter(c.technique_used for c in candidates)

    db.exec(
        """
        insert into title_audit_batches
          (id, created_at, source_filter, include_hidden, limit_requested,
           total_scanned, candidate_count, status, actor, notes)
        values (?, ?, ?, ?, ?, ?, ?, 'staged', ?, ?)
        """,
        (
            batch_id,
            created_at,
            str(source or "").strip(),
            1 if include_hidden else 0,
            int(limit or 0),
            int(total_scanned),
            len(candidates),
            str(actor or "cli"),
            str(notes or ""),
        ),
    )

    if candidates:
        db.executemany(
            """
            insert into title_audit_candidates
              (batch_id, asset_id, old_title, proposed_title, technique_used, review_status)
            values (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    batch_id,
                    c.asset_id,
                    c.old_title,
                    c.new_title,
                    c.technique_used,
                    REVIEW_STATUS_PENDING,
                )
                for c in candidates
            ],
        )

    if table_out:
        write_markdown_table(table_out, candidates)

    summary = _batch_summary(db, batch_id)
    summary.update(
        {
            "ok": True,
            "table_out": str(table_out) if table_out else "",
            "technique_counts": dict(sorted(technique_counts.items(), key=lambda kv: kv[0])),
        }
    )
    return summary


def review_title_audit_batch(
    db: Db,
    *,
    batch_id: str,
    status: str = "",
    limit: int = 100,
    offset: int = 0,
    table_out: Path | None = None,
) -> dict[str, Any]:
    batch = str(batch_id or "").strip()
    if not batch:
        raise ValueError("batch_id is required")
    _assert_batch_exists(db, batch)

    filter_sql, filter_params = _candidate_filter_sql(status)
    lim = int(limit or 0)
    off = int(offset or 0)
    if lim <= 0:
        lim = 100

    rows = db.query(
        f"""
        select c.id, c.asset_id, c.old_title, c.proposed_title, c.technique_used,
               c.review_status, c.review_note, c.reviewed_at, c.applied_at,
               a.title as live_title
        from title_audit_candidates c
        left join assets a on a.id = c.asset_id
        where c.batch_id = ?{filter_sql}
        order by c.id asc
        limit ? offset ?
        """,
        (batch, *filter_params, lim, off),
    )
    total_rows = int(
        db.query_value(
            f"""
            select count(*)
            from title_audit_candidates c
            where c.batch_id = ?{filter_sql}
            """,
            (batch, *filter_params),
        )
        or 0
    )

    candidates = [
        {
            "asset_id": str(row["asset_id"]),
            "old_title": str(row["old_title"] or ""),
            "new_title": str(row["proposed_title"] or ""),
            "technique_used": str(row["technique_used"] or ""),
            "review_status": str(row["review_status"] or ""),
            "review_note": str(row["review_note"] or ""),
            "reviewed_at": str(row["reviewed_at"] or ""),
            "applied_at": str(row["applied_at"] or ""),
            "live_title": str(row["live_title"] or ""),
        }
        for row in rows
    ]

    if table_out:
        write_markdown_table(
            table_out,
            [
                TitleAuditCandidate(
                    asset_id=str(row["asset_id"]),
                    old_title=str(row["old_title"] or ""),
                    new_title=str(row["proposed_title"] or ""),
                    technique_used=str(row["technique_used"] or ""),
                )
                for row in rows
            ],
        )

    summary = _batch_summary(db, batch)
    summary.update(
        {
            "ok": True,
            "filter_status": str(status or "").strip().lower(),
            "limit": lim,
            "offset": off,
            "rows_returned": len(rows),
            "rows_total": total_rows,
            "table_out": str(table_out) if table_out else "",
            "candidates": candidates,
        }
    )
    return summary


def mark_title_audit_candidates(
    db: Db,
    *,
    batch_id: str,
    status: str,
    asset_ids: list[str] | None = None,
    mark_all: bool = False,
    where_status: str = "",
    note: str = "",
) -> dict[str, Any]:
    batch = str(batch_id or "").strip()
    if not batch:
        raise ValueError("batch_id is required")
    _assert_batch_exists(db, batch)

    target_status = str(status or "").strip().lower()
    if target_status not in REVIEW_STATUSES:
        raise ValueError("status must be pending, approved, rejected, or edited")
    if target_status == REVIEW_STATUS_EDITED:
        raise ValueError("Use title-audit-edit to set edited rows with a specific title.")

    ids = [str(i).strip() for i in list(asset_ids or []) if str(i).strip()]
    now = _now_iso()
    changed = 0
    matched = 0
    mode = "ids"
    where_status_val = str(where_status or "").strip().lower()
    filter_sql = ""
    filter_params: tuple[object, ...] = ()
    if where_status_val:
        if where_status_val == "applied":
            raise ValueError("where_status=applied is not valid for mark operations")
        filter_sql, filter_params = _candidate_filter_sql(where_status_val)
        filter_sql = filter_sql.replace(" and c.", " and ")

    if ids:
        placeholders = ",".join(["?"] * len(ids))
        matched = int(
            db.query_value(
                f"""
                select count(*)
                from title_audit_candidates
                where batch_id = ? and asset_id in ({placeholders}) and applied_at is null
                """,
                (batch, *ids),
            )
            or 0
        )
        db.exec(
            f"""
            update title_audit_candidates
            set review_status = ?, review_note = ?, reviewed_at = ?
            where batch_id = ? and asset_id in ({placeholders}) and applied_at is null
            """,
            (target_status, str(note or ""), now, batch, *ids),
        )
        changed = int(db.query_value("select changes()") or 0)
    elif mark_all:
        mode = "all"
        matched = int(
            db.query_value(
                f"""
                select count(*)
                from title_audit_candidates
                where batch_id = ? and applied_at is null{filter_sql}
                """,
                (batch, *filter_params),
            )
            or 0
        )
        db.exec(
            f"""
            update title_audit_candidates
            set review_status = ?, review_note = ?, reviewed_at = ?
            where batch_id = ? and applied_at is null{filter_sql}
            """,
            (target_status, str(note or ""), now, batch, *filter_params),
        )
        changed = int(db.query_value("select changes()") or 0)
    else:
        raise ValueError("Provide --asset-id values or pass --all.")

    summary = _batch_summary(db, batch)
    requested = len(ids) if ids else matched
    summary.update(
        {
            "ok": True,
            "mode": mode,
            "status_set": target_status,
            "where_status": where_status_val,
            "note": str(note or ""),
            "asset_ids_requested": len(ids),
            "matched_unapplied": matched,
            "updated": changed,
            "skipped_missing_or_applied": max(0, requested - changed),
        }
    )
    return summary


def edit_title_audit_candidate(
    db: Db,
    *,
    batch_id: str,
    asset_id: str,
    new_title: str,
    note: str = "",
) -> dict[str, Any]:
    batch = str(batch_id or "").strip()
    aid = str(asset_id or "").strip()
    proposed = str(new_title or "").strip(" ,;:-")
    if not batch:
        raise ValueError("batch_id is required")
    if not aid:
        raise ValueError("asset_id is required")
    if not proposed:
        raise ValueError("new_title is required")
    _assert_batch_exists(db, batch)

    row = db.query(
        """
        select old_title, proposed_title, review_status, applied_at
        from title_audit_candidates
        where batch_id = ? and asset_id = ?
        limit 1
        """,
        (batch, aid),
    )
    if not row:
        raise ValueError(f"Asset {aid} is not in title-audit batch {batch}")
    current = row[0]
    if current["applied_at"]:
        raise ValueError("Cannot edit an already-applied row. Undo the batch first.")

    now = _now_iso()
    db.exec(
        """
        update title_audit_candidates
        set proposed_title = ?, review_status = ?, review_note = ?, reviewed_at = ?
        where batch_id = ? and asset_id = ?
        """,
        (proposed, REVIEW_STATUS_EDITED, str(note or ""), now, batch, aid),
    )

    summary = _batch_summary(db, batch)
    summary.update(
        {
            "ok": True,
            "asset_id": aid,
            "old_title": str(current["old_title"] or ""),
            "previous_new_title": str(current["proposed_title"] or ""),
            "new_title": proposed,
            "previous_status": str(current["review_status"] or ""),
            "status_set": REVIEW_STATUS_EDITED,
            "note": str(note or ""),
        }
    )
    return summary


def apply_title_audit_batch(
    db: Db,
    *,
    batch_id: str,
    dry_run: bool = False,
    force: bool = False,
    limit: int = 0,
) -> dict[str, Any]:
    batch = str(batch_id or "").strip()
    if not batch:
        raise ValueError("batch_id is required")
    _assert_batch_exists(db, batch)

    lim = int(limit or 0)
    limit_sql = ""
    params: list[object] = [batch]
    if lim > 0:
        limit_sql = " limit ?"
        params.append(lim)

    rows = db.query(
        f"""
        select c.asset_id, c.old_title, c.proposed_title, c.review_status, a.title as live_title
        from title_audit_candidates c
        left join assets a on a.id = c.asset_id
        where c.batch_id = ?
          and c.review_status in ('approved', 'edited')
          and c.applied_at is null
        order by c.id asc{limit_sql}
        """,
        tuple(params),
    )

    ready = len(rows)
    applied = 0
    conflicts = 0
    missing = 0
    already_matching = 0
    conflict_assets: list[str] = []
    missing_assets: list[str] = []
    applied_assets: list[str] = []
    now = _now_iso()

    for row in rows:
        aid = str(row["asset_id"] or "")
        if not aid:
            continue
        if row["live_title"] is None and db.query_value("select 1 from assets where id = ? limit 1", (aid,)) is None:
            missing += 1
            missing_assets.append(aid)
            continue

        live_title = str(row["live_title"] or "")
        old_title = str(row["old_title"] or "")
        proposed_title = str(row["proposed_title"] or "")

        if not force and live_title != old_title:
            conflicts += 1
            conflict_assets.append(aid)
            continue

        if live_title == proposed_title:
            already_matching += 1
            if dry_run:
                continue

        if dry_run:
            applied += 1
            applied_assets.append(aid)
            continue

        db.exec("update assets set title = ? where id = ?", (proposed_title, aid))
        db.exec(
            """
            update title_audit_candidates
            set applied_at = ?
            where batch_id = ? and asset_id = ?
            """,
            (now, batch, aid),
        )
        db.exec(
            """
            insert into title_audit_applied
              (batch_id, asset_id, old_title, new_title, applied_at, undone_at)
            values (?, ?, ?, ?, ?, null)
            on conflict(batch_id, asset_id)
            do update set old_title=excluded.old_title,
                          new_title=excluded.new_title,
                          applied_at=excluded.applied_at,
                          undone_at=null
            """,
            (batch, aid, live_title, proposed_title, now),
        )
        applied += 1
        applied_assets.append(aid)

    if not dry_run and applied > 0:
        db.exec(
            "update title_audit_batches set status = 'applied', applied_at = ?, undone_at = null where id = ?",
            (now, batch),
        )

    summary = _batch_summary(db, batch)
    summary.update(
        {
            "ok": True,
            "dry_run": bool(dry_run),
            "force": bool(force),
            "limit": lim,
            "ready_count": ready,
            "applied_count": applied,
            "already_matching_count": already_matching,
            "conflict_count": conflicts,
            "missing_count": missing,
            "applied_asset_ids": applied_assets,
            "conflict_asset_ids": conflict_assets,
            "missing_asset_ids": missing_assets,
        }
    )
    return summary


def undo_title_audit_batch(
    db: Db,
    *,
    batch_id: str,
    dry_run: bool = False,
    force: bool = False,
    limit: int = 0,
) -> dict[str, Any]:
    batch = str(batch_id or "").strip()
    if not batch:
        raise ValueError("batch_id is required")
    _assert_batch_exists(db, batch)

    lim = int(limit or 0)
    limit_sql = ""
    params: list[object] = [batch]
    if lim > 0:
        limit_sql = " limit ?"
        params.append(lim)

    rows = db.query(
        f"""
        select p.asset_id, p.old_title, p.new_title, p.applied_at, a.title as live_title
        from title_audit_applied p
        left join assets a on a.id = p.asset_id
        where p.batch_id = ? and p.undone_at is null
        order by p.id desc{limit_sql}
        """,
        tuple(params),
    )

    undo_ready = len(rows)
    undone = 0
    conflicts = 0
    missing = 0
    conflict_assets: list[str] = []
    missing_assets: list[str] = []
    undone_assets: list[str] = []
    now = _now_iso()

    for row in rows:
        aid = str(row["asset_id"] or "")
        if not aid:
            continue
        if row["live_title"] is None and db.query_value("select 1 from assets where id = ? limit 1", (aid,)) is None:
            missing += 1
            missing_assets.append(aid)
            continue

        live_title = str(row["live_title"] or "")
        applied_title = str(row["new_title"] or "")
        old_title = str(row["old_title"] or "")

        if not force and live_title != applied_title:
            conflicts += 1
            conflict_assets.append(aid)
            continue

        if dry_run:
            undone += 1
            undone_assets.append(aid)
            continue

        db.exec("update assets set title = ? where id = ?", (old_title, aid))
        db.exec(
            """
            update title_audit_applied
            set undone_at = ?
            where batch_id = ? and asset_id = ?
            """,
            (now, batch, aid),
        )
        db.exec(
            """
            update title_audit_candidates
            set applied_at = null
            where batch_id = ? and asset_id = ?
            """,
            (batch, aid),
        )
        undone += 1
        undone_assets.append(aid)

    if not dry_run and undone > 0:
        active_remaining = _active_apply_count(db, batch)
        if active_remaining == 0:
            db.exec(
                "update title_audit_batches set status = 'undone', undone_at = ? where id = ?",
                (now, batch),
            )

    summary = _batch_summary(db, batch)
    summary.update(
        {
            "ok": True,
            "dry_run": bool(dry_run),
            "force": bool(force),
            "limit": lim,
            "undo_ready_count": undo_ready,
            "undone_count": undone,
            "conflict_count": conflicts,
            "missing_count": missing,
            "undone_asset_ids": undone_assets,
            "conflict_asset_ids": conflict_assets,
            "missing_asset_ids": missing_assets,
        }
    )
    return summary
