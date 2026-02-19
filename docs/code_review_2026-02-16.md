# Code Review: Architecture, Security, Quality & Consolidation

**Date:** February 16, 2026
**Reviewer:** Claude (Senior Software Engineer role)
**Scope:** Full Python backend (`src/inspirations/`), all 15 source files (~7,300 LOC)
**Context:** Deep code review of a ChatGPT-authored codebase, building on the February 8 audit (`claude-suggested-improvements.md`). That prior audit covered repository config, CI/CD, and surface-level code issues. This review focuses on **runtime performance**, **architectural patterns**, **security depth**, and **code consolidation**.

---

## Status of Prior Audit Findings

The February 8 audit identified 25 items. The following have been resolved since then:

- [x] Branch protection on `main`
- [x] LICENSE file added
- [x] Path traversal fixed (uses `Path.relative_to`)
- [x] `.env` added to `.gitignore`
- [x] Python version matrix in CI (3.11, 3.12, 3.13)
- [x] Ruff linting in CI
- [x] `secrets.compare_digest` for admin password
- [x] Improved MIME type detection
- [x] Dependabot for GitHub Actions
- [x] `[build-system]` in `pyproject.toml`
- [x] `CLAUDE.md` committed

The following from the prior audit remain **open** and are reiterated in this review where applicable:

- [ ] `ensure_schema()` per-request (now elevated to Critical — Section 1.1 below)
- [ ] DNS rebinding TOCTOU (Section 2.5 below)
- [ ] Admin token eviction (Section 2.2 below)
- [ ] No CORS headers (lower priority, unchanged)
- [ ] No CSP / security headers (lower priority, unchanged)
- [ ] `ThreadingHTTPServer` (unchanged)
- [ ] WAL mode (unchanged)

---

## 1. Architecture & Scalability

### 1.1 CRITICAL: `ensure_schema()` called on every single request

**Location:** `server.py:688-690`

```python
def _with_db(self, fn, **kwargs):
    with Db(self.server.db_path) as db:
        ensure_schema(db)
        return fn(db, **kwargs)
```

Every API call opens a new SQLite connection and runs the full DDL suite: CREATE TABLE IF NOT EXISTS (x8), ALTER TABLE column checks (x8 columns with individual PRAGMA calls), CREATE INDEX IF NOT EXISTS (x15), and crucially — `_backfill_assets_metadata`, which runs a SELECT across the entire assets table with a multi-condition WHERE clause.

**Impact:** With 3,661 tagged Pinterest assets plus Facebook/scan assets, every GET `/api/assets` pays a measurable tax before the actual query runs. On LAN use from phone/tablet, this compounds with network latency.

**Fix:**

```python
# server.py — run_server()
def run_server(*, host, port, db_path, app_dir, store_dir):
    with Db(db_path) as db:
        ensure_schema(db)           # once at startup
    server = HTTPServer((host, port), ApiHandler)
    # ...

# server.py — _with_db()
def _with_db(self, fn, **kwargs):
    with Db(self.server.db_path) as db:
        return fn(db, **kwargs)     # schema already ensured
```

CLI commands still call `ensure_schema` individually before their operation, which is correct since they are one-shot processes.

---

### 1.2 HIGH: N+1 query in `list_collections`

**Location:** `store.py:233-243`

```python
def list_collections(db: Db) -> list[dict[str, Any]]:
    rows = db.query("select ... from collections order by updated_at desc")
    out = []
    for r in rows:
        count = db.query_value(
            "select count(*) from collection_items where collection_id=?", (r["id"],)
        )
        d = dict(r)
        d["count"] = count
        out.append(d)
    return out
```

Each collection fires a separate COUNT query. With 20 collections that's 21 queries per API call.

**Fix:**

```python
def list_collections(db: Db) -> list[dict[str, Any]]:
    rows = db.query("""
        select c.id, c.name, c.description, c.created_at, c.updated_at,
               count(ci.asset_id) as count
        from collections c
        left join collection_items ci on ci.collection_id = c.id
        group by c.id
        order by c.updated_at desc
    """)
    return [dict(r) for r in rows]
```

---

### 1.3 HIGH: Five correlated subqueries per row in `list_assets`

**Location:** `store.py:116-124`

The main asset listing runs 5 correlated subqueries per row to fetch the latest AI result:

