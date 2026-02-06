# Tagging Pipeline

This doc describes the end‑to‑end tagging pipeline, including **preflight checks**, **repair steps**, **time/cost estimates**, and **auto‑selection** of batch vs interactive tagging.

## Overview
The tagging pipeline is designed to:
- Validate that assets are taggable **before** sending anything to Gemini.
- Repair missing originals/thumbnails when possible.
- Estimate runtime and (optionally) cost.
- Choose the appropriate workflow based on volume.
- Automatically retry `RECITATION`-blocked responses on a fallback model.

Primary entry point:
```bash
GEMINI_API_KEY="YOUR_KEY" PYTHONPATH=src \
python3 tools/tagging_pipeline.py --mode auto
```

## Preflight Checks
Preflight scans candidates and counts:
- `missing_path`: no stored path / thumb path
- `missing_file`: path is set but file is missing
- `unsupported`: file extension not supported by the tagger

By default, preflight runs **before** tagging and can record failures into `asset_ai_errors`.

## Repair Steps
When enabled (default), the pipeline:
1. Downloads missing originals (`download_and_attach_originals`)
2. Generates missing thumbnails (`generate_thumbnails`)

You can disable with:
```bash
--no-repair-missing
```

## Time & Cost Estimates
The pipeline estimates interactive vs batch time using simple RPS constants:

Defaults:
- Interactive: `0.7 rps`
- Batch: `15 rps` + `60s` overhead
- Auto batch cutoff: `>= 500` candidates

Override estimates:
```bash
--est-interactive-rps 1.0 \
--est-batch-rps 20.0 \
--est-batch-overhead-s 30 \
--min-batch 300
```

Cost estimation options:
1) **Per‑asset cost**
```bash
--est-cost-per-asset 0.0015
```

2) **Token‑based cost**
```bash
--est-input-tokens 350 --est-output-tokens 300 \
--cost-per-1k-input 0.00035 --cost-per-1k-output 0.0012
```

Use `--estimate-only` to skip tagging:
```bash
python3 tools/tagging_pipeline.py --estimate-only
```

## Auto vs Manual Modes
```bash
--mode auto         # choose batch or interactive based on volume
--mode batch        # always batch
--mode interactive  # always interactive
```

## Recitation Fallback
Interactive tagging retries when the primary model returns `finishReason=RECITATION` with no JSON:
- Primary default: `gemini-2.5-flash`
- Fallback default: `gemini-2.0-flash`

Override or disable:
```bash
--recitation-fallback-model gemini-2.0-flash
--recitation-fallback-model ""
```

Environment override:
```bash
TAG_RECITATION_FALLBACK_MODEL=gemini-2.0-flash
```

## Batch Workflow
Batch uses `tools/tagging_batch.py` and JSONL file inputs.
It:
- Uploads JSONL file
- Submits batch
- Polls until complete
- Downloads output
- Ingests results

Manual batch run:
```bash
GEMINI_API_KEY="YOUR_KEY" PYTHONPATH=src \
python3 tools/tagging_batch.py run
```

## Interactive Workflow
Interactive uses `tools/tagging_runner.py` with a worker pool.
```bash
GEMINI_API_KEY="YOUR_KEY" PYTHONPATH=src \
python3 tools/tagging_runner.py
```

## Error Recording
Failures are stored in `asset_ai_errors`:
- Preflight errors (missing files, unsupported types)
- Batch ingest failures (no JSON, missing response)
- Interactive runner failures

This supports retries without re‑tagging the rest.

Candidate selection skips assets already tagged by Gemini provider (any model), so fallback-tagged assets are not reprocessed repeatedly.

## CLI Integration
The CLI now preflights by default:
```bash
PYTHONPATH=src python3 -m inspirations ai tag --provider gemini
```

Disable preflight (not recommended):
```bash
PYTHONPATH=src python3 -m inspirations ai tag --provider gemini --no-preflight
```

## Notes
- `.webp` thumbnails: if `sips` fails, Pillow is used when available.
- If you want `sips` only, remove Pillow or disable fallback logic in `src/inspirations/thumbnails.py`.

## UI Integration
The app grid renders `asset_ai` data:
- Compact cards by default
- Click to expand full tag buckets
- Annotate via the existing modal (notes + badges)
