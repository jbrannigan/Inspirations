from __future__ import annotations

import hashlib
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..db import Db


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    sha = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 64)
            if not chunk:
                break
            sha.update(chunk)
    return sha.hexdigest()


def _select_pdf_renderer(renderer: str) -> str | None:
    if renderer != "auto":
        return renderer
    if shutil.which("pdftoppm"):
        return "pdftoppm"
    if shutil.which("mutool"):
        return "mutool"
    return None


def _render_pdf(
    *,
    pdf_path: Path,
    out_dir: Path,
    fmt: str,
    max_pages: int,
    renderer: str,
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    fmt = fmt.lower()
    if fmt not in ("jpg", "jpeg", "png"):
        raise ValueError("format must be jpg or png")
    if renderer == "pdftoppm":
        prefix = out_dir / "page"
        args = ["pdftoppm", "-r", "200"]
        if fmt in ("jpg", "jpeg"):
            args += ["-jpeg"]
        else:
            args += ["-png"]
        if max_pages:
            args += ["-f", "1", "-l", str(max_pages)]
        args += [str(pdf_path), str(prefix)]
        subprocess.run(args, check=True)
        files = sorted(out_dir.glob("page-*.*"))
        return files
    if renderer == "mutool":
        pattern = out_dir / "page-%d." + ("jpg" if fmt in ("jpg", "jpeg") else "png")
        args = ["mutool", "draw", "-r", "200", "-o", str(pattern), str(pdf_path)]
        if max_pages:
            args.insert(3, f"1-{max_pages}")
        subprocess.run(args, check=True)
        files = sorted(out_dir.glob("page-*.*"))
        return files
    raise ValueError("No supported PDF renderer found (install poppler or mupdf)")


def import_scans_inbox(
    db: Db,
    inbox_dir: Path,
    store_dir: Path,
    *,
    format: str = "jpg",
    limit: int = 0,
    max_pages: int = 0,
    renderer: str = "auto",
) -> dict[str, Any]:
    inbox = inbox_dir.expanduser().resolve()
    store = store_dir.expanduser().resolve()
    if not inbox.exists():
        raise FileNotFoundError(f"Inbox not found: {inbox}")
    store.mkdir(parents=True, exist_ok=True)

    renderer = _select_pdf_renderer(renderer)

    parsed = 0
    created = 0
    skipped = 0
    errors: list[dict[str, str]] = []

    rows: list[tuple[Any, ...]] = []
    for path in sorted(inbox.iterdir()):
        if limit and parsed >= limit:
            break
        if not path.is_file():
            continue
        parsed += 1

        suffix = path.suffix.lower()
        try:
            if suffix in IMAGE_EXTS:
                sha = _sha256_file(path)
                dest = store / "originals" / "scan"
                dest.mkdir(parents=True, exist_ok=True)
                out_path = dest / f"{sha}{suffix}"
                if not out_path.exists():
                    shutil.copy2(path, out_path)
                asset_id = str(uuid.uuid4())
                rows.append(
                    (
                        asset_id,
                        "scan",
                        f"scan://{sha}",
                        path.stem,
                        None,
                        None,
                        None,
                        _now_iso(),
                        str(out_path),
                        str(out_path),
                        sha,
                    )
                )
                created += 1
                continue

            if suffix == ".pdf":
                if renderer is None:
                    errors.append({"file": str(path), "error": "No PDF renderer available (install poppler or mupdf)"})
                    continue
                sha = _sha256_file(path)
                pdf_dest = store / "originals" / "scan"
                pdf_dest.mkdir(parents=True, exist_ok=True)
                pdf_out = pdf_dest / f"{sha}.pdf"
                if not pdf_out.exists():
                    shutil.copy2(path, pdf_out)

                pages_dir = store / "pages" / "scan" / sha
                files = _render_pdf(
                    pdf_path=pdf_out, out_dir=pages_dir, fmt=format, max_pages=max_pages, renderer=renderer
                )
                if not files:
                    skipped += 1
                    continue
                for idx, img_path in enumerate(files, start=1):
                    asset_id = str(uuid.uuid4())
                    rows.append(
                        (
                            asset_id,
                            "scan",
                            f"scan://{sha}#p{idx}",
                            f"{path.stem} — p{idx}",
                            None,
                            None,
                            None,
                            _now_iso(),
                            str(img_path),
                            str(img_path),
                            sha,
                        )
                    )
                    created += 1
                continue

            skipped += 1
        except Exception as e:
            errors.append({"file": str(path), "error": str(e)})

    db.executemany(
        """
        insert or ignore into assets
          (id, source, source_ref, title, description, board, created_at, imported_at, image_url, stored_path, sha256)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        rows,
    )

    return {
        "source": "scan",
        "inbox": str(inbox),
        "parsed_files": parsed,
        "created_assets": created,
        "skipped_files": skipped,
        "errors": errors[:25],
        "note": "Errors are truncated to 25 in output.",
        "renderer": renderer,
    }
