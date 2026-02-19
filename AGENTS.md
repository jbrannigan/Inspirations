# Inspirations — Project-Specific Agent Notes

> **Shared roles, delegation patterns, and communication rules are in
> `/Users/minime/Projects/AGENTS.md`.** This file contains only
> Inspirations-specific extensions.

---

## Architecture Guardrails

- **Backend:** Python standard library only. No Flask, Django, FastAPI, or similar.
  The server is `http.server.HTTPServer` in `server.py`.
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

## File & Directory Conventions

- `data/`, `store/`, `imports/` are local-only and never committed.
- New Python modules go in `src/inspirations/`.
- New frontend files go in `app/`.
- Operational scripts go in `tools/`.
- Documentation goes in `docs/`.
- Do not create top-level files without user approval.

---
*Last updated: 2026-02-18*
