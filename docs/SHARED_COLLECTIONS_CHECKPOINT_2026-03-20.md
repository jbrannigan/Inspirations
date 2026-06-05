# Shared Collections Checkpoint — 2026-03-20

> Legacy note (2026-05-27): shared live collections and collaborator links are
> retired from the active product. Current designer handoff is standalone PDF
> export for one local collection at a time.

## Scope

This checkpoint captures the current state of shared collection creation, sharing, access enforcement, and collaborator landing behavior as of 2026-03-20.

## Implemented

- Collections now support explicit intent in the working model:
  - `working`
  - `shared`
- Shared collections can now be assigned to multiple named collaborators.
- The sharing model is normalized through `collection_shares`, with `collections.shared_actor_id` retained as a compatibility bridge.
- Owners have a dedicated `Share Collections` workflow separate from `Manage Visibility`.
- Share links are generated from saved state only. Draft collaborator selections do not create live links.
- Shared collection access is enforced server-side for:
  - context resolution
  - collection-scoped asset browsing
  - collection-scoped asset-id browsing
- Shared links establish collaborator identity clearly through `Viewing as ...` chips in browse and modal context.
- Shared-link landing now focuses the linked collection immediately and suppresses generic browse during the focused collaborator session.
- Collaborators can still opt into broader collaborator browsing through `Show other shared collections`.

## Product Rules Now Reflected in Code

- Every collection has explicit intent: `working` or `shared`.
- Shared collections are meant for named collaborators, not anonymous neutral browsing.
- Questions are always enabled for shared collections.
- Collaborators do not see working collections.
- Neutral visibility must not exceed collaborator visibility.

## What Still Feels Rough

- The focused shared-collection session still uses too much sidebar real estate for too little information. A compact shared-session sidebar is the right next refinement.
- The owner `Share Collections` UI is functional but still visually awkward and needs a more deliberate layout.
- Shared collection summaries in owner mode should better communicate who a collection is shared with and why.

## What Remains Outside This Slice

- Pre-share hardening for the 8001 review server under DevLauncher.
- Collaborator modal/header/share redesign.
- Modal next/previous navigation.
- Question flow polish (`Enter` vs `Shift+Enter`, delete confirmation, numbering).
- Construction-specific UX, which remains a separate workflow from style-side collection sharing.

## Recommended Next Steps

1. Pre-share hardening for the review server.
2. Polish the owner `Share Collections` workflow.
3. Replace the full sidebar in focused shared-collection mode with a compact shared-session sidebar.
4. Continue collaborator modal/share cleanup.
