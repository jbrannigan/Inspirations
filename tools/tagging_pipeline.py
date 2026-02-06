#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from inspirations.ai import DEFAULT_GEMINI_MODEL, _mime_from_path, _now_iso
from inspirations.db import Db, ensure_schema
from inspirations.storage import download_and_attach_originals
from inspirations.thumbnails import generate_thumbnails

DB_PATH = Path(os.environ.get("DB_PATH", "data/inspirations.sqlite"))
STORE_DIR = Path(os.environ.get("STORE_DIR", "store"))
MODEL = os.environ.get("MODEL", DEFAULT_GEMINI_MODEL)
SOURCE = os.environ.get("SOURCE", "pinterest")
IMAGE_KIND = os.environ.get("IMAGE_KIND", "thumb")

DEFAULT_INTERACTIVE_RPS = float(os.environ.get("TAG_EST_INTERACTIVE_RPS", "0.7"))
DEFAULT_BATCH_RPS = float(os.environ.get("TAG_EST_BATCH_RPS", "15.0"))
DEFAULT_BATCH_OVERHEAD_S = float(os.environ.get("TAG_EST_BATCH_OVERHEAD_S", "60"))
DEFAULT_MIN_BATCH = int(os.environ.get("TAG_AUTO_MIN_BATCH", "500"))
DEFAULT_COST_PER_ASSET = os.environ.get("TAG_EST_COST_PER_ASSET", "")
DEFAULT_COST_PER_ASSET = float(DEFAULT_COST_PER_ASSET) if DEFAULT_COST_PER_ASSET else None
DEFAULT_INPUT_TOKENS = os.environ.get("TAG_EST_INPUT_TOKENS", "")
DEFAULT_OUTPUT_TOKENS = os.environ.get("TAG_EST_OUTPUT_TOKENS", "")
DEFAULT_COST_PER_1K_IN = os.environ.get("TAG_COST_PER_1K_INPUT", "")
DEFAULT_COST_PER_1K_OUT = os.environ.get("TAG_COST_PER_1K_OUTPUT", "")
DEFAULT_RECITATION_FALLBACK_MODEL = os.environ.get("TAG_RECITATION_FALLBACK_MODEL", "gemini-2.0-flash")


def _candidate_rows(db: Db, source: str, model: str, limit: int) -> list[dict[str, Any]]:
    limit_sql = "" if not limit else f"limit {int(limit)}"
    return db.query(
        f"""
        select a.id, a.stored_path, a.thumb_path
        from assets a
        where a.source = ?
          and a.id not in (select asset_id from asset_ai where provider=?)
        order by a.imported_at asc
        {limit_sql}
        """,
        (source, "gemini"),
    )


def _insert_error_rows(db: Db, rows: list[tuple[str, str, str, str, str, str | None, str | None, str]]) -> None:
    if not rows:
        return
    db.executemany(
        """
        insert into asset_ai_errors
          (id, asset_id, provider, model, error, raw, run_id, created_at)
        values (?, ?, ?, ?, ?, ?, ?, ?);
        """,
        rows,
    )


