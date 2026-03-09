# Curation / Classification Checkpoint - 2026-03-07

## Purpose

This checkpoint separates the classification work from the UI work.

The classification stream is about:

- trustworthy discrimination between `style_product_decor`, `construction_concern`, `home_maintenance_diy`, and `irrelevant`
- trustworthy multi-axis categorization after the track gate
- preserving prior work as evidence while replacing weak legacy decision layers

The UX stream is important, but it should be handled as a separate cleanup sprint.

Related UX backlog document:

- `docs/UX_CLEANUP_SPRINT_BACKLOG_2026-03-07.md`

## Current best runs

These are the current reference runs for v2 classification:

- `track_gate`
  - current run id: `9a308297-d1f1-4509-b29c-d071e2f2d66d`
  - current notes: `raw irrelevant intent override, color-palette beauty carveout, and Leslie magazine clips style signal`
- `multi_axis_inference`
  - current run id: `98f95cbb-70bf-4223-9736-d1a23ecf94dc`
  - current notes: `use source-link evidence for construction concern-domain inference after landscape and inspection review`

## What is complete

### 1. Re-evaluation architecture is in place

The project now has a side-by-side v2 classification layer instead of overwriting legacy outputs.

Implemented already:

- `classification_runs`
- `asset_field_provenance`
- `asset_track_assessments`
- `asset_axis_memberships`
- `asset_axis_evidence`
- `asset_overrides`

This is consistent with the migration design in:

- `docs/CURATION_REEVALUATION_MIGRATION_SPEC_2026-03-06.md`

### 2. Title provenance and working-title workflow are in place

This is important because title quality was part of the earlier compounding-error problem.

Current title handling now distinguishes between:

- the current working title
- a better original/source-derived title where possible
- a concise suggested title for workflow use

### 3. v2 track gate is live and usable

Latest counts:

- `style_product_decor = 4301`
- `construction_concern = 189`
- `home_maintenance_diy = 7`
- `irrelevant = 172`
- `ambiguous = 282`

This is a major improvement over the older curation logic, especially around the previous construction over-bucketing problem.

### 4. v2 multi-axis inference is live and usable

The classifier now writes non-exclusive memberships such as:

- `space_context`
- `subject_type`
- `room`
- `product_focus`
- `concern_domain`
- `product_system_focus`

This is the key structural change that prevents forcing everything into a room bucket.

### 5. Review exports now exist for the remaining problem slices

A repeatable operational export has been added:

- `tools/export_classification_review.py`

Latest export directory:

- `data/exports/classification_review_checkpoint_20260307/`

Generated files:

- `manifest.json`
- `ambiguous_track.json`
- `ambiguous_track.csv`
- `pinterest_construction.json`
- `pinterest_construction.csv`
- `maintenance_diy_track.json`
- `maintenance_diy_track.csv`
- `pinterest_maintenance_diy.json`
- `pinterest_maintenance_diy.csv`
- `undifferentiated_envelope.json`
- `undifferentiated_envelope.csv`

## Current metrics

### Track counts

- current:
  - `style_product_decor = 4301`
  - `construction_concern = 189`
  - `home_maintenance_diy = 7`
  - `irrelevant = 172`
  - `ambiguous = 282`

### Remaining review slices

- current:
  - `ambiguous_track = 282`
  - `ambiguous_low_signal_url = 20`
  - `ambiguous_media_mismatch = 135`
  - `ambiguous_media_link_mismatch = 30`
  - `ambiguous_media_weak_thumbnail = 96`
  - `ambiguous_true_contested = 127`
  - `pinterest_construction = 24`
  - `maintenance_diy_track = 7`
  - `pinterest_maintenance_diy = 3`
  - `undifferentiated_envelope = 0`
  - `source_link_conflicting = 158`
  - `source_link_insufficient = 967`

### Why these slices matter

These are the highest-value slices for tightening the classifier further:

1. `ambiguous_track`
   - these are the items the gate itself is least sure about
2. `pinterest_construction`
   - this is now the narrowed true-construction residual for the Pinterest review set
3. `pinterest_maintenance_diy`
   - this is the new adjacent-bucket slice created from the reviewed Pinterest maintenance/repair items
4. `maintenance_diy_track`
   - this is the broader cross-source adjacent bucket that still needs spot-checking for precision
