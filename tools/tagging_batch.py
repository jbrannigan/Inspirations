#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import uuid
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from inspirations.ai import (
    DEFAULT_GEMINI_MODEL,
    DEFAULT_GEMINI_PROMPT,
    _extract_json_object,
    _extract_response_text,
    _flatten_ai_labels,
    _mime_from_path,
    _no_json_error_message,
    _now_iso,
)
from inspirations.db import Db, ensure_schema
from inspirations.storage import download_and_attach_originals
from inspirations.thumbnails import generate_thumbnails

API_ROOT = "https://generativelanguage.googleapis.com/v1beta"
UPLOAD_ROOT = "https://generativelanguage.googleapis.com/upload/v1beta/files"

DB_PATH = Path(os.environ.get("DB_PATH", "data/inspirations.sqlite"))
STORE_DIR = Path(os.environ.get("STORE_DIR", "store"))
MODEL = os.environ.get("MODEL", DEFAULT_GEMINI_MODEL)
SOURCE = os.environ.get("SOURCE", "pinterest")
IMAGE_KIND = os.environ.get("IMAGE_KIND", "thumb")
API_KEY = os.environ.get("GEMINI_API_KEY", "")
MAX_BYTES = int(os.environ.get("BATCH_MAX_BYTES", str(1_500_000_000)))
LOG_PATH = Path(os.environ.get("BATCH_LOG", "/tmp/inspirations_gemini_batch.log"))
OUT_DIR = Path(os.environ.get("BATCH_OUT_DIR", "data/batch_jobs"))


@dataclass
class BatchInput:
    idx: int
    input_path: Path
    map_path: Path
    skipped_path: Path
    count: int
    size_bytes: int


@dataclass
class BatchMeta:
    idx: int
    meta_path: Path
    batch_name: str | None = None
    input_file_id: str | None = None
    output_file_id: str | None = None
    output_path: Path | None = None


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def log(msg: str) -> None:
    line = f"[{_utc_now()}] {msg}"
    print(line, flush=True)
    with LOG_PATH.open("a") as f:
        f.write(line + "\n")


def _request_json(
    url: str,
    *,
    api_key: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout_s: float = 60.0,
) -> tuple[dict[str, Any], urllib.response.addinfourl]:
    hdrs = {
        "x-goog-api-key": api_key,
        "Accept": "application/json",
    }
    if headers:
        hdrs.update(headers)
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        resp = urllib.request.urlopen(req, timeout=timeout_s)
        body = resp.read()
        if body:
            return json.loads(body.decode("utf-8")), resp
        return {}, resp
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="ignore") if hasattr(e, "read") else ""
        raise RuntimeError(f"HTTP {e.code}: {detail}") from e


def _start_resumable_upload(api_key: str, size_bytes: int, mime_type: str, display_name: str) -> str:
    headers = {
        "X-Goog-Upload-Protocol": "resumable",
        "X-Goog-Upload-Command": "start",
        "X-Goog-Upload-Header-Content-Length": str(size_bytes),
        "X-Goog-Upload-Header-Content-Type": mime_type,
    }
    payload_snake = {"file": {"display_name": display_name}}
    payload_camel = {"file": {"displayName": display_name}}
    try:
        _, resp = _request_json(
            UPLOAD_ROOT,
            api_key=api_key,
            method="POST",
            payload=payload_snake,
            headers=headers,
            timeout_s=60,
        )
    except RuntimeError as e:
        if "Unknown name" in str(e) or "Invalid JSON payload" in str(e):
            _, resp = _request_json(
                UPLOAD_ROOT,
                api_key=api_key,
                method="POST",
                payload=payload_camel,
                headers=headers,
                timeout_s=60,
            )
        else:
            raise
    upload_url = resp.headers.get("X-Goog-Upload-URL") or resp.headers.get("x-goog-upload-url")
    if not upload_url:
        raise RuntimeError("Missing X-Goog-Upload-URL header from resumable upload start")
    return upload_url


