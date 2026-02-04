from __future__ import annotations

import hashlib
import os
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .db import Db
from .security import is_safe_public_url


@dataclass(frozen=True)
class DownloadResult:
    asset_id: str
    stored_path: str
    sha256: str
    bytes: int


def _ext_from_content_type(ct: str | None) -> str | None:
    if not ct:
        return None
    ct = ct.split(";")[0].strip().lower()
    return {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }.get(ct)


def _ext_from_url(url: str) -> str | None:
    path = urlparse(url).path
    m = re.search(r"(\\.jpg|\\.jpeg|\\.png|\\.webp|\\.gif)$", path, re.IGNORECASE)
    if not m:
        return None
    ext = m.group(1).lower()
    return ".jpg" if ext in (".jpeg", ".jpg") else ext


def download_url_to_store(
    *,
    url: str,
    dest_dir: Path,
    filename_stem: str,
    timeout_s: float = 30.0,
    max_bytes: int = 25 * 1024 * 1024,
) -> tuple[Path, str, int]:
    if not is_safe_public_url(url, allow_http=False):
        raise ValueError(f"Refusing to download non-public or non-https url: {url}")

    dest_dir.mkdir(parents=True, exist_ok=True)

    req = urllib.request.Request(url, headers={"User-Agent": "Inspirations/0.1"})
    sha = hashlib.sha256()
    total = 0

    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        ct = resp.headers.get("Content-Type")
        ext = _ext_from_content_type(ct) or _ext_from_url(url) or ".bin"
        out_path = dest_dir / f"{filename_stem}{ext}"

        # pre-check size if available
        clen = resp.headers.get("Content-Length")
        if clen:
            try:
                if int(clen) > max_bytes:
                    raise ValueError(f"Refusing to download >{max_bytes} bytes: {url}")
            except ValueError:
                pass

        tmp_path = out_path.with_suffix(out_path.suffix + ".part")
        with open(tmp_path, "wb") as f:
            while True:
                chunk = resp.read(1024 * 64)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError(f"Refusing to download >{max_bytes} bytes: {url}")
                sha.update(chunk)
                f.write(chunk)

        os.replace(tmp_path, out_path)
        return out_path, sha.hexdigest(), total


def download_and_attach_originals(db: Db, store_dir: Path, source: str, limit: int = 0) -> dict[str, Any]:
    """
    Downloads originals for assets where stored_path is null and image_url is present.
    """
    rows = db.query(
        "select id, image_url from assets where source=? and stored_path is null and image_url is not null order by imported_at asc",
        (source,),
    )
    downloaded: list[DownloadResult] = []
    errors: list[dict[str, str]] = []
    for i, r in enumerate(rows):
        if limit and i >= limit:
            break
        asset_id = r["id"]
        url = r["image_url"]
        try:
            out_path, sha, n = download_url_to_store(
                url=url, dest_dir=store_dir / "originals" / source, filename_stem=asset_id
            )
            db.exec(
                "update assets set stored_path=?, sha256=? where id=?",
                (str(out_path), sha, asset_id),
            )
            downloaded.append(DownloadResult(asset_id=asset_id, stored_path=str(out_path), sha256=sha, bytes=n))
        except Exception as e:
            errors.append({"id": asset_id, "url": str(url), "error": str(e)})

    return {
        "attempted": min(len(rows), limit) if limit else len(rows),
        "downloaded": len(downloaded),
        "errors": errors[:25],
        "note": "Errors are truncated to 25 in output.",
    }
