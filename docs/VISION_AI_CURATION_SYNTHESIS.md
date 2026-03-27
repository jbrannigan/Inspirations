# Vision: AI-Powered Curation and Synthesis for Home Design Inspiration

**Date:** 2026-03-08
**Author:** Jim Brannigan (with Claude)
**Context:** The Inspirations project has built a corpus of 6,343 home design assets from Pinterest, Facebook, Houzz, and magazine scans, enriched with Gemini AI tags and embeddings. This document explores how far modern AI can push the synthesis and presentation of that corpus — moving beyond retrieval ("find me kitchens") toward genuine understanding ("what does Leslie's taste look like, and how do I communicate it to a professional?").

---

## The Core Challenge

Leslie has spent years saving design inspiration across multiple platforms. That curation represents thousands of small aesthetic decisions — she saw something, it resonated, she saved it. The aggregate of those decisions is a remarkably detailed portrait of her taste, but it's implicit. No one — including Leslie herself — has sat down and articulated "my kitchen aesthetic is X because Y."

The challenge is to make that implicit taste explicit, in a form that's useful to the professionals designing and building her house.

This is fundamentally a **synthesis** problem, not a **search** problem. The system needs to reason across hundreds of items to identify patterns, tensions, preferences, and gaps — then present those findings in a form that a designer or architect can act on.

---

## What We Have to Work With

| Asset | Count | Quality |
|-------|-------|---------|
| Total items | 6,343 | Mix of high-quality pins and low-quality Facebook saves |
| Gemini AI tags | 6,186 | 13-field JSON per item: rooms, styles, materials, colors, elements, lighting, fixtures, appliances, brands, tags |
| Gemini embeddings | 5,306 | 3,072-dimension vectors (gemini-embedding-001) |
| AI labels | 152,395 rows | 20,636 distinct labels across all items |
| Thumbnails | ~6,070 | 512px, locally stored, immediately available for multimodal prompts |
| Leslie's board placements | 5,343 items | The ground truth of intent — she put each item on a specific board |
| Triage decisions | 674 hidden, 1 keeper | Mostly unused — junk filtering only |

---

## Approach 1: Statistical Taste Profiles

### What it is

Pre-compute aggregate statistics per room/topic from the existing structured AI data. No new AI calls required — this is pure data analysis over what Gemini has already tagged.

### How it works

For each room (kitchen, bathroom, etc.), compute:

- **Style distribution:** Traditional 38%, Transitional 24%, Farmhouse 18%, Modern 12%, Other 8%
- **Material frequency:** marble (89 items), wood (156), brass (47), glass (34), tile (78)
- **Color palette:** aggregate the `colors` arrays, weight by frequency, extract dominant palette
- **Recurring elements:** farmhouse sink (47), kitchen island (89), open shelving (23), subway tile (31)
- **Source distribution:** where did these saves come from? 70% Pinterest, 15% Facebook, 10% Houzz, 5% scans

Output: a structured JSON profile per room, plus a natural-language narrative generated from the statistics.

### Example output

> **Leslie's Kitchen Aesthetic**
>
> Based on 369 saved items across Pinterest (269), Facebook (56), Houzz (26), and magazine scans (18).
>
> Leslie's kitchen direction is firmly traditional-transitional, with warm wood tones, marble countertops, and brass hardware appearing consistently. She gravitates toward light, airy spaces — white and cream dominate her color palette, with natural wood and gold/brass as accents. The farmhouse sink appears in 47 saves, making it a clear preference. Kitchen islands are nearly universal (89 items), always with seating. Open shelving appears in 23 saves, usually alongside closed cabinetry rather than replacing it.
>
> Notable: she has saved both very traditional (raised panel, ornate) and quite clean transitional pieces — this tension is worth discussing.

### Pros

- **Fast to build.** The data already exists; this is aggregation and templating.
- **Transparent.** Every claim is backed by a count. "Marble appears in 89 items" is verifiable.
- **No new API costs.** Pure computation over existing data.
- **Stable.** The output is deterministic — same data produces same profile.
- **Foundation for everything else.** Every other approach builds on this.

### Cons

