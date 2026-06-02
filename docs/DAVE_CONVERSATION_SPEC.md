# Dave — Conversational Design Librarian

**Date:** 2026-03-20
**Status:** Draft
**Author:** Jim + Claude

---

## 1. Vision

Dave is a standalone conversational AI that acts as Jim and Leslie's design
librarian for their home build. He sits on top of the same data as Inspirations
(SQLite, images, embeddings) but provides a **conversation-first** experience —
you talk to Dave, and he responds with rich, visual, synthesized answers.

Dave is **not** a search box. He's a design critic, construction advisor, and
product researcher who happens to have access to everything Leslie ever saved.

### Why standalone first

The Inspirations app is a browse/triage tool. Dave is a conversation. Bolting
a rich conversational AI into the existing grid/explorer UI conflates two
fundamentally different workflows. Building Dave standalone lets us:

- Get retrieval + synthesis right without fighting existing UI constraints
- Test with real questions against real data immediately
- Integrate into Inspirations later as a proven component (or not — maybe
  they stay separate and that's fine)

### Content categories

Leslie's collection isn't one thing. It breaks into distinct modes of thinking
about building a house:

| Category | What it covers | How Dave should respond |
|----------|---------------|----------------------|
| **Style & Aesthetic** | Interior design, look/feel, color palettes, finishes, furniture | Visual comparisons, mood boards, style analysis |
| **Product Selection** | Specific fixtures, hardware, appliances, materials | Specs, comparisons, sourcing links, pro/con analysis |
| **Landscape** | Outdoor design, hardscape, planting, views | Both aesthetic inspiration and practical planting/drainage ideas |
| **Construction** | Framing, roofing, foundation, systems, code concerns | Cautionary items, checklists, "things to watch for" briefs |

These categories aren't mutually exclusive (a kitchen faucet is both product
selection and style) but they drive fundamentally different response styles.
Dave should detect which mode the question falls into and adjust his voice.

---

## 2. UX Design

### 2.1 Layout: Full-Page Conversation

Dave runs as its own web page — a chat-first interface with rich response
rendering. No sidebar, no grid. Just a conversation with the ability to
show images, comparisons, and generated artifacts inline.

```
┌────────────────────────────────────────────────────────┐
│  Dave                                    [≡] [history] │
├────────────────────────────────────────────────────────┤
│                                                        │
│  ┌──────────────────────────────────────────────────┐  │
│  │ conversation thread (scrollable)                 │  │
│  │                                                  │  │
│  │  [user bubble]                                   │  │
│  │  [Dave text + inline image cards]                │  │
│  │  [user bubble]                                   │  │
│  │  [Dave mood board artifact]                      │  │
│  │  [user bubble]                                   │  │
│  │  [Dave comparison layout]                        │  │
│  │                                                  │  │
│  │                                                  │  │
│  └──────────────────────────────────────────────────┘  │
│                                                        │
│  ┌──────────────────────────────────────────────────┐  │
│  │ [quick chips]                         [Send] [⋯] │  │
│  │ textarea input area                              │  │
│  └──────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────┘
```

**Layout details:**

| Aspect | Detail |
|--------|--------|
| Max width | 900px centered (readable line length for text + wide enough for image grids) |
| Thread | Full height minus input area, scrollable |
| Input | Fixed at bottom, multi-line auto-grow textarea |
| Header | Minimal — "Dave" title, hamburger menu (settings), history button |
| Background | Clean, warm neutral (not stark white — this is a design tool) |

### 2.2 Conversation Thread

Messages are rendered in a scrollable thread. Dave's responses can contain
mixed content — text interspersed with images, grids, and interactive elements.

**Message types:**

| Type | Rendered as |
|------|-------------|
| `user` | Right-aligned bubble with user text |
| `text` | Left-aligned Dave bubble with markdown-rendered text |
| `item_cards` | Horizontal-scroll strip of thumbnail cards (clickable → lightbox) |
| `item_grid` | Responsive tile grid embedded in thread (masonry layout, max 20 items visible, "show all N" expands) |
| `comparison` | Side-by-side images with captions and annotations |
| `mood_board` | Collage layout with title, palette swatch, and design notes |
| `html_artifact` | Sandboxed iframe rendered inline (resizable, "Open in new tab" link) |
| `video_embed` | Inline video player for reel/clip assets |
| `checklist` | Construction concerns rendered as a checklist with item references |
| `product_table` | Comparison table (specs, features, sources) for product selection items |
| `status` | Gray italic status line ("Searching 6,295 items...", "Found 23 matches") |
| `action_confirm` | Confirmation chip ("Created collection 'Warm Kitchens'" with link) |

**Thread behavior:**
- Auto-scroll to bottom on new messages
- Scroll-back preserved (no auto-dismiss)
- Session history kept in memory; conversations saveable to localStorage
- Streaming: Dave's text responses stream token-by-token (SSE)
- Loading state: pulsing dot animation in Dave's bubble while waiting
- Lightbox: clicking any image opens full-size overlay with AI metadata panel

### 2.3 Input Area

Multi-line auto-growing `<textarea>` fixed at the bottom of the viewport.

| Aspect | Detail |
|--------|--------|
| Default height | 1 line (44px, touch-friendly) |
| Auto-grow | Expands to max 6 lines as user types |
| Submit | `Enter` sends (desktop). Explicit Send button always visible (iPad) |
| Shift+Enter | Newline |
| Placeholder | "Ask Dave anything about your collection..." |
| Buttons | Send arrow, overflow menu (⋯) for: clear conversation, export conversation |

