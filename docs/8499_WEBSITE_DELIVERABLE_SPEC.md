# 8499TimberBridgeLn.com: Design Inspiration Deliverable

> Legacy note (2026-06-03): this website-deliverable direction is historical.
> D021 made a standalone one-collection PDF the active designer handoff. The
> separate Home website on port `8003` remains outside Inspirations.

**Date:** 2026-03-08 (updated after reviewing actual website project)
**Author:** Jim Brannigan (with Claude)
**Site status:** Live Next.js 16 app, Cloudflare tunnel on port 8003, Tufte-inspired design
**Goal:** Make it effortless for Leslie to share curated design inspiration and construction reference material with the project team through the existing 8499TimberBridgeLn.com website.

---

## The Problem

Leslie has 5,000+ design inspirations across Pinterest, Facebook, Houzz, and magazine scans. When she meets with the interior designer about the kitchen, or the cabinet maker about door styles, or the architect about the floor plan, she needs to say "go look at my ideas for this" and have the collaborator see a clean, organized, trustworthy presentation of her taste.

Today, producing that requires Jim to run export commands in a terminal. That's not sustainable for the number of collaborators and conversations that a house build generates. It needs to be easy enough that Jim can produce a new shareable view in minutes, not hours, and ideally that Leslie could trigger it herself.

---

## What Already Exists (discovered 2026-03-08)

The 8499TimberBridgeLn.com website is further along than originally assumed. Key infrastructure is already in place:

