# Morning Handoff - 2026-03-09

## Current state

App:

- owner link: http://127.0.0.1:8001/?actor=Gq1AgKKfLaB-9qgAOqQuOA

Completed focused review slices:

- collection: `Review: Landscaping Follow-Up - 2026-03-09`
- collection id: `ba65d193-5dc4-4650-ae1a-be77db2e85e4`
- reviewed result:
  - `construction_concern = 24`
  - `style_product_decor = 3`

- collection: `Review: Inspection Follow-Up - 2026-03-09`
- collection id: `08ba40fe-a7ed-4da8-bfe8-a0edd67b605b`
- reviewed result:
  - `construction_concern = 2`

Current reference runs:

- `track_gate`
  - run id: `9a308297-d1f1-4509-b29c-d071e2f2d66d`
  - counts:
    - `style_product_decor = 4301`
    - `construction_concern = 189`
    - `home_maintenance_diy = 7`
    - `irrelevant = 172`
    - `ambiguous = 282`
- `multi_axis_inference`
  - run id: `98f95cbb-70bf-4223-9736-d1a23ecf94dc`
  - note: `use source-link evidence for construction concern-domain inference after landscape and inspection review`

## What changed overnight

### Review workflow

- one-by-one review now uses the same track-review model as the modal
- review card now shows the asset ID
- one-by-one keeps a local draft of the track + reason while Jim types
- undo / go-back restores the prior item with its typed reason intact
- `Mark irrelevant` is now the dedicated irrelevant action
- both modal review and one-by-one review now include a structured `Review focus (optional)` field:
  - `Landscaping`
  - `Inspection`
- the track dropdown now only lists:
  - `Style / Decor`
  - `Construction`
  - `Maintenance / DIY`
- construction axis inference now also uses stored source-link text for subcategory assignment

### Safety / hygiene

- browser automation scratch output is now gitignored:
  - `.playwright-cli/`
  - `.claude/worktrees/`
- `CONTEXT.md` remains gitignored and was already removed from Git tracking earlier in the session

## Review results from the construction pass

Recent active overrides persisted during the pass window:

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

Landscaping follow-up final result:

- reviewed items: `27`
- split:
  - `construction_concern = 24`
  - `style_product_decor = 3`

Inspection follow-up final result:

- reviewed items: `2`
- split:
  - `construction_concern = 2`

Inspection domain status:

- `inspection_quality_control` is now a live `concern_domain`
- current count in the latest axis run: `2`
- one reviewed inspection item still remains pinned to:
  - `concern_domain = plans_code_permits`
  - `project_phase = permit_code`
- reason:
  - it has older active manual axis overrides from the earlier workflow
  - those were not removed automatically

## Recommended next order

1. use the modal / one-by-one classification-review workflow on `source_link_conflicting_grouped.html`
2. decide whether to clear the older manual axis overrides on the one inspection item that is still pinned to `plans_code_permits`
3. promote `Landscaping` into an explicit cross-track facet design
4. return to consuming v2 axes in report generation after the source-link conflict slice shrinks

## Supporting docs

- `docs/CURATION_CLASSIFICATION_CHECKPOINT_2026-03-07.md`
- `docs/UX_CLEANUP_SPRINT_BACKLOG_2026-03-07.md`
- `docs/CURATION_REEVALUATION_MIGRATION_SPEC_2026-03-06.md`
