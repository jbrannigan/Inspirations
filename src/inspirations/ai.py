from __future__ import annotations

import base64
import json
import math
import os
import re
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .db import Db
from .storage import download_and_attach_originals
from .thumbnails import generate_thumbnails


KEYWORDS = [
    "kitchen",
    "cabinet",
    "cabinets",
    "backsplash",
    "tile",
    "bathroom",
    "vanity",
    "lighting",
    "pendant",
    "sconce",
    "exterior",
    "siding",
    "window",
    "windows",
    "floor",
    "flooring",
    "white oak",
    "oak",
    "brass",
    "hardware",
    "fireplace",
    "mudroom",
    "built-ins",
    "shelves",
    "hood",
    "countertop",
]

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_GEMINI_RECITATION_FALLBACK_MODEL = "gemini-2.0-flash"
DEFAULT_GEMINI_EMBEDDING_MODEL = "gemini-embedding-001"
DEFAULT_GEMINI_PROMPT = """You are an interior design tagging assistant. Analyze the image and return ONLY valid JSON:
{
  "summary": "short, 1-2 sentence description",
  "image_type": "interior | exterior | product | plan | document | other",
  "rooms": [],
  "elements": [],
  "materials": [],
  "colors": [],
  "styles": [],
  "lighting": [],
  "fixtures": [],
  "appliances": [],
  "text_in_image": [],
  "brands_products": [],
  "tags": []
}

Rules:
- Use lowercase strings.
- Use short phrases when helpful (e.g., "white oak", "brass hardware").
- Return JSON only. No markdown. No extra keys.
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_labels(text: str) -> list[str]:
    text = text.lower()
    out: list[str] = []
    for k in KEYWORDS:
        if k in text and k not in out:
            out.append(k)
    return out


def _mime_from_path(path: Path) -> str | None:
    ext = path.suffix.lower()
    if ext in (".jpg", ".jpeg"):
        return "image/jpeg"
    if ext == ".png":
        return "image/png"
    if ext == ".webp":
        return "image/webp"
    if ext == ".gif":
        return "image/gif"
    return None


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z0-9]*", "", stripped)
        stripped = stripped.strip()
        if stripped.endswith("```"):
            stripped = stripped[: -len("```")].strip()
    return stripped


def _extract_json_object(text: str) -> dict[str, Any] | None:
    cleaned = _strip_code_fences(text)
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
        if not reason:
            continue
        if reason not in reasons:
            reasons.append(reason)
    return reasons


def _has_finish_reason(resp: dict[str, Any], reason: str) -> bool:
    target = reason.strip().upper()
    if not target:
        return False
    return any(r.upper() == target for r in _extract_finish_reasons(resp))


def _no_json_error_message(resp: dict[str, Any]) -> str:
    reasons = _extract_finish_reasons(resp)
    if reasons:
        return f"No JSON object in Gemini response (finishReason={','.join(reasons)})"
    return "No JSON object in Gemini response"


def _maybe_retry_with_recitation_fallback(
    *,
    api_key: str,
    primary_model: str,
    fallback_model: str | None,
    prompt: str,
    image_b64: str,
    mime_type: str,
    timeout_s: float = 60.0,
) -> tuple[dict[str, Any], str]:
    resp = _gemini_generate(
        api_key=api_key,
        model=primary_model,
        prompt=prompt,
        image_b64=image_b64,
        mime_type=mime_type,
        timeout_s=timeout_s,
    )
    if not fallback_model:
        return resp, primary_model
    fb_model = fallback_model.strip()
    if not fb_model or fb_model == primary_model:
        return resp, primary_model

    raw_text = _extract_response_text(resp)
    payload = _extract_json_object(raw_text)
    if payload is not None:
        return resp, primary_model
    if not _has_finish_reason(resp, "RECITATION"):
        return resp, primary_model

    fallback_resp = _gemini_generate(
        api_key=api_key,
        model=fb_model,
        prompt=prompt,
        image_b64=image_b64,
        mime_type=mime_type,
        timeout_s=timeout_s,
    )
    return fallback_resp, fb_model


def _normalize_label(label: str) -> str:
    label = re.sub(r"\s+", " ", (label or "").strip().lower())
    label = label.strip(" ,.;:!#*()[]{}<>\"'")
    if len(label) < 2:
        return ""
    return label


def _flatten_ai_labels(payload: dict[str, Any]) -> list[str]:
    buckets = [
        "rooms",
        "elements",
        "materials",
        "colors",
        "styles",
        "lighting",
        "fixtures",
        "appliances",
        "text_in_image",
        "brands_products",
        "tags",
    ]
    labels: list[str] = []
    for key in buckets:
        for item in payload.get(key, []) or []:
            lab = _normalize_label(str(item))
            if lab:
                labels.append(lab)
    image_type = _normalize_label(str(payload.get("image_type") or ""))
    if image_type:
        labels.append(image_type)
    seen: set[str] = set()
    out: list[str] = []
    for lab in labels:
        if lab in seen:
            continue
        seen.add(lab)
        out.append(lab)
    return out


def _log_ai_error(
    db: Db,
    *,
    asset_id: str | None,
    provider: str,
    model: str,
    error: str,
    raw: str | None,
    run_id: str,
    now: str,
) -> None:
    if not asset_id:
        return
    db.exec(
        """
        insert into asset_ai_errors
          (id, asset_id, provider, model, error, raw, run_id, created_at)
        values (?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (str(uuid.uuid4()), asset_id, provider, model, error, raw, run_id, now),
    )


