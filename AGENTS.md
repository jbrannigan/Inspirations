# AGENTS.md — AI Agent Operating Manual

This file defines rules, guardrails, and workflows for **any AI coding agent**
(Claude Code, Codex, Cursor, Copilot Workspace, etc.) operating in this repository.
These directives are mandatory and override agent defaults where they conflict.

> **Relationship to other docs:** `CLAUDE.md` provides project context and architecture.
> `CONTRIBUTING.md` defines the human contribution policy. This file provides
> agent-specific behavioral rules that complement both.

## Golden Rules

1. **Never commit secrets.** API keys, passwords, `.env` files, and `admin_password.txt`
   must never appear in commits. If you detect a secret staged for commit, abort and warn.
2. **Never bypass CI.** Do not use `--no-verify`, `--no-gpg-sign`, or skip pre-commit hooks.
3. **Never force-push to `main`.** Feature branches only. No direct merges of major work.
4. **Run tests before claiming done.** Every code change must pass:
   ```bash
   PYTHONPATH=src python3 -m unittest discover -s tests -v
   ```
5. **No new external dependencies.** This project uses only the Python standard library
   (plus optional Pillow). Do not add pip packages without explicit user approval.
6. **Preserve idempotency.** Importers are idempotent by design. Do not introduce
   side effects that break re-runnability.
7. **No emoji in code or docs** unless the user explicitly requests it.

## Code Quality Standards

- **Linting:** All code must pass `ruff check src tests` (enforced in CI).
  Run it locally before committing.
- **Tests:** Use Python's built-in `unittest`. No pytest. New features require tests.
  New bug fixes require a regression test.
- **CLI output:** All CLI commands must produce JSON. Do not add human-readable-only output.
- **No over-engineering:** Do not add abstractions, helpers, or configurability beyond
  what is directly needed. Three similar lines are better than a premature abstraction.
- **Security:** Validate all external URLs through `security.py`. Never bypass safe-URL
  checks. Watch for command injection, XSS in the web app, and SQL injection in queries.

## Git & PR Workflow

### Branching

- Major features and substantial changes require a feature branch + PR.
- Branch names: `<type>/<short-description>` (e.g., `feat/export-csv`, `fix/thumbnail-crash`).
- Trivial fixes (typos, single-line changes) may commit directly to `main`.

### Commits

- Write concise commit messages focused on "why," not "what."
- Do not amend published commits. Create new commits instead.
- Stage specific files by name — never use `git add -A` or `git add .`.

### Pull Requests

- PR descriptions must include: summary, testing evidence, and the checklist
  from `CONTRIBUTING.md`.
- Update `README.md` when features are added, removed, or substantially changed.
- Update `docs/pr_summary.md` when behavior changes.

### Post-Merge Cleanup (No Confirmation Needed)

When the user states a PR has been merged, immediately:

1. `git checkout main`
2. `git pull --ff-only origin main`
3. Delete the merged feature branch locally.
4. Delete the merged feature branch on `origin` if it still exists.

Do not ask whether to perform this cleanup once the user has already confirmed it
in the thread.

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

## Testing Protocol

Before marking any task complete:

```bash
# Full test suite
PYTHONPATH=src python3 -m unittest discover -s tests -v

# Lint check
ruff check src tests
```

- If tests fail, fix the issue — do not skip or mark the test as expected-failure.
- If a test is genuinely obsolete due to your change, explain why before removing it.
- New modules need corresponding test files in `tests/`.

## File & Directory Conventions

- `data/`, `store/`, `imports/` are local-only and never committed.
- Never create files in these directories as part of code changes.
- New Python modules go in `src/inspirations/`.
- New frontend files go in `app/`.
- Operational scripts go in `tools/`.
- Documentation goes in `docs/`.
- Do not create top-level files without user approval.

## Documentation Policy

When an agent makes changes that affect user-facing behavior:

1. **README.md** — Update in the same branch/commit when:
   - A feature is added, removed, or substantially changed
   - Setup steps, CLI commands, API endpoints, or workflows change
   - If no update is needed, state that explicitly in the PR description

2. **docs/pr_summary.md** — Update when behavior changes to keep the
   changelog current.

3. **CLAUDE.md** — Update the architecture section if you add new modules,
   change the data model, or modify the command set.

4. **Do not create new documentation files** (READMEs, guides, .md files)
   unless the user explicitly requests them. Update existing docs instead.

5. **Inline comments** — Only add comments where logic is non-obvious.
   Do not add docstrings or type annotations to code you did not change.

## Agent Communication & Behavior

- **Confirm before destructive actions.** Deleting files, dropping tables,
  force-pushing, resetting branches, or removing dependencies all require
  explicit user approval — even if you think it's the right call.
- **No time estimates.** Do not predict how long tasks will take.
- **Present alternatives when blocked.** If an approach fails, propose 2-3
  options rather than retrying the same thing or brute-forcing.
- **Be concise.** Prefer short answers. Save detail for when the user asks.
- **Explain before large changes.** If a task will touch more than 3 files,
  outline your plan and get approval before writing code.
- **Flag uncertainty.** If you're unsure about a design choice or whether
  something will break existing behavior, ask rather than guess.
- **One concern at a time.** Don't pile multiple unrelated suggestions into
  a single response. Focus on the task at hand.
