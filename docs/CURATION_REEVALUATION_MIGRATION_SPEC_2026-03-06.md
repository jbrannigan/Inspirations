# Curation Re-evaluation Migration Spec

Date: 2026-03-06  
Status: Design proposal  
Scope: Preserve prior work as evidence, not as unquestioned truth

## Decision summary

We should not discard prior AI characterization work.  
We should also not promote prior curation outputs to ground truth under the new hierarchy model.

The correct approach is:

1. Keep raw source records and prior AI outputs.
2. Freeze legacy curation results as `v1` outputs.
3. Re-run categorization under the new multi-axis model.
4. Treat prior Gemini analysis as evidence in the new system, not as final classification.

## What survives unchanged

These remain first-class evidence and should not be thrown away:

### Raw source and media evidence

From `assets` and related source metadata:

- `source`
- `source_ref`
- `source_url`
- `image_url`
- `stored_path`
- `thumb_path`
- `board`
- `description`
- `notes`
- `creator_name`
- `created_at`
- `imported_at`
- `scrape_json`
- media files on disk

These are closest to original acquisition context.

### User scope and curation state

- `triage_status` (`keeper`, `pending`, etc.)
- collections / hidden state
- annotations

These are human workflow signals and should be preserved exactly.

### Prior AI evidence

Keep all of the following:

- `asset_ai` rows for `provider='gemini'`
- `asset_ai` rows for `provider='gemini-video'`
- `asset_labels`
- `asset_embeddings`
- `ai_summary`

Important distinction:

- `asset_ai.json` and `asset_labels` are useful evidence.
- `ai_summary` is convenience text and should carry lower trust than structured evidence.

## What should be demoted to legacy

These should be preserved, but not reused as authoritative truth for the new classifier:

### Legacy curation outputs

- `style-best-of.json`
- `construction-concerns.json`
- `curation-manifest.json`
- HTML renders derived from those
- legacy dossier outputs from `Exploration/`

These are valuable for comparison and auditing, but they encode the old taxonomy assumptions.

### Legacy inferred decisions

Do not treat the following as canonical training truth:

- old room assignment
- old concern type assignment
- old machine star ratings
- old pairwise ranking results
- old dossier summaries

Those outputs were downstream of the older room-centric logic and may reflect categorization errors.

## What should be treated cautiously

### Titles

Current `title` values are useful but not intrinsically trustworthy.

They may originate from:

- imported source titles
- Facebook post text truncation
- Houzz slug/title fallback logic
- AI scan title suggestion
- title audit application
- manual edit flows

Recommendation:

- keep current title as a display field
- add provenance for where the current title came from
- do not let title dominate classification unless other evidence agrees

### AI summaries

Keep them, but use them as low-to-medium trust evidence only.

They are descriptive, but they are already lossy interpretations of the asset.

## Trust model for reused evidence

### High trust

- explicit user board intent when semantically meaningful
- human overrides
- `keeper` / `pending` triage state
- durable source-native structured metadata

### Medium trust

- prior Gemini structured JSON fields such as:
  - `image_type`
  - `rooms`
  - `materials`
  - `styles`
  - `fixtures`
  - `appliances`
  - `brands_products`
- AI labels
- embeddings

### Lower trust

- current title without provenance weighting
- AI prose summary
- heuristic expansions
- legacy curation assignment outputs

## Recommendation on Gemini reuse

Do not blindly rerun everything from zero if we already have usable Gemini evidence.

Recommended policy:

1. Reuse prior generic Gemini image-analysis JSON as evidence.
2. Re-evaluate track and hierarchy membership using the new schema.
3. Do not reuse old Gemini curation decisions as final labels.

This means:

- keep the old image understanding
- replace the old taxonomy decision layer

## Proposed new schema surface

Keep the existing evidence tables. Add a new classification layer instead of rewriting existing evidence in place.

### 1) `classification_runs`

Purpose:

- version each evaluation pass
- record schema and prompt/model versioning

Suggested fields:

- `id`
- `schema_version`
- `run_type` (`track_gate`, `multi_axis_inference`, `human_override_merge`, etc.)
- `model_provider`
- `model_name`
- `prompt_version`
- `created_at`
- `notes`

### 2) `asset_field_provenance`

Purpose:

- track where mutable display fields came from

Suggested fields:

