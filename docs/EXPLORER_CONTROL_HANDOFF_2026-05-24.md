# Explorer Control Handoff - 2026-05-24

## Current decision

Sidebar filters and text search define the base item scope. The Explorer
category drawer can further refine or arrange that scope through the
`Filter / Group` switch.

In 3D Explorer, `Group by` is a shortcut arrangement control:

- `None` shows the current sidebar/search scope in its normal layout.
- `Source`, `Room`, `Style`, `Material`, `Color`, and `Product` recompute grouping poles from the current visible scope.
- Changing `Group by` should not change global filters, sidebar state, or the grid/card scope.
- `Clear grouping` returns the same current scope to the ungrouped layout.

The category drawer is explicit:

- `Filter` means selected category chips reduce the visible item set.
- `Group` means selected category chips become attractor/grouping poles without
  changing the base sidebar/search scope.
- The active grouping strip shows the currently active grouping poles.

## Implementation notes

Changed files:

- `app/attractor-explorer-3d.js`
  - Added `_groupByKey`, group-by specs, scope recomputation helpers, and group-by selector wiring.
  - Restored the 3D `Categories` drawer and `Filter / Group` switch after a
    regression where the drawer was removed from the toolbar-mounted 3D controls.
  - Category chips now either filter or group depending on that switch.
  - `setFilter()` and `setSearch()` now rebuild the visible node set instead of dimming non-matching nodes.
- `app/styles.css`
  - Added compact `Group by` select and `Clear grouping` button styling.
  - Moved Explorer controls into the toolbar instead of a floating canvas overlay.
  - Increased chip contrast and added a panel background for the toolbar-mounted
    Categories drawer.
- `app/app.js`
  - Bumped the lazy-loaded 3D module to `attractor-explorer-3d.js?v=59`.
  - Adjusted the Explorer mode chip so full 3D scope says `3D map`, while filtered scope says `3D subset`.
  - Moved the card-view text filter into the top toolbar and made `Clear filters` clear sidebar/status/text scopes, not just text.
- `app/index.html`
  - Current cache versions: `styles.css?v=60`, `attractor-explorer.js?v=15`, and `app.js?v=116`.

## Current test target

Server should be available on LAN via:

```bash
./tools/run_review_server.sh
```

That script launches Inspirations on `0.0.0.0:8001`, so iPad/iPhone testing should use the Mac's LAN IP, for example:

```text
http://192.168.0.101:8001
```

## Manual test checklist

1. Open Explorer on desktop and confirm the 3D control row includes `Categories`, `Filter / Group`, and `Group by`.
2. Use sidebar classification/source filters and confirm the item count and visible 3D nodes shrink to the filtered scope.
3. In 3D, choose `Group by: Style`, then `Color`, then `Source`; confirm clusters rearrange but the sidebar/grid filter scope does not change.
4. Click `Clear grouping`; confirm the same filtered scope remains visible.
5. On iPad, apply a sidebar/text filter that produces a small enough subset for 3D and confirm the mode chip updates to 3D subset and drag-to-rotate works.
6. On iPad, apply a broad filter and confirm it remains in 2D full-map mode rather than crashing Safari.

## Verification run

Commands run after the change:

```bash
node --check app/app.js
node --check app/attractor-explorer.js
node --check app/attractor-explorer-3d.js
git diff --check
curl -s --max-time 5 'http://127.0.0.1:8001/' | rg -n 'styles\.css\?v=|attractor-explorer\.js\?v=|app\.js\?v='
curl -s --max-time 5 'http://127.0.0.1:8001/app/app.js?v=111' | rg -n 'EXPLORER_3D_MODULE_URL'
curl -s --max-time 5 'http://127.0.0.1:8001/app/attractor-explorer-3d.js?v=56' | rg -n 'Group by|_setGroupBy|_scopeNodesWithoutGrouping'
```

All checks passed.

## Open follow-up

The 2D attractor map still has the older category pill/filter-group control model. If the next goal is full harmonization across 2D and 3D, port this same `Group by arranges scope` model into `app/attractor-explorer.js`.

## Follow-up update

A later UX pass moved the Explorer controls into the shared persistent curation
bar, removed the duplicate card-view `Categories` mini-panel, and clarified the
lazy-loading count wording from `120 of 4666 items` to `120 loaded of 4666
items`.

## Follow-up update - 2026-05-25

Jim clarified that the tuning sliders were not supposed to disappear, and that
grouping needs a visible representation beyond the `Group by` dropdown.

Implemented:

- `app/attractor-explorer-3d.js`
  - Restored visible tuning controls in the toolbar.
  - Replaced passive numeric labels with editable number inputs for `Strength`,
    `Spread`, `Size`, and `Anchor`.
  - Added an `attractor-active-groups` strip that shows the current grouping
    poles as active chips, for example `Grouped by Style`.
  - Keeps grouping chips read-only; sidebar/text filters still define scope.
- `app/attractor-explorer.js`
  - Added matching slider-plus-number controls for the 2D attractor map.
  - Kept the older 2D `Categories` / `Filter` / `Group` model intact for now.
- `app/styles.css`
  - Removed the toolbar rule that hid slider value controls.
  - Added compact desktop styling and larger touch affordances under
    `@media (pointer: coarse)`.
  - Added styles for visible 3D grouping chips.
