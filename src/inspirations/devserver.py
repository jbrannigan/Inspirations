from __future__ import annotations

import os
import signal
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


def _start_child(*, host: str, port: int, db_path: Path, app_dir: Path, store_dir: Path) -> int:
    pid = os.fork()
    if pid == 0:
        run_server(host=host, port=port, db_path=db_path, app_dir=app_dir, store_dir=store_dir)
        return 0
    return pid


def _stop_child(pid: int) -> None:
    if pid <= 0:
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return

    deadline = time.time() + 2.0
    while time.time() < deadline:
        try:
            done_pid, _ = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            return
        if done_pid == pid:
            return
        time.sleep(0.05)

    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    try:
        os.waitpid(pid, 0)
    except ChildProcessError:
        return


def _child_exited(pid: int) -> bool:
    if pid <= 0:
        return True
    try:
        done_pid, _ = os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        return True
    return done_pid == pid


def run_with_reload(*, host: str, port: int, db_path: Path, app_dir: Path, store_dir: Path) -> None:
    root = Path.cwd()
    last = _scan(root)
    pid = _start_child(host=host, port=port, db_path=db_path, app_dir=app_dir, store_dir=store_dir)
    if pid == 0:
        return
    try:
        while True:
            time.sleep(0.5)
            if _child_exited(pid):
                # Child can die on startup/runtime exceptions; restart automatically.
                time.sleep(0.15)
                pid = _start_child(host=host, port=port, db_path=db_path, app_dir=app_dir, store_dir=store_dir)
                if pid == 0:
                    return
                last = _scan(root)
                continue
            curr = _scan(root)
            if _changed(last, curr):
                _stop_child(pid)
                # Give the OS a short moment to release the listening socket
                # before re-binding on the same port.
                time.sleep(0.15)
                pid = _start_child(host=host, port=port, db_path=db_path, app_dir=app_dir, store_dir=store_dir)
                if pid == 0:
                    return
                last = curr
    except KeyboardInterrupt:
        _stop_child(pid)
