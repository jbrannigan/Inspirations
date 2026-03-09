#!/bin/zsh
set -euo pipefail

ROOT="/Users/minime/Projects/Inspirations"
cd "$ROOT"

TRACK_RUN_ID="${1:-9a308297-d1f1-4509-b29c-d071e2f2d66d}"
CHUNK_SIZE="${2:-50}"
OUTDIR="$ROOT/data/exports/classification_review_checkpoint_20260307"
LOGDIR="$OUTDIR/logs"
mkdir -p "$LOGDIR"
SOURCE_FILTER="${SOURCE_FILTER:-pinterest,facebook}"
TIMEOUT_S="${TIMEOUT_S:-8}"
PROGRESS_EVERY="${PROGRESS_EVERY:-1}"
MAX_CHUNKS="${MAX_CHUNKS:-0}"
START_OFFSET="${START_OFFSET:-0}"

STAMP="$(date +%Y%m%d_%H%M%S)"
LOGFILE="$LOGDIR/source_link_browser_qc_background_${STAMP}.log"
STATUSFILE="$LOGDIR/source_link_browser_qc_status_latest.json"
STATUSHTML="$LOGDIR/source_link_browser_qc_status_latest.html"

now_iso() {
  date +"%Y-%m-%dT%H:%M:%S%z"
}

status_json() {
  local phase="$1"
  local chunk="$2"
  local start_index="$3"
  local end_index="$4"
  local total="$5"
  local note="$6"
  cat <<EOF
{"updated_at":"$(now_iso)","phase":"$phase","track_run_id":"$TRACK_RUN_ID","chunk":"$chunk","start_index":"$start_index","end_index":"$end_index","total":"$total","note":"$note","log_file":"$LOGFILE"}
EOF
}

render_status_html() {
  python3 tools/render_source_link_qc_status.py \
    --status "$STATUSFILE" \
    --out "$STATUSHTML" \
    --db "$ROOT/data/inspirations.sqlite" \
    --tail-lines 80 >/dev/null 2>&1 || true
}

TOTAL=$(TRACK_RUN_ID="$TRACK_RUN_ID" SOURCE_FILTER="$SOURCE_FILTER" python3 - <<'PY'
import sqlite3
import os
run_id = os.environ["TRACK_RUN_ID"]
sources = [item.strip().lower() for item in os.environ.get("SOURCE_FILTER", "").split(",") if item.strip()]
placeholders = ",".join(["?"] * len(sources))
conn = sqlite3.connect("data/inspirations.sqlite")
value = conn.execute(
    f"""
    select count(*)
    from assets a
    join asset_track_assessments ata on ata.asset_id = a.id
    where ata.run_id = ?
      and lower(a.source) in ({placeholders})
      and (coalesce(a.source_url, '') like 'http%' or coalesce(a.source_ref, '') like 'http%')
    """,
    (run_id, *sources),
).fetchone()[0]
print(int(value or 0))
PY
)

TOTAL="${TOTAL//$'\n'/}"

{
  echo "[$(now_iso)] starting browser wrapper source-link enrichment pass"
  echo "track_run_id=$TRACK_RUN_ID"
  echo "chunk_size=$CHUNK_SIZE"
  echo "source_filter=$SOURCE_FILTER"
  echo "total_candidates=$TOTAL"
} >> "$LOGFILE"

status_json "starting" "0" "0" "0" "$TOTAL" "initializing" > "$STATUSFILE"
render_status_html

OFFSET="$START_OFFSET"
CHUNK=$((OFFSET / CHUNK_SIZE))
PROCESSED_CHUNKS=0
while [ "$OFFSET" -lt "$TOTAL" ]; do
  if [ "$MAX_CHUNKS" -gt 0 ] && [ "$PROCESSED_CHUNKS" -ge "$MAX_CHUNKS" ]; then
    echo "[$(now_iso)] stopping early after $PROCESSED_CHUNKS chunks because MAX_CHUNKS=$MAX_CHUNKS" >> "$LOGFILE"
    break
  fi
  CHUNK=$((CHUNK + 1))
  PROCESSED_CHUNKS=$((PROCESSED_CHUNKS + 1))
  START_INDEX=$((OFFSET + 1))
  END_INDEX=$((OFFSET + CHUNK_SIZE))
  if [ "$END_INDEX" -gt "$TOTAL" ]; then
    END_INDEX="$TOTAL"
  fi

  echo "[$(now_iso)] chunk $CHUNK start items $START_INDEX-$END_INDEX of $TOTAL (offset=$OFFSET)" >> "$LOGFILE"
  status_json "enrichment" "$CHUNK" "$START_INDEX" "$END_INDEX" "$TOTAL" "running enrichment chunk" > "$STATUSFILE"
  render_status_html

  PYTHONPATH=src python3 -m inspirations curation enrich-source-links-v2 \
    --track-run-id "$TRACK_RUN_ID" \
    --source "$SOURCE_FILTER" \
    --include-platform-hosts \
    --browser-platform-hosts \
    --timeout-s "$TIMEOUT_S" \
    --limit "$CHUNK_SIZE" \
    --offset "$OFFSET" \
    --progress-every "$PROGRESS_EVERY" \
    --notes "browser wrapper source-link enrichment chunk $CHUNK ($START_INDEX-$END_INDEX of $TOTAL)" \
    >> "$LOGFILE" 2>&1

  echo "[$(now_iso)] chunk $CHUNK complete items $START_INDEX-$END_INDEX of $TOTAL" >> "$LOGFILE"
  status_json "enrichment" "$CHUNK" "$START_INDEX" "$END_INDEX" "$TOTAL" "chunk complete" > "$STATUSFILE"
  render_status_html
  OFFSET=$((OFFSET + CHUNK_SIZE))
done

echo "[$(now_iso)] browser wrapper enrichment complete" >> "$LOGFILE"
status_json "enrichment_complete" "$CHUNK" "$TOTAL" "$TOTAL" "$TOTAL" "browser wrapper enrichment complete" > "$STATUSFILE"
render_status_html

status_json "qc" "$CHUNK" "$TOTAL" "$TOTAL" "$TOTAL" "running source-link QC" > "$STATUSFILE"
render_status_html
PYTHONPATH=src python3 -m inspirations curation source-link-qc-v2 \
  --track-run-id "$TRACK_RUN_ID" \
  --notes "source-link QC after browser wrapper enrichment" \
  >> "$LOGFILE" 2>&1

echo "[$(now_iso)] source-link QC complete" >> "$LOGFILE"
status_json "qc_complete" "$CHUNK" "$TOTAL" "$TOTAL" "$TOTAL" "source-link QC complete" > "$STATUSFILE"
render_status_html

status_json "export" "$CHUNK" "$TOTAL" "$TOTAL" "$TOTAL" "rendering review export" > "$STATUSFILE"
render_status_html
python3 tools/export_classification_review.py \
  --db data/inspirations.sqlite \
  --outdir "$OUTDIR" \
  >> "$LOGFILE" 2>&1

echo "[$(now_iso)] review export complete" >> "$LOGFILE"
status_json "complete" "$CHUNK" "$TOTAL" "$TOTAL" "$TOTAL" "done" > "$STATUSFILE"
render_status_html

echo "$LOGFILE"
