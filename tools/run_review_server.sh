#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

HOST="${INSPIRATIONS_REVIEW_HOST:-0.0.0.0}"
PORT="${INSPIRATIONS_REVIEW_PORT:-8001}"
DB_PATH="${INSPIRATIONS_REVIEW_DB:-data/inspirations.sqlite}"
STORE_DIR="${INSPIRATIONS_REVIEW_STORE:-store}"

function keychain_read() {
  local service="$1"
  security find-generic-password -a "$USER" -s "$service" -w 2>/dev/null || true
}

function log_line() {
  printf '[review-server-wrapper %s] %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"
}

cd "${ROOT_DIR}"

# Always prepend this repo's src so imports work even when launched from a
# parent process that sets its own PYTHONPATH (e.g. DevLauncher).
if [[ -n "${PYTHONPATH:-}" ]]; then
  export PYTHONPATH="${ROOT_DIR}/src:${PYTHONPATH}"
else
  export PYTHONPATH="${ROOT_DIR}/src"
fi
# Secrets. Prefer the untracked mode-0600 env file: a boot-time LaunchDaemon
# runs outside the user's security session and cannot read the login keychain,
# so the keychain is only usable when this starts from a logged-in session.
# Already-set environment variables win, then the file, then the keychain.
ENV_FILE="${INSPIRATIONS_ENV_FILE:-${ROOT_DIR}/.env.production}"
if [[ -f "${ENV_FILE}" ]]; then
  perms="$(stat -f '%Lp' "${ENV_FILE}" 2>/dev/null || echo '???')"
  if [[ "${perms}" != "600" ]]; then
    log_line "WARNING: ${ENV_FILE} is mode ${perms}; expected 600"
  fi
  set -a
  source "${ENV_FILE}"
  set +a
fi

export GEMINI_API_KEY="${GEMINI_API_KEY:-$(keychain_read inspirations_gemini_api_key)}"
export ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-$(keychain_read inspirations_anthropic_api_key)}"

echo "[review-server] root=${ROOT_DIR}"
echo "[review-server] python=$(command -v python3)"
echo "[review-server] host=${HOST} port=${PORT}"
echo "[review-server] db=${DB_PATH} store=${STORE_DIR}"
echo "[review-server] gemini_key=$([[ -n \"${GEMINI_API_KEY}\" ]] && echo present || echo missing)"
echo "[review-server] anthropic_key=$([[ -n \"${ANTHROPIC_API_KEY}\" ]] && echo present || echo missing)"

log_line "starting python server"
python3 -u -m inspirations --db "${DB_PATH}" --store "${STORE_DIR}" serve --host "${HOST}" --port "${PORT}" &
child_pid=$!

function stop_child() {
  log_line "received stop signal; forwarding to pid=${child_pid}"
  kill -TERM "${child_pid}" 2>/dev/null || true
  wait "${child_pid}" 2>/dev/null || true
}

trap stop_child TERM INT
wait "${child_pid}"
exit_status=$?
log_line "python server exited status=${exit_status}"
exit "${exit_status}"