def preflight(
    *,
    db: Db,
    source: str,
    model: str,
    image_kind: str,
    limit: int,
    store_dir: Path,
    repair_missing: bool,
    record_errors: bool,
) -> dict[str, Any]:
    ensure_schema(db)
    if repair_missing:
        download_and_attach_originals(db, store_dir, source, limit=0)
        generate_thumbnails(db, store_dir, source=source, limit=0)

    rows = _candidate_rows(db, source, model, limit)

    total = len(rows)
    missing_path = 0
    missing_file = 0
    unsupported = 0
    error_rows: list[tuple[str, str, str, str, str, str | None, str | None, str]] = []
    now = _now_iso()
    run_id = str(uuid.uuid4()) if record_errors else None

    for r in rows:
        asset_id = r["id"]
        path_str = r["thumb_path"] if image_kind == "thumb" else r["stored_path"]
        if not path_str:
            missing_path += 1
            if record_errors:
                error_rows.append(
                    (str(uuid.uuid4()), asset_id, "gemini", model, "Missing image path", None, run_id, now)
                )
            continue
        path = Path(path_str)
        if not path.exists():
            missing_file += 1
            if record_errors:
                error_rows.append(
                    (str(uuid.uuid4()), asset_id, "gemini", model, "Missing image file", path_str, run_id, now)
                )
            continue
        if _mime_from_path(path) is None:
            unsupported += 1
            if record_errors:
                error_rows.append(
                    (
                        str(uuid.uuid4()),
                        asset_id,
                        "gemini",
                        model,
                        f"Unsupported image type: {path.suffix}",
                        path_str,
                        run_id,
                        now,
                    )
                )
            continue

    if record_errors and error_rows:
        _insert_error_rows(db, error_rows)

    valid = total - missing_path - missing_file - unsupported
    return {
        "total": total,
        "valid": valid,
        "missing_path": missing_path,
        "missing_file": missing_file,
        "unsupported": unsupported,
        "repair_missing": repair_missing,
    }


def estimate_time(count: int, interactive_rps: float, batch_rps: float, batch_overhead_s: float) -> dict[str, float]:
    interactive_s = count / interactive_rps if interactive_rps > 0 else -1
    batch_s = batch_overhead_s + (count / batch_rps if batch_rps > 0 else 0)
    return {
        "interactive_s": interactive_s,
        "batch_s": batch_s,
    }


def estimate_cost(
    count: int,
    *,
    cost_per_asset: float | None,
    input_tokens: float | None,
    output_tokens: float | None,
    cost_per_1k_input: float | None,
    cost_per_1k_output: float | None,
) -> float | None:
    if cost_per_asset is not None:
        return count * cost_per_asset
    if (
        input_tokens is not None
        and output_tokens is not None
        and cost_per_1k_input is not None
        and cost_per_1k_output is not None
    ):
        return count * ((input_tokens / 1000.0) * cost_per_1k_input + (output_tokens / 1000.0) * cost_per_1k_output)
    return None


