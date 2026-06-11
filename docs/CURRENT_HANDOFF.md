# Inspirations Current Handoff

Last updated: 2026-06-10

This is the authoritative reboot and lost-context resume document. Historical
handoffs and sprint plans remain in `docs/` for provenance, but they do not
override this file, `README.md`, `CLAUDE.md`, or `DECISIONS.md`.

## Start Here

- Repo: `/Users/minime/Projects/Inspirations`
- Branch: `codex/topbar-action-button-states`
- App port: `8001`
- Live database: `data/inspirations.sqlite`
- Active product: Jim and Leslie's local corpus curation/QC app
- External handoff: a standalone PDF for exactly one collection at a time
- Retired product layer: live collaborator sharing, magic links, actor context,
  collaborator questions, and app-dependent collection links

Resume:

```bash
cd /Users/minime/Projects/Inspirations
git checkout codex/topbar-action-button-states
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
- sidebar Browse tree for review status, source, board, collection, and
  classification filtering
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
- contextual `Export Collection PDF` action
- Explorer controls when Explorer is active
- Review or Make Collection action rows when those modes are active

Item visibility scopes now live in the left `Browse` sidebar under
`Review Status`, not in a top-bar `Show` dropdown. Review status choices are:

- `Usable items`
- `Flagged`
- `Keepers`
- `Needs comment`
- `Irrelevant / Discarded`
- `All items, including discarded`

`Usable items` excludes both triage-discarded assets and assets with an active
classification track of `irrelevant`. `Irrelevant / Discarded` is a real union
scope: it returns items with `triage_status='hidden'` plus items whose active
track classification is `irrelevant`. `All items, including discarded` remains
available for owner QC.

Review status choices change visible item scope only. They must not change which
detail view opens. Browse card clicks still open the calmer detail view; Review
card clicks still open detail with advanced QC/editing tools.

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

For Facebook/Pinterest hard cases, `Find source media` depends on the named
authenticated Playwright/Chrome session `media-repair-auth`. Open it with:

```bash
tools/open_media_repair_auth_browser.sh
```

Sign into Facebook/Pinterest in that Chrome window if prompted and leave it
open. The app does not read Safari or Jim's ordinary Chrome windows. Facebook
source capture now scrolls the post/comment modal inside the final extraction
step and labels lazy-loaded comment media as `Scrolled comment image N`. This
was verified on item `154c5218-0ef2-46e8-b30f-5b5b4d9d2fe4`, where `Scrolled
comment image 1` is the drywall-levels graphic.

Flagged cards use one stateful quick-action control. The persistent brown
`Unflag follow-up` button is both the flagged-state indicator and the removal
action; there is no separate red flag badge.

Source-link repair/discard is evidence-aware. Detail view shows the latest
source check status. `Broken link · discard item` / `Mark source unusable ·
discard` hides the item and marks `flagged_note='broken source link'`, but
browser/network errors are not treated as proof that the source is broken. A
discarded broken-source item exposes a restore action that clears that flag and
returns the item to ordinary browsing while keeping the original source URL.

The Grid automatically requests the next asset page before the curator reaches
the bottom. `Load More` remains a fallback and must show a loading state rather
than appearing inert on slower LAN/iPad requests. If the curator changes scope
while an automatic append request is active, the queued full reload must run as
soon as that request finishes so the active scope and visible cards cannot
disagree.

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

The collection sidebar section is a peer to `Browse`; its tree root is `All
Collections`. There is one owner action, `Manage Collections`, which now
contains collection creation, name/description editing, archive, restore, and
permanent delete controls. There is no separate `New Collection` sidebar action
and no separate `Manage Collection Archive` modal.

Obsolete `pins:` source-board mirror folders and completed `Review:` workflow
folders were removed after a local SQLite backup. Source-board browsing now
uses live `assets.board` metadata.

Live UI counts observed during the latest verification:

- usable, excluding active `irrelevant` track: `4349`
- usable without track exclusion: `4664`
- all items, including discarded: `5340`
- discarded: `676`
- flagged: `98`
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

On 2026-06-04, a stale DevLauncher-started Inspirations Python process was
holding `8001` and preventing launchd from taking over. That repo-owned process
was terminated, and launchd is again the active `8001` owner.

`run_server()` runs `ensure_schema()` once before starting
`ThreadingHTTPServer`. Normal API, catalog, media, and scan-PDF requests must
not run migrations or metadata backfills. Request-time schema writes previously
caused SQLite lock storms under concurrent thumbnail traffic.

Do not stop or repurpose port `8003`; it belongs to the separate Home website
and DevLauncher work.

## Performance Baseline

Latest performance sprint completed on 2026-06-10:

- Grid lazy loading appends only newly fetched cards instead of rebuilding all
  already loaded cards. Full Grid rerenders remain reserved for scope/filter
  changes.
- `renderGrid()` and skeleton rendering use document fragments to reduce
  repeated DOM attachment work.
- Explorer `attractor-data` and `layout` API responses have a small in-process
  cache keyed by endpoint parameters plus SQLite mtime. Explicit
  `refresh=1` layout requests still bypass this cache.
- Dynamic gzip uses a faster compression level for local/LAN responsiveness.
- Free-text asset search is backed by SQLite FTS5 (`asset_search_fts`) over
  title, description, board, notes, AI summary, source text, and labels. Known
  mutation paths refresh affected rows.
- Free-text `/api/assets?q=...` requests skip exact total-count scans. The API
  still returns the requested page and correct `has_more`; the UI should treat
  `total: null` as normal for text searches.
- Explicit DB maintenance is available from Admin **Optimize Database** or:

```bash
PYTHONPATH=src python3 -m inspirations --db data/inspirations.sqlite maintenance optimize-db
```

Run it after bulk imports, retagging/re-embedding/title cleanup, large
delete/cleanup batches, or unusual direct DB edits. Do not put it on every app
startup; the current corpus is fairly static and normal Add Media/title/note
paths refresh affected search rows themselves.
- `/favicon.ico` returns quiet `204 No Content` to avoid noisy browser-console
  404s during smoke tests.

Live measurements against `data/inspirations.sqlite` after restarting the
launchd-managed `0.0.0.0:8001` service:

```text
/api/assets?limit=241                         ~100 ms
/api/assets?limit=241&q=exterior              ~61 ms over HTTP, direct store ~12 ms with FTS
/api/assets?limit=241&q=mission               ~10 ms over HTTP
/api/explorer/attractor-data?dims=2           ~151 ms cold, ~68 ms in-process cached
/api/explorer/layout                          ~615 ms cold, ~39 ms in-process cached
```

Direct store-function timing for `q=exterior` after FTS:

```text
exact_total=True   ~14 ms
exact_total=False  ~12 ms
```

## Current Branch Scope

The unmerged branch combines:

- standalone one-collection PDF export and retirement of active live-sharing UI
- collection archive cleanup semantics and management
- consolidated collection manager with create/edit/archive/restore/delete in
  one dialog
- browse-first persistent curation bar
- stable sidebar `Review Status` scope semantics
- Review-scoped advanced detail editing and calmer Browse detail
- explicit one-by-one fast triage with `Edit title / media`
- separate visual Make Collection mode
- automatic Grid pagination with `Load More` fallback
- append-only lazy Grid rendering for pagination
- Explorer API payload caching and faster dynamic gzip for local/LAN response
  time
- launchd service tooling and local logs
- startup-only schema assurance for threaded serving
- tests and documentation for the above behavior

Local-only runtime data, exports, backups, media, and logs under `data/`,
`store/`, and `imports/` must not be committed.

## Verification State

Browser verification completed against `http://127.0.0.1:8001`:

- curation bar remains sticky while Grid scrolls
- top-bar `Show` dropdown is gone; text filtering remains in the curation bar
- left sidebar heading is `Browse`
- `Browse → Review Status` exposes `Usable items`, `Flagged`, `Keepers`,
  `Needs comment`, `Irrelevant / Discarded`, and
  `All items, including discarded`
- raw `Refine By` and `Track` wrappers are not shown in normal Browse IA
- `Browse → Review Status` options return expected live counts
- selection persists across review-status changes
- Review and Make Collection do not change global header height
- Explorer uses the shared search field and does not show a duplicate search
  field
- Explorer Categories and tuning controls remain available
- Browse card clicks open calmer detail while Review card clicks expose advanced
  QC/editing tools
- Browse detail hides advanced title/media/track repair panels
- grid Review detail exposes title editing, media repair, and Track Review
- Review detail renders an already irrelevant item as a grey disabled `Saved as
  irrelevant` action while the `Exclude as irrelevant` switch remains available
  for staging a restore
- when the left sidebar is collapsed, its expand button appears inside the
  sticky curation/filter bar so it remains visible
- explicit one-by-one review shows `Edit title / media`
- one-by-one `Edit title / media` opens Review-scoped advanced detail
- media repair on item `00a380ec-419b-4424-8da7-f59db468a4d3` shows the
  generated text card in use, preserves `Previously used: Saved image`, and
  reports the no-source-image result after a live source check
- flagged tiles show one brown `Unflag follow-up` control rather than two flag
  icons
- Grid lazy loading grew from 120 to 240 to 360 loaded cards using one new
  `/api/assets?...offset=...` request per append
- fresh browser session showed zero console errors on Grid
- Explorer opened as `3D map: 4665 items` with zero console errors/warnings

Latest completed automated verification before this handoff:

```text
node --check app/app.js
python3 -m py_compile src/inspirations/server.py src/inspirations/store.py
git diff --check
PYTHONPATH=src python3 -m unittest discover -s tests

Ran 400 tests in 71.128s
OK
```

Live service check after the run:

```text
Python PID 36840 listening on *:8001
/favicon.ico returns 204
node PID 850 still listening on *:8003
```

Run the same commands again after any final cleanup.

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
