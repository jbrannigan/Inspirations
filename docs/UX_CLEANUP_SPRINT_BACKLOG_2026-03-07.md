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
- Collections/share workflow needs its own focused sprint: collaborator entry, collection-scoped sharing, share-link UX, and collection tree defaults should be treated as one coherent workflow rather than piecemeal fixes.
- Collections intent model: every collection should have explicit intent, either `shared` or `working`.
- Shared collections rule: every shared collection should name a collaborator at minimum. A separate formal role field may be optional later, but a named person is required.
- Shared collections rule: questions are always enabled. Sharing a collection implies the collaborator question workflow.
- Shared collection links must be generated from persisted saved state only; draft collaborator selections should not produce live share links.
- Shared collection links need explicit access enforcement and clearer identity context (`Viewing as …`) so collection scope and actor scope cannot drift apart.
- Collaborator visibility rule: collaborators should not see `working` collections.
- Construction collections rule: for now, collections on the construction track are `working` collections only, used for curation, review, and improved categorization rather than the style-side sharing workflow.
- Collections/share rule: unauthenticated neutral mode must never expose more than collaborator mode. Neutral visibility should be less than or equal to collaborator visibility, especially for hidden, irrelevant, maintenance, and non-home content.
- Pre-share hardening pass: Inspirations server on port 8001 needs durable local process management, reliable restart behavior, and crash/shutdown logging before collaborator sharing is treated as stable.
- 3DE `Subject Type` needs review as both UX and taxonomy: refine the `Subject Type` enumeration itself, clarify the meaning of each value, and evaluate whether the current values are actually useful for exploration and understanding. Turning on all subject-type attractors is hard to interpret, which suggests the current enumeration may be too coarse, overloaded, or not semantically valuable enough for exploratory use.
## Collaborator Modal Review Notes (2026-03-11)

Jim review notes for collaborator-mode modal UX. These should be treated as direct UX requirements/input, not inferred assistant interpretation.

- Sidebar/tree in collaborator mode is still confusing around out-of-context items, hidden behavior, and the `Browse more from Leslie's collection` entry. `Collection` is overloaded and post-click behavior is confusing.
- Share bar should be graphically tightened. Prefer small icons in the upper right, aligned with common UX patterns.
- Collaborator annotations should likely be simplified to questions only. The full annotation workflow is too heavy for collaborators. If they ask a question and then email/message, that question should be included.
- In the annotation box, `Enter` should close the box; `Shift+Enter` should insert a line break.
- Add a visible section title for the labels/tags box in the modal UX. `Labels` is acceptable; the core issue is that the box currently has no visible name.
- Rework print/share. Current print target is weak. Likely direction: formatted share/export using the OS/browser native share pattern, eliminate the separate share bar, and likely replace `Copy ID` with `Copy Link` near the title. This should recover modal header space.
- Email should support a default address or otherwise defer to the OS/browser-native sharing pattern.
- Deleting questions should require confirmation.
- Printed/formatted share should likely include annotations/questions.
- Questions should be numbered, even if questions stop being freeform annotations.
- Add next/previous browse buttons in the modal with a clear exit path; current `X` close behavior is overloaded.
- Reduce the visual budget of the tags box. One or two lines is enough after curation, since `more...` already exists.
- The general `Notes` box could move higher in the modal and remain read-only for collaborators; collaborators should ask questions rather than edit notes.


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
- after the tree reorganization, the deeper harmonization problem is smaller:
  - the sidebar tree should set scope
  - 3D Explorer should explore that scope
  - the 3D chips are attractors, not a second copy of the tree
- 3D Explorer should not normally be used as a review mode
- however, there is a legitimate workflow where Jim may open 3DE from an odd item or outlier in grid view to understand nearby items/context
- this means 3DE is still an investigative tool adjacent to review, even if it is not the main review surface
- active scope/context in 3DE should remain clear

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
- once already in modal context, there may be little reason to make the user switch modes just to review
- `in modal -> in review` is a plausible direction for the unified workflow

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
- in the non-review version of the modal, the `Copy ID` button formatting is wrong and needs UX cleanup
- the modal has grown complicated / "exploded a bit"
- Jim is okay with the current complexity in owner mode for now, but it remains part of the UX cleanup work
- a non-owner/collaborator view of the modal needs explicit review during the UX sprint

### 11. Collections cleanup and trust assignment

Jim's direction:

- make a pass at cleaning up `Collections` as a first-class UX/workflow problem
- correct the trust assignment for collections whose names begin with `CB:`
- `CB:` collections were not human-curated selections by Leslie or Jim
- `CB:` collections were representative sets created from high-confidence descriptions/tagging
- do not present `CB:` collections as the highest-intent or most-refined human choices
- the app needs a clearer distinction between:
  - human-created collections
  - mirrored source collections/boards
  - AI-derived representative collections
- examples of affected collections include:
  - `CB: Kitchen`
  - `CB: Master Bath`
  - `CB: French Colonial Style`
  - `CB: Porches & Outdoor`

Implication for the UX sprint:

- collection provenance/trust needs to be visible enough that users do not mistake AI-derived collections for deliberate human curation
- collection labeling, grouping, or metadata display should make that distinction explicit
- raw `Cohort:` collections need a clearer distinction from cleaned working subsets and excluded provenance subsets; the architect-meeting batch should not read like three equivalent working collections
- `Other / Non-Home-Design` should move out of normal browse mode and into a hidden/archive or clearly review-only surface for owners
- 3DE control panel should only show relevant chips/pills based at minimum on current track, rather than exposing every attractor category in every scope.

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
