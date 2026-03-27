# AI Curation Pipelines And Report Spec

Date: 2026-03-03 (America/Chicago)

## Goals

- Replace brittle HTML parsing with a direct JSON contract for New Home.
- Preserve complete corpus coverage (`keeper + pending`) while keeping the primary style document readable.
- Separate construction concerns so they can be used independently for planning.

## Curation Principle (Hybrid)

- DB-assisted: use SQLite as the source for candidate retrieval, metadata, and media paths.
- Gemini-led: use explicit curation passes for relevance and intent classification.
- Result: preserve the strong junk-removal behavior of `generate_dossier.py` Steps 1-4 while moving to auditable CLI stages.

## Pipeline Coverage Table (Old -> New)

<table>
  <thead>
    <tr>
      <th>Old</th>
      <th>New</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><strong>Step 1</strong>: <code>generate_dossier.py</code> ingests scrape JSON files and assembles raw candidate items.</td>
      <td><strong>Step 1</strong>: <code>curation collect</code> retrieves candidate assets from SQLite (scope: keeper + pending, hidden excluded), including rich context fields needed for AI curation.</td>
    </tr>
    <tr>
      <td><strong>Step 2</strong>: Script cross-references URLs to <code>assets</code> and <code>asset_labels</code> for tags + thumbnails.</td>
      <td><strong>Step 2</strong>: <code>curation collect</code> enriches candidates from <code>assets</code>, <code>asset_labels</code>, and latest AI summaries; no fragile URL rematch loop required.</td>
    </tr>
    <tr>
      <td><strong>Step 3</strong>: AI prompt performs intent understanding and throws away junk while also assigning category meaning.</td>
      <td><strong>Step 3</strong>: <code>curation classify</code> is explicit and first-class: for each candidate, Gemini returns <code>include</code>, <code>track</code> (<code>style_product_decor</code> / <code>construction_concern</code> / <code>irrelevant</code>), confidence, and rationale.</td>
    </tr>
    <tr>
      <td><strong>Step 4</strong>: Room-level grouping and synthesis happen in one blended flow.</td>
      <td><strong>Step 4</strong>: <code>curation organize</code> groups included items by output intent: style -> rooms; construction -> concern types. This stage is separate from relevance filtering to keep behavior debuggable.</td>
    </tr>
    <tr>
      <td><strong>Step 5</strong>: Gemini provides style and construction dossier text and stars used to shape output sections.</td>
      <td><strong>Step 5</strong>: <code>curation synthesize</code> generates dossier summaries per group; machine stars are applied to style items only; construction remains concern-first (stars optional metadata).</td>
    </tr>
    <tr>
      <td><strong>Step 6</strong>: One-shot script output with limited auditability of what AI filtered or why.</td>
      <td><strong>Step 6</strong>: <code>curation override set</code> captures human overrides for include/exclude, track/group, and style stars; effective values become export truth.</td>
    </tr>
    <tr>
      <td><strong>Step 7</strong>: Markdown/Pandoc produce HTML/DOCX first; New Home then reparses HTML.</td>
      <td><strong>Step 7</strong>: <code>curation export</code> emits two canonical JSON documents directly (style best-of + full construction concerns). Optional HTML/DOCX renderers are downstream.</td>
    </tr>
    <tr>
      <td><strong>Step 8</strong>: State/delta logic depends on <code>processed_urls.json</code>.</td>
      <td><strong>Step 8</strong>: Run state, classification decisions, and overrides persist in DB for reproducible reruns and full audit history; New Home consumes JSON and applies native styling.</td>
    </tr>
  </tbody>
</table>

## Implementation Status (Current Pass)

- Implemented now:
  - `inspirations curation run`
  - Stages covered: collect, classify, organize, synthesize, export
  - Output artifacts: `style-best-of.json`, `construction-concerns.json`, `curation-manifest.json`
- Deferred intentionally:
  - Step 6 human override workflow (`curation override ...`)
  - Rationale: evaluate machine-first output quality before introducing override persistence

## CLI Switches (Best Of Culling)

Use these switches on `inspirations curation run` to force a smaller primary style document while keeping the full corpus in appendix:

- `--best-of-min-rating`: initial star threshold for Best Of candidates (default `4`)
- `--best-of-max-total`: hard global cap for Best Of (`0` means uncapped)
- `--best-of-max-per-room`: optional per-room cap (`0` means uncapped)
- `--best-of-target-per-room`: top-N per style room/category (`0` disables this mode)
- `--best-of-tie-max-per-room`: optional expansion cap when items tie at the per-room cutoff
- `--best-of-backfill-if-short/--no-best-of-backfill-if-short`: if under target, fill from lower-rated style items
- `--best-of-show-all-if-under-target/--no-best-of-show-all-if-under-target`: when total style items are fewer than target, include all style items

### Pairwise Ranking Mode (Style)

Use pairwise when you want finer style discrimination than integer stars, while keeping the same export contracts:

- `--style-ranking-mode pairwise`: re-rank style items by pairwise comparisons (room-scoped), then apply existing Best Of caps.
- `--pairwise-votes-path`: optional human vote file (`JSON` or `JSONL`) with rows like:
  - `{"left":"assetA","right":"assetB","winner":"left|right|tie"}`
  - `winner` may also be an explicit `assetId`.
- `--pairwise-max-candidates-per-room`: limit candidate pool per room for pairwise comparisons.
- `--pairwise-rounds-per-room`: increase/decrease pairwise matchup density.
- `--pairwise-max-pairs-per-room`: hard cap total comparisons per room.
- `--pairwise-elo-k`: tuning knob for update strength in pairwise ranking.

Recommended top-10 command (permissive fallback enabled):

