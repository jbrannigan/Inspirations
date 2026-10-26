#!/bin/zsh
set -euo pipefail

ACTION="${1:-}"
MODE="${2:-login}"

# In zsh $0 inside a function is the function name, so capture the script path
# here, at top level, for usage text and the sudo re-exec.
PROG="$0"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
LABEL="com.jimbrannigan.inspirations"
LOG_DIR="${ROOT_DIR}/data/logs"
OUT_LOG="${LOG_DIR}/inspirations-8001.out.log"
ERR_LOG="${LOG_DIR}/inspirations-8001.err.log"
PORT="${INSPIRATIONS_REVIEW_PORT:-8001}"
HOST="${INSPIRATIONS_REVIEW_HOST:-0.0.0.0}"

function usage() {
  cat <<EOF
Usage: ${PROG} install|status|logs|restart|stop|uninstall [login|boot]

Manages the launchd-backed Inspirations service on ${HOST}:${PORT}.

Modes:
  login  LaunchAgent in ~/Library/LaunchAgents, domain gui/<uid> (default).
         Starts at console login. Can read the login keychain.
  boot   LaunchDaemon in /Library/LaunchDaemons, domain system; re-execs via
         sudo. Starts at boot with no login required, which is what the public
         hostname needs. Runs as UserName below, but CANNOT read the login
         keychain — API keys must be in ${ROOT_DIR}/.env.production (mode 0600).

Logs:
  ${OUT_LOG}
  ${ERR_LOG}
EOF
}

case "${ACTION}" in
  install|status|logs|restart|stop|uninstall) ;;
  *) usage; exit 2 ;;
esac

if [[ "${MODE}" != "login" && "${MODE}" != "boot" ]]; then
  usage
  exit 2
fi

# Boot mode touches /Library/LaunchDaemons and the system domain.
if [[ "${MODE}" == "boot" && "${EUID}" -ne 0 ]]; then
  exec sudo "${PROG}" "${ACTION}" "${MODE}"
fi

if [[ "${MODE}" == "boot" ]]; then
  TARGET_USER="${SUDO_USER:-$(logname)}"
  DOMAIN="system"
  PLIST_DIR="/Library/LaunchDaemons"
else
  TARGET_USER="${USER}"
  DOMAIN="gui/$(id -u "${TARGET_USER}")"
  PLIST_DIR="${HOME}/Library/LaunchAgents"
fi
PLIST="${PLIST_DIR}/${LABEL}.plist"

function launchctl_print() {
  launchctl print "${DOMAIN}/${LABEL}" 2>&1 || true
}

function listener_pid() {
  lsof -nP -tiTCP:"${PORT}" -sTCP:LISTEN 2>/dev/null | head -n 1 || true
}

function warn_other_mode_installed() {
  # Both a LaunchAgent and a LaunchDaemon on the same port would fight over it.
  local other
  if [[ "${MODE}" == "boot" ]]; then
    other="$(eval echo ~"${TARGET_USER}")/Library/LaunchAgents/${LABEL}.plist"
  else
    other="/Library/LaunchDaemons/${LABEL}.plist"
  fi
  if [[ -f "${other}" ]]; then
    echo "[service] WARNING: the other mode is still installed at:" >&2
    echo "  ${other}" >&2
    echo "[service] both would contend for port ${PORT}; uninstall that mode first." >&2
  fi
}

function check_secrets_for_boot() {
  [[ "${MODE}" == "boot" ]] || return 0
  local env_file="${ROOT_DIR}/.env.production"
  if [[ ! -f "${env_file}" ]]; then
    echo "[service] WARNING: ${env_file} is missing." >&2
    echo "[service] A daemon cannot read the login keychain, so AI features will" >&2
    echo "[service] start with no API keys." >&2
    return 0
  fi
  if ! grep -qE '^GEMINI_API_KEY=.+' "${env_file}" || ! grep -qE '^ANTHROPIC_API_KEY=.+' "${env_file}"; then
    echo "[service] WARNING: ${env_file} has an empty GEMINI_API_KEY or" >&2
    echo "[service] ANTHROPIC_API_KEY. A daemon cannot fall back to the login" >&2
    echo "[service] keychain, so AI features will start with no API keys." >&2
  fi
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
  mkdir -p "${PLIST_DIR}" "${LOG_DIR}"
  if [[ "${MODE}" == "boot" ]]; then
    chown "${TARGET_USER}" "${LOG_DIR}" 2>/dev/null || true
  fi

  local user_key=""
  if [[ "${MODE}" == "boot" ]]; then
    user_key="  <key>UserName</key>
  <string>${TARGET_USER}</string>
"
  fi

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
${user_key}  <key>RunAtLoad</key>
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
  plutil -lint "${PLIST}" >/dev/null
}

function install_service() {
  chmod +x "${ROOT_DIR}/tools/run_review_server.sh"
  check_secrets_for_boot
  warn_other_mode_installed
  write_plist
  launchctl bootout "${DOMAIN}/${LABEL}" 2>/dev/null || true
  stop_existing_project_listener
  echo "[service] installing ${PLIST} (mode=${MODE})"
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
  echo "== launchd (${DOMAIN}/${LABEL}) =="
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

case "${ACTION}" in
  install) install_service ;;
  status) status_service ;;
  logs) logs_service ;;
  restart) restart_service ;;
  stop) stop_service ;;
  uninstall) uninstall_service ;;
esac
