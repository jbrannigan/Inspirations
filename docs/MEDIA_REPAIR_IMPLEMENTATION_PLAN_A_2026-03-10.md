# Media Repair Implementation Plan A

Date: March 10, 2026
Project: Inspirations
Scope: Implement the next-phase workflow for repairing misleading, placeholder, repeated, or low-information media while preserving provenance and supporting human acceptance.

## Purpose

The interactive filtering workflow proved that the main remaining problem is no longer top-level track ambiguity.

The main remaining problem is media evidence quality.

Typical failure modes:
- thumbnail is generic, repeated, or non-informative
- thumbnail mismatches the actual source content
- public wrapper pages hide the real meaning, but authenticated source text reveals it
- some Facebook/Pinterest items need source-page text more than they need image replacement
- some reels are better classified from post text than from the visible thumbnail

Workflow `A` is the implementation branch that makes this a first-class system capability instead of an ad hoc review habit.

## Implemented Checkpoint - June 3, 2026

The item modal now has a first-class `Repair media` gallery:

- `Find source media` captures authenticated, post-scoped Facebook/Pinterest evidence.
- The current saved image remains visible for comparison but is never treated as a proposed replacement.
- Captured post images are shown as explicit selectable candidates.
- A `Generated text card` option builds a local PNG from captured post text when text is the best representation.
- `Use selected media` promotes only the human-selected candidate.
- Previously used saved media is recovered from `asset_media_repair_audit` and remains selectable after later source checks, including checks that find no post images.
- `Find source media` opens the gallery immediately and reports searching, images-found, no-images-found, and failure states instead of relying on a disabled cursor.
- Facebook source capture uses the named authenticated Playwright/Chrome session `media-repair-auth`. Safari and Jim's ordinary Chrome windows are not visible to the capture tool.
- Facebook post/comment modals are scrolled during the final extraction pass; lazy-loaded comment media is offered as `Scrolled comment image N`.
- Generated cards use the normal local storage and thumbnail pathways, so Grid, detail view, and standalone collection PDF export use them without app-dependent links.
- Promotion records provenance in `asset_field_provenance`.
- Promotion archives stale machine evidence in `asset_media_repair_audit`, then clears old AI summaries, AI labels, embeddings, derived classification rows, and source-link QC rows for that asset.
- Human overrides, annotations, notes, and non-AI labels are preserved.
- Explorer PCA cache keys include embedding vectors, so refreshed embeddings produce refreshed coordinates.

Important capture rule:
- never borrow a visually prominent image from another feed post or unrelated sidebar region
- nearby and scrolled comment images may be offered when they are inside the authenticated source post/comment modal
- a text-only anchored post should produce useful text evidence with no unrelated image candidate

### Refresh after promotion

Use `Admin` -> `Repaired Media Search Evidence` -> `Refresh Search Evidence` after accepting one or more repairs. The batch action is deliberate: accepting replacement media remains immediate and local, while Gemini work runs only when requested. Failed items stay in the pending queue.

The Admin action applies these recipes automatically.

Generated text card:

```bash
PYTHONPATH=src python3 -m inspirations ai embed --asset-id <asset-id>
PYTHONPATH=src python3 -m inspirations curation track-gate-v2
PYTHONPATH=src python3 -m inspirations curation axis-infer-v2
```

Selected source image:

```bash
PYTHONPATH=src python3 -m inspirations ai tag --provider gemini --asset-id <asset-id>
PYTHONPATH=src python3 -m inspirations ai embed --asset-id <asset-id>
PYTHONPATH=src python3 -m inspirations curation track-gate-v2
PYTHONPATH=src python3 -m inspirations curation axis-infer-v2
```

The CLI commands remain useful as a manual fallback. The Admin action also regenerates the heuristic track and axis snapshots once per batch rather than once per repaired item.

## Goals

1. Capture better source evidence automatically where possible.
2. Make candidate replacement evidence visible in the modal.
3. Keep capture separate from promotion.
4. Preserve provenance for both the current media and any proposed replacement.
5. Support batch handling of repeated low-information thumbnail classes.
6. Feed repaired source evidence back into classification cleanly.

## Non-Goals

1. Do not auto-replace asset media without a human acceptance step.
2. Do not rebuild the classification taxonomy again.
3. Do not make this dependent on AppleScript or fragile browser scripting.
4. Do not require new Python dependencies.

## Existing Building Blocks

Already in place:
- authenticated Playwright profile workflow for Facebook/Pinterest source capture
- `asset_source_link_enrichment` table
- captured fields:
  - `page_title`
  - `text_excerpt`
  - `hero_image_url`
  - `hero_text_excerpt`
- modal `Source Candidate` panel
- `Media issue` review control
- hero-image promotion plumbing
- track override persistence
- authenticated Facebook post-text capture for hard cases
- reusable Facebook reel downloader with progressive fallback

This means workflow `A` is an implementation-completion problem, not a greenfield design problem.

## Proposed Architecture

