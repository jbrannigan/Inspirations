from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from .db import Db


def _can_use_pillow() -> bool:
    try:
        import PIL  # noqa: F401
    except Exception:
        return False
    return True


def _make_thumb_pillow(src: Path, dst: Path, size: int) -> None:
    from PIL import Image

    dst.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as im:
        im = im.convert("RGB")
        im.thumbnail((size, size))
        im.save(dst, format="JPEG", quality=85)


def _select_tool(tool: str) -> str | None:
    if tool != "auto":
        return tool
    if shutil.which("sips"):
        return "sips"
    if shutil.which("magick"):
        return "magick"
    if _can_use_pillow():
        return "pillow"
    return None


def _make_thumb(tool: str, src: Path, dst: Path, size: int) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if tool == "sips":
        subprocess.run(["sips", "-Z", str(size), str(src), "--out", str(dst)], check=True)
        return
    if tool == "magick":
        subprocess.run(["magick", str(src), "-resize", f"{size}x{size}", str(dst)], check=True)
        return
    if tool == "pillow":
        _make_thumb_pillow(src, dst, size)
        return
    raise ValueError(f"Unknown thumbnail tool: {tool}")


def generate_thumbnails(
    db: Db,
    store_dir: Path,
    *,
    size: int = 512,
    limit: int = 0,
    source: str | None = None,
    tool: str = "auto",
) -> dict[str, Any]:
    tool = _select_tool(tool)
    if tool is None:
        return {
            "attempted": 0,
            "generated": 0,
            "errors": [{"error": "No thumbnail tool available (install macOS sips or ImageMagick)"}],
        }

    args: list[Any] = []
    if source:
        args.append(source)
        rows = db.query(
            "select id, stored_path, source from assets where source=? and stored_path is not null and (thumb_path is null or thumb_path='') order by imported_at asc",
            tuple(args),
        )
    else:
        rows = db.query(
            "select id, stored_path, source from assets where stored_path is not null and (thumb_path is null or thumb_path='') order by imported_at asc"
        )

    attempted = 0
    generated = 0
    errors: list[dict[str, str]] = []

    for r in rows:
        if limit and attempted >= limit:
            break
        attempted += 1
        asset_id = r["id"]
        stored = Path(r["stored_path"])
        src = r["source"]
        try:
            if str(stored).lower().endswith(".bin"):
                errors.append({"id": asset_id, "error": "Skipping .bin (not an image)"})
                continue
            dst = store_dir / "thumbs" / src / f"{asset_id}.jpg"
            try:
                _make_thumb(tool, stored, dst, size)
                db.exec("update assets set thumb_path=? where id=?", (str(dst), asset_id))
                generated += 1
            except Exception as e:
                if tool != "pillow" and _can_use_pillow():
                    try:
                        _make_thumb("pillow", stored, dst, size)
                        db.exec("update assets set thumb_path=? where id=?", (str(dst), asset_id))
                        generated += 1
                        continue
                    except Exception:
                        pass
                # When raster tools cannot convert SVG, use the original SVG as preview.
                if stored.suffix.lower() == ".svg" and stored.exists():
                    db.exec("update assets set thumb_path=? where id=?", (str(stored), asset_id))
                    generated += 1
                    continue
                errors.append({"id": asset_id, "error": str(e)})
        except Exception as e:
            errors.append({"id": asset_id, "error": str(e)})

    return {
        "tool": tool,
        "attempted": attempted,
        "generated": generated,
        "errors": errors[:25],
        "note": "Errors are truncated to 25 in output.",
    }
