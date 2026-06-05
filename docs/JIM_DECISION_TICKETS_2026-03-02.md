# Jim Decision Tickets (Mar 2, 2026)

> Historical decision packet (2026-06-03): these tickets remain useful for the
> ingest and video-poster decisions they record. Collaborator-access references
> are legacy under D021.

Purpose: explicit product decisions and acceptance gates for the bug-fix sprint.

Status: `APPROVED BY JIM`
Decision interview completed on Mar 2, 2026.

## Final Outcomes

| Ticket | Decision | Status |
|---|---|---|
| `JIM-1` | Use Explorer-aligned ingest tag groups: `source`, `rooms`, `styles`, `materials`, `types`, `colors`, `elements`; include `actor` and `date/time` auto-tags on ingest | Approved |
| `JIM-2` | Expose Clip subtype branches now (`Clip > Scan / Photo / Video`) | Approved |
| `JIM-3` | Preserve scan doc/page suffixes when title override is applied | Approved |
| `JIM-4` | Implement video poster generation now | Approved |
| `JIM-5` | No assumed passes. Manual sign-off must use real run log with pass/fail; failures tracked as bugs; sprint cannot close with unresolved P1/P2 unless explicitly deferred | Approved |

---

## `JIM-1` Ingest Tag-Chip Source Set

### Final decision
Use Explorer-relevant tag groups in ingest UI:
- `source` (upload media subtype context: `scan`, `photo`, `video`)
- `rooms`
- `styles`
- `materials`
- `types`
- `colors`
- `elements`

Also auto-apply ingest metadata tags:
- `actor:<name>`
- `ingested_at:<iso8601>`

### Implementation acceptance criteria
1. All three ingest forms (scan/photo/video) show the same grouped Explorer-aligned chip framework.
2. Manual chip selection dedupes case-insensitively.
3. Auto tags (`actor`, `ingested_at`) are applied to every successful ingest batch.
4. Ingest tags are persisted to `asset_labels` and visible in modal labels.

---

## `JIM-2` Clip-Bucket Taxonomy Visibility

### Final decision
Expose subtype branches under Clip now.

### Implementation acceptance criteria
1. Sidebar/browse tree shows `Clip` with explicit subtype branches:
   - `Scan`
   - `Photo`
   - `Video`
2. Counts for subtype branches are accurate and update after ingest.
3. Selecting subtype branch filters correctly by `content_kind`.
4. Existing collaborator hidden-access constraints remain intact.

---

## `JIM-3` Scan Title Override Semantics (Split Pages)

### Final decision
Keep suffix-preserving behavior for scan split pages (`- doc N pM`).

### Implementation acceptance criteria
1. Scan title override keeps doc/page suffixes.
2. Photo/video title override remains exact (no suffix append).
3. Existing tests for scan suffix behavior remain green.

---

## `JIM-4` Video Poster Generation Strategy

### Final decision
Implement poster generation now.

### Implementation acceptance criteria
1. Video ingest generates a poster/thumb artifact usable in grid preview.
2. Video cards display poster image reliably before playback.
3. Modal video playback still works with poster fallback intact.
4. Poster generation failures degrade gracefully (video remains accessible).
5. Add automated tests for poster generation/serving behavior where feasible.

---

## `JIM-5` Manual Sign-Off Gate (Bug-Fix Sprint Closure)

### Final decision
No checklist item is considered passed until manually tested and logged.

### Required sign-off rule
1. Execute manual run on target platforms (iPad + desktop).
2. Log each checklist item as `pass` or `fail` with notes.
3. Each `fail` becomes a tracked bug with owner + repro.
4. Sprint cannot close while any P1/P2 failure remains unresolved, unless explicitly deferred.

### Execution update (Mar 4, 2026)
- Manual sign-off run completed.
- Run log: `docs/MANUAL_SIGNOFF_LOG_2026-03-04.md`
- Outcome: all listed checklist areas passed; no unresolved P1/P2 manual failures.

### Minimum checklist areas
- Owner grid + explorer core flows.
- Collaborator default + browse-unlock behavior.
- Add Media scan/photo/video ingest with title/tags.
- Modal share/print/source actions.
- iPad Safari + desktop browser validation.

---

## Execution Order (from decisions)

1. Implement `JIM-1` ingest taxonomy + auto-tag behavior.
2. Implement `JIM-2` Clip subtype branch exposure.
3. Implement `JIM-4` poster generation.
4. Run full automated suite.
5. Execute `JIM-5` manual sign-off run log.
