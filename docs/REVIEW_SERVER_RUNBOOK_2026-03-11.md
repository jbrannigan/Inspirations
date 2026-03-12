# Review Server Runbook — 2026-03-11

## Permanent fix for review sessions

Use the dedicated DevLauncher configuration:

- `inspirations-review`

Do not use ad hoc background shell launches for review sessions.

## Why

For review, stability matters more than auto-reload.

The existing dev config:

- `inspirations-dev`

runs with `--reload`, which is useful while coding but introduces extra process churn. That makes it a poor default for collaborator review and UX review.

The new review config:

- binds to `127.0.0.1`
- uses port `8001`
- runs without `--reload`

That is the correct mode for review.

## Launch configs

In `/Users/minime/Projects/Inspirations/.claude/launch.json`:

- `inspirations-review`
  - stable review server
- `inspirations-dev`
  - coding/dev with reload

## What “server is up” means

Do not treat a one-shot local curl as sufficient.

For review, the server is only considered up if all of these are true:

1. DevLauncher shows the `inspirations-review` process as running.
2. The browser can load `http://127.0.0.1:8001/`.
3. `http://127.0.0.1:8001/api/me` returns `200`.

## Verification helper

Use:

```bash
/Users/minime/Projects/Inspirations/tools/check_review_server.sh
```

That reports:

- whether anything is listening on `8001`
- the HTTP status/body from `/api/me`

## Operational rule

- Use `inspirations-review` for review sessions.
- Use `inspirations-dev` only when actively editing and wanting reload behavior.
- If review uptime becomes unstable even under `inspirations-review`, treat that as an application/runtime bug rather than a launch-method issue.
