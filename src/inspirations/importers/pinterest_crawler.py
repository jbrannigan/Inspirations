from __future__ import annotations

import json
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..db import Db


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coerce_board_name(board: Any) -> str | None:
    if isinstance(board, str):
        return board
    if isinstance(board, dict):
        # common keys: name, id
        for k in ("name", "id"):
            v = board.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return None


def _pin_url_from_record(rec: dict[str, Any]) -> str | None:
    seo_url = rec.get("seo_url")
    if isinstance(seo_url, str) and seo_url.startswith("/pin/"):
        return f"https://www.pinterest.com{seo_url}"
    pin_id = rec.get("id")
    if pin_id is not None:
        return f"https://www.pinterest.com/pin/{pin_id}/"
    return None


def import_pinterest_crawler_zip(db: Db, zip_path: Path, limit: int = 0) -> dict[str, Any]:
    """
    Import from a 'dataset_pinterest-crawler_*.zip' export.

    Observed: the ZIP contains the same logical dataset in JSON/CSV/HTML/XLSX.
    We prefer JSON for fidelity and nested data.
    """
    with zipfile.ZipFile(zip_path) as z:
        json_names = [n for n in z.namelist() if n.lower().endswith(".json")]
        if not json_names:
            raise ValueError("No .json found in pinterest crawler zip")
        raw = z.read(json_names[0])

    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("Expected top-level list in pinterest crawler JSON")

    skipped = 0
    errors = 0

    rows: list[tuple[Any, ...]] = []
    for i, rec in enumerate(data):
        if limit and i >= limit:
            break
        if not isinstance(rec, dict):
            errors += 1
            continue

        source_ref = _pin_url_from_record(rec)
        img = rec.get("image") if isinstance(rec.get("image"), dict) else {}
        image_url = img.get("url") if isinstance(img, dict) else None
        if not (isinstance(source_ref, str) and source_ref) or not (isinstance(image_url, str) and image_url):
            skipped += 1
            continue

        title = (
            (rec.get("title") or rec.get("grid_title") or rec.get("seo_title") or rec.get("auto_alt_text") or "")
            if isinstance(rec.get("title") or rec.get("grid_title") or rec.get("seo_title") or rec.get("auto_alt_text"), str)
            else ""
        ).strip()

        description = rec.get("description") if isinstance(rec.get("description"), str) else None
        board = _coerce_board_name(rec.get("board"))
        created_at = rec.get("created_at") if isinstance(rec.get("created_at"), str) else None

        asset_id = str(uuid.uuid4())
        rows.append(
            (
                asset_id,
                "pinterest",
                source_ref,
                title or None,
                description,
                board,
                created_at,
                _now_iso(),
                image_url,
            )
        )

    db.executemany(
        """
        insert or ignore into assets
          (id, source, source_ref, title, description, board, created_at, imported_at, image_url)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        rows,
    )

    total_after = db.query_value("select count(*) from assets where source='pinterest'")

    return {
        "source": "pinterest",
        "zip": str(zip_path),
        "parsed_records": len(rows),
        "skipped_records": skipped,
        "errors": errors,
        "note": "Counts are best-effort in this MVP; re-import is idempotent via (source, source_ref).",
        "total_assets_for_source": total_after,
    }
