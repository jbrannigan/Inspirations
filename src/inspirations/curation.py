from __future__ import annotations

import html
import hashlib
import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import Db

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_GEMINI_RECITATION_FALLBACK_MODEL = "gemini-2.0-flash"

TRACK_STYLE = "style_product_decor"
TRACK_CONSTRUCTION = "construction_concern"
TRACK_IRRELEVANT = "irrelevant"

STYLE_ROOMS = {
    "kitchen",
    "bathroom",
    "bedroom",
    "living_room",
    "dining_room",
    "entryway",
    "mudroom",
    "laundry_room",
    "garage",
    "exterior",
    "landscape",
    "other",
}

CONCERN_TYPES = {
    "site_exterior",
    "envelope",
    "structure",
    "mep",
    "plans_code_permits",
    "interiors_execution",
    "other",
}

ROOM_DISPLAY = {
    "kitchen": "Kitchen",
    "bathroom": "Bathroom",
    "bedroom": "Bedroom",
    "living_room": "Living Room",
    "dining_room": "Dining Room",
    "entryway": "Entryway",
    "mudroom": "Mudroom",
    "laundry_room": "Laundry Room",
    "garage": "Garage",
    "exterior": "Exterior",
    "landscape": "Landscape",
    "other": "Other",
}

CONCERN_DISPLAY = {
    "site_exterior": "Site / Exterior",
    "envelope": "Envelope",
    "structure": "Structure",
    "mep": "Mechanical / Electrical / Plumbing",
    "plans_code_permits": "Plans / Code / Permits",
    "interiors_execution": "Interior Execution",
    "other": "Other",
}

IRRELEVANT_HINTS = (
    "recipe",
    "recipes",
    "food",
    "meal",
    "workout",
    "exercise",
    "fitness",
    "makeup",
    "cosmetic",
    "beauty",
)

CONSTRUCTION_HINTS = (
    "construction",
    "builder",
    "building",
    "house plan",
    "floor plan",
    "blueprint",
    "foundation",
    "framing",
    "insulation",
    "hvac",
    "plumb",
    "electrical",
    "wiring",
    "roof",
    "drain",
    "waterproof",
    "masonry",
    "concrete",
    "slab",
    "grading",
    "site prep",
    "permit",
    "code",
    "structural",
    "septic",
)

ROOM_HINTS: dict[str, tuple[str, ...]] = {
    "kitchen": ("kitchen", "backsplash", "cabinet", "pantry"),
    "bathroom": ("bathroom", "vanity", "shower", "bathtub", "toilet"),
    "bedroom": ("bedroom", "nightstand", "headboard"),
    "living_room": ("living room", "family room", "sofa", "fireplace"),
    "dining_room": ("dining room", "dining", "breakfast nook"),
    "entryway": ("entryway", "foyer", "entry"),
    "mudroom": ("mudroom",),
    "laundry_room": ("laundry", "washer", "dryer"),
    "garage": ("garage",),
    "exterior": ("exterior", "facade", "curb appeal", "porch", "siding"),
    "landscape": ("landscape", "garden", "patio", "yard", "outdoor"),
}