### Phase 1. Candidate evidence as first-class modal content

Deliverable:
- make source candidate evidence a primary part of the modal, not an auxiliary panel

Implementation:
- show current stored image and candidate image side by side when available
- show current title and captured source text together
- visually separate:
  - `Current asset media`
  - `Captured source candidate`
  - `Human decision`

Success criteria:
- a reviewer can decide without opening external pages in most cases
- `Media issue` and track decision are visible in one place

### Phase 2. Capture workflow normalization

Deliverable:
- one capture path for hard Facebook/Pinterest items

Implementation:
- keep the persistent authenticated Playwright profile as the standard capture path
- treat source capture as evidence generation, not classification itself
- normalize captured result into:
  - page text
  - hero image candidate
  - final resolved URL
  - capture method
  - fetch status

Success criteria:
- no special-case manual shell steps are required to capture candidate evidence
- hard Facebook/Pinterest items can be refreshed repeatably

### Phase 3. Promotion workflow

Deliverable:
- clean human acceptance of candidate media

Implementation:
- modal buttons:
  - `Keep stored image`
  - `Use candidate image`
  - `Trust title/source only`
- `Use candidate image` should:
  - download and store the image through existing storage/original pathways
  - generate thumbnail(s)
  - preserve provenance in `asset_field_provenance`
- `Trust title/source only` should persist a media-reliability marker without forcing image replacement

Success criteria:
- accepted candidate images are visible in the corpus immediately
- provenance remains auditable
- no silent destructive media overwrite happens

### Phase 4. Repeated low-information thumbnail handling

Deliverable:
- batch resolution of known placeholder/reused thumbnail classes

Implementation:
- add thumbnail signature clustering for repeated low-information images
- define named classes such as:
  - `facebook_group_logo`
  - `facebook_anonymous_avatar`
  - `facebook_generic_placeholder`
  - future Pinterest placeholder classes
- allow one decision to propagate media-reliability semantics across a cluster

Success criteria:
- reviewers do not have to label the same meaningless thumbnail over and over
- the system stops treating placeholder images as content evidence

### Phase 5. Classification feedback loop

Deliverable:
- repaired source evidence improves future classification automatically

Implementation:
- ensure classification consumes latest source text and promoted media consistently
- keep track overrides distinct from improved machine evidence
- rerun track/axis inference after meaningful media repair batches

Success criteria:
- fewer items require manual track overrides over time
- repeated review burden drops

## Data Model Guidance

### Keep using current structures

Use existing tables rather than adding premature schema:
- `asset_source_link_enrichment`
- `asset_overrides`
- `asset_field_provenance`
- `asset_ai`
- `asset_labels`

### Add only if needed later

Possible future additions if current structures become awkward:
- named `thumbnail_class`
- candidate acceptance/rejection history table
- cluster-level media decision table

These are not required to begin workflow `A`.

## UX Requirements

The modal should support these decisions directly:
- what is the correct top-level track?
- is the stored image useful?
- should the candidate image replace it?
- should the title/source be trusted without image replacement?

Important UX rule:
- media reliability and track are different questions and must remain separate controls

## Priority Backlog Inside Workflow A

### A1. Make source candidate comparison primary in the modal
Highest value.

### A2. Make `Trust title/source only` a clearly visible first-class acceptance path
Also high value.

### A3. Add cluster handling for repeated placeholder thumbnails
Medium-high value.

### A4. Add batch candidate refresh for unresolved Facebook/Pinterest items
Medium value.

### A5. Add a small archive/reopen mechanic for completed media-repair review queues
Medium value.

## Risks

1. Facebook/Pinterest markup can change.
- Mitigation: keep capture logic shallow and evidence-oriented.

2. Hero image may not be the real semantic value.
- Mitigation: prioritize captured post/source text above the image.

3. Some items are better left as `Trust title/source only`.
- Mitigation: do not force image promotion.

4. Batch clustering can over-generalize.
- Mitigation: require named cluster review before propagation.

## Success Criteria For Workflow A

Workflow `A` is successful when all of these are true:

1. A reviewer can resolve hard media cases mostly from the modal.
2. Candidate evidence capture is repeatable and authenticated.
3. Image replacement is optional, auditable, and reversible.
4. Repeated placeholder thumbnails can be handled in batches.
5. Future classification improves because repaired evidence is being consumed.

## Recommended First Implementation Slice

Do this first:
1. elevate current/candidate comparison in the modal
2. finalize `Trust title/source only` as the normal non-replacement outcome
3. use the authenticated source capture path to populate that modal state reliably

Do not start with clustering first.

Reason:
- modal comparison and acceptance is the shortest path to immediate user value
- clustering is useful, but it should sit on top of a stable per-item repair workflow

## Bottom Line

The review workflow is done.

Workflow `A` is the correct next branch because it turns the remaining problem into an implementation problem with clear scope:
- capture better evidence
- present it clearly
- let a human accept or reject candidate media
- feed accepted evidence back into the corpus
