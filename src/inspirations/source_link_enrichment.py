from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

from .db import Db
from .security import is_safe_public_url


DEFAULT_TIMEOUT_S = 8.0
DEFAULT_MAX_BYTES = 262_144
DEFAULT_MAX_REDIRECTS = 4
DEFAULT_BROWSER_WAIT_MS = 1500
USER_AGENT = "Inspirations/0.1"
HTML_CONTENT_HINTS = ("text/html", "application/xhtml+xml", "text/plain")
PLATFORM_WRAPPER_HOSTS = {"pinterest.com", "facebook.com"}


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        return None


class _HeadMetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_title = False
        self._title_parts: list[str] = []
        self.meta: dict[str, str] = {}
        self.links: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = {str(key or "").lower(): str(value or "") for key, value in attrs}
        tag = str(tag or "").lower()
        if tag == "title":
            self._in_title = True
            return
        if tag == "meta":
            key = (attrs_map.get("property") or attrs_map.get("name") or "").strip().lower()
            value = (attrs_map.get("content") or "").strip()
            if key and value and key not in self.meta:
                self.meta[key] = value
            return
        if tag == "link":
            rel = (attrs_map.get("rel") or "").strip().lower()
            href = (attrs_map.get("href") or "").strip()
            if rel and href and rel not in self.links:
                self.links[rel] = href

    def handle_endtag(self, tag: str) -> None:
        if str(tag or "").lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(str(data or ""))

    @property
    def title(self) -> str:
        return _normalize_space("".join(self._title_parts))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_space(value: Any) -> str:
    text = str(value or "")
    try:
        text = text.encode("utf-8", errors="replace").decode("utf-8", errors="replace")
    except Exception:
        text = str(value or "")
    return re.sub(r"\s+", " ", text.strip())


def _db_text(value: Any) -> str | None:
    if value is None:
        return None
    return _normalize_space(value)


def _log_progress(message: str) -> None:
    print(f"[{_now_iso()}] {message}", file=sys.stderr, flush=True)


