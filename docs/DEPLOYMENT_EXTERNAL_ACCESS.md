# Serve Inspirations to External Collaborators

## Context

Inspirations runs locally on `127.0.0.1:8001` — a pure-Python stdlib HTTP server with SQLite, serving vanilla HTML/JS and ~2 GB of image/thumb assets. You've bought `8499timberbridgeln.com` from Squarespace and want to share the app at `8499timberbridgeln.com/inspirations` with a handful of collaborators, keeping the door open to host other things (docs, etc.) at the same domain later.

As of 2026-04-23, the machine-wide hosting standard has moved to repo-local
`launchd` services plus the shared Cloudflare runbook at
`/Users/minime/Projects/DevLauncher/docs/launchd-cloudflared-standard.md`. Treat
the manual LaunchAgent examples below as historical context, not the preferred
final state.

## Recommendation: Cloudflare Tunnel from your Mac

**Why this beats a VPS or Tailscale Funnel for your situation:**
- Zero hosting cost, zero data migration (12 GB store + 316 MB SQLite stay on your Mac)
- Cloudflare handles HTTPS, caching, DDoS, and basic WAF for free
- Path-based routing is natively supported for future apps
- No Docker, no nginx, no server to patch — you just keep running the Python server locally

**Trade-off:** Your Mac must stay on. If it sleeps or loses internet, the site goes down. For a handful of collaborators on a home-build project, that's fine. In the current standard, the app should run under `launchd` and `cloudflared` should use Cloudflare's official service installer.

**How it works with your router:** `cloudflared` makes a regular outbound HTTPS connection (port 443) from your Mac to Cloudflare's edge — the same kind your browser makes. Your router needs no port forwarding, no firewall changes, no configuration at all. Cloudflare sends incoming visitor requests back through the already-open tunnel. Your home IP is never exposed to collaborators.

**How collaborators authenticate:** Each collaborator gets a magic-link URL with a unique token (e.g. `https://8499timberbridgeln.com/inspirations/?actor=TOKEN`). They click it once; the token persists in their browser's localStorage + cookie. No passwords, no accounts, no login page. You create/revoke actors via `POST /api/actors` (owner-only).

---

## Implementation Steps

### Step 1: DNS — Move Squarespace nameservers to Cloudflare

