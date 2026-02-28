# 3D Explorer Fix

## Sprint Closeout (2026-02-28)

### Sprint intent

- Make 3D open in a readable, precomputed clustered layout (not an initial sphere).
- Fix 3D click behavior so thumbnails open the detail modal reliably.
- Improve thumb-size control range and make slider values visible for repeatable tuning.
- Reduce persistent live-mode micro-jitter after clusters arrange themselves.

### Completed in this sprint

1. 3D layout startup and data flow
- 3D mode reads layout positions from `/api/explorer/layout` and merges with attractor metadata.
- `loadData()` in 3D accepts/normalizes both layout-style and attractor-style payloads.
- Initial node positions now start from normalized rest coordinates (`_resetNodesToRest`) instead of settling from a sphere.

2. Better default sizing + wider size control
- Adaptive default node size now depends on collection size so large datasets start usable.
- Size slider range now supports very small values (`min=0.05`, `step=0.05`).
- Strength/Spread/Size now show live numeric values under each slider.

3. Persisted 3D view preferences
- Local settings persist strength, spread, size, focus/live/thumb visibility.
- Settings key version bumped to avoid stale old values during rollout (`inspirations.attractor3d.settings.v2`).

4. Thumb painting and overlay behavior
- Thumbnail overlay caps were removed for full visible-set painting behavior in current mode.
- Base colored tile is visually reduced when textured overlay is present to prevent color bleed.
- Overlay offset/scale were adjusted for clearer top-layer thumbnail rendering.

5. 3D click-to-modal reliability
- Pointer lifecycle handling now listens on both canvas and window for `pointerup`/`pointercancel`.
- Stale drag state is cleared defensively before click raycast.
- Cleanup now removes all pointer listeners on destroy.
- Modal open behavior in 3D was revalidated with pointer-sequence click paths.

6. Live jitter damping (calm-down behavior)
- Added adaptive calm state (`_liveCalm`) driven by average per-frame speed/force.
- Damping increases as the layout settles.
- Tiny residual velocity/force now falls into a deadzone (prevents constant “buzzing”).
- Collision pass now uses slop + softer impulses when calm to reduce chatter at near-contact.
- Calm state resets on load, attractor updates, and live toggle changes.

### Files updated in this sprint

- `app/attractor-explorer-3d.js`
- `app/styles.css`
- `app/index.html`
- `app/app.js`

### Verification status

- [x] 3D opens in precomputed multi-cluster shape.
- [x] Size slider supports very small values and shows numeric readout.
- [x] 3D click opens detail modal again.
- [x] Thumbs render in 3D without prior cap limits.
- [x] Live mode remains functional with calmer post-settle behavior.

---

## Next Sprint: 3D Fine Tune Plan

### Goal

Tune presentation quality and motion feel for both very large and smaller collections, without expanding scope into new interaction models.

### Scope assumptions

- Size buckets used for tuning decisions:
  - Small: `<= 300` visible items
  - Medium: `301-1500` visible items
  - Large: `> 1500` visible items
- Work stays frontend-only in `app/attractor-explorer-3d.js` + related UI files.
- Tuning uses existing controls and persisted settings model (no backend/API additions).

### Sprint backlog (fine-tuned and prioritized)

- [x] **P0: Live calm profile tuning by dataset size**
  - Primary code surface: `_forceTick()` and `_collisionPass()`.
  - Tune/possibly bucket these parameters: `damping`, `velEps`, `forceEps`, `slop`, `pushK`.
  - Add a small, documented parameter profile object in-code so values are easy to iterate without hunting constants.
  - Done when:
    - Live mode settles without persistent buzz after attractor changes.
    - Small/medium sets feel responsive; large sets do not look “frozen” during early settle.
    - No regression in click-to-open behavior while live mode is on.
  - Implemented tuning profile (bucketed by visible node count):
    - Small (`<= 300`): `damping 0.69→0.47`, `velEps 0.0055→0.0125`, `forceEps 0.0038→0.01`, `slopFactor 0.008→0.022`, `pushK 0.22→0.16`.
    - Medium (`301-1500`): `damping 0.66→0.44`, `velEps 0.006→0.015`, `forceEps 0.004→0.0115`, `slopFactor 0.01→0.03`, `pushK 0.24→0.15`.
    - Large (`> 1500`): `damping 0.68→0.50`, `velEps 0.005→0.0125`, `forceEps 0.0035→0.01`, `slopFactor 0.008→0.023`, `pushK 0.26→0.18`.
    - Calm responsiveness also bucketed (`speedHotNorm`, `forceHotNorm`, `calmLerp`) to keep large sets moving longer before entering fully calm damping.