```sql
(select ai.summary from asset_ai ai where ai.asset_id=a.id order by ai.created_at desc limit 1) as ai_summary,
(select ai.json from asset_ai ai where ai.asset_id=a.id order by ai.created_at desc limit 1) as ai_json,
(select ai.model from asset_ai ai where ai.asset_id=a.id order by ai.created_at desc limit 1) as ai_model,
(select ai.provider ...) as ai_provider,
(select ai.created_at ...) as ai_created_at,
```

At the default page size of 240, that's ~1,200 subquery evaluations per page load.

**Fix:** Use a single lateral-style subquery or window function:

```sql
left join (
    select asset_id, summary, json, model, provider, created_at,
           row_number() over (partition by asset_id order by created_at desc) as rn
    from asset_ai
) ai on ai.asset_id = a.id and ai.rn = 1
```

Note: This same 5-subquery pattern also appears in `run_similarity_search` (`ai.py:777-783`) and `_rows_for_export` logic. Fixing it in `store.py` should establish the pattern for the others.

---

### 1.4 MEDIUM: Similarity search loads all embeddings into Python

**Location:** `ai.py:770-845`

`run_similarity_search` fetches every embedding row from the database, JSON-parses each vector into a Python list of floats, and computes cosine similarity in pure Python. With 3,661+ assets and 768-dimensional vectors, this is ~22MB of JSON deserialized per query.

**Current impact:** Acceptable at current scale (sub-second on local SSD). Will become the bottleneck above ~10K assets.

**Future options (no action required now):**
- Cache parsed vectors in a server-level dict at startup
- Use sqlite-vec extension for in-database vector operations
- Pre-compute and cache a numpy-style matrix (if Pillow/numpy are ever added as optional deps)

---

### 1.5 MEDIUM: `set_collection_order` issues one UPDATE per item

**Location:** `store.py:302-308`

```python
for idx, aid in enumerate(asset_ids):
    db.exec("update collection_items set position=? where collection_id=? and asset_id=?",
            (idx + 1, collection_id, aid))
```

Reordering 50 items = 50 individual UPDATE round-trips.

**Fix:**

```python
db.executemany(
    "update collection_items set position=? where collection_id=? and asset_id=?",
    [(idx + 1, collection_id, aid) for idx, aid in enumerate(asset_ids)],
)
```

---

### 1.6 MEDIUM: `remove_from_tray` loops instead of batching

**Location:** `store.py:377-381`

```python
def remove_from_tray(db: Db, *, asset_ids: list[str]) -> None:
    for aid in asset_ids:
        db.exec("delete from tray_items where asset_id=?", (aid,))
```

**Fix:**

```python
if asset_ids:
    placeholders = ",".join(["?"] * len(asset_ids))
    db.exec(f"delete from tray_items where asset_id in ({placeholders})", tuple(asset_ids))
```

---

### 1.7 LOW: `export.py` is 2,611 lines

This single file embeds hundreds of lines of HTML, CSS, and JavaScript as Python string literals for the gallery and portal exports. It is the largest file by 2x and mixes template concerns with data logic.

**Suggestion:** Extract HTML/CSS/JS templates into standalone files under `app/templates/` or `src/inspirations/templates/`, loaded at export time with `Path.read_text()`. This makes both the Python logic and the templates independently editable and reviewable.

---

## 2. Security

### 2.1 HIGH: Admin token dict grows unbounded

**Location:** `server.py:336, 824`

```python
server.admin_tokens = {}
# ...
self.server.admin_tokens[token] = time.time() + 3600
```

Tokens accumulate forever. Expired tokens are only removed when *that specific token* is accessed again. Sustained login activity (legitimate or adversarial) causes unbounded memory growth.

**Fix — add lazy eviction to `_require_admin_token`:**

```python
def _require_admin_token(self) -> tuple[str | None, str | None]:
    now = time.time()
    # Lazy eviction: remove all expired tokens
    expired = [k for k, v in self.server.admin_tokens.items() if v < now]
    for k in expired:
        del self.server.admin_tokens[k]
    # ... rest of validation
```

---

### 2.2 HIGH: `model` parameter interpolated into API URL

**Location:** `ai.py:303`, `ai.py:369`

```python
url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
```

The `model` value originates from CLI `--model` flag or API query params. A crafted value like `../../admin` would produce a malformed URL. While Google's API would reject it, this is a URL injection vector that should be validated at the boundary.

