# Review Server Runbook — 2026-03-11

## Permanent fix for review sessions

Use DevLauncher's existing `Inspirations` project entry in `/Users/minime/Projects/Agent Manager/config/projects.json` for review sessions.

Do not use ad hoc background shell launches for review sessions.

## Why

For review, stability matters more than auto-reload.

DevLauncher does not read `/Users/minime/Projects/Inspirations/.claude/launch.json`.

It reads `/Users/minime/Projects/Agent Manager/config/projects.json`, and the existing `Inspirations` entry already runs without `--reload`:

- command: `python3 -m inspirations --db data/inspirations.sqlite --store store serve --host 0.0.0.0 --port 8001`
- cwd: `/Users/minime/Projects/Inspirations`
- health check: TCP port `8001`

That is the correct review/start path.

## DevLauncher mechanism

DevLauncher is the menu bar app in `/Users/minime/Projects/Agent Manager`.

It works like this:

1. Reads project definitions from `/Users/minime/Projects/Agent Manager/config/projects.json`.
2. Shows each project in the menu bar.
3. Uses TCP port checks every 5 seconds to decide green/red status.
4. Starts projects with `subprocess.Popen(..., shell=True, cwd=<project.path>, preexec_fn=os.setsid)`.
5. Stops only processes it started itself.
6. Writes logs to `/tmp/devlauncher/<project-name>.log`.

Relevant code:

- `/Users/minime/Projects/Agent Manager/src/devlauncher/config.py`
- `/Users/minime/Projects/Agent Manager/src/devlauncher/process_manager.py`
- `/Users/minime/Projects/Agent Manager/src/devlauncher/app.py`

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

- Use DevLauncher's `Inspirations` entry for review sessions.
- If you want reload while coding, that is a separate tool/workflow from DevLauncher, not the menu bar launcher.
- If review uptime becomes unstable even when started from DevLauncher, treat that as an application/runtime bug rather than a launch-method issue.
