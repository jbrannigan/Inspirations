from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from .db import Db


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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_labels(text: str) -> list[str]:
    text = text.lower()
    out: list[str] = []
    for k in KEYWORDS:
        if k in text and k not in out:
            out.append(k)
    return out


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


def run_ai_labeler(db: Db, *, provider: str, limit: int = 0) -> dict[str, Any]:
    provider = provider.lower()
    if provider == "mock":
        return run_mock_labeler(db, limit=limit)
    raise ValueError(
        "Only provider=mock is implemented in this MVP. Configure a cloud provider in a later step."
    )

