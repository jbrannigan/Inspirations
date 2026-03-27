from __future__ import annotations

import json
import re
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from .classification_v2 import (
    TRACK_CONSTRUCTION,
    TRACK_IRRELEVANT,
    TRACK_MAINTENANCE,
    TRACK_STYLE,
)
from .db import Db


VERDICT_SUPPORTING = "supporting"
VERDICT_CONFLICTING = "conflicting"
VERDICT_INSUFFICIENT = "insufficient"
VERDICT_PLATFORM_WRAPPER = "platform_wrapper"


FETCHED_STATUSES = {"fetched"}

STYLE_SOURCE_HINTS = (
    "interior design",
    "home decor",
    "paint color",
    "paint colors",
    "greige",
    "living room",
    "bedroom",
    "bathroom",
    "kitchen",
    "entryway",
    "mudroom",
    "porch",
    "patio",
    "staircase",
    "porch swing",
    "door hardware",
    "faucet",
    "tile",
    "cabinet",
    "cabinetry",
    "wallpaper",
    "lighting",
    "stone",
    "decor",
    "furniture",
    "styling",
    "zillow",
    "real estate",
    "home details",
    "property listing",
    "listing",
)

CONSTRUCTION_SOURCE_HINTS = (
    "builder",
    "builders",
    "construction",
    "inspection",
    "inspector",
    "generator enclosure",
    "generator",
    "foundation",
    "foundation repair",
    "drainage",
    "drain",
    "roof",
    "roof vent",
    "window",
    "flashing",
    "zip system",
    "sheathing",
    "insulation",
    "water monitor",
    "water shut off",
    "shut off",
    "plumbing",
    "electrical",
    "hvac",
    "duct",
    "frozen pipes",
    "bursting pipes",
)

MAINTENANCE_SOURCE_HINTS = (
    "maintenance",
    "repair",
    "fix",
    "prevent",
    "winterize",
    "pest",
    "frozen pipes",
    "bursting",
    "clogged drain",
    "how to fix",
)

IRRELEVANT_SOURCE_HINTS = (
    "recipe",
    "food",
    "diet",
    "workout",
    "exercise",
    "fitness",
    "makeup",
    "beauty",
    "cosmetics",
    "skincare",
    "movie",
    "music",
    "celebrity",
    "astrology",
    "health",
    "game",
)

STYLE_DOMAINS = (
    "houzz.com",
    "zillow.com",
    "julieblanner.com",
    "thecreativityexchange.com",
    "photographieinterieure.co",
    "doorware.com",
    "shop.moen.com",
    "patiolane.com",
    "kathykuohome.com",
    "luxebco.com",
)

CONSTRUCTION_DOMAINS = (
    "associationofprofessionalbuilders.com",
    "go.associationofprofessionalbuilders.com",
    "mericametal.com",
    "dufferfoundationrepair.com",
    "drain-it-now.com",
    "protectyourpipes.org",
    "ppc-ca.com",
)

IRRELEVANT_DOMAINS = (
    "epicurious.com",
    "goodrx.com",
    "italymagazine.com",
    "gamesradar.com",
    "hadiaslebanesecuisine.com",
    "awesomefood.familyfreshrecipes.com",
    "mykitsch.com",
    "emuaid.com",
)

