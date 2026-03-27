# Curation V2 Progress - 2026-03-06

## Current best runs

- Latest `track_gate` run:
  - `5e88e389-d977-4ea9-82ac-eb9612486905`
- Latest `multi_axis_inference` run:
  - `cc63e4bf-86cb-427d-a1c4-f73bd9c748a0`

These are the runs to inspect first.

## What changed in this work session

### Track-gate improvements

- Reduced overreliance on `assets.category=home_design`, especially for Facebook.
- Boosted irrelevant-title evidence so obvious off-topic saves do not stay on the style track.
- Strengthened construction classification for unfinished build scenes.
- Narrowed overly broad construction triggers:
  - removed bare `code` as a global track-level construction hint
  - removed bare `concrete` as a global track-level construction hint
- Lowered broad `diy` and `product_review` style/construction bias.
- Reduced generic AI construction-tag weight and relied more on stronger scene/text evidence.
- Increased Pinterest style prior to offset false-positive construction drift.

### Axis-layer improvements

- `product_system_focus` now keeps specific named systems alongside broader system classes.
- `zip-r sheathing` variants are recognized as `zip_system`.
- Bare shower `drain` references no longer force `site_exterior`.

## Regression coverage added

`tests/test_classification_v2.py` now covers:

- unfinished construction scene -> `construction_concern`
- low-signal supplement post -> `irrelevant`
- generic Pinterest `code` oddball -> not `construction_concern`
- patio reference with concrete pavers -> `style_product_decor`
- outdoor dining style item -> `outdoor_zone`, no room
- product shot -> `single_product`, no room
- construction system item -> `zip_system`
- shower drain case -> not `site_exterior`

Full suite result after changes:

- `43` tests passed

Command:

```bash
PYTHONPATH=src python3 -m unittest -v \
  tests.test_classification_v2 \
  tests.test_db_schema \
  tests.test_title_audit \
  tests.test_scans_import \
  tests.test_ai_mock \
  tests.test_curation_pipeline
```

## Track-gate delta

### Baseline run

- Run id: `00dfcc4d-4eff-421b-b604-fd384611c63d`
- Counts:
  - `style_product_decor = 4433`
  - `construction_concern = 172`
  - `irrelevant = 94`

By source:

- Facebook:
  - `style = 358`
  - `construction = 157`
  - `irrelevant = 31`
- Pinterest:
  - `style = 3705`
  - `construction = 15`
  - `irrelevant = 63`

### Intermediate run

- Run id: `30c4599a-150b-4f11-9ff2-208bedb70f1f`
- Counts:
  - `style_product_decor = 4284`
  - `construction_concern = 252`
  - `irrelevant = 163`

This improved recall, but it over-expanded Pinterest construction.

### Latest run

- Run id: `5e88e389-d977-4ea9-82ac-eb9612486905`
- Counts:
  - `style_product_decor = 4307`
  - `construction_concern = 232`
  - `irrelevant = 160`

By source:

- Facebook:
  - `style = 306`
  - `construction = 194`
  - `irrelevant = 46`
- Pinterest:
  - `style = 3631`
  - `construction = 38`
  - `irrelevant = 114`

Interpretation:

- Facebook drift improved in the desired direction.
- Pinterest false-positive construction improved from `52` down to `38`, but still needs more tightening.

## Axis-layer delta

### Earlier reference axis run

- Run id: `7136cb79-62aa-46f2-a455-a4b2e20af7a0`
- Envelope:
  - `total = 62`
  - `undifferentiated = 17`
  - `differentiated = 45`

### Latest axis run

- Run id: `cc63e4bf-86cb-427d-a1c4-f73bd9c748a0`
- Envelope:
  - `total = 71`
  - `undifferentiated = 24`
  - `differentiated = 47`

Current latest axis counts:

- `concern_domain`
  - `envelope = 71`
  - `mep = 46`
  - `plans_code_permits = 26`
  - `site_exterior = 22`
  - `structure = 12`
- `product_system_focus`
  - `window_system = 34`
  - `insulation_system = 31`
  - `water_heater = 14`
  - `duct_system = 7`
  - `roofing_system = 7`
  - `zip_system = 7`
  - `tankless_water_heater = 5`
  - `waterproofing_membrane = 4`

## Specific successful fixes

- Real `Zip R Sheathing explained...` asset now lands as:
  - `concern_domain = envelope`
  - `product_system_focus = insulation_system`
  - `product_system_focus = zip_system`
  - `trade_system = envelope`

- Outdoor dining items stay `outdoor_zone` and do not get forced into `dining_room`.

- Product-led style items such as faucets and valves can stay `single_product` without being forced into room buckets.

## Main remaining issues

1. Pinterest construction is still too high at `38`.
   - The remaining false positives appear to cluster around:
   - how-to / lifehack pins
   - text/image oddballs
   - generic repair or utility content that is not really a house-planning concern

2. Some `diy` videos still land in construction when they are more like generic gardening, cleaning, or utility hacks.

3. `undifferentiated envelope = 24` is much better than the old broad `Envelope = 913`, but it is still larger than ideal.

## Suggested next steps

1. Audit the remaining `38` Pinterest construction items and split them into:
   - true construction concerns
   - irrelevant utility/how-to content
   - style/exterior references

2. Tighten `diy` handling so generic lawn/garden/cleaning content does not enter construction unless there is explicit building-system evidence.

3. Add a lightweight review export for:
   - `construction_concern` items
   - `undifferentiated envelope`
   - `ambiguous track-gate` items

4. Once the track gate is steadier, start consuming `space_context` and `subject_type` in the report pipeline so room assignment is conditional instead of forced.
