#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import session_sync


def _run(cmd: list[str], cwd: Path) -> str:
    try:
        return subprocess.check_output(cmd, cwd=str(cwd), text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return ""


def _embedding_stats(db_path: Path, source: str) -> dict[str, Any]:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            select count(*)
            from asset_embeddings e
            join assets a on a.id = e.asset_id
            where a.source = ?
            """,
            (source,),
        ).fetchone()
        total = int(row[0] or 0) if row else 0
        models = conn.execute(
            """
            select e.model, count(*)
            from asset_embeddings e
            join assets a on a.id = e.asset_id
            where a.source = ?
            group by e.model
            order by count(*) desc, e.model asc
            """,
            (source,),
        ).fetchall()
    return {
        "total": total,
        "models": [{"model": str(r[0] or ""), "rows": int(r[1] or 0)} for r in models],
    }


def _render_checkpoint_markdown(
    *,
    snapshot: dict[str, Any],
    commit: str,
    upstream: str,
    embeddings: dict[str, Any],
    note: str,
    next_steps: list[str],
) -> str:
    model_breakdown = snapshot.get("model_breakdown") or []
    model_text = ", ".join(f"{x['model']}={x['assets']}" for x in model_breakdown) or "none"
    emb_models = embeddings.get("models") or []
    emb_text = ", ".join(f"{x['model']}={x['rows']}" for x in emb_models) or "none"

    lines = [
        f"## Session Checkpoint ({snapshot.get('timestamp_utc', '')})",
        f"- Branch: `{snapshot.get('branch') or '(unknown)'}`",
        f"- Commit: `{commit or '(unknown)'}`",
        f"- Upstream: `{upstream or '(none)'}`",
        f"- Dirty files: `{snapshot.get('dirty_files', 0)}`",
        (
            f"- Tagging: source={snapshot.get('source', '')} provider={snapshot.get('provider', '')} "
            f"model={snapshot.get('model', '')}"
        ),
        (
            f"- Coverage: total={snapshot.get('total_assets', 0)} "
            f"tagged_model={snapshot.get('tagged_assets', 0)} "
            f"remaining_model={snapshot.get('remaining_assets', 0)} "
            f"tagged_provider_any_model={snapshot.get('tagged_assets_any_model', 0)} "
            f"remaining_provider_any_model={snapshot.get('remaining_assets_any_model', 0)}"
        ),
        (
            f"- Asset integrity: missing_stored={snapshot.get('remaining_missing_stored', 0)} "
            f"missing_thumb={snapshot.get('remaining_missing_thumb', 0)}"
        ),
        (
            f"- Errors: rows={snapshot.get('error_rows', 0)} "
            f"actionable={snapshot.get('actionable_error_rows', 0)} "
            f"recitation_blocked={snapshot.get('recitation_blocked_assets', 0)}"
        ),
        f"- Model coverage breakdown: {model_text}",
        f"- Embeddings: total={embeddings.get('total', 0)} by_model={emb_text}",
    ]

    latest_run = snapshot.get("latest_run") or {}
    if latest_run.get("id"):
        lines.append(
            f"- Latest run: `{latest_run.get('id', '')}` ({latest_run.get('created_at', '')})"
        )
    latest_batch = snapshot.get("latest_batch_meta") or {}
    if latest_batch.get("path"):
        lines.append(
            f"- Latest batch meta: `{latest_batch.get('path', '')}` "
            f"name=`{latest_batch.get('batch_name', '')}` state=`{latest_batch.get('state', '')}`"
        )
    if note.strip():
        lines.append(f"- Notes: {note.strip()}")
    if next_steps:
        lines.append("- Next actions:")
        for idx, item in enumerate(next_steps, start=1):
            lines.append(f"  {idx}. {item}")

    return "\n".join(lines) + "\n"


def _append_text(path: Path, block: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        text = path.read_text(encoding="utf-8")
    else:
        text = "# Handoff\n"
    if not text.endswith("\n"):
        text += "\n"
    text += "\n" + block
    path.write_text(text, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Capture a durable session checkpoint for reboot-safe resumes.")
    p.add_argument("--repo", default=".")
    p.add_argument("--db", default="data/inspirations.sqlite")
    p.add_argument("--source", default="pinterest")
    p.add_argument("--provider", default="gemini")
    p.add_argument("--model", default="gemini-2.5-flash")
    p.add_argument("--batch-out", default="data/batch_jobs")
    p.add_argument("--handoff", default="docs/handoff.md")
    p.add_argument("--note", default="", help="Short summary of what changed in this session")
    p.add_argument(
        "--next",
        dest="next_steps",
        action="append",
        default=[],
        help="Repeat for each concrete next action",
    )
    p.add_argument("--no-append", action="store_true", help="Print checkpoint without appending to handoff")
    p.add_argument(
        "--json-out",
        default="",
        help="Optional path to write raw checkpoint payload JSON",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    repo = Path(args.repo).resolve()
    db_path = Path(args.db)
    if not db_path.is_absolute():
        db_path = (repo / db_path).resolve()
    batch_out = Path(args.batch_out)
    if not batch_out.is_absolute():
        batch_out = (repo / batch_out).resolve()
    handoff_path = Path(args.handoff)
    if not handoff_path.is_absolute():
        handoff_path = (repo / handoff_path).resolve()

    if not db_path.exists():
        raise SystemExit(f"DB not found: {db_path}")

    snapshot = session_sync.snapshot(
        repo=repo,
        db_path=db_path,
        source=args.source,
        provider=args.provider,
        model=args.model,
        batch_out=batch_out,
    )
    embeddings = _embedding_stats(db_path, args.source)
    commit = _run(["git", "rev-parse", "--short", "HEAD"], repo)
    upstream = _run(["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], repo)

    block = _render_checkpoint_markdown(
        snapshot=snapshot,
        commit=commit,
        upstream=upstream,
        embeddings=embeddings,
        note=args.note,
        next_steps=[x.strip() for x in args.next_steps if x.strip()],
    )
    print(block, end="")

    payload = {
        "snapshot": snapshot,
        "embeddings": embeddings,
        "commit": commit,
        "upstream": upstream,
        "note": args.note.strip(),
        "next_steps": [x.strip() for x in args.next_steps if x.strip()],
        "rendered_markdown": block,
    }
    if args.json_out.strip():
        out = Path(args.json_out)
        if not out.is_absolute():
            out = (repo / out).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    if not args.no_append:
        _append_text(handoff_path, block)
        print(f"\nAppended checkpoint to {handoff_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
