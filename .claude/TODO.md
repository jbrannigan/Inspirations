# TODO — Inspirations App

## Current State (Feb 24, 2026)

### What just shipped
- **Bulk Facebook reel analysis pipeline** — 951 reels processed through yt-dlp download → Gemini 2.5 Flash video analysis → auto-triage
  - 640 hidden (irrelevant: cooking, exercise, finance, makeup, pets, comedy)
  - 246 kept with Gemini-assigned titles, boards, and categories
  - 16 tagged by Jim — preserved for interactive review, not auto-triaged
  - 45 download errors (private/deleted reels), 4 analysis errors
- **UX fixes**: total item count in grid header, tree expand persistence, (uncategorized) board filter

### DB location
`data/inspirations.sqlite` (CLI default: `--db data/inspirations.sqlite`)

---

## Priority: Sidebar Tree Redesign

The browse tree is the main navigation but has fundamental problems that make it confusing and misleading.

### Problems

1. **Counts include hidden items** — Facebook shows 1190 but only ~550 are visible. Exercise shows 94 but 90 are hidden. Users click expecting N items and see far fewer.

2. **Status filter and tree are disconnected** — clicking "Hidden" status filters the grid, but the tree doesn't update counts or visual state. The two controls feel independent when they should cross-reference.

3. **Hidden items inflate the tree structure** — Exercise exists as a prominent Facebook sub-board only because of 90 hidden exercise reels. With hidden excluded it's 4 items — barely worth showing.

4. **Gemini board names don't match existing boards** — The reel pipeline assigned granular names like "Kitchen Renovation Tips" instead of mapping to existing "kitchen" board. ~200 reels have orphaned board names, all lumped into "(Unsorted Reels) 799".

5. **Tree is static** — Built from a pre-generated catalog `_index.md` file with baked-in counts. Cannot dynamically respond to triage changes or status filters. This is the root cause of problems 1-3.

### Design direction

- Tree counts should reflect what the user will actually see (exclude hidden by default)
- When a status filter is active, tree counts should update to match
- Consider making the tree DB-driven (live queries) rather than catalog-file-driven
- Normalize Gemini board names to existing boards (map "Kitchen Renovation Tips" → "kitchen")
- Small boards with <3 visible items should collapse into "(Small Boards)" or not show at all

---

## Deployment: Authentication

Before deploying publicly, gate access with email whitelist + magic links:
- Visitor enters email → if on whitelist, receive a magic-link email
- Magic link sets an actor token cookie (same mechanism as current `?actor=` flow)
- No password needed — token-based auth via email verification
- Whitelist managed in Admin page or DB table
- Anonymous visitors see nothing (or a login prompt) instead of the full browse UI

---

## Other Known Issues

- **Detail modal** needs more context: post text, AI labels, video analysis results
- **Sidebar state** doesn't persist when closing/reopening the detail modal
- **"Small boards"** UX could be improved — currently just a catch-all bucket
- **Jim's 16 tagged items** still need interactive Claude Code review (the original anomaly diagnosis workflow)
- **45 failed reel downloads** (private/deleted) — could retry or mark as permanently unavailable

## Tag System (Jim's Anomaly Markers)

Tags are separate from Flags. Tags mark items where Jim noticed something unusual (e.g., thumbnail label doesn't match actual content). The 16 tagged reels now have video analysis stored but were intentionally NOT auto-triaged — they're preserved for Leslie + Jim to review together.
