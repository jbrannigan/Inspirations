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


def _as_dict(x: Any) -> dict[str, Any] | None:
    return x if isinstance(x, dict) else None


def _as_list(x: Any) -> list[Any] | None:
    return x if isinstance(x, list) else None


def _extract_external_context(item: dict[str, Any]) -> dict[str, Any] | None:
    atts = _as_list(item.get("attachments"))
    if not atts:
        return None
    first = _as_dict(atts[0])
    if not first:
        return None
    data = _as_list(first.get("data"))
    if not data:
        return None
    d0 = _as_dict(data[0])
    if not d0:
        return None
    return _as_dict(d0.get("external_context"))


def import_facebook_saved_zip(db: Db, zip_path: Path, limit: int = 0) -> dict[str, Any]:
    """
    Import from a Facebook "Your saved items" export ZIP.

    Observed structure:
      - your_facebook_activity/saved_items_and_collections/your_saved_items.json (dict with key 'saves_v2')
      - items are heterogeneous; many have only a domain name, while a subset contain a usable URL in:
          attachments[0].data[0].external_context.source  (often a direct image URL)
    """
    with zipfile.ZipFile(zip_path) as z:
        saved_path = "your_facebook_activity/saved_items_and_collections/your_saved_items.json"
        raw = z.read(saved_path)

    data = json.loads(raw)
    items = data.get("saves_v2") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ValueError("Expected {saves_v2: [...]} in Facebook saved items JSON")

    parsed = 0
    candidates = 0
    skipped = 0

    rows: list[tuple[Any, ...]] = []
    for i, it in enumerate(items):
        if limit and i >= limit:
            break
        if not isinstance(it, dict):
            skipped += 1
            continue
        parsed += 1

        ec = _extract_external_context(it)
        source_ref = None
        image_url = None
        title = it.get("title") if isinstance(it.get("title"), str) else None
        created_at = None
        ts = it.get("timestamp")
        if isinstance(ts, (int, float)):
            created_at = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

        if isinstance(ec, dict):
            # 'source' is often the most useful: it can be an image URL
            src = ec.get("source")
            if isinstance(src, str) and src.startswith(("http://", "https://")):
                image_url = src
                source_ref = src
            # fallback: sometimes there is a url/domain only (not enough to download)

        if not image_url or not source_ref:
            skipped += 1
            continue
        candidates += 1

        asset_id = str(uuid.uuid4())
        rows.append(
            (
                asset_id,
                "facebook",
                source_ref,
                title,
                None,
                None,
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

    total_after = db.query_value("select count(*) from assets where source='facebook'")

    return {
        "source": "facebook",
        "zip": str(zip_path),
        "parsed_items": parsed,
        "candidate_assets": candidates,
        "skipped_items": skipped,
        "note": "Facebook exports are heterogeneous; this importer only captures items with external_context.source URLs.",
        "total_assets_for_source": total_after,
    }