- [x] **P0: Default node-size profile recalibration**
  - Primary code surface: `_defaultNodeSizeForCount()` and size slider initialization.
  - Revisit breakpoints and defaults to improve first-open readability by bucket.
  - Done when:
    - First-open density is readable in all three size buckets without immediate slider adjustment.
    - Existing manual size override behavior still wins over defaults.
  - Implemented defaults:
    - `>5500: 3.6`
    - `>4000: 4.2`
    - `>2500: 5.1`
    - `>1500: 6.0`
    - `>900: 6.9`
    - `>300: 8.0`
    - `<=300: 9.2`
  - Manual size overrides still persist and take precedence via local settings.

- [x] **P1: Thumb density/readability pass for small collections**
  - Validate that overlay scale/offset and spacing remain visually coherent for small sets.
  - Verify focused mode and thumb visibility toggle combinations for readability.
  - Done when:
    - Small collections do not look over-separated.
    - Thumbnails remain legible without heavy overlap in common camera angles.
  - Implemented bucketed thumb/collision presentation:
    - Small: `overlayScale=1.14`, `overlayOffset=0.18`, `baseTileWhenOverlay=0.025`, `collisionMinDistMul=0.98`.
    - Medium: `overlayScale=1.09`, `overlayOffset=0.22`, `baseTileWhenOverlay=0.02`, `collisionMinDistMul=1.06`.
    - Large: `overlayScale=1.04`, `overlayOffset=0.26`, `baseTileWhenOverlay=0.016`, `collisionMinDistMul=1.12`.

- [x] **P1: Optional named startup presets (time-boxed)**
  - Save/recall named looks: strength, spread, size, focused mode, live mode, thumbs.
  - Persist locally (new key version if needed), no server persistence.
  - Done when:
    - User can save, apply, and delete at least one named preset.
    - Existing default settings behavior remains intact for users who never create presets.
  - Implemented:
    - New controls row: `Looks` select + `Save` + `Delete` + `Startup` toggle.
    - Presets persisted in local storage key `inspirations.attractor3d.settings.v2` with `presets[]` and `startupPresetName`.
    - Startup preset auto-applies on load when selected.

- [x] **P1: Regression and sign-off sweep**
  - Re-run manual checks from this sprint plus new bucket checks.
  - Include one hard refresh verification for script cache busting (`attractor-explorer-3d.js?v=27` or latest version at time of implementation).
  - Done when:
    - No regressions on precomputed clustered open, modal click reliability, and slider readouts.
    - Final tuning values and rationale are captured in this doc.
  - Verified:
    - Hard refresh run once; script loaded as `attractor-explorer-3d.js?v=28`.
    - 3D mode fetched `/api/explorer/layout` and `/api/explorer/attractor-data?dims=2` with `200`.
    - Size slider readout still live at min (`0.05`).
    - 3D click still opens detail modal reliably (validated via canvas click path).
    - Test suite: `PYTHONPATH=src python3 -m unittest discover -s tests -q` → `Ran 160 tests`, `OK`.

### Suggested execution order

1. P0 calm profile tuning
2. P0 node-size recalibration
3. P1 small-collection readability pass
4. P1 named presets (only if P0 completes on schedule)
5. P1 regression/sign-off

### Explicitly not in next sprint scope (unless reprioritized)

- New framework dependencies.
- Replacing current attractor force model.
- Backend schema changes for 3D tuning.
