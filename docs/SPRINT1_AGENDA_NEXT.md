# Sprint 1 Agenda (Current Focus)

Date: 2026-03-03
Branch: `codex/sprint1-collaborator-collections-default`

## Goal

Keep momentum on planned Sprint 1 scope, then execute a dedicated stabilization bug-fix sprint.

## In-Scope Now

1. **Review UX unification (Grid + Explorer + role model)**
   - Finalize owner/collaborator IA and review-action consistency.
   - Align tree/root behavior and review controls across views.
2. **Upgrade Add Scan/Add Clip to unified Add Media entry**
   - Move owner ingest entry to one `Add Media` flow.
   - Preserve existing clip/photo import behavior.
   - Keep video intake as planned path (initially optional/placeholder if backend ingest path is not yet ready).

## Explicitly Deferred to Stabilization Sprint

- New regressions discovered in latest device testing.
- Any non-agenda breakages should be logged and fixed in `Sprint 6 — P1/P2 Stabilization Bug-Fix Sprint` in `.claude/TODO.md`.

## Acceptance for Agenda Slice

1. Owner/collaborator IA behavior documented and reflected in UI behavior.
2. Single owner-facing `Add Media` entry is implemented and usable.
3. Existing clip/photo import paths remain functional.
4. PR notes include clear “agenda complete” handoff into bug-fix sprint.

## Status Update (May 21, 2026)

- Review UX unification is partially closed down:
  - Owner sidebar IA uses `Status`, `Collections`, and `All Items` as peer roots.
  - Collaborator sidebar IA hides `Status`, keeps `Collections` as the primary surface, and leaves `All Items` as a peer corpus-browse section.
  - Owner review actions are unified between Grid review and one-by-one review.
  - Hidden owner collections appear under a `Hidden` branch within `Collections`.
  - Collection hide/restore/delete actions remain centralized in `Manage Visibility`; the sidebar stays browse-first.

## Status Update (Mar 2, 2026)

- `Add Media` agenda item is implemented:
  - One owner header entry opens clip/photo/video import choices.
  - Clip/photo/video uploads are supported.
  - Ingest prompts now include optional `Title` + `Tags` with clickable system label chips.
  - Per current product direction, all three ingest paths are stored under the Clip source bucket.