**Fix:**

```python
import re
_MODEL_RE = re.compile(r'^[a-zA-Z0-9._-]+$')

def _validate_model_name(model: str) -> str:
    if not _MODEL_RE.match(model):
        raise ValueError(f"Invalid model name: {model}")
    return model
```

Apply at the entry points in `_gemini_generate` and `_gemini_embed_text`.

---

### 2.3 MEDIUM: `_ensure_columns` uses f-strings for DDL identifiers

**Location:** `db.py:52-57`

```python
def _ensure_columns(db: Db, table: str, columns: dict[str, str]) -> None:
    existing = {r["name"] for r in db.query(f"pragma table_info({table});")}
    for name, decl in columns.items():
        db.exec(f"alter table {table} add column {name} {decl};")
```

All values are currently hardcoded internal constants. However, this sets a pattern where future contributors might pass unsanitized values into DDL operations. SQLite does not support parameterized identifiers, so validation is the only option.

**Fix — add a compile-time assertion:**

```python
_SAFE_IDENT_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')

def _ensure_columns(db: Db, table: str, columns: dict[str, str]) -> None:
    assert _SAFE_IDENT_RE.match(table), f"Unsafe table name: {table}"
    for name in columns:
        assert _SAFE_IDENT_RE.match(name), f"Unsafe column name: {name}"
    # ... existing logic
```

---

### 2.4 MEDIUM: SSRF DNS rebinding (TOCTOU)

**Location:** `security.py:51-90` + `storage.py:200-263`

`is_safe_public_url` resolves DNS and validates IPs, but the actual HTTP request in `download_url_to_store` resolves DNS independently. Between the two, a malicious DNS server could rebind to a private IP.

**Status:** Identified in prior audit. Blast radius is low (local-first tool, user-initiated downloads only). Documenting as a known limitation is sufficient for now.

---

### 2.5 LOW: No rate limiting on admin login

**Location:** `server.py:319-337`

`POST /api/admin/login` has no throttling. A brute-force attack on the admin password faces no resistance beyond the `secrets.compare_digest` timing protection.

**Suggestion:** Simple in-memory counter with exponential backoff after N failed attempts from the same handler connection. Not urgent for a LAN-only tool.

---

## 3. Readability & Maintainability

### 3.1 HIGH: Monolithic route dispatch in handler methods

**Location:** `server.py:121-272` (do_GET ~150 lines), `server.py:274-420` (do_POST ~150 lines)

Both methods are long chains of `if parsed.path == ...` / `m = re.match(...)` with inline request handling. This makes it hard to: find a specific route, test a handler in isolation, or add a new route without risk of misordering.

**Suggestion — declarative route table:**

```python
_GET_ROUTES = [
    (re.compile(r'^/api/assets$'),                        '_handle_get_assets'),
    (re.compile(r'^/api/collections$'),                   '_handle_get_collections'),
    (re.compile(r'^/api/collections/([^/]+)/items$'),     '_handle_get_collection_items'),
    (re.compile(r'^/api/facets$'),                        '_handle_get_facets'),
    (re.compile(r'^/api/tray$'),                          '_handle_get_tray'),
    (re.compile(r'^/api/annotations$'),                   '_handle_get_annotations'),
    (re.compile(r'^/api/search/similar$'),                '_handle_get_similar'),
    (re.compile(r'^/api/cluster/review$'),                '_handle_get_cluster_review'),
    (re.compile(r'^/media/([^/]+)$'),                     '_serve_media'),
]

def do_GET(self):
    parsed = urlparse(self.path)
    for pattern, handler_name in _GET_ROUTES:
        m = pattern.match(parsed.path)
        if m:
            return getattr(self, handler_name)(parsed, m)
    # static file fallback ...
    self.send_error(404)
```

Each handler becomes a focused method (~10-30 lines) that is independently testable.

---

### 3.2 HIGH: Repeated query-parameter parsing boilerplate

**Location:** `server.py:162-189` (similarity), `server.py:222-242` (cluster review), and others

The pattern of extracting, stripping, defaulting, and type-converting query params is repeated ~15 times:

```python
limit_raw = (q.get("limit", ["25"])[0] or "25").strip()
try:
    limit = max(1, min(500, int(limit_raw)))
except ValueError:
    return _send(self, 400, {"error": "limit must be integer"})
```

