# Card Content Plan (Pinterest + Facebook)

## Goal
Cards should feel like *rich snapshots* of the original source while remaining clean and scannable.

## Pinterest cards — content model
**Primary (always visible)**
- Pin image (thumbnail)
- Pin title (from `title` / `grid_title` / `seo_title`)
- Board name (e.g., “Kitchen”)
- Source site/domain (e.g., `architecturaldigest.com`)

**Secondary (expand on tap)**
- Description / auto alt text
- Creator profile name + link (if available)
- Pin date (created_at)
- Original Pin link (pinterest.com/pin/…)
- Source URL (original website)
- AI tags (labels)
- Notes count + annotation badge

**MVP data sources**
- JSON from crawler: `seo_url`, `image.url`, `title`, `grid_title`, `seo_title`, `board.name`, `created_at`, `sourceUrl`/`domain`

## Facebook saved items — content model
**Primary**
- Preview image (best-effort og:image or external_context.source)
- Saved title (from `title`)
- Source domain / name

**Secondary (expand on tap)**
- Saved timestamp (converted to local date)
- Original URL
- AI tags
- Notes count + annotation badge

**MVP data sources**
- `your_saved_items.json`: `title`, `timestamp`, `attachments[].data[].external_context` (`source`, `name`, `url`)

## UX behaviors (shared)
- Cards open a detail modal with:
  - full image
  - source link
  - annotations (drag + edit)
  - general notes
- “Badges” show: `source` (Pinterest/Facebook/Scan), notes count, and optional tag chips.
- “Expand” toggles show/hide secondary content.

## Badge color standard (selected)
Chosen option: **Solid violet** for annotation badges
- Border: `#2B2B30`
- Fill: `#6F5AA8`
- Text: `#F2F2F6`
- Shadow: `rgba(111,90,168,0.35)`
- Meets WCAG guidance for text and non‑text contrast.

## Implementation steps (next)
1. Extend DB to store:
   - `source_domain` (both)
   - `source_url` (original website)
   - `creator_name` (Pinterest if available)
2. Update importers to populate these fields.
3. Update UI cards to show Primary fields and toggle Secondary.
4. Add per‑source card templates.
