# Inspirations — Project-Specific Agent Notes

> **Shared roles, delegation patterns, and communication rules are in
> `/Users/minime/Projects/AGENTS.md`.** This file contains only
> Inspirations-specific extensions.

---

## Agent Roles (Rebuild)

- **Opus** — Browser scraping (Pinterest + Facebook), hard research, architectural decisions.
  Produces scrape JSON files in `data/scrape/`.
- **Sonnet** — Code implementation from specs. Implements `docs/SCRAPE_REBUILD_SPEC.md`.
  Cheaper and faster for structured coding work.

## Architecture Guardrails

- **Backend:** Python standard library only. No Flask, Django, FastAPI, or similar.
  The server is `http.server.ThreadingHTTPServer` in `server.py`.
- **Frontend:** Vanilla HTML/CSS/JS. No build tools, bundlers, or frameworks.
  No npm, no node_modules.
- **Database:** SQLite via `db.py`. All schema changes go through the migration
  system in `db.py`. Never write raw `CREATE TABLE` outside of it.
- **Importers:** Follow the adapter pattern in `importers/`. Each importer normalizes
  source data into `Asset` records. New importers must be idempotent.
- **AI pipeline:** Tag via `ai.py`. Primary model `gemini-2.5-flash`, fallback
  `gemini-2.0-flash` on RECITATION. Do not change model selection without user approval.

## Project-Specific Rules

- **No external Python dependencies** beyond optional Pillow. Do not add pip packages
  without explicit user approval.
- **Preserve idempotency.** Importers are idempotent by design. Do not introduce
  side effects that break re-runnability.
- **CLI output is JSON.** All CLI commands must produce JSON. Do not add
  human-readable-only output.
- **Security:** Validate all external URLs through `security.py`. Never bypass
  safe-URL checks.
- **UX tone:** Friendly, not techy. The curator app should feel warm and approachable,
  not like a developer tool.
- **Port coordination:** Inspirations runs on `8001`. Do not stop services on other
  project ports (notably `8003`) unless explicitly requested and verified.

## File & Directory Conventions

- `data/`, `store/`, `imports/` are local-only and never committed.
- `data/scrape/` holds browser-scraped JSON files.
- New Python modules go in `src/inspirations/`.
- New frontend files go in `app/`.
- Operational scripts go in `tools/`.
- Documentation goes in `docs/`. Old docs archived in `docs/archive/`.
- Do not create top-level files without user approval.

---
*Last updated: 2026-03-01*
