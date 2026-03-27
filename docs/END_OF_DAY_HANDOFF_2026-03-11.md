# End-of-Day Handoff — 2026-03-11

## Purpose

This document captures the current state of the collaborator UX work, collections/share product decisions, 3DE observations, server-launch clarification, and the exact next steps so work can resume cleanly even if the chat thread loses context.

## Current status

### Completed checkpoint commits

- `944cac8` — `checkpoint: collaborator ux and media repair groundwork`
- `6f4a453` — `add review-server runbook and workspace review doc`

### Main areas completed in the codebase

- collaborator browse/tree restrictions
- collaborator modal simplification toward question-first workflow
- collections provenance corrections (`CB:` collections are AI-derived representative sets, not human-curated)
- 3DE collaborator control suppression (`Looks`, `Thumbs` hidden for collaborators)
- 3DE live-burst / settle behavior and busy-state improvements
- review-vs-3DE workflow separation
- explicit backlog and checkpoint documentation

## Critical clarification about DevLauncher

A wrong assumption was corrected today.

### What DevLauncher actually uses

DevLauncher is the separate menu bar app in:

- `/Users/minime/Projects/Agent Manager`

It does **not** use Inspirations' `.claude/launch.json`.

It reads project definitions from:

- `/Users/minime/Projects/Agent Manager/config/projects.json`

Relevant code:

- `/Users/minime/Projects/Agent Manager/src/devlauncher/config.py`
- `/Users/minime/Projects/Agent Manager/src/devlauncher/process_manager.py`
- `/Users/minime/Projects/Agent Manager/src/devlauncher/app.py`

### How DevLauncher works

1. Reads `config/projects.json`.
2. Lists projects in the menu bar.
3. Uses TCP port checks every 5 seconds for green/red state.
4. Starts processes with `subprocess.Popen(..., shell=True, cwd=<project.path>, preexec_fn=os.setsid)`.
5. Stops only processes DevLauncher started itself.
6. Logs to `/tmp/devlauncher/<project-name>.log`.

### What the Inspirations review launcher really is

The review/start path is the existing `Inspirations` entry in DevLauncher, defined in:

- `/Users/minime/Projects/Agent Manager/config/projects.json`

That entry already runs without `--reload`.

This is the correct launch path for review.

### Why this mattered

Earlier reasoning treated `.claude/launch.json` as if DevLauncher consumed it. That was incorrect. The permanent fix for review startup is to rely on DevLauncher's real `Inspirations` project entry and evaluate stability using that path.

## Important operational gap still open

### Server stability / pre-share hardening

The Inspirations server on port `8001` is not yet considered operationally stable enough for collaborator sharing.

Observed behavior:

- one-shot local curl checks can succeed briefly
- the process can still disappear later
- browser-visible / DevLauncher-visible uptime is not yet reliable enough

### Correct standard for saying "server is up"

The server is only considered up if all of these are true:

1. DevLauncher shows `Inspirations` running.
2. Browser loads `http://127.0.0.1:8001/`.
3. `http://127.0.0.1:8001/api/me` returns `200`.

A one-shot shell `curl` is not sufficient evidence by itself.

### Supporting files

- `/Users/minime/Projects/Inspirations/docs/REVIEW_SERVER_RUNBOOK_2026-03-11.md`
- `/Users/minime/Projects/Inspirations/tools/check_review_server.sh`

## Collaborator UX state

### Implemented

- collaborators default into shared collections scope
- collections tree expanded by default for collaborators
- collaborators do not see:
  - `Other / Non-Home-Design`
  - `Irrelevant / Discarded`
- collaborator asset/source browsing excludes effective tracks:
  - `irrelevant`
  - `home_maintenance_diy`
- `+ New Collection` is owner-only
- collaborator-only browse unlock affordances removed
- collaborator modal is question-oriented
- collaborator cannot write shared general notes
- collaborator modal prompt above image encourages question placement
- collaborator annotations are question-only
- 3DE `Looks` hidden for collaborators
- 3DE `Thumbs` hidden for collaborators

### Still open on collaborator view

