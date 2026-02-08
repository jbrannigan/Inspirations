# AI Tagging Plan (Gemini Image)

This plan covers Gemini-based image tagging to improve search, faceting, and summaries across Pinterest/Facebook/scans.

## Output schema (stored per asset)
The Gemini prompt requests JSON with:
- `summary`: short description for search + preview text
- `image_type`: interior | exterior | product | plan | document | other
- `rooms`, `elements`, `materials`, `colors`, `styles`, `lighting`, `fixtures`, `appliances`
- `text_in_image`: OCR-like text snippets found in the image
- `brands_products`: any visible brand/product names
- `tags`: extra keywords that don’t fit other buckets

## Storage
- `assets.ai_summary` (for quick search + preview)
- `asset_ai` table for full JSON payloads
- `asset_labels` for normalized labels that power facets and search filters
- `asset_ai_errors` for failed assets + retry analysis

## CLI usage
Set your Gemini API key:

```sh
export GEMINI_API_KEY="YOUR_KEY"
```

Run tagging (thumbnails are cheaper/faster; originals are more accurate):

```sh
PYTHONPATH=src python3 -m inspirations ai tag --provider gemini --image-kind thumb
PYTHONPATH=src python3 -m inspirations ai tag --provider gemini --image-kind original --source pinterest
```

Preflight checks (default on; downloads missing originals + generates thumbs):

```sh
PYTHONPATH=src python3 -m inspirations ai tag --provider gemini --preflight
PYTHONPATH=src python3 -m inspirations ai tag --provider gemini --no-preflight
```

Batch pipeline (recommended for large volumes):

```sh
GEMINI_API_KEY="YOUR_KEY" PYTHONPATH=src \
python3 tools/tagging_pipeline.py --mode auto
```

Re-run tagging (force):

```sh
PYTHONPATH=src python3 -m inspirations ai tag --provider gemini --force
```

## Notes
- Start with thumbnails to validate quality and cost, then re-run on originals if needed.
- Tagging is idempotent unless `--force` is used.
- Batch ingest logs failures in `asset_ai_errors` to avoid silent loss.

## References
- https://ai.google.dev/gemini-api/docs/vision
- https://ai.google.dev/gemini-api/docs/system-instructions?lang=rest
