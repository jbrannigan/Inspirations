#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
PWCLI="$CODEX_HOME/skills/playwright/scripts/playwright_cli.sh"
PROFILE_DIR="${1:-$ROOT_DIR/data/playwright_profiles/media_repair_auth}"
SESSION_NAME="${PLAYWRIGHT_CLI_SESSION:-media-repair-auth}"

if ! command -v npx >/dev/null 2>&1; then
  echo "npx is required but was not found on PATH." >&2
  exit 1
fi

mkdir -p "$PROFILE_DIR"

export PLAYWRIGHT_CLI_SESSION="$SESSION_NAME"

exec "$PWCLI" open about:blank \
  --headed \
  --persistent \
  --browser chrome \
  --profile "$PROFILE_DIR"
