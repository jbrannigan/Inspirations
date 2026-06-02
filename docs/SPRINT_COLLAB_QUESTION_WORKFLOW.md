# Sprint Spec: Collaborator Question Workflow

> Legacy note (2026-05-27): collaborator question workflow is retired from the
> active product. Image annotations remain local corpus/QC notes.

Status: Sprint-ready
Date: 2026-02-28
Owner: Product + Builder
Dependency: `docs/SPRINT_COLLAB_CONTEXT_LINK.md`

## Goal

Provide an in-app thread panel where authenticated collaborators can ask and respond to questions tied to a specific shared item context.

## Locked Decisions

1. Question workflow is in-app (not email-thread-only).
2. Question context must be unambiguous and tied to shared item context.
3. Context uses fixed `item_id` anchor and `collection_id` scope.

## In Scope (v1)

1. Per-item question threads in collection context.
2. Create question, reply, and view thread history in-app.
3. Thread panel visible from item detail modal.
4. Role-aware permissions for create/reply/update status.

## Out of Scope (v1)

1. Email notifications.
2. Mentions/assignments.
3. Advanced moderation tools.
4. Rich text, attachments, or reactions.

## Thread Model (v1)

Thread scope key: `collection_id + item_id`

- Multiple top-level questions allowed per scoped item.
- Each question supports replies (one-level threaded conversation).
- Thread status: `open` or `resolved`.

## Data Model (SQLite)

### `question_threads`

- `id` TEXT PK
- `collection_id` TEXT NOT NULL
- `item_id` TEXT NOT NULL
- `created_by_actor_id` TEXT NOT NULL
- `title` TEXT NOT NULL
- `status` TEXT NOT NULL DEFAULT `open` (`open|resolved`)
- `created_at` TEXT NOT NULL
- `updated_at` TEXT NOT NULL

Indexes:
- `(collection_id, item_id, updated_at desc)`
- `(status, updated_at desc)`

### `question_messages`

- `id` TEXT PK
- `thread_id` TEXT NOT NULL
- `author_actor_id` TEXT NOT NULL
- `body` TEXT NOT NULL
- `parent_message_id` TEXT NULL
- `created_at` TEXT NOT NULL
- `updated_at` TEXT NOT NULL

Indexes:
- `(thread_id, created_at asc)`

## Permissions (v1)

1. Any authenticated collaborator can:
   - create thread,
   - reply to thread,
   - edit/delete own messages.
2. Owner/Jim can:
   - do all collaborator actions,
   - edit/delete any message,
   - mark thread resolved/reopen.

## API Endpoints (v1)

1. `GET /api/questions?collection_id=<cid>&item_id=<aid>`
   - list threads + message summaries for context.
2. `POST /api/questions`
   - create thread with first message.
3. `GET /api/questions/<thread_id>`
   - full thread detail + messages.
4. `POST /api/questions/<thread_id>/reply`
   - add reply message.
5. `PATCH /api/questions/<thread_id>`
   - update thread status (`open|resolved`).
6. `PATCH /api/questions/messages/<message_id>`
   - edit message body (permission gated).
7. `DELETE /api/questions/messages/<message_id>`
   - soft delete message (permission gated).

All endpoints JSON-only.

## Frontend Requirements

1. Add `Questions` panel in detail modal.
2. Panel shows:
   - list of open/resolved threads for current item context,
   - message timeline with actor identity,
   - compose box for new thread and replies.
3. Context chip always visible in panel:
   - collection name,
   - item title/id.
4. Thread status controls visible to owner/Jim.

## UX States

1. Empty state: `No questions yet for this item.`
2. Loading state for thread fetch.
3. Error state with retry action.
4. Resolved thread visually distinct.

## Implementation Plan

1. DB migration for `question_threads` and `question_messages`.
2. Store layer + server endpoints.
3. Frontend panel skeleton + data loading.
4. Compose/reply/status actions.
5. Permission guards in UI and backend.
6. Regression and role-behavior tests.

## Acceptance Criteria

1. Collaborator can create a question on item context.
2. Collaborator and owner/Jim can reply in same thread.
3. Owner/Jim can resolve and reopen threads.
4. Thread context always shows correct collection + item anchor.
5. Unauthorized edits/deletes are blocked.
6. Deleted/edited messages show clear state in thread timeline.

## Test Plan

1. Unit tests for store operations and permission checks.
2. API tests for create/reply/edit/delete/status endpoints.
3. UI tests for panel rendering and role-based controls.
4. Manual validation with owner and collaborator actors.

## Risks

1. Modal complexity growth (questions + annotations in same surface).
2. Ambiguity if item is removed from collection during active thread usage.
3. Query performance on high message volume without proper indexes.

## Definition of Done

1. Acceptance criteria pass.
2. 80%+ coverage on question store logic.
3. No regressions in modal/annotation core workflows.
