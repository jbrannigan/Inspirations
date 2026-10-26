# Inspirations Service Runbook

Inspirations runs under launchd in one of two modes, selected by the second
argument to `tools/inspirations_service.sh`:

- `login` (default) — a user LaunchAgent that starts at console login. Fine for
  local/LAN testing from iPad or iPhone, and able to read the login keychain.
- `boot` — a system LaunchDaemon that starts at boot with no login required.
  Required once the app is served publicly, because the tunnel comes up at boot
  and a gated site whose origin is down returns 502. Cannot read the login
  keychain: see Secrets below.

## Service

- Label: `com.jimbrannigan.inspirations`
- Plist: `~/Library/LaunchAgents/com.jimbrannigan.inspirations.plist`
- Command: `tools/run_review_server.sh`
- Bind: `0.0.0.0:8001`
- Restart policy: launchd `KeepAlive`

In `login` mode the plist is `~/Library/LaunchAgents/<label>.plist` in domain
`gui/<uid>`; in `boot` mode it is `/Library/LaunchDaemons/<label>.plist` in
domain `system`, with a `UserName` key so the server still runs as `minime`.
Neither mode needs DevLauncher or an open terminal.

Install only one mode at a time. Both would contend for port 8001; `install`
warns if the other mode's plist is still present, and `uninstall <mode>` removes
that mode's plist.

## Secrets

`tools/run_review_server.sh` resolves `GEMINI_API_KEY` and `ANTHROPIC_API_KEY`
in this order: already-set environment, then the untracked mode-0600
`.env.production`, then the macOS login keychain.

A LaunchDaemon runs outside the user's security session and starts before any
login, so it **cannot** read the login keychain. In `boot` mode the env file is
the only source; without it the server starts and serves normally but logs
`gemini_key=missing` and AI features fail. `install ... boot` warns when the
file is missing or its keys are blank.

## Commands

```bash
./tools/inspirations_service.sh install
./tools/inspirations_service.sh status
./tools/inspirations_service.sh logs
./tools/inspirations_service.sh restart
./tools/inspirations_service.sh stop
./tools/inspirations_service.sh uninstall
```

`install` safely stops an existing `8001` listener only when that listener's
command clearly belongs to this Inspirations repo.

## Access And Health Checks

Local Mac:

```bash
curl -I http://127.0.0.1:8001/
lsof -nP -iTCP:8001 -sTCP:LISTEN
```

LAN devices use the Mac mini's current LAN address:

```bash
ipconfig getifaddr en0
```

Then open `http://<mac-lan-ip>:8001` from the iPad or iPhone. A healthy
LAN-visible listener appears as `*:8001` in `lsof`.

## Logs

Logs are intentionally local-only under ignored `data/`:

- `data/logs/inspirations-8001.out.log`
- `data/logs/inspirations-8001.err.log`

The wrapper logs startup, stop signals, and process exit status. The Python
server logs startup messages and request lines. If the service disappears, run:

```bash
./tools/inspirations_service.sh status
./tools/inspirations_service.sh logs
launchctl print gui/$(id -u)/com.jimbrannigan.inspirations
```

Useful fields in `launchctl print` include `state`, `runs`, `pid`,
`last exit code`, and `last terminating signal`.

## SQLite Lock Diagnostics

Schema assurance and metadata backfills run once during server startup, before
the threaded HTTP server begins accepting requests. Normal API and media
requests must not call `ensure_schema()`.

If asset pages, thumbnails, or automatic grid loading fail intermittently,
check the stderr log for:

```text
sqlite3.OperationalError: database is locked
```

That error previously appeared when concurrent thumbnail and API requests each
attempted schema-maintenance writes. Do not fix it by restoring request-time
migrations. Confirm the server starts cleanly, then investigate any remaining
writer that overlaps normal read traffic.

## Neighbor Port

Do not stop or repurpose `8003`. That port belongs to the separate Home website
and DevLauncher work.