def _gemini_generate(
    *,
    api_key: str,
    model: str,
    prompt: str,
    image_b64: str,
    mime_type: str,
    timeout_s: float = 60.0,
) -> dict[str, Any]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    gen_configs: list[dict[str, Any]] = [
        {
            "temperature": 0.2,
            "maxOutputTokens": 4096,
            "responseMimeType": "application/json",
            "thinkingConfig": {"thinkingBudget": 0},
        },
        {
            "temperature": 0.2,
            "maxOutputTokens": 4096,
            "responseMimeType": "application/json",
        },
        {
            "temperature": 0.2,
            "maxOutputTokens": 4096,
        },
        {
            "temperature": 0.2,
            "maxOutputTokens": 2048,
        },
    ]
    last_exc: Exception | None = None
    for cfg in gen_configs:
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {"inline_data": {"mime_type": mime_type, "data": image_b64}},
                    ]
                }
            ],
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
            # Some API versions reject new generationConfig fields; fall back gracefully.
            if "Unknown name" in detail or "Invalid JSON payload" in detail:
                last_exc = RuntimeError(f"Gemini HTTP {e.code}: {detail}")
                continue
            raise RuntimeError(f"Gemini HTTP {e.code}: {detail}") from e
    if last_exc:
        raise last_exc
    raise RuntimeError("Gemini request failed before a response was received")


def _gemini_embed_text(
    *,
    api_key: str,
    model: str,
    text: str,
    task_type: str = "RETRIEVAL_DOCUMENT",
    timeout_s: float = 60.0,
) -> list[float]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:embedContent"
    payload = {
        "content": {
            "parts": [{"text": text}],
        },
        "taskType": task_type,
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
            data = json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="ignore") if hasattr(e, "read") else ""
        raise RuntimeError(f"Gemini embed HTTP {e.code}: {detail}") from e

    values = (data.get("embedding") or {}).get("values")
    if values is None and isinstance(data.get("embeddings"), list) and data["embeddings"]:
        values = (data["embeddings"][0] or {}).get("values")
    if not isinstance(values, list) or not values:
        raise RuntimeError("No embedding values in Gemini embed response")
    try:
        return [float(v) for v in values]
    except Exception as e:
        raise RuntimeError(f"Invalid embedding values in Gemini response: {e}") from e


