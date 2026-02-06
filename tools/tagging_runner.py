#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
import os
import sqlite3
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from inspirations.db import Db, ensure_schema
from inspirations.ai import (
    DEFAULT_GEMINI_MODEL,
    DEFAULT_GEMINI_PROMPT,
    _extract_json_object,
    _extract_response_text,
    _flatten_ai_labels,
    _gemini_generate,
    _has_finish_reason,
    _mime_from_path,
    _no_json_error_message,
    _now_iso,
)

DB_PATH = Path(os.environ.get("DB_PATH", "/Users/minime/Projects/Inspirations/data/inspirations.sqlite"))
LOG_PATH = Path(os.environ.get("PROGRESS_LOG", "/tmp/inspirations_gemini_tag_progress.log"))
MODEL = os.environ.get("MODEL", DEFAULT_GEMINI_MODEL)
RECITATION_FALLBACK_MODEL = os.environ.get("RECITATION_FALLBACK_MODEL", "gemini-2.0-flash").strip()
SOURCE = os.environ.get("SOURCE", "pinterest")
IMAGE_KIND = os.environ.get("IMAGE_KIND", "thumb")
BATCH = int(os.environ.get("TAG_BATCH_SIZE", "60"))
MAX_WORKERS = int(os.environ.get("TAG_WORKERS", "4"))
API_KEY = os.environ.get("GEMINI_API_KEY", "")
BATCH_TIMEOUT_S = int(os.environ.get("BATCH_TIMEOUT_S", "240"))
REQ_TIMEOUT_S = float(os.environ.get("REQ_TIMEOUT_S", "60"))


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def log(line: str) -> None:
    msg = f"[{_utc_now()}] {line}"
    print(msg, flush=True)
    with LOG_PATH.open("a") as f:
        f.write(msg + "\n")


def with_db(fn: Callable[[Db], Any], *, retries: int = 8, base_delay: float = 0.2) -> Any:
    for i in range(retries):
        try:
            with Db(DB_PATH) as db:
                ensure_schema(db)
                return fn(db)
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower() and i < retries - 1:
                time.sleep(base_delay * (2 ** i))
                continue
            raise


def remaining_count() -> int:
    return int(
        with_db(
            lambda db: db.query_value(
                """
                select count(*)
                from assets a
                where a.source = ?
                  and a.id not in (select asset_id from asset_ai where provider=?)
                """,
                (SOURCE, "gemini"),
            )
        )
        or 0
    )


def fetch_batch():
    return with_db(
        lambda db: db.query(
            """
            select a.id, a.title, a.description, a.board, a.stored_path, a.thumb_path
            from assets a
            where a.source = ?
              and a.id not in (select asset_id from asset_ai where provider=?)
            order by a.imported_at asc
            limit ?
            """,
            (SOURCE, "gemini", BATCH),
        )
    )


def process_row(r):
    asset_id = r["id"]
    preferred = r["thumb_path"] if IMAGE_KIND == "thumb" else r["stored_path"]
    fallback = r["stored_path"] if IMAGE_KIND == "thumb" else r["thumb_path"]
    path_str = preferred or fallback
    if not path_str:
        return asset_id, None, "No image available for tagging", MODEL, None
    path = Path(path_str)
    mime_type = _mime_from_path(path)
    if not mime_type:
        return asset_id, None, f"Unsupported image type: {path.suffix}", MODEL, str(path)
    try:
        image_b64 = base64.b64encode(path.read_bytes()).decode("ascii")
        resp = _gemini_generate(
            api_key=API_KEY,
            model=MODEL,
            prompt=DEFAULT_GEMINI_PROMPT,
            image_b64=image_b64,
            mime_type=mime_type,
            timeout_s=REQ_TIMEOUT_S,
        )
        used_model = MODEL
        raw_text = _extract_response_text(resp)
        payload = _extract_json_object(raw_text)
        if (
            payload is None
            and RECITATION_FALLBACK_MODEL
            and RECITATION_FALLBACK_MODEL != MODEL
            and _has_finish_reason(resp, "RECITATION")
        ):
            resp = _gemini_generate(
                api_key=API_KEY,
                model=RECITATION_FALLBACK_MODEL,
                prompt=DEFAULT_GEMINI_PROMPT,
                image_b64=image_b64,
                mime_type=mime_type,
                timeout_s=REQ_TIMEOUT_S,
            )
            used_model = RECITATION_FALLBACK_MODEL
            raw_text = _extract_response_text(resp)
            payload = _extract_json_object(raw_text)
        if not payload:
            raw = raw_text if raw_text else json.dumps(resp)
            return asset_id, None, _no_json_error_message(resp), used_model, raw[:10000]
        return asset_id, payload, None, used_model, None
    except Exception as e:
        return asset_id, None, str(e), MODEL, None


