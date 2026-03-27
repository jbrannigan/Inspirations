#!/bin/zsh
set -euo pipefail

ROOT="/Users/minime/Projects/Inspirations"
cd "$ROOT"

TRACK_RUN_ID="${1:-9a308297-d1f1-4509-b29c-d071e2f2d66d}"
OUTDIR="$ROOT/data/exports/classification_review_checkpoint_20260307"
LOGDIR="$OUTDIR/logs"
mkdir -p "$LOGDIR"

STAMP="$(date +%Y%m%d_%H%M%S)"
LOGFILE="$LOGDIR/source_link_qc_background_${STAMP}.log"
now_iso() {
  date +"%Y-%m-%dT%H:%M:%S%z"
}

{
  echo "[$(now_iso)] starting source-link enrichment background pass"
  echo "track_run_id=$TRACK_RUN_ID"

  PYTHONPATH=src python3 -m inspirations curation enrich-source-links-v2 \
    --track-run-id "$TRACK_RUN_ID" \
    --promote-best-source-url \
    --timeout-s 3 \
    --max-redirects 2 \
    --notes "full source-link enrichment with source_url promotion across latest track run (fast timeout background pass)"

  echo "[$(now_iso)] source-link enrichment complete"

  PYTHONPATH=src python3 -m inspirations curation source-link-qc-v2 \
    --track-run-id "$TRACK_RUN_ID" \
    --notes "full source-link QC background pass after enrichment"

  echo "[$(now_iso)] source-link QC complete"

  python3 tools/export_classification_review.py \
    --db data/inspirations.sqlite \
    --outdir "$OUTDIR"

  echo "[$(now_iso)] review export complete"
} >> "$LOGFILE" 2>&1

echo "$LOGFILE"
