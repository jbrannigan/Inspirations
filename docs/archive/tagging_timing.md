# Tagging Timing Notes

This document captures observed Gemini tagging throughput so we can estimate runtime and size worker pools for future ingest UX.

## Latest Measurement (2026-02-05)
- Provider/model: `gemini / gemini-2.5-flash`
- Source: `pinterest`
- Image kind: `thumb`
- Batch size: `60`
- Workers: `6`
- Start time: `2026-02-05T05:45:48Z`
- Progress log: `/tmp/inspirations_gemini_tag_progress.log`

First batch result (logged):
- `attempted=60` `labeled=51` `errors=9`
- `batch_s=73.3` seconds
- `rate=0.70/s` (about 42 per minute)
- `remaining=3240` `eta~77m`

At `2026-02-05T05:49:28Z`, total Gemini rows in DB:
- `asset_ai(gemini)=421`

## Estimation Heuristics
Given an observed rate `r` (images/sec):
- **ETA seconds** = `remaining / r`
- **ETA minutes** = `ceil(remaining / r / 60)`

If you scale workers, a rough first‑order estimate:
- `r_new ≈ r * (workers_new / workers_old)`
- Expect diminishing returns due to API latency, rate limits, and DB writes.

## UX Suggestions for Future Ingest
- Show live **rate**, **remaining**, and **ETA** in the UI.
- Expose a **worker count** selector with a warning about rate limits.
- Log per‑batch metrics to support accurate predictions.
- Surface error rate and sample errors (e.g., missing images, JSON parse).

## How to Monitor Now
- Tail progress:
  ```bash
  tail -n 20 /tmp/inspirations_gemini_tag_progress.log
  ```
- Check total tagged count:
  ```bash
  sqlite3 /Users/minime/Projects/Inspirations/data/inspirations.sqlite \
    "select count(*) from asset_ai where provider='gemini';"
  ```

## Latest Measurement (2026-02-05, Run 2)
- Script: `tools/tagging_runner.py`
- Start time: `2026-02-05T06:29:17Z`
- Batch size: `60`
- Workers: `6`

Batch 1 result:
- `attempted=60` `labeled=52` `errors=8`
- `batch_s=75.2` seconds
- `rate=0.69/s`
- `remaining=3188` `eta~76m`

## Latest Measurement (2026-02-05, Run 3)
- Script: `tools/tagging_runner.py`
- Start time: `2026-02-05T06:54:08Z`
- Batch size: `60`
- Workers: `4`
- Timeouts: `req=60s`, `batch=240s`

Batch 1 result:
- `attempted=60` `labeled=52` `errors=8`
- `batch_s=102.3` seconds
- `rate=0.51/s`
- `remaining=3136` `eta~102m`

## Latest Measurement (2026-02-05, Run 4)
- Script: `tools/tagging_runner.py`
- Start time: `2026-02-05T06:59:19Z`
- Batch size: `20`
- Workers: `1`
- Timeouts: `req=60s`, `batch=1200s`

Batch 1 result:
- `attempted=20` `labeled=12` `errors=8`
- `batch_s=145.6` seconds
- `rate=0.08/s`
- `remaining=3124` `eta~631m`

## Batch API Submission (2026-02-05)
Switch to Gemini Batch API using `tools/tagging_batch.py`.

- Batch name: `batches/6moh82ogzaks688e0wqi2xwzu9opios54h2v`
- Request count: `3121` (3 skipped due to missing/unsupported images)
- Input JSONL size: `293,593,768` bytes (~293 MB)
- Build + upload window:
  - Build started: `2026-02-05T07:34:27Z`
  - Batch submitted: `2026-02-05T07:36:26Z`
  - Build + upload elapsed: ~`2m`

Batch completion:
- Batch create time: `2026-02-05T07:36:13Z`
- Batch end time: `2026-02-05T07:39:09Z`
- Batch runtime: ~`2m56s`

Ingest result:
- Ingested at: `2026-02-05T18:31:28Z`
- Labeled: `3048`
- Errors: `73` (mostly “No JSON object in response”)
