#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

HOST="${INSPIRATIONS_REVIEW_HOST:-127.0.0.1}"
PORT="${INSPIRATIONS_REVIEW_PORT:-8001}"
DB_PATH="${INSPIRATIONS_REVIEW_DB:-data/inspirations.sqlite}"
STORE_DIR="${INSPIRATIONS_REVIEW_STORE:-store}"

function keychain_read() {
  local service="$1"
  security find-generic-password -a "$USER" -s "$service" -w 2>/dev/null || true
}

cd "${ROOT_DIR}"

# Always prepend this repo's src so imports work even when launched from a
# parent process that sets its own PYTHONPATH (e.g. DevLauncher).
if [[ -n "${PYTHONPATH:-}" ]]; then
  export PYTHONPATH="${ROOT_DIR}/src:${PYTHONPATH}"
else
  export PYTHONPATH="${ROOT_DIR}/src"
fi
export GEMINI_API_KEY="${GEMINI_API_KEY:-$(keychain_read inspirations_gemini_api_key)}"
export ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-$(keychain_read inspirations_anthropic_api_key)}"

echo "[review-server] root=${ROOT_DIR}"
echo "[review-server] python=$(command -v python3)"
echo "[review-server] host=${HOST} port=${PORT}"
echo "[review-server] db=${DB_PATH} store=${STORE_DIR}"
echo "[review-server] gemini_key=$([[ -n \"${GEMINI_API_KEY}\" ]] && echo present || echo missing)"
echo "[review-server] anthropic_key=$([[ -n \"${ANTHROPIC_API_KEY}\" ]] && echo present || echo missing)"

exec python3 -u -m inspirations --db "${DB_PATH}" --store "${STORE_DIR}" serve --host "${HOST}" --port "${PORT}"