- **No visual judgment.** Counts don't capture "she saves marble, but it's always Calacatta, never Carrara." The system knows "marble" but not which marble.
- **Gemini's vocabulary limits the analysis.** If Gemini didn't tag something, it doesn't exist in the profile. Gemini might call something "traditional" when a designer would call it "neoclassical."
- **Narrative is templated, not insightful.** "Marble appears 89 times" is informative but not the same as a designer saying "she has a Calacatta problem — half her kitchen pins are one specific marble pattern."
- **Misses tensions and contradictions.** The stats show "38% traditional, 12% modern" but don't flag that this might represent genuine ambivalence worth discussing.

### Effort: 2-3 days

---

## Approach 2: Embedding-Based Cluster Analysis

### What it is

Use the 5,306 Gemini embeddings to find natural clusters within each room/topic — groups of items that are semantically similar to each other. Then characterize each cluster.

### How it works

1. Filter embeddings to a topic (e.g., all kitchen-tagged items)
2. Run dimensionality reduction (UMAP) to project 3,072 dimensions to 2D/3D
3. Apply clustering (HDBSCAN or k-means) to find natural groupings
4. For each cluster: pick the centroid item as "most representative," compute aggregate stats, generate a characterization

### Example output

> **Leslie's Kitchen: 4 Natural Clusters**
>
> **Cluster 1: The Warm Traditional Kitchen** (112 items)
> Cream cabinetry, brass hardware, marble counters, farmhouse sink, natural wood floors. This is her dominant kitchen direction.
> Representative images: [8 thumbnails]
>
> **Cluster 2: The Clean Modern Kitchen** (34 items)
> Flat-panel cabinets, stainless hardware, quartz counters, integrated appliances. A secondary but notable interest.
> Representative images: [6 thumbnails]
>
> **Cluster 3: Kitchen Details & Hardware** (67 items)
> Close-up shots of cabinet pulls, faucets, backsplash tiles, range hoods. Not whole-room but specific elements.
> Representative images: [6 thumbnails]
>
> **Cluster 4: Kitchen Plans & Layouts** (28 items)
> Floor plans, elevation drawings, before/after renovations. Spatial thinking.
> Representative images: [4 thumbnails]

### Pros

- **Discovers structure Leslie didn't explicitly create.** The clusters emerge from the data, not from board names or AI labels.
- **Reveals tensions and sub-preferences.** Finding both a "warm traditional" and a "clean modern" cluster is more nuanced than "38% traditional."
- **Visual representatives are powerful.** Showing the 8 most central images of each cluster is an efficient way to communicate taste.
- **Leverages existing embeddings.** No new Gemini calls needed for the clustering itself.

### Cons

- **Cluster boundaries are arbitrary.** k-means forces a number of clusters; HDBSCAN may find too many or too few. The "right" number of clusters is a judgment call.
- **Characterizing clusters still requires AI.** You need a model to look at a cluster and say "this is the warm traditional group." That's either manual labeling or another LLM call.
- **Embeddings encode Gemini's understanding, not a designer's.** If Gemini conflated two distinct styles, the embeddings will too.
- **Works best for large rooms (kitchen: 369 items), poorly for small ones (home office: 12 items).**

### Effort: 3-5 days (clustering infrastructure + characterization)

---

## Approach 3: Multimodal Representative Selection

### What it is

Use a vision-language model (Claude or Gemini) to look at actual images and select the most representative subset for a given topic. The model sees the thumbnails, not just the labels.

### How it works

1. For a topic (e.g., kitchen), retrieve all relevant items (use board + AI room tags)
2. Pre-filter to a manageable set (~50) using embedding similarity to the topic centroid
3. Send the 50 thumbnails to a multimodal model with the taste profile from Approach 1 as context
4. Ask the model: "Select the 8-12 images that best represent Leslie's kitchen aesthetic. Consider style consistency, material preferences, and the overall narrative these images tell together."
5. The model returns selected image IDs plus a curatorial rationale

### Example prompt

