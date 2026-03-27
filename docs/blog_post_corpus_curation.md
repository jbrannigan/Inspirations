# From 6,000 Pins to a Searchable Design Corpus: What I Learned Building an AI-Powered Curation System

My wife Leslie has spent years saving home design inspiration — kitchen ideas on Pinterest, construction tips on Facebook, magazine clippings from Southern Living, photos from Houzz. When we started planning our custom home build, we had a problem that felt familiar from my career in information science: thousands of unstructured data points, scattered across platforms, with no unified way to search, analyze, or share them.

What started as "let's organize Leslie's pins" became a year-long project that changed how I think about AI-assisted curation, the limits of multimodal classification, and what it actually takes to make a personal corpus useful to other people.

## The Starting Point: Scraping and Normalizing

The first challenge was getting the data out of its silos. Pinterest doesn't offer a bulk export. Facebook saved items are even harder to extract. Magazine scans were sitting in folders on a hard drive.

We built browser-based scrapers that captured metadata alongside images — Pinterest's SEO alt text, Facebook post text, board assignments, engagement counts. The result was 6,295 assets from four sources: 3,783 Pinterest pins, 2,405 Facebook saved items, 107 magazine scans, and a handful of Houzz photos. All normalized into a single SQLite database with consistent fields for source, URL, board assignment, and content type.

This normalization step is unglamorous but critical. The same kitchen image might have been saved to a Pinterest board called "kitchen," a Facebook collection called "Dream Kitchen Ideas," and clipped from Architectural Digest. Without a common schema, you can't ask cross-platform questions.

## Enrichment: What Gemini Sees That Humans Don't Type

Raw scrape data is thin. A Pinterest pin might have a title like "a bathroom with two sinks and a shower" — auto-generated alt text, not a human description. To make the corpus searchable, we sent 6,186 thumbnails through Google's Gemini 2.5 Flash model for structured image analysis.

Each item came back with a 13-field JSON response: rooms, styles, materials, colors, elements, lighting, fixtures, appliances, brands, text visible in the image, and free-form tags. This produced 152,395 label rows across 20,636 distinct labels. We also generated 3,072-dimensional semantic embeddings for 5,306 items using Gemini's embedding model.

The Gemini enrichment was transformative for search — you could now find "brass hardware" across all sources even if no one ever typed the word "brass." But the descriptions themselves had a problem we came to call "frou-frou": verbose, generic, and focused on obvious visual content rather than the design-relevant details a professional would care about. "A beautifully designed transitional bathroom featuring elegant marble countertops and warm brass accents" tells you less than "Calacatta marble, unlacquered brass, sconce mounted at mirror height."

This is a generalizable lesson about using LLMs for domain-specific classification: the model's vocabulary and emphasis don't match the domain expert's. A designer would never describe a kitchen as "beautifully designed" — that's assumed. They'd note the specific cabinet profile, the countertop edge detail, the relationship between the backsplash and the hood. Prompt engineering helps, but there's a ceiling to how domain-specific you can make a general-purpose vision model.

## Visualization: Force-Directed Semantic Spaces

With structured tags and embeddings in hand, we built two visualization modes to explore the corpus spatially rather than through keyword search.

The 2D explorer uses D3's force-directed simulation on an HTML canvas. Each item is a node. Semantic "attractor" poles — toggleable chips for rooms (Kitchen, Bathroom, Bedroom), styles (Modern, Farmhouse, Traditional), materials (Marble, Wood, Brass), and colors — pull matching items toward labeled positions. The physics runs synchronously for 200 ticks to find a settled layout, then renders a single frame. Toggling an attractor re-runs the simulation for 150 ticks. The result is a spatial map where clusters of similar items emerge without anyone defining them.

The 3D version uses Three.js with a custom force simulation — no d3-force-3d dependency. Nodes are camera-facing billboard sprites with lazy-loaded thumbnails. The same attractor logic operates in three dimensions, with orbit controls for rotation and zoom. A grid-hash collision system prevents overlap.

Both modes share a key design decision: pre-computed physics by default, with a "Live" checkbox for real-time simulation. This avoids continuous CPU cost while still letting you watch the simulation respond when you toggle an attractor.