def _finalize_resumable_upload(api_key: str, upload_url: str, path: Path, size_bytes: int) -> dict[str, Any]:
    headers = {
        "X-Goog-Upload-Offset": "0",
        "X-Goog-Upload-Command": "upload, finalize",
        "Content-Length": str(size_bytes),
        "x-goog-api-key": api_key,
    }
    req = urllib.request.Request(upload_url, data=path.read_bytes(), method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = resp.read().decode("utf-8") if resp.readable() else ""
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="ignore") if hasattr(e, "read") else ""
        raise RuntimeError(f"Upload finalize failed HTTP {e.code}: {detail}") from e


def upload_jsonl(api_key: str, path: Path, display_name: str) -> dict[str, Any]:
    size_bytes = path.stat().st_size
    upload_url = _start_resumable_upload(api_key, size_bytes, "application/jsonl", display_name)
    resp = _finalize_resumable_upload(api_key, upload_url, path, size_bytes)
    if "file" in resp and isinstance(resp["file"], dict):
        return resp["file"]
    if "name" in resp:
        return resp
    raise RuntimeError(f"Unexpected upload response: {resp}")


def create_batch(api_key: str, model: str, file_id: str, display_name: str) -> dict[str, Any]:
    url = f"{API_ROOT}/models/{model}:batchGenerateContent"
    payload_snake = {
        "batch": {
            "display_name": display_name,
            "input_config": {"file_name": file_id},
        }
    }
    payload_camel = {
        "batch": {
            "displayName": display_name,
            "inputConfig": {"fileName": file_id},
        }
    }
    try:
        resp, _ = _request_json(url, api_key=api_key, method="POST", payload=payload_snake, timeout_s=60)
    except RuntimeError as e:
        if "Unknown name" in str(e) or "Invalid JSON payload" in str(e):
            resp, _ = _request_json(url, api_key=api_key, method="POST", payload=payload_camel, timeout_s=60)
        else:
            raise
    return resp


def get_batch(api_key: str, name: str) -> dict[str, Any]:
    url = f"{API_ROOT}/{name}"
    resp, _ = _request_json(url, api_key=api_key, method="GET", timeout_s=60)
    return resp


def get_file(api_key: str, file_id: str) -> dict[str, Any]:
    url = f"{API_ROOT}/{file_id}"
    resp, _ = _request_json(url, api_key=api_key, method="GET", timeout_s=60)
    return resp


def download_file(api_key: str, file_id: str, dest: Path) -> None:
    clean_id = file_id.replace("files/", "")

    def _direct_download() -> None:
        url = f"{API_ROOT}/files/{clean_id}:download?alt=media"
        req = urllib.request.Request(url, headers={"x-goog-api-key": api_key})
        with urllib.request.urlopen(req, timeout=120) as resp:
            dest.write_bytes(resp.read())

    try:
        info = get_file(api_key, f"files/{clean_id}")
        file_obj = info.get("file") if isinstance(info.get("file"), dict) else info
        download_uri = file_obj.get("downloadUri") or file_obj.get("download_uri")
        if not download_uri:
            _direct_download()
            return

        req = urllib.request.Request(download_uri, headers={"x-goog-api-key": api_key})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                dest.write_bytes(resp.read())
                return
        except urllib.error.HTTPError:
            pass

        if "?" not in download_uri:
            fallback = f"{download_uri}?key={api_key}"
        else:
            fallback = download_uri
        req = urllib.request.Request(fallback)
        with urllib.request.urlopen(req, timeout=120) as resp:
            dest.write_bytes(resp.read())
    except RuntimeError as e:
        # Some batch output file ids exceed GetFile name limits; download directly.
        if "GetFileRequest.name" in str(e) or "INVALID_ARGUMENT" in str(e):
            _direct_download()
            return
        raise


def _extract_batch_object(op: dict[str, Any]) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for key in ("response", "metadata", "batch"):
        val = op.get(key)
        if isinstance(val, dict):
            candidates.append(val)
            if "batch" in val and isinstance(val["batch"], dict):
                candidates.append(val["batch"])
    candidates.append(op)
    for obj in candidates:
        if not isinstance(obj, dict):
            continue
        if any(k in obj for k in ("output", "output_config", "outputConfig", "batchStats", "batch_stats")):
            return obj
    return None


