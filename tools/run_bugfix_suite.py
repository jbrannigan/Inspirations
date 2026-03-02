#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path


def _run_step(name: str, command: list[str], cwd: Path, env: dict[str, str]) -> dict:
    t0 = time.time()
    proc = subprocess.run(
        command,
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    dt = round(time.time() - t0, 3)
    return {
        "name": name,
        "command": command,
        "exit_code": int(proc.returncode),
        "duration_seconds": dt,
        "ok": proc.returncode == 0,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    existing_py_path = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = "src" if not existing_py_path else f"src:{existing_py_path}"

    steps = [
        ("lint", ["ruff", "check", "src", "tests"]),
        (
            "unit_tests",
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        ),
    ]

    results = [_run_step(name, cmd, repo_root, env) for name, cmd in steps]
    ok = all(r["ok"] for r in results)

    report = {
        "suite": "bugfix_validation",
        "repo": str(repo_root),
        "python": sys.version.split()[0],
        "timestamp_epoch": int(time.time()),
        "ok": ok,
        "steps": results,
    }
    print(json.dumps(report, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
