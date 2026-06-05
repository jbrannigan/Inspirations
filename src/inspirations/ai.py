from __future__ import annotations

import base64
import json
import math
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .db import Db
from .storage import download_and_attach_originals
from .thumbnails import generate_thumbnails
from .title_audit import strip_facebook_engagement_prefix


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
GEMINI_KEYCHAIN_SERVICE = "inspirations_gemini_api_key"
_SCAN_DOC_SUFFIX_RE = re.compile(r"(\s-\sdoc\s+\d+(?:\s+p\d+)?)\s*$", re.IGNORECASE)
_SCAN_GENERIC_PREFIX_RE = re.compile(
    r"^(?:a|an|the|this)\s+(?:scanned?\s+)?(?:magazine\s+page|image|photo|scan|page|document)"
    r"(?:\s+that)?\s+(?:show(?:ing|s)?|depict(?:ing|s)?|of|featur(?:ing|es)|with)\s+",
    re.IGNORECASE,
)
_SCAN_BOILERPLATE_PREFIX_RE = re.compile(
    r"^(?:this|the)\s+(?:image|photo|scan|page|document)\s+"
    r"(?:is|shows?|showcases?|depicts?|features?|illustrates?|captures?|displays?|presents?)\s+",
    re.IGNORECASE,
)
_SCAN_TRAILING_FILLER_RE = re.compile(
    r"(?:\s+|,)(?:and|or|with|of|in|on|to|for|from|featuring|showing|including)$",
    re.IGNORECASE,
)
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

_keychain_cache: dict[str, str] = {}


def _keychain_get(service: str) -> str:
    if service in _keychain_cache:
        return _keychain_cache[service]
    try:
        value = subprocess.check_output(
            ["security", "find-generic-password", "-s", service, "-w"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        value = ""
    _keychain_cache[service] = value
    return value


def get_gemini_api_key(explicit: str = "") -> str:
    key = str(explicit or "").strip() or os.environ.get("GEMINI_API_KEY", "").strip()
    if key:
        return key
    return _keychain_get(GEMINI_KEYCHAIN_SERVICE)
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
LEXICAL_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "with",
}
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


def _scan_doc_suffix(title: str) -> str:
    m = _SCAN_DOC_SUFFIX_RE.search((title or "").strip())
    if not m:
        return ""
    return str(m.group(1) or "")


def _strip_scan_doc_suffix(title: str) -> str:
    return _SCAN_DOC_SUFFIX_RE.sub("", (title or "").strip()).strip()


def _truncate_title(text: str, max_len: int = 74) -> str:
    if len(text) <= max_len:
        return text
    cut = text[: max_len + 1]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" ,.;:-")


