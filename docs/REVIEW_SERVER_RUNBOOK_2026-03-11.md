# Review Server Runbook — 2026-03-11

## Permanent fix for review sessions

Use DevLauncher's existing `Inspirations` project entry in `/Users/minime/Projects/Agent Manager/config/projects.json` for review sessions.

Do not use ad hoc background shell launches for review sessions.

That DevLauncher entry should launch the dedicated wrapper script:

- `/Users/minime/Projects/Inspirations/tools/run_review_server.sh`

## Why

For review, stability matters more than auto-reload.

DevLauncher does not read `/Users/minime/Projects/Inspirations/.claude/launch.json`.

It reads `/Users/minime/Projects/Agent Manager/config/projects.json`, and the `Inspirations` entry should run without `--reload` through the wrapper script:

- command: `exec ./tools/run_review_server.sh`
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

The review wrapper script improves observability by:

- loading API keys from env or macOS Keychain
- forcing unbuffered Python output
- logging host/port/db/store at startup
- ensuring the review server binds to `127.0.0.1:8001`

Relevant code:

- `/Users/minime/Projects/Agent Manager/src/devlauncher/config.py`
- `/Users/minime/Projects/Agent Manager/src/devlauncher/process_manager.py`
- `/Users/minime/Projects/Agent Manager/src/devlauncher/app.py`

## What “server is up” means

Do not treat a one-shot local curl as sufficient.

For review, the server is only considered up if all of these are true:

1. DevLauncher shows the `Inspirations` entry as running.
2. The browser can load `http://127.0.0.1:8001/`.
3. `http://127.0.0.1:8001/api/me` returns `200`.
4. The server stays healthy across a short dwell period, not just a one-shot curl.

## Verification helper

Use:

```bash
/Users/minime/Projects/Inspirations/tools/check_review_server.sh
```

That reports:

- whether anything is listening on `8001`
- the HTTP status for `/`
- the HTTP status/body from `/api/me`
- multiple attempts across a short dwell period

## Operational rule

- Use DevLauncher's `Inspirations` entry for review sessions.
- If you want reload while coding, that is a separate tool/workflow from DevLauncher, not the menu bar launcher.
- If review uptime becomes unstable even when started from DevLauncher, treat that as an application/runtime bug rather than a launch-method issue.
- Review logs should be read from `/tmp/devlauncher/inspirations.log`.
