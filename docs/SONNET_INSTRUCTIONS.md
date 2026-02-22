# Instructions for Sonnet

Copy-paste this into a new Claude Code Sonnet session in the `inspirations` project directory.

---

## Prompt to give Sonnet:

```
Read docs/SCRAPE_REBUILD_SPEC.md — this is your complete implementation spec.
Read CLAUDE.md for project conventions.
Read DECISIONS.md for architectural context.

You are implementing a scrape-first rebuild of the Inspirations app. The spec has 8 parts
(0 through 7). Execute them in order:

Part 0: Delete dead code (old importers + their tests + CLI wiring). Commit separately.
Part 1: Schema changes in db.py (new columns including needs_annotation).
Part 2: Pinterest scrape importer (pinterest_scrape.py).
Part 3: Facebook scrape importer (facebook_scrape.py).
Part 4: CLI commands (import pinterest-scrape, import facebook-scrape, rebuild-db).
Part 5: Triage backend (store functions + server endpoints).
Part 6: Frontend — this is a FULL rewrite of the frontend. Read Part 6 carefully — it
        specifies a warm, friendly design with collection chat, review mode with "Comment
        later" marking, and a two-column layout. The app should NOT look techy.
Part 7: Tests for all new code.

Important constraints:
- Python stdlib only (no pip packages except optional Pillow)
- Vanilla JS frontend (no npm, no build step)
- All CLI commands output JSON
- unittest (not pytest)
- Run tests and ruff after each part

The scrape data files (data/scrape/*.json) don't exist yet — Opus is producing them
in parallel. You can implement and test everything without them (use synthetic test data).
The importers just need to handle the JSON format described in the spec.

Start with Part 0 now.
```

---

## What Sonnet doesn't need to know

- How the browser scraping works (that's Opus's job)
- The old system's history (archived in docs/archive/)
- Pinterest CDN behavior, image quality research, etc.
- The consuming UX (deferred, see docs/TODO_CONSUMING_UX.md)

## What Sonnet DOES need to know

Everything is in the spec. The spec is self-contained. If Sonnet has questions about
the chat prompt implementation or the visual design, the answers are in Part 6 of the
spec. If Sonnet has questions about schema, look at Part 1. Etc.

## After Sonnet finishes

When Sonnet completes all 8 parts, the codebase will be ready for Opus to:
1. Run `rebuild-db` with the scraped data
2. Verify the app works end-to-end
3. Run Gemini tagging on the rebuilt dataset