- collection-scoped share UI
- collaborator modal header/share redesign
- modal next/prev
- question flow polish:
  - Enter submit/close
  - Shift+Enter newline
  - confirm delete
  - numbering
- pre-share hardening / stable review startup

## Neutral mode rule

A product rule was established:

- unauthenticated neutral mode must never expose more than collaborator mode
- neutral visibility must be less than or equal to collaborator visibility
- especially for:
  - hidden
  - irrelevant
  - maintenance
  - non-home content

## Collections product model

A clearer model was established today.

### Collection intents

Every collection should have explicit intent:

- `shared`
- `working`

### Shared collections

Shared collections are for human collaboration.

Rules:

- every shared collection must name a collaborator
- questions are always enabled for shared collections
- collaborators should not see working collections

Primary use:

- Leslie (most likely) or Jim makes a named collection for a collaborator
- the collaborator receives a magic link
- the collaborator can review that collection and ask questions in context

Examples of audiences:

- interior designer
- cabinet maker
- tile person
- other specific role/person involved in the home project

A separate formal role field may be optional later, but a named person is the minimum requirement.

### Working collections

Working collections are internal workflow objects.

Primary use:

- debugging
- curation review
- understanding the corpus
- improved categorization
- internal construction concern review

### Construction collections rule

For now, construction-track collections should be treated as `working` collections, not style-side shared artifacts.

## Construction UX/product direction

A separate model emerged for construction.

### Primary construction users

1. Jim + Leslie
   - understand the concern corpus
   - map concerns into:
     - checklist items
     - contract/spec requirements
     - product selections
     - vetting questions
     - inspection points

2. Construction administrator
   - help ensure work is done to spec
   - help determine what must be communicated to subcontractors
   - support vetting and inspection communication

### Key conclusion

Construction is not primarily a style-style collaborator collection problem.

It is primarily a:

- concern understanding
- concern organization
- migration-to-checklist/spec
- execution-readiness

workflow.

Therefore:

- do not force construction into the same style-side shared-collection UX
- construction needs its own dedicated UX/workflow sprint

## 3DE conclusions

### What was observed

- turning on all `Subject Type` attractors at once distorted the map but was hard to interpret
- turning them off made migration toward remaining poles easier to see

### Interpretation

This appears to be two things at once:

1. expected attractor behavior when all poles of one axis are active at the same time
2. a real sign that the current `Subject Type` enumeration may not be semantically strong enough for exploratory use

### Refined issue statement

The real issue is not just “3DE felt odd.”

It is:

- refine the `Subject Type` enumeration itself
- clarify the meaning of each value
- evaluate whether the current values are genuinely useful for exploration and understanding

This is now explicitly tracked in the UX backlog.

## Collections/share workflow sprint direction

A dedicated collections/share sprint is needed.

That sprint should cover:

- collaborator entry behavior
- collection tree defaults
- collection-scoped sharing
- share-link UX
- the distinction between shared vs working collections
- the neutral-vs-collaborator visibility rule

Important nuance:

- backend/URL support for collection-scoped links already exists via `collection_id`
- what is missing is the productized UX around it

## Untracked workspace review

A doc was created for unrelated untracked files that were left out of the checkpoint:

- `/Users/minime/Projects/Inspirations/docs/UNTRACKED_WORKSPACE_REVIEW_2026-03-11.md`

You explicitly said review of that doc is delayed for now.

## Stray file note

This untracked media file exists at repo root:

- `/Users/minime/Projects/Inspirations/The Hidden Cost of Union Power： Rich Contracts and Layoffs Down the Road [865574612774175].f1440144380661259a.m4a`

It was discovered via `git status --short`.

## Current recommended next-step order

1. Dedicated collections/share workflow sprint.
2. Pre-share hardening pass if DevLauncher-launched `Inspirations` still proves unstable.
3. Continue UX sprint:
   - collaborator modal/share redesign
   - modal next/prev
   - `Subject Type` refinement for 3DE/exploration
4. Construction-specific UX/workflow sprint.

## Immediate restart point for next session

When work resumes:

1. start `Inspirations` from DevLauncher
2. verify server-up state by the full standard (DevLauncher + browser + `/api/me`)
3. begin the collections/share workflow sprint from the now-settled rules above
