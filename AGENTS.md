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
- **Dave key lookup:** `/api/chat` reads `ANTHROPIC_API_KEY` first, then macOS
  Keychain service `inspirations_anthropic_api_key`. Keep this service name stable.
  Setup/runbook: `docs/LOCAL_DAVE_API_KEY.md`.
- **Security:** Validate all external URLs through `security.py`. Never bypass
  safe-URL checks.
- **Magic link hygiene:** `CONTEXT.md` / `context.md` are local-only operational notes and may contain live magic links. They must stay in `.gitignore` and must not be committed.
- **UX tone:** Friendly, not techy. The curator app should feel warm and approachable,
  not like a developer tool.
- **Port coordination:** Inspirations runs on `8001`. Do not stop services on other
  project ports (notably `8003`) unless explicitly requested and verified.

## Scan Corpus Semantics

- Treat scan **pages** and scan **documents** as different concepts.
- Final corpus references should point to **logical documents**:
  - a single-page scan is one document
  - a multi-page scan is one document made of multiple page assets
- Review collections created during cleanup are **working subsets**, not the final
  document model for the corpus.
- If delimiter detection misses blank separator pages, do not assume page-level
  imports are the final truth. Preserve the page assets, but plan a follow-up pass
  to restore the intended logical document grouping.
- For architect-meeting scan batches in particular:
  - single-page items should remain referable as standalone documents in the corpus
  - multi-page items should be regrouped into their original document units once
    the page boundaries are confirmed
  - exclusion/cleanup collections do not replace that underlying document intent

## Formatted Deliverables Tooling

Use this section when Jim asks for print-ready or formatted output (PDF/HTML/screenshots/visual QA).

### Skills available in this workspace

- `playwright` — Browser automation, UI flow validation, page screenshots, extraction.
- `screenshot` — OS-level screenshots when browser-only capture is not enough.
- `skill-creator` — Create/update reusable Codex skills.
- `skill-installer` — Install curated skills into `$CODEX_HOME/skills`.

### Installed formatting/export tools (local)

- `pandoc` (available in PATH) for Markdown to HTML/PDF/DOCX conversions.
- `tectonic` (available in PATH) as the default PDF engine for Pandoc.

### Default commands for formatted results

- Markdown -> PDF:
  - `pandoc <input.md> --pdf-engine=tectonic -o <output.pdf>`
- Markdown -> HTML:
  - `pandoc <input.md> -o <output.html>`
- Markdown -> DOCX:
  - `pandoc <input.md> -o <output.docx>`

### Agent behavior for formatting requests

- Prefer generating source `.md` in `docs/` first, then render downstream formats.
- If diagrams are requested, include Mermaid in Markdown; if rendered diagrams are required in PDF, use additional tooling only after approval.
- Ask before installing new tooling not already present.
- Keep generated artifacts in `docs/` unless the user requests another location.

## File & Directory Conventions

- `data/`, `store/`, `imports/` are local-only and never committed.
- `data/scrape/` holds browser-scraped JSON files.
- New Python modules go in `src/inspirations/`.
- New frontend files go in `app/`.
- Operational scripts go in `tools/`.
- Documentation goes in `docs/`. Old docs archived in `docs/archive/`.
- Do not create top-level files without user approval.

---
*Last updated: 2026-03-06*