def _clean_scan_title_text(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        return ""
    cleaned = re.split(r"(?<=[.!?])\s+", cleaned, maxsplit=1)[0]
    cleaned = cleaned.rstrip(" .!?")
    cleaned = _SCAN_GENERIC_PREFIX_RE.sub("", cleaned).strip()
    cleaned = _SCAN_BOILERPLATE_PREFIX_RE.sub("", cleaned).strip()
    cleaned = re.sub(r"^(?:a|an|the)\s+", "", cleaned, flags=re.IGNORECASE).strip()
    if len(cleaned) > 64:
        lead = re.split(r"\s*[,;:]\s*", cleaned, maxsplit=1)[0].strip()
        if len(lead) >= 22:
            cleaned = lead
    cleaned = cleaned.strip(" ,.;:-")
    if len(cleaned) < 3:
        return ""
    if _looks_autogenerated_scan_title(cleaned):
        return ""
    cleaned = _truncate_title(cleaned)
    while cleaned and _SCAN_TRAILING_FILLER_RE.search(cleaned):
        cleaned = _SCAN_TRAILING_FILLER_RE.sub("", cleaned).strip(" ,.;:-")
    if len(cleaned) < 3:
        return ""
    if cleaned and cleaned[0].islower():
        cleaned = cleaned[0].upper() + cleaned[1:]
    return cleaned


def _looks_autogenerated_scan_title(text: str) -> bool:
    base = _strip_scan_doc_suffix(text)
    lowered = base.lower().strip()
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


def _suggest_scan_title(payload: dict[str, Any], current_title: str) -> str:
    for key in ("suggested_title", "title", "headline"):
        value = _clean_scan_title_text(str(payload.get(key) or ""))
        if value:
            base = _strip_scan_doc_suffix(value)
            suffix = _scan_doc_suffix(current_title)
            return f"{base}{suffix}" if suffix else base

    summary = _clean_scan_title_text(str(payload.get("summary") or ""))
    if summary:
        base = _strip_scan_doc_suffix(summary)
        suffix = _scan_doc_suffix(current_title)
        return f"{base}{suffix}" if suffix else base
    if _looks_autogenerated_scan_title(current_title):
        suffix = _scan_doc_suffix(current_title)
        base = "Scanned inspiration"
        return f"{base}{suffix}" if suffix else base
    return ""


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
    source = str(row.get("source") or "").strip().lower()
    parts: list[str] = []
    field_order = [
        ("title", "title"),
        ("ai_summary", "summary"),
        ("description", "description"),
        ("board", "board"),
        ("notes", "notes"),
    ]
    for key, label in field_order:
        value = str(row.get(key) or "").strip()
        if key == "title" and source == "facebook":
            cleaned = strip_facebook_engagement_prefix(value)
            if cleaned:
                value = cleaned
        if value:
            parts.append(f"{label}: {value}")
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


def _tokenize_lexical(text: str) -> set[str]:
    tokens = set(re.findall(r"[a-z0-9]+", (text or "").lower()))
    return {t for t in tokens if t and t not in LEXICAL_STOPWORDS}


def _lexical_overlap_score(query_text: str, doc_text: str) -> float:
    q = _tokenize_lexical(query_text)
    if not q:
        return 0.0
    d = _tokenize_lexical(doc_text)
    if not d:
        return 0.0
    overlap = len(q.intersection(d)) / float(len(q))

    # Phrase boost helps preserve exact-intent queries for interiors/design styles.
    phrase_boost = 0.0
    q_norm = " ".join((query_text or "").lower().split())
    d_norm = " ".join((doc_text or "").lower().split())
    if q_norm and len(q_norm.split()) >= 2 and q_norm in d_norm:
        phrase_boost = 0.15
    return min(1.0, overlap + phrase_boost)


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
        sources = [s.strip() for s in source.split(",") if s.strip()]
        if sources:
            if len(sources) == 1:
                clauses.append("a.source = ?")
                params.append(sources[0])
            else:
                clauses.append("a.source in (%s)" % ",".join(["?"] * len(sources)))
                params.extend(sources)
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
    asset_id: str = "",
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
    if asset_id:
        clauses.append("a.id = ?")
        params.append(asset_id)
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
    semantic_weight: float = 0.85,
    lexical_weight: float = 0.15,
    min_score: float = 0.0,
) -> dict[str, Any]:
    query_text = (query or "").strip()
    if not query_text:
        raise ValueError("query is required")
    if limit <= 0:
        limit = 25
    semantic_weight = max(0.0, float(semantic_weight))
    lexical_weight = max(0.0, float(lexical_weight))
    if semantic_weight == 0.0 and lexical_weight == 0.0:
        semantic_weight = 1.0
    weight_sum = semantic_weight + lexical_weight
    semantic_weight /= weight_sum
    lexical_weight /= weight_sum
    min_score = max(0.0, min(1.0, float(min_score)))

    query_vec = _gemini_embed_text(
        api_key=api_key,
        model=model,
        text=query_text,
        task_type="RETRIEVAL_QUERY",
    )

    clauses = ["e.provider = ?", "e.model = ?"]
    params: list[Any] = ["gemini", model]
    if source:
        sources = [s.strip() for s in source.split(",") if s.strip()]
        if len(sources) == 1:
            clauses.append("a.source = ?")
            params.append(sources[0])
        elif len(sources) > 1:
            clauses.append("a.source in (%s)" % ",".join(["?"] * len(sources)))
            params.extend(sources)
    where = "where " + " and ".join(clauses)

    rows = db.query(
        f"""
        select e.asset_id, e.vector_json, e.dimensions, e.created_at,
               a.source, a.source_ref, a.title, a.description, a.board, a.notes,
               a.image_url, a.stored_path, a.thumb_path, a.imported_at,
               a.media_status, a.content_kind, a.creator_name, a.source_domain, a.source_name,
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
        semantic_score = _cosine_similarity(query_vec, vector)
        doc_text_parts = [
            str(r["title"] or ""),
            str(r["description"] or ""),
            str(r["board"] or ""),
            str(r["notes"] or ""),
            str(r["ai_summary"] or ""),
        ]
        ai_json_text = str(r["ai_json"] or "")
        if ai_json_text:
            doc_text_parts.append(ai_json_text)
        lexical_score = _lexical_overlap_score(query_text, " ".join(doc_text_parts))
        score = (semantic_weight * semantic_score) + (lexical_weight * lexical_score)
        if score < min_score:
            continue
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
                "media_status": r["media_status"],
                "content_kind": r["content_kind"],
                "creator_name": r["creator_name"],
                "source_domain": r["source_domain"],
                "source_name": r["source_name"],
                "ai_summary": r["ai_summary"],
                "ai_json": r["ai_json"],
                "ai_model": r["ai_model"],
                "ai_provider": r["ai_provider"],
                "ai_created_at": r["ai_created_at"],
                "semantic_score": semantic_score,
                "lexical_score": lexical_score,
                "score": score,
                "embedding_created_at": r["created_at"],
            }
        )
    scored.sort(key=lambda x: x["score"], reverse=True)

    return {
        "query": query_text,
        "provider": "gemini",
        "model": model,
        "semantic_weight": semantic_weight,
        "lexical_weight": lexical_weight,
        "min_score": min_score,
        "compared_assets": len(scored),
        "skipped_dimension_mismatch": skipped_mismatch,
        "results": scored[:limit],
    }


def run_mock_labeler(db: Db, *, limit: int = 0, asset_id: str = "") -> dict[str, Any]:
    run_id = str(uuid.uuid4())
    db.exec(
        "insert into ai_runs (id, provider, model, created_at) values (?, ?, ?, ?)",
        (run_id, "mock", "keyword-heuristic", _now_iso()),
    )

    rows = db.query(
        "select id, title, board from assets where (?='' or id=?) order by imported_at asc",
        (asset_id, asset_id),
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
    asset_id: str = "",
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

    if preflight and not asset_id:
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
    if asset_id:
        clauses.append("a.id = ?")
        params.append(asset_id)
    if not force:
        clauses.append(
            "a.id not in (select asset_id from asset_ai where provider=?)"
        )
        params.extend(["gemini"])
    where = "where " + " and ".join(clauses) if clauses else ""
    rows = db.query(
        f"""
        select a.id, a.source, a.title, a.description, a.board, a.stored_path, a.thumb_path
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
        asset_source = str(r["source"] or "").strip().lower()
        current_title = str(r["title"] or "").strip()
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
            if asset_source == "scan":
                suggested_title = _suggest_scan_title(payload, current_title)
                if suggested_title and suggested_title != current_title:
                    db.exec("update assets set title=? where id=?", (suggested_title, asset_id))
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
            if attempted % 50 == 0:
                print(f"  progress: {labeled} tagged / {attempted} attempted ({len(errors)} errors)")
            time.sleep(0.15)  # Rate limiting — avoid Gemini 429s on bulk runs
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
        return run_mock_labeler(db, limit=limit, asset_id=kwargs.get("asset_id") or "")
    if provider == "gemini":
        api_key = get_gemini_api_key(str(kwargs.get("api_key") or ""))
        if not api_key:
            raise ValueError(
                "Gemini API key required (set GEMINI_API_KEY, pass --api-key, "
                "or store in macOS Keychain service inspirations_gemini_api_key)."
            )
        model = kwargs.get("model") or DEFAULT_GEMINI_MODEL
        return run_gemini_image_labeler(
            db,
            api_key=api_key,
            model=model,
            limit=limit,
            source=kwargs.get("source") or "",
            asset_id=kwargs.get("asset_id") or "",
            image_kind=kwargs.get("image_kind") or "thumb",
            force=bool(kwargs.get("force")),
            store_dir=kwargs.get("store_dir"),
            preflight=bool(kwargs.get("preflight", True)),
            recitation_fallback_model=kwargs.get("recitation_fallback_model"),
        )
    raise ValueError("Unsupported provider. Use provider=mock or provider=gemini.")


# ---------------------------------------------------------------------------
# Facebook Reel Analysis Pipeline
# ---------------------------------------------------------------------------

REEL_ANALYSIS_PROMPT = """You are a home design content classifier. This video is from a user's \
saved Facebook reels collection focused on home design inspiration.

Determine whether this video is relevant to home design, construction, \
renovation, interior design, or architecture. Videos about unrelated \
topics (finance, haircare, cooking, comedy, pets, etc.) should be \
marked irrelevant with recommendation "hide".

Return ONLY valid JSON:
{
  "actual_content": "1-2 sentence description of what the video actually shows",
  "relevant_to_home_design": true or false,
  "confidence": 0.0-1.0,
  "category": "home_design | construction | diy | product_review | irrelevant",
  "subcategory": "kitchen | bathroom | flooring | exterior | lighting | furniture | landscaping | general",
  "suggested_title": "short descriptive title for this reel",
  "suggested_board": "board name this belongs in, or empty string if unclear",
  "recommendation": "keep | hide | recategorize",
  "recommendation_reason": "why this recommendation",
  "elements": [],
  "materials": [],
  "styles": []
}

Rules:
- Use lowercase strings in arrays.
- Return JSON only. No markdown. No extra keys.
"""


def _gemini_generate_video(
    *,
    api_key: str,
    model: str,
    prompt: str,
    video_b64: str,
    mime_type: str = "video/mp4",
    timeout_s: float = 120.0,
) -> dict[str, Any]:
    """Send a video to Gemini for analysis. Like _gemini_generate but for video content."""
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
    ]
    last_exc: Exception | None = None
    for cfg in gen_configs:
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {"inline_data": {"mime_type": mime_type, "data": video_b64}},
                    ]
                }
            ],
            "generationConfig": cfg,
        }
        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data_bytes,
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
            if "Unknown name" in detail or "Invalid JSON payload" in detail:
                last_exc = RuntimeError(f"Gemini HTTP {e.code}: {detail}")
                continue
            raise RuntimeError(f"Gemini HTTP {e.code}: {detail}") from e
    if last_exc:
        raise last_exc
    raise RuntimeError("Gemini video request failed before a response was received")


