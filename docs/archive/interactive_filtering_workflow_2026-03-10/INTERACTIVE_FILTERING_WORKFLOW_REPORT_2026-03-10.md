# Interactive Filtering Workflow Report

Date: March 10, 2026
Project: Inspirations
Scope: Interactive review and filtering work used to stabilize top-level track classification and isolate remaining media-quality problems.

## Purpose

This report documents the human-in-the-loop filtering workflow that was used to improve corpus classification after the v2 taxonomy and provenance work.

The practical goals were:

1. Improve confidence in top-level track discrimination.
   - `Style / Decor`
   - `Construction`
   - `Maintenance / DIY`
   - `Irrelevant`
2. Remove obviously wrong machine classifications through small, focused review exercises instead of one giant review queue.
3. Separate true classification problems from media-quality problems.
4. Reduce the number of items that keep reappearing because of weak or conflicting evidence.
5. Identify the remaining hard cases that need a different workflow, especially Facebook wrapper posts and placeholder/reused thumbnails.

## Review Model

The review workflow evolved from older curation semantics into a classification-specific workflow.

Final review actions used:

- `Keep current`
- `Move`
- `Mark irrelevant`
- optional `Review focus`
  - `Landscaping`
  - `Inspection`
- optional `Reason`

Later in the work, a second dimension was added:

- `Media issue`
  - `Trust title / source`
  - `Thumbnail is placeholder`
  - `Thumbnail mismatches content`

This change matters because some items are not hard to classify by track, but their thumbnail is misleading or useless.

## Success Criteria

Each exercise was considered successful if it did one or more of the following:

1. Closed a bounded review queue completely.
2. Converted a mixed machine bucket into a stable top-level track distribution.
3. Exposed a missing taxonomy concept that could be added cleanly.
4. Proved that a remaining queue was really a media-evidence problem, not just a classification problem.
5. Reduced the need for repeated human re-review of the same items.

## Exercises

### 1. Construction Track Review

Goal:
- Review the construction slice directly to catch obvious false positives and move items to the correct top-level track.

What was done:
- Reviewed the `Track -> Construction` queue in-app.
- Used top-level track only.
- Used `Reason` notes where helpful for emerging subcategory signals.

What it surfaced:
- `Landscaping` was overloaded.
  - Some items were landscape mood/reference.
  - Some items were actual site/lot landscaping scope.
- `Inspection` needed to become a first-class construction concern subtype.

Outcome:
- This pass materially improved the construction set before follow-up slices were created.

Success criteria met:
- Yes.
- It exposed the right missing concepts and reduced obvious construction false positives.

What remained ambiguous:
- Landscape items needed their own follow-up.
- Inspection items needed a cleaner construction subcategory.

### 2. Landscaping Follow-Up

Collection:
- `Review: Landscaping Follow-Up - 2026-03-09`
- 27 items

Goal:
- Split landscape mood/reference from lot/site landscaping scope.

Decision rule:
- mood/reference -> `Style / Decor`
- lot/site work/task/system -> `Construction`

Result:
- `Construction = 24`
- `Style / Decor = 3`

Success criteria met:
- Yes.
- It proved that most of this slice was real construction/site scope, not style.

What remained ambiguous:
- Landscaping still needs a cross-track facet in the longer-term design.
- It should not be a single flat bucket.

### 3. Inspection Follow-Up

Collection:
- `Review: Inspection Follow-Up - 2026-03-09`
- 2 items

Goal:
- Validate that inspection-related material belongs inside construction and deserves a dedicated construction subtype.

Result:
- `Construction = 2`

Success criteria met:
- Yes.
- This directly supported creation of `inspection_quality_control` as a live construction `concern_domain`.

What remained ambiguous:
- Some older manual axis overrides had to be cleared so new inference could take over cleanly.

### 4. Source Link Conflicts Review

Collection:
- `Review: Source Link Conflicts - 2026-03-09`
- 158 items

Goal:
- Review the items where source-page evidence conflicted with the current track classification.

Result:
- `Irrelevant = 76`
- `Style / Decor = 45`
- `Construction = 19`
- `Maintenance / DIY = 18`

