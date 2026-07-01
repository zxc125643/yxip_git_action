#!/usr/bin/env bash
set -Eeuo pipefail

# macOS wrapper for scripts/linux_daily_update.sh.
# Keep the update logic in one place, but provide launchd-friendly defaults.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${REPO_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
CONFIG_FILE="${CONFIG_FILE:-$REPO_DIR/scripts/macos_daily_update.env}"

export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.hermes/node/bin:$HOME/.nvm/current/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
export REPO_DIR

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

is_unset() {
  [ -z "${!1+x}" ]
}

if [ -f "$CONFIG_FILE" ]; then
  log "Loading macOS config: $CONFIG_FILE"
  set -a
  # shellcheck disable=SC1090
  . "$CONFIG_FILE"
  set +a
else
  log "No macOS config found at $CONFIG_FILE; using defaults"
fi

EDGAR_DIR="${EDGAR_DIR:-$HOME/projects/edgar3.0}"
export EDGAR_DIR

if [ ! -d "$EDGAR_DIR" ]; then
  log "Worker directory not found: $EDGAR_DIR"
  if is_unset DEPLOY_WORKER; then
    export DEPLOY_WORKER=false
    log "Defaulting DEPLOY_WORKER=false"
  fi
  if is_unset RUN_SOCKS5; then
    export RUN_SOCKS5=false
    log "Defaulting RUN_SOCKS5=false"
  fi
fi

cd "$REPO_DIR"
exec /bin/bash "$REPO_DIR/scripts/linux_daily_update.sh"