**Fix — extract helpers:**

```python
def _q_str(q: dict, key: str, default: str = "") -> str:
    return (q.get(key, [default])[0] or default).strip()

def _q_int(q: dict, key: str, default: int, *, min_val: int | None = None, max_val: int | None = None) -> int | None:
    """Returns parsed int or None on parse failure."""
    try:
        val = int(_q_str(q, key, str(default)))
        if min_val is not None: val = max(min_val, val)
        if max_val is not None: val = min(max_val, val)
        return val
    except ValueError:
        return None

def _q_float(q: dict, key: str, default: float) -> float | None:
    try:
        return float(_q_str(q, key, str(default)))
    except ValueError:
        return None
```

---

### 3.3 MEDIUM: `_handle_scan_pdf_upload` and `_handle_photo_upload` are 95% identical

**Location:** `server.py:422-492` and `server.py:494-550`

Both methods follow the exact same flow:
1. Parse multipart form
2. Validate filename extension
3. Sanitize filename
4. Create timestamped batch directory
5. Write uploaded bytes
6. Call source-specific importer
7. Call `generate_thumbnails`
8. Return report

The only differences are: allowed extensions, which importer function to call, and the source name for thumbnails. This should be a single generic method parameterized by extension set and importer callable.

---

### 3.4 MEDIUM: Built-in `format` shadowed

**Location:** `scans.py:258`

```python
def import_scans_inbox(db, inbox_dir, store_dir, *, format: str = "jpg", ...):
```

Shadows Python's built-in `format()`. Use `fmt` or `image_format` instead. This parameter name is also used in `cli.py:319` (`--format` maps to `args.format`); the CLI flag name can stay, but the internal parameter should be renamed.

---

### 3.5 LOW: Server attributes set via monkey-patching

**Location:** `server.py:818-824`

```python
server = HTTPServer((host, port), ApiHandler)
server.db_path = db_path       # not declared on HTTPServer
server.app_dir = app_dir
server.store_dir = store_dir
server.imports_dir = ...
server.admin_tokens = {}
```

These attributes are invisible to type checkers and IDE autocompletion. A small subclass makes this explicit:

```python
class InspirationServer(HTTPServer):
    def __init__(self, addr, handler, *, db_path, app_dir, store_dir, imports_dir):
        super().__init__(addr, handler)
        self.db_path: Path = db_path
        self.app_dir: Path = app_dir
        self.store_dir: Path = store_dir
        self.imports_dir: Path = imports_dir
        self.admin_tokens: dict[str, float] = {}
```

---

## 4. Consolidation (Duplicated Logic)

### 4.1 HIGH: `_now_iso()` defined 5 times

Identical implementations in:
- `store.py:10`
- `ai.py:99`
- `importers/facebook_saved.py:16`
- `importers/pinterest_crawler.py:13`
- `importers/scans.py:24`

**Fix:** Define once, import everywhere:

```python
# db.py (already imported by all modules)
def now_iso() -> str:
    """UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()
```

---

### 4.2 HIGH: `_looks_like_image_ref` defined 3 times with divergent logic

| File | Extensions | Method |
|------|-----------|--------|
| `db.py:60-69` | jpg, jpeg, png, webp, gif, bmp, svg | Regex + substring |
| `export.py:21-28` | jpg, jpeg, png, webp, gif, bmp, svg | `str.endswith()` + substring |
| `facebook_saved.py:44-57` | jpg, jpeg, png, webp, gif, bmp, svg | Regex + substring |

Three different implementations of the same concept with subtle logic differences (regex vs endswith, different query-string handling).

**Fix:** Single canonical function in `db.py` (or a new `utils.py`), imported by `export.py` and `facebook_saved.py`.

---

### 4.3 HIGH: `_mime_from_path` / `_mime_for_path` defined twice

| File | Name | Extensions |
|------|------|-----------|
| `ai.py:112-122` | `_mime_from_path` | jpg, png, webp, gif |
| `export.py:31-45` | `_mime_for_path` | jpg, png, webp, gif, bmp, svg |

The `ai.py` version is a strict subset of the `export.py` version. Both are used to determine MIME type from file extension.

**Fix:** Single function with the full extension set. Good candidate for `db.py` or `utils.py`.

---

### 4.4 MEDIUM: CSV-split-and-filter pattern repeated ~10 times