### The site stack
- **Next.js 16** (App Router) with server-side rendering
- **Tufte-inspired design** — ET Book/Palatino serif, warm off-white (#fffff8), high data-ink ratio, 800px content width
- **Magic-link auth** bridged from the Inspirations SQLite `actors` table
- **Role-based access control** — owner, architect, builder, legal, landscape roles
- **Cloudflare tunnel** serving on port 8003
- **Explicit document manifest** (`documents-config.json`) for role-gated file access

### Existing inspiration pages
Two pages already exist and render correctly:

- `/design-goals` → reads `public/data/curated-style.json`
- `/construction-goals` → reads `public/data/curated-construction.json`

Both are **commented out in the nav** (lines 37-38 of `layout.tsx`) but fully functional. They render a responsive image grid (350px min columns) with figcaptions containing star ratings, descriptions, tags, and Pinterest source links.

### Existing content
- **30 inspiration images** already in `public/inspirations-images/` (bathroom series)
- **`curated-style.json`** — 3 categories (Bathroom variations), ~35 items with AI-generated descriptions, ratings, tags
- **`curated-construction.json`** — exists but less populated

### The JSON schema (already working)

```json
{
  "title": "Curated Style Inspiration (Best Of)",
  "categories": [
    {
      "name": "Bathroom",
      "description": "The predominant aesthetic leans towards...",
      "items": [
        {
          "id": "bathroom-1",
          "imageUrl": "/inspirations-images/bathroom-1.jpg",
          "sourceUrl": "https://www.pinterest.com/pin/87116574031817225/",
          "rating": "⭐⭐⭐⭐",
          "description": "This item showcases a broad range of style elements...",
          "tags": ["bathroom", "bathroomdesign", "marble", "transitional", ...]
        }
      ]
    }
  ]
}
```

This is the target format. The Inspirations export pipeline needs to produce JSON matching this schema, not standalone HTML.

---

## Audience & Access Model

### The team

| Role | What they need to see | Example questions |
|------|----------------------|-------------------|
| **Interior designer** | Style inspiration by room — finishes, colors, furniture, fixtures, lighting | "What's her kitchen aesthetic? Does she lean traditional or modern?" |
| **Architect** | Floor plan references, exterior style, spatial preferences | "What exterior styles is she drawn to? How does she think about the entry sequence?" |
| **Landscape architect** | Garden, outdoor living, exterior context | "What outdoor spaces does she like? What's the relationship to the house?" |
| **Builder** | Construction concerns, material preferences, practical decisions | "What insulation approach? Any foundation concerns? Roofing preferences?" |
| **Cabinet maker** | Cabinet styles, hardware, finishes, specific product references | "Shaker or raised panel? What hardware finish? Any specific brands?" |
| **HVAC company** | System preferences, efficiency concerns | "Any preferences on system type? Zoning requirements?" |
| **Legal / construction admin** | Not inspiration — bid docs, contracts (separate section of site) | N/A for this spec |

### Access levels

The site already has two-tier access via magic-link auth and RBAC:

1. **Public pages** — Anyone with the URL can view. The design-goals and construction-goals pages should be public (no auth required). Leslie should be able to text a link to the cabinet maker and have it just work.
2. **Team pages** — Behind magic-link auth. For bid documents, contracts, and anything with financial or personal details. Already implemented via the Files page and `documents-config.json`.

**Decision needed:** Should design-goals/construction-goals require auth or be public? The current auth middleware can be configured per-route. For maximum ease of sharing, make inspiration pages public. The role-based system still lets you restrict sensitive pages.

---

## Information Architecture

The two-track split already exists in the site's page structure. The Inspirations export pipeline populates the JSON files; the website renders them.

### Branch 1: Design Goals (`/design-goals`)

Currently renders `public/data/curated-style.json`. Expand categories to cover:

| Category | Source signal | Approximate corpus size |
|----------|-------------|------------------------|
| Kitchen | board = kitchen | 269 Pinterest + 56 Facebook + 26 Houzz + 18 scans |
| Master Bath | board = bathroom (filtered) | ~200 items (subset of 502 bathroom pins) |
| Guest Bath | board = bathroom (filtered) | ~100 items |
| Bedroom | board = bedroom | ~150 items |
| Entry & Doors | board = door, entry | ~80 items |
| Exterior | board = exterior, french-colonial | ~120 items |
| Outdoor Living | board = porches, outdoor | ~60 items |
| Flooring | board = flooring | ~80 items |
| Lighting | board = lighting | ~70 items |
| Cabinetry | board = cabinetry, cabinet | ~60 items |
| Paint & Color | board = paint, color | ~50 items |
| Fireplace | board = fireplace | ~40 items |
| Trim & Millwork | board = crown, wainscoting, trim | ~30 items |
| General Style | cross-cutting — French Colonial, transitional | curated selection |

Each category gets a `description` field (2-3 sentences characterizing Leslie's direction) and its curated `items` array.

### Branch 2: Construction Goals (`/construction-goals`)

Currently renders `public/data/curated-construction.json`. Expand categories:

| Category | Source signal | Notes |
|----------|-------------|-------|
| Floor Plans | board = house-plans | Plan references and spatial ideas |
| Foundation & Structure | board = foundation, building | Structural decisions |
| Insulation & Envelope | board = insulation, roofing | Energy efficiency, weatherization |
| HVAC & Systems | board = hvac, generator, propane | Mechanical systems |
| Plumbing & Water | board = plumbing, well, septic | Water systems |
| Site Work | board = grading, drainage, site | Well, septic, grading |
| Materials & Specs | cross-cutting | Specific product references |
| Building Tips | Facebook construction boards | Practical construction wisdom |

For construction items, `description` should emphasize practical content. If the underlying Facebook post has text (`post_text`), include it in the item description. Construction is about information, not aesthetics.

---

## How Pages Get Produced

### The pipeline: Inspirations → JSON → Website

The export pipeline produces JSON files that the website already knows how to render. No new website code is needed for the basic flow.

**New CLI command in Inspirations:**

```bash
PYTHONPATH=src python3 -m inspirations export site-json \
  --track style \
  --output /path/to/New-Home/prototype-web/public/data/curated-style.json \
  --images-dir /path/to/New-Home/prototype-web/public/inspirations-images/
```

```bash
PYTHONPATH=src python3 -m inspirations export site-json \
  --track construction \
  --output /path/to/New-Home/prototype-web/public/data/curated-construction.json \
  --images-dir /path/to/New-Home/prototype-web/public/inspirations-images/
```

**What the command does:**

1. Queries the Inspirations database for items matching the track (style or construction)
2. Groups items by room/category using the `canonical_board` mapping (from Last Try Part 2) and room assignments
3. For each category, generates a description (from taste profile data or passed as `--intro`)
4. For each item, produces the JSON record: `{id, imageUrl, sourceUrl, rating, description, tags}`
5. Copies the needed images (thumbnails at display resolution) to the website's `public/inspirations-images/` directory, using a naming convention like `{category}-{n}.jpg`
6. Writes the complete JSON file

**Image handling:** Copy images from Inspirations `store/` to the website's `public/inspirations-images/`. The JSON references them as `/inspirations-images/{filename}`. This is already the working pattern — 30 images are already served this way.

### Workflow for Jim (Option A — CLI)

1. Run the Last Try curation pass (see `LAST_TRY_CURATION_SPEC.md`) to get clean, track-assigned data
2. Run `export site-json --track style` → produces `curated-style.json` + copies images
3. Run `export site-json --track construction` → produces `curated-construction.json` + copies images
4. Uncomment the nav links in `layout.tsx` (lines 37-38)
5. The Cloudflare tunnel serves it immediately — no deploy step needed

Total time after initial setup: ~30 seconds per regeneration.

### Workflow for Leslie (Option B — future)

1. Open the Inspirations app on her phone/tablet (LAN access already works)
2. Browse to the room or topic she wants to share
3. Enter canvas review mode — tap images she wants to include (gold border)
4. Hit "Share to Site" → enters a title ("Kitchen Ideas for Sarah") → generates the JSON + copies images
5. Gets a URL she can text: `https://8499timberbridgeln.com/design-goals`

This requires a new "Share to site" feature in the Inspirations app. Start with Option A, build toward Option B.

---

## Enhancing the Existing Pages

The current `design-goals/page.tsx` and `construction-goals/page.tsx` are functional but could be improved. These are suggestions, not blockers for the MVP.

### Short-term improvements (do alongside export pipeline)

1. **Uncomment nav links** — lines 37-38 of `layout.tsx`. One-line change.
2. **Source link text** — Currently hardcoded as "Pinterest Source" even for Facebook/Houzz items. Change to derive from `sourceUrl` domain or add a `source` field to the JSON schema.
3. **Category navigation** — Add a table of contents at the top of each page (anchor links to each category `<h3>`). When there are 10+ categories, scrolling to find "Cabinetry" is tedious.
4. **Image click-to-enlarge** — Currently images render at grid size only. Add a simple lightbox (CSS-only or minimal JS) for inspecting design details at full resolution.
5. **Print stylesheet** — A designer might print these to pin on their own board. The Tufte design already prints well, but ensure the grid doesn't break across pages.

### Extended JSON schema

Add optional fields to support construction items and richer metadata:

```json
{
  "id": "kitchen-12",
  "imageUrl": "/inspirations-images/kitchen-12.jpg",
  "sourceUrl": "https://www.pinterest.com/pin/...",
  "source": "pinterest",
  "rating": "⭐⭐⭐⭐",
  "description": "Traditional-transitional kitchen with warm wood island...",
  "postText": "Article excerpt or Facebook post text for construction items...",
  "tags": ["kitchen", "marble", "brass", "transitional"],
  "assetId": "a1b2c3d4"
}
```

New fields: `source` (pinterest/facebook/houzz/scan), `postText` (for construction items where the article text matters more than the image), `assetId` (8-char prefix linking back to Inspirations database for traceability).

The existing page components would need minor updates to render `postText` and derive source link labels from the `source` field.

---

## Image Serving

**Already solved.** The pattern is established:

- Images live in `prototype-web/public/inspirations-images/`
- JSON references them as `/inspirations-images/{filename}`
- 30 images already served this way
- Next.js serves static files from `public/` with no configuration needed

**The export command's responsibility:**
- Copy thumbnails (512px wide — enough for the 350px grid columns with retina support) from Inspirations `store/thumbs/` to the website's `public/inspirations-images/`
- Use descriptive filenames: `kitchen-1.jpg`, `master-bath-14.jpg`, `hvac-3.jpg`
- Optionally copy originals to `public/inspirations-images/full/` for a future lightbox feature
- For ~40 items per category across ~14 categories, that's ~560 images total — well within static serving limits

---

## Minimum Viable Deliverable

### What to build in the Inspirations project

1. **`export site-json` CLI command** — queries database, groups by category, generates JSON matching the existing schema, copies images
2. **Category-to-room mapping** — maps the `canonical_board` values (from Last Try Part 2) to the website category names listed above
3. **Description generation** — either accept `--intro` text per category, or auto-generate from Gemini taste profiles (the descriptions in the existing `curated-style.json` are a good template)
4. **Image copy utility** — copies selected thumbnails to the target directory with clean filenames

### What to change in the website project

1. **Uncomment nav links** — `layout.tsx` lines 37-38
2. **Optional: source link label** — derive from `source` field instead of hardcoded "Pinterest Source"
3. **Optional: category TOC** — anchor links at page top
4. **No new pages needed** — the existing pages render whatever JSON you give them

### First content to produce

1. **Kitchen** — Leslie's most-saved room. Curate to ~30-40 best items.
2. **Master Bath** — Second-most-saved. ~30 items.
3. **Exterior / French Colonial** — The architectural direction. ~20-30 items.
4. **General Style** — Cross-cutting "Leslie's overall aesthetic." ~20 items.

These four categories in `curated-style.json` would give the interior designer enough to work with for initial meetings. Construction categories can follow as those collaborators come on board.

---

## Relationship to Mood Board Vision

The JSON-driven gallery pages are the **practical deliverable** — they work today with existing infrastructure. The mood board vision (see `VISION_AI_CURATION_SYNTHESIS.md`) describes a future where the system generates synthesized taste profiles, AI-curated representative selections, and composite mood boards.

If that vision materializes, the mood boards could become additional data in the JSON:

```json
{
  "title": "Curated Style Inspiration",
  "moodBoard": {
    "heroImage": "/inspirations-images/mood/kitchen-synthesis.jpg",
    "narrative": "Leslie's kitchen aesthetic centers on traditional-transitional spaces...",
    "colorPalette": ["#8B7355", "#F5F0EB", "#C8A882", "#2F4538", "#D4A574"]
  },
  "categories": [ ... ]
}
```

The page component would render the mood board section at the top, followed by the full gallery. The gallery pages are the foundation; the mood boards are the aspiration.

---

## Technical Notes

### Integration points

| Concern | Resolution |
|---------|-----------|
| Where does the website project live? | Configure path in Inspirations `config/` or pass as `--output` / `--images-dir` CLI args. Both projects live on the same machine. |
| JSON schema compatibility | Export must produce the exact schema the existing pages expect. See "Extended JSON schema" above for backward-compatible additions. |
| Image paths | Always relative: `/inspirations-images/{filename}`. The export command writes images to the target directory. |
| Auth for inspiration pages | Decision: public (no auth) for design-goals/construction-goals. The magic-link system stays for Files, Admin, etc. |
| Deployment | No deploy step — Cloudflare tunnel serves the Next.js dev server (or production build) on port 8003. Changes to `public/` are picked up automatically. |

### File structure (existing, to be populated)

```
New Home/prototype-web/
  public/
    data/
      curated-style.json          ← Inspirations export target
      curated-construction.json   ← Inspirations export target
    inspirations-images/
      bathroom-1.jpg              ← 30 existing images
      kitchen-1.jpg               ← new images from export
      master-bath-1.jpg
      ...
  src/app/
    design-goals/page.tsx         ← Already renders curated-style.json
    construction-goals/page.tsx   ← Already renders curated-construction.json
    layout.tsx                    ← Uncomment lines 37-38 for nav
```

### Ongoing maintenance

When Leslie saves new items or Jim re-runs curation:

```bash
# From the Inspirations project directory:

# Regenerate both tracks
PYTHONPATH=src python3 -m inspirations export site-json \
  --track style \
  --output ../New\ Home/prototype-web/public/data/curated-style.json \
  --images-dir ../New\ Home/prototype-web/public/inspirations-images/

PYTHONPATH=src python3 -m inspirations export site-json \
  --track construction \
  --output ../New\ Home/prototype-web/public/data/curated-construction.json \
  --images-dir ../New\ Home/prototype-web/public/inspirations-images/
```

This should be a one-command operation (or two, one per track). The goal is for Jim to be able to say "Leslie saved some new kitchen ideas, let me update the site" and have it take 30 seconds.

### Dependencies on Last Try Curation

The export pipeline depends on several outputs from the Last Try curation spec:

- **Part 1 (Junk removal):** Hidden items must be excluded from export
- **Part 2 (Facebook consolidation):** `canonical_board` provides clean category assignments
- **Part 5 (Two-track split):** The `track` column (style/construction/both) determines which JSON file each item appears in
- **Part 4 (Title source):** Helps the export choose better descriptions — prefer `original` titles over `seo_alt_text`

The Last Try pass should be completed before building the export pipeline. The four MVP categories (kitchen, master bath, exterior, general style) can be produced with manual filtering even before the full Last Try pass, if timing requires it.
