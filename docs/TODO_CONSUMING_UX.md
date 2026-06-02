# TODO: Consuming UX (Shared Collection Viewer)

**Status:** Legacy planning note. Superseded on 2026-05-27 by the current
direction: Jim keeps Inspirations as a local corpus/QC app and shares one
collection at a time via standalone PDF export. See
`docs/COLLECTION_PDF_EXPORT_HANDOFF_2026-05-27.md`.

## The Question

When a curated collection is shared with a designer or decorator, what does
their experience look like? The current system exports static HTML files with
source links. But what *should* the consuming experience be?

## What We Know

- The curator (Leslie) uses the local app to scrape, triage, organize, and annotate
- The consumer (decorator/designer) receives a curated set of inspiration images
- Each image links back to the original Pinterest pin or Facebook post
- Some images will have point-based annotations with notes

## Open Design Questions

1. **Format** — Is a single HTML file sufficient? A hosted web page? A PDF?
2. **Navigation** — How does the viewer browse? Grid? Swipe? Categories?
3. **Interaction** — Can they comment? Star favorites? Or purely view-only?
4. **Device** — Optimized for desktop? iPad? Both?
5. **Freshness** — One-time snapshot or does it update as the curator makes changes?
6. **Access control** — Password? Link-only? Login?

## Existing Capability

The pre-rebuild system had two export modes:
- `export html` — Single-file gallery with cards and detail modals
- `export portal` — Browse-only static portal with search/filter

Both are preserved in the codebase and can serve as starting points. See
`docs/archive/` for the old documentation on these features.

## When to Work on This

After the scrape-first rebuild is complete and the triage workflow is functional.
The curator needs to be able to curate before we design how curated sets are consumed.