def _log_value(value: Any, *, limit: int = 160) -> str:
    text = _normalize_space(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _extract_domain(url: str) -> str:
    try:
        host = (urlparse(url).hostname or "").strip().lower()
    except Exception:
        host = ""
    if host.startswith("www."):
        host = host[4:]
    return host


def _is_platform_wrapper_host(host: str) -> bool:
    text = _normalize_space(host).lower().strip(".")
    if text.startswith("www."):
        text = text[4:]
    return text in PLATFORM_WRAPPER_HOSTS or any(text.endswith("." + item) for item in PLATFORM_WRAPPER_HOSTS)


def _best_source_url(asset: dict[str, Any]) -> str:
    for key in ("source_url", "source_ref"):
        value = str(asset.get(key) or "").strip()
        if value.startswith("https://") or value.startswith("http://"):
            return value
    return ""


def _promoted_source_url_candidate(asset: dict[str, Any], result: dict[str, Any]) -> str:
    current = str(asset.get("source_url") or "").strip()
    current_host = _extract_domain(current)
    candidate = str(result.get("canonical_url") or "").strip() or str(result.get("final_url") or "").strip()
    candidate_host = _extract_domain(candidate)
    if not candidate or not candidate_host or _is_platform_wrapper_host(candidate_host):
        return ""
    if current and current == candidate:
        return ""
    if current and not _is_platform_wrapper_host(current_host):
        return ""
    return candidate


def _record_field_provenance(
    db: Db,
    *,
    asset_id: str,
    field_name: str,
    field_value: str,
    origin_type: str,
    origin_ref: str,
    actor: str,
    confidence: float,
    created_at: str,
) -> None:
    current_rows = db.query(
        """
        select id, field_value
        from asset_field_provenance
        where asset_id=? and field_name=? and is_current=1
        """,
        (asset_id, field_name),
    )
    for row in current_rows:
        if str(row["field_value"] or "").strip() == field_value:
            return
    if current_rows:
        db.executemany(
            "update asset_field_provenance set superseded_at=?, is_current=0 where id=? and is_current=1",
            [(created_at, str(row["id"])) for row in current_rows],
        )
    db.exec(
        """
        insert into asset_field_provenance
          (id, asset_id, field_name, field_value, origin_type, origin_ref, actor,
           confidence, created_at, superseded_at, is_current)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            asset_id,
            field_name,
            field_value,
            origin_type,
            origin_ref or None,
            actor or None,
            float(confidence),
            created_at,
            None,
            1,
        ),
    )


def _safe_redirect_target(current_url: str, location: str) -> str:
    next_url = urljoin(current_url, str(location or "").strip())
    return next_url


def _decode_bytes(raw: bytes, content_type: str, headers: Any) -> str:
    charset = ""
    if hasattr(headers, "get_content_charset"):
        charset = str(headers.get_content_charset() or "").strip()
    if not charset:
        match = re.search(r"charset=([A-Za-z0-9._-]+)", content_type, re.IGNORECASE)
        if match:
            charset = match.group(1)
    if not charset:
        charset = "utf-8"
    return raw.decode(charset, errors="replace")


def _strip_html_text(html_text: str, *, limit: int = 600) -> str:
    text = re.sub(r"(?is)<script\b.*?</script>", " ", html_text)
    text = re.sub(r"(?is)<style\b.*?</style>", " ", text)
    text = re.sub(r"(?is)<noscript\b.*?</noscript>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = unescape(text)
    text = _normalize_space(text)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def _parse_html_payload(raw_text: str, *, final_url: str) -> dict[str, Any]:
    parser = _HeadMetaParser()
    try:
        parser.feed(raw_text)
    except Exception:
        pass
    canonical_url = parser.links.get("canonical", "")
    if canonical_url:
        canonical_url = urljoin(final_url, canonical_url)
    return {
        "page_title": parser.title,
        "og_title": _normalize_space(parser.meta.get("og:title", "")),
        "meta_description": _normalize_space(parser.meta.get("description", "")),
        "og_description": _normalize_space(parser.meta.get("og:description", "")),
        "og_image_url": urljoin(final_url, parser.meta.get("og:image", "")) if parser.meta.get("og:image") else "",
        "canonical_url": canonical_url,
        "text_excerpt": _strip_html_text(raw_text),
    }


def _parse_text_payload(raw_text: str) -> dict[str, Any]:
    lines = [line.strip() for line in str(raw_text or "").splitlines() if line.strip()]
    page_title = lines[0] if lines else ""
    excerpt = _normalize_space(" ".join(lines[:8]))
    if len(excerpt) > 600:
        excerpt = excerpt[:599].rstrip() + "..."
    return {
        "page_title": page_title,
        "og_title": "",
        "meta_description": "",
        "og_description": "",
        "og_image_url": "",
        "canonical_url": "",
        "text_excerpt": excerpt,
    }


def _fetch_source_page(
    *,
    url: str,
    timeout_s: float,
    max_bytes: int,
    max_redirects: int,
    allow_http: bool,
) -> dict[str, Any]:
    current_url = url
    opener = urllib.request.build_opener(_NoRedirectHandler())

    for redirect_count in range(max_redirects + 1):
        if not is_safe_public_url(current_url, allow_http=allow_http):
            return {
                "input_url": url,
                "final_url": current_url,
                "final_domain": _extract_domain(current_url),
                "canonical_url": "",
                "og_image_url": "",
                "page_title": "",
                "og_title": "",
                "meta_description": "",
                "og_description": "",
                "text_excerpt": "",
                "content_type": "",
                "http_status": None,
                "redirect_count": redirect_count,
                "truncated": 0,
                "fetch_status": "unsafe_url",
                "error": "URL failed public safety checks",
                "content_hash": "",
            }

        req = urllib.request.Request(
            current_url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.2",
            },
        )
        try:
            with opener.open(req, timeout=timeout_s) as resp:
                status = int(resp.getcode() or 200)
                final_url = str(resp.geturl() or current_url)
                content_type = str(resp.headers.get("Content-Type") or "").strip()
                raw = resp.read(max_bytes + 1)
                truncated = 1 if len(raw) > max_bytes else 0
                raw = raw[:max_bytes]
                text = _decode_bytes(raw, content_type, resp.headers)
                parsed = (
                    _parse_html_payload(text, final_url=final_url)
                    if any(hint in content_type.lower() for hint in HTML_CONTENT_HINTS[:-1])
                    else _parse_text_payload(text)
                )
                return {
                    "input_url": url,
                    "final_url": final_url,
                    "final_domain": _extract_domain(final_url),
                    "content_type": content_type,
                    "http_status": status,
                    "redirect_count": redirect_count,
                    "truncated": truncated,
                    "fetch_status": "fetched",
                    "error": "",
                    "content_hash": hashlib.sha256(raw).hexdigest() if raw else "",
                    **parsed,
                }
        except urllib.error.HTTPError as exc:
            code = int(getattr(exc, "code", 0) or 0)
            location = ""
            if exc.headers is not None:
                location = str(exc.headers.get("Location") or "").strip()
            if 300 <= code < 400 and location:
                if redirect_count >= max_redirects:
                    return {
                        "input_url": url,
                        "final_url": current_url,
                        "final_domain": _extract_domain(current_url),
                        "canonical_url": "",
                        "og_image_url": "",
                        "page_title": "",
                        "og_title": "",
                        "meta_description": "",
                        "og_description": "",
                        "text_excerpt": "",
                        "content_type": "",
                        "http_status": code,
                        "redirect_count": redirect_count,
                        "truncated": 0,
                        "fetch_status": "redirect_limit",
                        "error": f"Too many redirects from {url}",
                        "content_hash": "",
                    }
                current_url = _safe_redirect_target(current_url, location)
                continue
            return {
                "input_url": url,
                "final_url": current_url,
                "final_domain": _extract_domain(current_url),
                "canonical_url": "",
                "og_image_url": "",
                "page_title": "",
                "og_title": "",
                "meta_description": "",
                "og_description": "",
                "text_excerpt": "",
                "content_type": str(exc.headers.get("Content-Type") or "").strip() if exc.headers else "",
                "http_status": code or None,
                "redirect_count": redirect_count,
                "truncated": 0,
                "fetch_status": "http_error",
                "error": _normalize_space(exc.reason if hasattr(exc, "reason") else f"HTTP {code}"),
                "content_hash": "",
            }
        except urllib.error.URLError as exc:
            return {
                "input_url": url,
                "final_url": current_url,
                "final_domain": _extract_domain(current_url),
                "canonical_url": "",
                "og_image_url": "",
                "page_title": "",
                "og_title": "",
                "meta_description": "",
                "og_description": "",
                "text_excerpt": "",
                "content_type": "",
                "http_status": None,
                "redirect_count": redirect_count,
                "truncated": 0,
                "fetch_status": "network_error",
                "error": _normalize_space(getattr(exc, "reason", str(exc))),
                "content_hash": "",
            }
        except Exception as exc:
            return {
                "input_url": url,
                "final_url": current_url,
                "final_domain": _extract_domain(current_url),
                "canonical_url": "",
                "og_image_url": "",
                "page_title": "",
                "og_title": "",
                "meta_description": "",
                "og_description": "",
                "text_excerpt": "",
                "content_type": "",
                "http_status": None,
                "redirect_count": redirect_count,
                "truncated": 0,
                "fetch_status": "error",
                "error": _normalize_space(str(exc)),
                "content_hash": "",
            }

    return {
        "input_url": url,
        "final_url": current_url,
        "final_domain": _extract_domain(current_url),
        "canonical_url": "",
        "og_image_url": "",
        "page_title": "",
        "og_title": "",
        "meta_description": "",
        "og_description": "",
        "text_excerpt": "",
        "content_type": "",
        "http_status": None,
        "redirect_count": max_redirects,
        "truncated": 0,
        "fetch_status": "redirect_limit",
        "error": f"Too many redirects from {url}",
        "content_hash": "",
    }


def _playwright_cli_path() -> str:
    codex_home = str(os.environ.get("CODEX_HOME") or "").strip() or os.path.expanduser("~/.codex")
    return os.path.join(codex_home, "skills", "playwright", "scripts", "playwright_cli.sh")


def _run_playwright_cli(
    args: list[str],
    *,
    session_name: str,
    timeout_s: float,
) -> str:
    cli_path = _playwright_cli_path()
    env = dict(os.environ)
    env["PLAYWRIGHT_CLI_SESSION"] = session_name
    process = subprocess.Popen(
        [cli_path, *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=max(10.0, float(timeout_s) + 10.0))
    except subprocess.TimeoutExpired as exc:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        stdout, stderr = process.communicate()
        raise subprocess.TimeoutExpired(exc.cmd, exc.timeout, output=stdout, stderr=stderr)
    if process.returncode != 0:
        raise subprocess.CalledProcessError(process.returncode, process.args, output=stdout, stderr=stderr)
    return str(stdout or "")


def _extract_playwright_result(stdout: str) -> Any:
    text = str(stdout or "")
    match = re.search(r"### Result\s*(.*?)\s*### Ran Playwright code", text, re.DOTALL)
    if not match:
        raise ValueError("Could not parse Playwright CLI result block")
    payload = match.group(1).strip()
    if not payload:
        raise ValueError("Playwright CLI result block was empty")
    return json.loads(payload)


def _close_playwright_session(session_name: str, *, timeout_s: float) -> None:
    try:
        _run_playwright_cli(["close"], session_name=session_name, timeout_s=timeout_s)
    except Exception:
        return


def _fetch_source_page_browser(
    *,
    url: str,
    timeout_s: float,
    session_name: str,
    wait_ms: int = DEFAULT_BROWSER_WAIT_MS,
) -> dict[str, Any]:
    if not is_safe_public_url(url, allow_http=False):
        return {
            "input_url": url,
            "final_url": url,
            "final_domain": _extract_domain(url),
            "canonical_url": "",
            "og_image_url": "",
            "page_title": "",
            "og_title": "",
            "meta_description": "",
            "og_description": "",
            "text_excerpt": "",
            "content_type": "",
            "http_status": None,
            "redirect_count": 0,
            "truncated": 0,
            "fetch_status": "browser_unsafe_url",
            "error": "URL did not pass public-URL safety checks",
            "content_hash": "",
        }
    try:
        _run_playwright_cli(["open", url], session_name=session_name, timeout_s=timeout_s)
        if wait_ms > 0:
            _run_playwright_cli(
                ["run-code", f"await page.waitForTimeout({int(wait_ms)});"],
                session_name=session_name,
                timeout_s=timeout_s,
            )
        stdout = _run_playwright_cli(
            [
                "eval",
                "() => ({"
                "url: location.href,"
                "title: document.title || '',"
                "h1: Array.from(document.querySelectorAll('h1')).map(el => (el.textContent || '').trim()).filter(Boolean).slice(0, 3),"
                "text: (((document.body && document.body.innerText) || '').replace(/\\\\s+/g, ' ').trim().slice(0, 1200))"
                "})",
            ],
            session_name=session_name,
            timeout_s=timeout_s,
        )
        payload = _extract_playwright_result(stdout)
        final_url = _normalize_space(payload.get("url", "")) or url
        page_title = _normalize_space(payload.get("title", ""))
        h1_values = payload.get("h1", [])
        if not isinstance(h1_values, list):
            h1_values = []
        h1_values = [_normalize_space(item) for item in h1_values if _normalize_space(item)]
        text_excerpt = _normalize_space(payload.get("text", ""))
        content_hash = ""
        if text_excerpt:
            content_hash = hashlib.sha256(text_excerpt.encode("utf-8", errors="ignore")).hexdigest()
        return {
            "input_url": url,
            "final_url": final_url,
            "final_domain": _extract_domain(final_url),
            "canonical_url": "",
            "og_image_url": "",
            "page_title": page_title,
            "og_title": h1_values[0] if h1_values else "",
            "meta_description": "",
            "og_description": "",
            "text_excerpt": text_excerpt,
            "content_type": "browser/document",
            "http_status": 200,
            "redirect_count": 0,
            "truncated": 1 if len(text_excerpt) >= 1199 else 0,
            "fetch_status": "fetched",
            "error": "",
            "content_hash": content_hash,
        }
    except subprocess.TimeoutExpired:
        return {
            "input_url": url,
            "final_url": url,
            "final_domain": _extract_domain(url),
            "canonical_url": "",
            "og_image_url": "",
            "page_title": "",
            "og_title": "",
            "meta_description": "",
            "og_description": "",
            "text_excerpt": "",
            "content_type": "",
            "http_status": None,
            "redirect_count": 0,
            "truncated": 0,
            "fetch_status": "browser_timeout",
            "error": "Playwright wrapper fetch timed out",
            "content_hash": "",
        }
    except subprocess.CalledProcessError as exc:
        detail = _normalize_space(exc.stderr or exc.stdout or str(exc))
        return {
            "input_url": url,
            "final_url": url,
            "final_domain": _extract_domain(url),
            "canonical_url": "",
            "og_image_url": "",
            "page_title": "",
            "og_title": "",
            "meta_description": "",
            "og_description": "",
            "text_excerpt": "",
            "content_type": "",
            "http_status": None,
            "redirect_count": 0,
            "truncated": 0,
            "fetch_status": "browser_error",
            "error": detail or "Playwright wrapper fetch failed",
            "content_hash": "",
        }
    except Exception as exc:
        return {
            "input_url": url,
            "final_url": url,
            "final_domain": _extract_domain(url),
            "canonical_url": "",
            "og_image_url": "",
            "page_title": "",
            "og_title": "",
            "meta_description": "",
            "og_description": "",
            "text_excerpt": "",
            "content_type": "",
            "http_status": None,
            "redirect_count": 0,
            "truncated": 0,
            "fetch_status": "browser_error",
            "error": _normalize_space(str(exc)),
            "content_hash": "",
        }


def _latest_track_run_id(db: Db) -> str:
    value = db.query_value(
        """
        select id
        from classification_runs
        where run_type='track_gate'
        order by created_at desc
        limit 1
        """
    )
    return str(value or "").strip()


def _csv_values(value: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in str(value or "").split(","):
        item = raw.strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def collect_source_link_enrichment_candidates(
    db: Db,
    *,
    track_run_id: str = "",
    only_ambiguous: bool = True,
    source: str = "",
    limit: int = 0,
    offset: int = 0,
) -> tuple[str, list[dict[str, Any]]]:
    resolved_track_run_id = str(track_run_id or "").strip() or _latest_track_run_id(db)
    if not resolved_track_run_id:
        raise RuntimeError("No track_gate run found for source-link enrichment")

    clauses = ["ata.run_id = ?"]
    params: list[Any] = [resolved_track_run_id]
    if only_ambiguous:
        clauses.append("ata.is_ambiguous = 1")
    sources = _csv_values(source)
    if sources:
        clauses.append("lower(a.source) in (%s)" % ",".join(["?"] * len(sources)))
        params.extend(source.lower() for source in sources)
    clauses.append("(coalesce(a.source_url, '') like 'http%' or coalesce(a.source_ref, '') like 'http%')")
    where = " and ".join(clauses)
    offset_value = max(0, int(offset or 0))
    if limit and limit > 0 and offset_value > 0:
        limit_sql = " limit ? offset ?"
        params.extend((int(limit), offset_value))
    elif limit and limit > 0:
        limit_sql = " limit ?"
        params.append(int(limit))
    elif offset_value > 0:
        limit_sql = " limit -1 offset ?"
        params.append(offset_value)
    else:
        limit_sql = ""
    rows = db.query(
        f"""
        select
          a.id,
          a.source,
          a.source_ref,
          a.source_url,
          a.title,
          a.board,
          ata.track,
          ata.is_ambiguous
        from assets a
        join asset_track_assessments ata
          on ata.asset_id = a.id
        where {where}
        order by ata.is_ambiguous desc, a.source asc, a.imported_at desc, a.id asc
        {limit_sql}
        """,
        tuple(params),
    )
    return resolved_track_run_id, [dict(row) for row in rows]


def run_source_link_enrichment(
    db: Db,
    *,
    track_run_id: str = "",
    only_ambiguous: bool = True,
    source: str = "",
    limit: int = 0,
    offset: int = 0,
    notes: str = "",
    timeout_s: float = DEFAULT_TIMEOUT_S,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    allow_http: bool = False,
    include_platform_hosts: bool = False,
    browser_platform_hosts: bool = False,
    promote_best_source_url: bool = False,
    progress_every: int = 0,
) -> dict[str, Any]:
    resolved_track_run_id, candidates = collect_source_link_enrichment_candidates(
        db,
        track_run_id=track_run_id,
        only_ambiguous=only_ambiguous,
        source=source,
        limit=limit,
        offset=offset,
    )

    run_id = str(uuid.uuid4())
    created_at = _now_iso()
    config = {
        "track_run_id": resolved_track_run_id,
        "only_ambiguous": bool(only_ambiguous),
        "source": source,
        "limit": int(limit),
        "offset": int(offset),
        "timeout_s": float(timeout_s),
        "max_bytes": int(max_bytes),
        "max_redirects": int(max_redirects),
        "allow_http": bool(allow_http),
        "include_platform_hosts": bool(include_platform_hosts),
        "browser_platform_hosts": bool(browser_platform_hosts),
        "promote_best_source_url": bool(promote_best_source_url),
        "progress_every": int(progress_every),
    }
    db.exec(
        """
        insert into classification_runs
          (id, schema_version, run_type, model_provider, model_name, prompt_version, config_json, created_at, notes)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            "curation_v2",
            "source_link_enrichment",
            "heuristic",
            "url_fetch_head_meta_v1",
            "",
            json.dumps(config, sort_keys=True),
            created_at,
            notes or None,
        ),
    )

    rows_to_insert: list[tuple[Any, ...]] = []
    outcome_counts: dict[str, int] = {}
    promoted = 0
    examples: list[dict[str, Any]] = []
    browser_session_name = f"sl{run_id[:6]}"
    total = len(candidates)
    try:
        for index, asset in enumerate(candidates, start=1):
            url = _best_source_url(asset)
            host = _extract_domain(url)
            item_started_at = time.monotonic()
            mode = "http"
            if url and _is_platform_wrapper_host(host):
                mode = "browser_wrapper" if browser_platform_hosts and include_platform_hosts else "wrapper"
            if progress_every and (index == 1 or index % progress_every == 0 or mode == "browser_wrapper"):
                _log_progress(
                    "source-link-enrichment start "
                    f"{index}/{total} asset={asset['id']} source={asset.get('source','')} host={host or '-'} "
                    f"mode={mode} title={_log_value(asset.get('title', ''))}"
                )
            if url and _is_platform_wrapper_host(host):
                if not include_platform_hosts:
                    result = {
                        "input_url": url,
                        "final_url": url,
                        "final_domain": host,
                        "canonical_url": "",
                        "og_image_url": "",
                        "page_title": "",
                        "og_title": "",
                        "meta_description": "",
                        "og_description": "",
                        "text_excerpt": "",
                        "content_type": "",
                        "http_status": None,
                        "redirect_count": 0,
                        "truncated": 0,
                        "fetch_status": "platform_wrapper_skipped",
                        "error": "Platform wrapper URL; no direct source page captured on this asset",
                        "content_hash": "",
                    }
                elif browser_platform_hosts:
                    result = _fetch_source_page_browser(
                        url=url,
                        timeout_s=timeout_s,
                        session_name=browser_session_name,
                    )
                else:
                    result = _fetch_source_page(
                        url=url,
                        timeout_s=timeout_s,
                        max_bytes=max_bytes,
                        max_redirects=max_redirects,
                        allow_http=allow_http,
                    )
            elif url:
                result = _fetch_source_page(
                    url=url,
                    timeout_s=timeout_s,
                    max_bytes=max_bytes,
                    max_redirects=max_redirects,
                    allow_http=allow_http,
                )
            else:
                result = {
                    "input_url": "",
                    "final_url": "",
                    "final_domain": "",
                    "canonical_url": "",
                    "og_image_url": "",
                    "page_title": "",
                    "og_title": "",
                    "meta_description": "",
                    "og_description": "",
                    "text_excerpt": "",
                    "content_type": "",
                    "http_status": None,
                    "redirect_count": 0,
                    "truncated": 0,
                    "fetch_status": "no_url",
                    "error": "No fetchable source URL",
                    "content_hash": "",
                }
            outcome = str(result["fetch_status"])
            outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1
            promoted_url = ""
            if promote_best_source_url:
                promoted_url = _promoted_source_url_candidate(asset, result)
                if promoted_url:
                    promoted_host = _extract_domain(promoted_url)
                    db.exec(
                        "update assets set source_url=?, source_domain=? where id=?",
                        (promoted_url, promoted_host or None, str(asset["id"])),
                    )
                    _record_field_provenance(
                        db,
                        asset_id=str(asset["id"]),
                        field_name="source_url",
                        field_value=promoted_url,
                        origin_type="source_link_enrichment",
                        origin_ref=run_id,
                        actor="source_link_enrichment",
                        confidence=0.92,
                        created_at=created_at,
                    )
                    promoted += 1
            rows_to_insert.append(
                (
                    str(uuid.uuid4()),
                    run_id,
                    str(asset["id"]),
                    _db_text(result.get("input_url")),
                    _db_text(result.get("final_url")),
                    _db_text(result.get("final_domain")),
                    _db_text(result.get("canonical_url")),
                    _db_text(result.get("og_image_url")),
                    _db_text(result.get("page_title")),
                    _db_text(result.get("og_title")),
                    _db_text(result.get("meta_description")),
                    _db_text(result.get("og_description")),
                    _db_text(result.get("text_excerpt")),
                    _db_text(result.get("content_type")),
                    result.get("http_status"),
                    int(result.get("redirect_count") or 0),
                    int(result.get("truncated") or 0),
                    outcome,
                    _db_text(result.get("error")),
                    _db_text(result.get("content_hash")),
                    created_at,
                )
            )
            if len(examples) < 10:
                examples.append(
                    {
                        "asset_id": str(asset["id"]),
                        "source": str(asset.get("source") or ""),
                        "input_url": str(result.get("input_url") or ""),
                        "fetch_status": outcome,
                        "page_title": str(result.get("page_title") or ""),
                        "final_domain": str(result.get("final_domain") or ""),
                        "promoted_source_url": promoted_url,
                    }
                )
            elapsed_s = time.monotonic() - item_started_at
            if progress_every and (index == 1 or index % progress_every == 0 or outcome != "fetched" or mode == "browser_wrapper" or index == total):
                _log_progress(
                    "source-link-enrichment done "
                    f"{index}/{total} asset={asset['id']} status={outcome} elapsed_s={elapsed_s:.1f} "
                    f"domain={_log_value(result.get('final_domain', ''), limit=80)} "
                    f"page_title={_log_value(result.get('page_title', ''))}"
                )
    finally:
        if browser_platform_hosts and include_platform_hosts:
            _close_playwright_session(browser_session_name, timeout_s=timeout_s)

    if rows_to_insert:
        db.executemany(
            """
            insert into asset_source_link_enrichment (
              id, run_id, asset_id, input_url, final_url, final_domain, canonical_url, og_image_url,
              page_title, og_title, meta_description, og_description, text_excerpt, content_type,
              http_status, redirect_count, truncated, fetch_status, error, content_hash, created_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows_to_insert,
        )

    return {
        "ok": True,
        "run_id": run_id,
        "track_run_id": resolved_track_run_id,
        "schema_version": "curation_v2",
        "run_type": "source_link_enrichment",
        "model_provider": "heuristic",
        "model_name": "url_fetch_head_meta_v1",
        "candidate_count": len(candidates),
        "rows_written": len(rows_to_insert),
        "counts": outcome_counts,
        "promoted_source_url_count": promoted,
        "examples": examples,
    }
