# Project Status (Resume Here)

## Current status (February 8, 2026)
- Pinterest provider-level tagging is complete: `3661/3661` tagged for Gemini provider (any model).
- Model split: `gemini-2.5-flash=3654`, `gemini-2.0-flash=7` (RECITATION fallback coverage).
- Missing media paths are resolved: `missing stored_path=0`, `missing thumb_path=0`.
- CI and repo governance hardening shipped:
  - Branch protection on `main` (PR + checks + no force push/delete).
  - CI matrix (`3.11`, `3.12`, `3.13`) + `ruff` lint gate.
  - `LICENSE`, `CONTRIBUTING.md`, PR template, Dependabot config.
- App includes admin delete workflow and collection bulk-remove workflow.
- First semantic-search slice is shipped:
  - `inspirations ai errors` triages `asset_ai_errors` into actionable vs historical.
  - `inspirations ai embed` stores Gemini text embeddings in `asset_embeddings`.
  - `inspirations ai similar` performs cosine similarity search over stored vectors.

## Where to look
- `docs/AI_TAGGING_PLAN.md` — Gemini tagging workflow and CLI usage
- `docs/SEARCH_STRATEGY.md` — hybrid search + embeddings + knowledge graph plan
- `docs/ARCHITECTURE.md` — end‑to‑end pipeline and options
- `docs/tagging_pipeline.md` — preflight + estimates + auto mode
- `docs/next_steps.md` — quick resume checklist after restart

## Next steps (suggested)
1. Backfill embeddings for all Pinterest assets and validate quality of semantic results.
2. Tune semantic relevance (input text composition, thresholds, query prompts) based on real usage.
3. Review tagging quality in the compact/expand UI and capture correction needs.
4. Keep handoff docs current (`docs/handoff.md`, `docs/pr_summary.md`) after each material change.