Success criteria met:
- Yes.
- This was the highest-value review pass because it resolved direct evidence conflicts.

What remained ambiguous:
- Some conflicts were actually thumbnail/media defects rather than track defects.
- This pass helped expose that difference but did not solve it fully.

### 5. Ambiguous True Contested Review

Collection:
- `Review: Ambiguous True Contested - 2026-03-10`
- 127 items

Goal:
- Review the items where the classifier still had genuinely mixed signals, not just low-signal URL noise.

Result:
- `Irrelevant = 67`
- `Style / Decor = 24`
- `Construction = 24`
- `Maintenance / DIY = 12`

Success criteria met:
- Yes.
- This narrowed the remaining genuinely contested set.

What remained ambiguous:
- Some items were still contested because media evidence was poor.
- Those should not be repeatedly reviewed as pure classification problems.

### 6. Ambiguous Low-Signal URL Review

Collection:
- `Review: Ambiguous Low Signal URLs - 2026-03-10`
- 20 items

Goal:
- Clear weak URL-backed cases where the model had too little evidence and the likely answer could still be judged quickly by a human.

Result:
- `Irrelevant = 15`
- `Style / Decor = 3`
- `Construction = 1`
- `Maintenance / DIY = 1`

Success criteria met:
- Yes.
- This was a small, efficient cleanup pass.

What remained ambiguous:
- Low-signal URL issues still exist at larger scale in `source_link_insufficient`.

### 7. Ambiguous Media Link Mismatch Review

Collection:
- `Review: Ambiguous Media Link Mismatch - 2026-03-10`
- 30 items

Goal:
- Review items where the thumbnail and link context appeared to disagree.

Result:
- `Irrelevant = 29`
- `Construction = 1`

Success criteria met:
- Yes.
- This proved that many explicit mismatch cases were just junk or wrong-context media.

What remained ambiguous:
- Mismatch review still did not solve the larger class of misleading but repeated low-information thumbnails.

### 8. Maintenance / DIY Track Confirmation

Collection:
- `Review: Maintenance / DIY Track - 2026-03-10`
- 7 items

Goal:
- Confirm whether the remaining maintenance items actually belonged in the adjacent `Maintenance / DIY` track.

Result:
- `Maintenance / DIY = 7`

Success criteria met:
- Yes.
- The adjacent bucket held.

What remained ambiguous:
- Nothing significant in this slice.

## Current Post-Exercise State

Visible corpus totals:
- `4669` visible assets
- `674` hidden assets

Current effective top-level track totals:
- `Style / Decor = 4170`
- `Irrelevant = 290`
- `Construction = 178`
- `Maintenance / DIY = 31`

Current active Jim manual track overrides:
- `Construction = 178`
- `Irrelevant = 155`
- `Style / Decor = 78`
- `Maintenance / DIY = 31`

Interpretation:
- The style corpus remains dominant, which is expected.
- Construction is now a much tighter slice than in the old pipeline.
- Maintenance / DIY is small and stable as an adjacent bucket.
- Irrelevant is now explicit rather than leaking into construction/style review.

## What Worked

1. Small, named review slices worked much better than giant undifferentiated queues.
2. Source-link conflict review produced high-value corrections quickly.
3. Separating `Maintenance / DIY` from `Construction` was correct.
4. Landscape and inspection both needed focused follow-up rather than being forced into vague buckets.
5. Human overrides had to be treated as first-class inputs to filtering, sidebar counts, and one-by-one review.

## What Did Not Work Well Enough

1. `Weak thumbnail` was too vague as a queue name.
   - Many items in that bucket were not obviously weak to a human.
   - The real issue was often “trust title/source more than the image.”

2. Source-link browser enrichment is not enough for Facebook group wrapper posts when unauthenticated.
   - The live probe often landed on group-level branding instead of the real post graphic/banner.
   - This is why a browser-assisted authenticated hero-capture workflow is now needed.

3. One dimension was not enough.
   - Track classification and media reliability are separate questions.
   - Treating them as one made review awkward.

## Remaining Ambiguity

### A. Media Reliability Population

