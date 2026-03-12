#!/bin/zsh
set -euo pipefail

PORT="${1:-8001}"
URL="http://127.0.0.1:${PORT}/api/me"

if lsof -iTCP:${PORT} -sTCP:LISTEN -n -P >/dev/null 2>&1; then
  echo "LISTENING ${PORT}"
  lsof -iTCP:${PORT} -sTCP:LISTEN -n -P
else
  echo "NOT_LISTENING ${PORT}"
fi

echo "---"
HTTP_CODE="$(curl -s -o /tmp/inspirations_review_server_check.json -w '%{http_code}' "${URL}" || true)"
echo "HTTP ${HTTP_CODE} ${URL}"
cat /tmp/inspirations_review_server_check.json 2>/dev/null || true
printf '\n'