```bash
PYTHONPATH=src python3 -m inspirations curation run \
  --provider heuristic \
  --summary-provider gemini \
  --best-of-max-total 10 \
  --best-of-min-rating 4 \
  --best-of-backfill-if-short \
  --best-of-show-all-if-under-target \
  --render-html \
  --out-dir data/exports/curation_top10
```

Per-category top-10 (allow expansion to 20 on ties at room cutoff):

```bash
PYTHONPATH=src python3 -m inspirations curation run \
  --provider heuristic \
  --summary-provider gemini \
  --best-of-target-per-room 10 \
  --best-of-tie-max-per-room 20 \
  --best-of-min-rating 4 \
  --best-of-backfill-if-short \
  --best-of-show-all-if-under-target \
  --render-html \
  --out-dir data/exports/curation_top10_per_room
```

Pairwise-driven top-10 per room (with optional human vote overrides):

```bash
PYTHONPATH=src python3 -m inspirations curation run \
  --provider heuristic \
  --summary-provider gemini \
  --style-ranking-mode pairwise \
  --pairwise-votes-path data/exports/pairwise_votes.jsonl \
  --pairwise-max-candidates-per-room 60 \
  --pairwise-rounds-per-room 5 \
  --pairwise-max-pairs-per-room 200 \
  --pairwise-elo-k 24 \
  --best-of-target-per-room 10 \
  --best-of-tie-max-per-room 20 \
  --best-of-min-rating 4 \
  --best-of-backfill-if-short \
  --best-of-show-all-if-under-target \
  --render-html \
  --out-dir data/exports/curation_pairwise_top10_per_room
```

## Output Spec (Two Documents)

## Document 1: Best Of Style

Purpose: Small, highly curated style reference.

- Includes: `style/product/decor` items.
- Primary section: `keepers + 4-5 star` items grouped by room.
- Appendix section: `1-3 star` non-keepers grouped by room, so style corpus remains complete.
- Uses stars (`1..5`) and allows human override of machine stars.
- When `--best-of-target-per-room` is used, primary selection switches to per-room top-N mode (with optional tie expansion), and all remaining style items stay in appendix.

Suggested output files:

- `style-best-of.json` (canonical)
- `style-best-of.html` (optional presentation)
- `style-best-of.docx` (optional sharing artifact)

Required item fields:

- `assetId`
- `id` (stable export id)
- `classification` (`style_product_decor|construction_concern|irrelevant`)
- `include` (`true|false`)
- `classificationConfidence` (`0..1`)
- `classificationReason`
- `room`
- `imageUrl`
- `sourceUrl`
- `description`
- `tags[]`
- `machineRating` (`1..5`)
- `humanRating` (`1..5|null`)
- `ratingValue` (`humanRating ?? machineRating`)
- `ratingSource` (`machine|human`)
- `selectionState` (`keeper|pending`)

## Document 2: Construction Concerns

Purpose: Separate, actionable concerns document for design/build planning.

- Includes: all `construction concern` items in `keeper + pending`.
- No star-gating required; stars are optional metadata only.
- Grouping recommended by concern type:
  - `site/exterior`
  - `envelope`
  - `structure`
  - `MEP (mechanical/electrical/plumbing)`
  - `plans/code/permits`

Suggested output files:

- `construction-concerns.json` (canonical)
- `construction-concerns.html` (optional presentation)
- `construction-concerns.docx` (optional sharing artifact)

Required item fields:

- `assetId`
- `id`
- `classification` (`construction_concern`)
- `include` (`true`)
- `classificationConfidence` (`0..1`)
- `classificationReason`
- `concernType`
- `imageUrl`
- `sourceUrl`
- `description`
- `tags[]`
- `selectionState` (`keeper|pending`)
- `note` (machine rationale and/or human editorial note)

## Canonical JSON Envelope (For New Home)

```json
{
  "generatedAt": "2026-03-03T21:10:00Z",
  "run": {
    "mode": "hybrid-db-assisted-gemini-led",
    "classifierModel": "gemini-2.5-flash",
    "scopeTotal": 4663,
    "includedTotal": 0,
    "irrelevantTotal": 0
  },
  "scope": {
    "triageIncluded": ["keeper", "pending"],
    "hiddenExcluded": true
  },
  "documents": [
    {
      "kind": "style-best-of",
      "title": "Curated Style Inspiration (Best Of)",
      "summary": "Top-rated style direction with full non-keeper appendix.",
      "groups": []
    },
    {
      "kind": "construction-concerns",
      "title": "Construction Concerns",
      "summary": "All planning and construction-relevant items.",
      "groups": []
    }
  ]
}
```

Notes for New Home consumption:

- Treat JSON as the source of truth; New Home owns all visual styling.
- Avoid Pandoc/HTML parsing in the integration path.
- Use existing Inspirations media endpoint format for images when running live:
  - `/media/{assetId}?kind=thumb`
  - `/media/{assetId}?kind=original`

## Current Corpus Size Estimate (From Database)

Scope used for estimate: `triage_status in (pending, keeper)` (hidden excluded).

- Active scope total: `4663`
- Hidden (excluded by scope): `644`
- Total assets in DB: `5307`

Heuristic estimate (style/product/decor vs construction concerns):

| Heuristic | Construction concerns | Style/Product/Decor | Irrelevant | Notes |
|---|---:|---:|---:|---|
| Strict | 388 | 4044 | 242 | Uses high-signal construction terms only (plans/HVAC/plumbing/foundation/etc.) |
| Medium | 1053 | 3383 | 242 | Adds broader structural/building terms; recommended planning baseline |
| Broad | 1396 | 3043 | 242 | Includes wider material/exterior signals; likely over-inclusive |

Practical planning range:

- Construction concerns likely between `~400` and `~1400`.
- Initial implementation sizing target: `~1000` construction items (medium heuristic).