5. `undifferentiated_envelope`
   - this is the remaining catch-all bucket we want to reduce further

## What the exports show

### Step 2 tightening pass outcome

The latest pass targeted two failure modes:

1. generic DIY / maintenance / utility content that should not stay in `construction_concern`
2. true envelope concerns that were real construction items but still too broad in `concern_domain=envelope`

Implemented changes:

- added stronger irrelevant signals for:
  - cleaning
  - mopping
  - lifehacks
  - moving furniture
  - stripped screw / household-product / woodworking-style utility content
- added a `diy`-specific irrelevant override when the evidence looks like generic non-home DIY rather than a house-planning concern
- expanded construction `product_system_focus` to include more specific envelope systems such as:
  - `door_system`
  - `garage_door_system`
  - `siding_system`
  - `flashing_system`
  - `sheathing_system`
  - `roof_vent_system`
  - broader `window_system` coverage

Result:

- obvious false positives such as:
  - `Living Off Grid - A Home Made Deep Well Pump`
  - `How We Got Our Stained Grout White Again`
  - `Power Tool Woodworking for Everyone Online Overarm Pin Router`
  - the Facebook shower-cleaning reel
  now land in `irrelevant`
- true envelope construction items now pick up specific `product_system_focus` memberships instead of staying broad-only

### 1. Ambiguous-track cases still contain low-signal drift

Representative examples show that a number of ambiguous Facebook items are still landing in `style_product_decor` with very weak evidence, sometimes mostly because of inherited `assets.category=home_design`.

Examples from the export:

- `Driveway sweeper Part 01`
- `Adkins Materials`
- `Association of Professional Builders (APB): Builders Qualifying Checklist`

Interpretation:

- the classifier is no longer wildly overconfident here, which is good
- but the residual default/style prior is still too generous in some low-signal cases

### 2. Pinterest construction still includes utility/how-to contamination

Representative examples from the export:

- `Living Off Grid - A Home Made Deep Well Pump - Mother Earth News`
- `How We Got Our Stained Grout White Again | Young House Love`
- `Power Tool Woodworking for Everyone Online Overarm Pin Router`

Interpretation:

- some of these are plausibly construction-adjacent
- some are really maintenance, utility, DIY, or workshop content rather than house-planning concerns
- this slice needs better negative evidence and better handling of generic how-to content

### 3. Undifferentiated envelope still contains obvious noise

Representative examples from the export:

- real construction videos in `building`
- partially-understood under-construction scenes
- an obvious false positive from `Cleaning Tips`

Interpretation:

- the broad old `Envelope = 913` failure mode has been dramatically reduced
- but `envelope` is still too easy to trigger without a named system or stronger building-envelope evidence

This statement is now partially superseded by the latest pass:

- `undifferentiated_envelope` is currently `0`

That does not mean the construction axis work is finished. It means the current remaining problem is less about broad envelope collapse and more about validating whether the new `product_system_focus` values are the right ones.

### 4. Pinterest regrouping pass is now aligned with the reviewed proposal

The Pinterest construction slice was reviewed manually and grouped into four intended outcomes:

1. `style reference`
2. `construction concern`
3. `construction-adjacent maintenance / repair / utility`
4. `irrelevant / noisy misfire`

The latest classifier pass now matches that proposal exactly for the reviewed `29`-item subset:

- `13 / 13` proposed `style reference` items now land in `style_product_decor`
- `8 / 8` proposed `construction concern` items remain in `construction_concern`
- `5 / 5` proposed `maintenance / repair / utility` items now land in `home_maintenance_diy`
- `3 / 3` proposed `irrelevant / noisy misfire` items now land in `irrelevant`

Implication:

- the remaining Pinterest construction slice is no longer a mixed plan/reference bucket
- the construction and maintenance-adjacent material are now separated cleanly in this reviewed slice

### 5. Maintenance / DIY is now a real fourth track

This was a taxonomy decision, not just a scoring tweak.

The classifier now has a first-class adjacent track:

- `home_maintenance_diy`

Current status:

- total `home_maintenance_diy = 17`
- `pinterest_maintenance_diy = 5`
- the reviewed Pinterest maintenance set now lands there exactly as intended

Current caveat:

- the cross-source bucket is much smaller and cleaner than the first draft, but it still needs spot review for precision, especially on Facebook

## Classification work that remains

### 1. Tighten low-signal track decisions

Priority:

- reduce cases where weak or inherited priors allow a low-information item to stay in `style_product_decor`

Likely work:

- reduce the fallback power of `assets.category=home_design`
- require stronger positive evidence before keeping ambiguous non-visual items on the style track
- push clearly generic content more readily toward `irrelevant`

### 2. Tighten cross-source maintenance / DIY precision

Priority:

- validate that the new adjacent bucket is precise outside the manually-reviewed Pinterest set

Likely work:

- inspect the `maintenance_diy_track` export visually
- remove any remaining generic tool/garden/problem-solving drift
- decide whether this bucket needs its own future axis model or can continue borrowing the construction-side axes

### 3. Tighten Pinterest construction

Priority:

- separate real construction concerns from generic maintenance / DIY / workshop / utility content

Likely work:

- add negative evidence for generic how-to and utility content
- downweight workshop/tool content unless there is explicit house-system evidence
- distinguish `construction concern` from `home maintenance tip`

Current status after the latest pass:

- improved from `38` to `8`
- the false-positive plan/reference cluster has been cleared
- the maintenance/repair subset has been split into its own adjacent track

The remaining rows still appear to contain a mixture of:

- true house-planning concerns
- build-system references
- checklist/planning material
- a smaller amount of ambiguous residue

### 4. Tighten undifferentiated envelope

Priority:

- avoid using `envelope` as a fallback concern domain when the evidence is weak

Likely work:

- require explicit system or building-envelope evidence
- downweight bathroom/cleaning/shower drift unless there is clear enclosure/waterproofing context
- prefer `unknown/ambiguous` over a broad envelope label when evidence is mixed

Current status after the latest pass:

- the raw `undifferentiated_envelope` slice is currently `0`

So the next issue is no longer broad envelope collapse itself.  
The next issue is validating the specificity and usefulness of the new envelope system labels.

### 5. Start consuming v2 axes in report generation

This remains a necessary follow-through step.

Report generation should use:

- `space_context`
- `subject_type`
- `room` only when justified
- `product_focus` / `product_system_focus`

The important rule remains:

- do not force room assignment unless the asset is actually an interior full-room scene or equivalent strong room evidence exists

### 6. Review landscape items for style-vs-construction split

Priority:

- separate landscape mood/reference material from actual lot-landscaping construction scope

Why this is needed:

- `landscape` is overloaded
- some items are aesthetic precedent and belong in `style_product_decor`
- some items represent real site-work or lot-landscaping tasks and belong in `construction_concern`

Working rule:

- keep items in `style_product_decor` when they are about how the grounds should feel or look
- move items to `construction_concern` when they are about work that must be executed on the lot or site

Likely work:

- review landscape/reference items currently landing on the style side
- spot-check whether any of them are actually site-work / execution concerns
- tighten the wording and examples so future review passes treat `landscape mood` and `lot landscaping task` as different things

Current status after the focused review:

- the dedicated landscaping follow-up collection is complete
- final reviewed split:
  - `construction_concern = 24`
  - `style_product_decor = 3`
- implication:
  - the landscape ambiguity is real but bounded
  - most of the reviewed slice was legitimately lot / site / execution work, not style mood/reference

## What is explicitly deferred to the UX sprint

These items should not drive classifier changes directly.

Examples:

- side panel organization and discoverability
- one-by-one review ergonomics
- modal layout and wording
- 3D Explorer control clarity
- visual polish and interaction cleanup

Operational note:

- the recent count-sync bug in one-by-one review has been fixed so the live scope, sidebar node count, and hidden count move together correctly
- that fix is operationally useful, but it is not part of the core classifier checkpoint

## Recommended next classification step

The next engineering pass should operate on the new review exports rather than on broad intuition.

Recommended order:

1. inspect the updated `pinterest_construction.csv`
2. inspect the new `pinterest_maintenance_diy.csv` and `maintenance_diy_track.csv`
3. review landscape items that may be style mood/reference versus lot-landscaping construction scope
4. inspect the highest-noise rows in `ambiguous_track.csv`
5. validate the new `product_system_focus` values for envelope-heavy construction items
6. once that is stable, start consuming v2 axes in report generation

