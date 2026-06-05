# Last Try: Final Automated Curation Pass

> Historical implementation spec (2026-06-03): this completed curation pass is
> useful provenance, but its collaborator-facing deliverable assumptions are
> superseded by D021 and the standalone collection PDF workflow.

**Date:** 2026-03-08
**Author:** Jim Brannigan (with Claude)
**Estimated effort:** 3–5 days in Claude Code sessions
**Goal:** Extract maximum value from existing data, fix known trust and classification errors, and produce a clean corpus ready for the 8499TimberBridgeLn.com deliverable.

---

## Background

The Inspirations corpus contains 6,343 assets scraped from Pinterest (3,783), Facebook (1,190), Houzz (226), and local scans (144). Gemini has tagged 6,186 of these with structured metadata (rooms, styles, materials, colors, elements) and 5,306 have semantic embeddings. The data is rich but the organizational layer on top of it has accumulated errors and inflated confidence levels that need to be corrected before the corpus can be shared with collaborators.

This spec defines the final automated pass. After this, the corpus is "done" from a data-quality standpoint — further refinement happens through Leslie's direct curation in the UI, not through batch processing.

---

## Part 0: Trust Hierarchy Correction

**Problem:** The 12 CB: collections (756 items) are documented as "Human-curated groupings" with "the highest intent signal" in CLAUDE.md, chat.py routing prompts, and catalog.py. In reality, they were created by a prior Claude Code session using AI tags and board names. They are AI-curated-on-behalf-of-human, which is a fundamentally different confidence level.

**What to do:**

### 0.1 Update CLAUDE.md trust hierarchy

Replace the current hierarchy:

```
CURRENT (WRONG):
1. Collections (CB: = highest intent)
2. Source boards
3. AI-assigned rooms/styles
4. AI labels

CORRECTED:
1. Leslie's board placements — she saved an item to "kitchen" or "bathroom" on
   Pinterest, or to a named Facebook collection. This is the ground truth of intent.
2. Jim's triage decisions — keeper/hidden status set through the UI.
3. Leslie's direct collection edits — any future manual adds/removes in the app.
4. AI-curated collections (CB:) — a prior Claude session's interpretation of the
   corpus, organized by theme. Useful as a starting hypothesis but unconfirmed by
   Leslie. Should be treated as "suggested groupings" not "refined selections."
5. AI-assigned rooms/styles (Gemini) — image analysis. Good for enrichment,
   secondary to board placement.
6. AI labels — flattened tags, lowest priority.
```

### 0.2 Update chat.py routing prompt

The `_build_routing_prompt()` function references CB: collections three times as "most refined, intentional selections." Change all three references to reflect that CB: collections are AI-curated starting points, not human-confirmed selections. The prompt should tell Dave to still use them — they're useful groupings — but not to present them as Leslie's deliberate choices.

### 0.3 Rename or annotate CB: collections

Add a `provenance` or `curator` column to the `collections` table (or use the existing `description` field) to record that CB: collections were created by `claude-code-session` rather than by a human actor. This metadata flows downstream to any system that reads collections.

### 0.4 Update catalog.py

The `_generate_index()` function should annotate CB: collections differently from user-created collections. Suggested format in the index:

```
- "CB: Kitchen" (76 items, AI-curated from pinterest:kitchen + AI room tags)
```

---

## Part 1: Junk Removal

**Problem:** 279 items are categorized as `other` (exercise, food, workout, makeup, cleaning, products-i-love, personal style). These should never appear in collaborator-facing views.

**What to do:**

### 1.1 Bulk-hide junk categories

```sql
UPDATE assets SET triage_status = 'hidden', triage_at = datetime('now')
WHERE category = 'other' AND (triage_status IS NULL OR triage_status = 'pending');
```

Log this in `triage_log` with `actor = 'curation-script'` and `reason = 'bulk-hide: non-home-design items (exercise, food, workout, makeup, etc.)'`.

### 1.2 Verify edge cases

Some items on boards like `products-i-love` or `my-style` or `for-the-home` may have been miscategorized. Before hiding, run a spot check:

- Query 10 random items from each of these boards
- If any are genuinely home-design related, update their `category` to `home_design` before the bulk hide

### 1.3 Review the ~26 Facebook items with no board

These are `source = 'facebook'` and `board IS NULL`. Many are likely junk (GoodRx ads, random saves) but some might be construction-related. Inspect and categorize.

---

## Part 2: Facebook Board Consolidation

**Problem:** Facebook board names are a mess. There are 80+ unique board names for 1,190 items, most with 1-3 items each, many of which are Facebook's auto-categorization rather than Leslie's intentional placement. Examples: "Construction Tips," "New Home Construction Tips," "Home Construction Tips," "Custom Home Building Tips," and "Home Building Process" are five separate boards each with 1-8 items.

**What to do:**

### 2.1 Create a canonical Facebook board mapping

Define a mapping from the ~80 raw Facebook board names to ~15 canonical categories:

```python
FB_BOARD_MAP = {
    # Construction
    "building": "Construction",
    "Construction Tips": "Construction",
    "New Home Construction Tips": "Construction",
    "Home Construction Tips": "Construction",
    "Custom Home Building Tips": "Construction",
    "Home Building Process": "Construction",
    "Construction Management": "Construction",
    "Construction Details": "Construction",
    "Construction Techniques": "Construction",
    "Custom Home Builds": "Construction",
    "Contractor Tips & Legal Advice": "Construction",
    "Home Construction Ideas": "Construction",
    "Home Construction Issues": "Construction",
    "Home Construction Process": "Construction",
    "Homeowner Rights & Construction Issues": "Construction",
    "Building Materials": "Construction",
    "Exterior Home Construction": "Construction",
    "Concrete Repair Solutions": "Construction",

    # HVAC & Systems
    "hvac": "HVAC & Systems",
    "HVAC & Home Systems": "HVAC & Systems",
    "HVAC & Indoor Air Quality": "HVAC & Systems",
    "Home Systems & Maintenance": "HVAC & Systems",
    "generator": "HVAC & Systems",
    "propane": "HVAC & Systems",
    "Smart Home Features": "HVAC & Systems",

    # Plumbing & Water
    "plumbing": "Plumbing & Water",
    "Plumbing & HVAC": "Plumbing & Water",
    "Plumbing & Water Systems": "Plumbing & Water",
    "Plumbing Solutions": "Plumbing & Water",
    "Kitchen Plumbing": "Plumbing & Water",
    "well": "Plumbing & Water",
    "water": "Plumbing & Water",
    "septic": "Plumbing & Water",

    # Insulation & Envelope
    "insulation": "Insulation & Envelope",
    "Insulation & Energy Efficiency": "Insulation & Envelope",
    "Home Insulation & Energy Efficiency": "Insulation & Envelope",
    "roofing": "Roofing & Envelope",
    "Roofing & Exterior": "Roofing & Envelope",
    "foundation": "Foundation & Structure",
    "freeze": "Foundation & Structure",

    # ... (continue for remaining boards)
}
```

### 2.2 Add a `canonical_board` column to assets

Rather than overwriting `board` (which preserves the original Facebook data), add a `canonical_board` column that holds the mapped value. This way the raw data is preserved and the mapping is reversible.

### 2.3 Update catalog generation

`catalog.py` should use `canonical_board` (falling back to `board`) when generating the source dimension files. This collapses 80 tiny files into 15 meaningful ones.

---

## Part 3: Pinterest Link Depth (Selective)

**Problem:** Pinterest pins point to `pinterest.com/pin/{id}` which in turn links to an underlying article or blog post. The scrape captured only 5 fields per pin and did not follow the click-through link. About 961 pins have article-style titles suggesting valuable underlying content (color reviews, product specs, design guides, installation how-tos).

**What to do:**

### 3.1 Assess cost/benefit before committing

This is the most time-consuming part of the spec. Before building a scraper, answer these questions:

1. **Are the Pinterest pin pages still accessible?** Try 10 random `source_ref` URLs. Pinterest may require login or may have changed their page structure since the original scrape.

2. **Does the Pinterest pin page expose the click-through URL?** On a pin page, there's typically a "Visit" or source link. Check whether this is in the HTML, in a JSON-LD block, or requires JavaScript rendering.

3. **For how many of the 961 article-style pins are the underlying sites still live?** Many home design blogs from 5-10 years ago may be dead.

### 3.2 If feasible: selective scrape

Only follow links for pins where the underlying content would add value:

- **Construction-relevant pins** (house-plans board, brick, flooring, paint) — the article often contains specs, measurements, product names, installation details that the image alone doesn't convey.
- **Pins with product titles** (contains brand names, model numbers, "review" or "guide") — the article has pricing, comparisons, availability.
- **Skip**: Pure aesthetic pins where the image is the entire value (most of bathroom, bedroom, favorite-places-spaces).

### 3.3 What to capture

From the underlying article, extract:

- **Article title** (often different from Pinterest's auto-generated title)
- **Article URL** (store in `source_url`)
- **Source domain** (store in `source_domain`, e.g., "thedecorologist.com")
- **Source name** (store in `source_name`, e.g., "The Decorologist")
- **First 500 words of article text** (store in a new `source_text` column or in `post_text`) — enough for the AI agent to understand context without storing entire copyrighted articles

### 3.4 If not feasible: skip and document

If Pinterest pages require JavaScript rendering or login, or if the click-through URLs are not accessible, document the limitation and move on. The Gemini image analysis already provides good metadata for most use cases. The link depth would be a "nice to have" for construction items, not a blocker.

---

## Part 4: AI Tag Quality Review

**Problem:** Gemini's descriptions are often verbose and generic. Titles like "a bathroom with two sinks, a toilet and a shower" came from Pinterest's auto-generated alt text, not from Gemini, but the system treats them the same. The AI summaries add value but sometimes describe obvious visual content without extracting design-relevant details.

**What to do:**

### 4.1 Title source tracking

Add a `title_source` column (or use `asset_field_provenance`) to track where each asset's title came from:

- `original` — came from the source platform with a real title (article name, product name)
- `seo_alt_text` — Pinterest's auto-generated alt text ("a bathroom with...")
- `ai_summary` — Gemini's AI-generated summary was used as the title fallback
- `manual` — manually edited

This lets downstream systems weight titles appropriately. An "original" title like "Benjamin Moore Swiss Coffee: a complete color review" is enormously more valuable than "a white kitchen with beige cabinets."

### 4.2 Selective AI re-tagging

For the ~831 pins with auto-generated titles (Pinterest alt text), consider a targeted Gemini re-tag with an updated prompt that emphasizes:

- Extracting any text visible in the image (brand names, product labels, magazine titles)
- Identifying specific products rather than generic descriptions
- Noting construction-relevant details (materials, dimensions, techniques) when visible
- Generating a concise 10-word summary rather than a flowery paragraph

This is optional and depends on API budget. The existing tags are adequate for most items.

---

## Part 5: Two-Track Split

**Problem:** The corpus serves two distinct audiences — interior designers (style) and architects/builders (construction) — but everything is currently mixed together.

**What to do:**

### 5.1 Define the track gate

Every asset should be assigned to one or more tracks:

| Track | Description | Primary signal |
|-------|-------------|---------------|
| `style` | Aesthetic inspiration — rooms, finishes, furniture, color, lighting | Board names: bathroom, kitchen, bedroom, favorite-places-spaces, furniture, lighting, paint, flooring, door, etc. |
| `construction` | Practical building concerns — structural, mechanical, code, materials | Board names: house-plans, building, insulation, hvac, foundation, roofing, septic, plumbing, etc. |
| `both` | Items relevant to both (e.g., kitchen cabinets have both aesthetic and construction aspects) | Boards like brick, stone, tile, windows, flooring that cross both domains |
| `irrelevant` | Not home-related | `category = 'other'` — already handled by Part 1 |

### 5.2 Implement as a column

Add `track` to assets: `style`, `construction`, `both`, `irrelevant`. Default assignment by board mapping, with AI labels as a secondary signal for unboarded items.

### 5.3 Generate separate catalogs

`catalog.py` should be able to generate track-filtered catalogs:

- `data/catalog/style/` — only style + both items
- `data/catalog/construction/` — only construction + both items

These feed into the separate website sections on 8499TimberBridgeLn.com.

---

## Part 6: Embedding Completion

**Problem:** 5,306 of 6,343 assets have embeddings. The remaining ~1,037 need embeddings for vector search to work consistently.

**What to do:**

### 6.1 Generate missing embeddings

```bash
PYTHONPATH=src python3 -m inspirations ai embed --provider gemini --api-key "$GEMINI_API_KEY"
```

Verify the command handles the gap (only processes assets without existing embeddings).

### 6.2 Verify embedding quality

Spot-check: pick 5 kitchen items and retrieve their 10 nearest neighbors by cosine similarity. Do the neighbors make visual/semantic sense? If not, the embedding input text may need adjustment (currently uses title + AI summary).

---

## Claude Code Session Setup

### Recommended model

**Claude Sonnet 4** (`claude-sonnet-4-20250514`) for the curation work. Opus is unnecessary for batch data operations and would burn through context budget faster. Sonnet is fast, follows specs precisely, and handles SQL/Python well.

For the selective AI re-tagging in Part 4.2, the Gemini calls use `gemini-2.5-flash` which is already configured.

### CLAUDE.md additions

Add a section to the project CLAUDE.md that the Claude Code session should see:

```markdown
## Active Sprint: Last Try Curation

See `docs/LAST_TRY_CURATION_SPEC.md` for the full spec.

Working through Parts 0-6 in order. Each part should be a separate commit.
Run tests after each part: `PYTHONPATH=src python3 -m unittest discover -s tests -v`

### Trust hierarchy (CORRECTED — read carefully)
The CB: collections were created by a prior Claude Code session, NOT by Leslie.
They are AI-curated starting points, not human-confirmed selections.
Do not treat them as highest-trust data. Leslie's board placements are the
ground truth. See Part 0 of the spec for the corrected hierarchy.
```

### Session structure

Each part should be a focused session:

1. **Part 0** — Trust hierarchy fix (CLAUDE.md, chat.py, catalog.py). Small, surgical changes. Commit and verify tests pass.
2. **Part 1** — Junk removal. SQL updates + triage_log entries. Commit.
3. **Part 2** — Facebook board consolidation. Schema change + mapping + catalog update. Commit.
4. **Part 3** — Pinterest link depth assessment. Research first, build only if feasible. Commit findings either way.
5. **Part 4** — Title source tracking. Schema change + backfill. Commit. Optional: re-tagging pass.
6. **Part 5** — Two-track split. Schema change + assignment + catalog generation. Commit.
7. **Part 6** — Embedding completion. Run command + spot-check. Commit.

### Verification

After all parts complete:

- All tests pass
- Catalog regenerated: `PYTHONPATH=src python3 -m inspirations catalog generate`
- Dev server starts clean: `PYTHONPATH=src python3 -m inspirations serve --port 8001`
- Browse sanity check passes (run `tools/sanity_browse_tree_explorer.js` in DevTools)
- Spot-check: search for "kitchen" in Dave chat — results should include items from multiple sources, not just CB: Kitchen