def run_batch(args: argparse.Namespace) -> None:
    cmd = [
        sys.executable,
        "tools/tagging_batch.py",
        "--source",
        args.source,
        "--image-kind",
        args.image_kind,
        "--model",
        args.model,
        "--limit",
        str(args.limit),
        "--out-dir",
        args.out_dir,
        "run",
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = "src"
    if args.api_key:
        env["GEMINI_API_KEY"] = args.api_key
    subprocess.run(cmd, check=True, env=env)


def run_interactive(args: argparse.Namespace) -> None:
    cmd = [sys.executable, "tools/tagging_runner.py"]
    env = os.environ.copy()
    env["PYTHONPATH"] = "src"
    if args.api_key:
        env["GEMINI_API_KEY"] = args.api_key
    env["MODEL"] = args.model
    env["SOURCE"] = args.source
    env["IMAGE_KIND"] = args.image_kind
    env["TAG_BATCH_SIZE"] = str(args.batch_size)
    env["TAG_WORKERS"] = str(args.workers)
    env["REQ_TIMEOUT_S"] = str(args.req_timeout_s)
    env["BATCH_TIMEOUT_S"] = str(args.batch_timeout_s)
    env["RECITATION_FALLBACK_MODEL"] = args.recitation_fallback_model
    subprocess.run(cmd, check=True, env=env)


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Gemini tagging pipeline (preflight + estimate + auto mode)")
    p.add_argument("--db", default=str(DB_PATH))
    p.add_argument("--store", default=str(STORE_DIR))
    p.add_argument("--source", default=SOURCE)
    p.add_argument("--image-kind", choices=["thumb", "original"], default=IMAGE_KIND)
    p.add_argument("--model", default=MODEL)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--mode", choices=["auto", "batch", "interactive"], default="auto")
    p.add_argument("--min-batch", type=int, default=DEFAULT_MIN_BATCH)
    p.add_argument(
        "--repair-missing",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Repair missing originals/thumbs before tagging",
    )
    p.add_argument(
        "--record-errors",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Record preflight failures to asset_ai_errors",
    )
    p.add_argument("--estimate-only", action="store_true")

    p.add_argument("--api-key", default=os.environ.get("GEMINI_API_KEY", ""))

    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--batch-size", type=int, default=60)
    p.add_argument("--req-timeout-s", type=int, default=60)
    p.add_argument("--batch-timeout-s", type=int, default=240)
    p.add_argument(
        "--recitation-fallback-model",
        default=DEFAULT_RECITATION_FALLBACK_MODEL,
        help="Fallback model when primary returns finishReason=RECITATION (empty disables fallback)",
    )

    p.add_argument("--est-interactive-rps", type=float, default=DEFAULT_INTERACTIVE_RPS)
    p.add_argument("--est-batch-rps", type=float, default=DEFAULT_BATCH_RPS)
    p.add_argument("--est-batch-overhead-s", type=float, default=DEFAULT_BATCH_OVERHEAD_S)
    p.add_argument("--est-cost-per-asset", type=float, default=DEFAULT_COST_PER_ASSET)
    p.add_argument("--est-input-tokens", type=float, default=float(DEFAULT_INPUT_TOKENS) if DEFAULT_INPUT_TOKENS else None)
    p.add_argument("--est-output-tokens", type=float, default=float(DEFAULT_OUTPUT_TOKENS) if DEFAULT_OUTPUT_TOKENS else None)
    p.add_argument("--cost-per-1k-input", type=float, default=float(DEFAULT_COST_PER_1K_IN) if DEFAULT_COST_PER_1K_IN else None)
    p.add_argument("--cost-per-1k-output", type=float, default=float(DEFAULT_COST_PER_1K_OUT) if DEFAULT_COST_PER_1K_OUT else None)

    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if not args.api_key:
        raise SystemExit("GEMINI_API_KEY is required")

    db_path = Path(args.db)
    store_dir = Path(args.store)

    with Db(db_path) as db:
        pre = preflight(
            db=db,
            source=args.source,
            model=args.model,
            image_kind=args.image_kind,
            limit=args.limit,
            store_dir=store_dir,
            repair_missing=args.repair_missing,
            record_errors=args.record_errors,
        )

    estimates = estimate_time(
        pre["valid"],
        args.est_interactive_rps,
        args.est_batch_rps,
        args.est_batch_overhead_s,
    )
    cost_est = estimate_cost(
        pre["valid"],
        cost_per_asset=args.est_cost_per_asset,
        input_tokens=args.est_input_tokens,
        output_tokens=args.est_output_tokens,
        cost_per_1k_input=args.cost_per_1k_input,
        cost_per_1k_output=args.cost_per_1k_output,
    )

    chosen = args.mode
    if chosen == "auto":
        chosen = "batch" if pre["valid"] >= args.min_batch else "interactive"

    print("Preflight summary:")
    print(f"  total_candidates: {pre['total']}")
    print(f"  valid_candidates: {pre['valid']}")
    print(f"  missing_path:     {pre['missing_path']}")
    print(f"  missing_file:     {pre['missing_file']}")
    print(f"  unsupported:      {pre['unsupported']}")
    print(f"  repair_missing:   {pre['repair_missing']}")
    print(f"  recitation_fallback_model: {args.recitation_fallback_model or '(disabled)'}")
    print("Estimates:")
    print(f"  interactive_eta:  {estimates['interactive_s'] / 60:.1f} minutes")
    print(f"  batch_eta:        {estimates['batch_s'] / 60:.1f} minutes")
    if cost_est is None:
        print("  cost_estimate:    unknown (set --est-cost-per-asset or token pricing inputs)")
    else:
        print(f"  cost_estimate:    ${cost_est:,.2f}")
    print(f"Chosen mode: {chosen}")

    if args.estimate_only:
        return 0

    if chosen == "batch":
        run_batch(args)
    else:
        run_interactive(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
