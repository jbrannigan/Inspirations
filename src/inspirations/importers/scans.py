from __future__ import annotations

import hashlib
import math
import re
import shutil
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..db import Db


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".heic", ".heif", ".tif", ".tiff"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv", ".mpeg", ".mpg", ".wmv", ".3gp"}
_WS_BYTES = b" \t\r\n"
_PAGE_NUM_RE = re.compile(r"-(\d+)\.[^.]+$")


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


def _page_sort_key(path: Path) -> tuple[int, str]:
    m = _PAGE_NUM_RE.search(path.name)
    if not m:
        return (10**9, path.name)
    return (int(m.group(1)), path.name)


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
        files = sorted(out_dir.glob("page-*.*"), key=_page_sort_key)
        return files
    if renderer == "mutool":
        pattern = out_dir / f"page-%d.{('jpg' if fmt in ('jpg', 'jpeg') else 'png')}"
        args = ["mutool", "draw", "-r", "200", "-o", str(pattern), str(pdf_path)]
        if max_pages:
            args.append(f"1-{max_pages}")
        subprocess.run(args, check=True)
        files = sorted(out_dir.glob("page-*.*"), key=_page_sort_key)
        return files
    raise ValueError("No supported PDF renderer found (install poppler or mupdf)")


def _render_pdf_probe_pages(*, pdf_path: Path, out_dir: Path, max_pages: int, renderer: str) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if renderer == "pdftoppm":
        prefix = out_dir / "probe"
        args = ["pdftoppm", "-r", "40", "-gray"]
        if max_pages:
            args += ["-f", "1", "-l", str(max_pages)]
        args += [str(pdf_path), str(prefix)]
        subprocess.run(args, check=True)
        return sorted(out_dir.glob("probe-*.*"), key=_page_sort_key)
    if renderer == "mutool":
        pattern = out_dir / "probe-%d.pgm"
        args = ["mutool", "draw", "-r", "40", "-F", "pgm", "-o", str(pattern), str(pdf_path)]
        if max_pages:
            args.append(f"1-{max_pages}")
        subprocess.run(args, check=True)
        return sorted(out_dir.glob("probe-*.*"), key=_page_sort_key)
    return []


def _next_pgm_token(data: bytes, start: int) -> tuple[bytes, int]:
    idx = start
    while idx < len(data):
        b = data[idx]
        if b in _WS_BYTES:
            idx += 1
            continue
        if b == 35:  # '#': comment
            while idx < len(data) and data[idx] not in b"\r\n":
                idx += 1
            continue
        break
    token_start = idx
    while idx < len(data) and data[idx] not in _WS_BYTES:
        idx += 1
    return data[token_start:idx], idx