def _extract_responses_file(batch: dict[str, Any] | None) -> str | None:
    if not batch:
        return None
    output = batch.get("output") or batch.get("output_config") or batch.get("outputConfig")
    if not isinstance(output, dict):
        return None
    return (
        output.get("responsesFile")
        or output.get("responses_file")
        or output.get("file_name")
        or output.get("fileName")
    )


def _extract_batch_stats(batch: dict[str, Any] | None) -> dict[str, Any] | None:
    if not batch:
        return None
    stats = batch.get("batchStats") or batch.get("batch_stats")
    if isinstance(stats, dict):
        return stats
    return None


def _extract_state(batch: dict[str, Any] | None) -> str | None:
    if not batch:
        return None
    state = batch.get("state")
    if isinstance(state, str):
        return state
    return None


def _infer_key(obj: dict[str, Any]) -> str | None:
    key = obj.get("key")
    if isinstance(key, str):
        return key
    meta = obj.get("metadata")
    if isinstance(meta, dict):
        key = meta.get("key")
        if isinstance(key, str):
            return key
    return None


def _extract_response(obj: dict[str, Any]) -> dict[str, Any] | None:
    if "response" in obj and isinstance(obj["response"], dict):
        return obj["response"]
    if "result" in obj and isinstance(obj["result"], dict):
        return obj["result"]
    if "candidates" in obj:
        return obj
    return None


def fetch_candidates(db: Db, source: str, model: str) -> list[dict[str, Any]]:
    return db.query(
        """
        select a.id, a.title, a.description, a.board, a.stored_path, a.thumb_path
        from assets a
        where a.source = ?
          and a.id not in (select asset_id from asset_ai where provider=?)
        order by a.imported_at asc
        """,
        (source, "gemini"),
    )


