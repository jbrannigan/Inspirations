# Curation Provenance Audit (2026-03-05)

## Scope
- Candidate scope (`pending,keeper`): **4663**
- Source split:
  - `pinterest`: 3783
  - `facebook`: 546
  - `houzz`: 226
  - `scan`: 108

## Key Findings
- If `title` is blanked in heuristic classification, **69** items change track and **99** items change room.
- Style room changes from title blanking: **46/3050** items.
- Dining-room assignments with outdoor evidence: **17** items.
- Missing board: **150**, missing labels: **64**, missing both: **47**.

## Why This Is Compounding Error
- We mix heterogeneous fields (`title`, `description`, `board`, `notes`, `ai_summary`, `labels`) into one blob with no provenance weighting.
- `title` can originate from multiple pipelines and can be rewritten later; current curation does not track trust level per field.
- Room assignment is first-match keyword logic, so one noisy token can dominate.

## Immediate Recommendation (Before More Ranking Work)
1. Freeze room taxonomy changes until provenance/trust model is defined.
2. Introduce `unknown/ambiguous` room instead of forced assignment when signals conflict.
3. Weight board/manual labels above generated titles and heuristics.
4. Keep pairwise only for ranking within trusted categories, not for category assignment.

Raw machine report: `data/exports/provenance_audit_20260305.json`
