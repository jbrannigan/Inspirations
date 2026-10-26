# Public access: inspirations.8499timberbridgeln.com

Current runbook for serving this app on the internet. Supersedes
`DEPLOYMENT_EXTERNAL_ACCESS.md`, which describes a retired design and whose
steps 3, 5 and 9 must not be re-applied.

## Shape

```
browser
  → Cloudflare edge (zone 8499timberbridgeln.com)
      → Cloudflare Access  ── email one-time PIN, allowlist
          → tunnel 481dd153-a080-46dc-9150-dfc3257db735
              → http://localhost:8001   (launchd, this repo)
```

A subdomain, not a subpath: `BASE_PATH` is not used and the New Home portal is
not involved. See D030 in `../DECISIONS.md`.

## Why the gate is load-bearing

This app has no authentication. `_resolve_actor` in `src/inspirations/server.py`
resolves any request without an actor token to
`{"id": "local-owner", "role": "owner"}`, so every `owner access required`
check passes for an anonymous caller — bulk delete included. The admin password
covers four endpoints only.

**Cloudflare Access is therefore the entire security boundary.** Treat any
change that weakens it as a change that exposes delete endpoints to the
internet. In particular:

- Never add a **Bypass** policy, for the home IP or anything else. A bypass
  grants `owner` to every device and guest on that network.
- Never leave the Access application's **path** field set. A path-scoped app
  gates one route and leaves the rest open.
- Deleting the Access application **opens** the site. It is not a rollback.

The LAN surface is a separate, accepted exposure: the service binds
`0.0.0.0:8001`, so any device on the home network reaches it as owner without
logging in. Access does nothing about that. This was a deliberate choice to keep
the existing iPad LAN route working.

## Inventory — state that exists only in the Cloudflare dashboard

Nothing below is reproducible from this repo. Keep it current.

| Item | Value |
|---|---|
| Zone | `8499timberbridgeln.com` (registrar Squarespace, nameservers at Cloudflare) |
| Account tag | `1731ea36d0478b954887f7c550ec08a4` |
| Tunnel name | `inspirations` (predates the New Home site) |
| Tunnel UUID | `481dd153-a080-46dc-9150-dfc3257db735` |
| Tunnel credentials | `~/.cloudflared/481dd153-….json` and `/etc/cloudflared/481dd153-….json` |
| cloudflared service | system LaunchDaemon `com.cloudflare.cloudflared` |
| DNS record | `inspirations` → proxied CNAME to `481dd153-….cfargotunnel.com` |
| Access team domain | `mcginty-clan.cloudflareaccess.com` (account-wide; the login page carries clan branding) |

### Access application intended state

| Field | Value |
|---|---|
| Type | Self-hosted |
| Name | `Inspirations` |
| Domain | `inspirations.8499timberbridgeln.com` |
| Path | **empty** |
| Session duration | 24h |
| App Launcher visible | No |
| Policy name | `Household` |
| Decision | Allow |
| Include | Emails: Jim, Leslie |
| Login method | One-time PIN |

Session duration is short on purpose: Access is the only control, so a stolen
browser session is total compromise. Do not exceed 168h.

Configured by hand in the dashboard, deliberately not scripted. The clan site's
`tools/cf-access-setup.py` PUT-replaces its apps and group on every run;
extending it to cover this app would add a standing way to widen or clobber a
live gate for no benefit at two users.

## Tunnel ingress

The editable source of truth is `~/.cloudflared/config.yml`. Never edit
`/etc/cloudflared/config.yml` directly — it is a synced copy and the next
install reverts it.

```yaml
ingress:
  - hostname: 8499timberbridgeln.com
    service: http://localhost:8003
  - hostname: inspirations.8499timberbridgeln.com
    service: http://localhost:8001
  - service: http_status:404
```

Rules match top to bottom. The new rule must sit **above** the
`http_status:404` catch-all; anything below it is unreachable. Use an exact
hostname — a `*.8499timberbridgeln.com` wildcard placed above the apex rule
would hijack the portal's traffic *and* route it to this ungated app.

### Applying a config-only change

Nothing in the plist changes, so do not run
`DevLauncher/scripts/install-cloudflared-boot-service.sh`: it is a full
`service uninstall` / `service install` cycle that drops the live portal, and
its uninstall is unguarded under `set -euo pipefail`, so a failed reinstall
leaves no daemon at all. Reload instead:

```sh
# validate offline first
cloudflared tunnel --config ~/.cloudflared/config.yml ingress validate
cloudflared tunnel --config ~/.cloudflared/config.yml ingress rule https://inspirations.8499timberbridgeln.com/
cloudflared tunnel --config ~/.cloudflared/config.yml ingress rule https://8499timberbridgeln.com/

# sync to the path the daemon reads, preserving the /etc credentials path
sed 's#^credentials-file:.*#credentials-file: /etc/cloudflared/481dd153-a080-46dc-9150-dfc3257db735.json#' \
  ~/.cloudflared/config.yml > /tmp/cf-config.yml
sudo install -m 600 -o root -g wheel /tmp/cf-config.yml /etc/cloudflared/config.yml

# graceful reload — keeps edge connections up, no portal downtime
sudo kill -HUP "$(pgrep -f 'cloudflared tunnel --config /etc/cloudflared/config.yml')"
```

If SIGHUP does not pick up the change, `sudo launchctl kickstart -k
system/com.cloudflare.cloudflared` restarts the process without touching the
plist (~3-8s of apex downtime). Use the installer only when the plist itself
must change.

