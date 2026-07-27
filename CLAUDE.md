# Inspirations

Local-first inspiration library for the home-design research behind the New Home
build. Browser-scraped Pinterest and Facebook data plus Houzz items and local
scans, with triage, a semantic Explorer, collection management, and
one-collection PDF export for designer handoffs.

Python standard library only (server is `http.server.ThreadingHTTPServer`),
SQLite, vanilla JS frontend with no build step.

**Read `docs/CURRENT_HANDOFF.md` first** after a reboot, branch switch, or lost
context. It has current state; this file has the invariants.

Accessibility tier: B.

## Commands

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v     # tests
ruff check src tests                                        # lint
PYTHONPATH=src python3 -m inspirations serve --reload       # dev server :8001
PYTHONPATH=src python3 -m inspirations <subcommand>         # CLI
```

Subcommands: `init`, `list`, `maintenance optimize-db`, `import pinterest-scrape`,
`import facebook-scrape`, `rebuild-db`, `thumbs`, `catalog generate`, `ai tag`,
`ai reels`, `ai errors`, `ai embed`, `ai similar`, `export html`, `export portal`
(legacy), `export collection-pdf`, `serve`.

Serve on the LAN with `--host 0.0.0.0 --port 8001`. Behind the New Home reverse
proxy, prefix with `BASE_PATH=/inspirations-app`.

Deeper notes live where the code does: `src/inspirations/CLAUDE.md` (data model,
classification, AI pipeline) and `app/CLAUDE.md` (frontend behavior).

## Invariants

- **Standard library only.** No Flask/FastAPI/Django, no bundler, no npm, no
  `node_modules`. Optional Pillow is the single permitted dependency. Adding
  anything else needs Jim's approval.
- **All schema changes go through the migration system in `db.py`.** Never write
  a raw `CREATE TABLE` outside it.
- **`ensure_schema()` runs once in `run_server()`, before the server starts.**
  API, catalog, media, and scan-PDF requests must never run migrations or
  metadata backfills — doing so caused SQLite lock storms under concurrent
  thumbnail traffic.
- **Importers are idempotent.** Keep them that way; they get re-run.
- **All CLI output is JSON.** No human-readable-only commands.
- **Validate every external URL through `security.py`.** It blocks private IPs.
  Never bypass it.
- Gemini model selection (`gemini-2.5-flash`, falling back to `gemini-2.0-flash`
  on `RECITATION`) doesn't change without approval.
- API keys resolve from env vars first, then macOS Keychain — services
  `inspirations_anthropic_api_key` and `inspirations_gemini_api_key`. Keep those
  service names stable. Setup: `docs/LOCAL_DAVE_API_KEY.md`.
- `CONTEXT.md` / `context.md` are local-only notes that may contain live magic
  links. They stay gitignored and uncommitted.
- `data/`, `store/`, `imports/` are local-only and never committed.
- UX tone is warm and friendly, not techy. This is a curator's app, not a
  developer tool.

## Gotchas

- **Text search totals:** free-text `/api/assets?q=...` skips the exact
  total-count scan. `total: null` is expected; `has_more` is authoritative.
- **`BASE_PATH` mode:** any new frontend `fetch()` or `/media/` URL must go
  through `Shared.prefixPath(path)` or `Shared.basePath`. Absolute URLs break
  the reverse-proxy deployment silently.
- **`maintenance optimize-db`** rebuilds the FTS5 index. Run after bulk imports,
  re-tagging, or direct DB edits — never on startup. Normal edit paths refresh
  their own search rows.
- **Live collaborator sharing is retired.** `/api/me`, `/api/actors`,
  `/api/context/resolve`, `/api/questions/dashboard`, and magic-link actor UX are
  disabled. Schema columns stay for compatibility; don't surface the features.
- **Known data damage:** ~174 Pinterest images failed download and show
  thumbnail fallback only; ~800 Facebook items had bad captures (login screens,
  group covers) and fall back to `thumbnail_url`, which needs internet.
- Facebook media repair uses the named Playwright/Chrome session
  `media-repair-auth`. Ordinary Safari/Chrome windows are invisible to the
  capture tool.
- Scan **pages** and scan **documents** are different things. A multi-page scan
  is one document made of several page assets. Review collections created during
  cleanup are working subsets, not the final document model. If delimiter
  detection missed blank separator pages, preserve the page assets and plan a
  regrouping pass — don't treat page-level imports as final truth.

## Before a PR touching explorer, sidebar, or browse-tree code

Start the dev server, open http://localhost:8001, paste
`tools/sanity_browse_tree_explorer.js` into the DevTools console. All 16 checks
must pass.

## Service

`./tools/inspirations_service.sh install|status|logs` installs the launchd agent
`com.jimbrannigan.inspirations` on `0.0.0.0:8001` with logs in `data/logs/`.
Registered in `../DevLauncher/config/projects.json` — update it if the port or
command changes.

CI (GitHub Actions) runs `ruff` plus the unittest suite on Python 3.11/3.12/3.13
for every push and PR.