CONCERN_HINTS: dict[str, tuple[str, ...]] = {
    "site_exterior": ("grading", "drain", "site prep", "exterior drainage", "erosion", "lot"),
    "envelope": ("roof", "siding", "window", "door", "waterproof", "insulation", "flashing"),
    "structure": ("foundation", "framing", "structural", "beam", "load bearing", "slab"),
    "mep": ("hvac", "plumb", "electrical", "wiring", "mechanical", "duct"),
    "plans_code_permits": ("permit", "code", "inspection", "plan", "blueprint", "specification"),
    "interiors_execution": ("tile layout", "cabinet install", "trim detail", "finish schedule"),
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _csv_values(value: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in str(value or "").split(","):
        v = raw.strip()
        if not v:
            continue
        if v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


def _truncate(text: str, n: int) -> str:
    t = _normalize_space(text)
    if len(t) <= n:
        return t
    return t[: max(0, n - 1)].rstrip() + "…"


def _extract_json_object(text: str) -> dict[str, Any] | None:
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z0-9_-]*", "", cleaned).strip()
        if cleaned.endswith("```"):
            cleaned = cleaned[: -len("```")].strip()
    decoder = json.JSONDecoder()
    try:
        obj, _ = decoder.raw_decode(cleaned)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    for match in re.finditer(r"\{", cleaned):
        try:
            obj, _ = decoder.raw_decode(cleaned[match.start() :])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    return None


def _extract_response_text(resp: dict[str, Any]) -> str:
    text_parts: list[str] = []
    for cand in resp.get("candidates", []) or []:
        for part in (cand.get("content") or {}).get("parts", []) or []:
            if "text" in part:
                text_parts.append(str(part["text"]))
    return "\n".join(text_parts).strip()


def _extract_finish_reasons(resp: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    for cand in resp.get("candidates", []) or []:
        reason = str(cand.get("finishReason") or "").strip()
        if reason and reason not in reasons:
            reasons.append(reason)
    return reasons


def _has_finish_reason(resp: dict[str, Any], reason: str) -> bool:
    target = str(reason or "").strip().upper()
    if not target:
        return False
    return any(r.upper() == target for r in _extract_finish_reasons(resp))


def _gemini_generate_text_json(
    *,
    api_key: str,
    model: str,
    prompt: str,
    temperature: float,
    max_output_tokens: int,
    timeout_s: float,
) -> dict[str, Any]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    gen_configs: list[dict[str, Any]] = [
        {
            "temperature": temperature,
            "maxOutputTokens": max_output_tokens,
            "responseMimeType": "application/json",
            "thinkingConfig": {"thinkingBudget": 0},
        },
        {
            "temperature": temperature,
            "maxOutputTokens": max_output_tokens,
            "responseMimeType": "application/json",
        },
        {
            "temperature": temperature,
            "maxOutputTokens": max_output_tokens,
        },
        {
            "temperature": temperature,
            "maxOutputTokens": min(2048, max_output_tokens),
        },
    ]

    last_exc: Exception | None = None
    for cfg in gen_configs:
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": cfg,
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": api_key,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                return json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="ignore") if hasattr(e, "read") else ""
            # Some API versions reject newer generationConfig fields.
            if "Unknown name" in detail or "Invalid JSON payload" in detail:
                last_exc = RuntimeError(f"Gemini HTTP {e.code}: {detail}")
                continue
            raise RuntimeError(f"Gemini HTTP {e.code}: {detail}") from e
    if last_exc:
        raise last_exc
    raise RuntimeError("Gemini request failed before a response was received")


def _maybe_retry_with_recitation_fallback(
    *,
    api_key: str,
    primary_model: str,
    fallback_model: str | None,
    prompt: str,
    temperature: float,
    max_output_tokens: int,
    timeout_s: float,
) -> tuple[dict[str, Any], str]:
    resp = _gemini_generate_text_json(
        api_key=api_key,
        model=primary_model,
        prompt=prompt,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        timeout_s=timeout_s,
    )
    if not _has_finish_reason(resp, "RECITATION"):
        return resp, primary_model
    fallback = str(fallback_model or "").strip()
    if not fallback or fallback == primary_model:
        return resp, primary_model
    fb_resp = _gemini_generate_text_json(
        api_key=api_key,
        model=fallback,
        prompt=prompt,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        timeout_s=timeout_s,
    )
    return fb_resp, fallback


def _resolve_gemini_api_key(explicit: str = "") -> str:
    key = str(explicit or "").strip() or os.environ.get("GEMINI_API_KEY", "").strip()
    if key:
        return key
    # Exploration spec uses this service name; keep as fallback.
    try:
        proc = subprocess.run(
            ["security", "find-generic-password", "-s", "inspirations_gemini_api_key", "-w"],
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0:
            secret = str(proc.stdout or "").strip()
            if secret:
                return secret
    except Exception:
        pass
    return ""


def _candidate_text_blob(candidate: dict[str, Any]) -> str:
    parts = [
        str(candidate.get("title") or ""),
        str(candidate.get("description") or ""),
        str(candidate.get("board") or ""),
        str(candidate.get("notes") or ""),
        str(candidate.get("ai_summary") or ""),
        " ".join(candidate.get("labels") or []),
    ]
    return _normalize_space(" ".join(parts).lower())


def _normalize_track(value: Any, include: bool) -> str:
    raw = str(value or "").strip().lower()
    if not include:
        return TRACK_IRRELEVANT
    if raw in (TRACK_STYLE, "style", "decor", "style_product", "style-decor"):
        return TRACK_STYLE
    if raw in (TRACK_CONSTRUCTION, "construction", "construction_concern", "concern"):
        return TRACK_CONSTRUCTION
    if raw in (TRACK_IRRELEVANT, "irrelevant", "junk", "exclude"):
        return TRACK_IRRELEVANT
    return TRACK_STYLE


def _normalize_style_room(value: Any, candidate: dict[str, Any]) -> str:
    raw = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    alias = {
        "living": "living_room",
        "livingroom": "living_room",
        "dining": "dining_room",
        "entry": "entryway",
        "foyer": "entryway",
        "laundry": "laundry_room",
        "mud": "mudroom",
        "outdoor": "landscape",
        "garden": "landscape",
    }
    raw = alias.get(raw, raw)
    if raw in STYLE_ROOMS:
        return raw
    blob = _candidate_text_blob(candidate)
    for room, hints in ROOM_HINTS.items():
        if any(h in blob for h in hints):
            return room
    return "other"


def _normalize_concern_type(value: Any, candidate: dict[str, Any]) -> str:
    raw = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    alias = {
        "site": "site_exterior",
        "exterior": "site_exterior",
        "m_e_p": "mep",
        "plans": "plans_code_permits",
        "permits": "plans_code_permits",
        "code": "plans_code_permits",
        "interiors": "interiors_execution",
    }
    raw = alias.get(raw, raw)
    if raw in CONCERN_TYPES:
        return raw
    blob = _candidate_text_blob(candidate)
    for concern, hints in CONCERN_HINTS.items():
        if any(h in blob for h in hints):
            return concern
    return "other"


def _coerce_confidence(value: Any) -> float:
    try:
        x = float(value)
    except Exception:
        return 0.5
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def _coerce_style_rating(value: Any, candidate: dict[str, Any]) -> int:
    try:
        r = int(value)
    except Exception:
        return _heuristic_style_rating(candidate)
    return max(1, min(5, r))


def _heuristic_style_rating(candidate: dict[str, Any]) -> int:
    if str(candidate.get("selection_state") or "pending") == "keeper":
        return 5
    blob = _candidate_text_blob(candidate)
    score = 0
    style_hints = (
        "decor",
        "design",
        "lighting",
        "furniture",
        "tile",
        "cabinet",
        "paint",
        "marble",
        "wood",
        "kitchen",
        "bathroom",
        "living room",
        "bedroom",
    )
    for hint in style_hints:
        if hint in blob:
            score += 1
    if score >= 8:
        return 5
    if score >= 4:
        return 4
    return 3


def _heuristic_classification(candidate: dict[str, Any]) -> dict[str, Any]:
    blob = _candidate_text_blob(candidate)
    if any(h in blob for h in IRRELEVANT_HINTS):
        return {
            "include": False,
            "track": TRACK_IRRELEVANT,
            "style_room": "other",
            "concern_type": "other",
            "machine_rating": None,
            "context_note": "Filtered as non-home content for this report.",
            "classification_reason": "Heuristic irrelevant filter matched non-home keywords.",
            "classification_confidence": 0.85,
        }
    if any(h in blob for h in CONSTRUCTION_HINTS):
        concern_type = _normalize_concern_type("", candidate)
        return {
            "include": True,
            "track": TRACK_CONSTRUCTION,
            "style_room": "other",
            "concern_type": concern_type,
            "machine_rating": None,
            "context_note": "Construction-relevant concern for planning review.",
            "classification_reason": "Heuristic construction filter matched planning/build keywords.",
            "classification_confidence": 0.75,
        }
    room = _normalize_style_room("", candidate)
    return {
        "include": True,
        "track": TRACK_STYLE,
        "style_room": room,
        "concern_type": "other",
        "machine_rating": _heuristic_style_rating(candidate),
        "context_note": "Style/decor direction relevant to room and product selection.",
        "classification_reason": "Defaulted to style/product/decor when no strong concern or junk signals were found.",
        "classification_confidence": 0.6,
    }


def _batch(iterable: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    if size <= 0:
        size = 25
    out: list[list[dict[str, Any]]] = []
    for i in range(0, len(iterable), size):
        out.append(iterable[i : i + size])
    return out


def _compact_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": candidate["asset_id"],
        "source": candidate.get("source"),
        "board": _truncate(str(candidate.get("board") or ""), 90),
        "title": _truncate(str(candidate.get("title") or ""), 220),
        "description": _truncate(str(candidate.get("description") or ""), 280),
        "notes": _truncate(str(candidate.get("notes") or ""), 200),
        "ai_summary": _truncate(str(candidate.get("ai_summary") or ""), 240),
        "labels": [str(x) for x in (candidate.get("labels") or [])[:40]],
    }


def _classify_batch_with_gemini(
    *,
    batch: list[dict[str, Any]],
    api_key: str,
    model: str,
    fallback_model: str,
    timeout_s: float,
) -> tuple[dict[str, dict[str, Any]], str]:
    compact = [_compact_candidate(c) for c in batch]
    prompt = f"""
You are curating home inspiration for two outputs:
1) style/product/decor report
2) construction concerns report

For each input item, decide whether to include it and classify it.
Remove junk that does not support home design or construction planning (e.g., recipes, workouts, beauty content).

Return ONLY JSON with this exact top-level shape:
{{
  "items": [
    {{
      "id": "input id",
      "include": true,
      "track": "style_product_decor | construction_concern | irrelevant",
      "style_room": "kitchen|bathroom|bedroom|living_room|dining_room|entryway|mudroom|laundry_room|garage|exterior|landscape|other",
      "concern_type": "site_exterior|envelope|structure|mep|plans_code_permits|interiors_execution|other",
      "style_rating": 1,
      "context_note": "short reason tailored to the item",
      "classification_reason": "why this track/include decision was made",
      "confidence": 0.0
    }}
  ]
}}

Rules:
- Every returned id must exist in the input.
- Return one object per input id.
- If include=false, use track=irrelevant, style_rating=null.
- style_rating is required only when include=true and track=style_product_decor.
- construction_concern items should focus on risks, systems, code, execution, durability, or build decisions.
- Keep context_note concise (<= 24 words).

Input:
{json.dumps(compact, ensure_ascii=False)}
"""
    resp, used_model = _maybe_retry_with_recitation_fallback(
        api_key=api_key,
        primary_model=model,
        fallback_model=fallback_model,
        prompt=prompt,
        temperature=0.15,
        max_output_tokens=8192,
        timeout_s=timeout_s,
    )
    text = _extract_response_text(resp)
    payload = _extract_json_object(text)
    if not payload or not isinstance(payload.get("items"), list):
        reasons = ",".join(_extract_finish_reasons(resp))
        raise RuntimeError(f"No valid classification JSON in Gemini response (finishReason={reasons or 'n/a'})")
    by_id: dict[str, dict[str, Any]] = {}
    for item in payload.get("items") or []:
        cid = str((item or {}).get("id") or "").strip()
        if not cid:
            continue
        by_id[cid] = dict(item or {})
    return by_id, used_model


def _summarize_group_with_gemini(
    *,
    api_key: str,
    model: str,
    fallback_model: str,
    timeout_s: float,
    kind: str,
    group_key: str,
    items: list[dict[str, Any]],
    sample_size: int,
) -> str:
    sample = [_compact_candidate(c) for c in items[: max(1, sample_size)]]
    if kind == "style":
        instruction = (
            "Write one warm, concrete paragraph describing recurring style direction for this room: "
            "palette, materials, fixtures, forms, and product/decor tendencies."
        )
    else:
        instruction = (
            "Write one concise planning paragraph summarizing construction concerns, risks, "
            "and execution checkpoints for this concern group."
        )
    prompt = f"""
You are summarizing curated home project items.

Group kind: {kind}
Group key: {group_key}

Task:
{instruction}

Return ONLY JSON:
{{
  "summary": "one paragraph"
}}

Input:
{json.dumps(sample, ensure_ascii=False)}
"""
    resp, _ = _maybe_retry_with_recitation_fallback(
        api_key=api_key,
        primary_model=model,
        fallback_model=fallback_model,
        prompt=prompt,
        temperature=0.2,
        max_output_tokens=1024,
        timeout_s=timeout_s,
    )
    payload = _extract_json_object(_extract_response_text(resp))
    summary = _normalize_space(str((payload or {}).get("summary") or ""))
    return summary


def _heuristic_group_summary(kind: str, group_key: str, items: list[dict[str, Any]]) -> str:
    labels: Counter[str] = Counter()
    for item in items:
        for label in item.get("labels") or []:
            lab = str(label or "").strip().lower()
            if lab:
                labels[lab] += 1
    top = [k for k, _ in labels.most_common(6)]
    if kind == "style":
        group = ROOM_DISPLAY.get(group_key, group_key.title())
        if top:
            return f"{group} direction concentrates around {', '.join(top[:4])}, with repeated visual cues and product choices worth carrying into the final design."
        return f"{group} direction shows recurring style signals appropriate for curation."
    group = CONCERN_DISPLAY.get(group_key, group_key.replace("_", " ").title())
    if top:
        return f"{group} concerns repeatedly reference {', '.join(top[:4])}; review these as checklist items during planning and execution."
    return f"{group} includes concerns that should be reviewed during planning and build execution."


def _labels_from_csv(value: Any) -> list[str]:
    raw = str(value or "").strip()
    if not raw:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for part in raw.split("|"):
        v = _normalize_space(part).lower()
        if not v or v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out


def collect_candidates(
    db: Db,
    *,
    triage_status: str = "pending,keeper",
    source: str = "",
    limit: int = 0,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []

    sources = _csv_values(source)
    if sources:
        clauses.append("a.source in (%s)" % ",".join(["?"] * len(sources)))
        params.extend(sources)

    statuses = [s.lower() for s in _csv_values(triage_status)]
    if statuses:
        if "pending" in statuses:
            others = [s for s in statuses if s != "pending"]
            if others:
                clauses.append("(a.triage_status is null or a.triage_status in (%s))" % ",".join(["?"] * len(others)))
                params.extend(others)
            else:
                clauses.append("a.triage_status is null")
        else:
            clauses.append("a.triage_status in (%s)" % ",".join(["?"] * len(statuses)))
            params.extend(statuses)

    hidden_collection_id = db.query_value("select id from collections where lower(name)='hidden' limit 1")
    if hidden_collection_id:
        clauses.append("a.id not in (select asset_id from collection_items where collection_id = ?)")
        params.append(str(hidden_collection_id))

    where = "where " + " and ".join(clauses) if clauses else ""
    limit_sql = "limit ?" if limit and limit > 0 else ""
    if limit_sql:
        params.append(int(limit))

    rows = db.query(
        f"""
        select a.id, a.source, a.source_ref, a.source_url, a.image_url,
               a.title, a.description, a.board, a.notes, a.ai_summary,
               a.creator_name, a.imported_at, a.triage_status,
               (select group_concat(al.label, '|') from asset_labels al where al.asset_id = a.id) as labels_csv
        from assets a
        {where}
        order by a.imported_at desc
        {limit_sql}
        """,
        tuple(params),
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        source_ref = str(row["source_ref"] or "").strip()
        source_url = str(row["source_url"] or "").strip() or source_ref
        triage = str(row["triage_status"] or "").strip().lower() or "pending"
        out.append(
            {
                "asset_id": str(row["id"]),
                "source": str(row["source"] or "").strip().lower(),
                "source_ref": source_ref,
                "source_url": source_url,
                "image_url": str(row["image_url"] or "").strip(),
                "title": str(row["title"] or "").strip(),
                "description": str(row["description"] or "").strip(),
                "board": str(row["board"] or "").strip(),
                "notes": str(row["notes"] or "").strip(),
                "ai_summary": str(row["ai_summary"] or "").strip(),
                "creator_name": str(row["creator_name"] or "").strip(),
                "imported_at": str(row["imported_at"] or "").strip(),
                "selection_state": "keeper" if triage == "keeper" else "pending",
                "labels": _labels_from_csv(row["labels_csv"]),
            }
        )
    return out


def classify_candidates(
    candidates: list[dict[str, Any]],
    *,
    provider: str,
    api_key: str,
    model: str,
    recitation_fallback_model: str,
    batch_size: int,
    timeout_s: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    provider_key = str(provider or "gemini").strip().lower()
    out: list[dict[str, Any]] = []
    model_usage: Counter[str] = Counter()
    warnings: list[str] = []
    total_batches = 0
    fallback_batches = 0
    parse_fail_batches = 0
    gemini_items = 0
    heuristic_items = 0

    if provider_key == "heuristic":
        for candidate in candidates:
            merged = dict(candidate)
            merged.update(_heuristic_classification(candidate))
            out.append(merged)
            heuristic_items += 1
        return out, {
            "provider": "heuristic",
            "total_batches": 0,
            "fallback_batches": 0,
            "parse_fail_batches": 0,
            "gemini_items": 0,
            "heuristic_items": heuristic_items,
            "warnings": warnings,
        }

    for batch in _batch(candidates, batch_size):
        total_batches += 1
        by_id: dict[str, dict[str, Any]] = {}
        used_model = ""
        try:
            by_id, used_model = _classify_batch_with_gemini(
                batch=batch,
                api_key=api_key,
                model=model,
                fallback_model=recitation_fallback_model,
                timeout_s=timeout_s,
            )
            if used_model:
                model_usage[used_model] += 1
            if used_model and used_model != model:
                fallback_batches += 1
        except Exception as e:
            warnings.append(f"Gemini batch fallback to heuristics ({len(batch)} items): {e}")
            parse_fail_batches += 1
            by_id = {}

        for candidate in batch:
            aid = candidate["asset_id"]
            row = by_id.get(aid)
            if row is None:
                merged = dict(candidate)
                merged.update(_heuristic_classification(candidate))
                out.append(merged)
                heuristic_items += 1
                continue

            include = bool(row.get("include"))
            track = _normalize_track(row.get("track"), include=include)
            if track == TRACK_IRRELEVANT:
                include = False
            style_room = _normalize_style_room(row.get("style_room"), candidate)
            concern_type = _normalize_concern_type(row.get("concern_type"), candidate)
            context_note = _truncate(str(row.get("context_note") or "").strip(), 240)
            if not context_note:
                context_note = "Classified by AI curation pass for report inclusion."
            classification_reason = _truncate(str(row.get("classification_reason") or "").strip(), 240)
            if not classification_reason:
                classification_reason = "AI classified based on title, description, board, and tags."
            conf = _coerce_confidence(row.get("confidence"))
            machine_rating: int | None
            if include and track == TRACK_STYLE:
                machine_rating = _coerce_style_rating(row.get("style_rating"), candidate)
            else:
                machine_rating = None

            merged = dict(candidate)
            merged.update(
                {
                    "include": include,
                    "track": track,
                    "style_room": style_room,
                    "concern_type": concern_type,
                    "machine_rating": machine_rating,
                    "context_note": context_note,
                    "classification_reason": classification_reason,
                    "classification_confidence": conf,
                }
            )
            out.append(merged)
            gemini_items += 1

    return out, {
        "provider": "gemini",
        "total_batches": total_batches,
        "fallback_batches": fallback_batches,
        "parse_fail_batches": parse_fail_batches,
        "gemini_items": gemini_items,
        "heuristic_items": heuristic_items,
        "models": dict(model_usage),
        "warnings": warnings[:50],
    }


def organize_items(
    classified: list[dict[str, Any]],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]], dict[str, int]]:
    style_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    concern_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    counts = {
        "included": 0,
        "style": 0,
        "construction": 0,
        "irrelevant": 0,
        "excluded": 0,
    }
    for item in classified:
        include = bool(item.get("include"))
        track = str(item.get("track") or TRACK_IRRELEVANT)
        if not include or track == TRACK_IRRELEVANT:
            counts["excluded"] += 1
            counts["irrelevant"] += 1
            continue
        counts["included"] += 1
        if track == TRACK_CONSTRUCTION:
            key = _normalize_concern_type(item.get("concern_type"), item)
            item["concern_type"] = key
            concern_groups[key].append(item)
            counts["construction"] += 1
            continue
        key = _normalize_style_room(item.get("style_room"), item)
        item["style_room"] = key
        if item.get("machine_rating") is None:
            item["machine_rating"] = _heuristic_style_rating(item)
        style_groups[key].append(item)
        counts["style"] += 1

    for room_items in style_groups.values():
        room_items.sort(
            key=lambda x: (
                0 if str(x.get("selection_state") or "") == "keeper" else 1,
                -int(x.get("machine_rating") or 0),
                str(x.get("asset_id") or ""),
            )
        )
    for concern_items in concern_groups.values():
        concern_items.sort(
            key=lambda x: (
                str(x.get("source") or "").lower(),
                str(x.get("board") or "").lower(),
                str(x.get("title") or "").lower(),
                str(x.get("asset_id") or ""),
            )
        )
    return dict(style_groups), dict(concern_groups), counts


def _source_url_for_export(item: dict[str, Any]) -> str:
    for key in ("source_url", "source_ref", "image_url"):
        value = str(item.get(key) or "").strip()
        if value:
            return value
    return ""


def _description_for_export(item: dict[str, Any]) -> str:
    for key in ("context_note", "description", "ai_summary", "title"):
        value = _normalize_space(str(item.get(key) or ""))
        if value:
            return value
    return "No description available."


def _stars(rating: int) -> str:
    return "★" * max(0, int(rating or 0))


def _style_item_payload(item: dict[str, Any]) -> dict[str, Any]:
    asset_id = str(item.get("asset_id") or "")
    rating = int(item.get("machine_rating") or 3)
    return {
        "id": asset_id,
        "assetId": asset_id,
        "imageUrl": f"/media/{asset_id}?kind=thumb",
        "detailImageUrl": f"/media/{asset_id}?kind=original",
        "sourceUrl": _source_url_for_export(item),
        "rating": _stars(rating),
        "ratingValue": rating,
        "machineRating": rating,
        "humanRating": None,
        "ratingSource": "machine",
        "description": _description_for_export(item),
        "tags": list(item.get("labels") or []),
        "selectionState": str(item.get("selection_state") or "pending"),
        "classification": TRACK_STYLE,
        "include": True,
        "classificationConfidence": float(item.get("classification_confidence") or 0.5),
        "classificationReason": str(item.get("classification_reason") or ""),
        "source": str(item.get("source") or ""),
        "board": str(item.get("board") or ""),
    }


def _stable_unit(*parts: str) -> float:
    raw = "|".join(str(p or "") for p in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).digest()
    whole = int.from_bytes(digest[:8], byteorder="big", signed=False)
    return whole / float((1 << 64) - 1)


def _pair_key(a: str, b: str) -> str:
    aa = str(a or "").strip()
    bb = str(b or "").strip()
    if aa <= bb:
        return f"{aa}|{bb}"
    return f"{bb}|{aa}"


def _load_pairwise_votes(path: str) -> tuple[dict[str, str], list[str]]:
    path_value = str(path or "").strip()
    if not path_value:
        return {}, []
    vote_path = Path(path_value).expanduser()
    if not vote_path.is_file():
        return {}, [f"Pairwise votes file not found: {vote_path}"]
    try:
        raw = vote_path.read_text(encoding="utf-8")
    except Exception as e:
        return {}, [f"Failed reading pairwise votes file {vote_path}: {e}"]

    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    stripped = raw.lstrip()
    if not stripped:
        return {}, []
    if stripped[0] in "[{":
        try:
            payload = json.loads(raw)
        except Exception as e:
            return {}, [f"Invalid pairwise votes JSON {vote_path}: {e}"]
        if isinstance(payload, list):
            rows = [x for x in payload if isinstance(x, dict)]
        elif isinstance(payload, dict):
            votes_value = payload.get("votes")
            if isinstance(votes_value, list):
                rows = [x for x in votes_value if isinstance(x, dict)]
            else:
                warnings.append("Pairwise votes JSON object had no list under 'votes'.")
        else:
            warnings.append("Pairwise votes JSON root was not list/dict.")
    else:
        for lineno, line in enumerate(raw.splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception as e:
                warnings.append(f"Skipping invalid pairwise vote line {lineno}: {e}")
                continue
            if isinstance(obj, dict):
                rows.append(obj)
            else:
                warnings.append(f"Skipping non-object pairwise vote line {lineno}.")

    votes: dict[str, str] = {}
    for row in rows:
        left = str(row.get("left") or row.get("a") or row.get("idA") or "").strip()
        right = str(row.get("right") or row.get("b") or row.get("idB") or "").strip()
        if not left or not right or left == right:
            continue
        winner_raw = str(
            row.get("winner")
            or row.get("result")
            or row.get("choice")
            or row.get("winnerAssetId")
            or ""
        ).strip()
        if not winner_raw:
            continue
        winner_norm = winner_raw.lower()
        winner_value = ""
        if winner_norm in {"left", "a"}:
            winner_value = left
        elif winner_norm in {"right", "b"}:
            winner_value = right
        elif winner_norm in {"tie", "draw"}:
            winner_value = "__tie__"
        elif winner_norm in {"skip", "none"}:
            continue
        else:
            if winner_raw in {left, right}:
                winner_value = winner_raw
            else:
                warnings.append(
                    f"Skipping pairwise vote with unknown winner '{winner_raw}' for pair ({left}, {right})."
                )
                continue
        votes[_pair_key(left, right)] = winner_value

    return votes, warnings


def _compute_pairwise_item_meta(
    *,
    records: list[tuple[str, dict[str, Any], bool, int, float]],
    max_candidates_per_room: int,
    rounds_per_room: int,
    max_pairs_per_room: int,
    elo_k: float,
    votes_by_pair: dict[str, str],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    by_room: dict[str, list[tuple[str, dict[str, Any], bool, int, float]]] = defaultdict(list)
    for rec in records:
        by_room[rec[0]].append(rec)

    item_meta: dict[str, dict[str, Any]] = {}
    baseline_score: dict[str, float] = {}
    room_stats: dict[str, dict[str, int]] = {}
    pair_keys_used: set[str] = set()
    compared_items: set[str] = set()
    total_pairs = 0
    total_human_pairs = 0
    total_auto_pairs = 0
    max_candidates = max(0, int(max_candidates_per_room or 0))
    max_pairs = max(0, int(max_pairs_per_room or 0))
    rounds = max(1, int(rounds_per_room or 1))
    k_factor = float(elo_k or 24.0)
    if k_factor < 1.0:
        k_factor = 1.0

    for room, room_records in by_room.items():
        ordered = sorted(
            room_records,
            key=lambda rec: (
                0 if rec[2] else 1,
                -int(rec[3]),
                -float(rec[4]),
                str(rec[1].get("assetId") or rec[1].get("id") or ""),
            ),
        )
        tag_counts: Counter[str] = Counter()
        for rec in ordered:
            for t in rec[1].get("tags") or []:
                tag = _normalize_space(str(t or "").lower())
                if tag:
                    tag_counts[tag] += 1
        dominant_tags = {tag for tag, _n in tag_counts.most_common(6)}

        for rec in ordered:
            aid = str(rec[1].get("assetId") or rec[1].get("id") or "").strip()
            if not aid:
                continue
            raw_tags = {
                _normalize_space(str(t or "").lower())
                for t in (rec[1].get("tags") or [])
                if _normalize_space(str(t or "").lower())
            }
            overlap = len(raw_tags.intersection(dominant_tags))
            base = (
                float(int(rec[3])) * 1.4
                + (1.2 if bool(rec[2]) else 0.0)
                + float(rec[4]) * 2.0
                + min(1.0, overlap * 0.15)
            )
            baseline_score[aid] = base
            item_meta[aid] = {
                "pairwiseScore": 0.5,
                "pairwiseElo": 1000.0 + (base * 30.0),
                "pairwiseComparisons": 0,
                "pairwiseWins": 0,
                "pairwiseLosses": 0,
                "pairwiseTies": 0,
                "pairwiseHumanComparisons": 0,
                "pairwiseAutoComparisons": 0,
                "pairwiseRankInRoom": 0,
            }

        candidate_records = list(ordered)
        if max_candidates > 0 and len(candidate_records) > max_candidates:
            candidate_records = candidate_records[:max_candidates]
        candidate_ids = [
            str(rec[1].get("assetId") or rec[1].get("id") or "").strip()
            for rec in candidate_records
            if str(rec[1].get("assetId") or rec[1].get("id") or "").strip()
        ]
        room_pairs: list[tuple[str, str, str]] = []
        if len(candidate_ids) >= 2:
            rounds_here = min(rounds, len(candidate_ids) - 1)
            seen: set[str] = set()
            stop = False
            for shift in range(1, rounds_here + 1):
                for idx, aid in enumerate(candidate_ids):
                    bid = candidate_ids[(idx + shift) % len(candidate_ids)]
                    if aid == bid:
                        continue
                    key = _pair_key(aid, bid)
                    if key in seen:
                        continue
                    seen.add(key)
                    room_pairs.append((aid, bid, key))
                    if max_pairs > 0 and len(room_pairs) >= max_pairs:
                        stop = True
                        break
                if stop:
                    break

        room_human_pairs = 0
        room_auto_pairs = 0
        for aid, bid, key in room_pairs:
            vote = votes_by_pair.get(key, "")
            pair_keys_used.add(key)
            if vote == "__tie__":
                score_a = 0.5
                source = "human"
                room_human_pairs += 1
            elif vote == aid:
                score_a = 1.0
                source = "human"
                room_human_pairs += 1
            elif vote == bid:
                score_a = 0.0
                source = "human"
                room_human_pairs += 1
            else:
                source = "auto"
                room_auto_pairs += 1
                delta = float(baseline_score.get(aid, 0.0)) - float(baseline_score.get(bid, 0.0))
                if abs(delta) < 0.15:
                    delta += (_stable_unit(key) - 0.5) * 0.20
                if abs(delta) < 0.03:
                    score_a = 0.5
                elif delta > 0:
                    score_a = 1.0
                else:
                    score_a = 0.0

            compared_items.add(aid)
            compared_items.add(bid)
            item_meta[aid]["pairwiseComparisons"] += 1
            item_meta[bid]["pairwiseComparisons"] += 1
            if source == "human":
                item_meta[aid]["pairwiseHumanComparisons"] += 1
                item_meta[bid]["pairwiseHumanComparisons"] += 1
            else:
                item_meta[aid]["pairwiseAutoComparisons"] += 1
                item_meta[bid]["pairwiseAutoComparisons"] += 1

            if score_a >= 0.999:
                item_meta[aid]["pairwiseWins"] += 1
                item_meta[bid]["pairwiseLosses"] += 1
            elif score_a <= 0.001:
                item_meta[aid]["pairwiseLosses"] += 1
                item_meta[bid]["pairwiseWins"] += 1
            else:
                item_meta[aid]["pairwiseTies"] += 1
                item_meta[bid]["pairwiseTies"] += 1

            rating_a = float(item_meta[aid]["pairwiseElo"])
            rating_b = float(item_meta[bid]["pairwiseElo"])
            expect_a = 1.0 / (1.0 + (10.0 ** ((rating_b - rating_a) / 400.0)))
            expect_b = 1.0 - expect_a
            score_b = 1.0 - score_a
            item_meta[aid]["pairwiseElo"] = rating_a + (k_factor * (score_a - expect_a))
            item_meta[bid]["pairwiseElo"] = rating_b + (k_factor * (score_b - expect_b))

        room_all_ids = [
            str(rec[1].get("assetId") or rec[1].get("id") or "").strip()
            for rec in ordered
            if str(rec[1].get("assetId") or rec[1].get("id") or "").strip()
        ]
        room_elo_values = [float(item_meta[aid]["pairwiseElo"]) for aid in room_all_ids] or [1000.0]
        low = min(room_elo_values)
        high = max(room_elo_values)
        for aid in room_all_ids:
            elo_value = float(item_meta[aid]["pairwiseElo"])
            if high > low:
                elo_norm = (elo_value - low) / (high - low)
            else:
                elo_norm = 0.5
            comparisons = int(item_meta[aid]["pairwiseComparisons"] or 0)
            if comparisons > 0:
                wins = int(item_meta[aid]["pairwiseWins"] or 0)
                ties = int(item_meta[aid]["pairwiseTies"] or 0)
                outcome_norm = (float(wins) + (0.5 * float(ties))) / float(comparisons)
                normalized = (0.65 * outcome_norm) + (0.35 * elo_norm)
            else:
                normalized = elo_norm
            normalized += (_stable_unit(room, aid) - 0.5) * 0.0005
            if normalized < 0.0:
                normalized = 0.0
            if normalized > 1.0:
                normalized = 1.0
            item_meta[aid]["pairwiseScore"] = round(normalized, 6)
            item_meta[aid]["pairwiseElo"] = round(elo_value, 3)

        ranked_room_ids = sorted(
            room_all_ids,
            key=lambda aid: (
                -float(item_meta[aid].get("pairwiseScore") or 0.0),
                -float(item_meta[aid].get("pairwiseElo") or 0.0),
                aid,
            ),
        )
        for idx, aid in enumerate(ranked_room_ids, start=1):
            item_meta[aid]["pairwiseRankInRoom"] = idx

        total_pairs += len(room_pairs)
        total_human_pairs += room_human_pairs
        total_auto_pairs += room_auto_pairs
        room_stats[room] = {
            "roomItems": len(room_all_ids),
            "candidateItems": len(candidate_ids),
            "pairs": len(room_pairs),
            "humanPairs": room_human_pairs,
            "autoPairs": room_auto_pairs,
        }

    unused_votes = max(0, len(votes_by_pair) - len(pair_keys_used))
    meta = {
        "rooms": len(room_stats),
        "pairs": total_pairs,
        "humanPairs": total_human_pairs,
        "autoPairs": total_auto_pairs,
        "comparedItems": len(compared_items),
        "votesLoaded": len(votes_by_pair),
        "unusedVotes": unused_votes,
        "roomStats": room_stats,
        "config": {
            "maxCandidatesPerRoom": max_candidates,
            "roundsPerRoom": rounds,
            "maxPairsPerRoom": max_pairs,
            "eloK": round(k_factor, 3),
        },
    }
    return item_meta, meta


def _construction_item_payload(item: dict[str, Any]) -> dict[str, Any]:
    asset_id = str(item.get("asset_id") or "")
    return {
        "id": asset_id,
        "assetId": asset_id,
        "imageUrl": f"/media/{asset_id}?kind=thumb",
        "detailImageUrl": f"/media/{asset_id}?kind=original",
        "sourceUrl": _source_url_for_export(item),
        "description": _description_for_export(item),
        "tags": list(item.get("labels") or []),
        "selectionState": str(item.get("selection_state") or "pending"),
        "classification": TRACK_CONSTRUCTION,
        "include": True,
        "classificationConfidence": float(item.get("classification_confidence") or 0.5),
        "classificationReason": str(item.get("classification_reason") or ""),
        "note": str(item.get("context_note") or ""),
        "concernType": str(item.get("concern_type") or "other"),
        "source": str(item.get("source") or ""),
        "board": str(item.get("board") or ""),
    }


def _synthesize_group_summaries(
    *,
    style_groups: dict[str, list[dict[str, Any]]],
    concern_groups: dict[str, list[dict[str, Any]]],
    summarize: bool,
    provider: str,
    summary_provider: str,
    api_key: str,
    model: str,
    recitation_fallback_model: str,
    timeout_s: float,
    summary_sample_size: int,
) -> tuple[dict[str, str], dict[str, str], list[str]]:
    style_summaries: dict[str, str] = {}
    concern_summaries: dict[str, str] = {}
    warnings: list[str] = []

    summary_provider_key = str(summary_provider or "auto").strip().lower()
    use_gemini = summarize and bool(api_key) and (
        summary_provider_key == "gemini" or (summary_provider_key == "auto" and provider == "gemini")
    )

    for room, items in style_groups.items():
        if use_gemini:
            try:
                summary = _summarize_group_with_gemini(
                    api_key=api_key,
                    model=model,
                    fallback_model=recitation_fallback_model,
                    timeout_s=timeout_s,
                    kind="style",
                    group_key=room,
                    items=items,
                    sample_size=summary_sample_size,
                )
                if summary:
                    style_summaries[room] = summary
                    continue
            except Exception as e:
                warnings.append(f"Style summary fallback for '{room}': {e}")
        style_summaries[room] = _heuristic_group_summary("style", room, items)

    for concern, items in concern_groups.items():
        if use_gemini:
            try:
                summary = _summarize_group_with_gemini(
                    api_key=api_key,
                    model=model,
                    fallback_model=recitation_fallback_model,
                    timeout_s=timeout_s,
                    kind="construction",
                    group_key=concern,
                    items=items,
                    sample_size=summary_sample_size,
                )
                if summary:
                    concern_summaries[concern] = summary
                    continue
            except Exception as e:
                warnings.append(f"Construction summary fallback for '{concern}': {e}")
        concern_summaries[concern] = _heuristic_group_summary("construction", concern, items)

    return style_summaries, concern_summaries, warnings[:100]


def _build_style_document(
    *,
    style_groups: dict[str, list[dict[str, Any]]],
    style_summaries: dict[str, str],
    generated_at: str,
    style_ranking_mode: str,
    best_of_min_rating: int,
    best_of_max_total: int,
    best_of_max_per_room: int,
    best_of_target_per_room: int,
    best_of_tie_max_per_room: int,
    best_of_backfill_if_short: bool,
    best_of_show_all_if_under_target: bool,
    pairwise_votes_path: str,
    pairwise_max_candidates_per_room: int,
    pairwise_rounds_per_room: int,
    pairwise_max_pairs_per_room: int,
    pairwise_elo_k: float,
) -> dict[str, Any]:
    ranking_mode = str(style_ranking_mode or "stars").strip().lower()
    if ranking_mode not in {"stars", "pairwise"}:
        ranking_mode = "stars"
    min_rating = max(1, min(5, int(best_of_min_rating or 4)))
    max_total = max(0, int(best_of_max_total or 0))
    max_per_room = max(0, int(best_of_max_per_room or 0))
    target_per_room = max(0, int(best_of_target_per_room or 0))
    tie_max_per_room = max(0, int(best_of_tie_max_per_room or 0))
    backfill_if_short = bool(best_of_backfill_if_short)
    show_all_if_under_target = bool(best_of_show_all_if_under_target)

    categories: list[dict[str, Any]] = []
    appendix_categories: list[dict[str, Any]] = []
    best_total = 0
    appendix_total = 0
    keeper_total = 0
    eligible_total = 0

    room_payloads: dict[str, list[dict[str, Any]]] = {}
    all_records: list[tuple[str, dict[str, Any], bool, int, float]] = []
    eligible: list[tuple[str, dict[str, Any], bool, int, float]] = []

    sorted_rooms = sorted(style_groups.items(), key=lambda kv: (kv[0] == "other", kv[0]))
    for room, items in sorted_rooms:
        payloads: list[dict[str, Any]] = []
        room_payloads[room] = payloads
        for item in items:
            payload = _style_item_payload(item)
            rating = int(payload["ratingValue"])
            is_keeper = str(payload["selectionState"]) == "keeper"
            if is_keeper:
                keeper_total += 1
            payloads.append(payload)
            record = (
                room,
                payload,
                is_keeper,
                rating,
                float(payload.get("classificationConfidence") or 0.0),
            )
            all_records.append(record)
            if is_keeper or rating >= min_rating:
                eligible.append(record)
    eligible_total = len(eligible)

    pairwise_item_meta: dict[str, dict[str, Any]] = {}
    pairwise_meta: dict[str, Any] = {
        "rooms": 0,
        "pairs": 0,
        "humanPairs": 0,
        "autoPairs": 0,
        "comparedItems": 0,
        "votesLoaded": 0,
        "unusedVotes": 0,
        "roomStats": {},
        "config": {
            "maxCandidatesPerRoom": max(0, int(pairwise_max_candidates_per_room or 0)),
            "roundsPerRoom": max(1, int(pairwise_rounds_per_room or 1)),
            "maxPairsPerRoom": max(0, int(pairwise_max_pairs_per_room or 0)),
            "eloK": float(pairwise_elo_k or 24.0),
        },
    }
    pairwise_warnings: list[str] = []
    if ranking_mode == "pairwise":
        votes_by_pair, vote_warnings = _load_pairwise_votes(pairwise_votes_path)
        pairwise_warnings.extend(vote_warnings)
        pairwise_item_meta, pairwise_meta = _compute_pairwise_item_meta(
            records=all_records,
            max_candidates_per_room=pairwise_max_candidates_per_room,
            rounds_per_room=pairwise_rounds_per_room,
            max_pairs_per_room=pairwise_max_pairs_per_room,
            elo_k=pairwise_elo_k,
            votes_by_pair=votes_by_pair,
        )

    # Rank stronger candidates first, then stable by id for deterministic output.
    def rank_key(rec: tuple[str, dict[str, Any], bool, int, float]) -> tuple[Any, ...]:
        aid = str(rec[1].get("assetId") or rec[1].get("id") or "")
        if ranking_mode == "pairwise":
            p = pairwise_item_meta.get(aid) or {}
            return (
                -float(p.get("pairwiseScore") or 0.0),
                -float(p.get("pairwiseElo") or 0.0),
                0 if rec[2] else 1,
                -rec[3],
                -rec[4],
                aid,
            )
        return (
            0 if rec[2] else 1,
            -rec[3],
            -rec[4],
            aid,
        )

    eligible.sort(key=rank_key)
    all_records.sort(key=rank_key)

    selected_ids: set[str] = set()
    room_selected_counts: dict[str, int] = defaultdict(int)
    all_by_room: dict[str, list[tuple[str, dict[str, Any], bool, int, float]]] = defaultdict(list)
    eligible_by_room: dict[str, list[tuple[str, dict[str, Any], bool, int, float]]] = defaultdict(list)
    ordered_ids_by_room: dict[str, list[str]] = defaultdict(list)
    for rec in all_records:
        all_by_room[rec[0]].append(rec)
        rid = str(rec[1].get("assetId") or rec[1].get("id") or "")
        if rid:
            ordered_ids_by_room[rec[0]].append(rid)
    for rec in eligible:
        eligible_by_room[rec[0]].append(rec)

    def _record_id(rec: tuple[str, dict[str, Any], bool, int, float]) -> str:
        return str(rec[1].get("assetId") or rec[1].get("id") or "")

    def add_record(rec: tuple[str, dict[str, Any], bool, int, float]) -> bool:
        room = rec[0]
        aid = _record_id(rec)
        if not aid or aid in selected_ids:
            return False
        selected_ids.add(aid)
        room_selected_counts[room] += 1
        return True

    # Per-room target mode: top-N for every style category, with optional tie expansion.
    if target_per_room > 0:
        for room, _items in sorted_rooms:
            room_all = list(all_by_room.get(room) or [])
            if not room_all:
                continue
            room_eligible = list(eligible_by_room.get(room) or [])
            if show_all_if_under_target and len(room_all) <= target_per_room:
                for rec in room_all:
                    add_record(rec)
                continue

            picked_room: list[tuple[str, dict[str, Any], bool, int, float]] = []
            for rec in room_eligible:
                if len(picked_room) >= target_per_room:
                    break
                if add_record(rec):
                    picked_room.append(rec)

            if len(picked_room) < target_per_room and backfill_if_short:
                for rec in room_all:
                    if len(picked_room) >= target_per_room:
                        break
                    if add_record(rec):
                        picked_room.append(rec)

            if (
                picked_room
                and len(picked_room) >= target_per_room
                and tie_max_per_room > target_per_room
                and room_selected_counts[room] < tie_max_per_room
            ):
                cutoff_rating = int(picked_room[target_per_room - 1][3])
                for rec in room_all:
                    if room_selected_counts[room] >= tie_max_per_room:
                        break
                    if int(rec[3]) != cutoff_rating:
                        continue
                    add_record(rec)

    else:
        # Global cap mode (legacy/default behavior).
        room_capped_counts: dict[str, int] = defaultdict(int)

        def add_record_with_caps(rec: tuple[str, dict[str, Any], bool, int, float], *, enforce_rating: bool) -> bool:
            room, _payload, is_keeper, rating, _conf = rec
            if enforce_rating and not (is_keeper or rating >= min_rating):
                return False
            if max_per_room > 0 and room_capped_counts[room] >= max_per_room:
                return False
            if max_total > 0 and len(selected_ids) >= max_total:
                return False
            if add_record(rec):
                room_capped_counts[room] += 1
                return True
            return False

        for rec in eligible:
            if max_total > 0 and len(selected_ids) >= max_total:
                break
            add_record_with_caps(rec, enforce_rating=True)

        if max_total > 0 and len(selected_ids) < max_total and backfill_if_short:
            for rec in all_records:
                if len(selected_ids) >= max_total:
                    break
                add_record_with_caps(rec, enforce_rating=False)

        total_style_items = len(all_records)
        if max_total > 0 and len(selected_ids) < max_total and show_all_if_under_target and total_style_items <= max_total:
            selected_ids = {_record_id(rec) for rec in all_records if _record_id(rec)}

    for room, _items in sorted_rooms:
        payloads = room_payloads.get(room) or []
        payload_by_id: dict[str, dict[str, Any]] = {}
        for payload in payloads:
            aid = str(payload.get("assetId") or payload.get("id") or "")
            if aid:
                payload_by_id[aid] = payload
        ordered_payloads: list[dict[str, Any]] = []
        seen_payload_ids: set[str] = set()
        for aid in ordered_ids_by_room.get(room) or []:
            payload = payload_by_id.get(aid)
            if payload is None or aid in seen_payload_ids:
                continue
            ordered_payloads.append(payload)
            seen_payload_ids.add(aid)
        for payload in payloads:
            aid = str(payload.get("assetId") or payload.get("id") or "")
            if aid and aid in seen_payload_ids:
                continue
            ordered_payloads.append(payload)

        best: list[dict[str, Any]] = []
        appendix: list[dict[str, Any]] = []
        for payload in ordered_payloads:
            aid = str(payload.get("assetId") or payload.get("id") or "")
            if ranking_mode == "pairwise" and aid in pairwise_item_meta:
                p = pairwise_item_meta[aid]
                payload.update(
                    {
                        "pairwiseScore": float(p.get("pairwiseScore") or 0.0),
                        "pairwiseElo": float(p.get("pairwiseElo") or 0.0),
                        "pairwiseComparisons": int(p.get("pairwiseComparisons") or 0),
                        "pairwiseWins": int(p.get("pairwiseWins") or 0),
                        "pairwiseLosses": int(p.get("pairwiseLosses") or 0),
                        "pairwiseTies": int(p.get("pairwiseTies") or 0),
                        "pairwiseHumanComparisons": int(p.get("pairwiseHumanComparisons") or 0),
                        "pairwiseAutoComparisons": int(p.get("pairwiseAutoComparisons") or 0),
                        "pairwiseRankInRoom": int(p.get("pairwiseRankInRoom") or 0),
                    }
                )
            if aid in selected_ids:
                best.append(payload)
            else:
                appendix.append(payload)
        best_total += len(best)
        appendix_total += len(appendix)
        category_base = {
            "name": ROOM_DISPLAY.get(room, room.replace("_", " ").title()),
            "description": style_summaries.get(room, ""),
        }
        if best:
            categories.append({**category_base, "items": best})
        if appendix:
            appendix_categories.append({**category_base, "items": appendix})

    return {
        "title": "Curated Style Inspiration (Best Of)",
        "generatedAt": generated_at,
        "categories": categories,
        "appendixCategories": appendix_categories,
        "stats": {
            "categories": len(categories),
            "appendixCategories": len(appendix_categories),
            "bestOfItems": best_total,
            "appendixItems": appendix_total,
            "keeperItems": keeper_total,
            "totalStyleItems": best_total + appendix_total,
            "bestOfEligible": eligible_total,
            "bestOfMinRating": min_rating,
            "bestOfMaxTotal": max_total,
            "bestOfMaxPerRoom": max_per_room,
            "bestOfTargetPerRoom": target_per_room,
            "bestOfTieMaxPerRoom": tie_max_per_room,
            "bestOfBackfillIfShort": backfill_if_short,
            "bestOfShowAllIfUnderTarget": show_all_if_under_target,
            "styleRankingMode": ranking_mode,
            "pairwiseComparedPairs": int(pairwise_meta.get("pairs") or 0),
            "pairwiseHumanPairs": int(pairwise_meta.get("humanPairs") or 0),
            "pairwiseAutoPairs": int(pairwise_meta.get("autoPairs") or 0),
            "pairwiseComparedItems": int(pairwise_meta.get("comparedItems") or 0),
            "pairwiseVotesLoaded": int(pairwise_meta.get("votesLoaded") or 0),
            "pairwiseUnusedVotes": int(pairwise_meta.get("unusedVotes") or 0),
            "pairwiseRooms": int(pairwise_meta.get("rooms") or 0),
            "pairwiseMaxCandidatesPerRoom": int(pairwise_meta.get("config", {}).get("maxCandidatesPerRoom") or 0),
            "pairwiseRoundsPerRoom": int(pairwise_meta.get("config", {}).get("roundsPerRoom") or 0),
            "pairwiseMaxPairsPerRoom": int(pairwise_meta.get("config", {}).get("maxPairsPerRoom") or 0),
            "pairwiseEloK": float(pairwise_meta.get("config", {}).get("eloK") or 0.0),
            "pairwiseWarnings": pairwise_warnings[:50],
        },
    }


def _build_construction_document(
    *,
    concern_groups: dict[str, list[dict[str, Any]]],
    concern_summaries: dict[str, str],
    generated_at: str,
) -> dict[str, Any]:
    categories: list[dict[str, Any]] = []
    total_items = 0
    for concern, items in sorted(concern_groups.items(), key=lambda kv: (kv[0] == "other", kv[0])):
        payload_items = [_construction_item_payload(item) for item in items]
        total_items += len(payload_items)
        categories.append(
            {
                "name": CONCERN_DISPLAY.get(concern, concern.replace("_", " ").title()),
                "description": concern_summaries.get(concern, ""),
                "items": payload_items,
            }
        )
    return {
        "title": "Construction Concerns",
        "generatedAt": generated_at,
        "categories": categories,
        "stats": {
            "categories": len(categories),
            "totalConstructionItems": total_items,
        },
    }


def _with_media_base(url: str, media_base: str) -> str:
    value = str(url or "").strip()
    base = str(media_base or "").strip().rstrip("/")
    if not value:
        return value
    if not base:
        return value
    if value.startswith("/"):
        return f"{base}{value}"
    return value


def _to_existing_file(path: str, *, db_path: Path) -> Path | None:
    raw = str(path or "").strip()
    if not raw:
        return None
    candidate = Path(raw).expanduser()
    checks: list[Path]
    if candidate.is_absolute():
        checks = [candidate]
    else:
        # Stored paths can be relative either to cwd or repo root (parent of data/).
        checks = [Path.cwd() / candidate, db_path.parent.parent / candidate, db_path.parent / candidate]
    for value in checks:
        resolved = value.resolve()
        if resolved.exists() and resolved.is_file():
            return resolved
    return None


def _collect_asset_media_paths(
    *,
    db_path: Path,
    asset_ids: list[str],
) -> dict[str, dict[str, str]]:
    ids = [str(x).strip() for x in asset_ids if str(x).strip()]
    if not ids:
        return {}
    placeholders = ",".join(["?"] * len(ids))
    out: dict[str, dict[str, str]] = {}
    with Db(db_path) as db:
        rows = db.query(
            f"""
            select id, thumb_path, stored_path
            from assets
            where id in ({placeholders})
            """,
            tuple(ids),
        )
    for row in rows:
        aid = str(row["id"])
        thumb_path = str(row["thumb_path"] or "").strip()
        stored_path = str(row["stored_path"] or "").strip()
        thumb = ""
        original = ""
        if thumb_path:
            p = _to_existing_file(thumb_path, db_path=db_path)
            if p is not None:
                thumb = p.as_uri()
        if stored_path:
            p = _to_existing_file(stored_path, db_path=db_path)
            if p is not None:
                original = p.as_uri()
        out[aid] = {"thumb": thumb, "original": original}
    return out


def _resolve_item_media_src(
    *,
    item: dict[str, Any],
    media_base: str,
    asset_media: dict[str, dict[str, str]],
    kind: str,
) -> str:
    asset_id = str(item.get("assetId") or item.get("id") or "").strip()
    if media_base:
        key = "imageUrl" if kind == "thumb" else "detailImageUrl"
        return _with_media_base(str(item.get(key) or ""), media_base)
    if asset_id:
        local = str((asset_media.get(asset_id) or {}).get(kind) or "").strip()
        if local:
            return local
    key = "imageUrl" if kind == "thumb" else "detailImageUrl"
    return str(item.get(key) or "")


def _render_style_html(
    doc: dict[str, Any],
    *,
    media_base: str,
    asset_media: dict[str, dict[str, str]],
) -> str:
    title = html.escape(str(doc.get("title") or "Curated Style Inspiration (Best Of)"))
    generated = html.escape(str(doc.get("generatedAt") or ""))
    categories = doc.get("categories") or []
    appendix_categories = doc.get("appendixCategories") or []

    def render_items(items: list[dict[str, Any]]) -> str:
        if not items:
            return '<p class="muted">No items in this section.</p>'
        cards: list[str] = []
        for item in items:
            img_src = _resolve_item_media_src(
                item=item, media_base=media_base, asset_media=asset_media, kind="thumb"
            )
            detail_src = _resolve_item_media_src(
                item=item, media_base=media_base, asset_media=asset_media, kind="original"
            )
            source_url = str(item.get("sourceUrl") or "").strip()
            desc = html.escape(str(item.get("description") or ""))
            tags = [html.escape(str(t)) for t in (item.get("tags") or [])[:8]]
            rating = html.escape(str(item.get("rating") or ""))
            source = html.escape(str(item.get("source") or ""))
            board = html.escape(str(item.get("board") or ""))
            classification_reason = html.escape(str(item.get("classificationReason") or ""))
            card = f"""
            <article class="card">
              <a href="{html.escape(detail_src or img_src, quote=True)}" target="_blank" rel="noopener noreferrer">
                <img src="{html.escape(img_src, quote=True)}" alt="" loading="lazy" />
              </a>
              <div class="cardBody">
                <div class="metaRow">
                  <span class="rating">{rating or "n/a"}</span>
                  <span class="source">{source or "unknown"}{f" • {board}" if board else ""}</span>
                </div>
                <p class="desc">{desc}</p>
                <p class="reason">{classification_reason}</p>
                <div class="tags">{" ".join(f"<span>#{t}</span>" for t in tags)}</div>
                <div class="links">
                  {f'<a href="{html.escape(source_url, quote=True)}" target="_blank" rel="noopener noreferrer">Source</a>' if source_url else '<span class="muted">No source</span>'}
                </div>
              </div>
            </article>
            """
            cards.append(card)
        return f'<div class="grid">{"".join(cards)}</div>'

    sections: list[str] = []
    appendix_by_name = {str(c.get("name") or ""): c for c in appendix_categories}
    best_room_names: set[str] = set()
    for cat in categories:
        name = str(cat.get("name") or "")
        desc = html.escape(str(cat.get("description") or ""))
        best_items = list(cat.get("items") or [])
        if not best_items:
            continue
        best_room_names.add(name)
        app_items = list((appendix_by_name.get(name) or {}).get("items") or [])
        appendix_block = (
            f"""
              <details>
                <summary>Appendix (non-best style items): {len(app_items)}</summary>
                {render_items(app_items)}
              </details>
            """
            if app_items
            else '<p class="muted">No appendix items for this room.</p>'
        )
        sections.append(
            f"""
            <section class="group">
              <h2>{html.escape(name)}</h2>
              <p class="groupDesc">{desc}</p>
              <h3>Best Of</h3>
              {render_items(best_items)}
              {appendix_block}
            </section>
            """
        )

    appendix_only_sections: list[str] = []
    for cat in appendix_categories:
        name = str(cat.get("name") or "")
        if not name or name in best_room_names:
            continue
        app_items = list(cat.get("items") or [])
        if not app_items:
            continue
        desc = html.escape(str(cat.get("description") or ""))
        appendix_only_sections.append(
            f"""
            <section class="group">
              <h2>{html.escape(name)}</h2>
              <p class="groupDesc">{desc}</p>
              <details>
                <summary>Appendix only room (no top picks in capped Best Of): {len(app_items)}</summary>
                {render_items(app_items)}
              </details>
            </section>
            """
        )

    appendix_only_block = ""
    if appendix_only_sections:
        appendix_only_block = f"""
        <section class="group">
          <h2>Appendix-Only Rooms</h2>
          <p class="groupDesc">These rooms had no items in the capped Best Of selection, but all style items are preserved here.</p>
        </section>
        {"".join(appendix_only_sections)}
        """

    main_sections_html = "".join(sections)
    if not main_sections_html:
        main_sections_html = """
        <section class="group">
          <h2>Best Of</h2>
          <p class="muted">No items selected for Best Of with the current cap/rating policy.</p>
        </section>
        """

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <style>
    :root {{
      --bg: #f6f7f8;
      --panel: #ffffff;
      --text: #1f2933;
      --muted: #52606d;
      --line: #d9e2ec;
      --accent: #334e68;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: "Avenir Next", "Segoe UI", sans-serif; background: var(--bg); color: var(--text); }}
    main {{ width: min(1400px, 95vw); margin: 24px auto 36px; display: grid; gap: 18px; }}
    .hero {{ background: var(--panel); border: 1px solid var(--line); border-radius: 14px; padding: 16px; }}
    h1 {{ margin: 0 0 6px; font-size: 30px; line-height: 1.1; }}
    .muted {{ color: var(--muted); }}
    .group {{ background: var(--panel); border: 1px solid var(--line); border-radius: 14px; padding: 16px; display: grid; gap: 12px; }}
    h2 {{ margin: 0; font-size: 24px; }}
    h3 {{ margin: 8px 0 0; font-size: 16px; color: var(--accent); }}
    .groupDesc {{ margin: 0; color: var(--muted); line-height: 1.5; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(290px, 1fr)); gap: 14px; }}
    .card {{ border: 1px solid var(--line); border-radius: 10px; overflow: hidden; background: #fff; display: grid; }}
    .card img {{ width: 100%; height: 220px; object-fit: cover; background: #eef2f6; display: block; }}
    .cardBody {{ padding: 10px; display: grid; gap: 8px; }}
    .metaRow {{ display: flex; justify-content: space-between; gap: 8px; font-size: 13px; color: var(--muted); }}
    .rating {{ font-weight: 700; letter-spacing: 0.02em; color: #7a5d00; }}
    .desc {{ margin: 0; font-size: 14px; line-height: 1.4; }}
    .reason {{ margin: 0; font-size: 12px; line-height: 1.4; color: var(--muted); }}
    .tags {{ display: flex; flex-wrap: wrap; gap: 6px; font-size: 12px; color: var(--accent); }}
    .tags span {{ background: #eef4fb; border: 1px solid #d6e4f1; border-radius: 999px; padding: 2px 8px; }}
    .links a {{ font-size: 13px; color: #2f5d8a; text-decoration: none; }}
    .links a:hover {{ text-decoration: underline; }}
    details {{ border-top: 1px solid var(--line); padding-top: 10px; }}
    summary {{ cursor: pointer; color: var(--accent); font-weight: 600; }}
  </style>
</head>
<body>
  <main>
    <section class="hero">
      <h1>{title}</h1>
      <p class="muted">Generated: {generated}</p>
      <p class="muted">Primary curation plus full style appendix.</p>
    </section>
    {main_sections_html}
    {appendix_only_block}
  </main>
</body>
</html>
"""


def _render_construction_html(
    doc: dict[str, Any],
    *,
    media_base: str,
    asset_media: dict[str, dict[str, str]],
) -> str:
    title = html.escape(str(doc.get("title") or "Construction Concerns"))
    generated = html.escape(str(doc.get("generatedAt") or ""))
    categories = doc.get("categories") or []

    sections: list[str] = []
    nav_links: list[str] = []

    def _anchor_id(name: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", str(name or "").lower()).strip("-")
        return slug or "group"

    for cat in categories:
        raw_name = str(cat.get("name") or "")
        name = html.escape(raw_name)
        section_id = _anchor_id(raw_name)
        desc = html.escape(str(cat.get("description") or ""))
        items = sorted(
            list(cat.get("items") or []),
            key=lambda x: (
                str(x.get("source") or "").lower(),
                str(x.get("board") or "").lower(),
                str(x.get("description") or x.get("note") or "").lower(),
                str(x.get("assetId") or x.get("id") or ""),
            ),
        )
        item_count = len(items)
        open_attr = " open" if item_count <= 120 else ""
        nav_links.append(
            f'<a href="#{html.escape(section_id, quote=True)}">'
            f"<span>{name}</span><strong>{item_count}</strong></a>"
        )
        rows: list[str] = []
        for item in items:
            img_src = _resolve_item_media_src(
                item=item, media_base=media_base, asset_media=asset_media, kind="thumb"
            )
            source_url = str(item.get("sourceUrl") or "").strip()
            reason = html.escape(str(item.get("classificationReason") or ""))
            note = html.escape(str(item.get("note") or item.get("description") or ""))
            source = html.escape(str(item.get("source") or ""))
            board = html.escape(str(item.get("board") or ""))
            rows.append(
                f"""
                <article class="row">
                  <img src="{html.escape(img_src, quote=True)}" alt="" loading="lazy" />
                  <div class="body">
                    <p class="note">{note}</p>
                    <p class="reason">{reason}</p>
                    <p class="meta">{source or "unknown"}{f" • {board}" if board else ""}</p>
                    {f'<a href="{html.escape(source_url, quote=True)}" target="_blank" rel="noopener noreferrer">Source</a>' if source_url else '<span class="muted">No source</span>'}
                  </div>
                </article>
                """
            )
        sections.append(
            f"""
            <section class="group" id="{html.escape(section_id, quote=True)}">
              <div class="groupHead">
                <h2>{name}</h2>
                <span class="count">{item_count} items</span>
              </div>
              <p class="groupDesc">{desc}</p>
              <details{open_attr}>
                <summary>Show items ({item_count})</summary>
                <div class="list">{"".join(rows) if rows else '<p class="muted">No items in this group.</p>'}</div>
              </details>
            </section>
            """
        )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <style>
    :root {{
      --bg: #f4f6f8;
      --panel: #ffffff;
      --text: #102a43;
      --muted: #486581;
      --line: #d9e2ec;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: "Avenir Next", "Segoe UI", sans-serif; background: var(--bg); color: var(--text); }}
    main {{ width: min(1320px, 95vw); margin: 24px auto 36px; display: grid; gap: 18px; }}
    .hero {{ background: var(--panel); border: 1px solid var(--line); border-radius: 14px; padding: 16px; }}
    h1 {{ margin: 0 0 6px; font-size: 30px; line-height: 1.1; }}
    .muted {{ color: var(--muted); }}
    .nav {{ background: var(--panel); border: 1px solid var(--line); border-radius: 14px; padding: 12px; display: grid; gap: 10px; }}
    .navGrid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 8px; }}
    .navGrid a {{ border: 1px solid var(--line); border-radius: 10px; padding: 8px 10px; display: flex; justify-content: space-between; align-items: center; color: var(--text); text-decoration: none; background: #fff; }}
    .navGrid a:hover {{ border-color: #9fb3c8; background: #f7fafc; }}
    .navGrid strong {{ font-size: 12px; color: var(--muted); }}
    .group {{ background: var(--panel); border: 1px solid var(--line); border-radius: 14px; padding: 16px; display: grid; gap: 12px; }}
    h2 {{ margin: 0; font-size: 22px; }}
    .groupHead {{ display: flex; justify-content: space-between; gap: 8px; align-items: baseline; }}
    .count {{ font-size: 12px; color: var(--muted); font-weight: 700; }}
    .groupDesc {{ margin: 0; color: var(--muted); line-height: 1.5; }}
    .list {{ display: grid; gap: 10px; }}
    .row {{ border: 1px solid var(--line); border-radius: 10px; padding: 8px; display: grid; grid-template-columns: 160px 1fr; gap: 10px; background: #fff; }}
    .row img {{ width: 100%; height: 120px; object-fit: cover; border-radius: 6px; background: #eef2f6; }}
    .body {{ display: grid; gap: 6px; align-content: start; }}
    .note {{ margin: 0; font-size: 14px; line-height: 1.4; }}
    .reason {{ margin: 0; font-size: 12px; color: var(--muted); }}
    .meta {{ margin: 0; font-size: 12px; color: var(--muted); }}
    a {{ font-size: 13px; color: #2f5d8a; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    details {{ border-top: 1px solid var(--line); padding-top: 10px; }}
    summary {{ cursor: pointer; color: #334e68; font-weight: 700; }}
    @media (max-width: 760px) {{
      .row {{ grid-template-columns: 1fr; }}
      .row img {{ height: 200px; }}
    }}
  </style>
</head>
<body>
  <main>
    <section class="hero">
      <h1>{title}</h1>
      <p class="muted">Generated: {generated}</p>
      <p class="muted">Construction concerns are kept separate from style star-ranking for planning workflows.</p>
    </section>
    <section class="nav">
      <p class="muted">Categories</p>
      <div class="navGrid">{"".join(nav_links) if nav_links else '<span class="muted">No categories.</span>'}</div>
    </section>
    {"".join(sections)}
  </main>
</body>
</html>
"""


def render_curation_html(
    *,
    out_dir: Path,
    media_base: str = "",
    db_path: Path | None = None,
) -> dict[str, Any]:
    out_path = out_dir.expanduser().resolve()
    style_json_path = out_path / "style-best-of.json"
    construction_json_path = out_path / "construction-concerns.json"
    if not style_json_path.exists():
        raise FileNotFoundError(f"Missing style JSON: {style_json_path}")
    if not construction_json_path.exists():
        raise FileNotFoundError(f"Missing construction JSON: {construction_json_path}")

    style_doc = json.loads(style_json_path.read_text(encoding="utf-8") or "{}")
    construction_doc = json.loads(construction_json_path.read_text(encoding="utf-8") or "{}")
    asset_ids: list[str] = []
    for cat in style_doc.get("categories") or []:
        for item in cat.get("items") or []:
            aid = str(item.get("assetId") or item.get("id") or "").strip()
            if aid:
                asset_ids.append(aid)
    for cat in style_doc.get("appendixCategories") or []:
        for item in cat.get("items") or []:
            aid = str(item.get("assetId") or item.get("id") or "").strip()
            if aid:
                asset_ids.append(aid)
    for cat in construction_doc.get("categories") or []:
        for item in cat.get("items") or []:
            aid = str(item.get("assetId") or item.get("id") or "").strip()
            if aid:
                asset_ids.append(aid)
    unique_ids = sorted(set(asset_ids))
    if db_path is None:
        db_path = Path("data/inspirations.sqlite").resolve()
    asset_media = _collect_asset_media_paths(db_path=db_path, asset_ids=unique_ids)
    style_html_path = out_path / "style-best-of.html"
    construction_html_path = out_path / "construction-concerns.html"
    style_html_path.write_text(
        _render_style_html(style_doc, media_base=media_base, asset_media=asset_media),
        encoding="utf-8",
    )
    construction_html_path.write_text(
        _render_construction_html(construction_doc, media_base=media_base, asset_media=asset_media),
        encoding="utf-8",
    )
    return {
        "ok": True,
        "styleBestOfHtml": str(style_html_path),
        "constructionConcernsHtml": str(construction_html_path),
        "mediaBase": media_base or None,
        "localMediaResolved": bool(not media_base),
    }


def run_curation_pipeline(
    db: Db,
    *,
    out_dir: Path,
    triage_status: str = "pending,keeper",
    source: str = "",
    limit: int = 0,
    provider: str = "gemini",
    summary_provider: str = "auto",
    model: str = DEFAULT_GEMINI_MODEL,
    recitation_fallback_model: str = DEFAULT_GEMINI_RECITATION_FALLBACK_MODEL,
    api_key: str = "",
    batch_size: int = 24,
    timeout_s: float = 90.0,
    summarize: bool = True,
    summary_sample_size: int = 60,
    style_ranking_mode: str = "stars",
    best_of_min_rating: int = 4,
    best_of_max_total: int = 0,
    best_of_max_per_room: int = 0,
    best_of_target_per_room: int = 0,
    best_of_tie_max_per_room: int = 0,
    best_of_backfill_if_short: bool = True,
    best_of_show_all_if_under_target: bool = True,
    pairwise_votes_path: str = "",
    pairwise_max_candidates_per_room: int = 60,
    pairwise_rounds_per_room: int = 5,
    pairwise_max_pairs_per_room: int = 200,
    pairwise_elo_k: float = 24.0,
    render_html: bool = False,
    media_base: str = "",
) -> dict[str, Any]:
    generated_at = _now_iso()
    provider_key = str(provider or "gemini").strip().lower()
    summary_provider_key = str(summary_provider or "auto").strip().lower()
    ranking_mode_key = str(style_ranking_mode or "stars").strip().lower()
    if summary_provider_key not in {"auto", "gemini", "heuristic"}:
        raise ValueError("summary_provider must be one of: auto, gemini, heuristic")
    if ranking_mode_key not in {"stars", "pairwise"}:
        raise ValueError("style_ranking_mode must be one of: stars, pairwise")

    summary_requests_gemini = summarize and (
        summary_provider_key == "gemini" or (summary_provider_key == "auto" and provider_key == "gemini")
    )
    key = _resolve_gemini_api_key(api_key) if (provider_key == "gemini" or summary_requests_gemini) else ""
    if provider_key == "gemini" and not key:
        raise ValueError(
            "Gemini API key required for provider=gemini (set GEMINI_API_KEY, pass --api-key, "
            "or store in macOS Keychain service inspirations_gemini_api_key)."
        )
    if summarize and summary_provider_key == "gemini" and not key:
        raise ValueError(
            "Gemini API key required for summary_provider=gemini (set GEMINI_API_KEY, pass --api-key, "
            "or store in macOS Keychain service inspirations_gemini_api_key)."
        )

    candidates = collect_candidates(db, triage_status=triage_status, source=source, limit=limit)
    classified, classify_meta = classify_candidates(
        candidates,
        provider=provider_key,
        api_key=key,
        model=model,
        recitation_fallback_model=recitation_fallback_model,
        batch_size=batch_size,
        timeout_s=timeout_s,
    )
    style_groups, concern_groups, counts = organize_items(classified)
    style_summaries, concern_summaries, summary_warnings = _synthesize_group_summaries(
        style_groups=style_groups,
        concern_groups=concern_groups,
        summarize=summarize,
        provider=provider_key,
        summary_provider=summary_provider_key,
        api_key=key,
        model=model,
        recitation_fallback_model=recitation_fallback_model,
        timeout_s=timeout_s,
        summary_sample_size=summary_sample_size,
    )

    style_doc = _build_style_document(
        style_groups=style_groups,
        style_summaries=style_summaries,
        generated_at=generated_at,
        style_ranking_mode=ranking_mode_key,
        best_of_min_rating=best_of_min_rating,
        best_of_max_total=best_of_max_total,
        best_of_max_per_room=best_of_max_per_room,
        best_of_target_per_room=best_of_target_per_room,
        best_of_tie_max_per_room=best_of_tie_max_per_room,
        best_of_backfill_if_short=best_of_backfill_if_short,
        best_of_show_all_if_under_target=best_of_show_all_if_under_target,
        pairwise_votes_path=pairwise_votes_path,
        pairwise_max_candidates_per_room=pairwise_max_candidates_per_room,
        pairwise_rounds_per_room=pairwise_rounds_per_room,
        pairwise_max_pairs_per_room=pairwise_max_pairs_per_room,
        pairwise_elo_k=pairwise_elo_k,
    )
    construction_doc = _build_construction_document(
        concern_groups=concern_groups,
        concern_summaries=concern_summaries,
        generated_at=generated_at,
    )

    out_path = out_dir.expanduser().resolve()
    out_path.mkdir(parents=True, exist_ok=True)
    style_path = out_path / "style-best-of.json"
    construction_path = out_path / "construction-concerns.json"
    manifest_path = out_path / "curation-manifest.json"

    style_path.write_text(json.dumps(style_doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    construction_path.write_text(
        json.dumps(construction_doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    manifest: dict[str, Any] = {
        "ok": True,
        "generatedAt": generated_at,
        "mode": "hybrid-db-assisted-gemini-led",
        "step6OverrideEnabled": False,
        "note": "Step 6 (human overrides) intentionally deferred for this first-pass run.",
        "provider": provider_key,
        "summaryProvider": summary_provider_key,
        "model": model if provider_key == "gemini" else None,
        "recitationFallbackModel": recitation_fallback_model if provider_key == "gemini" else None,
        "scope": {
            "triageStatus": triage_status,
            "source": source or None,
            "limit": int(limit) if limit and limit > 0 else None,
            "hiddenExcluded": True,
        },
        "bestOfPolicy": {
            "styleRankingMode": str(style_doc.get("stats", {}).get("styleRankingMode") or "stars"),
            "minRating": int(style_doc.get("stats", {}).get("bestOfMinRating") or 0),
            "maxTotal": int(style_doc.get("stats", {}).get("bestOfMaxTotal") or 0),
            "maxPerRoom": int(style_doc.get("stats", {}).get("bestOfMaxPerRoom") or 0),
            "targetPerRoom": int(style_doc.get("stats", {}).get("bestOfTargetPerRoom") or 0),
            "tieMaxPerRoom": int(style_doc.get("stats", {}).get("bestOfTieMaxPerRoom") or 0),
            "backfillIfShort": bool(style_doc.get("stats", {}).get("bestOfBackfillIfShort")),
            "showAllIfUnderTarget": bool(style_doc.get("stats", {}).get("bestOfShowAllIfUnderTarget")),
            "pairwiseVotesPath": str(pairwise_votes_path or "") or None,
            "pairwiseComparedPairs": int(style_doc.get("stats", {}).get("pairwiseComparedPairs") or 0),
            "pairwiseHumanPairs": int(style_doc.get("stats", {}).get("pairwiseHumanPairs") or 0),
            "pairwiseAutoPairs": int(style_doc.get("stats", {}).get("pairwiseAutoPairs") or 0),
            "pairwiseComparedItems": int(style_doc.get("stats", {}).get("pairwiseComparedItems") or 0),
            "pairwiseVotesLoaded": int(style_doc.get("stats", {}).get("pairwiseVotesLoaded") or 0),
            "pairwiseUnusedVotes": int(style_doc.get("stats", {}).get("pairwiseUnusedVotes") or 0),
            "pairwiseRooms": int(style_doc.get("stats", {}).get("pairwiseRooms") or 0),
            "pairwiseMaxCandidatesPerRoom": int(style_doc.get("stats", {}).get("pairwiseMaxCandidatesPerRoom") or 0),
            "pairwiseRoundsPerRoom": int(style_doc.get("stats", {}).get("pairwiseRoundsPerRoom") or 0),
            "pairwiseMaxPairsPerRoom": int(style_doc.get("stats", {}).get("pairwiseMaxPairsPerRoom") or 0),
            "pairwiseEloK": float(style_doc.get("stats", {}).get("pairwiseEloK") or 0.0),
        },
        "counts": {
            "candidates": len(candidates),
            "included": counts["included"],
            "style": counts["style"],
            "construction": counts["construction"],
            "irrelevantOrExcluded": counts["irrelevant"],
            "styleBestOf": int(style_doc.get("stats", {}).get("bestOfItems") or 0),
            "styleAppendix": int(style_doc.get("stats", {}).get("appendixItems") or 0),
            "constructionTotal": int(construction_doc.get("stats", {}).get("totalConstructionItems") or 0),
        },
        "classifyMeta": classify_meta,
        "warnings": [*classify_meta.get("warnings", []), *summary_warnings][:200],
        "files": {
            "styleBestOfJson": str(style_path),
            "constructionConcernsJson": str(construction_path),
            "manifestJson": str(manifest_path),
        },
    }
    if render_html:
        html_report = render_curation_html(out_dir=out_path, media_base=media_base, db_path=db.path)
        manifest["files"].update(
            {
                "styleBestOfHtml": str(html_report["styleBestOfHtml"]),
                "constructionConcernsHtml": str(html_report["constructionConcernsHtml"]),
            }
        )
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest
