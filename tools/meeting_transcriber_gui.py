#!/usr/bin/env python3
"""
Meeting Transcriber GUI

A local web UI for repeatable meeting transcription workflows:
- Cloud mode: OpenAI diarization with automatic chunking + merge
- Local mode: WhisperX + pyannote diarization
- Speaker name mapping for recurring participants
- Outputs: merged diarized JSON, speaker transcript, cleaned transcript, SRT, summary

Usage:
  python tools/meeting_transcriber_gui.py --port 8012
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
import secrets
import shutil
import ssl
import subprocess
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

MAX_BODY = 1_500_000
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8012
DEFAULT_CLOUD_MODEL = "gpt-4o-transcribe-diarize"
DEFAULT_SUMMARY_MODEL = "gpt-4o-mini"
DEFAULT_LOCAL_MODEL = "small"
DEFAULT_MAX_CHUNK_SECONDS = 120.0
DEFAULT_OVERLAP_SECONDS = 10.0
JOB_HISTORY_PATH = Path(__file__).resolve().parents[1] / "data" / "meeting_transcriber_jobs.json"
SPEAKER_REFERENCE_ROOT = Path(__file__).resolve().parents[1] / "data" / "speaker_references"
OPENAI_AUDIO_URL = "https://api.openai.com/v1/audio/transcriptions"
OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
MAX_KNOWN_SPEAKER_REFERENCES = 4


HTML_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Meeting Transcriber</title>
  <style>
    :root {
      --bg: #f2efe8;
      --panel: #fffdf8;
      --ink: #222;
      --muted: #5c5a55;
      --line: #d8d2c4;
      --accent: #1f6f5f;
      --accent-2: #1a5b4f;
      --bad: #8b2d2d;
      --ok: #1f6f5f;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Avenir Next", "Segoe UI", sans-serif;
      color: var(--ink);
      background: radial-gradient(circle at 10% 10%, #f9f6ef, var(--bg));
    }
    .wrap {
      max-width: 1060px;
      margin: 24px auto;
      padding: 0 16px 24px;
    }
    h1 {
      margin: 0 0 8px;
      font-size: 28px;
      line-height: 1.2;
      letter-spacing: 0.2px;
    }
    .sub {
      color: var(--muted);
      margin-bottom: 16px;
    }
    .card {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 14px;
      margin-bottom: 12px;
      box-shadow: 0 3px 10px rgba(0,0,0,0.04);
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(12, 1fr);
      gap: 10px;
      align-items: end;
    }
    .field {
      grid-column: span 12;
    }
    .field.half { grid-column: span 6; }
    .field.third { grid-column: span 4; }
    .field.quarter { grid-column: span 3; }
    label {
      display: block;
      margin-bottom: 6px;
      font-size: 13px;
      color: var(--muted);
    }
    input, select, textarea, button {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 10px 11px;
      font-size: 14px;
      font-family: inherit;
      background: #fff;
      color: var(--ink);
    }
    textarea { min-height: 80px; resize: vertical; }
    .row {
      display: flex;
      gap: 8px;
      align-items: center;
    }
    .row input[type="checkbox"] {
      width: auto;
      transform: scale(1.1);
    }
    button {
      cursor: pointer;
      background: var(--accent);
      color: #fff;
      border: 1px solid var(--accent);
      font-weight: 600;
    }
    button:hover { background: var(--accent-2); }
    .muted { color: var(--muted); font-size: 13px; }
    .jobs {
      display: grid;
      gap: 10px;
    }
    .job {
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 10px;
      background: #fff;
    }
    .job h3 {
      margin: 0 0 8px;
      font-size: 14px;
    }
    .status {
      display: inline-block;
      padding: 2px 8px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.3px;
      border: 1px solid transparent;
    }
    .status.running { background: #e7f4f1; color: #145246; border-color: #b7ddd4; }
    .status.succeeded { background: #e9f5ec; color: #1a5f2f; border-color: #bedfca; }
    .status.failed { background: #f8e9e9; color: #7a2424; border-color: #e2bcbc; }
    .status.interrupted { background: #f3edf9; color: #5b3a78; border-color: #d7c3ea; }
    .status.queued { background: #f4f0e7; color: #6f5f24; border-color: #dfd3b9; }
    pre {
      white-space: pre-wrap;
      word-break: break-word;
      margin: 8px 0 0;
      background: #f8f6f0;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
      max-height: 260px;
      overflow: auto;
      font-size: 12px;
      line-height: 1.4;
    }
    ul {
      margin: 8px 0 0;
      padding-left: 16px;
    }
    @media (max-width: 820px) {
      .field.half, .field.third, .field.quarter { grid-column: span 12; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Meeting Transcriber</h1>
    <div class="sub">Generic recurring-participant workflow for meetings. Cloud mode supports OpenAI diarization. Local mode supports WhisperX plus pyannote diarization.</div>

    <div class="card">
      <div class="grid">
        <div class="field">
          <label for="source_path">Source file path (audio/video)</label>
          <input id="source_path" type="text" placeholder="/absolute/path/to/meeting.m4a" />
        </div>
        <div class="field third">
          <label for="mode">Mode</label>
          <select id="mode">
            <option value="cloud" selected>Cloud (OpenAI diarization)</option>
            <option value="local">Local (WhisperX + pyannote diarization)</option>
          </select>
        </div>
        <div class="field third">
          <label for="known_participants">Likely participants (comma-separated)</label>
          <input id="known_participants" type="text" placeholder="Jim Brannigan, Leslie Brannigan" />
        </div>
        <div class="field third">
          <label for="expected_speakers">Expected speakers (optional)</label>
          <input id="expected_speakers" type="number" min="1" step="1" placeholder="3" />
        </div>

        <div class="field quarter">
          <label for="cloud_model">Cloud model</label>
          <input id="cloud_model" type="text" value="gpt-4o-transcribe-diarize" />
        </div>
        <div class="field quarter">
          <label for="summary_model">Summary model</label>
          <input id="summary_model" type="text" value="gpt-4o-mini" />
        </div>
        <div class="field quarter">
          <label for="local_model">Local WhisperX model</label>
          <input id="local_model" type="text" value="small" />
        </div>
        <div class="field quarter">
          <label for="max_chunk_seconds">Max chunk seconds (120 recommended)</label>
          <input id="max_chunk_seconds" type="number" min="60" step="10" value="120" />
        </div>
        <div class="field quarter">
          <label for="chunk_overlap_seconds">Chunk overlap seconds</label>
          <input id="chunk_overlap_seconds" type="number" min="0" max="30" step="1" value="10" />
        </div>

        <div class="field half">
          <div class="row">
            <input id="generate_summary" type="checkbox" checked />
            <label for="generate_summary" style="margin:0;">Generate summary</label>
          </div>
          <div class="row" style="margin-top:6px;">
            <input id="apply_speaker_names" type="checkbox" />
            <label for="apply_speaker_names" style="margin:0;">Apply participant names (heuristic)</label>
          </div>
          <div class="row" style="margin-top:6px;">
            <input id="compact_timecodes" type="checkbox" checked />
            <label for="compact_timecodes" style="margin:0;">Compact timecodes (speaker changes only)</label>
          </div>
          <div class="row" style="margin-top:6px;">
            <input id="open_folder_hint" type="checkbox" checked disabled />
            <label for="open_folder_hint" style="margin:0;">Outputs saved in per-run subfolder next to source file</label>
          </div>
        </div>

        <div class="field half">
          <button id="start_btn">Start Transcription Job</button>
          <div class="muted" style="margin-top:8px;">Cloud mode uses Keychain service <code>openai_api_key</code> and auto-matches clips under <code>data/speaker_references/</code> to names in Known participants. Local mode uses <code>huggingface_api_token</code> and downloads models on first run.</div>
        </div>
      </div>
    </div>

    <div class="card">
      <h2 style="margin:0 0 8px;font-size:18px;">Jobs</h2>
      <div class="jobs" id="jobs"></div>
    </div>
  </div>

  <script>
    const jobsEl = document.getElementById('jobs');
    const startBtn = document.getElementById('start_btn');
    let timer = null;

    function val(id) { return document.getElementById(id).value; }
    function checked(id) { return document.getElementById(id).checked; }

    async function api(path, opts = {}) {
      const res = await fetch(path, {
        headers: { 'Content-Type': 'application/json' },
        ...opts,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const msg = data && data.error ? data.error : `HTTP ${res.status}`;
        throw new Error(msg);
      }
      return data;
    }

    function escapeHtml(s) {
      return String(s || '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#039;');
    }

    function formatLocalDateTime(value) {
      if (!value) return '';
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return String(value);
      return date.toLocaleString([], {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
      });
    }

    function renderJob(job) {
      const files = job.result_files || [];
      const logs = (job.logs || []).join('\\n');
      const cls = ['queued', 'running', 'succeeded', 'failed', 'interrupted'].includes(job.status) ? job.status : 'queued';
      const fileHtml = files.length
        ? `<ul>${files.map(f => `<li><code>${escapeHtml(f)}</code></li>`).join('')}</ul>`
        : '<div class="muted">No output files yet.</div>';

      return `
        <div class="job">
          <h3>
            <code>${escapeHtml(job.id)}</code>
            <span class="status ${cls}">${escapeHtml(job.status)}</span>
          </h3>
          <div><strong>Source:</strong> <code>${escapeHtml(job.config?.source_path || '')}</code></div>
          <div><strong>Progress:</strong> ${escapeHtml(job.progress || '')}</div>
          <div><strong>Created:</strong> ${escapeHtml(formatLocalDateTime(job.created_at))}</div>
          <div><strong>Updated:</strong> ${escapeHtml(formatLocalDateTime(job.updated_at))}</div>
          ${job.output_dir ? `<div><strong>Output dir:</strong> <code>${escapeHtml(job.output_dir)}</code></div>` : ''}
          ${job.error ? `<div style="color:#8b2d2d;"><strong>Error:</strong> ${escapeHtml(job.error)}</div>` : ''}
          <div style="margin-top:8px;"><strong>Result files</strong>${fileHtml}</div>
          <pre>${escapeHtml(logs)}</pre>
        </div>
      `;
    }

    async function refreshJobs() {
      try {
        const data = await api('/api/jobs');
        const jobs = data.jobs || [];
        jobsEl.innerHTML = jobs.length
          ? jobs.map(renderJob).join('')
          : '<div class="muted">No jobs yet.</div>';
      } catch (err) {
        jobsEl.innerHTML = `<div style="color:#8b2d2d;">${escapeHtml(err.message)}</div>`;
      }
    }

    async function createJob() {
      const payload = {
        source_path: val('source_path').trim(),
        mode: val('mode'),
        known_participants: val('known_participants').trim(),
        expected_speakers: val('expected_speakers').trim(),
        cloud_model: val('cloud_model').trim(),
        summary_model: val('summary_model').trim(),
        local_model: val('local_model').trim(),
        max_chunk_seconds: val('max_chunk_seconds').trim(),
        chunk_overlap_seconds: val('chunk_overlap_seconds').trim(),
        generate_summary: checked('generate_summary'),
        apply_speaker_names: checked('apply_speaker_names'),
        compact_timecodes: checked('compact_timecodes'),
      };
      if (!payload.source_path) {
        throw new Error('Source file path is required.');
      }
      await api('/api/jobs', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
    }

    startBtn.addEventListener('click', async () => {
      startBtn.disabled = true;
      try {
        await createJob();
        await refreshJobs();
      } catch (err) {
        alert(err.message || String(err));
      } finally {
        startBtn.disabled = false;
      }
    });

    timer = setInterval(refreshJobs, 2000);
    refreshJobs();
  </script>
</body>
</html>
"""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ts_hhmmss(seconds: float) -> str:
    total = int(max(0, round(seconds)))
    hh = total // 3600
    mm = (total % 3600) // 60
    ss = total % 60
    return f"{hh:02d}:{mm:02d}:{ss:02d}"


def _ts_srt(seconds: float) -> str:
    ms = int(max(0, round(seconds * 1000)))
    hh = ms // 3_600_000
    ms %= 3_600_000
    mm = ms // 60_000
    ms %= 60_000
    ss = ms // 1000
    ms %= 1000
    return f"{hh:02d}:{mm:02d}:{ss:02d},{ms:03d}"


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


def _norm_text_for_match(text: str) -> str:
    t = _clean_text(text).lower()
    t = re.sub(r"[^a-z0-9 ]+", "", t)
    return t


def _text_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm_text_for_match(a), _norm_text_for_match(b)).ratio()


def _slug_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(text or "").lower())


def _speaker_aliases(name: str) -> list[str]:
    clean = _clean_text(name)
    if not clean:
        return []
    aliases: list[str] = []
    seen: set[str] = set()
    parts = [part for part in re.split(r"\s+", clean) if part]
    for candidate in [clean, "".join(parts), *parts]:
        slug = _slug_text(candidate)
        if not slug or slug in seen:
            continue
        seen.add(slug)
        aliases.append(slug)
    return aliases


def _is_generic_speaker_label(label: str) -> bool:
    text = _clean_text(label)
    if not text or text == "?":
        return True
    return bool(
        re.fullmatch(r"speaker(?:[_ ]?\d+)?", text, flags=re.IGNORECASE)
        or re.fullmatch(r"speaker_\d+", text, flags=re.IGNORECASE)
    )


def _parse_participants(raw: str) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for chunk in re.split(r"[,;\n]+", raw or ""):
        name = chunk.strip()
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
    return names


def _safe_int(raw: Any, default: int | None = None) -> int | None:
    try:
        if raw is None or str(raw).strip() == "":
            return default
        return int(str(raw).strip())
    except Exception:
        return default


def _safe_float(raw: Any, default: float) -> float:
    try:
        if raw is None or str(raw).strip() == "":
            return default
        return float(str(raw).strip())
    except Exception:
        return default


