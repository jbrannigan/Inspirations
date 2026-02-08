# Project Status (Resume Here)

## Current status (Feb 5, 2026)
- Gemini Batch tagging completed; `asset_ai(gemini-2.5-flash)=3585`, remaining Pinterest: `76`.
- Preflight + auto mode pipeline added (`tools/tagging_pipeline.py`).
- Error capture table added (`asset_ai_errors`) for failed assets.
- App grid now renders AI summaries + full tag buckets; compact by default, expand on click, annotate via modal.

## Where to look
- `docs/AI_TAGGING_PLAN.md` — Gemini tagging workflow and CLI usage
- `docs/SEARCH_STRATEGY.md` — hybrid search + embeddings + knowledge graph plan
- `docs/ARCHITECTURE.md` — end‑to‑end pipeline and options
- `docs/tagging_pipeline.md` — preflight + estimates + auto mode
- `docs/next_steps.md` — quick resume checklist after restart

## Gemini tagging commands
Set key:
```sh
export GEMINI_API_KEY="YOUR_KEY"
```

Tag from thumbnails (faster/cheaper):
```sh
PYTHONPATH=src python3 -m inspirations ai tag --provider gemini --image-kind thumb
```

Tag from originals (higher fidelity):
```sh
PYTHONPATH=src python3 -m inspirations ai tag --provider gemini --image-kind original
```

Force re‑tag:
```sh
PYTHONPATH=src python3 -m inspirations ai tag --provider gemini --force
```

## Next steps (suggested)
1. Retry remaining 76 assets (batch or interactive fallback).
2. Review tag quality in the new compact/expand grid.
3. Decide whether to re‑run on originals for better accuracy.
4. (Optional) Add embeddings + similarity search once tagging is good.
