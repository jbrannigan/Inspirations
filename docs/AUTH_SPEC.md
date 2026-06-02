# Authentication Specification — Inspirations

> Legacy note (2026-05-27): the magic-link collaborator actor system is retired
> from the active product. Current app sessions default to local owner mode, and
> designer handoff happens through standalone collection PDFs. Keep this document
> only as historical/compatibility reference while legacy schema remains.

## Overview

Inspirations uses a dual-auth architecture:

1. **Magic-link actor system** — for collaboration (browsing, annotating, triaging)
2. **Admin password system** — for privileged maintenance operations

These are independent systems. An actor token identifies *who you are*; an admin token authorizes *dangerous actions*.

---

## 1. Magic-Link Actor System

### Schema

```sql
-- db.py:358-370
create table if not exists actors (
  id         text primary key,           -- UUID v4
  name       text not null,              -- human-readable (e.g. "Leslie")
  token      text not null unique,       -- magic-link token
  role       text not null default 'collaborator',  -- "owner" or "collaborator"
  created_at text not null               -- ISO 8601 UTC
);
create unique index if not exists ux_actors_token on actors(token);
```

### Token generation

`store.py:1091-1100` — `create_actor()`

- ID: `uuid.uuid4()` (standard UUID v4)
- Token: `secrets.token_urlsafe(16)` — 128 bits of entropy, ~24 URL-safe characters
- Tokens are stored in plaintext in SQLite (not hashed)

### CRUD functions

All in `store.py:1091-1117`:

| Function | Signature | Notes |
|----------|-----------|-------|
| `create_actor` | `(db, *, name, role="collaborator") → dict` | Generates UUID + token |
| `list_actors` | `(db) → list[dict]` | Returns all actors ordered by `created_at` |
| `get_actor_by_token` | `(db, *, token) → dict \| None` | Lookup by magic-link token |
| `delete_actor` | `(db, *, actor_id) → None` | Hard delete from actors table |

### Default actor seeding

`server.py:1647-1663` — `_seed_default_actors()`

Called on every server start (`run_server()` line 1701). If the `actors` table is empty, creates two default owners:

- **Leslie** (role: `owner`)
- **Jim** (role: `owner`)

Magic-link URLs are printed to stdout on startup for all actors, whether newly created or existing.

---

## 2. Frontend Magic-Link Flow

`app/shared.js:3-42`

### Step-by-step

1. **Extract token from URL** — `new URLSearchParams(window.location.search).get("actor")`
2. **Persist token** — saved to both `localStorage("actorToken")` and a cookie:
   ```javascript
   document.cookie = `actorToken=${token}; path=/; max-age=31536000; SameSite=Lax`;
   ```
3. **Strip token from URL** — `window.history.replaceState()` removes `?actor=` so the token isn't bookmarkable
4. **Resolve on subsequent visits** — checks localStorage first, falls back to cookie:
   ```javascript
   const actorToken = localStorage.getItem("actorToken")
     || (document.cookie.match(/(?:^|;\s*)actorToken=([^;]+)/) || [])[1]
     || "";
   ```
5. **Send on API calls** — every `fetch()` via the shared `api()` helper includes `X-Actor-Token: <token>` if set

### Cookie properties

| Flag | Value | Notes |
|------|-------|-------|
| `path` | `/` | Accessible from all paths |
| `max-age` | `31536000` (1 year) | Long-lived |
| `SameSite` | `Lax` | Prevents CSRF; allows top-level navigation |
| `Secure` | **not set** | Cookie transmits over HTTP (production gap) |
| `HttpOnly` | **not set** | JS can read the cookie (needed for the current design) |

---

## 3. Server-Side Token Resolution

`server.py:163-174` — `_resolve_actor()`

### Resolution order

1. Check `X-Actor-Token` HTTP header (primary — used by `api()` calls)
2. Check `?actor=` query parameter (fallback — used on initial magic-link click)
3. Look up token in database via `get_actor_by_token()`
4. Return actor dict or `None`

### Result shape

```python
{
    "id": "uuid-v4",
    "name": "Leslie",
    "token": "aBcDeF-GhIjKlMnOpQrStUvW",
    "role": "owner",
    "created_at": "2026-02-28T10:23:45.123456+00:00"
}
```

---

## 4. Role-Based Access Control

### Roles

| Role | See hidden items | Manage actors | Questions dashboard | Create annotations | Triage items |
|------|:---:|:---:|:---:|:---:|:---:|
| `owner` | yes | yes | yes | yes | yes |
| `collaborator` | no | no | no | yes | yes |
| anonymous (no token) | no | no | no | no | limited |

### Owner-only endpoints

All return `403 {"error": "owner access required"}` for non-owners:

| Endpoint | Method | Purpose | Line |
|----------|--------|---------|------|
| `/api/actors` | GET | List all actors | 505 |
| `/api/actors` | POST | Create new actor | 801 |
| `/api/actors/{id}` | DELETE | Revoke an actor | 1002 |
| `/api/hidden/tree` | GET | Browse hidden items | 512 |
| `/api/questions/dashboard` | GET | View open questions | 519 |

