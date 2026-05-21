# TODO — Inspirations App

**Last reconciled: Mar 27, 2026** (cross-referenced with New Home prototype-web and Dave standalone project)

## DB location
`data/inspirations.sqlite` (CLI default: `--db data/inspirations.sqlite`)

---

## Open Backlog

### P1 — Review UX unification (Grid + Explorer + role model)

Active scope/acceptance doc: `docs/SPRINT1_AGENDA_NEXT.md`

- Run a focused UX review of current Grid review mode redundancy.
- [x] Owners see one consolidated `Review` action set in Grid review and one-by-one review (`Keep`, `Hide in collection`, `Hide globally`, `Flag`, `Clear`).
- [ ] Explorer review entry still switches to Grid review for safety; revisit native Explorer action parity after Grid/one-by-one stabilizes.
- Information architecture target (owner view):
  - [x] Root 1: `Status` tree — `All` at root, children: `Pending`, `Keepers`, `Hidden`, `Needs comment`, `Flagged`.
  - [x] Root 2: `Collections` (peer root).
  - [x] Root 3: `All Items` (peer root for corpus browsing facets/sources).
- Information architecture target (collaborator view):
  - Hide entire `Status` block.
  - `Collections` first, `All Items` as peer. Default `Collections` expanded.
- [x] Collection lifecycle: hidden collections move under a `Hidden` branch within `Collections` for owners.
- [ ] Collection lifecycle polish: owner hide/restore/delete actions exist in Manage Visibility; decide whether to add per-collection inline actions in the sidebar.
- Scope hierarchy copy: `Hide in this collection` vs. `Hide globally` vs. `Keep` (corpus-level).
- Follow-up note: switching out of one-by-one review should feel like moving between review modes rather than exiting the workflow. Implemented in current UX unification slice: one-by-one now returns to Grid review when launched from Grid review.

### P1 — Dave replacement (full rebuild within Inspirations)

**Status: needs scoping + planning before implementation.**
Spec: `docs/DAVE_CONVERSATION_SPEC.md` (Mar 20, 2026)

Dave replaces the existing chat stub with a full conversational design librarian, built as
a new full-page view inside the Inspirations app (same pattern as Grid and Explorer views).
The existing chat panel is retired when the new Dave ships.

**What the spec defines:**
- Full-page conversation view — thread + fixed input + quick-action chips
- Rich response types: item card strips, tile grids, mood boards, comparisons, checklists,
  product tables, construction concern lists, video embeds, HTML artifacts
- Image lightbox with AI metadata + "Open in Inspirations" deep-link
- Conversation history (localStorage, auto-saved, restorable)
- Two-pass retrieval: fast intent analysis (Haiku/Gemini Flash) → hybrid retrieval
  (embedding cosine search + structured SQL filter) → optional VLM reranking → synthesis (Claude)
- Category-aware response style: style/aesthetic, product selection, landscape, construction
- Rolling 10-turn context window for natural follow-ups

**What needs to be scoped before build:**
- [ ] Which AI provider for intent analysis (Pass 1) and synthesis (Pass 2) — Gemini vs. Claude?
- [ ] Embedding readiness — how many assets have embeddings today? Is `ai embed` pipeline complete?
- [ ] Entry point UX — header nav button? Replaces existing chat icon? Keyboard shortcut?
- [ ] "Open in Inspirations" deep-link direction — Dave → Grid item, or do both share a modal?
- [ ] Collection management actions from Dave (e.g. "Save as collection") — scope in v1 or defer?
- [ ] Server-side vs. client-side retrieval pipeline — new API endpoints needed
- [ ] Build order: retrieval backend first, then UI, or prototype UI against stub data first?

### P1 — Cross-site actor/role admin

Multi-role management (architect, builder, legal, landscape) is **implemented in New Home
prototype-web** — roles stored as subtypes in the shared Inspirations SQLite `actors` table.
What remains open here:

- [ ] Single owner UI in Inspirations admin to manage actors across both Inspirations and New Home
  (add/remove/edit roles without touching the New Home app directly).
- [ ] Cross-site admin scope: cover the full `8499timberbridgeln.com` actor set from one interface.

Named user admin (email proxy identity) is blocked on the above.

### P1 — IA harmonization with New Home website

New Home prototype-web has its own IA (timeline, files, checklist, design goals, construction goals).
The open question is whether Inspirations sidebar/nav naming and the `/inspirations` bridge page
(in New Home) need explicit alignment work, or whether they stay decoupled.

- [ ] Review `/inspirations` bridge page UX in New Home prototype-web.
- [ ] Decide if shared nav chrome or naming conventions are needed, or if they stay independent apps.

### P2 — Explorer polish

- [ ] Side panel vs. control panel overlap audit — decide if both needed, remove redundancy.
- [ ] Attractor/anchor clarity + spacing controls — more distinct cluster balls.
- [ ] Anchor de-select persistence bug — anchors should fully clear after unselect.
- [ ] Header view-toggle icon polish — matched pair, equal visual weight, no Safari clipping.
  - Explorer target style: perspective cube, lighter line weight, internal cluster dots.
- [ ] 3D hover preview experiment — non-modal hover enlarge for crowded thumbnails (validate with Jim first).
- [ ] 3D thumbnail rendering speed — prioritize nearest-visible thumbs, reduce time-to-first-texture.

### P2 — Collaborator question workflow

Sprint spec: `docs/SPRINT_COLLAB_QUESTION_WORKFLOW.md`

- Define how collaborators ask questions tied to shared context links.
- Define response/threading in an in-app thread panel.
- Ensure question context is unambiguous without brittle manual quoting.

### P2 — AI title quality audit + replacement

