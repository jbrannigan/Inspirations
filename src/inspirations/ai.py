from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
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
