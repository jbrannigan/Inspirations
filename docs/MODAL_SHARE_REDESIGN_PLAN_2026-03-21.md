# Modal / Share Redesign Plan — 2026-03-21

Status: Proposed for review before implementation
Project: Inspirations

## Why this needs its own pass

The modal is currently carrying too many responsibilities at once:

1. asset viewing
2. owner editing
3. collaborator questions
4. sharing/export actions
5. navigation through a scoped set
6. review-only controls in some contexts

That overload shows up in two ways:

- owner mode feels powerful but crowded
- collaborator mode still inherits too much of the owner mental model

The goal of this redesign is not to remove capability. It is to make the current capability legible by role and context.

## Design goals

### Primary

- collaborator mode should feel like a focused conversation around a collection item
- owner mode should remain capable, but more organized
- sharing should feel native and compact, not like a toolbar bolted on later
- modal navigation should feel like browsing within a scoped set, not jumping around the app

### Secondary

- reduce header clutter
- reduce ambiguous controls
- make the difference between `questions` and `annotations` visible, not just conceptual
- keep print/share decisions aligned with the eventual export workflow

## Product rules already agreed

### Collaborator modal

- collaborators ask questions, not generic annotations
- general notes are read-only for collaborators
- shared collections always have questions enabled
- collaborator visibility must remain narrower than owner visibility

### Owner modal

- owner retains full editing capability
- owner can still annotate, manage notes, and inspect metadata
- owner complexity is acceptable for now if it is organized better

## Proposed modal structure

```text
Modal
  Header
    Title block
    Identity / context
    Navigation
    Share actions
    Close

  Main body
    Left: image / media stage
    Right: contextual information + questions / annotations

  Footer (optional, context-dependent)
    owner-only review actions
```

## Header redesign

### Current problem

The header is visually overloaded:

- title
- copy id
- source links
- share buttons
- prev/next
- close

Everything competes at the same level.

### Proposal

Split the header into three conceptual groups.

#### 1. Title block

Contains:

- content-kind badge
- title
- short metadata line
- `Viewing as ...` chip when relevant
- source links

Remove from this area:

- `Copy ID`

#### 2. Navigation group

Contains:

- `Prev`
- position indicator (`7 of 52`)
- `Next`

This group should read as browsing state, not utility.

#### 3. Share group

Compact and right-aligned.

Target direction:

- `Copy Link`
- `Email`
- `Message`
- `Print`

Possible final visual treatment:

- icon-first compact actions
- or a single `Share` button opening a small action menu

Important: this is the part that should be reviewed before implementation.

## Copy ID decision

Recommendation:

- remove `Copy ID` from the main modal header
- keep asset ID visible in owner context, but as metadata rather than a top-level action
- preferred action is `Copy Link`

Reason:

- `Copy ID` is operationally useful, but not a primary user task
- `Copy Link` is the correct general-purpose share action
- this recovers space and reduces confusion in collaborator mode

## Collaborator right column

### Proposed structure

```text
Questions
  stage prompt above image
  question list below metadata
  read-only notes below, if present
  labels/tags below that
```

### Collaborator-specific rules

- `Questions` heading should remain explicit
- image-stage prompt should stay above the image
- prompt should mention:
  - click to ask
  - `Enter` saves
  - `Shift+Enter` adds a new line
- questions should be numbered
- deleting a question confirms first

### Notes placement

Move read-only general notes higher than they are now, but still visually separate from collaborator questions.

Reason:

- notes are context
- questions are interaction
- collaborators should not mistake notes for an editable field

## Owner right column

### Proposed structure

```text
Owner context
  Notes
  Annotations
  Labels
  Source/title metadata
  Review/editor controls (when relevant)
```

Owner mode can remain denser than collaborator mode, but sections should be visually separated.

## Print and share direction

### Current issue

Current print/share is a mix of old and new assumptions.

### Proposal

Short term:

- keep current buttons while redesigning the header
- prefer `Copy Link` as the primary generic action

Later:

- add a formatted share/export view
- let print come from that formatted representation when appropriate
- annotations/questions should be eligible for inclusion there

## Navigation behavior

### Proposed rule

When modal is opened from a scoped set:

- prev/next remain inside that scope
- close returns to the scoped browsing surface

This is already the interaction model we are moving toward and should remain.

## Visual language

### Questions vs annotations

Keep them visually distinct.

Suggested approach:

- `Questions` heading uses the same orange family as question markers
- `Annotations` heading uses the annotation color family
- question numbering should appear in both the list and the image markers

## Recommended implementation order

1. Header cleanup
   - remove `Copy ID`
   - reorganize title / nav / share groups
2. Collaborator right-column simplification
   - read-only notes placement
   - labels heading clarity
3. Share action compaction
   - icons or compact menu
4. Print/export follow-up
   - later sprint slice

## Decision needed from Jim before implementation

1. Should share be:
   - compact icon row
   - or single `Share` menu/button
2. Should `Email` and `Message` remain explicit first-class actions in the header, or move under `Share`?
3. Should read-only notes for collaborators move above the question list, or stay below it as secondary context?

## Recommendation

My recommendation is:

- compact navigation row
- a single `Share` button/menu instead of four equal-weight buttons
- `Copy Link` as the default first action inside it
- collaborator notes above the question list, but visually subdued

That is the cleanest path without weakening owner capability.
