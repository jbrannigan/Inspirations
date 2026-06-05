# Inspirations Service Runbook

Inspirations can run as a logged user LaunchAgent on the Mac mini. This is the
preferred local/LAN uptime mode when Jim is testing from iPad or iPhone.

## Service

- Label: `com.jimbrannigan.inspirations`
- Plist: `~/Library/LaunchAgents/com.jimbrannigan.inspirations.plist`
- Command: `tools/run_review_server.sh`
- Bind: `0.0.0.0:8001`
- Restart policy: launchd `KeepAlive`

This is a user LaunchAgent, not a system LaunchDaemon. It is appropriate for
logged-in Mac mini sessions. If the app must run before user login after a full
reboot, promote the setup to a LaunchDaemon.

After a reboot, the LaunchAgent starts when Jim logs into the Mac mini. It does
not require DevLauncher or an open terminal window.

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
