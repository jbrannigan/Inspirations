#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
LABEL="com.jimbrannigan.inspirations"
PLIST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
LOG_DIR="${ROOT_DIR}/data/logs"
OUT_LOG="${LOG_DIR}/inspirations-8001.out.log"
ERR_LOG="${LOG_DIR}/inspirations-8001.err.log"
PORT="${INSPIRATIONS_REVIEW_PORT:-8001}"
HOST="${INSPIRATIONS_REVIEW_HOST:-0.0.0.0}"
UID_NUM="$(id -u)"
DOMAIN="gui/${UID_NUM}"

function usage() {
  cat <<EOF
Usage: $0 install|status|logs|restart|stop|uninstall

Manages the launchd-backed Inspirations service on ${HOST}:${PORT}.
Logs:
  ${OUT_LOG}
  ${ERR_LOG}
EOF
}

function launchctl_print() {
  launchctl print "${DOMAIN}/${LABEL}" 2>&1 || true
}

function listener_pid() {
  lsof -nP -tiTCP:"${PORT}" -sTCP:LISTEN 2>/dev/null | head -n 1 || true
}

function stop_existing_project_listener() {
  local pid
  pid="$(listener_pid)"
  [[ -n "${pid}" ]] || return 0

  local cmd
  cmd="$(ps -p "${pid}" -o command= 2>/dev/null || true)"
  if [[ "${cmd}" == *"${ROOT_DIR}"* || "${cmd}" == *" -m inspirations "* || "${cmd}" == *"run_review_server.sh"* ]]; then
    echo "[service] stopping existing Inspirations listener pid=${pid}"
    kill -TERM "${pid}" 2>/dev/null || true
    for _ in {1..30}; do
      sleep 0.2
      [[ -z "$(listener_pid)" ]] && return 0
    done
    echo "[service] existing listener did not stop; refusing to force-kill automatically" >&2
    return 1
  fi

  echo "[service] port ${PORT} is in use by a process that does not clearly belong to this repo:" >&2
  echo "  pid=${pid}" >&2
  echo "  ${cmd}" >&2
  return 1
}

function write_plist() {
  mkdir -p "${HOME}/Library/LaunchAgents" "${LOG_DIR}"
  cat > "${PLIST}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${ROOT_DIR}/tools/run_review_server.sh</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${ROOT_DIR}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>INSPIRATIONS_REVIEW_HOST</key>
    <string>${HOST}</string>
    <key>INSPIRATIONS_REVIEW_PORT</key>
    <string>${PORT}</string>
    <key>PYTHONUNBUFFERED</key>
    <string>1</string>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>ThrottleInterval</key>
  <integer>10</integer>
  <key>StandardOutPath</key>
  <string>${OUT_LOG}</string>
  <key>StandardErrorPath</key>
  <string>${ERR_LOG}</string>
  <key>ProcessType</key>
  <string>Background</string>
</dict>
</plist>
EOF
}

function install_service() {
  chmod +x "${ROOT_DIR}/tools/run_review_server.sh"
  write_plist
  launchctl bootout "${DOMAIN}/${LABEL}" 2>/dev/null || true
  stop_existing_project_listener
  echo "[service] installing ${PLIST}"
  launchctl bootstrap "${DOMAIN}" "${PLIST}"
  launchctl enable "${DOMAIN}/${LABEL}" 2>/dev/null || true
  launchctl kickstart -k "${DOMAIN}/${LABEL}"
  sleep 2
  status_service
}

function stop_service() {
  launchctl bootout "${DOMAIN}/${LABEL}" 2>/dev/null || true
}

function restart_service() {
  launchctl kickstart -k "${DOMAIN}/${LABEL}"
  sleep 2
  status_service
}

function status_service() {
  echo "== launchd =="
  launchctl_print | sed -n '1,90p'
  echo
  echo "== listener :${PORT} =="
  lsof -nP -iTCP:"${PORT}" -sTCP:LISTEN || true
  echo
  echo "== health =="
  curl -fsS "http://127.0.0.1:${PORT}/api/assets?limit=1" >/dev/null \
    && echo "api: ok" \
    || echo "api: failed"
  echo
  echo "== recent stderr =="
  tail -n 40 "${ERR_LOG}" 2>/dev/null || true
  echo
  echo "== recent stdout =="
  tail -n 40 "${OUT_LOG}" 2>/dev/null || true
}

function logs_service() {
  echo "== ${ERR_LOG} =="
  tail -n 80 "${ERR_LOG}" 2>/dev/null || true
  echo
  echo "== ${OUT_LOG} =="
  tail -n 120 "${OUT_LOG}" 2>/dev/null || true
}

function uninstall_service() {
  stop_service
  rm -f "${PLIST}"
  echo "[service] removed ${PLIST}"
}

case "${1:-}" in
  install) install_service ;;
  status) status_service ;;
  logs) logs_service ;;
  restart) restart_service ;;
  stop) stop_service ;;
  uninstall) uninstall_service ;;
  *) usage; exit 2 ;;
esac
