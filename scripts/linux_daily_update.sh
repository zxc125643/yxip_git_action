#!/usr/bin/env bash
set -Eeuo pipefail

# Unified daily job for the Linux machine:
# 1. Pull the GitHub IP list.
# 2. Test Cloudflare IPs from the local network.
# 3. Select the best PROXYIP/PROXYIP_LIST for the Worker.
# 4. Optionally deploy the Worker and refresh the SOCKS5 secret.

REPO_DIR="${REPO_DIR:-$HOME/yxip_git_action_trace}"
EDGAR_DIR="${EDGAR_DIR:-$HOME/projects/edgar3.0}"
TRACE_HOST="${TRACE_HOST:-edgar.vegaavc.cn}"
TRACE_INPUT="${TRACE_INPUT:-ip_clean.txt}"
TRACE_WORKERS="${TRACE_WORKERS:-16}"
TRACE_TIMEOUT="${TRACE_TIMEOUT:-8}"
TOP_N="${TOP_N:-5}"
MIN_PURITY="${MIN_PURITY:-80}"
DEPLOY_WORKER="${DEPLOY_WORKER:-true}"
RUN_SOCKS5="${RUN_SOCKS5:-true}"
PUSH_TRACE="${PUSH_TRACE:-false}"
PULL_REPO="${PULL_REPO:-true}"
GIT_REMOTE="${GIT_REMOTE:-origin}"
GIT_BRANCH="${GIT_BRANCH:-main}"

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

is_true() {
  case "${1:-}" in
    true|TRUE|1|yes|YES|y|Y) return 0 ;;
    *) return 1 ;;
  esac
}

unset_proxy_env() {
  unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY
}

log "Entering repo: $REPO_DIR"
cd "$REPO_DIR"

if is_true "$PULL_REPO" && [ -d .git ]; then
  log "Pulling latest GitHub results"
  git pull --ff-only "$GIT_REMOTE" "$GIT_BRANCH"
else
  log "Skipping repo pull because PULL_REPO=$PULL_REPO"
fi

if [ ! -f "$TRACE_INPUT" ]; then
  log "Trace input $TRACE_INPUT not found; falling back to ip.txt"
  TRACE_INPUT="ip.txt"
fi

log "Running local Cloudflare trace for $TRACE_HOST using $TRACE_INPUT"
python3 scripts/local_cf_trace.py \
  --host "$TRACE_HOST" \
  --input "$TRACE_INPUT" \
  --workers "$TRACE_WORKERS" \
  --timeout "$TRACE_TIMEOUT"

log "Selecting best PROXYIP values"
python3 scripts/select_trace_ips.py \
  --input ip_trace.csv \
  --count "$TOP_N" \
  --min-purity "$MIN_PURITY" \
  --env-output cf_proxyip.env \
  --list-output cf_proxyip_list.txt

# shellcheck disable=SC1091
. ./cf_proxyip.env
log "Selected PROXYIP=$PROXYIP"
log "Selected PROXYIP_LIST=$PROXYIP_LIST"

if is_true "$DEPLOY_WORKER"; then
  log "Deploying Worker with selected Cloudflare IPs"
  cd "$EDGAR_DIR"
  unset_proxy_env
  npx wrangler deploy \
    --var "PROXYIP:$PROXYIP" \
    --var "PROXY_FALLBACK:true" \
    --var "PROXYIP_LIST:$PROXYIP_LIST"
  cd "$REPO_DIR"
else
  log "Skipping Worker deploy because DEPLOY_WORKER=$DEPLOY_WORKER"
fi

if is_true "$RUN_SOCKS5"; then
  log "Refreshing Worker SOCKS5 secret via existing manage.py"
  cd "$EDGAR_DIR"
  if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    . ./.env
    set +a
  fi
  python3 manage.py run
  cd "$REPO_DIR"
else
  log "Skipping SOCKS5 refresh because RUN_SOCKS5=$RUN_SOCKS5"
fi

if is_true "$PUSH_TRACE" && [ -d "$REPO_DIR/.git" ]; then
  log "Pushing local trace outputs to GitHub"
  cd "$REPO_DIR"
  git add ip_trace.csv ip_traced.txt cf_proxyip.env cf_proxyip_list.txt
  if git diff --cached --quiet; then
    log "No trace changes to commit"
  else
    git commit -m "Update local trace results"
    git push "$GIT_REMOTE" "HEAD:$GIT_BRANCH"
  fi
else
  log "Skipping GitHub push because PUSH_TRACE=$PUSH_TRACE"
fi

log "Daily network update completed"
