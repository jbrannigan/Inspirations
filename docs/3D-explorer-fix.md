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

### Backlog (prioritized)

- [ ] Tune live calming constants across dataset sizes.
  - This is the suggested improvement queued from this sprint.
  - Tune `damping` range, deadzone thresholds (`velEps`, `forceEps`), and collision calm parameters (`slop`, `pushK`) for smoother settle with minimal drift.

- [ ] Calibrate default open-size profile by item count.
  - Validate current defaults against multiple collection sizes and adjust breakpoints.

- [ ] Add optional named startup presets.
  - Store/recall “good looks” (strength, spread, size, focus/live/thumbs) for faster iteration.

- [ ] Validate thumb density vs readability on smaller collections.
  - Ensure large-collection improvements do not over-separate or under-fill small sets.

### Explicitly not in next sprint scope (unless reprioritized)

- New framework dependencies.
- Replacing current attractor force model.
- Backend schema changes for 3D tuning.