Current clearly flagged media-reliability population:
- `126` unique items

Made from:
- `Media: Link / Thumbnail Mismatch = 30`
- `Media: Trust Title / Source = 96`

Breakdown:
- `Facebook = 44`
- `Pinterest = 82`

Within the Facebook subset:
- `12` are explicit Facebook group permalinks

Interpretation:
- This is the bounded queue where media is non-informative or misleading.
- It is not the whole corpus.
- It is the right place to pilot hero-image replacement.

### B. Larger Source-Link Insufficient Population

There is still a much larger queue:
- `source_link_insufficient = 967`

Breakdown:
- `Facebook = 326`
- `Pinterest = 641`
- explicit Facebook group permalinks in this set: `84`

Overlap with the current media-reliability union:
- overlap: `51`
- `916` are `source_link_insufficient` only

Interpretation:
- The `126` media-reliability set is the sharper, more actionable subset.
- The `967` set is a larger adjacent problem where the source page did not yield enough usable signal.
- Better clickthrough + banner/hero capture could help part of that larger set, especially the Facebook subgroup.

## Workflow Changes Made During This Phase

### Review UX

The workflow was simplified to classification review, not old-style keeper curation.

Key changes:
- modal and one-by-one review were brought closer together
- `Keep current`, `Move`, `Mark irrelevant` became the core actions
- `Irrelevant` became a direct action instead of a confusing duplicate dropdown choice
- one-by-one review now auto-advances and supports undo
- stale out-of-scope review items were removed from the one-by-one queue
- track filters and sidebar counts were fixed to honor active manual overrides

### New Review Fields

Added:
- `Review focus`
  - `Landscaping`
  - `Inspection`
- `Media issue`
  - `Trust title / source`
  - `Thumbnail is placeholder`
  - `Thumbnail mismatches content`

Current saved counts:
- `review_focus` active rows: `40`
- `media_reliability` active rows: `0`

Interpretation:
- The media issue workflow is now implemented in the UI, but has not yet been used in a completed pass.

## Current Collections Relevant To Next Phase

Fully reviewed exercises:
- `Review: Source Link Conflicts - 2026-03-09`
- `Review: Ambiguous True Contested - 2026-03-10`
- `Review: Ambiguous Low Signal URLs - 2026-03-10`
- `Review: Ambiguous Media Link Mismatch - 2026-03-10`
- `Review: Landscaping Follow-Up - 2026-03-09`
- `Review: Inspection Follow-Up - 2026-03-09`
- `Review: Maintenance / DIY Track - 2026-03-10`

Derivative / not fully resolved yet:
- `Review: Media - Trust Title / Source - 2026-03-10`
  - `96` total
  - only `30` currently have Jim overrides because this collection overlaps earlier reviewed items
- `Review: Facebook Media Reliability - 2026-03-10`
  - `44` total
  - `33` already intersect existing Jim overrides
- `Review: Facebook Group Hero Capture - 2026-03-10`
  - `12` total
  - `7` already intersect existing Jim overrides

This distinction matters:
- those later collections are organizational slices for the next workflow phase
- they are not evidence that those queues have already been fully handled end-to-end

## Next Step

The next correct workflow is not another broad classification pass.

It is:

1. Use the `44` Facebook media-reliability items as the bounded target population.
2. Start with the `12` Facebook group permalink hard cases.
3. In a real browser session, click through to the actual post/discussion page.
4. Capture a candidate replacement image near the top of the content.
5. Save nearby banner/question text as better evidence.
6. Optionally promote that image into asset media so the modal shows the real content instead of the platform placeholder.
7. Then finalize track classification only after the better evidence is in place.

That is the first workflow that addresses the true remaining problem directly.

## Bottom Line

The interactive filtering workflow achieved its main goal.

It did not “finish classification forever,” but it did:
- stabilize the top-level tracks,
- isolate the remaining media-quality problem,
- prove that small targeted review slices work,
- and narrow the next hard engineering problem to a bounded Facebook/media subset instead of an amorphous corpus-wide mess.

The next phase should therefore be treated as:
- `media evidence repair`,
not
- `generic classification review`.