def _json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0") or "0")
    if length > MAX_BODY:
        raise ValueError("request body too large")
    raw = handler.rfile.read(length) if length else b"{}"
    try:
        data = json.loads(raw.decode("utf-8") or "{}")
    except Exception as exc:
        raise ValueError(f"invalid JSON body: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("JSON body must be an object")
    return data


def _send_json(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    if handler.command != "HEAD":
        handler.wfile.write(data)


def _get_keychain_value(service: str) -> str:
    try:
        return subprocess.check_output(
            ["security", "find-generic-password", "-s", service, "-w"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return ""


def _get_openai_api_key() -> str:
    env_val = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if env_val:
        return env_val
    return _get_keychain_value("openai_api_key")


def _get_huggingface_api_token() -> str:
    for env_name in ("HF_TOKEN", "HUGGINGFACE_TOKEN"):
        env_val = (os.environ.get(env_name) or "").strip()
        if env_val:
            return env_val
    return _get_keychain_value("huggingface_api_token")


def _run_subprocess(args: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )


def _speaker_reference_audio_files() -> list[Path]:
    if not SPEAKER_REFERENCE_ROOT.exists():
        return []
    exts = {".wav", ".mp3", ".m4a", ".mp4", ".mpeg", ".mpga", ".webm", ".ogg", ".flac"}
    files = [path for path in SPEAKER_REFERENCE_ROOT.rglob("*") if path.is_file() and path.suffix.lower() in exts]
    files.sort()
    return files


def _resolve_known_speaker_references(participants: list[str]) -> list[tuple[str, Path]]:
    if not participants:
        return []

    reference_files = _speaker_reference_audio_files()
    if not reference_files:
        return []

    matches: list[tuple[str, Path]] = []
    used_paths: set[Path] = set()
    for participant in participants:
        aliases = set(_speaker_aliases(participant))
        if not aliases:
            continue

        scored: list[tuple[int, str, Path]] = []
        for path in reference_files:
            parent_slug = _slug_text(path.parent.name)
            stem_slug = _slug_text(path.stem)
            if parent_slug in aliases:
                scored.append((0, path.name.lower(), path))
                continue
            if stem_slug in aliases:
                scored.append((1, path.name.lower(), path))
                continue
            if any(alias and alias in stem_slug for alias in aliases):
                scored.append((2, path.name.lower(), path))
                continue
            if any(alias and alias in parent_slug for alias in aliases):
                scored.append((3, path.name.lower(), path))

        if not scored:
            continue
        scored.sort(key=lambda item: (item[0], item[1]))
        chosen = scored[0][2]
        if chosen in used_paths:
            continue
        used_paths.add(chosen)
        matches.append((participant, chosen))
        if len(matches) >= MAX_KNOWN_SPEAKER_REFERENCES:
            break

    return matches


def _ffprobe_duration(path: Path) -> float:
    cp = _run_subprocess(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ]
    )
    if cp.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {cp.stderr.strip() or cp.stdout.strip()}")
    try:
        return float(cp.stdout.strip())
    except Exception as exc:
        raise RuntimeError("ffprobe returned invalid duration") from exc


def _ffmpeg_compress_for_cloud(src: Path, dst: Path) -> None:
    cp = _run_subprocess(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(src),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "aac",
            "-b:a",
            "48k",
            str(dst),
        ]
    )
    if cp.returncode != 0:
        raise RuntimeError(f"ffmpeg compression failed: {cp.stderr.strip() or cp.stdout.strip()}")


def _ffmpeg_slice(src: Path, dst: Path, *, start: float, duration: float) -> None:
    cp = _run_subprocess(
        [
            "ffmpeg",
            "-y",
            "-ss",
            f"{start:.3f}",
            "-t",
            f"{duration:.3f}",
            "-i",
            str(src),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "aac",
            "-b:a",
            "48k",
            str(dst),
        ]
    )
    if cp.returncode != 0:
        raise RuntimeError(f"ffmpeg slice failed: {cp.stderr.strip() or cp.stdout.strip()}")


def _plan_chunks(duration_sec: float, max_chunk_sec: float, overlap_sec: float) -> list[tuple[float, float]]:
    if duration_sec <= 0:
        raise ValueError("duration must be > 0")
    if max_chunk_sec <= 0:
        raise ValueError("max_chunk_sec must be > 0")
    if overlap_sec < 0:
        raise ValueError("overlap_sec must be >= 0")
    if overlap_sec >= max_chunk_sec:
        raise ValueError("overlap_sec must be smaller than max_chunk_sec")

    chunks: list[tuple[float, float]] = []
    step = max_chunk_sec - overlap_sec
    start = 0.0
    while start < duration_sec:
        length = min(max_chunk_sec, max(0.0, duration_sec - start))
        if length < 0.5:
            break
        chunks.append((start, length))
        if start + length >= duration_sec:
            break
        start += step
    return chunks


def _build_multipart_form(fields: list[tuple[str, str]], file_field: str, file_path: Path) -> tuple[bytes, str]:
    boundary = "----meetingtranscriber" + uuid.uuid4().hex
    body = bytearray()

    for name, value in fields:
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        body.extend(str(value).encode("utf-8"))
        body.extend(b"\r\n")

    mime = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    data = file_path.read_bytes()
    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(
        f'Content-Disposition: form-data; name="{file_field}"; filename="{file_path.name}"\r\n'.encode("utf-8")
    )
    body.extend(f"Content-Type: {mime}\r\n\r\n".encode("utf-8"))
    body.extend(data)
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode("utf-8"))

    content_type = f"multipart/form-data; boundary={boundary}"
    return bytes(body), content_type


def _audio_file_data_url(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{payload}"


def _prepare_openai_reference_clip(src: Path, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = _slug_text(src.stem) or "speaker-reference"
    dst = out_dir / f"{slug}.m4a"
    cp = _run_subprocess(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(src),
            "-t",
            "10",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "aac",
            "-b:a",
            "24k",
            str(dst),
        ]
    )
    if cp.returncode != 0:
        raise RuntimeError(f"reference clip preparation failed for {src.name}: {cp.stderr.strip() or cp.stdout.strip()}")
    if not dst.exists():
        raise RuntimeError(f"reference clip preparation did not produce output for {src.name}")
    if dst.stat().st_size > 700 * 1024:
        cp = _run_subprocess(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(src),
                "-t",
                "8",
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "aac",
                "-b:a",
                "16k",
                str(dst),
            ]
        )
        if cp.returncode != 0:
            raise RuntimeError(f"reference clip recompression failed for {src.name}: {cp.stderr.strip() or cp.stdout.strip()}")
    if dst.stat().st_size > 700 * 1024:
        raise RuntimeError(f"reference clip remains too large after compression: {src.name}")
    return dst


def _openai_transcribe_diarized(
    file_path: Path,
    *,
    api_key: str,
    model: str,
    known_speaker_refs: list[tuple[str, Path]] | None = None,
) -> dict[str, Any]:
    fields: list[tuple[str, str]] = [
        ("model", model),
        ("response_format", "diarized_json"),
        ("chunking_strategy", '{"type":"server_vad"}'),
    ]
    if known_speaker_refs:
        fields.append(("known_speaker_names", json.dumps([speaker_name for speaker_name, _ in known_speaker_refs])))
        fields.append(
            (
                "known_speaker_references",
                json.dumps([_audio_file_data_url(speaker_path) for _speaker_name, speaker_path in known_speaker_refs]),
            )
        )
    body, content_type = _build_multipart_form(fields, "file", file_path)

    req = Request(OPENAI_AUDIO_URL, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Content-Type", content_type)

    with urlopen(req, timeout=60 * 15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _openai_summary_markdown(
    transcript_text: str,
    *,
    api_key: str,
    summary_model: str,
) -> str:
    system = (
        "You are a meeting analyst. Be factual and concise. "
        "Do not invent details not present in transcript."
    )
    user = (
        "Summarize this meeting transcript in markdown with sections:\n"
        "## Overview\n"
        "## Decisions\n"
        "## Action Items\n"
        "## Open Questions\n"
        "## Next Steps\n\n"
        "For action items, use bullets exactly as:\n"
        "- [ ] Task — Owner — When\n"
        "Use TBD where unknown.\n\n"
        f"Transcript:\n\n{transcript_text}"
    )
    payload = {
        "model": summary_model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    raw = json.dumps(payload).encode("utf-8")
    req = Request(OPENAI_CHAT_URL, data=raw, method="POST")
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Content-Type", "application/json")
    with urlopen(req, timeout=60 * 8) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return str(data["choices"][0]["message"]["content"]).strip()


def _merge_cloud_chunks(chunks: list[dict[str, Any]], overlap_sec: float) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    next_global_idx = 1

    for chunk_idx, chunk in enumerate(chunks):
        offset = float(chunk["offset"])
        raw_segments = chunk.get("segments") or []

        local_segments: list[dict[str, Any]] = []
        for seg in raw_segments:
            text = _clean_text(seg.get("text", ""))
            if not text:
                continue
            local_segments.append(
                {
                    "start": offset + float(seg.get("start", 0.0)),
                    "end": offset + float(seg.get("end", 0.0)),
                    "text": text,
                    "local_speaker": str(seg.get("speaker") or "?"),
                }
            )

        local_segments.sort(key=lambda x: x["start"])
        if not local_segments:
            continue

        local_to_global: dict[str, str] = {}
        if chunk_idx == 0:
            for seg in local_segments:
                speaker = seg["local_speaker"]
                if speaker not in local_to_global:
                    if _is_generic_speaker_label(speaker):
                        local_to_global[speaker] = f"Speaker {next_global_idx}"
                        next_global_idx += 1
                    else:
                        local_to_global[speaker] = speaker
        else:
            overlap_start = offset
            overlap_end = offset + overlap_sec + 6.0
            prev_candidates = [
                p
                for p in merged
                if p["end"] > overlap_start - 8.0 and p["start"] < overlap_end + 8.0
            ]
            current_candidates = [s for s in local_segments if s["start"] < overlap_end]

            votes: dict[str, dict[str, int]] = {}
            for cur in current_candidates:
                if not _is_generic_speaker_label(cur["local_speaker"]):
                    local_to_global[cur["local_speaker"]] = cur["local_speaker"]
                    continue
                for prev in prev_candidates:
                    time_close = abs(cur["start"] - prev["start"]) <= 2.5 or not (
                        cur["end"] < prev["start"] or cur["start"] > prev["end"]
                    )
                    if not time_close:
                        continue
                    ratio = _text_similarity(cur["text"], prev["text"])
                    if ratio < 0.62:
                        continue
                    sp = cur["local_speaker"]
                    votes.setdefault(sp, {}).setdefault(prev["speaker"], 0)
                    votes[sp][prev["speaker"]] += 1

            for local_sp, bucket in votes.items():
                chosen = max(bucket.items(), key=lambda kv: kv[1])[0]
                local_to_global[local_sp] = chosen

            for seg in local_segments:
                sp = seg["local_speaker"]
                if sp not in local_to_global:
                    if _is_generic_speaker_label(sp):
                        local_to_global[sp] = f"Speaker {next_global_idx}"
                        next_global_idx += 1
                    else:
                        local_to_global[sp] = sp

        for seg in local_segments:
            abs_seg = {
                "start": float(seg["start"]),
                "end": float(seg["end"]),
                "text": seg["text"],
                "speaker": local_to_global[seg["local_speaker"]],
            }

            # Deduplicate overlap echoes.
            duplicate = False
            for prev in merged[-60:]:
                if abs(abs_seg["start"] - prev["start"]) <= 3.0 and _text_similarity(abs_seg["text"], prev["text"]) >= 0.90:
                    duplicate = True
                    break
            if duplicate:
                continue
            if chunk_idx > 0 and abs_seg["end"] <= offset + 4.0:
                continue
            merged.append(abs_seg)

    merged.sort(key=lambda x: x["start"])

    # Coalesce tiny same-speaker neighboring segments.
    compacted: list[dict[str, Any]] = []
    for seg in merged:
        if not compacted:
            compacted.append(dict(seg))
            continue
        last = compacted[-1]
        if seg["speaker"] == last["speaker"] and seg["start"] - last["end"] <= 1.2:
            last["end"] = max(last["end"], seg["end"])
            last["text"] = _clean_text(last["text"] + " " + seg["text"])
        else:
            compacted.append(dict(seg))

    return compacted


def _apply_speaker_name_mapping(
    segments: list[dict[str, Any]],
    known_participants: list[str],
    expected_speakers: int | None,
    apply_speaker_names: bool,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    if not segments:
        return [], {}

    by_duration: dict[str, float] = {}
    for seg in segments:
        by_duration.setdefault(str(seg["speaker"]), 0.0)
        by_duration[str(seg["speaker"])] += max(0.0, float(seg["end"]) - float(seg["start"]))

    speakers_sorted = [sp for sp, _dur in sorted(by_duration.items(), key=lambda kv: kv[1], reverse=True)]
    speaker_map: dict[str, str] = {}

    for speaker in speakers_sorted:
        if not _is_generic_speaker_label(speaker):
            speaker_map[speaker] = speaker

    if apply_speaker_names:
        available_names = [name for name in known_participants if name not in set(speaker_map.values())]
        generic_speakers = [speaker for speaker in speakers_sorted if speaker not in speaker_map]
        for idx, name in enumerate(available_names):
            if idx >= len(generic_speakers):
                break
            speaker_map[generic_speakers[idx]] = name

    # Ensure all remaining speakers get a generic stable label.
    generic_idx = 1
    used_names = set(speaker_map.values())
    for sp in speakers_sorted:
        if sp in speaker_map:
            continue
        while True:
            candidate = f"Speaker {generic_idx}"
            generic_idx += 1
            if candidate not in used_names:
                speaker_map[sp] = candidate
                used_names.add(candidate)
                break

    mapped: list[dict[str, Any]] = []
    for seg in segments:
        original = str(seg["speaker"])
        mapped.append(
            {
                "start": float(seg["start"]),
                "end": float(seg["end"]),
                "text": _clean_text(seg["text"]),
                "speaker": speaker_map.get(original, original),
                "original_speaker": original,
            }
        )

    # Optional reduce-to-N speakers pass for over-segmentation.
    if expected_speakers and expected_speakers > 0:
        current_speakers = sorted({seg["speaker"] for seg in mapped})
        if len(current_speakers) > expected_speakers:
            # collapse by speaking time into top-N labels
            dur: dict[str, float] = {}
            for seg in mapped:
                dur.setdefault(seg["speaker"], 0.0)
                dur[seg["speaker"]] += max(0.0, seg["end"] - seg["start"])
            top = [sp for sp, _ in sorted(dur.items(), key=lambda kv: kv[1], reverse=True)[:expected_speakers]]
            if top:
                top_set = set(top)
                for idx, seg in enumerate(mapped):
                    if seg["speaker"] in top_set:
                        continue
                    # nearest top speaker in context
                    prev_top = None
                    for j in range(idx - 1, -1, -1):
                        if mapped[j]["speaker"] in top_set:
                            prev_top = mapped[j]["speaker"]
                            break
                    next_top = None
                    for j in range(idx + 1, len(mapped)):
                        if mapped[j]["speaker"] in top_set:
                            next_top = mapped[j]["speaker"]
                            break
                    if prev_top and next_top and prev_top == next_top:
                        seg["speaker"] = prev_top
                    elif prev_top:
                        seg["speaker"] = prev_top
                    elif next_top:
                        seg["speaker"] = next_top
                    else:
                        seg["speaker"] = top[0]

    final_duration: dict[str, float] = {}
    for seg in mapped:
        final_duration.setdefault(str(seg["speaker"]), 0.0)
        final_duration[str(seg["speaker"])] += max(0.0, float(seg["end"]) - float(seg["start"]))

    final_speakers = [sp for sp, _dur in sorted(final_duration.items(), key=lambda kv: kv[1], reverse=True)]
    if not apply_speaker_names:
        explicit_speakers = [speaker for speaker in final_speakers if not _is_generic_speaker_label(speaker)]
        generic_speakers = [speaker for speaker in final_speakers if _is_generic_speaker_label(speaker)]
        relabel = {speaker: speaker for speaker in explicit_speakers}
        for idx, speaker in enumerate(generic_speakers, start=1):
            relabel[speaker] = f"Speaker {idx}"
        for seg in mapped:
            seg["speaker"] = relabel[str(seg["speaker"])]
        speaker_map = {
            raw_speaker: relabel[label]
            for raw_speaker, label in speaker_map.items()
            if label in relabel
        }
    else:
        used_labels = set(final_speakers)
        speaker_map = {
            raw_speaker: label
            for raw_speaker, label in speaker_map.items()
            if label in used_labels
        }

    return mapped, speaker_map


def _build_cleaned_blocks(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for seg in segments:
        text = _clean_text(seg["text"])
        if not text:
            continue
        if not blocks:
            blocks.append({"speaker": seg["speaker"], "start": seg["start"], "end": seg["end"], "text": text})
            continue
        last = blocks[-1]
        if seg["speaker"] == last["speaker"] and seg["start"] - last["end"] <= 6.0 and len(last["text"]) < 1400:
            last["end"] = max(last["end"], seg["end"])
            last["text"] = _clean_text(last["text"] + " " + text)
        else:
            blocks.append({"speaker": seg["speaker"], "start": seg["start"], "end": seg["end"], "text": text})
    return blocks


def _build_speaker_turns(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    turns: list[dict[str, Any]] = []
    for seg in segments:
        speaker = str(seg["speaker"])
        text = _clean_text(seg["text"])
        if not text:
            continue
        if not turns or speaker != turns[-1]["speaker"]:
            turns.append(
                {
                    "speaker": speaker,
                    "start": float(seg["start"]),
                    "end": float(seg["end"]),
                    "text": text,
                }
            )
            continue
        turns[-1]["end"] = max(float(turns[-1]["end"]), float(seg["end"]))
        turns[-1]["text"] = _clean_text(str(turns[-1]["text"]) + " " + text)
    return turns


def _write_speakers_markdown(
    path: Path,
    stem: str,
    segments: list[dict[str, Any]],
    *,
    compact_timecodes: bool,
) -> None:
    with path.open("w", encoding="utf-8") as fh:
        fh.write(f"# {stem}\n\n")
        fh.write("## Speaker Transcript\n\n")
        if compact_timecodes:
            fh.write("Time code shown only when the speaker changes.\n\n")
            for turn in _build_speaker_turns(segments):
                fh.write(f"### `{_ts_hhmmss(turn['start'])}` {turn['speaker']}\n\n")
                fh.write(turn["text"] + "\n\n")
        else:
            fh.write("Time-stamped transcript grouped by speaker turns.\n\n")
            current_speaker: str | None = None
            for seg in segments:
                speaker = str(seg["speaker"])
                text = _clean_text(seg["text"])
                if not text:
                    continue
                if speaker != current_speaker:
                    fh.write(f"### {speaker}\n\n")
                    current_speaker = speaker
                fh.write(f"- `{_ts_hhmmss(seg['start'])}` {text}\n")
        fh.write("\n")


def _write_cleaned_markdown(
    path: Path,
    stem: str,
    blocks: list[dict[str, Any]],
    *,
    compact_timecodes: bool,
) -> None:
    with path.open("w", encoding="utf-8") as fh:
        fh.write(f"# {stem}\n\n")
        fh.write("## Cleaned Transcript\n\n")
        fh.write("Longer speaker blocks for easier reading.\n\n")
        for block in blocks:
            start = _ts_hhmmss(float(block["start"]))
            speaker = str(block["speaker"])
            text = _clean_text(block["text"])
            if not text:
                continue
            if compact_timecodes:
                fh.write(f"### `{start}` {speaker}\n\n")
            else:
                end = _ts_hhmmss(float(block["end"]))
                fh.write(f"### {start} - {end} {speaker}\n\n")
            fh.write(text + "\n\n")


def _write_outputs(
    run_dir: Path,
    stem: str,
    segments: list[dict[str, Any]],
    speaker_map: dict[str, str],
    *,
    summary_text: str | None,
    compact_timecodes: bool,
) -> list[str]:
    result_files: list[str] = []

    merged_json = run_dir / f"{stem}.diarized.merged.json"
    merged_json.write_text(
        json.dumps({"speaker_map": speaker_map, "segments": segments}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    result_files.append(str(merged_json))

    speakers_txt = run_dir / f"{stem}.speakers.txt"
    with speakers_txt.open("w", encoding="utf-8") as fh:
        if compact_timecodes:
            for turn in _build_speaker_turns(segments):
                fh.write(f"[{_ts_hhmmss(turn['start'])}] {turn['speaker']}: {turn['text']}\n\n")
        else:
            for seg in segments:
                fh.write(f"[{_ts_hhmmss(seg['start'])}] {seg['speaker']}: {seg['text']}\n")
    result_files.append(str(speakers_txt))

    blocks = _build_cleaned_blocks(segments)

    speakers_md = run_dir / f"{stem}.speakers.md"
    _write_speakers_markdown(speakers_md, stem, segments, compact_timecodes=compact_timecodes)
    result_files.append(str(speakers_md))

    cleaned = run_dir / f"{stem}.cleaned-transcript.txt"
    with cleaned.open("w", encoding="utf-8") as fh:
        fh.write(f"{stem}\n")
        fh.write("Speaker-labeled cleaned transcript\n\n")
        for block in blocks:
            if compact_timecodes:
                fh.write(f"[{_ts_hhmmss(block['start'])}] {block['speaker']}\n")
            else:
                fh.write(f"[{_ts_hhmmss(block['start'])} - {_ts_hhmmss(block['end'])}] {block['speaker']}\n")
            fh.write(block["text"] + "\n\n")
    result_files.append(str(cleaned))

    cleaned_md = run_dir / f"{stem}.cleaned-transcript.md"
    _write_cleaned_markdown(cleaned_md, stem, blocks, compact_timecodes=compact_timecodes)
    result_files.append(str(cleaned_md))

    srt = run_dir / f"{stem}.speakers.srt"
    with srt.open("w", encoding="utf-8") as fh:
        idx = 1
        for seg in segments:
            start = float(seg["start"])
            end = float(seg["end"])
            if end <= start:
                end = start + 0.2
            fh.write(f"{idx}\n")
            fh.write(f"{_ts_srt(start)} --> {_ts_srt(end)}\n")
            fh.write(f"{seg['speaker']}: {seg['text']}\n\n")
            idx += 1
    result_files.append(str(srt))

    if summary_text is not None:
        summary_file = run_dir / f"{stem}.meeting-summary.md"
        summary_file.write_text(summary_text.rstrip() + "\n", encoding="utf-8")
        result_files.append(str(summary_file))

    return result_files


def _find_whisperx_python() -> str | None:
    env_override = (os.environ.get("WHISPERX_PYTHON") or "").strip()
    candidates = [
        env_override,
        str(Path.home() / ".venvs" / "whisperx" / "bin" / "python"),
        shutil.which("python3.11"),
    ]
    for cand in candidates:
        if not cand:
            continue
        p = Path(cand)
        if p.exists() and os.access(str(p), os.X_OK):
            return str(p)
    return None


def _local_transcribe_segments(
    src: Path,
    run_dir: Path,
    model: str,
    expected_speakers: int | None,
) -> list[dict[str, Any]]:
    whisperx_python = _find_whisperx_python()
    if not whisperx_python:
        raise RuntimeError("local mode requires WhisperX Python at ~/.venvs/whisperx/bin/python or WHISPERX_PYTHON")

    hf_token = _get_huggingface_api_token()
    if not hf_token:
        raise RuntimeError("local mode requires HF_TOKEN/HUGGINGFACE_TOKEN or keychain service 'huggingface_api_token'")

    local_output_dir = run_dir / "local-whisperx"
    local_output_dir.mkdir(parents=True, exist_ok=True)

    args = [
        whisperx_python,
        "-m",
        "whisperx",
        str(src),
        "--model",
        model,
        "--device",
        "cpu",
        "--compute_type",
        "int8",
        "--diarize",
        "--diarize_model",
        "pyannote/speaker-diarization-community-1",
        "--hf_token",
        hf_token,
        "--output_format",
        "json",
        "--output_dir",
        str(local_output_dir),
        "--batch_size",
        "4",
        "--verbose",
        "False",
    ]
    if expected_speakers and expected_speakers > 0:
        args.extend(["--min_speakers", str(expected_speakers), "--max_speakers", str(expected_speakers)])

    cp = _run_subprocess(args)
    if cp.returncode != 0:
        raise RuntimeError(f"local WhisperX failed: {cp.stderr.strip() or cp.stdout.strip()}")

    json_out = local_output_dir / f"{src.stem}.json"
    if not json_out.exists():
        found = sorted(local_output_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not found:
            raise RuntimeError("local WhisperX completed but no JSON output was found")
        json_out = found[0]

    data = json.loads(json_out.read_text(encoding="utf-8"))
    segments = []
    for seg in data.get("segments") or []:
        text = _clean_text(seg.get("text") or "")
        if not text:
            continue
        segments.append(
            {
                "start": float(seg.get("start", 0.0)),
                "end": float(seg.get("end", 0.0)),
                "text": text,
                "speaker": str(seg.get("speaker") or "Speaker 1"),
            }
        )
    return segments


@dataclass
class Job:
    id: str
    config: dict[str, Any]
    status: str = "queued"
    progress: str = "queued"
    created_at: str = field(default_factory=_utc_now_iso)
    updated_at: str = field(default_factory=_utc_now_iso)
    logs: list[str] = field(default_factory=list)
    output_dir: str | None = None
    result_files: list[str] = field(default_factory=list)
    error: str | None = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "config": self.config,
            "status": self.status,
            "progress": self.progress,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "logs": list(self.logs[-250:]),
            "output_dir": self.output_dir,
            "result_files": list(self.result_files),
            "error": self.error,
        }

    @classmethod
    def from_snapshot(cls, data: dict[str, Any]) -> "Job":
        return cls(
            id=str(data.get("id") or ""),
            config=dict(data.get("config") or {}),
            status=str(data.get("status") or "queued"),
            progress=str(data.get("progress") or "queued"),
            created_at=str(data.get("created_at") or _utc_now_iso()),
            updated_at=str(data.get("updated_at") or _utc_now_iso()),
            logs=list(data.get("logs") or []),
            output_dir=data.get("output_dir"),
            result_files=list(data.get("result_files") or []),
            error=data.get("error"),
        )


class JobManager:
    def __init__(self, history_path: Path | None = None) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._history_path = history_path or JOB_HISTORY_PATH
        self._history_path.parent.mkdir(parents=True, exist_ok=True)
        self._load_history()

    def _load_history(self) -> None:
        if not self._history_path.exists():
            return
        try:
            payload = json.loads(self._history_path.read_text(encoding="utf-8"))
        except Exception:
            return

        raw_jobs = payload.get("jobs") if isinstance(payload, dict) else None
        if not isinstance(raw_jobs, list):
            return

        loaded: dict[str, Job] = {}
        for item in raw_jobs:
            if not isinstance(item, dict):
                continue
            job = Job.from_snapshot(item)
            if not job.id:
                continue
            self._recover_loaded_job(job)
            loaded[job.id] = job

        with self._lock:
            self._jobs = loaded
            self._persist_locked()

    def _recover_loaded_job(self, job: Job) -> None:
        if job.output_dir:
            run_manifest = Path(job.output_dir) / "run_manifest.json"
            if run_manifest.exists():
                try:
                    manifest = json.loads(run_manifest.read_text(encoding="utf-8"))
                    result_files = manifest.get("result_files") or []
                    if isinstance(result_files, list) and result_files:
                        job.result_files = [str(p) for p in result_files]
                    if str(run_manifest) not in job.result_files:
                        job.result_files.append(str(run_manifest))
                    job.status = "succeeded"
                    job.progress = "completed"
                    job.error = None
                    job.updated_at = _utc_now_iso()
                    if not job.logs or job.logs[-1] != "[recovered] Job restored from run_manifest.json":
                        job.logs.append("[recovered] Job restored from run_manifest.json")
                    return
                except Exception:
                    pass

        if job.status in {"queued", "running"}:
            job.status = "interrupted"
            job.progress = "interrupted by server restart"
            job.error = job.error or "Server restarted before job status was finalized."
            job.updated_at = _utc_now_iso()
            if not job.logs or job.logs[-1] != "[recovered] Marked interrupted after restart":
                job.logs.append("[recovered] Marked interrupted after restart")

    def _persist_locked(self) -> None:
        payload = {
            "updated_at": _utc_now_iso(),
            "jobs": [job.snapshot() for job in self._jobs.values()],
        }
        tmp_path = self._history_path.with_suffix(self._history_path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp_path.replace(self._history_path)

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            jobs = [job.snapshot() for job in self._jobs.values()]
        jobs.sort(key=lambda j: (j.get("updated_at") or "", j.get("created_at") or ""), reverse=True)
        return jobs

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return None if job is None else job.snapshot()

    def create_job(self, config: dict[str, Any]) -> dict[str, Any]:
        job_id = secrets.token_hex(6)
        job = Job(id=job_id, config=config)
        with self._lock:
            self._jobs[job_id] = job
            self._persist_locked()
        thread = threading.Thread(target=self._run_job, args=(job_id,), daemon=True)
        thread.start()
        return job.snapshot()

    def _set_status(self, job: Job, *, status: str | None = None, progress: str | None = None, error: str | None = None) -> None:
        with self._lock:
            if status is not None:
                job.status = status
            if progress is not None:
                job.progress = progress
            if error is not None:
                job.error = error
            job.updated_at = _utc_now_iso()
            self._persist_locked()

    def _log(self, job: Job, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{stamp}] {message}"
        with self._lock:
            job.logs.append(line)
            if len(job.logs) > 500:
                job.logs = job.logs[-500:]
            job.updated_at = _utc_now_iso()
            self._persist_locked()

    def _set_result(self, job: Job, *, output_dir: Path, result_files: list[str]) -> None:
        with self._lock:
            job.output_dir = str(output_dir)
            job.result_files = list(result_files)
            job.updated_at = _utc_now_iso()
            self._persist_locked()

    def _run_job(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs[job_id]

        try:
            self._set_status(job, status="running", progress="starting")
            self._execute(job)
            self._set_status(job, status="succeeded", progress="completed")
            self._log(job, "Job completed.")
        except Exception as exc:
            self._set_status(job, status="failed", progress="failed", error=str(exc))
            self._log(job, f"FAILED: {exc}")
            tb = traceback.format_exc(limit=8)
            self._log(job, tb)

    def _execute(self, job: Job) -> None:
        cfg = dict(job.config)
        source_path = Path(str(cfg.get("source_path", "")).strip()).expanduser()
        if not source_path.exists() or not source_path.is_file():
            raise RuntimeError(f"source file not found: {source_path}")

        mode = str(cfg.get("mode") or "cloud").strip().lower()
        if mode not in {"cloud", "local"}:
            raise RuntimeError("mode must be either 'cloud' or 'local'")

        known_participants = _parse_participants(str(cfg.get("known_participants") or ""))
        expected_speakers = _safe_int(cfg.get("expected_speakers"), None)
        generate_summary = bool(cfg.get("generate_summary", True))
        apply_speaker_names = bool(cfg.get("apply_speaker_names", False))
        compact_timecodes = bool(cfg.get("compact_timecodes", cfg.get("suppress_timecodes", True)))
        summary_model = str(cfg.get("summary_model") or DEFAULT_SUMMARY_MODEL).strip() or DEFAULT_SUMMARY_MODEL
        resume_run_dir_value = str(cfg.get("resume_run_dir") or "").strip()

        if resume_run_dir_value:
            run_dir = Path(resume_run_dir_value).expanduser()
        else:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            run_dir = source_path.parent / f"{source_path.stem} - Transcription Results - {stamp}"
        run_dir.mkdir(parents=True, exist_ok=True)
        self._set_result(job, output_dir=run_dir, result_files=[])

        manifest = {
            "created_at": _utc_now_iso(),
            "source_path": str(source_path),
            "mode": mode,
            "known_participants": known_participants,
            "expected_speakers": expected_speakers,
            "apply_speaker_names": apply_speaker_names,
            "compact_timecodes": compact_timecodes,
        }

        segments: list[dict[str, Any]] = []
        speaker_map: dict[str, str] = {}

        if mode == "cloud":
            self._set_status(job, progress="validating cloud prerequisites")
            self._log(job, "Cloud mode selected.")
            api_key = _get_openai_api_key()
            if not api_key:
                raise RuntimeError("OPENAI_API_KEY missing and keychain service 'openai_api_key' not found")

            if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
                raise RuntimeError("ffmpeg and ffprobe are required for cloud mode")

            cloud_model = str(cfg.get("cloud_model") or DEFAULT_CLOUD_MODEL).strip() or DEFAULT_CLOUD_MODEL
            max_chunk_seconds = _safe_float(cfg.get("max_chunk_seconds"), DEFAULT_MAX_CHUNK_SECONDS)
            max_chunk_seconds = min(1800.0, max(60.0, max_chunk_seconds))
            overlap_seconds = min(30.0, max(0.0, _safe_float(cfg.get("chunk_overlap_seconds"), DEFAULT_OVERLAP_SECONDS)))

            self._set_status(job, progress="compressing source for upload")
            upload_file = run_dir / f"{source_path.stem}.cloud-upload.m4a"
            _ffmpeg_compress_for_cloud(source_path, upload_file)
            self._log(job, f"Compressed source: {upload_file.name}")

            speaker_reference_matches = _resolve_known_speaker_references(known_participants)
            prepared_speaker_reference_matches: list[tuple[str, Path]] = []
            if speaker_reference_matches:
                prepared_dir = run_dir / "speaker-references"
                for participant_name, speaker_path in speaker_reference_matches:
                    prepared_path = _prepare_openai_reference_clip(speaker_path, prepared_dir)
                    prepared_speaker_reference_matches.append((participant_name, prepared_path))
                    self._log(job, f"Using speaker reference for {participant_name}: {speaker_path} -> {prepared_path.name}")
            elif known_participants:
                self._log(job, "No matching speaker reference clips found under data/speaker_references.")

            duration = _ffprobe_duration(upload_file)
            self._log(job, f"Duration: {duration:.1f}s")
            chunks = _plan_chunks(duration, max_chunk_seconds, overlap_seconds)
            self._log(job, f"Chunk plan: {len(chunks)} chunk(s)")

            chunk_dir = run_dir / "chunks"
            chunk_dir.mkdir(parents=True, exist_ok=True)
            chunk_results: list[dict[str, Any]] = []

            for idx, (start, length) in enumerate(chunks, start=1):
                self._set_status(job, progress=f"transcribing chunk {idx}/{len(chunks)}")
                chunk_audio = chunk_dir / f"chunk_{idx:02d}_{int(start):04d}s.m4a"
                chunk_json = chunk_dir / f"chunk_{idx:02d}_{int(start):04d}s.json"
                if len(chunks) == 1 and start <= 0.001 and abs(length - duration) < 1.0:
                    chunk_audio = upload_file
                elif not chunk_audio.exists():
                    _ffmpeg_slice(upload_file, chunk_audio, start=start, duration=length)

                if chunk_json.exists():
                    try:
                        response = json.loads(chunk_json.read_text(encoding="utf-8"))
                        self._log(job, f"Reusing existing chunk {idx}: {chunk_json.name}")
                        chunk_results.append({"offset": start, "segments": response.get("segments") or []})
                        continue
                    except json.JSONDecodeError:
                        self._log(job, f"Ignoring unreadable chunk cache for chunk {idx}: {chunk_json.name}")

                self._log(job, f"OpenAI request chunk {idx}: start={start:.1f}s len={length:.1f}s")

                response = None
                last_error: str | None = None
                for attempt in range(1, 5):
                    try:
                        chunk_started = time.time()
                        response = _openai_transcribe_diarized(
                            chunk_audio,
                            api_key=api_key,
                            model=cloud_model,
                            known_speaker_refs=prepared_speaker_reference_matches,
                        )
                        elapsed = time.time() - chunk_started
                        self._log(job, f"Chunk {idx} completed in {elapsed:.1f}s")
                        break
                    except HTTPError as exc:
                        body = exc.read().decode("utf-8", errors="ignore")
                        last_error = f"HTTP {exc.code}: {body[:500]}"
                        if exc.code in {429, 500, 502, 503, 504} and attempt < 4:
                            backoff = 2 ** attempt
                            self._log(job, f"Chunk {idx} retry in {backoff}s ({last_error})")
                            time.sleep(backoff)
                            continue
                        raise RuntimeError(last_error) from exc
                    except (URLError, ssl.SSLError, TimeoutError, ConnectionResetError) as exc:
                        last_error = str(exc)
                        if attempt < 4:
                            backoff = 2 ** attempt
                            self._log(job, f"Chunk {idx} network retry in {backoff}s ({last_error})")
                            time.sleep(backoff)
                            continue
                        raise RuntimeError(f"network error during chunk {idx}: {last_error}") from exc

                if response is None:
                    raise RuntimeError(last_error or f"transcription failed for chunk {idx}")

                chunk_json.write_text(
                    json.dumps(response, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                chunk_results.append({"offset": start, "segments": response.get("segments") or []})

            self._set_status(job, progress="merging diarized chunks")
            merged = _merge_cloud_chunks(chunk_results, overlap_seconds)
            if not merged:
                # fallback if no segments are returned
                text_chunks = []
                for result in chunk_results:
                    text = " ".join(_clean_text(seg.get("text") or "") for seg in result.get("segments") or [])
                    text = _clean_text(text)
                    if text:
                        text_chunks.append(text)
                if text_chunks:
                    merged = [{"start": 0.0, "end": duration, "text": " ".join(text_chunks), "speaker": "Speaker 1"}]
            segments, speaker_map = _apply_speaker_name_mapping(
                merged,
                known_participants,
                expected_speakers,
                apply_speaker_names,
            )
            manifest["cloud_model"] = cloud_model
            manifest["speaker_reference_matches"] = [
                {"name": participant_name, "path": str(speaker_path)}
                for participant_name, speaker_path in speaker_reference_matches
            ]

        else:
            self._set_status(job, progress="running local WhisperX")
            self._log(job, "Local mode selected (WhisperX + pyannote diarization).")
            local_model = str(cfg.get("local_model") or DEFAULT_LOCAL_MODEL).strip() or DEFAULT_LOCAL_MODEL
            local_segments = _local_transcribe_segments(source_path, run_dir, local_model, expected_speakers)
            if not local_segments:
                raise RuntimeError("local transcription produced no segments")
            segments, speaker_map = _apply_speaker_name_mapping(
                local_segments,
                known_participants,
                expected_speakers,
                apply_speaker_names,
            )
            manifest["local_model"] = local_model

        self._set_status(job, progress="writing output files")
        summary_text: str | None = None

        if generate_summary:
            self._log(job, "Generating summary...")
            api_key = _get_openai_api_key()
            if api_key:
                clean_blocks = _build_cleaned_blocks(segments)
                summary_source = "\n\n".join(
                    f"[{_ts_hhmmss(b['start'])}-{_ts_hhmmss(b['end'])}] {b['speaker']}: {b['text']}" for b in clean_blocks
                )
                try:
                    summary_text = _openai_summary_markdown(summary_source, api_key=api_key, summary_model=summary_model)
                except Exception as exc:
                    summary_text = (
                        "# Meeting Summary\n\n"
                        "Summary generation failed.\n\n"
                        f"Error: `{exc}`\n"
                    )
                    self._log(job, f"Summary generation failed: {exc}")
            else:
                summary_text = "# Meeting Summary\n\nSkipped: OpenAI API key unavailable.\n"
                self._log(job, "Summary skipped: OpenAI key unavailable.")

        result_files = _write_outputs(
            run_dir,
            source_path.stem,
            segments,
            speaker_map,
            summary_text=summary_text,
            compact_timecodes=compact_timecodes,
        )

        manifest["speaker_map"] = speaker_map
        manifest_path = run_dir / "run_manifest.json"
        result_files.append(str(manifest_path))
        manifest["result_files"] = result_files
        manifest["finished_at"] = _utc_now_iso()
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        self._set_result(job, output_dir=run_dir, result_files=result_files)
        self._log(job, f"Output directory: {run_dir}")


class MeetingTranscriberHandler(BaseHTTPRequestHandler):
    server_version = "MeetingTranscriber/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/index.html"}:
            return self._send_html(HTML_PAGE)

        if parsed.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return

        if parsed.path == "/api/jobs":
            return _send_json(self, 200, {"jobs": self.server.job_manager.list_jobs()})

        if parsed.path.startswith("/api/jobs/"):
            job_id = parsed.path.split("/")[-1]
            item = self.server.job_manager.get_job(job_id)
            if item is None:
                return _send_json(self, 404, {"error": "job not found"})
            return _send_json(self, 200, item)

        return _send_json(self, 404, {"error": "not found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/jobs":
            return _send_json(self, 404, {"error": "not found"})

        try:
            body = _json_body(self)
        except ValueError as exc:
            return _send_json(self, 400, {"error": str(exc)})

        source_path = str(body.get("source_path") or "").strip()
        if not source_path:
            return _send_json(self, 400, {"error": "source_path is required"})

        config = {
            "source_path": source_path,
            "mode": str(body.get("mode") or "cloud"),
            "known_participants": str(body.get("known_participants") or ""),
            "expected_speakers": body.get("expected_speakers"),
            "cloud_model": str(body.get("cloud_model") or DEFAULT_CLOUD_MODEL),
            "summary_model": str(body.get("summary_model") or DEFAULT_SUMMARY_MODEL),
            "local_model": str(body.get("local_model") or DEFAULT_LOCAL_MODEL),
            "max_chunk_seconds": body.get("max_chunk_seconds"),
            "chunk_overlap_seconds": body.get("chunk_overlap_seconds") or DEFAULT_OVERLAP_SECONDS,
            "generate_summary": bool(body.get("generate_summary", True)),
            "apply_speaker_names": bool(body.get("apply_speaker_names", False)),
            "compact_timecodes": bool(body.get("compact_timecodes", body.get("suppress_timecodes", True))),
            "resume_run_dir": str(body.get("resume_run_dir") or ""),
        }

        item = self.server.job_manager.create_job(config)
        return _send_json(self, 202, item)

    def log_message(self, _format: str, *_args: object) -> None:  # noqa: A003
        return

    def _send_html(self, html: str) -> None:
        data = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Meeting Transcriber local GUI")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"Host bind address (default: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Port (default: {DEFAULT_PORT})")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    job_manager = JobManager()
    server = ThreadingHTTPServer((args.host, args.port), MeetingTranscriberHandler)
    server.job_manager = job_manager

    startup = {
        "status": "serving",
        "url": f"http://{args.host}:{args.port}",
        "cloud_model_default": DEFAULT_CLOUD_MODEL,
        "summary_model_default": DEFAULT_SUMMARY_MODEL,
        "local_model_default": DEFAULT_LOCAL_MODEL,
    }
    print(json.dumps(startup), flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