- `app/app.js`
  - Replaced the hard-coded iPad 3D cutoff with a measured mobile WebGL budget.
    The benchmark renders point batches in a hidden WebGL canvas, applies safety
    factors for viewport/texture constraints, and caches the result per session.
  - The iPad mode chip now calls broad mode `iPad lite: 2D map` and explains
    the measured 3D budget in its title.
  - Fixed a mode-switch cleanup bug: when switching from 2D lite to 3D subset,
    the previous explorer implementation is now destroyed before `_ExplorerImpl`
    is reassigned. This prevents duplicate 2D and 3D control rows.
- `app/index.html`
  - Current cache versions: `styles.css?v=59`, `attractor-explorer.js?v=13`,
    `app.js?v=113`.
- `app/app.js`
  - Current 3D lazy module version: `attractor-explorer-3d.js?v=57`.

Current mobile behavior:

- Broad iPad/narrow viewport sets open in `iPad lite: 2D map`.
- Applying a text/sidebar filter measures the device budget and switches to 3D
  only when the filtered subset is within that measured budget.
- The 2D fallback should now be treated as lite/emergency mode, not the desired
  steady-state for explorable subsets.

Browser smoke run:

- Desktop Explorer loaded `app.js?v=112`/`v=113`, `styles.css?v=59`, and
  `attractor-explorer-3d.js?v=57`.
- 3D toolbar showed four visible editable number inputs and four ranges.
- Selecting `Group by: Style` showed seven active grouping chips and enabled
  `Clear grouping`.
- `Clear grouping` hid the active group strip and reset the selector to `None`.
- Narrow viewport `820x768` opened as `iPad lite: 2D map (4666 items)` with
  visible 2D number inputs and no toolbar overflow.
- Filtering text to `exterior` switched to `3D subset: 1158 items - drag to rotate`.
- After the 2D-to-3D switch, only one Explorer control instance remained.
- `Group by: Style` after the mobile switch showed seven grouping chips and no
  toolbar overflow.

## Follow-up correction - 2026-05-25

Jim reported three regressions:

- Categories did not show on iPad.
- Category chips were too low-contrast on Mac.
- The Mac 3D view no longer had a Filter/Group switch.

Fixed:

- Restored the 3D `Categories` button and drawer.
- Restored the 3D `Filter / Group` switch.
- Default-opened useful category sections (`Source`, `Rooms`, `Style Family`,
  `Materials`, `Colors`) so the drawer exposes actual chips immediately,
  especially on iPad.
- Increased chip contrast and made active chips dark text on a gold background.
- Kept `Group by` as an automatic grouping shortcut; manually clicking category
  chips clears `Group by` and uses the explicit `Filter / Group` mode.

Latest smoke:

- Desktop 3D loaded `app.js?v=115`, `styles.css?v=60`, and
  `attractor-explorer-3d.js?v=59`.
- Desktop 3D Categories drawer opened with 80 chips and default-open sections.
- Desktop 3D showed the `Filter / Group` switch.
- Group mode plus `Pinterest` chip showed `Grouped categories` with an active
  high-contrast `Pinterest` chip.
- Narrow `820x768` mode showed `iPad lite: 2D map (4666 items)`, Categories
  open, `Filter / Group`, 80 chips, and default-open sections.

## Follow-up correction - 2026-05-25, iPad mode/count hint

Jim reported that the iPad hint text still said the old 2D/3D mode and full
item count after filters were applied, even though the visible map had changed.

Fixed:

- `app/app.js` now treats internal category selections as filtered scope only
  when the Explorer is in `Filter` mode, not `Group` mode.
- The iPad mode/count chip clears temporary status overrides after a filter
  applies and refreshes from `_explorerFilterCount`.
- The 2D attractor map now reports `categoryMode` so `Group` chips do not make
  the app-level hint behave like the global scope changed.
- Current cache versions: `attractor-explorer.js?v=15`, `app.js?v=116`,
  `styles.css?v=60`, and lazy `attractor-explorer-3d.js?v=59`.

Latest smoke:

- Narrow `820x768` mode loaded as `iPad lite: 2D map (4666 items)`.
- Opening `Categories` and selecting `Pinterest` updated the hint to
  `iPad lite: 2D map (3766 items)`.
- The top stats text also updated to `3766 items`.

## Follow-up update - 2026-05-26, sidebar Refine By facets

Jim reported that `Style` values such as `Mission` had effectively vanished:
Explorer had a `Style Family` category, but the sidebar did not expose the same
dimension, and both Explorer drawers and the sidebar had been silently clipping
some groups to a top-N subset.

Implemented:

- Sidebar `Classification` is now `Refine By`.
- Refine By choices are stackable filters, not exclusive browse scopes.
  Source/board/collection scope can remain active while Room, Style, Material,
  Color, etc. are layered on top.
- Backend `/api/assets` and `/api/asset-ids` now accept repeated
  `facet=axis:value` params:
  - values within one axis are OR
  - different axes are AND
  - legacy `classification_axis` / `classification_value` still works
- `Style`, `Materials`, and `Colors` now appear in the sidebar using the same
  legacy metadata extraction as Explorer.
- `Spanish / Mission` is the display label for the canonical `spanish` style.
- Explorer category drawers now show all available chips in each category
  instead of silently slicing to a hidden top-N.

Current cache versions:

- `styles.css?v=61`
- `attractor-explorer.js?v=16`
- `app.js?v=117`
- lazy `attractor-explorer-3d.js?v=60`

Latest smoke:

- Browser sidebar showed `Refine By`, `Style`, `Materials`, and `Colors`.
- Expanded `Style` and confirmed all 20 style chips were visible, including
  `Spanish / Mission`.
- Toggled `Kitchen` and `Spanish / Mission`; the summary showed
  `Refine: Kitchen, Spanish / Mission` and both leaves stayed active.
- `Clear filters` removed both active facet selections.
