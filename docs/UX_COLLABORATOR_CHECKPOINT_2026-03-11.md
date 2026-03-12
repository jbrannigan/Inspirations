# UX Collaborator Checkpoint — 2026-03-11

## Scope

This checkpoint captures the collaborator-facing UX cleanup, adjacent 3DE control cleanup, and known pre-share hardening gaps as of 2026-03-11.

## Implemented

- Collaborators default into shared collections scope.
- The Collections tree is expanded by default for collaborators.
- Collaborators do not see `Other / Non-Home-Design` or `Irrelevant / Discarded` branches.
- Collaborator asset/source browsing excludes effective tracks `irrelevant` and `home_maintenance_diy`.
- `+ New Collection` is owner-only.
- Collaborator-only browse unlock affordances were removed.
- Collaborator modal is question-oriented:
  - shared general notes are read-only/non-writable
  - the prompt to ask a question is promoted above the image
  - collaborator annotations are question-only
  - the annotations/questions section is explicitly labeled
- `Copy ID` sizing bug in the modal was fixed.
- 3DE collaborator controls were reduced:
  - `Looks` is owner-only
  - `Thumbs` toggle is owner-only
- 3DE now uses a short live burst with auto-settle and re-arms on relevant scope/attractor changes.
- Review mode and 3DE are treated as separate workflows.
- Sidebar/source/classification/collections structure was partially reorganized to reduce conceptual mixing.
- `CB:` collections are explicitly treated as AI-derived representative sets, not human-curated sets.

## Captured But Not Yet Implemented

- Dedicated collections/share workflow sprint.
- Collection-scoped share UI, even though `collection_id` links already work at the URL level.
- Collaborator modal header/share redesign.
- Modal next/previous navigation.
- Question flow polish:
  - Enter to submit/close
  - Shift+Enter for newline
  - confirm delete
  - numbering
- Construction-specific UX split.
- Refinement of `Subject Type` enumeration and meaning/value for exploration and understanding.
- Control-panel chip relevance based on current track/scope.
- Scan import hardening for blank separator pages and cleanup of existing artifacts.

## Important Operational Gap

The Inspirations server on port 8001 is not yet operationally stable enough for collaborator sharing.

Observed behavior:

- one-shot local `curl` checks can succeed immediately after launch
- the server process can still disappear shortly after
- browser-visible/DevLauncher-visible uptime is therefore not reliable yet

This needs a pre-share hardening pass covering:

- durable local process management
- reliable restart behavior
- crash/shutdown logging
- validation using browser-visible and DevLauncher-visible criteria, not only local curl success

## Recommended Next Start Point

1. Pre-share hardening for the 8001 server.
2. Dedicated collections/share workflow sprint.
3. Collaborator modal/header/share simplification.
4. `Subject Type` refinement pass for 3DE and taxonomy.
