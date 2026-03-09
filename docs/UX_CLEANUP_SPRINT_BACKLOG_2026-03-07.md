# UX Cleanup Sprint Backlog - 2026-03-07

## Purpose

This document holds UX comments separately from the classification work.

Important rule:

- `User Intent` sections are meant to preserve Jim's direction as faithfully as possible
- `Assistant Suggestions` sections are optional interpretations or design proposals and are not the same thing as Jim's instruction

## Scope separation

- classification work decides what the corpus means
- UX work decides how the app should support browsing, review, and reporting workflows

## User Intent

Jim said:

- "What I said in my remarks."

### 1. Review mode and sidebar behavior

Jim's direction:

- the sidebar status items:
  - `All`
  - `Pending`
  - `Keepers`
  - `Hidden`
  - `Needs comment`
  - `Flagged`
  should show up only under review
- in review mode, the rest of the browse tree should go away so it cannot be clicked on and interfere with the items that have been filtered into the canvas for review
- the hidden branch should move into the review scope
- hidden needs to show all of the categorizations of the hidden
- once review mode exits, the status part of the sidebar should go away, including the `Pending`, `Keepers`, `Hidden`, `Needs comment`, and `Flagged` nodes
- counts should be consistent

### 2. Browse-tree organization outside review

Jim's direction:

- outside review mode, the remaining tree needs better organization
- currently collections, data sources, track, and other concepts are mixed together
- suggestions are needed, but this belongs clearly in the UX sprint backlog

### 3. Grid view, sidebar, and 3D Explorer should be harmonized

Jim's direction:

- harmonize the 3D Explorer panel with the sidebar and with grid view
- the easiest path may be to give grid view the control panel as well
- the control panel comes after the revised classification work

### 4. Current product sequence

Jim's direction:

- right now the app is evolving while the collection is being curated into a more stable focus
- after that stabilizes, it may return to the earlier idea where Leslie can highlight things that need to go into a report
- that report-oriented workflow should be delayed for now

### 5. Construction may need a different workflow from style review

Jim's direction:

- construction concerns and construction systems may need a completely different modality
- they do not have the same junk problem as the style side
- Jim wants to go through that material in more detail and separately
- there probably will not be anything like the current keeper/pending review workflow there
- a different solution is needed for that track

### 6. One-by-one review and modal should be the same workflow

Jim's direction:

- one-by-one review and the modal should be one and the same
- the one-by-one-specific additions should just be added onto the modal
- there should be one review workflow, not two separate ones

### 7. Rating / reaction consistency

Jim's direction:

- current reactions are inconsistent:
  - hearts / `Love it`
  - stars
- this needs to become consistent
- there may need to be a `1-5 star` style model, or something along those lines
- Jim likes `Love it`, but the system still needs consistency

### 8. Grid-review consistency

Jim's direction:

- the review behavior in grid view needs to be checked against one-by-one review
- it should be consistent with whatever is decided for the unified modal / one-by-one workflow

### 9. Design workshop usage

Jim's direction:

- these UX points should be part of a design workshop between the two of us

### 10. Review ergonomics in one-by-one mode

Jim's direction:

- the review screen needs to show the asset ID so an item can be referenced precisely in discussion
- if Jim goes back after making a decision, the typed `Reason (optional)` text should still be there in the UX
- `Irrelevant` should not feel like two different actions at once
- if there is a dedicated `Mark irrelevant` button, the dropdown should not force Jim to think about whether he also needs to choose `Irrelevant` there

## Assistant Suggestions

This section is optional design thinking only. It is not a record of Jim's intent.

### 1. Safe documentation rule for future UX capture

Recommendation:

- keep future UX notes in two layers:
  - `User Intent`
  - `Assistant Suggestions`

This avoids accidentally turning a user thought into a design decision.

### 2. Suggested workshop questions

Possible workshop questions:

1. what exactly appears in the sidebar during review mode?
2. what, if anything, remains accessible outside the review-filtered scope while review is active?
3. what is the top-level browse IA outside review mode?
4. what is the shared control model across grid and 3D?
5. does construction get its own dedicated mode?
6. what is the final rating model?

### 3. Existing fixed operational issue

Already fixed:

- one-by-one review count behavior now keeps live scope counts and sidebar counts in sync during hide/undo

This is included here only so it is not mistaken for an unresolved UX item.