INSUFFICIENT_PAGE_TITLES = {"form", "page not found", "access denied", "login"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_space(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _normalize_domain(value: Any) -> str:
    text = _normalize_space(value).lower().strip(".")
    if text.startswith("www."):
        text = text[4:]
    return text


def _contains_hint(text: str, hint: str) -> bool:
    haystack = _normalize_space(text).lower()
    needle = _normalize_space(hint).lower()
    if not haystack or not needle:
        return False
    if " " in needle:
        return needle in haystack
    return re.search(rf"\b{re.escape(needle)}\b", haystack) is not None


def _matching_hints(text: str, hints: tuple[str, ...]) -> list[str]:
    return [hint for hint in hints if _contains_hint(text, hint)]


def _latest_track_run_id(db: Db) -> str:
    value = db.query_value(
        """
        select id
        from classification_runs
        where run_type='track_gate'
        order by created_at desc
        limit 1
        """
    )
    return str(value or "").strip()


def _csv_values(value: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in str(value or "").split(","):
        item = raw.strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def collect_source_link_qc_candidates(
    db: Db,
    *,
    track_run_id: str = "",
    source: str = "",
    limit: int = 0,
) -> tuple[str, list[dict[str, Any]]]:
    resolved_track_run_id = str(track_run_id or "").strip() or _latest_track_run_id(db)
    if not resolved_track_run_id:
        raise RuntimeError("No track_gate run found for source-link QC")

    clauses = ["ata.run_id = ?"]
    params: list[Any] = [resolved_track_run_id]
    sources = _csv_values(source)
    if sources:
        clauses.append("lower(a.source) in (%s)" % ",".join(["?"] * len(sources)))
        params.extend(source.lower() for source in sources)
    clauses.append("(coalesce(a.source_url, '') like 'http%' or coalesce(a.source_ref, '') like 'http%')")
    where = " and ".join(clauses)
    limit_sql = " limit ?" if limit and limit > 0 else ""
    if limit_sql:
        params.append(int(limit))
    rows = db.query(
        f"""
        select
          a.id,
          a.source,
          a.source_ref,
          a.source_url,
          a.source_domain,
          a.title,
          a.board,
          ata.track
        from assets a
        join asset_track_assessments ata
          on ata.asset_id = a.id
        where {where}
        order by a.source asc, a.imported_at desc, a.id asc
        {limit_sql}
        """,
        tuple(params),
    )
    return resolved_track_run_id, [dict(row) for row in rows]


def _load_latest_source_link_enrichment(db: Db, asset_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not asset_ids:
        return {}
    placeholders = ",".join(["?"] * len(asset_ids))
    rows = db.query(
        f"""
        select e.asset_id, e.final_url, e.final_domain, e.canonical_url, e.page_title, e.og_title,
               e.meta_description, e.og_description, e.text_excerpt, e.fetch_status, e.error
        from asset_source_link_enrichment e
        join (
          select asset_id, max(created_at) as max_created_at
          from asset_source_link_enrichment
          where asset_id in ({placeholders})
          group by asset_id
        ) latest
          on latest.asset_id = e.asset_id
         and latest.max_created_at = e.created_at
        where e.asset_id in ({placeholders})
        """,
        tuple(asset_ids + asset_ids),
    )
    return {str(row["asset_id"]): dict(row) for row in rows}


def _domain_score(domain: str, domains: tuple[str, ...]) -> bool:
    return any(domain == item or domain.endswith("." + item) for item in domains)


def _source_page_context(enrichment: dict[str, Any]) -> str:
    return " | ".join(
        _normalize_space(enrichment.get(key, ""))
        for key in ("page_title", "og_title", "meta_description", "og_description", "text_excerpt", "final_domain", "final_url")
        if _normalize_space(enrichment.get(key, ""))
    )


def _infer_track_from_source_page(asset: dict[str, Any], enrichment: dict[str, Any]) -> tuple[str, float, str]:
    fetch_status = str(enrichment.get("fetch_status") or "").strip()
    if fetch_status not in FETCHED_STATUSES:
        return ("", 0.0, "")

    context = _source_page_context(enrichment)
    page_title = _normalize_space(enrichment.get("page_title", "")).lower()
    if not context:
        return ("", 0.0, "No meaningful source-page content was captured.")
    if page_title in INSUFFICIENT_PAGE_TITLES:
        return ("", 0.0, f"Source page title is too generic: {page_title}.")
    if context.startswith("@layer ") or context.startswith(":root{") or context.startswith("function "):
        return ("", 0.0, "Source page content looks like CSS or script boilerplate.")

    domain = _normalize_domain(enrichment.get("final_domain", ""))
    style_matches = _matching_hints(context, STYLE_SOURCE_HINTS)
    construction_matches = _matching_hints(context, CONSTRUCTION_SOURCE_HINTS)
    maintenance_matches = _matching_hints(context, MAINTENANCE_SOURCE_HINTS)
    irrelevant_matches = _matching_hints(context, IRRELEVANT_SOURCE_HINTS)

    scores: Counter[str] = Counter()
    notes: list[str] = []

    if style_matches:
        scores[TRACK_STYLE] += 0.8 + 0.2 * min(4, len(style_matches))
        notes.append(f"style hints: {', '.join(style_matches[:6])}")
    if construction_matches:
        scores[TRACK_CONSTRUCTION] += 0.8 + 0.2 * min(4, len(construction_matches))
        notes.append(f"construction hints: {', '.join(construction_matches[:6])}")
    if maintenance_matches:
        scores[TRACK_MAINTENANCE] += 0.75 + 0.18 * min(4, len(maintenance_matches))
        notes.append(f"maintenance hints: {', '.join(maintenance_matches[:6])}")
    if irrelevant_matches:
        scores[TRACK_IRRELEVANT] += 0.8 + 0.2 * min(4, len(irrelevant_matches))
        notes.append(f"irrelevant hints: {', '.join(irrelevant_matches[:6])}")

    if _domain_score(domain, STYLE_DOMAINS):
        scores[TRACK_STYLE] += 0.7
        notes.append(f"style domain: {domain}")
    if _domain_score(domain, CONSTRUCTION_DOMAINS):
        scores[TRACK_CONSTRUCTION] += 0.7
        notes.append(f"construction domain: {domain}")
    if _domain_score(domain, IRRELEVANT_DOMAINS):
        scores[TRACK_IRRELEVANT] += 0.7
        notes.append(f"irrelevant domain: {domain}")

    if not scores:
        return ("", 0.0, "Source page did not provide enough recognizable home/non-home evidence.")

    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    track, top = ordered[0]
    second = ordered[1][1] if len(ordered) > 1 else 0.0
    margin = float(top) - float(second)
    if top < 0.95 or margin < 0.3:
        return ("", min(0.68, 0.42 + 0.1 * float(top)), "Source-page evidence is mixed or too weak. " + " | ".join(notes[:3]))
    confidence = min(0.98, 0.52 + 0.12 * float(top) + 0.1 * margin)
    return (track, confidence, " | ".join(notes[:4]))


def _assess_source_link(asset: dict[str, Any], enrichment: dict[str, Any]) -> tuple[str, str, float, str, str]:
    current_track = str(asset.get("track") or "").strip()
    fetch_status = str(enrichment.get("fetch_status") or "").strip()
    if fetch_status == "platform_wrapper_skipped":
        return (
            "",
            VERDICT_PLATFORM_WRAPPER,
            0.96,
            "Only a Pinterest/Facebook wrapper URL is available; no direct destination page has been captured yet.",
            fetch_status,
        )
    if not enrichment:
        return (
            "",
            VERDICT_INSUFFICIENT,
            0.4,
            "No source-link enrichment evidence is available yet for this asset.",
            "",
        )
    if fetch_status not in FETCHED_STATUSES:
        error = _normalize_space(enrichment.get("error", ""))
        return (
            "",
            VERDICT_INSUFFICIENT,
            0.5,
            f"Source page could not be fetched cleanly ({fetch_status}). {error}".strip(),
            fetch_status,
        )

    inferred_track, confidence, reason = _infer_track_from_source_page(asset, enrichment)
    if not inferred_track:
        return ("", VERDICT_INSUFFICIENT, confidence, reason, fetch_status)
    if inferred_track == current_track:
        return (inferred_track, VERDICT_SUPPORTING, confidence, f"Source page supports current track. {reason}", fetch_status)
    return (
        inferred_track,
        VERDICT_CONFLICTING,
        confidence,
        f"Source page suggests {inferred_track} instead of {current_track}. {reason}",
        fetch_status,
    )


def run_source_link_qc(
    db: Db,
    *,
    track_run_id: str = "",
    source: str = "",
    limit: int = 0,
    notes: str = "",
) -> dict[str, Any]:
    resolved_track_run_id, candidates = collect_source_link_qc_candidates(
        db,
        track_run_id=track_run_id,
        source=source,
        limit=limit,
    )
    enrichments = _load_latest_source_link_enrichment(db, [str(item["id"]) for item in candidates])

    run_id = str(uuid.uuid4())
    created_at = _now_iso()
    config = {
        "track_run_id": resolved_track_run_id,
        "source": source,
        "limit": int(limit),
    }
    db.exec(
        """
        insert into classification_runs
          (id, schema_version, run_type, model_provider, model_name, prompt_version, config_json, created_at, notes)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            "curation_v2",
            "source_link_qc",
            "heuristic",
            "source_link_consistency_v1",
            "",
            json.dumps(config, sort_keys=True),
            created_at,
            notes or None,
        ),
    )

    verdict_counts: Counter[str] = Counter()
    rows_to_insert: list[tuple[Any, ...]] = []
    examples: list[dict[str, Any]] = []

    for asset in candidates:
        enrichment = enrichments.get(str(asset["id"]), {})
        inferred_track, verdict, confidence, reason, fetch_status = _assess_source_link(asset, enrichment)
        verdict_counts[verdict] += 1
        rows_to_insert.append(
            (
                str(uuid.uuid4()),
                run_id,
                str(asset["id"]),
                str(asset.get("track") or ""),
                inferred_track or None,
                verdict,
                float(confidence),
                reason or None,
                fetch_status or None,
                created_at,
            )
        )
        if len(examples) < 12 and verdict in {VERDICT_CONFLICTING, VERDICT_INSUFFICIENT, VERDICT_PLATFORM_WRAPPER}:
            examples.append(
                {
                    "asset_id": str(asset["id"]),
                    "track": str(asset.get("track") or ""),
                    "inferred_track": inferred_track,
                    "verdict": verdict,
                    "fetch_status": fetch_status,
                    "title": str(asset.get("title") or ""),
                    "reason": reason,
                }
            )

    if rows_to_insert:
        db.executemany(
            """
            insert into asset_source_link_qc
              (id, run_id, asset_id, track, inferred_track, verdict, confidence, reason, fetch_status, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows_to_insert,
        )

    return {
        "ok": True,
        "run_id": run_id,
        "track_run_id": resolved_track_run_id,
        "schema_version": "curation_v2",
        "run_type": "source_link_qc",
        "model_provider": "heuristic",
        "model_name": "source_link_consistency_v1",
        "candidate_count": len(candidates),
        "rows_written": len(rows_to_insert),
        "counts": dict(verdict_counts),
        "examples": examples,
    }
