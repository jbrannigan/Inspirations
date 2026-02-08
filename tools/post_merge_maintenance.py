#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


PROTECTED_BRANCHES = {"main", "master", "develop", "dev"}


def _run(cmd: list[str], *, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )


def _output(cmd: list[str], *, cwd: Path) -> str:
    try:
        return _run(cmd, cwd=cwd).stdout.strip()
    except Exception:
        return ""


def _is_ancestor(repo: Path, candidate: str, target: str) -> bool:
    proc = subprocess.run(
        ["git", "merge-base", "--is-ancestor", candidate, target],
        cwd=str(repo),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return proc.returncode == 0


def _gone_tracking_branches(repo: Path) -> list[str]:
    rows = _output(
        ["git", "for-each-ref", "--format=%(refname:short)\t%(upstream:track)", "refs/heads"],
        cwd=repo,
    ).splitlines()
    out: list[str] = []
    for row in rows:
        if not row.strip():
            continue
        parts = row.split("\t")
        name = parts[0].strip()
        track = parts[1].strip() if len(parts) > 1 else ""
        if track == "[gone]":
            out.append(name)
    return out


def _delete_stale_branches(repo: Path, *, main_branch: str) -> dict[str, list[str]]:
    deleted: list[str] = []
    skipped: list[str] = []
    current = _output(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo)
    for branch in _gone_tracking_branches(repo):
        if branch == current or branch in PROTECTED_BRANCHES:
            skipped.append(branch)
            continue
        if not _is_ancestor(repo, branch, main_branch):
            skipped.append(branch)
            continue
        proc = subprocess.run(
            ["git", "branch", "-d", branch],
            cwd=str(repo),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if proc.returncode == 0:
            deleted.append(branch)
        else:
            skipped.append(branch)
    return {"deleted": deleted, "skipped": skipped}


def _write_checkpoints(repo: Path, *, note: str) -> None:
    checkpoint_dir = repo / "data" / "session_checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stamped_path = checkpoint_dir / f"checkpoint_{stamp}.json"
    latest_path = checkpoint_dir / "last_checkpoint.json"

    env = dict(os.environ)
    env["PYTHONPATH"] = "src"
    cmd = [
        "python3",
        "tools/session_checkpoint.py",
        "--no-append",
        "--note",
        note,
        "--next",
        "Read docs/next_steps.md, then run PYTHONPATH=src python3 tools/session_sync.py",
        "--json-out",
        str(stamped_path),
    ]
    subprocess.run(cmd, cwd=str(repo), env=env, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if stamped_path.exists():
        shutil.copy2(stamped_path, latest_path)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Post-merge maintenance: stale branch cleanup + local checkpoint snapshot.")
    p.add_argument("--repo", default=".")
    p.add_argument("--main-branch", default="main")
    p.add_argument("--hook-source", default="manual")
    p.add_argument("--squash", default="0")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    repo = Path(args.repo).resolve()
    branch = _output(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo)
    if branch != args.main_branch:
        print(f"skip: current branch is {branch}, expected {args.main_branch}")
        return 0

    subprocess.run(["git", "fetch", "--prune", "origin"], cwd=str(repo), check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    result = _delete_stale_branches(repo, main_branch=args.main_branch)
    note = (
        f"Auto checkpoint from {args.hook_source} hook (squash={args.squash}). "
        f"Deleted stale merged branches: {', '.join(result['deleted']) if result['deleted'] else 'none'}."
    )
    _write_checkpoints(repo, note=note)
    print(f"deleted={len(result['deleted'])} skipped={len(result['skipped'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