This deviates from `DevLauncher/docs/launchd-cloudflared-standard.md` step 5,
which documents only the installer. The deviation is recorded there too.

## Order of operations

The invariant: at no point is *resolves publicly* **and** *routes to the app*
**and** *Access not enforcing* simultaneously true.

1. **Pre-flight.** Confirm `dig +short inspirations.8499timberbridgeln.com` is
   empty and the zone has no wildcard. Confirm Access seats remain under the
   50-seat free-plan limit — the clan whitelist already holds ~49 addresses.
   Confirm no zone-wide Redirect or Transform Rule would catch the new host.
2. **Create the Access application** per the table above. The hostname is not
   resolvable yet, so nothing is exposed.
3. **Create the DNS record:**
   `cloudflared tunnel route dns inspirations inspirations.8499timberbridgeln.com`.
   This goes live within seconds. The ingress rule is still absent, so the
   tunnel answers `http_status:404` — two independent barriers.
4. **Negative test, run 1** (below). The app is provably unreachable while this
   runs, so a misconfigured gate costs nothing.
5. **Add the ingress rule** and reload per the section above. Verify the portal
   still answers 200.
6. **Negative test, run 2.** This is the one that matters.
7. **Positive test**, in a browser: Jim completes the OTP, the app renders, a
   thumbnail loads, `/app/admin.html` works.
8. **Allowlist test:** a non-allowlisted address must be refused. An Allow
   policy that accidentally included everyone still produces a perfect-looking
   login for Jim.
9. **Leslie signs in** from her own device, which also confirms seats.

## Verification

Every request through the tunnel arrives from `127.0.0.1`, so the client address
cannot distinguish remote from local. Use a unique marker instead.

```sh
MARK="gate-test-$(date +%s)"

for P in "/" "/api/assets?limit=1&probe=$MARK" "/app/index.html?probe=$MARK"; do
  echo "--- $P"
  curl -sS -o /dev/null -D - --max-time 20 "https://inspirations.8499timberbridgeln.com$P" \
    | grep -Ei '^(HTTP/|location|www-authenticate)'
done

# the destructive endpoint, explicitly
curl -sS -o /dev/null -D - --max-time 20 -X POST -H 'Content-Type: application/json' -d '{}' \
  "https://inspirations.8499timberbridgeln.com/api/admin/assets/delete?probe=$MARK" \
  | grep -Ei '^(HTTP/|location)'

# follow redirects and prove no app bytes come back
curl -sS -L --max-time 20 \
  "https://inspirations.8499timberbridgeln.com/api/assets?limit=1&probe=$MARK" | head -c 300

# did anything reach the origin?  MUST print 0
grep -c "$MARK" data/logs/inspirations-8001.err.log
```

**Pass:** every probe returns `302` to `*.cloudflareaccess.com` with a
`www-authenticate: Cloudflare-Access` header; the `-L` fetch ends in Access
login HTML, never JSON; and the marker count is `0`.

**Fail:** any `200`, any `content-type: application/json`, or any non-zero
marker count. Roll back immediately.

Request lines land in `data/logs/inspirations-8001.err.log`, not `.out.log` —
`log_message` is not overridden, so they go to stderr.

Headless verification of the *authenticated* side is impossible: no Access
service token exists, and one should not be created for this app. A service
token bypasses the OTP entirely, and against an app that grants `owner` to any
caller a leaked token is total compromise. The test that actually protects the
site needs no credentials.

## Rollback

1. **Delete the DNS record** in the dashboard. Fastest, works from the
   Cloudflare mobile app, and does not touch the tunnel or the portal.
2. Then remove the ingress rule and reload, so the hostname falls through to
   `http_status:404`.

Confirm closed:

```sh
curl -sSL -o /dev/null -w '%{http_code}\n' https://inspirations.8499timberbridgeln.com/
dig +short inspirations.8499timberbridgeln.com
cloudflared tunnel --config ~/.cloudflared/config.yml ingress rule https://inspirations.8499timberbridgeln.com/
curl -sS -o /dev/null -w 'portal: %{http_code}\n' https://8499timberbridgeln.com/
```

Never `kill` either launchd-owned process; use `launchctl bootout`/`kickstart`.
`launchctl bootout system com.cloudflare.cloudflared` also takes the portal
down — last resort only.

## Known limits of remote use

- **Cloudflare free plan caps request and response bodies at 100 MB.** Ten files
  in the store exceed 90 MB; those will fail at the edge regardless of what the
  origin does. Uploads over 100 MB will fail too.
- **100-second origin timeout (error 524), not raisable on the free plan.** The
  AI labeller and the cluster export can exceed it. Through the tunnel the
  browser sees 524 while the local process runs to completion, so a retry
  repeats work that already succeeded.
- **Security headers** are set by the app itself (`ApiHandler.end_headers`);
  Access injects none. There is no CSP.
- **Reboot behaviour.** cloudflared is a system LaunchDaemon, so it comes up at
  boot. The app must therefore run in `boot` mode too:

  ```sh
  ./tools/inspirations_service.sh uninstall login
  ./tools/inspirations_service.sh install boot      # prompts for sudo
  ```

  Left as a `login` LaunchAgent, a reboot with no console login brings the
  tunnel up and the app down, and the gated site returns 502. Before switching,
  put the AI keys in the mode-0600 `.env.production`: a daemon cannot read the
  login keychain, and the wrapper will otherwise start with no keys and fail AI
  features silently.