def write_results(
    run_id: str,
    now: str,
    results: list[tuple[str, dict[str, Any], str]],
) -> tuple[int, int]:
    labeled = 0
    fallback_labeled = 0

    def _write(db: Db) -> None:
        nonlocal labeled, fallback_labeled
        for asset_id, payload, used_model in results:
            try:
                existing_any_model = db.query_value(
                    "select count(*) from asset_ai where asset_id=? and provider='gemini'",
                    (asset_id,),
                )
                if int(existing_any_model or 0) > 0:
                    continue
                summary = str(payload.get("summary") or "").strip()
                db.exec(
                    "insert into asset_ai (id, asset_id, provider, model, summary, json, created_at) values (?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(uuid.uuid4()),
                        asset_id,
                        "gemini",
                        used_model,
                        summary or None,
                        json.dumps(payload),
                        now,
                    ),
                )
                if summary:
                    db.exec("update assets set ai_summary=? where id=?", (summary, asset_id))
                labels = _flatten_ai_labels(payload)
                for lab in labels:
                    db.exec(
                        """
                        insert or ignore into asset_labels
                          (id, asset_id, label, confidence, source, model, run_id, created_at)
                        values (?, ?, ?, ?, ?, ?, ?, ?);
                        """,
                        (str(uuid.uuid4()), asset_id, lab, 0.7, "ai", used_model, run_id, now),
                    )
                labeled += 1
                if used_model != MODEL:
                    fallback_labeled += 1
            except Exception as e:
                log(f"write_error asset_id={asset_id} error={e}")

    with_db(_write)
    return labeled, fallback_labeled


def _looks_like_uuid(value: str) -> bool:
    return len(value) == 36 and value.count("-") == 4


def write_errors(run_id: str, now: str, errors: list[dict[str, str]]) -> None:
    rows: list[tuple[str, str, str, str, str, str | None, str, str]] = []
    for err in errors:
        asset_id = err.get("id") if isinstance(err, dict) else None
        if not asset_id or not _looks_like_uuid(asset_id):
            continue
        err_model = str(err.get("model") or MODEL)
        rows.append(
            (
                str(uuid.uuid4()),
                asset_id,
                "gemini",
                err_model,
                err.get("error", ""),
                err.get("raw"),
                run_id,
                now,
            )
        )
    if not rows:
        return

    def _write(db: Db) -> None:
        db.executemany(
            """
            insert into asset_ai_errors
              (id, asset_id, provider, model, error, raw, run_id, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            rows,
        )

    with_db(_write)


def main() -> None:
    start_ts = time.time()
    run_id = str(uuid.uuid4())
    now = _now_iso()

    with_db(
        lambda db: db.exec(
            "insert into ai_runs (id, provider, model, created_at) values (?, ?, ?, ?)",
            (run_id, "gemini", MODEL, now),
        )
    )

    log(
        f"start run_id={run_id} batch_size={BATCH} workers={MAX_WORKERS} "
        f"source={SOURCE} image_kind={IMAGE_KIND} req_timeout_s={REQ_TIMEOUT_S} batch_timeout_s={BATCH_TIMEOUT_S} "
        f"recitation_fallback_model={RECITATION_FALLBACK_MODEL or '(disabled)'}"
    )

    batch_num = 0
    consecutive_zero = 0
    cumulative_labeled = 0
    cumulative_fallback_labeled = 0

    while True:
        batch_num += 1
        try:
            rows = fetch_batch()
        except Exception as e:
            log(f"fetch_batch_error batch={batch_num} error={e}")
            time.sleep(5)
            continue

        if not rows:
            log("done: no more candidates")
            break

        batch_start = time.time()
        results = []
        errors = []

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as exe:
            futures = [exe.submit(process_row, r) for r in rows]
            done = set()
            start_wait = time.time()
            try:
                for fut in as_completed(futures, timeout=BATCH_TIMEOUT_S):
                    done.add(fut)
                    asset_id, payload, err, used_model, raw = fut.result()
                    if err:
                        errors.append({"id": asset_id, "error": err, "model": used_model, "raw": raw})
                    else:
                        results.append((asset_id, payload, used_model))
            except Exception as e:
                errors.append({"id": "batch_timeout", "error": str(e)})
            finally:
                pending = [f for f in futures if f not in done]
                for f in pending:
                    f.cancel()
                if pending:
                    errors.append(
                        {
                            "id": "pending_futures",
                            "error": f"cancelled {len(pending)} pending after {int(time.time() - start_wait)}s",
                        }
                    )

        try:
            labeled, fallback_labeled = write_results(run_id, now, results)
        except Exception as e:
            log(f"write_results_error batch={batch_num} error={e}")
            labeled = 0
            fallback_labeled = 0

        try:
            write_errors(run_id, now, errors)
        except Exception as e:
            log(f"write_errors_error batch={batch_num} error={e}")

        cumulative_labeled += labeled
        cumulative_fallback_labeled += fallback_labeled
        attempted = len(rows)
        batch_s = max(0.001, time.time() - batch_start)
        rate = labeled / batch_s
        try:
            remaining = remaining_count()
        except Exception as e:
            log(f"remaining_count_error error={e}")
            remaining = -1
        eta_s = int(remaining / rate) if rate > 0 and remaining >= 0 else -1
        eta_min = eta_s // 60 if eta_s >= 0 else -1

        log(
            f"batch {batch_num}: attempted={attempted} labeled={labeled} fallback_labeled={fallback_labeled} errors={len(errors)} "
            f"batch_s={batch_s:.1f} rate={rate:.2f}/s remaining={remaining} eta~{eta_min}m"
        )

        if labeled == 0:
            consecutive_zero += 1
        else:
            consecutive_zero = 0
        if consecutive_zero >= 3:
            log("stopping: 3 consecutive zero-labeled batches")
            break

    elapsed = time.time() - start_ts
    log(
        f"finished run_id={run_id} elapsed_s={elapsed:.1f} labeled_total={cumulative_labeled} "
        f"fallback_labeled_total={cumulative_fallback_labeled}"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"fatal_error: {e}")