The visualization revealed something that statistics alone couldn't: Leslie's taste has genuine internal tensions. Toggle "Kitchen" and "Traditional" together, and items cluster tightly. Toggle "Kitchen" and "Modern," and a smaller but distinct cluster appears in a different region. The force-directed layout makes the relative weight of these sub-preferences visually immediate in a way that a bar chart ("38% Traditional, 12% Modern") doesn't.

## The Trust Hierarchy Problem

Midway through the project, we discovered a significant data integrity issue. A prior Claude Code session had created 12 "builder collections" (CB: prefix) grouping items by theme — "CB: Kitchen," "CB: Master Bath," etc. These were documented in the system's CLAUDE.md file as "Human-curated groupings" with "the highest intent signal."

They weren't. They were AI-curated groupings based on Gemini tags and board names, created by a large language model that (reasonably) organized items into useful categories. But the system had started treating them as ground truth — more trusted than Leslie's own board placements.

This is a subtle but important failure mode for AI-assisted workflows: the system's documentation didn't distinguish between human curation and AI curation, and downstream components amplified the error. The chat agent, the catalog system, and the trust hierarchy all weighted these collections as Leslie's deliberate choices when they were actually an AI's interpretation of her choices.

The fix was a corrected trust hierarchy: Leslie's board placements first (she deliberately saved an item to "kitchen"), then Jim's triage decisions, then Leslie's direct edits, then the AI-curated collections (useful as starting hypotheses but unconfirmed), then Gemini's tags and labels at the bottom.

## The Pivot: From "Best Images" to "Searchable Corpus"

The original question was narrow: how do you find the 30-40 images that best represent Leslie's kitchen aesthetic to share with an interior designer? That's a selection problem — rank items by representativeness, pick the top N.

But working through the data revealed that the more valuable question was different: how do you organize a personal design corpus so that multiple professionals with different needs can each find what's relevant to them?

An interior designer wants to see style direction — finishes, colors, fixtures, spatial feel. An architect wants floor plan references, exterior precedents, and spatial relationships. A builder wants construction details — insulation approaches, foundation techniques, HVAC system comparisons. The same corpus serves all of them, but through completely different lenses.

This reframing — from selection to organization — changed the architecture. Instead of one ranked output, the system needed a two-track split (style vs. construction), per-room categorization, a canonical board mapping (consolidating Facebook's 80+ fragmented board names into 15 categories), and track-specific catalogs that a downstream website could consume as structured JSON.

The website already existed — a Next.js application at 8499TimberBridgeLn.com with role-based access control and separate pages for design goals and construction goals, each reading from JSON data files. The Inspirations project's job shifted from "generate a gallery" to "produce the structured data that feeds an existing rendering system." The export pipeline produces JSON; the website renders it. No new website code needed.

## What I'd Tell Someone Starting a Similar Project

First, normalize early and preserve provenance. Every piece of metadata should carry its source — was this title written by a human, generated by Pinterest's alt-text system, or written by Gemini? The answer determines how much you should trust it.

Second, LLM enrichment is powerful for search but unreliable for curation. Gemini's structured tags made the corpus searchable across 20,000+ labels. But its aesthetic judgments weren't calibrated to our domain. Use AI for breadth (tagging everything), not for depth (deciding what's best).

Third, visualization is worth the engineering investment. The force-directed explorer didn't just look interesting — it revealed structural patterns in the data that statistical summaries missed. Seeing 300 kitchen items physically separate into traditional and modern clusters, with a transitional bridge between them, communicates something that no bar chart or word cloud can.

Fourth, trust hierarchies matter more than you'd expect. When your system has multiple sources of classification (human curation, AI tags, AI-created collections), being explicit about which takes precedence prevents subtle errors that compound over time.

And finally, the most useful reframing was recognizing that the problem wasn't "pick the best images" but "make the corpus navigable by people who don't know what's in it." That's an information architecture problem, not a machine learning problem. The AI is a powerful tool for enrichment and exploration, but the organizing intelligence — the decision about what matters to whom — is still a human design problem.

---

*Jim Brannigan is building a custom home in Tennessee and apparently can't stop turning personal projects into data engineering exercises. The Inspirations project is open source and runs on Python's standard library, SQLite, Gemini, and stubbornness.*
