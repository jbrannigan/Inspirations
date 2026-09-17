# Inspirations frontend

Vanilla HTML/CSS/JS, no build step. Loads when working under `app/`.

## Three workflows

1. **Browse + Review** — collections as tile grids, filter the usable corpus,
   optionally reveal muted discarded items, enter focused review for QC.
2. **Attractor Explorer** — semantic visualization, 2D (`attractor-explorer.js`,
   canvas + D3 forces) or 3D (`attractor-explorer-3d.js`, Three.js WebGL).
   `app.js` handles view switching, filter sync, and the iPad fallback budget.
3. **Collection PDF export** — exactly one selected collection, self-contained.

## UI rules that get violated by accident

- **The mode header is stable.** Entering Review or Make Collection must not
  reshape the global app header. Each mode adds its own action row inside the
  shared sticky curation bar.
- **Advanced repair belongs to Review only.** Title repair, media repair, and
  Track Review controls appear in Review context (grid Review and the one-by-one
  `Edit title / media` action). Browse must never show those panels — Browse card
  clicks open the calmer detail view.
- **One flag affordance per card.** Flagged cards use a single persistent brown
  `Unflag follow-up` button as both indicator and action. Do not add a second
  flag badge.
- **Media repair is reversible.** The `Repair media` gallery includes previously
  used saved media from the audit log, so picking a generated text card or source
  image never destroys the curator's recovery path.
- **Category chips have explicit `Filter` vs `Group` semantics.** Filter narrows
  the visible set; Group rearranges the current scope *without* touching
  global/sidebar filters. 3D adds a `Group by` shortcut over the same rule.
- **Append means append.** Lazy-loaded pages append only newly fetched cards —
  never call full `renderGrid()` from the append branch. Full rerenders are for
  scope/filter/state changes that invalidate existing cards.
- **Pagination lifecycle:** set the button and top item count to loading state as
  soon as an asset request begins; keep the final refresh calls *after*
  `state.loadingAssets = false`; always honor a queued full reload once an append
  or non-append request finishes.
- Item-visibility scopes live in `Browse → Review Status` (Usable, Flagged,
  Keepers, Needs comment, Irrelevant/Discarded, All including discarded) — not in
  the top bar, and they refine the current scope rather than reviving the old
  review-queue backlog.

## iPad

Explorer controls sit in the persistent curation bar with editable numeric values
beside the tuning sliders. Broad sets on mobile-constrained devices fall back to
`iPad lite: 2D map`; filtered subsets switch back to 3D when the measured
per-session WebGL budget allows. The mode/count hint must update when filters
change, including in 2D fallback.

## Reverse proxy

Every `fetch()` and `/media/` URL goes through `Shared.prefixPath(path)` or
`Shared.basePath`. Hardcoded absolute paths break `BASE_PATH` deployments behind
the New Home site with no visible error locally.