Baseline draft: `docs/AI_TITLE_AUDIT_BASELINE_2026-03-01.md`
Dry-run CLI: `inspirations ai title-audit --table-out <path>`

- Produce count/quality trend/reason breakdown and candidate replacement strategy.
- Evaluate source click-through + DOM title extraction as background workflow, then human vet.

### P3 — Architecture + ingestion

- [ ] Ingestion harness — idempotent incremental ingest path (skip existing; ingest only new/changed).
- [ ] Optional Explorer edges — evaluate as toggle-only experiment (not default).
- [ ] Unify Home + Inspirations server architecture — backup/rollback plan required first.
  *Note: New Home prototype-web is Next.js; Inspirations is Python stdlib. Unification scope TBD.*

### P3 — Tagging completeness confidence framework

Define if needed and, if so, set a measurable target by source/pipeline before implementing.

---

## Deferred / Platform

- **External access via Cloudflare Tunnel** — serve Inspirations at `8499timberbridgeln.com/inspirations-app`
  for collaborators. Spec: `docs/DEPLOYMENT_EXTERNAL_ACCESS.md`. The BASE_PATH reverse-proxy
  support is already implemented (Mar 2026). New Home has Cloudflare deployment docs
  (`DEPLOYMENT-ARCHITECTURE.md`) — same tunnel covers both. Covers: ThreadingHTTPServer + WAL mode,
  security headers, Secure cookies, Launch Agents for auto-start, rate limiting.
- **Consuming UX** — The New Home `/inspirations` bridge page is the primary collaborator entry
  point. `docs/TODO_CONSUMING_UX.md` is superseded for the New Home use case. Static HTML export
  (`export html`, `export portal`) remains for other sharing contexts.
- **DevLauncher coordination / resilience** — safe-restart lifecycle hooks so one project restart
  doesn't clobber others.
- **Detail modal context expansion** — post text, AI labels, video analysis context.
- **Sidebar state persistence** when closing/reopening modal.
- **Small boards UX** refinements.
- **Jim's 16 tagged reels** — interactive review workflow (video analysis stored, intentionally
  not auto-triaged, preserved for collaborative review).
- **45 failed reel downloads** — retry or mark-unavailable decision.
- **UX-driven ingest smoke test** — end-to-end test for adding photos, scans, other media.
- **iPhone Explorer** — rotate crash deferred; active platforms are iPad + desktop only.

## Technical Debt

- **Rollback control placement** — move rollback controls and history visibility to Admin page UX
  (owner-only) so operational actions live in one place. Keep chat-triggered rollback for now.

---

## Tag System (Jim's Anomaly Markers)

Tags are separate from Flags. Tags mark items where Jim noticed something unusual (e.g. thumbnail
label mismatch). The 16 tagged reels have video analysis stored but were intentionally not
auto-triaged; they are preserved for collaborative review.

---

## Completed Sprint History

All completed work collapsed here for reference. Full detail in git log and sprint docs.

### Sprint 0 — P1 Stabilization (Mar 2, 2026) ✅
- Header view-toggle icon polish (matched 16px SVG pair, Safari-safe)
- 3D canvas side scrollbar / resize interference fixed (flex + overflow containment)
- Explorer count mismatch in 3D fixed (scope-accurate counts)
- Owner modal print-button moved into share/utility action group
- iPhone Explorer rotate crash → deferred (iPad + desktop only)

### Sprint 1 — Collaborator-first browsing (Mar 2, 2026) ✅
- Collaborator default entry = Collections-first shared scope
- `Browse Leslie's collection` unlock affordance + post-unlock click guard
- Collaborator hidden-item leak fixed (server role-gates `include_hidden`)
- `Add Media` unified intake (scan/photo/video, ingest metadata + chips)

### Sprint 6 — P1/P2 Stabilization Bug-Fix (Mar 4, 2026) ✅
- JIM-1: ingest chips align to Explorer groups + auto-tags (`actor`, `ingested_at`)
- JIM-2: Clip > Scan/Photo/Video subtype branches in tree/filter UX
- JIM-3: scan doc/page suffix behavior preserved on title override
- JIM-4: video poster generation in ingest/display pipeline (ffmpeg, fail-open)
- Collaborator browse toggle copy symmetric; tree hierarchy readability polish
- 3D unmatched-node spacing regression fixed (centroid fallback)
- Manual sign-off log: `docs/MANUAL_SIGNOFF_LOG_2026-03-04.md`

### Explore Sprint — UX responsiveness (Feb 28 – Mar 1, 2026) ✅
- Explorer busy overlay + spinner + phase copy (`Fetching…` → `Arranging…`)
- Side tree header/folder click filters both Grid + Explorer (recursive scope)
- Hidden visibility rule in Explorer (role-gated, owner only when Hidden status active)
- Header button to hide/show side panel (localStorage persistence)
- PDF source-link bug fixed (`#page=` anchors, multipage modal mapping)
- 3D deferred settle; dataset-size budgets + nearest-first texture queue
- View mode persisted across reloads; devserver restart hardened

### Elaboration Sprint — Collaboration context link (Mar 1, 2026) ✅
- `GET /api/context/resolve` with role-aware hidden-item handling
- Modal share helpers (Copy Link, Email, Web Share fallback)
- Deep-link restore on app load (`collection_id` + `item_id` + optional `open=1`)
- "Item no longer in collection" missing-state banner
- Annotation edit/delete permissions enforced (owner all; collaborators own-only)
- API tests for context resolve and annotation ownership

### Earlier completions
- Bulk Facebook reel analysis pipeline (951 reels: 640 hidden, 246 kept, 45 errors)
- 3D fine tune: dataset-size tuning profiles, node size calibration, Looks presets
- BASE_PATH reverse-proxy support (Mar 2026) — `server.py` + `shared.js` + `app.js`