> You are a design consultant reviewing a homeowner's saved inspiration. Here is their statistical taste profile for kitchens: [profile from Approach 1].
>
> Below are 50 kitchen images they saved. Select 8-12 that, shown together, would best communicate their kitchen aesthetic to an interior designer. Consider:
> - Which images represent the dominant style direction?
> - Which show key recurring elements (island, farmhouse sink, brass hardware)?
> - Which capture the color and material palette?
> - Are there any that show a distinctive or unexpected preference worth highlighting?
>
> Return the selected image IDs and a 2-3 sentence explanation of why this set tells the story.

### Pros

- **Visual judgment.** The model can see that two "traditional kitchen" images feel completely different — one is a cozy cottage kitchen, the other is a grand estate kitchen. Label-based selection can't make this distinction.
- **Narrative curation.** The selected set tells a coherent story, not just "top 12 by label frequency."
- **Catches what labels miss.** "She always saves kitchens with a window over the sink" is a pattern visible in images but not captured in any label field.
- **Directly produces the collaborator deliverable.** The output is exactly what goes on the website.

### Cons

- **API cost per generation.** Sending 50 thumbnails to a multimodal model costs real money. At ~$0.003 per image input token, 50 512px thumbnails might cost $1-3 per topic. Acceptable for occasional generation, not for real-time.
- **Non-deterministic.** Run it twice, get different selections. The A/B testing Jim described would help converge, but it means the output isn't stable.
- **The model's taste isn't Leslie's taste.** Claude or Gemini will pick images that *it* thinks are representative, filtered through its own aesthetic training data. A model trained on high-end design magazines might select the most "impressive" kitchens rather than the ones Leslie actually likes most.
- **Context window limits.** 50 thumbnails at 512px is feasible but approaching limits. Larger candidate sets require pre-filtering.

### Effort: 3-5 days (prompt engineering + A/B testing framework)

---

## Approach 4: Generative Mood Boards

### What it is

The most ambitious approach. Combine Leslie's real images with AI-generated synthesis elements to produce mood boards: a single visual artifact that communicates her aesthetic for a room.

### How it works

