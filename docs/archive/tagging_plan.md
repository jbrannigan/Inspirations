# Gemini Tagging Performance Plan

This plan summarizes best‑practice guidance from Google Gemini docs and compares it to the current interactive tagging workflow.

## What Google Recommends (Summary)
- **Rate limits are enforced per project** and depend on model + usage tier. Exceeding RPM/TPM/RPD triggers rate‑limit errors. Check limits in AI Studio for your project.
- **Batch API** is recommended for large volumes. It supports file inputs, has a 24‑hour SLO, and is priced at ~50% of standard interactive calls.
- **Batch best practices**: use file input for large requests, check `batchStats` and per‑line errors, break very large batches, and avoid resubmitting the same batch creation request.
- **Caching**: implicit caching requires a minimum input token count; for Gemini 2.5 Flash the minimum is 1024 tokens.

## Current Workflow
- Interactive `generateContent` calls per asset (image + prompt) with a local worker pool.
- A DB query excludes already‑tagged assets.
- Logs per batch include rate + ETA.

## Comparison / Gaps
- **Batch API** could be better for full‑library tagging jobs (cost + throughput), but has a 24‑hour SLO and more setup.
- **Caching** likely provides little benefit here because the prompt is short and does not hit the 1024‑token minimum.
- **Rate‑limit awareness** could be improved by tuning concurrency to project RPM/TPM.

## Plan (If We Want to Change)
1) **Confirm tier + limits** in AI Studio for the project (RPM/TPM/RPD).
2) **Pick mode**:
   - If we need same‑day results and UI progress, keep interactive.
   - If we can accept async completion, switch to Batch API.
3) **Interactive upgrades**:
   - Add a rate‑limited queue (token‑bucket by RPM/TPM).
   - Keep single‑worker as fallback when stalling.
   - Persist failures so the system doesn’t retry known‑bad assets.
4) **Batch API path**:
   - Build a batch input file with one request per asset.
   - Submit a batch job; poll `batchStats` and parse per‑line errors.
   - Store results to DB once batch completes.
5) **UX**:
   - Display rate, remaining, ETA, and error samples.
   - Warn when nearing daily request quota if applicable.

## Current Run Notes
- Single‑worker mode is the most stable but slowest.
- The tagging runner avoids re‑tagging by excluding assets already in `asset_ai` for provider/model.

## Status (2026-02-05)
- Implemented `tools/tagging_batch.py` to use Gemini Batch API with JSONL file input.
- A small validation batch is running to confirm end‑to‑end upload → batch → download → ingest flow.
- Pending validation success, the next step is to submit the full Pinterest backlog via Batch API.
- Full backlog batch has now been submitted; awaiting completion to ingest results.
- Added `tools/tagging_pipeline.py` to preflight, estimate time/cost, and auto‑choose batch vs interactive.
- App grid now renders AI summaries + tag buckets (compact by default, expand on click).