def build_batch_inputs(
    rows: Iterable[dict[str, Any]],
    *,
    out_dir: Path,
    image_kind: str,
    max_bytes: int,
    limit: int,
) -> tuple[list[BatchInput], list[dict[str, Any]]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    batches: list[BatchInput] = []
    skipped: list[dict[str, Any]] = []

    batch_idx = 1
    count = 0
    size_bytes = 0
    line_idx = 0

    input_path = out_dir / f"input_{batch_idx:03d}.jsonl"
    map_path = out_dir / f"map_{batch_idx:03d}.jsonl"
    skipped_path = out_dir / f"skipped_{batch_idx:03d}.jsonl"
    input_f = input_path.open("wb")
    map_f = map_path.open("w", encoding="utf-8")
    skipped_f = skipped_path.open("w", encoding="utf-8")

    def _close_current() -> None:
        nonlocal input_f, map_f, skipped_f
        input_f.close()
        map_f.close()
        skipped_f.close()

    def _start_new_batch() -> tuple[Path, Path, Path]:
        nonlocal batch_idx, input_path, map_path, skipped_path, input_f, map_f, skipped_f
        batch_idx += 1
        input_path = out_dir / f"input_{batch_idx:03d}.jsonl"
        map_path = out_dir / f"map_{batch_idx:03d}.jsonl"
        skipped_path = out_dir / f"skipped_{batch_idx:03d}.jsonl"
        input_f = input_path.open("wb")
        map_f = map_path.open("w", encoding="utf-8")
        skipped_f = skipped_path.open("w", encoding="utf-8")
        return input_path, map_path, skipped_path

    for r in rows:
        if limit and count >= limit:
            break
        asset_id = r["id"]
        preferred = r["thumb_path"] if image_kind == "thumb" else r["stored_path"]
        fallback = r["stored_path"] if image_kind == "thumb" else r["thumb_path"]
        path_str = preferred or fallback
        if not path_str:
            skipped.append({"id": asset_id, "error": "No image available"})
            skipped_f.write(json.dumps(skipped[-1]) + "\n")
            continue
        path = Path(path_str)
        mime_type = _mime_from_path(path)
        if not mime_type:
            skipped.append({"id": asset_id, "error": f"Unsupported image type: {path.suffix}"})
            skipped_f.write(json.dumps(skipped[-1]) + "\n")
            continue

        image_b64 = base64.b64encode(path.read_bytes()).decode("ascii")
        request = {
            "contents": [
                {
                    "parts": [
                        {"text": DEFAULT_GEMINI_PROMPT},
                        {"inline_data": {"mime_type": mime_type, "data": image_b64}},
                    ]
                }
            ],
            "generation_config": {"temperature": 0.2, "maxOutputTokens": 2048},
        }
        line_obj = {"key": asset_id, "request": request}
        line = json.dumps(line_obj, separators=(",", ":")).encode("utf-8")

        if size_bytes + len(line) + 1 > max_bytes and count > 0:
            _close_current()
            batches.append(
                BatchInput(
                    idx=batch_idx,
                    input_path=input_path,
                    map_path=map_path,
                    skipped_path=skipped_path,
                    count=count,
                    size_bytes=size_bytes,
                )
            )
            count = 0
            size_bytes = 0
            line_idx = 0
            _start_new_batch()

        input_f.write(line + b"\n")
        map_f.write(json.dumps({"index": line_idx, "asset_id": asset_id, "key": asset_id}) + "\n")
        size_bytes += len(line) + 1
        count += 1
        line_idx += 1

        if count % 50 == 0:
            log(f"prepared {count} requests in batch {batch_idx} (size={size_bytes/1e6:.1f} MB)")

    _close_current()
    if count > 0:
        batches.append(
            BatchInput(
                idx=batch_idx,
                input_path=input_path,
                map_path=map_path,
                skipped_path=skipped_path,
                count=count,
                size_bytes=size_bytes,
            )
        )
    return batches, skipped


def write_meta(meta_path: Path, data: dict[str, Any]) -> None:
    meta_path.write_text(json.dumps(data, indent=2))


def load_meta(meta_path: Path) -> dict[str, Any]:
    return json.loads(meta_path.read_text())


def ingest_output(
    *,
    output_path: Path,
    map_path: Path,
    model: str,
    run_id: str,
    created_at: str,
) -> dict[str, Any]:
    asset_ids: list[str] = []
    with map_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            obj = json.loads(line)
            asset_ids.append(obj.get("asset_id") or obj.get("key") or "")

    errors: list[dict[str, Any]] = []
    error_rows: list[tuple[str, str | None, str, str, str, str | None, str, str]] = []
    labeled = 0

    with Db(DB_PATH) as db:
        ensure_schema(db)
        existing = set(
            r["asset_id"]
            for r in db.query(
                "select asset_id from asset_ai where provider=?",
                ("gemini",),
            )
        )

        with output_path.open("r", encoding="utf-8") as f:
            for idx, line in enumerate(f):
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as e:
                    errors.append({"index": idx, "error": f"JSON decode failed: {e}"})
                    continue

                asset_id = None
                key = _infer_key(obj)
                if key:
                    asset_id = key
                elif idx < len(asset_ids):
                    asset_id = asset_ids[idx]

                if not asset_id:
                    errors.append({"index": idx, "error": "Missing asset_id mapping"})
                    continue
                if asset_id in existing:
                    continue

                if "error" in obj:
                    errors.append({"id": asset_id, "error": obj["error"]})
                    error_rows.append(
                        (
                            str(uuid.uuid4()),
                            asset_id,
                            "gemini",
                            model,
                            str(obj["error"]),
                            json.dumps(obj)[:10000],
                            run_id,
                            created_at,
                        )
                    )
                    continue

                resp = _extract_response(obj)
                if not resp:
                    errors.append({"id": asset_id, "error": "Missing response"})
                    error_rows.append(
                        (
                            str(uuid.uuid4()),
                            asset_id,
                            "gemini",
                            model,
                            "Missing response",
                            json.dumps(obj)[:10000],
                            run_id,
                            created_at,
                        )
                    )
                    continue

                raw_text = _extract_response_text(resp)
                payload = _extract_json_object(raw_text)
                if not payload:
                    err_msg = _no_json_error_message(resp)
                    errors.append({"id": asset_id, "error": err_msg})
                    error_rows.append(
                        (
                            str(uuid.uuid4()),
                            asset_id,
                            "gemini",
                            model,
                            err_msg,
                            (raw_text if raw_text else json.dumps(resp))[:10000],
                            run_id,
                            created_at,
                        )
                    )
                    continue

                summary = str(payload.get("summary") or "").strip()
                db.exec(
                    "insert into asset_ai (id, asset_id, provider, model, summary, json, created_at) values (?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(uuid.uuid4()),
                        asset_id,
                        "gemini",
                        model,
                        summary or None,
                        json.dumps(payload),
                        created_at,
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
                        (str(uuid.uuid4()), asset_id, lab, 0.7, "ai", model, run_id, created_at),
                    )
                labeled += 1

        if error_rows:
            db.executemany(
                """
                insert into asset_ai_errors
                  (id, asset_id, provider, model, error, raw, run_id, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                error_rows,
            )

    return {"labeled": labeled, "errors": errors[:25], "error_count": len(errors)}


def submit_batches(
    *,
    api_key: str,
    model: str,
    source: str,
    image_kind: str,
    limit: int,
    max_bytes: int,
    out_dir: Path,
) -> list[BatchMeta]:
    with Db(DB_PATH) as db:
        ensure_schema(db)
        rows = fetch_candidates(db, source, model)
    if not rows:
        log("no candidates to tag")
        return []

    log(f"building batch inputs for {len(rows)} candidates")
    batches, skipped = build_batch_inputs(
        rows,
        out_dir=out_dir,
        image_kind=image_kind,
        max_bytes=max_bytes,
        limit=limit,
    )
    if skipped:
        log(f"skipped {len(skipped)} assets (missing/unsupported images)")

    metas: list[BatchMeta] = []
    for batch in batches:
        display_name = f"inspirations-{source}-{batch.idx:03d}-{int(time.time())}"
        log(f"uploading batch {batch.idx} file {batch.input_path} ({batch.count} requests)")
        file_info = upload_jsonl(api_key, batch.input_path, display_name)
        file_id = file_info.get("name") or file_info.get("file_name") or file_info.get("fileName")
        if not file_id:
            raise RuntimeError(f"Missing file id in upload response: {file_info}")
        log(f"creating batch job for file {file_id}")
        batch_resp = create_batch(api_key, model, file_id, display_name)
        batch_name = batch_resp.get("name") or batch_resp.get("batch") or batch_resp.get("batch_name")
        if not batch_name:
            batch_name = batch_resp.get("response", {}).get("name")
        if not batch_name:
            raise RuntimeError(f"Missing batch name in response: {batch_resp}")

        meta_path = out_dir / f"meta_{batch.idx:03d}.json"
        meta = {
            "idx": batch.idx,
            "batch_name": batch_name,
            "display_name": display_name,
            "input_file": str(batch.input_path),
            "map_file": str(batch.map_path),
            "skipped_file": str(batch.skipped_path),
            "input_file_id": file_id,
            "request_count": batch.count,
            "input_size_bytes": batch.size_bytes,
            "model": model,
            "source": source,
            "image_kind": image_kind,
            "created_at": _now_iso(),
        }
        write_meta(meta_path, meta)
        metas.append(BatchMeta(idx=batch.idx, meta_path=meta_path, batch_name=batch_name, input_file_id=file_id))
        log(f"batch {batch.idx} submitted name={batch_name}")
    return metas


def watch_batch(api_key: str, name: str, poll_s: int = 30, max_wait_s: int = 0) -> dict[str, Any]:
    start = time.time()
    while True:
        op = get_batch(api_key, name)
        done = op.get("done") is True
        batch_obj = _extract_batch_object(op)
        state = _extract_state(batch_obj)
        stats = _extract_batch_stats(batch_obj)
        if stats:
            log(f"status {name}: done={done} state={state} stats={stats}")
        else:
            log(f"status {name}: done={done} state={state}")
        if done or (state in {"SUCCEEDED", "FAILED", "CANCELLED"}):
            return op
        if max_wait_s and (time.time() - start) > max_wait_s:
            return op
        time.sleep(poll_s)


def run(args: argparse.Namespace) -> int:
    api_key = args.api_key or API_KEY
    if not api_key:
        raise SystemExit("GEMINI_API_KEY is required")

    timestamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    out_dir = Path(args.out_dir) / f"batch_{timestamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.repair_missing:
        log("repair_missing enabled: downloading missing originals + generating thumbs")
        with Db(DB_PATH) as db:
            ensure_schema(db)
            download_and_attach_originals(db, STORE_DIR, args.source, limit=0)
            generate_thumbnails(db, STORE_DIR, source=args.source, limit=0)

    log(f"starting batch run model={args.model} source={args.source} image_kind={args.image_kind}")
    meta_list = submit_batches(
        api_key=api_key,
        model=args.model,
        source=args.source,
        image_kind=args.image_kind,
        limit=args.limit,
        max_bytes=args.max_bytes,
        out_dir=out_dir,
    )
    if not meta_list:
        return 0

    for meta in meta_list:
        log(f"watching batch {meta.batch_name}")
        op = watch_batch(api_key, meta.batch_name, poll_s=args.poll, max_wait_s=args.max_wait_s)
        batch_obj = _extract_batch_object(op)
        responses_file = _extract_responses_file(batch_obj)
        meta_data = load_meta(meta.meta_path)
        meta_data["last_status"] = op
        meta_data["state"] = _extract_state(batch_obj)
        if responses_file:
            meta_data["output_file_id"] = responses_file
            output_path = out_dir / f"output_{meta.idx:03d}.jsonl"
            meta_data["output_path"] = str(output_path)
            write_meta(meta.meta_path, meta_data)
            log(f"downloading output file {responses_file}")
            download_file(api_key, responses_file, output_path)
            run_id = str(uuid.uuid4())
            created_at = _now_iso()
            with Db(DB_PATH) as db:
                ensure_schema(db)
                db.exec(
                    "insert into ai_runs (id, provider, model, created_at) values (?, ?, ?, ?)",
                    (run_id, "gemini", args.model, created_at),
                )
            ingest_report = ingest_output(
                output_path=output_path,
                map_path=Path(meta_data["map_file"]),
                model=args.model,
                run_id=run_id,
                created_at=created_at,
            )
            meta_data["ingest_report"] = ingest_report
            write_meta(meta.meta_path, meta_data)
            log(f"ingested batch {meta.idx}: {ingest_report}")
        else:
            write_meta(meta.meta_path, meta_data)
            log(f"batch {meta.idx} finished without responsesFile")

    return 0


def cmd_submit(args: argparse.Namespace) -> int:
    api_key = args.api_key or API_KEY
    if not api_key:
        raise SystemExit("GEMINI_API_KEY is required")
    timestamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    out_dir = Path(args.out_dir) / f"batch_{timestamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.repair_missing:
        log("repair_missing enabled: downloading missing originals + generating thumbs")
        with Db(DB_PATH) as db:
            ensure_schema(db)
            download_and_attach_originals(db, STORE_DIR, args.source, limit=0)
            generate_thumbnails(db, STORE_DIR, source=args.source, limit=0)
    submit_batches(
        api_key=api_key,
        model=args.model,
        source=args.source,
        image_kind=args.image_kind,
        limit=args.limit,
        max_bytes=args.max_bytes,
        out_dir=out_dir,
    )
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    api_key = args.api_key or API_KEY
    if not api_key:
        raise SystemExit("GEMINI_API_KEY is required")
    if not args.name:
        raise SystemExit("--name is required for watch")
    watch_batch(api_key, args.name, poll_s=args.poll, max_wait_s=args.max_wait_s)
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    api_key = args.api_key or API_KEY
    if not api_key:
        raise SystemExit("GEMINI_API_KEY is required")
    if not args.meta:
        raise SystemExit("--meta is required for fetch")
    meta = load_meta(Path(args.meta))
    responses_file = meta.get("output_file_id") or meta.get("responses_file")
    if not responses_file:
        raise SystemExit("meta file missing output_file_id")
    output_path = Path(meta.get("output_path") or (Path(args.meta).parent / "output.jsonl"))
    download_file(api_key, responses_file, output_path)
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    api_key = args.api_key or API_KEY
    if not api_key:
        raise SystemExit("GEMINI_API_KEY is required")
    if not args.meta:
        raise SystemExit("--meta is required for ingest")
    meta_path = Path(args.meta)
    meta = load_meta(meta_path)
    responses_file = meta.get("output_file_id") or meta.get("responses_file")
    if not responses_file and meta.get("batch_name"):
        op = get_batch(api_key, meta["batch_name"])
        batch_obj = _extract_batch_object(op)
        responses_file = _extract_responses_file(batch_obj)
        if responses_file:
            meta["output_file_id"] = responses_file
            write_meta(meta_path, meta)
    if not responses_file:
        raise SystemExit("meta file missing output_file_id")
    output_path = Path(meta.get("output_path") or (meta_path.parent / "output.jsonl"))
    if not output_path.exists():
        download_file(api_key, responses_file, output_path)

    run_id = str(uuid.uuid4())
    created_at = _now_iso()
    with Db(DB_PATH) as db:
        ensure_schema(db)
        db.exec(
            "insert into ai_runs (id, provider, model, created_at) values (?, ?, ?, ?)",
            (run_id, "gemini", meta.get("model") or MODEL, created_at),
        )
    ingest_report = ingest_output(
        output_path=output_path,
        map_path=Path(meta["map_file"]),
        model=meta.get("model") or MODEL,
        run_id=run_id,
        created_at=created_at,
    )
    meta["ingest_report"] = ingest_report
    meta["output_path"] = str(output_path)
    write_meta(meta_path, meta)
    log(f"ingested batch from {meta_path}: {ingest_report}")
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Gemini batch tagging helper")
    p.add_argument("--db", default=str(DB_PATH), help="SQLite DB path")
    p.add_argument("--store", default=str(STORE_DIR), help="Store directory (originals/thumbs)")
    p.add_argument("--source", default=SOURCE)
    p.add_argument("--image-kind", choices=["thumb", "original"], default=IMAGE_KIND)
    p.add_argument("--model", default=MODEL)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--max-bytes", type=int, default=MAX_BYTES)
    p.add_argument("--out-dir", default=str(OUT_DIR))
    p.add_argument("--api-key", default="")
    p.add_argument("--poll", type=int, default=30)
    p.add_argument("--max-wait-s", type=int, default=0)
    p.add_argument(
        "--repair-missing",
        action="store_true",
        help="Attempt to download missing originals and generate thumbs before batching",
    )

    sub = p.add_subparsers(dest="cmd", required=True)

    run_cmd = sub.add_parser("run", help="Submit, watch, download, and ingest")
    run_cmd.set_defaults(func=run)

    submit_cmd = sub.add_parser("submit", help="Build input + submit batch")
    submit_cmd.set_defaults(func=cmd_submit)

    watch_cmd = sub.add_parser("watch", help="Watch a batch by name")
    watch_cmd.add_argument("--name", required=True)
    watch_cmd.set_defaults(func=cmd_watch)

    fetch_cmd = sub.add_parser("fetch", help="Download output for a batch (meta file)")
    fetch_cmd.add_argument("--meta", required=True)
    fetch_cmd.set_defaults(func=cmd_fetch)

    ingest_cmd = sub.add_parser("ingest", help="Ingest output for a batch (meta file)")
    ingest_cmd.add_argument("--meta", required=True)
    ingest_cmd.set_defaults(func=cmd_ingest)

    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.db:
        global DB_PATH
        DB_PATH = Path(args.db)
    if args.store:
        global STORE_DIR
        STORE_DIR = Path(args.store)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
