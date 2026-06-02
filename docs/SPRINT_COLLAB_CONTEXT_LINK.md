# Sprint Spec: Collaboration Context Links

> Legacy note (2026-05-27): collaborator context links are retired from the
> active product. Do not implement this sprint unless the product direction
> changes again.

Status: Sprint-ready
Date: 2026-02-28
Owner: Product + Builder

## Goal

Let owner/Jim share a link to a specific item in collection context so any authenticated collaborator can open that exact context and immediately understand what is being referenced.

## Locked Decisions

1. Links are durable by default (no expiry for v1; revocation policy deferred).
2. Link opens latest collection state (not historical snapshot).
3. Link always includes fixed `item_id` anchor.
4. Any authenticated collaborator can open the link.
5. If target item is no longer in collection, show explicit "no longer in collection" state.
6. Collaborator annotations are allowed and visually distinct (name + color).
7. Annotation permissions:
   - collaborator can edit/delete their own annotations,
   - owner/Jim can edit/delete collaborator annotations.

## In Scope (v1)

1. Generate context links from current item context.
2. Share helpers in UI: copy link, email compose, message compose.
3. Resolve deep link on app load and restore context.
4. Show explicit missing-state if item removed from collection.
5. Distinct collaborator annotation styling and permissions.

## Out of Scope (v1)

1. Link expiry, revocation, or per-recipient access control.
2. Full collaborator question/reply thread system (separate sprint spec).
3. Public anonymous access.

## UX Flow

### A. Generate Link

1. Owner/Jim opens item detail in collection context.
2. Clicks `Share Context`.
3. Modal/sheet shows actions:
   - Copy Link
   - Email
   - Message
4. Link payload includes at minimum: `collection_id`, `item_id`.

### B. Open Link

1. Collaborator opens link.
2. If not authenticated, user completes normal auth flow.
3. App loads latest collection state.
4. App attempts to locate `item_id` in that collection.
5. If found, app opens item detail modal in that collection context.
6. If not found, app shows a clear state: `This item is no longer in this collection.`

## URL / Context Format (v1)

Use app URL query params (no new token system in v1):

- `collection_id=<uuid>`
- `item_id=<uuid>`
- optional `open=1` (auto-open modal)

Example:
`/?collection_id=<cid>&item_id=<aid>&open=1`

## Backend Requirements

No schema change required for link generation itself.

API additions/changes:

1. Add context resolve endpoint:
   - `GET /api/context/resolve?collection_id=<cid>&item_id=<aid>`
   - Returns:
     - `{"ok": true, "found": true, "collection_id": "...", "item_id": "..."}`
     - or `{"ok": true, "found": false, "reason": "item_not_in_collection"}`
2. Enforce role-aware hidden behavior for explorer context filters:
   - hidden assets only for owner/Jim when hidden status is explicitly active.

## Frontend Requirements

1. Add `Share Context` action to detail modal.
2. Add share action helpers:
   - Copy link (always)
   - Web Share API when available
   - fallback `mailto:` and SMS/message URL compose shortcuts.
3. On app startup, parse link params and call context resolve API.
4. If resolved, apply collection filter and open anchored item modal.
5. If unresolved, show explicit banner/state.
6. Annotation rendering:
   - show actor name + color badge,
   - enforce edit/delete permissions by actor role/id.

## Data + Permission Rules

1. Collaborator can annotate and manage only own annotations.
2. Owner/Jim can manage all annotations.
3. Collaborators can open links but do not gain owner-only powers.

## Implementation Plan

1. Backend context resolve endpoint + tests.
2. Frontend deep-link parser + restore flow.
3. Share Context button + copy/email/message actions.
4. Missing-state UI for removed item.
5. Annotation visual + permission updates.
6. Regression pass for existing modal open workflows.

## Acceptance Criteria

1. Owner/Jim can generate and copy a link from item modal.
2. Authenticated collaborator opening the link lands in the same collection + item context.
3. Link still works after collection has changed, as long as item remains in collection.
4. If item removed, user sees explicit "no longer in collection" state.
5. Collaborator annotations display name + color.
6. Collaborator cannot edit/delete other collaborator or owner annotations.
7. Owner/Jim can edit/delete collaborator annotations.

## Test Plan

1. Unit tests: context resolve endpoint membership logic.
2. API tests: auth + role checks for hidden visibility behavior.
3. UI tests:
   - link generation from modal,
   - deep-link restore success,
   - deep-link removed-item state,
   - annotation permission gates.
4. Manual check on desktop and iPad-size viewport.

## Risks

1. Context restore race with initial app loading.
2. Existing modal open paths may conflict with deep-link open timing.
3. Message/email compose behavior differs by platform.

## Definition of Done

1. Acceptance criteria all pass.
2. No regressions to existing modal and explorer behavior.
3. Sprint notes added to `.claude/TODO.md` and relevant docs.
