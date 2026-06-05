# Inspirations Current Handoff

Last updated: 2026-06-03

This is the authoritative reboot and lost-context resume document. Historical
handoffs and sprint plans remain in `docs/` for provenance, but they do not
override this file, `README.md`, `CLAUDE.md`, or `DECISIONS.md`.

## Start Here

- Repo: `/Users/minime/Projects/Inspirations`
- Branch: `codex/collection-pdf-retire-sharing`
- Draft PR: [#71](https://github.com/jbrannigan/Inspirations/pull/71)
- App port: `8001`
- Live database: `data/inspirations.sqlite`
- Active product: Jim and Leslie's local corpus curation/QC app
- External handoff: a standalone PDF for exactly one collection at a time
- Retired product layer: live collaborator sharing, magic links, actor context,
  collaborator questions, and app-dependent collection links

Resume:

```bash
cd /Users/minime/Projects/Inspirations
git checkout codex/collection-pdf-retire-sharing
./tools/inspirations_service.sh status
./tools/inspirations_service.sh logs
```

If the launchd service is not installed or running:

```bash
./tools/inspirations_service.sh install
```

Open:

- Mac: `http://127.0.0.1:8001`
- iPad/iPhone: `http://<mac-lan-ip>:8001`

Find the current Wi-Fi LAN address with:

```bash
ipconfig getifaddr en0
```

## Current Product Contract

Keep active:

- Grid and Explorer, including the 2D/3D Explorer stack
- sidebar source, board, collection, and `Refine By` filtering
- live text filtering
- browse-first collection making
- optional Review/QC and one-by-one triage
- flagged, keeper, and discarded state
- title repair, media repair, annotations, notes, imports, and source-link QC
- Dave/chat/catalog
- one-collection standalone PDF export

Do not revive without a new explicit decision:

- collaborator actor or magic-link UX
- shared-collection assignment and generated app links
- `?actor=...&collection_id=...` context links
- collaborator question workflow or owner question polling
- `Share Collections` as a live-link product
- static browser share portal as the primary designer deliverable
- DevLauncher as the Inspirations uptime mechanism

Legacy sharing schema remains intentionally. Do not drop `actors`,
`collection_shares`, `collections.intent`, `collections.shared_actor_id`, or
annotation actor/type columns in an incidental cleanup.

## Current UX Contract

The app has a stable global header and a persistent curation bar above the
canvas. The curation bar remains visible while scrolling and owns:

- item count
- shared text filter
- active-filter summary and clear action
- `Show` selector
- contextual `Export Collection PDF` action
- Explorer controls when Explorer is active
- Review or Make Collection action rows when those modes are active

`Show` options are:

- `Usable items`
- `All items, including discarded`
- `Keepers`
- `Flagged`
- `Discarded`

The `Show` selector changes visible item scope only. It must not change which
detail view opens.

Card interaction rules:

- normal Browse Grid card click opens a calmer detail view
- Review Grid card click opens detail with advanced QC/editing tools
- Review checkboxes select cards for bulk actions
- the explicit `One-by-one` action opens the fast triage screen
- one-by-one review has `Edit title / media`, which opens detail with advanced
  QC/editing tools
- Make Collection is a separate selection mode; card clicks select cards there
- entering Explorer closes Make Collection selection mode

Advanced item editing is Review-scoped. Title repair, media repair, and Track
Review controls appear in grid Review and one-by-one `Edit title / media`, even
for ordinary items that were not pre-flagged as ambiguous. Browse should not
show those advanced repair panels. Edits made in Review detail must remain
visible when returning to one-by-one review.

Media repair is reversible. The gallery exposes previously used saved media
from `asset_media_repair_audit` as selectable candidates, even when a later
`Find source media` check returns no post images. The action opens the panel
immediately, shows an in-progress state, and reports whether source images were
found, none were found, or the check failed. Choosing a previous image archives
the current media in turn and queues the normal Admin search-evidence refresh.

Flagged cards use one stateful quick-action control. The persistent brown
`Unflag follow-up` button is both the flagged-state indicator and the removal
action; there is no separate red flag badge.

The Grid automatically requests the next asset page before the curator reaches
the bottom. `Load More` remains a fallback and must show a loading state rather
than appearing inert on slower LAN/iPad requests. If the curator changes scope
while an automatic append request is active, the queued full reload must run as
soon as that request finishes so the selector and visible cards cannot disagree.

## Collection And Data Baseline

Observed against `data/inspirations.sqlite` on 2026-06-03:

- 5,340 assets in the active database
- 4,666 usable assets with null triage status
- 674 discarded assets with `triage_status='hidden'`
- 15 active collection folders
- 12 `CB:` AI-derived representative starting sets
- 3 architect first-meeting scan cohorts

The `CB:` collections are starting hypotheses, not highest-trust human
curation. Leslie's original board placement remains a stronger intent signal.

Collection-folder archiving and discarded assets are separate concepts.
Archiving or deleting a collection folder does not hide or delete its member
assets.

Obsolete `pins:` source-board mirror folders and completed `Review:` workflow
folders were removed after a local SQLite backup. Source-board browsing now
uses live `assets.board` metadata.

Live UI counts observed during the latest browser verification:

- usable: `4666`
- all items, including discarded: `5340`
- discarded: `674`
- flagged: `99`
- keepers: `0`

Flagged and keeper counts are expected to change as curation continues.

## Service Reliability

Inspirations is installed as a logged-user launchd LaunchAgent:

- label: `com.jimbrannigan.inspirations`
- command: `tools/run_review_server.sh`
- bind: `0.0.0.0:8001`
- restart policy: `KeepAlive`
- logs: `data/logs/inspirations-8001.out.log` and
  `data/logs/inspirations-8001.err.log`

This starts after Jim logs into the Mac mini following a reboot. It does not
require an open terminal or DevLauncher. See
`docs/INSPIRATIONS_SERVICE_RUNBOOK.md`.

`run_server()` runs `ensure_schema()` once before starting
`ThreadingHTTPServer`. Normal API, catalog, media, and scan-PDF requests must
not run migrations or metadata backfills. Request-time schema writes previously
caused SQLite lock storms under concurrent thumbnail traffic.

Do not stop or repurpose port `8003`; it belongs to the separate Home website
and DevLauncher work.

## Current Branch Scope

The unmerged branch combines:

- standalone one-collection PDF export and retirement of active live-sharing UI
- collection archive cleanup semantics and management
- browse-first persistent curation bar
- stable `Show` scope semantics
- Review-scoped advanced detail editing and calmer Browse detail
- explicit one-by-one fast triage with `Edit title / media`
- separate visual Make Collection mode
- automatic Grid pagination with `Load More` fallback
- launchd service tooling and local logs
- startup-only schema assurance for threaded serving
- tests and documentation for the above behavior

Local-only runtime data, exports, backups, media, and logs under `data/`,
`store/`, and `imports/` must not be committed.

## Verification State

Browser verification completed against `http://127.0.0.1:8001`:

- curation bar remains sticky while Grid scrolls
- `Show` options return expected live counts
- selection persists across `Show` changes
- Review and Make Collection do not change global header height
- Explorer uses the shared search field and does not show a duplicate search
  field
- Explorer Categories and tuning controls remain available
- Browse card clicks open calmer detail while Review card clicks expose advanced
  QC/editing tools
- Browse detail hides advanced title/media/track repair panels
- grid Review detail exposes title editing, media repair, and Track Review
- explicit one-by-one review shows `Edit title / media`
- one-by-one `Edit title / media` opens Review-scoped advanced detail
- media repair on item `00a380ec-419b-4424-8da7-f59db468a4d3` shows the
  generated text card in use, preserves `Previously used: Saved image`, and
  reports the no-source-image result after a live source check
- flagged tiles show one brown `Unflag follow-up` control rather than two flag
  icons

Latest completed automated verification before this handoff:

```text
node --check app/app.js
node --check app/shared.js
git diff --check
ruff check src tests
PYTHONPATH=src python3 -m unittest discover -s tests -v

Ran 381 tests in 64.140s
OK
```

Run the same commands again after any final cleanup or before pushing.

## Next Work

The likely next product issue is improving collection creation and ordering:

- make the collection-building workflow feel obvious for Leslie
- support deliberate manual item ordering for PDF output
- polish empty collection creation only if it remains useful
- continue source/media/title QC as new problems are found

The user has said the iPad detail layout is not a priority. iPad/LAN browsing
and Explorer stability still matter, but do not spend a large UX pass on the
detail modal solely for iPad without a new request.

## Documentation Hierarchy

Use these as current:

- `README.md`
- `CLAUDE.md`
- `DECISIONS.md`
- `OPEN-QUESTIONS.md`
- `docs/CURRENT_HANDOFF.md`
- `docs/INSPIRATIONS_SERVICE_RUNBOOK.md`
- `docs/COLLECTION_PDF_EXPORT_HANDOFF_2026-05-27.md`
- `docs/EXPLORER_CONTROL_HANDOFF_2026-05-24.md`
- `docs/COLLECTION_ARCHIVE_CLEANUP_HANDOFF_2026-06-01.md`

Many older specs intentionally preserve collaborator-era decisions. They are
historical provenance, not current instructions. Documents that could be
mistaken for active plans have a legacy note at the top.

## Guardrails

- Backend remains Python standard library only.
- Frontend remains vanilla HTML/CSS/JS with no build step.
- Schema changes go through the migration system in `db.py`.
- All CLI commands output JSON.
- Validate external URLs through `security.py`.
- Do not change Gemini model selection without user approval.
- Preserve importer idempotency.
- Do not commit `CONTEXT.md`, `context.md`, `data/`, `store/`, or `imports/`.
