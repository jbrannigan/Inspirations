#!/bin/zsh
set -euo pipefail

ROOT="/Users/minime/Projects/Inspirations"
cd "$ROOT"

STATUSFILE="${1:-$ROOT/data/exports/classification_review_checkpoint_20260307/logs/source_link_browser_qc_status_latest.json}"
OUTFILE="${2:-$ROOT/data/exports/classification_review_checkpoint_20260307/logs/source_link_browser_qc_status_latest.html}"
INTERVAL="${INTERVAL:-10}"

while true; do
  python3 tools/render_source_link_qc_status.py \
    --status "$STATUSFILE" \
    --out "$OUTFILE" \
    --db "$ROOT/data/inspirations.sqlite" \
    --tail-lines 80 >/dev/null 2>&1 || true

  PHASE=$(python3 - <<'PY' "$STATUSFILE"
import json
import sys
from pathlib import Path
path = Path(sys.argv[1])
try:
    obj = json.loads(path.read_text())
except Exception:
    obj = {}
print(str(obj.get("phase") or ""))
PY
)
  PHASE="${PHASE//$'\n'/}"
  if [ "$PHASE" = "complete" ]; then
    break
  fi
  sleep "$INTERVAL"
done
