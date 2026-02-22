# Search Strategy (Hybrid + Graph-ready)

## Signals to index
1. **Source metadata**: title, description, board, domain
2. **User input**: notes, annotations, curated collection names
3. **AI tags**: rooms, materials, colors, styles, fixtures, appliances, etc.
4. **Text-in-image**: OCR-style snippets from Gemini
5. **Summaries**: short AI captions for natural-language matching

## Query handling (MVP)
1. Parse user query for **structured filters**: room, material, color, style, brand.
2. Run **keyword search** across metadata + AI labels + summaries.
3. Allow quick pivots via facets (source, board, labels).

## Semantic upgrade (recommended)
Use embeddings for “find images like this text”:
- Generate vectors with the Gemini `embedContent` endpoint (model `gemini-embedding-001`).
- Store vectors per asset; compute cosine similarity at query time.
- Combine results with keyword/tag filters for hybrid retrieval.

## Knowledge graph (future-ready)
A knowledge graph makes “smart” multi-hop questions possible:
- Example edges: `Asset → hasMaterial → white oak`, `Asset → depictsRoom → kitchen`
- Represent as RDF triples or a property graph with typed relationships.
- Later, use graph queries + embeddings for richer retrieval and explanations.

## References
- https://ai.google.dev/gemini-api/docs/embeddings
- https://ai.google.dev/gemini-api/docs/embeddings?hl=en#python
- https://www.w3.org/TR/rdf11-concepts/
