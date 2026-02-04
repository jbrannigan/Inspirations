from __future__ import annotations

import os
import time
from pathlib import Path

from .server import run_server


WATCH_DIRS = ["app", "src"]
WATCH_EXTS = {".py", ".js", ".css", ".html"}


def _scan(root: Path) -> dict[str, float]:
    out: dict[str, float] = {}
    for rel in WATCH_DIRS:
        base = (root / rel).resolve()
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix.lower() not in WATCH_EXTS:
                continue
            out[str(p)] = p.stat().st_mtime
    return out


def _changed(prev: dict[str, float], curr: dict[str, float]) -> bool:
    if prev.keys() != curr.keys():
        return True
    for k, v in curr.items():
        if prev.get(k) != v:
            return True
    return False


def run_with_reload(*, host: str, port: int, db_path: Path, app_dir: Path, store_dir: Path) -> None:
    root = Path.cwd()
    last = _scan(root)
    pid = os.fork()
    if pid == 0:
        run_server(host=host, port=port, db_path=db_path, app_dir=app_dir, store_dir=store_dir)
        return
    try:
        while True:
            time.sleep(0.5)
            curr = _scan(root)
            if _changed(last, curr):
                os.kill(pid, 9)
                pid = os.fork()
                if pid == 0:
                    run_server(host=host, port=port, db_path=db_path, app_dir=app_dir, store_dir=store_dir)
                    return
                last = curr
    except KeyboardInterrupt:
        os.kill(pid, 9)

