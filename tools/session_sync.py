#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _run(cmd: list[str], cwd: Path) -> str:
    try:
        return subprocess.check_output(cmd, cwd=str(cwd), text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return ""


def _query_one(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    if not row:
        return 0
    return int(row[0] or 0)


def _latest_batch_meta(out_dir: Path) -> dict[str, Any] | None:
    meta_files = sorted(out_dir.glob("batch_*/meta_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not meta_files:
        return None
    path = meta_files[0]
    try:
        payload = json.loads(path.read_text())
    except Exception:
        payload = {}
    return {
        "path": str(path),
        "batch_name": payload.get("batch_name") or payload.get("name") or "",
        "state": payload.get("state") or payload.get("batch_state") or "",
    }


def snapshot(*, repo: Path, db_path: Path, source: str, provider: str, model: str, batch_out: Path) -> dict[str, Any]:
    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], repo)
    status_lines = _run(["git", "status", "--short"], repo).splitlines()

    with sqlite3.connect(db_path) as conn:
        total_assets = _query_one(conn, "select count(*) from assets where source = ?", (source,))
        tagged_assets = _query_one(
            conn,
            """
            select count(distinct ai.asset_id)
            from asset_ai ai
            join assets a on a.id = ai.asset_id
            where a.source = ? and ai.provider = ? and ai.model = ?
            """,
            (source, provider, model),
        )
        tagged_assets_any_model = _query_one(
            conn,
            """
            select count(distinct ai.asset_id)
            from asset_ai ai
            join assets a on a.id = ai.asset_id
            where a.source = ? and ai.provider = ?
            """,
            (source, provider),
        )
        remaining_assets = _query_one(
            conn,
            """
            select count(*)
            from assets a
            where a.source = ?
              and a.id not in (
                select asset_id from asset_ai where provider = ? and model = ?
              )
            """,
            (source, provider, model),
        )
        remaining_assets_any_model = _query_one(
            conn,
            """
            select count(*)
            from assets a
            where a.source = ?
              and a.id not in (
                select asset_id from asset_ai where provider = ?
              )
            """,
            (source, provider),
        )
        remaining_missing_stored = _query_one(
            conn,
            """
            select count(*)
            from assets a
            where a.source = ?
              and (a.stored_path is null or a.stored_path = '')
              and a.id not in (
                select asset_id from asset_ai where provider = ? and model = ?
              )
            """,
            (source, provider, model),
        )
        remaining_missing_thumb = _query_one(
            conn,
            """
            select count(*)
            from assets a
            where a.source = ?
              and (a.thumb_path is null or a.thumb_path = '')
              and a.id not in (
                select asset_id from asset_ai where provider = ? and model = ?
              )
            """,
            (source, provider, model),
        )
        error_rows = _query_one(
            conn,
            """
            select count(*)
            from asset_ai_errors e
            join assets a on a.id = e.asset_id
            where a.source = ? and e.provider = ? and coalesce(e.model, '') = ?
            """,
            (source, provider, model),
        )
        actionable_error_rows = _query_one(
            conn,
            """
            select count(*)
            from asset_ai_errors e
            join assets a on a.id = e.asset_id
            where a.source = ? and e.provider = ? and coalesce(e.model, '') = ?
              and not exists (
                select 1
                from asset_ai ai
                where ai.asset_id = e.asset_id
                  and ai.provider = e.provider
                  and ai.created_at >= e.created_at
              )
            """,
            (source, provider, model),
        )
        recitation_blocked_assets = _query_one(
            conn,
            """
            select count(distinct e.asset_id)
            from asset_ai_errors e
            join assets a on a.id = e.asset_id
            where a.source = ?
              and e.provider = ?
              and coalesce(e.model, '') = ?
              and coalesce(e.raw, '') like '%"finishReason": "RECITATION"%'
            """,
            (source, provider, model),
        )
        model_rows = conn.execute(
            """
            select ai.model, count(distinct ai.asset_id) as n
            from asset_ai ai
            join assets a on a.id = ai.asset_id
            where a.source = ? and ai.provider = ?
            group by ai.model
            order by n desc, ai.model asc
            """,
            (source, provider),
        ).fetchall()
        latest_run = conn.execute(
            """
            select id, created_at
            from ai_runs
            where provider = ? and model = ?
            order by created_at desc
            limit 1
            """,
            (provider, model),
        ).fetchone()

    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "repo": str(repo),
        "branch": branch,
        "dirty_files": len([l for l in status_lines if l.strip()]),
        "source": source,
        "provider": provider,
        "model": model,
        "total_assets": total_assets,
        "tagged_assets": tagged_assets,
        "remaining_assets": remaining_assets,
        "tagged_assets_any_model": tagged_assets_any_model,
        "remaining_assets_any_model": remaining_assets_any_model,
        "remaining_missing_stored": remaining_missing_stored,
        "remaining_missing_thumb": remaining_missing_thumb,
        "error_rows": error_rows,
        "actionable_error_rows": actionable_error_rows,
        "recitation_blocked_assets": recitation_blocked_assets,
        "model_breakdown": [{"model": r[0], "assets": int(r[1])} for r in model_rows],
        "latest_run": {
            "id": (latest_run[0] if latest_run else ""),
            "created_at": (latest_run[1] if latest_run else ""),
        },
        "latest_batch_meta": _latest_batch_meta(batch_out),
    }


def print_text(s: dict[str, Any]) -> None:
    print(f"Snapshot UTC: {s['timestamp_utc']}")
    print(f"Repo: {s['repo']}")
    print(f"Branch: {s['branch'] or '(unknown)'}")
    print(f"Dirty files: {s['dirty_files']}")
    print(
        f"Tagging: source={s['source']} provider={s['provider']} model={s['model']}"
    )
    print(f"Assets total: {s['total_assets']}")
    print(f"Assets tagged (model={s['model']}): {s['tagged_assets']}")
    print(f"Assets remaining (model={s['model']}): {s['remaining_assets']}")
    print(f"Assets tagged (provider any-model): {s['tagged_assets_any_model']}")
    print(f"Assets remaining (provider any-model): {s['remaining_assets_any_model']}")
    print(f"Remaining missing stored_path: {s['remaining_missing_stored']}")
    print(f"Remaining missing thumb_path: {s['remaining_missing_thumb']}")
    print(f"asset_ai_errors rows: {s['error_rows']}")
    print(f"asset_ai_errors actionable rows: {s['actionable_error_rows']}")
    print(f"RECITATION-blocked assets (model={s['model']}): {s['recitation_blocked_assets']}")
    breakdown = s.get("model_breakdown") or []
    if breakdown:
        rendered = ", ".join([f"{x['model']}={x['assets']}" for x in breakdown])
        print(f"Model coverage: {rendered}")
    run = s.get("latest_run") or {}
    if run.get("id"):
        print(f"Latest run: {run['id']} ({run.get('created_at', '')})")
    else:
        print("Latest run: none")
    meta = s.get("latest_batch_meta")
    if meta:
        print(f"Latest batch meta: {meta.get('path', '')}")
        if meta.get("batch_name") or meta.get("state"):
            print(f"Batch: {meta.get('batch_name', '')} state={meta.get('state', '')}")
    else:
        print("Latest batch meta: none")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Print a consistent session sync snapshot for Inspirations")
    p.add_argument("--repo", default=".")
    p.add_argument("--db", default="data/inspirations.sqlite")
    p.add_argument("--source", default="pinterest")
    p.add_argument("--provider", default="gemini")
    p.add_argument("--model", default="gemini-2.5-flash")
    p.add_argument("--batch-out", default="data/batch_jobs")
    p.add_argument("--json", action="store_true", help="Emit JSON")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    repo = Path(args.repo).resolve()
    db_path = Path(args.db)
    if not db_path.is_absolute():
        db_path = repo / db_path
    batch_out = Path(args.batch_out)
    if not batch_out.is_absolute():
        batch_out = repo / batch_out

    data = snapshot(
        repo=repo,
        db_path=db_path,
        source=args.source,
        provider=args.provider,
        model=args.model,
        batch_out=batch_out,
    )

    if args.json:
        print(json.dumps(data, indent=2, sort_keys=True))
    else:
        print_text(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
