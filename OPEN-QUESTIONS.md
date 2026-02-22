# Open Questions

Unresolved questions and decisions that need input. Check here before starting
new work — your question might already be captured.

---

## OQ001 — Consuming UX for shared collections

**Context:** The curation app (local) is for the curator. But shared collections
are viewed by designers/decorators who need a different experience.

**Questions:**
- What does the designer see when they open a shared HTML export?
- Should there be filtering/search in the shared view?
- Should viewers be able to comment or annotate?
- Is a static HTML file sufficient or do we need a hosted viewer?
- What about mobile (iPad) viewing experience?

**Status:** Deferred. Noted as future work in `docs/TODO_CONSUMING_UX.md`.

---

## OQ002 — Natural-language collection management implementation

**Context:** D016 decided to use chat-style prompts for collection management.

**Questions:**
- Client-side pattern matching or server-side AI-assisted?
- What operations need to be supported? (create, merge, move items, split, rename, delete)
- Should it use Gemini or simple keyword/intent parsing?
- How does it handle ambiguity? ("Put the kitchen stuff together" — which items are kitchen?)

---

## OQ003 — Annotation marking during triage

**Context:** During triage review, the user wants to mark items for later annotation
(e.g., a "comment later" checkbox when keeping an item).

**Questions:**
- Should this be a separate status field or a flag on the triage status?
- How do you then walk through just the "needs annotation" items?
- Is it per-asset or per-asset-in-collection?

---

## ~~OQ-RESOLVED: Scrape vs ZIP import~~ (resolved D014)

Resolved: Browser scrape is the primary ingestion path.

## ~~OQ-RESOLVED: Triage workflow~~ (resolved D015)

Resolved: Keeper/hidden card-by-card review with keyboard shortcuts.
