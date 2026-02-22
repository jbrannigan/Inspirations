# Archived Documentation

These files document the **first generation** of the Inspirations project (February 2026).
They were archived on **2026-02-22** when the project pivoted to a **scrape-first rebuild**
approach. See `docs/SCRAPE_REBUILD_SPEC.md` for the new direction.

## Why these are archived

The original system was built around importing pre-exported ZIP files (Pinterest crawler
exports, Facebook saved-items HTML exports) and running Gemini AI tagging on those imports.
It included a cluster explorer for similarity-based curation, a multi-mode share export
pipeline, and an elaborate annotation/collection system.

The rebuild takes a fundamentally different approach: **browser-scrape Pinterest and
Facebook directly**, capture richer metadata (post text, hashtags, creator names, engagement
data, high-res images), import into a cleaned-up schema, and then curate through a
keeper/hidden triage workflow before sharing.

Most of the old code (importers, cluster tools, complex UX) is being replaced, so the
documentation that described it is no longer the active reference.

## What's here

### Architecture & product
- `ARCHITECTURE.md` -- Options analysis (local-first vs web vs hybrid)
- `PRODUCT_SPEC.md` -- Original product spec (roles, data model, workflows)
- `BUILD_TEST_PLAN.md` -- Phase-based design/build/test plan
- `CARD_CONTENT_PLAN.md` -- Card display design guidelines

### AI tagging pipeline
- `AI_TAGGING_PLAN.md` -- Gemini tagging workflow and CLI usage
- `SEARCH_STRATEGY.md` -- Hybrid search + embeddings + knowledge graph plan
- `tagging_pipeline.md` -- Preflight, estimates, auto-mode pipeline docs
- `tagging_plan.md` -- Gemini performance best practices
- `tagging_timing.md` -- Throughput measurements from Feb 5, 2026

### Cluster explorer
- `CLUSTER_EXPLORER_SPEC.md` -- Original spec (superseded by v2)
- `CLUSTER_EXPLORER_SPEC-old.md` -- Older draft (superseded by v2)
- `CLUSTER_EXPLORER_SPEC-v2.md` -- Final implementation spec for cluster explorer
- `EXPLORER_FIXES.md` -- Cluster spacing and 2D/3D view fixes

### Implementation briefs (completed work)
- `ROUND1_BUGFIXES.md` -- Round 1 bug fix implementation brief
- `ROUND2_IMPLEMENTATION.md` -- 3D semantic explorer implementation
- `PROMOTE_BOARDS_MIGRATION.md` -- One-time boards-to-collections migration
- `FACEBOOK_DOCX_IMPORT.md` -- Facebook Word doc import spec
- `OPUS_HOTFIX_SUMMARY.md` -- Manual Facebook image quality upgrade hotfix
- `EXPORT_IMPRESSIONS.md` -- Pinterest crawler dataset export record
- `UX_REFACTOR_PLAN.md` -- UX redesign plan (consumption/curation focus)

### Code reviews & audits
- `code_review_2026-02-16.md` -- Full Python backend code review
- `ux_audit_2026-02-16.md` -- Full frontend UX audit
- `claude-suggested-improvements.md` -- Repository audit (GitHub config, CI, security, testing)

### Session history & coordination
- `SESSION-LOG.md` -- Dated session log entries
- `handoff.md` -- Detailed timestamped execution history (Codex era)
- `codex_worklog_2026-02-05.md` -- Single-day Codex session log
- `next_steps.md` -- Resume checklist and coordination docs
- `fast_path.md` -- 5-minute restart checklist
- `STATUS.md` -- Project status snapshot (Feb 19, 2026)
- `pr_summary.md` -- PR summaries for all changes through Feb 19

### Project management
- `CHANGELOG.md` -- Changelog through v0.1.0 and unreleased
- `CONTRIBUTING.md` -- Inspirations-specific contribution guidelines
- `WORKFLOWS.md` -- Day-to-day operational workflows
- `potential_future_options.md` -- Roadmap and ingestion/sync options
- `SERVER-UNIFICATION.md` -- Docker containerization plan

## If you need something from here

These files are preserved for reference. Some architectural decisions (stdlib-only backend,
SQLite, vanilla JS frontend) carry forward into the rebuild. If you need to understand why
something was done a certain way in the old system, check the relevant file here.
