#!/bin/zsh
set -euo pipefail

PORT="${1:-8001}"
TRIES="${REVIEW_SERVER_CHECK_TRIES:-3}"
SLEEP_SECONDS="${REVIEW_SERVER_CHECK_SLEEP_SECONDS:-2}"
ROOT_URL="http://127.0.0.1:${PORT}/"
API_URL="http://127.0.0.1:${PORT}/api/me"

for ATTEMPT in $(seq 1 "${TRIES}"); do
  echo "ATTEMPT ${ATTEMPT}/${TRIES}"
  if lsof -iTCP:${PORT} -sTCP:LISTEN -n -P >/dev/null 2>&1; then
    echo "LISTENING ${PORT}"
    lsof -iTCP:${PORT} -sTCP:LISTEN -n -P
  else
    echo "NOT_LISTENING ${PORT}"
  fi

  echo "--- ROOT ---"
  ROOT_HTTP_CODE="$(curl -s -o /tmp/inspirations_review_root_check.html -w '%{http_code}' "${ROOT_URL}" || true)"
  echo "HTTP ${ROOT_HTTP_CODE} ${ROOT_URL}"
  head -c 160 /tmp/inspirations_review_root_check.html 2>/dev/null || true
  printf '\n'

  echo "--- API ---"
  API_HTTP_CODE="$(curl -s -o /tmp/inspirations_review_server_check.json -w '%{http_code}' "${API_URL}" || true)"
  echo "HTTP ${API_HTTP_CODE} ${API_URL}"
  cat /tmp/inspirations_review_server_check.json 2>/dev/null || true
  printf '\n'

  if [[ "${ATTEMPT}" != "${TRIES}" ]]; then
    echo "--- sleeping ${SLEEP_SECONDS}s ---"
    sleep "${SLEEP_SECONDS}"
  fi
done