1. Run Approaches 1-3 to get the taste profile, clusters, and representative images
2. Extract a color palette from the representative images (pixel-level k-means clustering, not Gemini's label-level colors)
3. Assemble a mood board layout: representative images arranged with intentional composition, plus:
   - A generated color palette strip (actual hex swatches sampled from her images)
   - Material/texture callouts ("marble," "brass," "white oak" with sampled image patches)
   - A short narrative characterization
   - Optionally: an AI-generated "concept image" that synthesizes her aesthetic into a single scene
4. Output as a high-resolution image or HTML page

### Example output

A mood board for "Leslie's Kitchen" would be a single visual artifact containing:

- 6-8 of her actual saved images, arranged by a layout algorithm (large hero image + smaller supporting images)
- A color palette strip: 5-6 swatches extracted from her images, showing the warm white → cream → gold → natural wood range
- Material callouts: small cropped patches showing her recurring marble, brass, and wood preferences
- A 2-sentence characterization: "Traditional-transitional with warm metals and natural stone. Light, airy, and grounded."
- Optionally: an AI-generated image showing "Leslie's ideal kitchen" — synthesized from the patterns, not any one of her saves

### Pros

- **The most powerful communicator.** A mood board is the native language of interior design. A designer receiving this artifact immediately understands the direction.
- **Combines data and aesthetics.** The color palette is data-derived (real pixel values), the layout is aesthetically composed, the narrative is AI-synthesized.
- **The A/B testing loop makes it convergent.** Generate two mood boards, ask Leslie (or Jim, or the AI) which better represents her taste, iterate. Over several rounds, this converges on a stable representation.
- **The AI-generated concept image is a conversation starter.** "Is this what you're going for?" is a powerful question for a designer to ask, even if the image isn't perfect.

### Cons

- **Highest complexity.** Requires image processing (color extraction), layout algorithms, multimodal AI, and potentially image generation.
- **Image generation quality is uncertain.** Current image generation models (DALL-E 3, Midjourney, Stable Diffusion) can produce beautiful kitchens but may not accurately synthesize *Leslie's specific* aesthetic. The generated image could mislead if it doesn't match her taste.
- **The A/B testing loop requires human judgment.** Someone (Leslie, Jim) has to evaluate each iteration. If the system generates 5 variations and asks "which is best?", that's still manual work — just better-targeted manual work.
- **Legal/ethical consideration with AI-generated images.** If the mood board includes a generated image, the collaborator needs to know it's not a real space. Misrepresenting AI-generated content as actual inspiration could mislead design decisions.
- **Layout composition is its own hard problem.** Arranging 8 images + swatches + text into an aesthetically pleasing single-page layout is non-trivial. Bad layout undermines the entire artifact.

### Effort: 1-2 weeks (image processing + layout + generation + A/B framework)

---

## Approach 5: RAG-Powered Conversational Agent

### What it is

An AI agent that collaborators can chat with to explore Leslie's taste. The designer asks questions, the agent retrieves relevant items and synthesizes answers with visual evidence.

### How it works

1. Pre-compute taste profiles (Approach 1) and embeddings (existing)
2. When a collaborator asks a question, embed the query and retrieve relevant items
3. For synthesis questions ("What's her kitchen style?"), load the pre-computed profile and generate a narrative, grounded in specific items
4. For retrieval questions ("Show me kitchens with brass hardware"), vector search + label filter, return a curated grid
5. Maintain conversational context across turns so the designer can drill down: "What about modern kitchens?" → "How do those compare to the traditional ones?"
6. Optionally: multimodal mode where the agent shows images alongside its answers

### Example conversation

> **Designer:** What's Leslie's overall aesthetic direction?
>
> **Agent:** Leslie's collection is predominantly traditional-transitional, with a consistent warmth — cream tones, natural wood, brass and gold metals. Her strongest room collections are kitchen (369 items) and bathroom (502 items), both leaning heavily traditional with marble, subway tile, and farmhouse fixtures. She has a notable interest in French Colonial exterior style (99 items specifically curated for this). The interesting tension in her collection is between very traditional, ornate pieces and cleaner transitional ones — this is worth discussing with her directly.
>
> **Designer:** Tell me more about the kitchen specifically.
>
> **Agent:** [Shows 6 representative kitchen images] Her kitchen direction is anchored in traditional-transitional: warm wood tones or cream cabinetry, marble countertops (appears in 89 items), brass hardware, and farmhouse sinks (47 items). Kitchen islands with seating are nearly universal. She's drawn to natural light — most of her kitchen saves feature large windows. Open shelving appears in 23 saves but always alongside closed cabinetry, suggesting she wants the look without going fully open.
>
> **Designer:** Does she have strong feelings about backsplash?
>
> **Agent:** Subway tile appears in 31 kitchen saves — it's her most-saved backsplash pattern. She leans toward white or cream subway tile in a brick pattern, sometimes with contrasting grout. She's also saved some hexagonal mosaic tile (8 items) and a few patterned cement tiles (4 items), but subway is the clear default. [Shows 4 backsplash-specific images]

### Pros

- **The richest interaction model.** A designer can ask exactly what they need to know, in their own language, and get a tailored answer.
- **Handles both breadth and specificity.** "What's her overall style?" and "Does she like pendant lighting?" are both answerable.
- **Conversational context enables drill-down.** The most natural way to explore a collection — start broad, narrow in.
- **Can serve both audiences.** The interior designer and the builder ask different questions and get different answers from the same system, automatically filtered by track.
- **Grounds answers in evidence.** Every claim links to specific items from Leslie's collection.

### Cons

- **Requires always-on infrastructure.** The agent needs an LLM API key, the Inspirations database, and a server running. Not a static artifact you can hand someone.
- **Cost per conversation.** Each multi-turn conversation costs $0.50-$2.00 in API calls, depending on the model and number of turns.
- **The agent's voice isn't Leslie's voice.** It's synthesizing from data, and the collaborator needs to understand that. "The agent says she likes farmhouse sinks" is different from "Leslie says she likes farmhouse sinks."
- **Hallucination risk.** If the agent claims "she prefers Calacatta marble over Carrara" but the labels only say "marble," that's a hallucination. RAG mitigates this but doesn't eliminate it.
- **Doesn't replace the gallery.** The designer still wants to *look at* the images, not just hear about them. The conversational agent is best as a complement to the visual gallery, not a replacement.

### Effort: 1-2 weeks (RAG infrastructure + taste profiles + conversational memory + UI)

---

## Comparison Matrix

| Criterion | 1. Profiles | 2. Clusters | 3. Multimodal | 4. Mood Boards | 5. RAG Agent |
|-----------|:-----------:|:-----------:|:-------------:|:--------------:|:------------:|
| Build complexity | Low | Medium | Medium | High | High |
| Ongoing API cost | None | None | Low | Medium | Medium |
| Visual quality of output | Text only | Text + reps | Curated images | Full artifact | Text + images |
| Usefulness to designer | Good | Good | Very good | Excellent | Excellent |
| Usefulness to builder | Good | Low | Low | Low | Very good |
| Leslie can trigger it | No | No | Maybe | No (initially) | No |
| Jim can trigger it | CLI | CLI | CLI | CLI | Always-on |
| Requires human review | No | Minimal | A/B rounds | A/B rounds | Per-conversation |
| Builds on previous | — | Uses 1 | Uses 1 + 2 | Uses 1 + 2 + 3 | Uses 1 + 2 |

---

## Recommendation

**Build in layers, starting from the foundation.**

### Phase 1 (this week): Statistical Taste Profiles

Implement Approach 1. This is pure computation over existing data, has zero API cost, and produces the foundation that everything else builds on. The taste profiles go directly into the 8499TimberBridgeLn.com gallery pages as introductory narratives. Immediate value, no risk.

### Phase 2 (next week): Multimodal Representative Selection

Skip straight to Approach 3, using the taste profiles from Phase 1 as context. The cluster analysis (Approach 2) is intellectually interesting but the multimodal selection produces a better deliverable with less infrastructure. Use Claude's vision capability to select representative images for each room, then iterate with A/B testing until the selections feel right.

This is where the 8499TimberBridgeLn.com pages go from "all of Leslie's kitchen pins" to "the 30-40 images that best represent her kitchen direction" — which is exactly the deliverable Jim described.

### Phase 3 (following week): Generative Mood Board Prototype

With profiles and curated selections in hand, prototype one mood board — kitchen. Extract the color palette from the selected images, compose a layout, write the narrative. See if the artifact is good enough to show a designer. If yes, produce mood boards for the other key rooms.

The AI-generated concept image is optional and should be treated as experimental. Try it, see if it adds value, don't rely on it.

### Phase 4 (future): RAG Conversational Agent

This is the long-term play. It requires the most infrastructure but provides the richest experience. Build it after the static deliverables are proven — the profiles, selections, and mood boards become the agent's pre-computed knowledge base, and the embeddings enable real-time retrieval for specific questions.

The key architectural insight: the RAG agent's quality depends entirely on the quality of Phases 1-3. If the taste profiles are wrong (because the trust hierarchy wasn't corrected), the agent's synthesis will be wrong. If the representative selections are biased (because the CB: collections skewed them), the agent's visual evidence will be biased. The foundational data work in the Last Try curation spec is a prerequisite for all of this.

---

## A Note on How Far We Can Go

Jim's question — "how far can we go these days" — deserves a direct answer.

The individual AI capabilities are remarkably good in 2026. Vision models can look at 50 kitchen images and pick the 8 that tell a coherent story. Language models can synthesize statistical patterns into natural prose that a designer would actually want to read. Embedding models can find semantic structure in a corpus without being told what to look for. Image generation can produce photorealistic room concepts from text descriptions.

What's hard is not any single capability — it's **composing them into a system that's trustworthy.** The risk isn't that the AI can't characterize Leslie's taste; it's that it characterizes it *slightly wrong* and the designer builds a kitchen that's 80% right and 20% the AI's taste. The "last mile" of trustworthiness is why the A/B testing loop matters, why the trust hierarchy correction matters, and why Leslie's explicit confirmation matters more than any amount of AI analysis.

The approaches above are ordered by trustworthiness: statistical profiles are fully transparent and verifiable; multimodal selection is inspectable (you can see what the model picked and disagree); mood boards are opinionated but reviewable; the conversational agent is the least controllable but the most powerful. The recommendation is to build from the trustworthy foundation outward, adding AI autonomy only where it's proven to help.
