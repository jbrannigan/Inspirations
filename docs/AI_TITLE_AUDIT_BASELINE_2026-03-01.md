# AI Title Audit Baseline - March 1, 2026

## Scope

- Dataset: `data/inspirations.sqlite`
- Table: `assets`
- Rows scanned: 5306
- Method: local regex-based audit matching current UI title-quality rules in `app/app.js`

## Topline counts

- Empty titles: 72
- Junk short-domain titles (examples: `BlueHost.com`): 54
- Facebook generic saved-link titles: 40
  - Classified `Dynamic Link`: 25
  - Classified `Title Check`: 15
  - Saved-link rows with slug-derived fallback title possible: 29

## Source mix (all assets)

- Facebook: 1190
- Houzz: 226
- Pinterest: 3783
- Scan: 107

## Triage status mix

- Unset: 4662
- Hidden: 644

## Example buckets

### Empty titles (sample)

- `11433f8a` - facebook - `https://www.facebook.com/reel/890879477131603/`
- `43e15de0` - facebook - `https://www.facebook.com/groups/builderbrigade/posts/1949207169318060/`
- `14b91e39` - facebook - `https://www.facebook.com/reel/1717023212605127/`

### Junk short-domain titles (sample)

- `0d57f652` - pinterest - `click.com.cn`
- `5a6b07c3` - pinterest - `BlueHost.com`
- `773a06e5` - pinterest - `Coveandgrey.com`

### Facebook saved-link dynamic examples (sample)

- `64243998` - `Leslie Brannigan saved a link from Xbox Magazine's post.`
  - source_ref: `https://www.gamesradar.com/following-xbox-deal-embattled-activision-ceo-bobby-kotick-will-stay-through-the-end-of-2023-at-phil-spencers-request`
- `cafdffbe` - `Leslie Brannigan saved a link from NDS's post.`
  - source_ref: `https://www.drain-it-now.com`
- `06ff0331` - `Leslie Brannigan saved a link from Architectural Designs - House Plans's post.`
  - source_ref: `https://www.architecturaldesigns.com/couponcode`

### Facebook saved-link title-check examples (sample)

- `96947044` - `Leslie Brannigan saved a link from Epicurious's post.`
- `7f1009cb` - `Leslie Brannigan saved a link from Popular Mechanics's post.`
- `71f221d3` - `Leslie Brannigan saved a link from NYT Cooking's post.`

## Initial replacement workflow proposal (draft)

1. Auto-replace only high-confidence cases (no human review first pass):
   - empty title + non-empty `ai_summary` or `seo_alt_text`
   - junk short-domain title where source URL slug yields a non-numeric readable phrase
2. Flag-for-review queue (human-in-loop):
   - all `Dynamic Link` saved-link titles
   - saved-link titles where slug fallback is weak/empty
3. Keep-as-is bucket:
   - `Title Check` rows unless user explicitly requests rewrite

## Open decisions for morning

- Should auto-replacements write directly to `assets.title` or into a sidecar candidate table first?
- Do we include hidden items in the first replacement pass?
- What confidence threshold should gate auto-apply vs review queue?