### Hidden asset filtering

`server.py:246-252`, `store.py:453-460`

The client can request `?include_hidden=true`, but the server enforces:

```python
include_hidden = bool(include_hidden_req and actor and actor.get("role") == "owner")
```

Non-owners never see hidden items regardless of query parameters. The filtering adds SQL clauses excluding `triage_status='hidden'` and items in the "Hidden" collection.

### Attribution

- **Annotations** (`server.py:774-797`): `actor_id` and `actor_name` recorded on each annotation
- **Triage** (`server.py:672-686`): actor name recorded in `triage_log` audit table

---

## 5. Admin Password System

### Password resolution

`server.py:1022-1029` — `_admin_password()`

1. Environment variable `INSPIRATIONS_ADMIN_PASSWORD` (checked first)
2. File `{db_dir}/admin_password.txt` (fallback)
3. Empty string if neither exists (admin endpoints return 503)

### First-time setup

Open `http://localhost:8001/app/admin.html` on the Mac itself. If no admin password exists, the page exposes a first-time setup form backed by:

- `GET /api/admin/status`
- `POST /api/admin/setup`

Setup writes `{db_dir}/admin_password.txt` with `0600` permissions. The setup endpoint accepts requests only from a loopback client with a literal `localhost` or loopback Host header, and only while no password is configured. This blocks bootstrap through a public reverse proxy whose upstream connection happens to be local. After setup, enter the new password normally to start an admin session. LAN clients can log in after setup, but cannot bootstrap a password.

### Login flow

`POST /api/admin/login` — `server.py:571-589`

- Request: `{"password": "the-password"}`
- Comparison: `secrets.compare_digest()` (timing-attack safe)
- Response: `{"token": "<token>", "expires_in": 3600}`
- Token: `secrets.token_urlsafe(32)` — 256 bits of entropy
- Stored in `server.admin_tokens` dict (in-memory only, lost on restart)
- Expires in 1 hour, extended by 1 hour on each successful use

### Session management

`server.py:1031-1043` — `_require_admin_token()`

- Header: `X-Admin-Token`
- On valid token: extends expiry by 1 hour (sliding window)
- On expired token: removes from dict, returns error
- On server restart: all admin sessions are lost

### Logout

`POST /api/admin/logout` — `server.py:591-595`

Removes the token from `server.admin_tokens`.

### Protected operations

| Endpoint | Method | Requirements | Line |
|----------|--------|-------------|------|
| `/api/admin/media-repairs/refresh` | POST | `X-Admin-Token` | current |
| `/api/admin/assets/delete` | POST | `X-Admin-Token` + `admin_mode: true` + `confirm: "DELETE"` | 597-615 |

The media-repair refresh action retags replacement photos, re-embeds repaired items, and regenerates classification snapshots once per batch. Generated text cards intentionally skip visual tagging. The delete endpoint also creates a database backup before proceeding.

---

## 6. Identity Endpoint

`GET /api/me` — `server.py:234-237`

Returns the current actor (or null) based on the token in the request:

```json
{"actor": {"id": "...", "name": "Leslie", "role": "owner", "created_at": "..."}}
```

or:

```json
{"actor": null}
```

Used by the frontend to determine what UI elements to show (e.g., hidden-item toggle, actor management).

---

## 7. Security Properties

### What's in place

- Cryptographically random tokens (`secrets` module)
- Timing-safe password comparison (`secrets.compare_digest`)
- Parameterized SQL queries (no injection)
- URL-safe token format (no encoding issues)
- Token stripped from URL after capture (not bookmarkable)
- Admin tokens expire (1-hour sliding window)
- Database backup before destructive operations

### Production gaps

| Gap | Impact | Mitigation |
|-----|--------|------------|
| No `Secure` flag on cookie | Token sent over HTTP | Add flag; enforce HTTPS via Cloudflare |
| No `HttpOnly` flag on cookie | XSS can read token | Needed for current localStorage+cookie design |
| Tokens not hashed in DB | DB compromise exposes all tokens | Low risk for personal project |
| No rate limiting | Admin password brute-force | Add Cloudflare rate limiting rule |
| Actor tokens never expire | Revocation requires manual delete | Acceptable for small trust circle |
| Admin password in plaintext file | File access = admin access | Use env var in production |

---

## 8. Key Files

| File | What it contains |
|------|-----------------|
| `src/inspirations/store.py:1091-1117` | Actor CRUD functions |
| `src/inspirations/server.py:163-174` | `_resolve_actor()` — token lookup |
| `src/inspirations/server.py:571-595` | Admin login/logout endpoints |
| `src/inspirations/server.py:1022-1043` | Admin token validation |
| `src/inspirations/server.py:1647-1663` | Default actor seeding |
| `src/inspirations/db.py:358-370` | Actors table schema |
| `app/shared.js:3-42` | Frontend magic-link handling + API helper |
| `app/admin.js:79-179` | Admin login UI |
| `tests/test_server_api.py:141-179` | Auth-related tests |