1. Create free Cloudflare account at cloudflare.com
2. Add `8499timberbridgeln.com` — Cloudflare will assign two nameservers
3. In Squarespace Domains dashboard, change nameservers to the Cloudflare ones (don't transfer the domain, just swap NS records)
4. Wait for propagation (usually 15-30 min, up to 48 hrs)
5. Verify domain is active in Cloudflare dashboard

> If Squarespace is handling email for this domain, recreate MX records in Cloudflare first.

### Step 2: Install and configure cloudflared

```bash
brew install cloudflared
cloudflared tunnel login            # opens browser, select your domain
cloudflared tunnel create inspirations
```

Create `~/.cloudflared/config.yml`:
```yaml
tunnel: <TUNNEL-UUID>
credentials-file: /Users/minime/.cloudflared/<TUNNEL-UUID>.json

ingress:
  - hostname: 8499timberbridgeln.com
    service: http://localhost:8001
  - service: http_status:404
```

Route DNS:
```bash
cloudflared tunnel route dns inspirations 8499timberbridgeln.com
```

### Step 3: Path routing via Cloudflare Transform Rule

Since the Python server expects paths like `/api/assets`, `/store/thumbs/...` (not `/inspirations/api/assets`), use a Cloudflare Transform Rule (free, up to 10 rules) to strip the prefix:

- Cloudflare Dashboard > Rules > Transform Rules > Rewrite URL
- **When:** URI Path starts with `/inspirations`
- **Rewrite to:** Dynamic — `regex_replace(http.request.uri.path, "^/inspirations", "")`

This way `8499timberbridgeln.com/inspirations/api/assets` hits your server as `/api/assets`. No code changes needed for path routing.

**For adding other apps later**, use subdomains (simplest) or Cloudflare Workers for path-prefix routing to different local ports:
- `docs.8499timberbridgeln.com` → `localhost:8002`
- Or a Worker that routes `/docs/*` → one tunnel, `/inspirations/*` → another

### Step 4: Security hardening (code changes)

Four small changes to make the app safe for internet exposure:

**4a. Switch to ThreadingHTTPServer** — `server.py:16,1683`
The current single-threaded server will block all users when one request is slow. One-line fix:

```python
# line 16: add ThreadingHTTPServer to import
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer

# line 1683: swap HTTPServer → ThreadingHTTPServer
server = ThreadingHTTPServer((host, port), ApiHandler)
```

**4b. Enable SQLite WAL mode** — `db.py` (in `ensure_schema` or connection setup)
Required for safe concurrent reads/writes with ThreadingHTTPServer:

```python
db.exec("PRAGMA journal_mode=WAL")
```

**4c. Add security headers** — `server.py:152` (`_send` function) and static file responses

```python
handler.send_header("X-Content-Type-Options", "nosniff")
handler.send_header("X-Frame-Options", "DENY")
handler.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
```

**4d. Secure cookie flag** — `app/shared.js:9`

```javascript
// Add Secure flag so cookie is only sent over HTTPS
document.cookie = `actorToken=${_urlActorToken}; path=/; max-age=${60 * 60 * 24 * 365}; SameSite=Lax; Secure`;
```

### Step 5: Root domain redirect

Add a Cloudflare Redirect Rule so `8499timberbridgeln.com/` redirects to `/inspirations`:
- Rules > Redirect Rules > Create Rule
- **When:** URI Path equals `/`
- **Then:** Redirect to `https://8499timberbridgeln.com/inspirations/` (301 permanent)

### Step 6: Cloudflare SSL settings

In Cloudflare Dashboard:
- SSL/TLS > set mode to **Full** (not "Full Strict" — your local server has no cert)
- Edge Certificates > enable **Always Use HTTPS**
- (Optional) Enable **Auto Minify** for JS/CSS and **Brotli** compression

### Step 7: Cloudflare rate limiting

Free plan allows 1 rate limiting rule. Protect admin login from brute-force:
- Security > WAF > Rate Limiting Rules
- Match: URI Path equals `/api/admin/login`
- Rate: 5 requests per minute per IP
- Action: Block

### Step 8: Auto-start via launchd + shared Cloudflare standard

- Run Inspirations under its own repo-local `launchd` service.
- Reuse the Mac mini's shared Cloudflare tunnel instead of starting a separate
  long-lived `cloudflared` process from this repo.
- Use `cloudflared service install` for login-only setup or
  `sudo cloudflared service install` for boot-time setup.
- Store boot-time Cloudflare config in `/etc/cloudflared/config.yml`.
- Also: System Settings > Energy > prevent automatic sleep when display is off.

### Step 9: Send magic links to collaborators

Once running, collaborators access the site via magic link URLs:
```
https://8499timberbridgeln.com/inspirations/?actor=<THEIR-TOKEN>
```
The token persists in their browser's localStorage + cookie. They bookmark the site and it works from then on.

---

## Files to modify

| File | Change |
|------|--------|
| `src/inspirations/server.py:16` | Import `ThreadingHTTPServer` |
| `src/inspirations/server.py:1683` | Use `ThreadingHTTPServer` |
| `src/inspirations/server.py:152-159` | Add security headers in `_send()` |
| `src/inspirations/db.py` | Add `PRAGMA journal_mode=WAL` |
| `app/shared.js:9` | Add `Secure` flag to cookie |

Plus repo-local launchd setup for the app service, and the shared machine-wide
Cloudflare configuration described in the DevLauncher runbook.

## Verification

1. Start the Python server and cloudflared tunnel locally
2. Visit `https://8499timberbridgeln.com/inspirations/` from a different network (phone on cellular, or ask a collaborator)
3. Confirm the app loads, images display, magic link auth works
4. Check Cloudflare analytics dashboard for request logs
5. Test admin login rate limiting by hitting `/api/admin/login` rapidly
6. Reboot Mac and verify the app service and Cloudflare service auto-start via `launchd`
7. Run existing test suite: `PYTHONPATH=src python3 -m unittest discover -s tests -v`