def _build_embedding_input_text(row: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("title", "description", "board", "notes", "ai_summary"):
        value = str(row.get(key) or "").strip()
        if value:
            parts.append(value)
    labels_csv = str(row.get("labels_csv") or "").strip()
    if labels_csv:
        labels = [x.strip() for x in labels_csv.split("|") if x.strip()]
        if labels:
            parts.append(f"labels: {', '.join(labels[:80])}")
    text = "\n".join(parts).strip()
    if len(text) > 4000:
        text = text[:4000].strip()
    return text


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / (na * nb)


def _classify_ai_error(error: str, raw: str | None = None) -> str:
    err = (error or "").lower()
    raw_l = (raw or "").lower()
    if "nodename nor servname provided" in err or "temporary failure in name resolution" in err:
        return "network_dns"
    if "no json object" in err:
        if "recitation" in err or ("finishreason" in raw_l and "recitation" in raw_l):
            return "no_json_recitation"
        return "no_json_other"
    if "no image available" in err:
        return "missing_image"
    if "unsupported image type" in err:
        return "unsupported_image"
    if "gemini http" in err:
        return "gemini_http"
    return "other"


def _triage_action_for_error(category: str, resolved_after_error: bool) -> str:
    if resolved_after_error:
        return "historical_resolved"
    if category == "network_dns":
        return "retry_when_network_available"
    if category == "no_json_recitation":
        return "use_fallback_or_alt_model"
    if category == "no_json_other":
        return "inspect_prompt_or_parser"
    if category in {"missing_image", "unsupported_image"}:
        return "repair_media"
    if category == "gemini_http":
        return "inspect_api_response"
    return "manual_investigation"


def run_ai_error_triage(
    db: Db,
    *,
    source: str = "",
    provider: str = "",
    model: str = "",
    days: int = 0,
    limit: int = 0,
    examples_per_action: int = 3,
) -> dict[str, Any]:
    cutoff = ""
    if days > 0:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    clauses: list[str] = []
    params: list[Any] = []
    if source:
        clauses.append("a.source = ?")
        params.append(source)
    if provider:
        clauses.append("e.provider = ?")
        params.append(provider)
    if model:
        clauses.append("coalesce(e.model, '') = ?")
        params.append(model)
    if cutoff:
        clauses.append("e.created_at >= ?")
        params.append(cutoff)
    where = "where " + " and ".join(clauses) if clauses else ""

    sql = f"""
    select e.id, e.asset_id, e.provider, e.model, e.error, e.raw, e.run_id, e.created_at,
           a.source,
           exists(
             select 1
             from asset_ai ai
             where ai.asset_id = e.asset_id
               and ai.provider = e.provider
               and ai.created_at >= e.created_at
           ) as resolved_after_error
    from asset_ai_errors e
    left join assets a on a.id = e.asset_id
    {where}
    order by e.created_at desc
    """
    if limit > 0:
        sql += " limit ?"
        params.append(limit)
    rows = [dict(r) for r in db.query(sql, tuple(params))]

    category_stats: dict[str, dict[str, int]] = {}
    action_stats: dict[str, int] = {}
    examples: dict[str, list[dict[str, Any]]] = {}
    unique_assets: set[str] = set()
    actionable_assets: set[str] = set()
    actionable_errors = 0

    for row in rows:
        asset_id = str(row.get("asset_id") or "").strip()
        if asset_id:
            unique_assets.add(asset_id)
        resolved_after_error = bool(row.get("resolved_after_error"))
        category = _classify_ai_error(str(row.get("error") or ""), row.get("raw"))
        action = _triage_action_for_error(category, resolved_after_error)
        if not resolved_after_error:
            actionable_errors += 1
            if asset_id:
                actionable_assets.add(asset_id)

        if category not in category_stats:
            category_stats[category] = {"total": 0, "actionable": 0, "resolved": 0}
        category_stats[category]["total"] += 1
        if resolved_after_error:
            category_stats[category]["resolved"] += 1
        else:
            category_stats[category]["actionable"] += 1

        action_stats[action] = action_stats.get(action, 0) + 1
        if action not in examples:
            examples[action] = []
        if len(examples[action]) < max(1, examples_per_action):
            examples[action].append(
                {
                    "error_id": row.get("id"),
                    "asset_id": row.get("asset_id"),
                    "source": row.get("source"),
                    "provider": row.get("provider"),
                    "model": row.get("model"),
                    "created_at": row.get("created_at"),
                    "error": row.get("error"),
                    "category": category,
                    "resolved_after_error": resolved_after_error,
                }
            )

    categories = [
        {"category": name, **vals}
        for name, vals in sorted(category_stats.items(), key=lambda kv: (-kv[1]["total"], kv[0]))
    ]
    actions = [
        {"action": name, "count": count}
        for name, count in sorted(action_stats.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    action_examples = [
        {"action": action, "examples": ex}
        for action, ex in sorted(examples.items(), key=lambda kv: kv[0])
    ]

    return {
        "filters": {
            "source": source or None,
            "provider": provider or None,
            "model": model or None,
            "days": days if days > 0 else None,
            "limit": limit if limit > 0 else None,
        },
        "total_errors": len(rows),
        "total_assets": len(unique_assets),
        "actionable_errors": actionable_errors,
        "actionable_assets": len(actionable_assets),
        "categories": categories,
        "actions": actions,
        "examples_by_action": action_examples,
    }


def run_gemini_text_embedder(
    db: Db,
    *,
    api_key: str,
    model: str = DEFAULT_GEMINI_EMBEDDING_MODEL,
    source: str = "",
    limit: int = 0,
    force: bool = False,
) -> dict[str, Any]:
    run_id = str(uuid.uuid4())
    now = _now_iso()
    db.exec(
        "insert into ai_runs (id, provider, model, created_at) values (?, ?, ?, ?)",
        (run_id, "gemini-embed", model, now),
    )

    clauses: list[str] = []
    params: list[Any] = []
    if source:
        clauses.append("a.source = ?")
        params.append(source)
    if not force:
        clauses.append(
            "a.id not in (select asset_id from asset_embeddings where provider=? and model=?)"
        )
        params.extend(["gemini", model])
    where = "where " + " and ".join(clauses) if clauses else ""
    rows = db.query(
        f"""
        select a.id, a.source, a.title, a.description, a.board, a.notes,
               coalesce(
                 (select ai.summary from asset_ai ai where ai.asset_id=a.id order by ai.created_at desc limit 1),
                 a.ai_summary
               ) as ai_summary,
               (select group_concat(al.label, '|') from asset_labels al where al.asset_id=a.id and al.source='ai') as labels_csv
        from assets a
        {where}
        order by a.imported_at asc
        """,
        tuple(params),
    )

    attempted = 0
    embedded = 0
    errors: list[dict[str, str]] = []
    for r in rows:
        if limit and attempted >= limit:
            break
        attempted += 1
        row = dict(r)
        asset_id = row["id"]
        text = _build_embedding_input_text(row)
        if not text:
            errors.append({"id": asset_id, "error": "No text content available for embedding"})
            continue
        try:
            vector = _gemini_embed_text(
                api_key=api_key,
                model=model,
                text=text,
                task_type="RETRIEVAL_DOCUMENT",
            )
            db.exec(
                """
                insert into asset_embeddings
                  (id, asset_id, provider, model, input_text, vector_json, dimensions, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(asset_id, provider, model) do update set
                  input_text=excluded.input_text,
                  vector_json=excluded.vector_json,
                  dimensions=excluded.dimensions,
                  created_at=excluded.created_at
                """,
                (
                    str(uuid.uuid4()),
                    asset_id,
                    "gemini",
                    model,
                    text,
                    json.dumps(vector),
                    len(vector),
                    now,
                ),
            )
            embedded += 1
        except Exception as e:
            errors.append({"id": asset_id, "error": str(e)})

    return {
        "provider": "gemini",
        "model": model,
        "run_id": run_id,
        "attempted": attempted,
        "embedded_assets": embedded,
        "errors": errors[:25],
        "note": "Errors are truncated to 25 in output.",
    }


def run_similarity_search(
    db: Db,
    *,
    api_key: str,
    query: str,
    model: str = DEFAULT_GEMINI_EMBEDDING_MODEL,
    source: str = "",
    limit: int = 25,
) -> dict[str, Any]:
    query_text = (query or "").strip()
    if not query_text:
        raise ValueError("query is required")
    if limit <= 0:
        limit = 25

    query_vec = _gemini_embed_text(
        api_key=api_key,
        model=model,
        text=query_text,
        task_type="RETRIEVAL_QUERY",
    )

    clauses = ["e.provider = ?", "e.model = ?"]
    params: list[Any] = ["gemini", model]
    if source:
        clauses.append("a.source = ?")
        params.append(source)
    where = "where " + " and ".join(clauses)

    rows = db.query(
        f"""
        select e.asset_id, e.vector_json, e.dimensions, e.created_at,
               a.source, a.source_ref, a.title, a.description, a.board, a.notes,
               a.image_url, a.stored_path, a.thumb_path, a.imported_at,
               coalesce(
                 (select ai.summary from asset_ai ai where ai.asset_id=a.id order by ai.created_at desc limit 1),
                 a.ai_summary
               ) as ai_summary,
               (select ai.json from asset_ai ai where ai.asset_id=a.id order by ai.created_at desc limit 1) as ai_json,
               (select ai.model from asset_ai ai where ai.asset_id=a.id order by ai.created_at desc limit 1) as ai_model,
               (select ai.provider from asset_ai ai where ai.asset_id=a.id order by ai.created_at desc limit 1) as ai_provider,
               (select ai.created_at from asset_ai ai where ai.asset_id=a.id order by ai.created_at desc limit 1) as ai_created_at
        from asset_embeddings e
        join assets a on a.id = e.asset_id
        {where}
        """,
        tuple(params),
    )

    scored: list[dict[str, Any]] = []
    skipped_mismatch = 0
    for r in rows:
        try:
            vector = [float(x) for x in json.loads(r["vector_json"] or "[]")]
        except Exception:
            continue
        if len(vector) != len(query_vec):
            skipped_mismatch += 1
            continue
        score = _cosine_similarity(query_vec, vector)
        scored.append(
            {
                "id": r["asset_id"],
                "source": r["source"],
                "source_ref": r["source_ref"],
                "title": r["title"],
                "description": r["description"],
                "board": r["board"],
                "notes": r["notes"],
                "image_url": r["image_url"],
                "stored_path": r["stored_path"],
                "thumb_path": r["thumb_path"],
                "imported_at": r["imported_at"],
                "ai_summary": r["ai_summary"],
                "ai_json": r["ai_json"],
                "ai_model": r["ai_model"],
                "ai_provider": r["ai_provider"],
                "ai_created_at": r["ai_created_at"],
                "score": score,
                "embedding_created_at": r["created_at"],
            }
        )
    scored.sort(key=lambda x: x["score"], reverse=True)

    return {
        "query": query_text,
        "provider": "gemini",
        "model": model,
        "compared_assets": len(scored),
        "skipped_dimension_mismatch": skipped_mismatch,
        "results": scored[:limit],
    }


def run_mock_labeler(db: Db, *, limit: int = 0) -> dict[str, Any]:
    run_id = str(uuid.uuid4())
    db.exec(
        "insert into ai_runs (id, provider, model, created_at) values (?, ?, ?, ?)",
        (run_id, "mock", "keyword-heuristic", _now_iso()),
    )

    rows = db.query(
        "select id, title, board from assets order by imported_at asc"
    )
    attempted = 0
    labeled = 0
    errors: list[dict[str, str]] = []

    for r in rows:
        if limit and attempted >= limit:
            break
        attempted += 1
        asset_id = r["id"]
        text = " ".join([r["title"] or "", r["board"] or ""]).strip()
        if not text:
            continue
        labels = _extract_labels(text)
        if not labels:
            continue
        for lab in labels:
            try:
                db.exec(
                    """
                    insert or ignore into asset_labels
                      (id, asset_id, label, confidence, source, model, run_id, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (str(uuid.uuid4()), asset_id, lab, 0.35, "ai", "keyword-heuristic", run_id, _now_iso()),
                )
            except Exception as e:
                errors.append({"id": asset_id, "error": str(e)})
        labeled += 1

    return {
        "provider": "mock",
        "run_id": run_id,
        "attempted": attempted,
        "labeled_assets": labeled,
        "errors": errors[:25],
        "note": "Errors are truncated to 25 in output.",
    }


def run_gemini_image_labeler(
    db: Db,
    *,
    api_key: str,
    model: str,
    limit: int = 0,
    source: str = "",
    image_kind: str = "thumb",
    force: bool = False,
    store_dir: Path | None = None,
    preflight: bool = True,
    recitation_fallback_model: str | None = None,
) -> dict[str, Any]:
    fallback_model = (
        (recitation_fallback_model or "").strip()
        or os.environ.get("GEMINI_RECITATION_FALLBACK_MODEL", "").strip()
        or DEFAULT_GEMINI_RECITATION_FALLBACK_MODEL
    )
    if fallback_model == model:
        fallback_model = ""

    run_id = str(uuid.uuid4())
    now = _now_iso()
    db.exec(
        "insert into ai_runs (id, provider, model, created_at) values (?, ?, ?, ?)",
        (run_id, "gemini", model, now),
    )

    if preflight:
        store_dir = store_dir or Path("store")
        if source:
            sources = [source]
        else:
            sources = [r["source"] for r in db.query("select distinct source from assets")]
        for src in sources:
            download_and_attach_originals(db, store_dir, src, limit=0)
            if image_kind == "thumb":
                generate_thumbnails(db, store_dir, source=src, limit=0)

    clauses: list[str] = []
    params: list[Any] = []
    if source:
        clauses.append("a.source = ?")
        params.append(source)
    if not force:
        clauses.append(
            "a.id not in (select asset_id from asset_ai where provider=?)"
        )
        params.extend(["gemini"])
    where = "where " + " and ".join(clauses) if clauses else ""
    rows = db.query(
        f"""
        select a.id, a.title, a.description, a.board, a.stored_path, a.thumb_path
        from assets a
        {where}
        order by a.imported_at asc
        """,
        tuple(params),
    )

    attempted = 0
    labeled = 0
    fallback_labeled = 0
    errors: list[dict[str, str]] = []

    for r in rows:
        if limit and attempted >= limit:
            break
        attempted += 1
        asset_id = r["id"]
        preferred = r["thumb_path"] if image_kind == "thumb" else r["stored_path"]
        fallback = r["stored_path"] if image_kind == "thumb" else r["thumb_path"]
        path_str = preferred or fallback
        if not path_str:
            errors.append({"id": asset_id, "error": "No image available for tagging"})
            _log_ai_error(
                db,
                asset_id=asset_id,
                provider="gemini",
                model=model,
                error="No image available for tagging",
                raw=None,
                run_id=run_id,
                now=now,
            )
            continue
        path = Path(path_str)
        mime_type = _mime_from_path(path)
        if not mime_type:
            errors.append({"id": asset_id, "error": f"Unsupported image type: {path.suffix}"})
            _log_ai_error(
                db,
                asset_id=asset_id,
                provider="gemini",
                model=model,
                error=f"Unsupported image type: {path.suffix}",
                raw=str(path),
                run_id=run_id,
                now=now,
            )
            continue
        used_model = model
        raw_error: str | None = None
        try:
            image_b64 = base64.b64encode(path.read_bytes()).decode("ascii")
            resp, used_model = _maybe_retry_with_recitation_fallback(
                api_key=api_key,
                primary_model=model,
                fallback_model=fallback_model,
                prompt=DEFAULT_GEMINI_PROMPT,
                image_b64=image_b64,
                mime_type=mime_type,
            )
            raw_text = _extract_response_text(resp)
            payload = _extract_json_object(raw_text)
            if not payload:
                raw_payload = raw_text if raw_text else json.dumps(resp)
                raw_error = raw_payload[:10000]
                raise RuntimeError(_no_json_error_message(resp))
            summary = str(payload.get("summary") or "").strip()
            db.exec(
                "insert into asset_ai (id, asset_id, provider, model, summary, json, created_at) values (?, ?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), asset_id, "gemini", used_model, summary or None, json.dumps(payload), now),
            )
            if summary:
                db.exec("update assets set ai_summary=? where id=?", (summary, asset_id))
            labels = _flatten_ai_labels(payload)
            for lab in labels:
                db.exec(
                    """
                    insert or ignore into asset_labels
                      (id, asset_id, label, confidence, source, model, run_id, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (str(uuid.uuid4()), asset_id, lab, 0.7, "ai", used_model, run_id, now),
                )
            labeled += 1
            if used_model != model:
                fallback_labeled += 1
        except Exception as e:
            errors.append({"id": asset_id, "error": str(e)})
            _log_ai_error(
                db,
                asset_id=asset_id,
                provider="gemini",
                model=used_model,
                error=str(e),
                raw=raw_error,
                run_id=run_id,
                now=now,
            )

    return {
        "provider": "gemini",
        "model": model,
        "recitation_fallback_model": fallback_model or None,
        "run_id": run_id,
        "attempted": attempted,
        "labeled_assets": labeled,
        "fallback_labeled_assets": fallback_labeled,
        "errors": errors[:25],
        "note": "Errors are truncated to 25 in output.",
    }


def run_ai_labeler(db: Db, *, provider: str, limit: int = 0, **kwargs: Any) -> dict[str, Any]:
    provider = provider.lower()
    if provider == "mock":
        return run_mock_labeler(db, limit=limit)
    if provider == "gemini":
        api_key = kwargs.get("api_key") or os.environ.get("GEMINI_API_KEY") or ""
        if not api_key:
            raise ValueError("Gemini API key required (set GEMINI_API_KEY or pass --api-key)")
        model = kwargs.get("model") or DEFAULT_GEMINI_MODEL
        return run_gemini_image_labeler(
            db,
            api_key=api_key,
            model=model,
            limit=limit,
            source=kwargs.get("source") or "",
            image_kind=kwargs.get("image_kind") or "thumb",
            force=bool(kwargs.get("force")),
            store_dir=kwargs.get("store_dir"),
            preflight=bool(kwargs.get("preflight", True)),
            recitation_fallback_model=kwargs.get("recitation_fallback_model"),
        )
    raise ValueError("Unsupported provider. Use provider=mock or provider=gemini.")