## Checkpoint artifacts

Primary design docs:

- `docs/CURATION_CONFIDENCE_HIERARCHY_SPEC_2026-03-05.md`
- `docs/CURATION_PROVENANCE_AUDIT_2026-03-05.md`
- `docs/CURATION_REEVALUATION_MIGRATION_SPEC_2026-03-06.md`
- `docs/CURATION_V2_PROGRESS_2026-03-06.md`

Operational review artifacts:

- `data/exports/classification_review_checkpoint_20260307/manifest.json`
- `data/exports/classification_review_checkpoint_20260307/ambiguous_track.csv`
- `data/exports/classification_review_checkpoint_20260307/pinterest_construction.csv`
- `data/exports/classification_review_checkpoint_20260307/pinterest_maintenance_diy.csv`
- `data/exports/classification_review_checkpoint_20260307/maintenance_diy_track.csv`
- `data/exports/classification_review_checkpoint_20260307/undifferentiated_envelope.csv`

## 2026-03-09 addendum

### Construction review pass completed

Jim completed a manual one-by-one review pass over the `Track -> Construction` slice.

Recent active overrides persisted during that pass window:

- `construction_concern = 76`
- `style_product_decor = 10`
- `irrelevant = 5`
- `home_maintenance_diy = 4`
- total persisted in the pass window: `95`

Current active Jim track overrides overall:

- `construction_concern = 158`
- `style_product_decor = 21`
- `irrelevant = 11`
- `home_maintenance_diy = 5`
- total active Jim track overrides: `195`

Interpretation:

- the top-level four-track workflow is usable enough for real manual review
- the next classification pressure point is no longer broad construction triage
- it is the sub-structure around landscaping and inspection-like material

### Landscaping follow-up is now the main focused review slice

During the construction review pass, Jim used the reason field to mark landscaping-related items.

Current landscaping-note counts across active Jim track overrides:

- `27` items mention `landscap`
- current track split within that slice:
  - `construction_concern = 23`
  - `style_product_decor = 4`

A follow-up collection was created to make that review slice accessible in the app:

- `Review: Landscaping Follow-Up - 2026-03-09`
- collection id: `ba65d193-5dc4-4650-ae1a-be77db2e85e4`
- item count: `27`

This was intentionally a mixed slice.

It answered:

- which items are landscape mood/reference and should stay on the style side
- which items are site-work / drainage / irrigation / lot-landscaping concerns and should stay on the construction side

Final reviewed result:

- `construction_concern = 24`
- `style_product_decor = 3`

### Inspection is now a live construction concern domain

`inspection_quality_control` is now a first-class `concern_domain` in the v2 model.

Latest axis count:

- `inspection_quality_control = 2`

What changed:

- the focused inspection review confirmed the need
- the classifier now maps strong inspection evidence into `inspection_quality_control`
- stored source-link text is now used in construction-axis inference, which makes source-backed inspection/build topics usable even when the thumbnail/title are weak

One unresolved wrinkle remains:

- asset `5af0e064-01fd-43c9-91a1-4c4dc4ed5852` is still pinned to:
  - `concern_domain = plans_code_permits`
  - `project_phase = permit_code`
- reason:
  - it carries older active manual axis overrides from the earlier workflow
  - those overrides were preserved rather than automatically removed

### One-by-one review is now materially safer

The overnight UX cleanup completed these review-mode changes:

- one-by-one review and modal review now use the same track-review model
- the review card now shows the asset ID
- the one-by-one review form keeps a local draft while Jim types
- undo/go-back restores the saved review draft instead of dropping the typed reason
- `Irrelevant` is now a dedicated action button rather than a duplicated dropdown choice
- both review surfaces now include a structured `Review focus (optional)` field:
  - `Landscaping`
  - `Inspection`

Validation completed:

- `node --check app/app.js`
- `PYTHONPATH=src python3 -m unittest -v tests.test_server_api`
- result: `65` tests passed

### Next starting point

Recommended order for the next session:

1. open the app
2. use the review workflow on the grouped source-link conflict slice
3. decide whether to clear the one stale inspection-axis override that still pins an item to `plans_code_permits`
4. once the source-link conflict slice is smaller, resume report-generation work on top of the v2 axes
