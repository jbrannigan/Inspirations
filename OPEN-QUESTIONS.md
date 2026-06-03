# Open Questions

Unresolved questions and decisions that need input. Check here before starting
new work — your question might already be captured.

---

## ~~OQ001 — Consuming UX for shared collections~~ (resolved D021)

Resolved: live shared-collection UX is retired. The active designer handoff is
a standalone one-collection PDF with embedded images and external source links.

**Questions:**
- What does the designer see when they open a shared HTML export?
- Should there be filtering/search in the shared view?
- Should viewers be able to comment or annotate?
- Is a static HTML file sufficient or do we need a hosted viewer?
- What about mobile (iPad) viewing experience?

**Status:** Historical questions remain in `docs/TODO_CONSUMING_UX.md`.

---

## OQ002 — Natural-language collection management implementation

**Context:** D016 decided to use chat-style prompts for collection management.
The browse-first visual `Make Collection` workflow is now the primary manual
path; this question applies only to complementary power-user operations.

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

## ~~OQ-RESOLVED: Everyday curation workflow~~ (resolved D023)

Resolved: browse-first collection making with optional focused review. The
keeper/hidden schema remains as usable/discarded state rather than a required
corpus-wide backlog.
