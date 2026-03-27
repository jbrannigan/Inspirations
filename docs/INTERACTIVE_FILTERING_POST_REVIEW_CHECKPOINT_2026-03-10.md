# Interactive Filtering Post-Review Checkpoint

Date: March 10, 2026
Project: Inspirations
Scope: End-of-pass checkpoint after the interactive filtering / human review workflow for top-level track stabilization and media-reliability cleanup.

## Summary

The interactive filtering workflow is complete for the current review stream.

Key result:
- all active review collections in this filtering workflow now have `0` unresolved items
- completed review collections were hidden in the app as archived workflow collections
- superseded workflow docs were moved into the archive directory

This is now a checkpoint state, not an active review state.

## Effective Corpus State

Visible corpus total:
- `4669`

Hidden corpus total:
- `674`

Effective visible track counts after applying latest classifier output plus active human track overrides:
- `Style / Decor = 4115`
- `Construction = 192`
- `Maintenance / DIY = 52`
- `Irrelevant = 310`

Interpretation:
- the visible style corpus remains the dominant corpus, as expected
- construction is now a much tighter, cleaner slice than the old broad-envelope workflow
- maintenance / DIY is stable as a small adjacent bucket
- irrelevant is now explicit and materially cleaner than earlier mixed buckets

## Human Review Totals

Active Jim manual track overrides:
- `Style / Decor = 103`
- `Construction = 191`
- `Maintenance / DIY = 52`
- `Irrelevant = 180`

Media-reliability overrides currently saved:
- `Trust title / source = 1`
- `Thumbnail is placeholder = 2`
- `Thumbnail mismatches content = 3`

Interpretation:
- top-level track review is now the durable human-reviewed layer
- media-reliability controls exist and work, but they have only begun to be used as structured data
- future workflow A should increase use of media-reliability markings without forcing unnecessary track changes

## Completed Review Collections

The following `Review:` collections are complete and were archived by hiding them in the app on March 11, 2026 (UTC):

- `Review: Landscaping Follow-Up - 2026-03-09` (`27`)
- `Review: Inspection Follow-Up - 2026-03-09` (`2`)
- `Review: Source Link Conflicts - 2026-03-09` (`158`)
- `Review: Ambiguous True Contested - 2026-03-10` (`127`)
- `Review: Ambiguous Low Signal URLs - 2026-03-10` (`20`)
- `Review: Ambiguous Media Link Mismatch - 2026-03-10` (`30`)
- `Review: Maintenance / DIY Track - 2026-03-10` (`7`)
- `Review: Media - Trust Title / Source - 2026-03-10` (`96`)
- `Review: Facebook Media Reliability - 2026-03-10` (`44`)
- `Review: Facebook Group Hero Capture - 2026-03-10` (`12`)
- `Review: Hard Facebook Reels - 2026-03-10` (`25`)
- `Review: Hard Facebook Reels - Post Text - 2026-03-10` (`23`)
- `Review: Hard Facebook Reels - Page Unavailable - 2026-03-10` (`0`)
- `Review: Pinterest Media Reliability - 2026-03-10` (`55`)
- `Review: Facebook Group Hero Follow-Up - 2026-03-10` (`5`)
- `Review: Facebook Media Reliability Tail - 2026-03-10` (`6`)

All of these now have `0` unresolved items by the workflow rule:
- visible item
- no active human `track` override

## What Changed During the Final Phase

### Facebook reel path

The reusable Facebook reel path was materially improved:
- the downloader now retries with progressive formats (`hd/sd/best`) when the default path fails or only yields audio
- CLI Gemini auth now supports macOS Keychain fallback via `inspirations_gemini_api_key`
- additional Facebook reels were downloaded and analyzed with `gemini-video`
- authenticated Facebook post-text capture was used to resolve hard reels that were better handled as post text than as video understanding

Net effect:
- the remaining Facebook reel backlog is no longer a general review problem
- the remaining hard cases are now mostly media/source capture problems, not top-level track ambiguity

### Media reliability

The workflow established a clean distinction between:
- track classification
- media reliability

That distinction is now ready for a proper implementation phase.

## Remaining Structural Weaknesses

The review stream is complete, but the system still has structural work left.

### 1. Media-reliability capture is not yet the primary workflow

The app can record media issues, but the practical workflow is still too manual.

Missing behavior:
- source candidate capture should be easier to apply systematically
- candidate replacement image/text review should be more central in the modal
- repeated low-information thumbnails should be batch-addressable

### 2. Some Facebook/Pinterest media still depend on authenticated source capture

The review work proved that:
- public wrapper/public thumbnail evidence is often insufficient
- authenticated source-page text is often the best evidence
- video download/analysis is useful, but not always the first or best step

### 3. Archive state exists in the app only as hidden collections

Completed workflow collections are hidden, not deleted.
This is correct for now, but the app still does not have a richer first-class archive mode for completed review workflows.

### 4. Collection trust/provenance is still too implicit

The review stream is complete, but collection trust is not yet clean.

In particular:
- the `CB:` collections are still easy to misread as deliberate human-curated builder sets
- they were actually created as representative AI-derived sets from high-confidence descriptions/tagging
- they should not be treated as Leslie's or Jim's highest-intent curation

Operational consequence:
- any UX, chat, or browse surface that presents `CB:` collections as human-curated/highest-trust is still overstating their provenance

This should be part of the next collections-cleanup pass, not left implicit.

## Recommended Next Engineering Branch

Do not continue ad hoc review from here.

Recommended next branch:
- implement media-repair workflow `A`

Parallel UX follow-up that should not be forgotten:
- clean up collection provenance/trust presentation, especially for `CB:` collections

Reason:
- classification review is no longer the main bottleneck
- the remaining friction is media evidence quality, capture, and promotion

## Operational State At Checkpoint

Live app:
- `http://127.0.0.1:8001/`

Current owner link for Jim:
- `http://127.0.0.1:8001/?actor=Gq1AgKKfLaB-9qgAOqQuOA`

## Bottom Line

The interactive filtering workflow achieved its intended purpose.

It:
- stabilized top-level track review
- closed the active human review queues
- separated classification from media-quality problems
- left the project at a natural engineering handoff point

The next meaningful work is implementation, not more manual triage.