def _pgm_blank_metrics(path: Path) -> tuple[float, float] | None:
    data = path.read_bytes()
    if not data.startswith(b"P5"):
        return None
    token, idx = _next_pgm_token(data, 2)
    if not token:
        return None
    width = int(token)
    token, idx = _next_pgm_token(data, idx)
    if not token:
        return None
    height = int(token)
    token, idx = _next_pgm_token(data, idx)
    if not token:
        return None
    maxval = int(token)
    if maxval >= 256:
        return None
    while idx < len(data) and data[idx] in _WS_BYTES:
        idx += 1
    expected = width * height
    pixels = data[idx : idx + expected]
    if len(pixels) < expected or not pixels:
        return None
    sample_step = max(1, len(pixels) // 120_000)
    samples = pixels[::sample_step]
    if not samples:
        return None
    total = len(samples)
    dark = 0
    sum_px = 0.0
    for px in samples:
        if px < 240:
            dark += 1
        sum_px += px
    mean = sum_px / total
    variance = 0.0
    for px in samples:
        diff = px - mean
        variance += diff * diff
    stddev = math.sqrt(variance / total)
    return (dark / total, stddev)


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    vals = sorted(values)
    n = len(vals)
    m = n // 2
    if n % 2:
        return vals[m]
    return (vals[m - 1] + vals[m]) / 2.0


def _delimiter_candidates_from_metrics(metrics: list[tuple[int, float, float]]) -> set[int]:
    if len(metrics) < 3:
        return set()
    inks = [m[1] for m in metrics]
    stds = [m[2] for m in metrics]
    median_ink = _median(inks)
    median_std = _median(stds)
    abs_ink = 0.018
    abs_std = 16.0
    rel_ink = median_ink * 0.35 if median_ink > 0 else 0.0
    rel_std = median_std * 0.60 if median_std > 0 else 0.0
    ink_threshold = min(abs_ink, rel_ink) if rel_ink else abs_ink
    std_threshold = min(abs_std, rel_std) if rel_std else abs_std
    candidates = {
        page_idx
        for page_idx, ink_ratio, stddev in metrics
        if ink_ratio <= ink_threshold and stddev <= std_threshold
    }
    if not candidates:
        candidates = {
            page_idx for page_idx, ink_ratio, stddev in metrics if ink_ratio <= abs_ink and stddev <= abs_std
        }
    if len(candidates) > int(len(metrics) * 0.60):
        return set()
    return candidates


def _detect_pdf_delimiter_pages(*, pdf_path: Path, max_pages: int, renderer: str) -> set[int]:
    try:
        with tempfile.TemporaryDirectory() as td:
            probe_dir = Path(td)
            probe_files = _render_pdf_probe_pages(
                pdf_path=pdf_path, out_dir=probe_dir, max_pages=max_pages, renderer=renderer
            )
            metrics: list[tuple[int, float, float]] = []
            for idx, probe_file in enumerate(probe_files, start=1):
                probe = _pgm_blank_metrics(probe_file)
                if not probe:
                    continue
                metrics.append((idx, probe[0], probe[1]))
            return _delimiter_candidates_from_metrics(metrics)
    except Exception:
        return set()


def _video_poster_tool() -> str | None:
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    return None


def _extract_video_poster_ffmpeg(*, video_path: Path, poster_path: Path) -> None:
    poster_path.parent.mkdir(parents=True, exist_ok=True)
    attempts = [
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            "00:00:00.500",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(poster_path),
        ],
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(poster_path),
        ],
    ]
    last_error: Exception | None = None
    for args in attempts:
        try:
            subprocess.run(
                args,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if poster_path.exists() and poster_path.stat().st_size > 0:
                return
            raise RuntimeError("poster file not created")
        except Exception as e:
            last_error = e
    raise RuntimeError(f"poster extraction failed: {last_error}")


def _split_pages_into_documents(total_pages: int, delimiter_pages: set[int]) -> tuple[dict[int, tuple[int, int, int]], int]:
    docs: list[list[int]] = []
    current_doc: list[int] | None = None
    for page_idx in range(1, total_pages + 1):
        if page_idx in delimiter_pages:
            if current_doc:
                docs.append(current_doc)
            current_doc = []
            continue
        if current_doc is None:
            docs.append([page_idx])
        else:
            current_doc.append(page_idx)
    if current_doc:
        docs.append(current_doc)
    page_map: dict[int, tuple[int, int, int]] = {}
    for doc_idx, doc_pages in enumerate(docs, start=1):
        doc_len = len(doc_pages)
        for doc_page, page_idx in enumerate(doc_pages, start=1):
            page_map[page_idx] = (doc_idx, doc_page, doc_len)
    return (page_map, len(docs))


def import_scans_inbox(
    db: Db,
    inbox_dir: Path,
    store_dir: Path,
    *,
    format: str = "jpg",
    limit: int = 0,
    max_pages: int = 0,
    renderer: str = "auto",
    split_on_delimiters: bool = True,
) -> dict[str, Any]:
    inbox = inbox_dir.expanduser().resolve()
    store = store_dir.expanduser().resolve()
    if not inbox.exists():
        raise FileNotFoundError(f"Inbox not found: {inbox}")
    store.mkdir(parents=True, exist_ok=True)

    renderer = _select_pdf_renderer(renderer)

    seen_files = 0
    skipped = 0
    duplicates_skipped = 0
    unsupported_files = 0
    delimiter_pages_skipped = 0
    detected_documents = 0
    errors: list[dict[str, str]] = []
    imported_at = _now_iso()

    existing_refs = {str(r["source_ref"]) for r in db.query("select source_ref from assets where source='scan'")}
    pending_refs: set[str] = set()
    rows: list[tuple[Any, ...]] = []
    for path in sorted(inbox.rglob("*")):
        if limit and seen_files >= limit:
            break
        if not path.is_file():
            continue
        seen_files += 1

        suffix = path.suffix.lower()
        try:
            if suffix in IMAGE_EXTS:
                sha = _sha256_file(path)
                source_ref = f"scan://{sha}"
                if source_ref in existing_refs or source_ref in pending_refs:
                    duplicates_skipped += 1
                    skipped += 1
                    continue
                dest = store / "originals" / "scan"
                dest.mkdir(parents=True, exist_ok=True)
                out_path = dest / f"{sha}{suffix}"
                if not out_path.exists():
                    shutil.copy2(path, out_path)
                pending_refs.add(source_ref)
                rows.append(
                    (
                        str(uuid.uuid4()),
                        "scan",
                        source_ref,
                        path.stem,
                        None,
                        None,
                        None,
                        imported_at,
                        str(out_path),
                        str(out_path),
                        sha,
                        "image",
                        "scan",
                    )
                )
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
                delimiter_pages: set[int] = set()
                if split_on_delimiters:
                    delimiter_pages = _detect_pdf_delimiter_pages(
                        pdf_path=pdf_out, max_pages=max_pages, renderer=renderer
                    )
                page_map, doc_count = _split_pages_into_documents(len(files), delimiter_pages)
                detected_documents += doc_count
                for idx, img_path in enumerate(files, start=1):
                    if idx in delimiter_pages:
                        delimiter_pages_skipped += 1
                        skipped += 1
                        continue
                    doc_meta = page_map.get(idx)
                    if not doc_meta:
                        skipped += 1
                        continue
                    doc_idx, doc_page, doc_len = doc_meta
                    source_ref = f"scan://{sha}#p{idx}"
                    if source_ref in existing_refs or source_ref in pending_refs:
                        duplicates_skipped += 1
                        skipped += 1
                        continue
                    if doc_len <= 1:
                        title = f"{path.stem} - doc {doc_idx}"
                    else:
                        title = f"{path.stem} - doc {doc_idx} p{doc_page}"
                    pending_refs.add(source_ref)
                    rows.append(
                        (
                            str(uuid.uuid4()),
                            "scan",
                            source_ref,
                            title,
                            None,
                            None,
                            None,
                            imported_at,
                            str(img_path),
                            str(img_path),
                            sha,
                            "image",
                            "scan",
                        )
                    )
                continue

            unsupported_files += 1
            skipped += 1
        except Exception as e:
            errors.append({"file": str(path), "error": str(e)})

    db.executemany(
        """
        insert or ignore into assets
          (
            id, source, source_ref, title, description, board, created_at, imported_at, image_url,
            stored_path, sha256, media_status, content_kind
          )
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        rows,
    )
    created = int(
        db.query_value(
            "select count(*) from assets where source='scan' and imported_at=?",
            (imported_at,),
        )
        or 0
    )

    return {
        "source": "scan",
        "inbox": str(inbox),
        "imported_at": imported_at,
        "parsed_files": seen_files,
        "created_assets": created,
        "skipped_files": skipped,
        "duplicates_skipped": duplicates_skipped,
        "unsupported_files": unsupported_files,
        "delimiter_pages_skipped": delimiter_pages_skipped,
        "delimiter_detection_enabled": bool(split_on_delimiters),
        "detected_documents": detected_documents,
        "errors": errors[:25],
        "note": "Errors are truncated to 25 in output.",
        "renderer": renderer,
    }


def import_photos_inbox(
    db: Db,
    inbox_dir: Path,
    store_dir: Path,
    *,
    limit: int = 0,
    source: str = "photo",
    content_kind: str = "photo",
    source_ref_scheme: str = "photo",
) -> dict[str, Any]:
    inbox = inbox_dir.expanduser().resolve()
    store = store_dir.expanduser().resolve()
    if not inbox.exists():
        raise FileNotFoundError(f"Inbox not found: {inbox}")
    store.mkdir(parents=True, exist_ok=True)

    seen_files = 0
    skipped = 0
    duplicates_skipped = 0
    unsupported_files = 0
    errors: list[dict[str, str]] = []
    imported_at = _now_iso()

    existing_refs = {str(r["source_ref"]) for r in db.query("select source_ref from assets where source=?", (source,))}
    pending_refs: set[str] = set()
    rows: list[tuple[Any, ...]] = []
    for path in sorted(inbox.rglob("*")):
        if limit and seen_files >= limit:
            break
        if not path.is_file():
            continue
        seen_files += 1
        suffix = path.suffix.lower()
        if suffix not in PHOTO_EXTS:
            unsupported_files += 1
            skipped += 1
            continue
        try:
            sha = _sha256_file(path)
            source_ref = f"{source_ref_scheme}://{sha}"
            if source_ref in existing_refs or source_ref in pending_refs:
                duplicates_skipped += 1
                skipped += 1
                continue
            dest = store / "originals" / "photo"
            dest.mkdir(parents=True, exist_ok=True)
            out_path = dest / f"{sha}{suffix}"
            if not out_path.exists():
                shutil.copy2(path, out_path)
            pending_refs.add(source_ref)
            rows.append(
                (
                    str(uuid.uuid4()),
                    source,
                    source_ref,
                    path.stem,
                    None,
                    None,
                    None,
                    imported_at,
                    str(out_path),
                    str(out_path),
                    sha,
                    "image",
                    content_kind,
                )
            )
        except Exception as e:
            errors.append({"file": str(path), "error": str(e)})

    db.executemany(
        """
        insert or ignore into assets
          (
            id, source, source_ref, title, description, board, created_at, imported_at, image_url,
            stored_path, sha256, media_status, content_kind
          )
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        rows,
    )
    created = int(
        db.query_value(
            "select count(*) from assets where source=? and imported_at=?",
            (source, imported_at),
        )
        or 0
    )

    return {
        "source": source,
        "inbox": str(inbox),
        "imported_at": imported_at,
        "parsed_files": seen_files,
        "created_assets": created,
        "skipped_files": skipped,
        "duplicates_skipped": duplicates_skipped,
        "unsupported_files": unsupported_files,
        "errors": errors[:25],
        "note": "Errors are truncated to 25 in output.",
    }


def import_videos_inbox(
    db: Db,
    inbox_dir: Path,
    store_dir: Path,
    *,
    limit: int = 0,
    source: str = "video",
    content_kind: str = "video",
    source_ref_scheme: str = "video",
) -> dict[str, Any]:
    inbox = inbox_dir.expanduser().resolve()
    store = store_dir.expanduser().resolve()
    if not inbox.exists():
        raise FileNotFoundError(f"Inbox not found: {inbox}")
    store.mkdir(parents=True, exist_ok=True)

    seen_files = 0
    skipped = 0
    duplicates_skipped = 0
    unsupported_files = 0
    errors: list[dict[str, str]] = []
    imported_at = _now_iso()
    poster_tool = _video_poster_tool()
    poster_generated = 0
    poster_errors: list[dict[str, str]] = []

    existing_refs = {str(r["source_ref"]) for r in db.query("select source_ref from assets where source=?", (source,))}
    pending_refs: set[str] = set()
    rows: list[tuple[Any, ...]] = []
    for path in sorted(inbox.rglob("*")):
        if limit and seen_files >= limit:
            break
        if not path.is_file():
            continue
        seen_files += 1
        suffix = path.suffix.lower()
        if suffix not in VIDEO_EXTS:
            unsupported_files += 1
            skipped += 1
            continue
        try:
            asset_id = str(uuid.uuid4())
            sha = _sha256_file(path)
            source_ref = f"{source_ref_scheme}://{sha}"
            if source_ref in existing_refs or source_ref in pending_refs:
                duplicates_skipped += 1
                skipped += 1
                continue
            dest = store / "originals" / "video"
            dest.mkdir(parents=True, exist_ok=True)
            out_path = dest / f"{sha}{suffix}"
            if not out_path.exists():
                shutil.copy2(path, out_path)

            thumb_path = ""
            if poster_tool == "ffmpeg":
                poster_path = store / "thumbs" / "video" / f"{asset_id}.jpg"
                try:
                    _extract_video_poster_ffmpeg(video_path=out_path, poster_path=poster_path)
                    thumb_path = str(poster_path)
                    poster_generated += 1
                except Exception as e:
                    poster_errors.append({"file": str(path), "error": str(e)})

            pending_refs.add(source_ref)
            rows.append(
                (
                    asset_id,
                    source,
                    source_ref,
                    path.stem,
                    None,
                    None,
                    None,
                    imported_at,
                    None,
                    thumb_path or None,
                    str(out_path),
                    sha,
                    "video",
                    content_kind,
                    str(out_path),
                )
            )
        except Exception as e:
            errors.append({"file": str(path), "error": str(e)})

    db.executemany(
        """
        insert or ignore into assets
          (
            id, source, source_ref, title, description, board, created_at, imported_at, image_url,
            thumb_path, stored_path, sha256, media_status, content_kind, stored_video_path
          )
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        rows,
    )
    created = int(
        db.query_value(
            "select count(*) from assets where source=? and imported_at=?",
            (source, imported_at),
        )
        or 0
    )

    return {
        "source": source,
        "inbox": str(inbox),
        "imported_at": imported_at,
        "parsed_files": seen_files,
        "created_assets": created,
        "skipped_files": skipped,
        "duplicates_skipped": duplicates_skipped,
        "unsupported_files": unsupported_files,
        "errors": errors[:25],
        "poster": {
            "tool": poster_tool or "",
            "generated": poster_generated,
            "errors": poster_errors[:25],
            "note": "Poster generation errors are truncated to 25 in output.",
        },
        "note": "Errors are truncated to 25 in output.",
    }