The pattern `[s.strip() for s in value.split(",") if s.strip()]` followed by dynamic `IN (?,?,?)` construction appears in:
- `store.py` — lines 38, 42, 68, 72, 76 (five occurrences in `list_assets` alone)
- `store.py:200-208` — in `list_facets`
- `ai.py:511-517` — in `run_ai_error_triage`
- `ai.py:761-767` — in `run_similarity_search`
- `export.py:202-205` — in `_rows_for_export`

**Fix:**

```python
# db.py or utils.py
def csv_split(raw: str) -> list[str]:
    """Split comma-separated string, strip whitespace, drop empties."""
    return [s.strip() for s in (raw or "").split(",") if s.strip()]

def in_clause(column: str, values: list[str]) -> tuple[str, list[str]]:
    """Build a parameterized IN clause: ('col IN (?,?)' , ['a','b'])"""
    return f"{column} in ({','.join(['?'] * len(values))})", values
```

---

### 4.5 MEDIUM: `_extract_domain` / `_domain_from_any` overlap

| File | Function | Input type |
|------|----------|-----------|
| `db.py:72-82` | `_extract_domain(value: str)` | str |
| `facebook_saved.py:98-110` | `_domain_from_any(value: Any)` | Any |

Both parse a hostname from a URL and strip `www.` prefix. The facebook version additionally handles non-URL strings. These should be unified.

---

### 4.6 MEDIUM: Asset-ID dedup pattern copied twice

**Location:** `store.py:276-286` and `store.py:321-328`

Identical loop:
```python
unique_ids: list[str] = []
seen: set[str] = set()
for aid in asset_ids:
    aid_s = str(aid or "").strip()
    if not aid_s or aid_s in seen:
        continue
    seen.add(aid_s)
    unique_ids.append(aid_s)
```

**Fix:**

```python
def _unique_ids(raw: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for aid in raw:
        s = str(aid or "").strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out
```

---

## 5. Additional Observations

### 5.1 `_backfill_assets_metadata` has no guard clause

**Location:** `db.py:100-133`

Called from `ensure_schema` (which, per issue 1.1, runs every request). After the initial backfill completes, this SELECT still runs every time but returns 0 rows. Even when moved to startup-only, it should have a `LIMIT` to prevent accidental unbounded work during future schema migrations.

### 5.2 `_serve_media` opens its own DB connection

**Location:** `server.py:774`

This handler manually opens a DB connection and calls `ensure_schema` instead of using `_with_db`. This is a one-off inconsistency — the same method should use the standard pattern.

### 5.3 Missing `__init__.py` in `importers/`

**Location:** `src/inspirations/importers/`

The directory has no `__init__.py`. Python 3 implicit namespace packages make this work, but an explicit `__init__.py` (even empty) signals intentional package structure and avoids edge cases with some tooling.

---

## Priority Summary

| Priority | # | Key Items |
|----------|---|-----------|
| **Critical** | 1 | `ensure_schema` per-request (1.1) |
| **High** | 6 | N+1 collections (1.2), correlated subqueries (1.3), token eviction (2.1), model URL injection (2.2), `_now_iso` x5 (4.1), `_looks_like_image_ref` x3 (4.2) |
| **Medium** | 9 | Similarity in Python (1.4), set_collection_order (1.5), remove_from_tray (1.6), DDL f-strings (2.3), DNS rebinding (2.4), upload handlers (3.3), format shadowing (3.4), CSV pattern (4.4), dedup pattern (4.6) |
| **Low** | 5 | export.py size (1.7), rate limiting (2.5), server subclass (3.5), backfill guard (5.1), importers __init__ (5.3) |

### Recommended Fix Order

1. **1.1** — Move `ensure_schema` to server startup (immediate, high-impact, low-risk)
2. **4.1 + 4.2 + 4.3** — Consolidate duplicated utilities (reduces maintenance surface)
3. **1.2 + 1.3** — Fix N+1 and correlated subqueries (improves every page load)
4. **2.1 + 2.2** — Token eviction and model validation (security hygiene)
5. **1.5 + 1.6** — Batch DB operations (easy wins)
6. **3.1 + 3.2** — Route table + param helpers (readability, reduces future bugs)

---

*This document should be treated as the current source-of-truth for code-level findings. The February 8 audit (`claude-suggested-improvements.md`) remains as historical context for repository-config and CI/CD items.*