### 2.4 Quick Action Chips

Above the input, a row of contextual quick-action chips:

**On conversation start:**
`What's in my library?` · `Show me kitchens` · `Construction concerns` · `Surprise me`

**After Dave shows items:**
`Why these?` · `Compare the top 3` · `Make a mood board` · `More like this`

**After a mood board:**
`Refine this` · `Save as collection` · `Export as HTML` · `Show me the outlier`

**After construction items:**
`What should I ask the builder?` · `Related products` · `Show similar concerns`

### 2.5 Image Lightbox

Clicking any image in the thread opens a full-viewport lightbox showing:
- Full-size image (or video player for reels)
- Source badge (Pinterest / Facebook / Houzz / Scan)
- Board name (Leslie's original curation)
- AI summary, rooms, styles, materials, colors
- Labels as chips
- "Open in Inspirations" link (deep-link to the item in the main app)
- Arrow keys / swipe for prev/next within the current result set

### 2.6 Conversation History

Accessible via header button. Shows saved conversations as a list:
- Auto-saved title (first user message, truncated)
- Date and turn count
- Click to restore (replaces current conversation with confirmation)
- Delete individual conversations
- Stored in localStorage (no server persistence needed)

### 2.7 iPad Considerations

- Full-page layout works naturally on iPad — no panel gymnastics
- Input at bottom is thumb-friendly in landscape
- Software keyboard pushes viewport up (standard iOS behavior)
- Explicit Send button (no Enter-to-submit on software keyboard)
- Image grids use touch-friendly tile sizes (min 120px)
- Lightbox supports swipe gestures
- Quick chips are 44px min touch targets

---

## 3. Content Category Awareness

Dave detects which category a question falls into and adjusts his response
style, retrieval strategy, and output format accordingly.

### 3.1 Category Detection

Part of intent analysis (Pass 1). The LLM classifies the question into one
or more categories and adjusts retrieval weights:

```json
{
  "categories": ["style", "product_selection"],
  "response_mode": "visual_comparison",
  "retrieval_weights": {
    "embedding_weight": 0.7,
    "label_weight": 0.2,
    "board_weight": 0.1
  }
}
```

### 3.2 Category-Specific Behavior

**Style & Aesthetic:**
- Heavy on visual results — show image grids, mood boards, comparisons
- Describe colors, materials, and design movements
- Reference specific AI-detected styles (Modern, Farmhouse, Transitional...)
- Mood board and palette generation are natural outputs
- Voice: design-industry tone, visual language

**Product Selection:**
- Show items with spec-like callouts (what fixture? what finish? what brand?)
- Product comparison tables when relevant
- Cross-reference: "Leslie saved 3 different brass faucet styles — here's how they differ"
- Voice: practical, comparative, decision-oriented

**Landscape:**
- Split aesthetic vs. practical: "Here's what caught Leslie's eye" vs. "Here are drainage/grading concerns she flagged"
- Outdoor-specific labels matter more (hardscape, native plants, retaining walls)
- Voice: blend of design inspiration and practical landscaping advice

**Construction:**
- Checklists and concern lists over pretty pictures
- "Things to discuss with your builder" framing
- Reference source boards where Leslie saved cautionary/educational content
- Cross-reference with product selection when construction items imply material choices
- Voice: practical, cautionary, builder-to-homeowner translation

### 3.3 Cross-Category Queries

Many real questions span categories:
- "What kind of kitchen faucet should we get?" → style + product selection
- "Is there anything about roof materials in my saves?" → construction + product selection
- "Show me patios that would work with our lot" → landscape + style

Dave handles these by retrieving from all relevant categories and organizing
the response with clear sections: "From a design perspective... From a
construction standpoint... Products to consider..."

---

## 4. Retrieval Architecture

### 4.1 Hybrid Retrieval Pipeline

```
User query → Intent analysis (single fast LLM call)
           → Category detection + query expansion
           → Parallel: embedding search + structured filter
           → Merge + deduplicate + score
           → Optional: rerank with metadata context (top 50 → top 15)
           → Synthesis (single LLM call with full context + tool use)
```

### 4.2 Intent Analysis (Pass 1)

A single fast LLM call (Haiku or Gemini Flash) that returns structured intent:

```json
{
  "type": "search|converse|create|compare|analyze",
  "categories": ["style", "construction"],
  "search_text": "warm evening patio lighting",
  "expanded_terms": ["teak", "string lights", "twilight", "outdoor living"],
  "hard_filters": {
    "rooms": ["patio"],
    "styles": ["transitional", "farmhouse"],
    "sources": ["pinterest"]
  },
  "response_mode": "visual_comparison|mood_board|checklist|narrative|product_table",
  "follow_up_context": "User previously asked about outdoor spaces"
}
```

For pure conversation (no retrieval needed), skip to synthesis directly.

### 4.3 Embedding Search

**Storage:** `asset_embeddings` table with Gemini embedding-001 vectors.

**Query flow:**
1. Embed `search_text` + `expanded_terms` via Gemini embedding API
2. Brute-force cosine similarity against all vectors (~5ms at 6,295 items)
3. Return top 100 by score

**Future multi-index path** (from the Gemini RAG blueprint):
- Global aesthetic embedding (current — full-image Gemini vectors)
- Object-level embedding (SAM segmentation → per-object vectors) — defer
- Video keyframe embeddings (sample every 2–5s, embed each frame) — defer
- Multimodal cross-encoder (CLIP/Voyage for text-to-image) — evaluate

For now, single-index Gemini embeddings + structured metadata is sufficient
at this scale. The architecture supports adding indices later without
pipeline changes.

### 4.4 Structured Filter

In parallel with embedding search, query `asset_ai` and `asset_labels` using
hard filters from intent analysis:

```sql
SELECT DISTINCT a.id FROM assets a
JOIN asset_ai ai ON ai.asset_id = a.id
WHERE json_extract(ai.json, '$.rooms') LIKE '%patio%'
  AND a.source = 'pinterest'
```

Also filter by category-relevant labels:
- Construction: labels matching "foundation", "framing", "roofing", etc.
- Product: labels matching "faucet", "hardware", "fixture", brands
- Landscape: labels matching "hardscape", "planting", "drainage", etc.

### 4.5 Merge, Deduplicate, Score

Union embedding results and structured filter results. Items appearing in
both get a score boost.

```
final_score = (0.6 * embedding_score)
            + (0.3 * filter_match_score)
            + (0.1 * provenance_boost)
```

Where `provenance_boost` factors in:
- `triage_status = 'keeper'` → boost
- Board provenance (Leslie saved it intentionally) → boost
- Has annotations → boost
- Category-relevant board name → boost

### 4.6 Reranking (Optional)

For high-stakes queries (mood boards, briefs, comparisons), send top 50
results to a VLM for relevance reranking:

- Send thumbnails + metadata + original query
- VLM scores each item 0–10 for relevance
- Top 15 proceed to synthesis

This is the "secret weapon" from the Gemini blueprint — slower but much
more accurate than raw vector distance. Use Gemini 2.5 Flash for cost
efficiency.

Reranking is optional and can be toggled off for speed during iterative
conversation (only used on first query or explicit "find me the best").

### 4.7 Synthesis (Pass 2)

Send top results to Claude with full context for the response.

**Context provided:**
- Conversation history (last 10 turns)
- Retrieved items with: title, AI summary, board, source, rooms, styles,
  materials, labels, triage status, annotations (full — not truncated)
- Detected categories and response mode
- User's original message
- Available skills (tool definitions)

**Claude responds with:**
- One or more skill invocations (inline item cards, mood board, etc.)
- Conversational text referencing specific items by visual content
- Category-appropriate analysis (design critique vs. construction checklist)

### 4.8 Conversation Context

Rolling context window of last 10 turns:

```json
{
  "role": "user|assistant",
  "content": "the message text",
  "skill_results": [{"skill": "show_items", "count": 12}],
  "item_ids_shown": ["uuid1", "uuid2"],
  "categories": ["style"],
  "timestamp": "2026-03-20T14:30:00Z"
}
```

Enables natural follow-ups:
- "Now just the modern ones" → filters previous result set
- "Why that third one?" → references items from last response
- "What construction concerns relate to these?" → cross-category pivot
- "Make a mood board from these" → uses items from last response

---

## 5. Delivery Model — How Dave Shows Things

Every skill Dave invokes needs to end up on screen. The core question:
**where does it render?** Not everything fits in a chat bubble, and not
everything needs to take over the viewport. The delivery model defines
three tiers based on how much real estate the output needs.

### 5.1 The Three Delivery Tiers

```
TIER 1 — INLINE                TIER 2 — CANVAS                 TIER 3 — FULL TAKEOVER
(stays in chat thread)          (split view: canvas + input)     (full viewport, rare)

┌──────────────────┐           ┌──────────────────────────┐     ┌──────────────────────────┐
│ [user bubble]    │           │  Canvas area             │     │                          │
│ [Dave text]      │           │  (tile grid / mood board │     │  Full-viewport artifact  │
│ [thumbnail strip]│           │   / comparison / explorer│     │  (generated HTML page    │
│ [user bubble]    │           │   with Dave's presets)   │     │   or immersive explorer) │
│ [Dave text]      │           │                          │     │                          │
│ [small compare]  │           │                          │     │                          │
│ [user bubble]    │           ├──────────────────────────┤     │              [✕ Close]   │
│ ...              │           │ [conversation collapsed] │     │              [↗ New tab] │
│                  │           │ [chips]        [Send] [▲]│     │                          │
│ [chips]  [Send]  │           │ input: _________________ │     └──────────────────────────┘
│ input: _________ │           └──────────────────────────┘      ✕ returns to Tier 1 or 2
└──────────────────┘
```

**Tier 1 — Inline (in the conversation thread)**

Output renders directly inside a Dave message bubble. The conversation
stays full-screen, the user reads the result as part of the thread and
scrolls naturally. Best for:

- Text responses
- Small thumbnail strips (≤8 items)
- Small comparisons (2–3 items side-by-side)
- Checklists and product tables
- Status messages and confirmations

**Tier 2 — Canvas (split view)**

The viewport splits: a **canvas area** takes the upper portion, and the
**conversation collapses** to the bottom — just the input bar, quick chips,
and a draggable top edge to reveal the conversation thread.

This is the money layout. The user sees the visual output (grid, mood board,
explorer, comparison) at full width while still being able to type refinements:
"remove the farmhouse ones", "zoom into that cluster", "now make a mood board
from these."

The canvas area is a **slot** — different skills render different content into
it. Only one canvas output is active at a time. A new canvas skill replaces
the previous one (with a smooth transition). Dismissing the canvas returns to
Tier 1 (full-thread conversation).

Best for:
- Tile grids (>8 items)
- Mood boards and collages
- Side-by-side comparisons (4+ items)
- 3D attractor explorer with preset attractors
- Video players with annotation overlays

**Tier 3 — Full Takeover (entire viewport)**

The canvas fills the entire viewport. Conversation is hidden behind a close
button. This is rare — only for immersive experiences that need every pixel.

Best for:
- Generated HTML pages (design briefs, share-ready documents)
- Full 3D explorer when the user explicitly wants immersion
- Exported artifacts being previewed before save/share

Close button (`✕`) or `Esc` returns to whatever state was active before
(Tier 1 or Tier 2).

### 5.2 Skill → Tier Mapping

Each skill has a **default tier** but can be promoted or demoted based on
content size or user action.

| Skill | Default Tier | Promotes to | Notes |
|-------|-------------|-------------|-------|
| `message` | 1 (inline) | — | Always inline |
| `item_cards` | 1 (inline) | 2 if >8 items | Thumbnail strip in bubble; "Show in grid" promotes to canvas |
| `checklist` | 1 (inline) | — | Construction concerns list, always inline |
| `product_table` | 1 (inline) | — | Comparison table, always inline |
| `item_grid` | 2 (canvas) | — | Tile grid in canvas, always needs width |
| `comparison` | 1 if 2–3 items, 2 if 4+ | — | Small comparisons inline, larger ones in canvas |
| `mood_board` | 2 (canvas) | 3 via "fullscreen" | Collage needs space; user can expand |
| `explorer` | 2 (canvas) | 3 via "immerse" | 3D explorer in canvas; fullscreen option |
| `html_artifact` | 3 (takeover) | — | Generated pages need full viewport |

### 5.3 Tier Transitions

**Tier 1 → Tier 2 (opening the canvas):**
1. Dave's skill result arrives with tier 2 content
2. Conversation thread slides down and collapses to input bar height
3. Canvas area slides in from top (or fades in — keep it fast)
4. Canvas renders the skill output (grid, mood board, explorer)
5. A **canvas title bar** appears: skill title + `[✕ Close]` + `[↗ Fullscreen]`

**Tier 2 → Tier 1 (closing the canvas):**
1. User clicks `✕` on canvas title bar, or types a message that produces an
   inline-only response (Dave decides the canvas is no longer needed)
2. Canvas slides out, conversation expands to full height
3. A **thumbnail placeholder** remains in the conversation thread at the point
   where the canvas was opened — clicking it re-opens the canvas with the
   same content

**Tier 2 → Tier 2 (replacing canvas content):**
1. User asks a follow-up that triggers a different canvas skill
2. Canvas content crossfades to the new output
3. Previous canvas content becomes a thumbnail placeholder in the thread

**Tier 2 ↔ Tier 3 (fullscreen toggle):**
1. User clicks `↗ Fullscreen` on canvas title bar
2. Canvas expands to fill viewport, input bar hides
3. `✕ Close` returns to Tier 2 (not Tier 1)

### 5.4 The Canvas Slot

The canvas is a single `<div>` container that different skill renderers
populate. It is NOT a second conversation thread — it's a display surface.

```html
<div id="dave-canvas" class="dave-canvas hidden">
  <div class="canvas-titlebar">
    <span class="canvas-title">Warm Transitional Kitchens — 15 items</span>
    <button class="canvas-close">✕</button>
    <button class="canvas-fullscreen">↗</button>
  </div>
  <div class="canvas-content">
    <!-- Skill renderer injects content here -->
    <!-- Could be: tile grid, mood board, explorer, iframe, comparison -->
  </div>
</div>
```

Each skill renderer is a JS module that:
1. Receives the skill params (item IDs, attractors, HTML, layout options)
2. Creates/updates DOM inside `.canvas-content`
3. Cleans up when replaced by another renderer
4. Optionally exposes an update API for refinement ("remove item X" without
   full re-render)

### 5.5 Conversation While Canvas Is Open

This is what makes split view powerful. When the canvas is showing:

- Input bar is always visible and active
- Quick chips update to canvas-relevant actions
- User types "remove the farmhouse ones" → Dave processes it, updates the
  canvas content in-place (items fade out, grid reflows)
- User types "make a mood board from these" → canvas crossfades from grid
  to mood board
- User types a question with no visual component → Dave responds with
  inline text in the collapsed thread (auto-expands thread briefly to
  show the response, then re-collapses)
- User types something that invalidates the canvas → canvas closes,
  thread expands

Dave decides whether a follow-up **updates the current canvas**, **replaces
it with a new canvas**, or **closes the canvas and responds inline**. This
is part of the synthesis step — the LLM sees the current canvas state in
its context and chooses accordingly.

### 5.6 Thread Placeholders (Canvas Breadcrumbs)

When a canvas output is dismissed or replaced, a **placeholder card** remains
in the conversation thread at the point where it was opened:

```
┌─────────────────────────────────────────┐
│ 🖼 Warm Transitional Kitchens — 15 items │
│ [Re-open]  [Open in new tab]            │
└─────────────────────────────────────────┘
```

This serves as a breadcrumb — the user can scroll back through the
conversation and re-open any previous canvas output. The content is
cached so re-opening is instant.

---

## 6. Dave's Output Skills

Skills are structured outputs that the frontend renders as rich content,
either inline in the conversation thread (Tier 1) or in the canvas (Tier 2/3).

### 6.1 `message` — Plain Text (Tier 1)

Conversational text, always inline. Markdown-rendered.

```json
{ "skill": "message", "params": { "text": "You have 6,295 items..." } }
```

### 6.2 `item_cards` — Thumbnail Strip (Tier 1, promotes to Tier 2)

Horizontal-scroll strip of thumbnail cards in a conversation bubble.

```json
{
  "skill": "item_cards",
  "params": {
    "ids": ["uuid1", "uuid2", ...],
    "title": "Warm transitional kitchens",
    "explanation": "These 12 items share a warm palette with brass hardware..."
  }
}
```

**Delivery:** Renders inline as a scrollable strip. If >8 items, strip shows
first 8 with a "Show all N in grid" button that **promotes to Tier 2** —
opening the canvas with a full tile grid of all items.

Clicking any card → lightbox.

### 6.3 `checklist` — Construction Concerns (Tier 1)

Always inline. Construction-category output.

```json
{
  "skill": "checklist",
  "params": {
    "title": "Foundation Concerns from Leslie's Saves",
    "items": [
      {"id": "uuid1", "concern": "Drainage grading near foundation", "source": "Pinterest/construction-tips"},
      {"id": "uuid2", "concern": "Pier vs. slab considerations for sloped lots"}
    ],
    "summary": "Leslie saved several items about foundation drainage..."
  }
}
```

**Delivery:** Rendered as a styled checklist in a Dave bubble. Each item
has a small thumbnail and clickable concern text (→ lightbox). The checklist
is a reference doc — user can screenshot or "Export as HTML" from overflow menu.

### 6.4 `product_table` — Product Comparison (Tier 1)

Always inline. Product-selection-category output.

```json
{
  "skill": "product_table",
  "params": {
    "title": "Brass Faucet Options",
    "columns": ["Style", "Finish", "Source"],
    "rows": [
      {"id": "uuid1", "cells": ["Bridge", "Brushed brass", "Pinterest"]},
      {"id": "uuid2", "cells": ["Pull-down", "Aged brass", "Houzz"]}
    ],
    "notes": "The bridge style appears in 3 of Leslie's kitchen boards..."
  }
}
```

**Delivery:** Rendered as a compact table in a Dave bubble. Row thumbnails
on the left, cells to the right. Click any row → lightbox for that item.

### 6.5 `comparison` — Side-by-Side (Tier 1 small, Tier 2 large)

```json
{
  "skill": "comparison",
  "params": {
    "items": [
      {"id": "uuid1", "caption": "Warm brass with white oak"},
      {"id": "uuid2", "caption": "Cool chrome with painted cabinets"}
    ],
    "title": "Hardware finish comparison",
    "analysis": "Both approaches work for transitional kitchens, but..."
  }
}
```

**Delivery:**
- **2–3 items:** Inline (Tier 1). Images side-by-side in the bubble with
  captions below each. Analysis text follows.
- **4–6 items:** Canvas (Tier 2). Split-pane layout with each item at
  readable size. Analysis text in a panel or overlay.

### 6.6 `item_grid` — Tile Grid (Tier 2)

Opens the canvas with a responsive tile grid.

```json
{
  "skill": "item_grid",
  "params": {
    "ids": ["uuid1", "uuid2", ...],
    "title": "All patio saves — 47 items",
    "explanation": "47 patio items sorted by relevance to your query"
  }
}
```

**Delivery:** Canvas opens with a masonry tile grid. Each tile shows
thumbnail + board name badge. Click tile → lightbox. The grid supports
Dave-driven updates: "remove the farmhouse ones" causes items to fade
out and the grid to reflow without a full re-render.

Canvas title bar shows: grid title, item count, `✕` close, `↗` fullscreen.

### 6.7 `mood_board` — Mood Board Collage (Tier 2, promotes to Tier 3)

```json
{
  "skill": "mood_board",
  "params": {
    "title": "Master Bath Direction",
    "items": ["uuid1", "uuid2", "uuid3", "uuid4", "uuid5"],
    "palette": ["#F5F0EB", "#8B7355", "#2C3E50", "#C4A882"],
    "notes": "Leslie's saves lean toward warm marble with brass fixtures...",
    "layout": "collage"
  }
}
```

**Delivery:** Canvas opens with a styled collage layout. Images arranged
in an asymmetric grid (hero image larger, supporting images smaller).
Color palette strip along bottom edge. Title and notes overlaid.

Canvas title bar adds: `Save as collection`, `Export as HTML`, `↗ Fullscreen`.

Fullscreen (Tier 3) gives the mood board the entire viewport — good for
showing Leslie on the iPad or sharing the screen with Chris.

### 6.8 `explorer` — 3D Attractor Explorer (Tier 2, promotes to Tier 3)

Dave configures and opens the attractor explorer with specific attractors
pre-activated and an optional filtered item set.

```json
{
  "skill": "explorer",
  "params": {
    "attractors": ["Kitchen", "Modern", "Brass", "Marble"],
    "filter_ids": ["uuid1", "uuid2", ...],
    "mode": "3d",
    "title": "Kitchen style landscape",
    "explanation": "Here's how your kitchen items cluster by style and material..."
  }
}
```

**Delivery:** Canvas opens with the 3D (or 2D) attractor explorer. The
specified attractor chips are pre-activated — items are already pulling
toward their semantic poles. If `filter_ids` is provided, only those items
are shown (others dimmed or hidden).

This is powerful because Dave has already done the retrieval and knows
*which* attractors are relevant to the query. The user doesn't have to
manually toggle chips — they see the clustering immediately.

**Canvas interactions while explorer is open:**
- User can still interact with the explorer directly (rotate, zoom, click items)
- "Focus on the modern cluster" → Dave adjusts attractor weights
- "What's that outlier over there?" → Dave identifies the item the user is pointing at (via click or description)
- "Add the Farmhouse attractor" → Dave activates another chip
- `↗ Fullscreen` gives the explorer the entire viewport (Tier 3) — immersive exploration mode

**What Dave provides that manual explorer doesn't:**
- Pre-selected attractors (user doesn't hunt through chips)
- Pre-filtered item set (only relevant items, not all 6,295)
- Explanation of what the clustering reveals
- Conversational refinement ("now show me how these relate to materials instead of styles")

### 6.9 `html_artifact` — Generated HTML Page (Tier 3)

Dave generates a standalone HTML page — design briefs, share-ready
documents, curated galleries with narrative.

```json
{
  "skill": "html_artifact",
  "params": {
    "html": "<html>...</html>",
    "title": "Kitchen Direction Brief for Chris",
    "description": "A curated brief showing our kitchen preferences"
  }
}
```

**Delivery:** Full viewport takeover (Tier 3). The generated HTML renders
in a sandboxed iframe filling the screen. Title bar shows: page title,
`✕ Close`, `↗ Open in new tab`, `💾 Save HTML`.

Dave generates the full HTML himself — layout, typography, image placement,
narrative structure. The HTML references media via `/media/{id}?kind=thumb`
URLs (or originals for high-res briefs).

**What Dave puts in the HTML:**
- Image grids with captions and source attribution
- Video embeds for reel/clip assets
- Design analysis with callouts to specific images
- Color palette visualizations
- Comparison tables (materials, styles, sources)
- Section headings and narrative flow
- CSS styling (Dave chooses — accept variance for creative flexibility)

This is the skill for producing something **shareable** — a document you
could show Chris Wierick or email to Leslie's sister.

---

## 7. System Prompt

```
You are Dave, the design librarian for Jim and Leslie's home inspiration library.

ABOUT THE PROJECT:
Jim and Leslie are building a retirement home at Timber Bridge (Lot 14).
They work with Chris Wierick (home designer) and need to communicate
their preferences clearly. Leslie curated thousands of images from
Pinterest, Facebook, and Houzz — plus magazine scans — organized by
boards that reflect her interests and concerns.

PERSONALITY:
- Warm, concise, genuinely enthusiastic about their project
- You're a knowledgeable design advisor, not a search engine
- Reference items by their visual content ("the kitchen with the waterfall
  island and brass pendants"), not by IDs
- When you find patterns across the collection, point them out
- Respect Leslie's curation — if she saved it, that was intentional

CONTENT CATEGORIES — adapt your voice and output to what's being asked:

1. Style & Aesthetic: Design-industry tone. Visual comparisons, mood boards,
   palette analysis. Describe what makes things work visually.

2. Product Selection: Practical and comparative. Specs, options, trade-offs.
   "Leslie saved 3 versions of this — here's how they differ."

3. Landscape: Blend of inspiration and practical advice. Split aesthetic
   ("here's the look") from functional ("here's the drainage concern").

4. Construction: Cautionary, practical, builder-to-homeowner translation.
   Checklists over pretty pictures. "Things to discuss with your builder."

Questions often span categories — organize your response with clear sections.

TRUST HIERARCHY (when sources conflict):
1. Source boards — Leslie's intentional curation (highest)
2. Human triage decisions (keeper/hidden) — durable intent
3. Collections — deliberate working subsets; "CB:" = AI-derived representative sets.
   Historical "pins:" source mirrors are retired; browse live source boards through
   `assets.board` metadata.
4. AI rooms/styles — Gemini analysis, good enrichment
5. AI labels — useful for search, lowest priority

CONVERSATION RULES:
- Always explain WHY items match, not just THAT they match
- Describe visual patterns and connections between items
- If the user says "these" or "those", they mean items from your last response
- Follow-ups can refine previous results without re-explaining everything
- Keep text to 2-4 sentences unless the user asks for detail
- For mood boards and briefs, write richer descriptive text
- You can invoke multiple skills in one response
```

---

## 8. API Design

### 8.1 `POST /api/dave/conversation` (SSE)

**Request:**
```json
{
  "message": "Show me warm transitional kitchens",
  "conversation_id": "conv_abc123"
}
```

**Response:** Server-Sent Events stream:

```
event: status
data: {"text": "Searching 6,295 items..."}

event: status
data: {"text": "Found 47 matches, selecting best 15..."}

event: token
data: {"text": "Here"}

event: token
data: {"text": " are"}

event: skill
data: {"skill": "item_cards", "params": {"ids": [...], "title": "..."}}

event: token
data: {"text": "\n\nThese items share a warm transitional..."}

event: done
data: {"conversation_id": "conv_abc123", "turn_id": "turn_xyz"}
```

**Why SSE:**
- Streaming tokens give immediate feedback
- Status events show retrieval progress
- Skill events fire as soon as decided (images appear before explanation finishes)
- Simple implementation with Python standard library

### 8.2 Media Serving

Dave's frontend needs access to thumbnails and originals:

- `GET /media/{id}?kind=thumb` — thumbnail (existing Inspirations endpoint)
- `GET /media/{id}?kind=original` — full-size original

Dave's standalone server proxies these from the Inspirations data directories,
or (simpler) both apps serve from the same `store/` directory.

### 8.3 Metadata Endpoint

`GET /api/dave/item/{id}` — returns full metadata for lightbox display:

```json
{
  "id": "uuid",
  "title": "...",
  "source": "pinterest",
  "board": "kitchen-ideas",
  "ai_summary": "...",
  "rooms": ["Kitchen"],
  "styles": ["Transitional"],
  "materials": ["Brass", "White Oak"],
  "colors": ["Warm White", "Gold"],
  "labels": ["island", "pendant-light", "waterfall-counter"],
  "triage_status": "keeper",
  "content_kind": "pin",
  "image_url": "/media/{id}?kind=thumb",
  "original_url": "/media/{id}?kind=original"
}
```

---

## 9. Technical Implementation

### 9.1 Standalone App Structure

```
dave/
  app/
    index.html          — single page app
    dave.css            — styles
    dave.js             — conversation UI, message rendering
    skills.js           — skill renderers (grids, mood boards, comparisons, etc.)
    lightbox.js         — image lightbox with metadata panel
  server.py             — HTTP server (standard library, like Inspirations)
  retrieval.py          — intent analysis, embedding search, structured filter, merge
  synthesis.py          — Claude API integration, system prompt, tool definitions
  conversation.py       — conversation context management
```

### 9.2 Shared Data Layer

Dave reads from the same SQLite database and file store as Inspirations:

- `data/inspirations.db` — assets, collections, asset_ai, asset_labels,
  asset_embeddings, triage_log
- `store/` — originals and thumbnails

No data duplication. Both apps are read-compatible. Write operations
(creating collections, triage actions) go through Inspirations' existing
store layer — Dave imports and calls those functions.

### 9.3 Dependencies

Same as Inspirations — standard library only, plus:
- `anthropic` Python SDK (for Claude API streaming)
- Optional: `google-generativeai` (for Gemini embedding + reranking)

### 9.4 Dev Server

```bash
PYTHONPATH=src python3 dave/server.py --port 8002
```

Separate port from Inspirations (8001). Both can run simultaneously.

---

## 10. Integration Path (Future)

Once Dave is proven standalone, integration options:

1. **Bottom panel in Inspirations** — embed Dave's conversation UI as a
   bottom panel in the existing app. Dave gains canvas control skills
   (push to grid, open explorer, etc.)

2. **Deep links** — Dave links into Inspirations ("Open in Inspirations"
   from lightbox). Inspirations links into Dave ("Ask Dave about this
   collection").

3. **Shared conversation** — Inspirations sidebar has a "Dave" button
   that opens the standalone Dave in a new tab with the current filter
   context pre-loaded.

4. **Stay separate** — Maybe they're just two apps and that's fine.

Decision deferred until Dave v1 is working.

---

## 11. Implementation Plan

### Phase 1: Conversation + Tier 1 Output

1. Standalone server with SSE conversation endpoint
2. Conversation UI — thread, input, streaming token rendering
3. Intent analysis → embedding search → synthesis pipeline
4. Tier 1 skill renderers: `message`, `item_cards` (inline strip)
5. Image lightbox with metadata panel

### Phase 2: Canvas + Tier 2 Output

6. Canvas slot implementation (the `<div>` that holds canvas content)
7. Tier transition system (Tier 1 ↔ 2, conversation collapse/expand)
8. `item_grid` canvas renderer (masonry tiles, Dave-driven updates)
9. `comparison` renderer (inline for 2–3, canvas for 4+)
10. Thread placeholders (breadcrumb cards for dismissed canvas outputs)
11. Canvas refinement loop (user types while canvas is open → Dave updates canvas)

### Phase 3: Category Awareness + Domain Skills

12. Content category detection in intent analysis
13. Category-specific retrieval weights and label filters
14. `checklist` renderer (construction concerns, Tier 1)
15. `product_table` renderer (product comparison, Tier 1)
16. Structured filter path (query asset_ai JSON fields)
17. Merge/dedup/score with provenance boost

### Phase 4: Rich Canvas Skills

18. `mood_board` canvas renderer (collage layout with palette, Tier 2)
19. `explorer` canvas renderer — 3D attractor explorer with preset attractors (Tier 2)
20. `html_artifact` renderer (sandboxed iframe, Tier 3 takeover)
21. Tier 2 → Tier 3 fullscreen toggle
22. Quick action chips (contextual, updates based on active skill)

### Phase 5: Polish

23. Conversation history (save/load to localStorage)
24. Reranking pass (VLM relevance scoring, optional toggle)
25. Export conversation as HTML
26. iPad optimization pass
27. Integration hooks (deep links between Dave and Inspirations)

---

## 12. Success Criteria

1. **5-turn conversation works** — ask, refine, pivot category, refine again,
   generate artifact — without re-explaining context.

2. **Category awareness** — "what construction concerns relate to kitchens?"
   returns checklist-style content, not pretty kitchen photos.

3. **Retrieval quality** — "show me moody evening patios" returns items that
   match the vibe, not just items tagged "patio." Dave explains why they fit.

4. **Tier transitions feel natural** — small results stay inline, larger
   results open the canvas, user can refine while canvas is open, and
   dismissing the canvas leaves a re-openable breadcrumb in the thread.

5. **Explorer integration** — "show me how kitchen items cluster by style"
   opens a 3D explorer with attractors pre-activated and only relevant items.
   User can refine from the input bar without leaving the explorer.

6. **Fast feedback** — streaming starts within 1 second. Status messages
   show retrieval progress. No 10-second blank waits.

---

## 13. 8499TimberBridgeLn.com Integration

Dave's first external integration: producing curated content for the
8499TimberBridgeLn.com website (see `docs/8499_WEBSITE_DELIVERABLE_SPEC.md`).

### Current website pipeline (CLI-driven)

```
Inspirations DB → `export site-json --track style` → JSON file → Next.js renders
```

This requires Jim to run terminal commands. It works but isn't sustainable
for the frequency of updates a house build generates.

### Dave-powered pipeline (Phase 5+)

```
Jim asks Dave: "Prepare kitchen content for the website"
  → Dave retrieves + curates items (using full retrieval pipeline)
  → Dave shows results in canvas (Tier 2 grid) for review
  → Jim refines: "remove those two, add more brass hardware"
  → Jim approves: "looks good, publish it"
  → Dave writes curated-style.json + copies images to website directory
  → Cloudflare tunnel serves updated content immediately
```

### What Dave produces

The website expects JSON matching the existing schema:

```json
{
  "title": "Curated Style Inspiration",
  "categories": [
    {
      "name": "Kitchen",
      "description": "Leslie's kitchen aesthetic centers on...",
      "items": [
        {
          "id": "kitchen-1",
          "imageUrl": "/inspirations-images/kitchen-1.jpg",
          "sourceUrl": "https://pinterest.com/pin/...",
          "source": "pinterest",
          "rating": "⭐⭐⭐⭐",
          "description": "Traditional-transitional kitchen with warm wood island...",
          "tags": ["kitchen", "marble", "brass", "transitional"],
          "assetId": "a1b2c3d4"
        }
      ]
    }
  ]
}
```

Dave generates the `description` for each category (design-industry voice)
and for each item (from AI summary + board context). The `rating` comes
from retrieval relevance score mapped to stars.

### New skill: `publish_to_site`

```json
{
  "skill": "publish_to_site",
  "params": {
    "track": "style",
    "categories": [
      {
        "name": "Kitchen",
        "description": "...",
        "item_ids": ["uuid1", "uuid2", ...]
      }
    ],
    "site_path": "/path/to/New Home/prototype-web"
  }
}
```

**Delivery:** Tier 1 (inline confirmation). Dave writes the JSON file,
copies images, and shows a confirmation with a link to the live page.

### Future options (deferred)

- **Option B:** Dave generates mood board metadata (`moodBoard` field in JSON)
  for richer website pages with hero images, palettes, and narratives.
- **Option C:** Dave lives on the website itself — collaborators ask Dave
  questions directly at `8499timberbridgeln.com/ask-dave`. Most ambitious,
  most interesting, but requires embedding Dave's server behind Next.js
  API routes with magic-link auth gating.

---

## 14. Backlog

### 14.1 Builder Brigade Checklist Skill

**Source material:** Builder Brigade checklist spreadsheets in
`/Users/minime/Projects/New Home/Documents/Builder Brigade/`:
- `bb-excel-checklist-v11_private_943xz.xlsx` (main checklist, ~1,000 rows)
- `Excel_v12_G5D7KV.xlsx` (v12 update)
- Jim's edited version in `Archive/Builder Brigade Checklist v12 jcb edit 07OCT2025 latest.xlsx`
- Plus supplementary PDFs: homebuilding checklist, blue tape walkthrough,
  land/homesite checklist

**Vision:** Dave cross-references Leslie's construction-category saves
against the Builder Brigade checklist to produce actionable checklists
like: "Based on what Leslie saved about foundations, here are the relevant
Builder Brigade checklist items to review with your builder."

**Potential skill:** `builder_checklist` — takes a topic or construction
category, finds matching Inspirations items AND matching Builder Brigade
rows, and produces a merged checklist that combines Leslie's visual
references with the Builder Brigade's systematic coverage.

**To flesh out:**
- How the Builder Brigade spreadsheet data gets ingested (import to SQLite?
  keep as separate file? parse on the fly?)
- Schema mapping between Builder Brigade categories and Inspirations
  construction categories
- Whether this is a Dave skill or a standalone tool that Dave can invoke
- How to handle the distinction between items Jim controls (cabinets,
  fixtures) vs. items the builder controls (framing, foundation)

---

## 15. Resolved Decisions

1. **Annotations in context?** No — not meaningfully populated yet.
2. **Mood boards saveable?** Yes — "Save as collection" persists item set.
3. **Artifact generation?** LLM-generated, not templates. Let Dave surprise us.
4. **Sidebar relationship?** Decoupled — Dave is standalone, no sidebar dependency.
5. **Bottom panel vs standalone?** Standalone first. Integration is Phase 5+.
6. **Content categories?** First-class concept in retrieval and response generation.
   Style, product selection, landscape, construction — with cross-category support.
7. **Delivery model?** Three tiers. Tier 1 = inline in chat bubble. Tier 2 =
   canvas split view (canvas top, input bar bottom, conversation collapsed).
   Tier 3 = full viewport takeover. Each skill has a default tier and can
   promote based on content size or user action.
8. **Canvas behavior during conversation?** Split view — canvas stays open,
   input bar stays active, user can refine while viewing. Dave decides whether
   follow-ups update the canvas, replace it, or close it and respond inline.
9. **8499 integration approach?** Option A — Dave replaces the CLI export.
   Conversational curation → JSON + images written to the website's
   `public/` directory. Options B (mood board metadata) and C (Dave on
   the website) deferred.
10. **Opus vs Sonnet?** Opus architects and builds Phase 1 (foundation,
    retrieval pipeline, conversation UI). Sonnet builds Phase 2+ components
    to established patterns. Opus reviews.