def _upload_to_gemini_file_api(
    *,
    api_key: str,
    file_path: Path,
    mime_type: str = "video/mp4",
    timeout_s: float = 300.0,
) -> str:
    """Upload a file to Gemini File API and return the file URI."""
    # Step 1: Start resumable upload
    start_url = "https://generativelanguage.googleapis.com/upload/v1beta/files"
    file_size = file_path.stat().st_size
    meta = json.dumps({"file": {"display_name": file_path.name}}).encode("utf-8")
    req = urllib.request.Request(
        start_url,
        data=meta,
        headers={
            "Content-Type": "application/json",
            "X-Goog-Upload-Protocol": "resumable",
            "X-Goog-Upload-Command": "start",
            "X-Goog-Upload-Header-Content-Length": str(file_size),
            "X-Goog-Upload-Header-Content-Type": mime_type,
            "x-goog-api-key": api_key,
        },
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        upload_url = resp.headers.get("X-Goog-Upload-URL")
        if not upload_url:
            raise RuntimeError("No upload URL returned from Gemini File API")

    # Step 2: Upload the bytes
    file_bytes = file_path.read_bytes()
    req2 = urllib.request.Request(
        upload_url,
        data=file_bytes,
        headers={
            "Content-Length": str(file_size),
            "X-Goog-Upload-Offset": "0",
            "X-Goog-Upload-Command": "upload, finalize",
        },
    )
    with urllib.request.urlopen(req2, timeout=timeout_s) as resp2:
        result = json.loads(resp2.read().decode("utf-8") or "{}")

    file_uri = (result.get("file") or {}).get("uri") or ""
    if not file_uri:
        raise RuntimeError(f"No file URI in upload response: {json.dumps(result)[:500]}")

    # Step 3: Wait for processing
    file_name = (result.get("file") or {}).get("name") or ""
    if file_name:
        check_url = f"https://generativelanguage.googleapis.com/v1beta/{file_name}"
        for _ in range(60):
            time.sleep(2)
            check_req = urllib.request.Request(
                check_url,
                headers={"x-goog-api-key": api_key},
            )
            try:
                with urllib.request.urlopen(check_req, timeout=30) as check_resp:
                    state = json.loads(check_resp.read().decode("utf-8") or "{}")
                    status = (state.get("state") or "").upper()
                    if status == "ACTIVE":
                        return str((state.get("uri") or file_uri))
                    if status == "FAILED":
                        raise RuntimeError(f"File processing failed: {json.dumps(state)[:500]}")
            except urllib.error.HTTPError:
                pass
        raise RuntimeError("Timed out waiting for file processing")
    return file_uri


def _gemini_generate_with_file_uri(
    *,
    api_key: str,
    model: str,
    prompt: str,
    file_uri: str,
    mime_type: str = "video/mp4",
    timeout_s: float = 120.0,
) -> dict[str, Any]:
    """Send a request using a Gemini File API URI."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {"file_data": {"mime_type": mime_type, "file_uri": file_uri}},
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 4096,
            "responseMimeType": "application/json",
        },
    }
    data_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data_bytes,
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
        raise RuntimeError(f"Gemini HTTP {e.code}: {detail}") from e


def download_facebook_reels(
    db: Db,
    store_dir: Path,
    *,
    limit: int = 0,
    force: bool = False,
) -> dict[str, Any]:
    """Download Facebook reel videos via yt-dlp.

    Stores video files at store_dir/reels/facebook/{asset_id}.*
    Updates assets with stored_video_path, video_duration, title, post_text, creator_name.
    """
    reels_dir = store_dir / "reels" / "facebook"
    reels_dir.mkdir(parents=True, exist_ok=True)

    rows = db.query(
        "select id, source_ref from assets where source='facebook' and content_kind='reel' order by imported_at asc"
    )

    attempted = 0
    downloaded = 0
    skipped = 0
    errors: list[dict[str, str]] = []

    def _find_video_file(asset_id: str) -> Path | None:
        for candidate in sorted(reels_dir.glob(f"{asset_id}.*")):
            if candidate.suffix.lower() in {".mp4", ".webm", ".mkv", ".mov"}:
                return candidate
        return None

    for r in rows:
        if limit and attempted >= limit:
            break
        asset_id = str(r["id"])
        source_ref = str(r["source_ref"] or "").strip()
        if not source_ref:
            errors.append({"id": asset_id, "error": "No source_ref URL"})
            continue

        video_path = _find_video_file(asset_id)
        info_path = reels_dir / f"{asset_id}.info.json"

        # Skip if already downloaded
        if video_path and not force:
            # Still update DB if not set
            if not db.query_value(
                "select stored_video_path from assets where id=? and stored_video_path is not null",
                (asset_id,),
            ):
                _update_reel_from_files(db, asset_id, video_path, info_path)
            skipped += 1
            continue

        if force:
            for stale in reels_dir.glob(f"{asset_id}.*"):
                try:
                    stale.unlink()
                except Exception:
                    pass

        attempted += 1
        try:
            output_template = reels_dir / f"{asset_id}.%(ext)s"
            default_cmd = [
                "yt-dlp",
                "-o", str(output_template),
                "--write-info-json",
                "--no-playlist",
                "--max-filesize", "50m",
                "--force-overwrites" if force else "--no-overwrites",
                "--quiet",
                source_ref,
            ]
            result = subprocess.run(
                default_cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
            error_parts: list[str] = []
            if result.returncode != 0:
                err_msg = (result.stderr or "").strip()[:500]
                if err_msg:
                    error_parts.append(f"default: yt-dlp exit {result.returncode}: {err_msg}")

            video_path = _find_video_file(asset_id)
            if not video_path:
                fallback_cmd = [
                    "yt-dlp",
                    "-f", "hd/sd/best",
                    "--merge-output-format", "mp4",
                    "-o", str(output_template),
                    "--write-info-json",
                    "--no-playlist",
                    "--max-filesize", "50m",
                    "--force-overwrites",
                    "--quiet",
                    source_ref,
                ]
                fallback = subprocess.run(
                    fallback_cmd,
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if fallback.returncode != 0:
                    err_msg = (fallback.stderr or "").strip()[:500]
                    if err_msg:
                        error_parts.append(f"fallback: yt-dlp exit {fallback.returncode}: {err_msg}")
                video_path = _find_video_file(asset_id)

            if not video_path:
                detail = "; ".join(error_parts) or "yt-dlp ran but no video file found"
                errors.append({"id": asset_id, "error": detail})
                continue

            _update_reel_from_files(db, asset_id, video_path, info_path)
            downloaded += 1

            if attempted % 25 == 0:
                print(f"  downloaded {downloaded}/{attempted} reels ({skipped} skipped, {len(errors)} errors)")

        except subprocess.TimeoutExpired:
            errors.append({"id": asset_id, "error": "yt-dlp timed out (120s)"})
        except Exception as e:
            errors.append({"id": asset_id, "error": str(e)[:500]})

    return {
        "attempted": attempted,
        "downloaded": downloaded,
        "skipped": skipped,
        "errors": errors[:50],
        "total_errors": len(errors),
    }


def _update_reel_from_files(db: Db, asset_id: str, mp4_path: Path, info_path: Path) -> None:
    """Update asset row from downloaded video + info.json metadata."""
    db.exec(
        "update assets set stored_video_path=? where id=?",
        (str(mp4_path), asset_id),
    )

    if not info_path.exists():
        return
    try:
        info = json.loads(info_path.read_text(encoding="utf-8"))
    except Exception:
        return

    duration = info.get("duration")
    title = str(info.get("title") or "").strip()
    description = str(info.get("description") or "").strip()
    uploader = str(info.get("uploader") or info.get("channel") or "").strip()

    updates: list[str] = []
    params: list[Any] = []

    if duration:
        updates.append("video_duration=?")
        params.append(float(duration))

    # Only fill empty fields — don't overwrite human edits
    current = db.query(
        "select title, post_text, creator_name from assets where id=?", (asset_id,)
    )
    if current:
        row = dict(current[0])
        if not str(row.get("title") or "").strip() and title:
            updates.append("title=?")
            params.append(title[:200])
        if not str(row.get("post_text") or "").strip() and description:
            updates.append("post_text=?")
            params.append(description[:2000])
        if not str(row.get("creator_name") or "").strip() and uploader:
            updates.append("creator_name=?")
            params.append(uploader[:200])

    if updates:
        params.append(asset_id)
        db.exec(f"update assets set {', '.join(updates)} where id=?", tuple(params))


def run_gemini_video_labeler(
    db: Db,
    *,
    api_key: str,
    model: str = DEFAULT_GEMINI_MODEL,
    limit: int = 0,
    force: bool = False,
    store_dir: Path | None = None,
) -> dict[str, Any]:
    """Analyze downloaded reel videos with Gemini 2.5 Flash.

    Sends each MP4 to Gemini for content classification.
    Stores results in asset_ai with provider='gemini-video'.
    """
    run_id = str(uuid.uuid4())
    now = _now_iso()
    db.exec(
        "insert into ai_runs (id, provider, model, created_at) values (?, ?, ?, ?)",
        (run_id, "gemini-video", model, now),
    )

    # Find reels with downloaded video that haven't been video-analyzed yet
    clauses = [
        "a.source='facebook'",
        "a.content_kind='reel'",
        "a.stored_video_path is not null",
        "a.stored_video_path != ''",
    ]
    params: list[Any] = []
    if not force:
        clauses.append(
            "a.id not in (select asset_id from asset_ai where provider='gemini-video')"
        )
    where = "where " + " and ".join(clauses)

    rows = db.query(
        f"select a.id, a.stored_video_path from assets a {where} order by a.imported_at asc",
        tuple(params),
    )

    attempted = 0
    labeled = 0
    errors: list[dict[str, str]] = []
    file_api_count = 0

    for r in rows:
        if limit and attempted >= limit:
            break
        asset_id = str(r["id"])
        video_path = Path(str(r["stored_video_path"]))

        if not video_path.exists():
            errors.append({"id": asset_id, "error": f"Video file missing: {video_path}"})
            continue

        attempted += 1
        raw_error: str | None = None
        try:
            file_size = video_path.stat().st_size
            if file_size > 20 * 1024 * 1024:
                # Large file — use File API
                file_uri = _upload_to_gemini_file_api(
                    api_key=api_key,
                    file_path=video_path,
                    mime_type="video/mp4",
                )
                resp = _gemini_generate_with_file_uri(
                    api_key=api_key,
                    model=model,
                    prompt=REEL_ANALYSIS_PROMPT,
                    file_uri=file_uri,
                    mime_type="video/mp4",
                )
                file_api_count += 1
            else:
                # Small file — send inline
                video_b64 = base64.b64encode(video_path.read_bytes()).decode("ascii")
                resp = _gemini_generate_video(
                    api_key=api_key,
                    model=model,
                    prompt=REEL_ANALYSIS_PROMPT,
                    video_b64=video_b64,
                    mime_type="video/mp4",
                )

            raw_text = _extract_response_text(resp)
            payload = _extract_json_object(raw_text)
            if not payload:
                raw_payload = raw_text if raw_text else json.dumps(resp)
                raw_error = raw_payload[:10000]
                raise RuntimeError(_no_json_error_message(resp))

            summary = str(payload.get("actual_content") or payload.get("summary") or "").strip()

            # Store in asset_ai with provider='gemini-video'
            db.exec(
                "insert into asset_ai (id, asset_id, provider, model, summary, json, created_at) values (?, ?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), asset_id, "gemini-video", model, summary or None, json.dumps(payload), now),
            )

            # Update ai_summary on the asset
            if summary:
                db.exec("update assets set ai_summary=? where id=?", (summary, asset_id))

            # Replace stale thumbnail-based labels with video-based ones
            db.exec(
                "delete from asset_labels where asset_id=? and source='ai'",
                (asset_id,),
            )
            labels = _flatten_reel_labels(payload)
            for lab in labels:
                db.exec(
                    """
                    insert or ignore into asset_labels
                      (id, asset_id, label, confidence, source, model, run_id, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (str(uuid.uuid4()), asset_id, lab, 0.8, "ai-video", model, run_id, now),
                )

            labeled += 1

            if attempted % 10 == 0:
                print(f"  analyzed {labeled}/{attempted} reels ({len(errors)} errors, {file_api_count} via file API)")

            # Rate limiting — Gemini free tier is ~15 RPM for video
            time.sleep(0.5)

        except Exception as e:
            errors.append({"id": asset_id, "error": str(e)[:500]})
            _log_ai_error(
                db,
                asset_id=asset_id,
                provider="gemini-video",
                model=model,
                error=str(e),
                raw=raw_error,
                run_id=run_id,
                now=now,
            )

    return {
        "provider": "gemini-video",
        "model": model,
        "run_id": run_id,
        "attempted": attempted,
        "labeled_assets": labeled,
        "file_api_uploads": file_api_count,
        "errors": errors[:50],
        "total_errors": len(errors),
    }


def _flatten_reel_labels(payload: dict[str, Any]) -> list[str]:
    """Extract normalized labels from reel analysis JSON."""
    buckets = ["elements", "materials", "styles"]
    labels: list[str] = []
    for key in buckets:
        for item in payload.get(key, []) or []:
            lab = _normalize_label(str(item))
            if lab:
                labels.append(lab)
    # Add category + subcategory as labels
    cat = _normalize_label(str(payload.get("category") or ""))
    if cat and cat != "irrelevant":
        labels.append(cat)
    subcat = _normalize_label(str(payload.get("subcategory") or ""))
    if subcat and subcat != "general":
        labels.append(subcat)
    # Dedupe
    seen: set[str] = set()
    out: list[str] = []
    for lab in labels:
        if lab in seen:
            continue
        seen.add(lab)
        out.append(lab)
    return out


def apply_reel_recommendations(
    db: Db,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Apply Gemini video analysis recommendations to reel assets.

    - Hides irrelevant reels (triage_status='hidden')
    - Updates title/board/category for relevant reels
    - Skips tagged items (Jim's anomalies — those are for interactive review)
    """
    rows = db.query(
        """
        select a.id, a.title, a.board, a.category, a.tagged,
               ai.json as ai_json, ai.summary as ai_summary
        from assets a
        join asset_ai ai on ai.asset_id = a.id and ai.provider = 'gemini-video'
        where a.source = 'facebook' and a.content_kind = 'reel'
          and (a.triage_status is null)
        order by a.imported_at asc
        """
    )

    hidden = 0
    kept = 0
    recategorized = 0
    tagged_skipped = 0
    errors: list[dict[str, str]] = []
    recommendations: dict[str, int] = {}

    for r in rows:
        asset_id = str(r["id"])
        is_tagged = bool(r["tagged"])

        try:
            payload = json.loads(str(r["ai_json"] or "{}"))
        except Exception:
            errors.append({"id": asset_id, "error": "Invalid JSON in ai_json"})
            continue

        recommendation = str(payload.get("recommendation") or "").strip().lower()
        recommendations[recommendation] = recommendations.get(recommendation, 0) + 1

        if is_tagged:
            # Tagged items get analysis stored but no auto-triage
            tagged_skipped += 1
            continue

        if dry_run:
            continue

        if recommendation == "hide":
            now = _now_iso()
            db.exec(
                "update assets set triage_status='hidden', triage_at=? where id=?",
                (now, asset_id),
            )
            db.exec(
                "insert into triage_log (asset_id, old_status, new_status, reason, actor, created_at) "
                "values (?, ?, 'hidden', ?, 'ai-reel-triage', ?)",
                (asset_id, None, f"gemini-video recommendation: {recommendation}", now),
            )
            hidden += 1
        elif recommendation in ("keep", "recategorize"):
            updates: list[str] = []
            params: list[Any] = []

            suggested_title = str(payload.get("suggested_title") or "").strip()
            suggested_board = str(payload.get("suggested_board") or "").strip()
            category = str(payload.get("category") or "").strip()

            current_title = str(r["title"] or "").strip()
            current_board = str(r["board"] or "").strip()

            if not current_title and suggested_title:
                updates.append("title=?")
                params.append(suggested_title[:200])

            if not current_board and suggested_board:
                updates.append("board=?")
                params.append(suggested_board[:200])

            if category and category != "irrelevant":
                updates.append("category=?")
                params.append(category)

            if updates:
                params.append(asset_id)
                db.exec(f"update assets set {', '.join(updates)} where id=?", tuple(params))

            if recommendation == "recategorize":
                recategorized += 1
            kept += 1

    return {
        "total_analyzed": len(rows),
        "hidden": hidden,
        "kept": kept,
        "recategorized": recategorized,
        "tagged_skipped": tagged_skipped,
        "recommendation_breakdown": recommendations,
        "dry_run": dry_run,
        "errors": errors[:25],
    }