- `id`
- `asset_id`
- `field_name` (`title`, `description`, `board`, `ai_summary`, etc.)
- `origin_type` (`imported`, `source_native`, `ai_suggested`, `title_audit`, `manual_edit`, `derived`)
- `origin_ref`
- `actor`
- `confidence`
- `created_at`
- `superseded_at`
- `is_current`

Minimum immediate use:

- backfill provenance for `title`

### 3) `asset_track_assessments`

Purpose:

- store track-level classification per run

Suggested fields:

- `id`
- `run_id`
- `asset_id`
- `track`
- `confidence`
- `is_ambiguous`
- `decision_source` (`model`, `heuristic`, `merged`, `human_override`)
- `created_at`

### 4) `asset_axis_memberships`

Purpose:

- store multi-valued memberships for the new hierarchy

This should be generic, not room-only.

Suggested fields:

- `id`
- `run_id`
- `asset_id`
- `track`
- `axis_name`
- `axis_value`
- `confidence`
- `rank`
- `is_primary`
- `is_ambiguous`
- `created_at`

Examples:

- `axis_name='space_context'`, `axis_value='outdoor_zone'`
- `axis_name='function'`, `axis_value='dining'`
- `axis_name='product_focus'`, `axis_value='sink'`
- `axis_name='concern_domain'`, `axis_value='envelope'`
- `axis_name='product_system_focus'`, `axis_value='zip_system'`

This table is the core of the non-exclusive model.

### 5) `asset_axis_evidence`

Purpose:

- explain why a membership was assigned

Suggested fields:

- `id`
- `run_id`
- `asset_id`
- `axis_name`
- `axis_value`
- `evidence_type` (`board`, `asset_ai_json`, `asset_label`, `title`, `description`, `embedding_neighbor`, `human_override`)
- `evidence_ref`
- `weight`
- `confidence`
- `note`
- `created_at`

This is critical for auditability and reviewer trust.

### 6) `asset_overrides`

Purpose:

- apply human corrections without mutating the original machine evidence

Suggested fields:

- `id`
- `asset_id`
- `axis_name`
- `axis_value`
- `operation` (`add`, `remove`, `set_primary`, `suppress`)
- `actor`
- `note`
- `created_at`
- `expires_at` (nullable)

## Migration policy by artifact

### Keep as evidence

- `assets`
- `asset_ai`
- `asset_labels`
- `asset_embeddings`
- `title_audit_*`
- collections and triage state

### Freeze as legacy comparison artifacts

- current curation JSON outputs
- HTML report outputs
- legacy Exploration dossier outputs

### Recompute under new model

- `track`
- style hierarchy memberships
- construction hierarchy memberships
- room assignment
- product / system focus
- ambiguity flags
- export groupings derived from those

## Practical migration steps

### Phase 1: Snapshot legacy

- preserve current export directories as `v1`
- do not delete prior outputs

### Phase 2: Add provenance and new classification tables

- add new tables through `db.py` migration path
- backfill `title` provenance first

### Phase 3: Build v2 evaluator

Inputs:

- raw source fields
- prior Gemini structured JSON
- labels
- embeddings
- user scope / triage signals

Outputs:

- track assessment
- multi-axis memberships
- evidence rows
- ambiguity markers

### Phase 4: Keep old and new side by side

- legacy outputs remain reviewable
- new outputs use `v2` schema
- compare disagreement rates before replacing old export path

## What not to do

- do not overwrite old evidence with new classification outputs
- do not train the new system on old room assignments as if they were ground truth
- do not let pairwise ranking compensate for bad categorization
- do not force a single room when `space_context`, `subject_type`, or `product_focus` suggests otherwise

## Minimal viable implementation order

If we want the smallest defensible implementation:

1. add `classification_runs`
2. add `asset_field_provenance`
3. add `asset_track_assessments`
4. add `asset_axis_memberships`
5. backfill title provenance
6. build new track gate
7. build new multi-axis membership inference

`asset_axis_evidence` should come immediately after if we care about explainability, which we probably should.

## Final recommendation

We should keep most of the previous attempts, but recast them:

- raw source data stays authoritative
- generic Gemini visual characterization stays as reusable evidence
- legacy curation decisions become historical comparison artifacts
- the new agent should evaluate classification anew, but using prior evidence rather than ignoring it

That is the safest path that preserves past work without inheriting its assumptions.

