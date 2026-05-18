#!/usr/bin/env bash
set -euo pipefail

REPO="${CLAWSEAT_UPDATE_REPO:-${HOME}/ClawSeat}"
LOG="${CLAWSEAT_AUTO_UPDATE_LOG:-${HOME}/.clawseat/auto-update.log}"

timestamp() {
  date -u +%Y-%m-%dT%H:%M:%SZ
}

log() {
  mkdir -p "$(dirname "$LOG")"
  printf '[%s] %s\n' "$(timestamp)" "$*" >> "$LOG"
}

cd "$REPO" 2>/dev/null || {
  log "skip: $REPO not found"
  exit 0
}

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  log "skip: $REPO is not a git worktree"
  exit 0
fi

current="$(git symbolic-ref --short HEAD 2>/dev/null || printf 'DETACHED')"
if [[ "$current" != "main" ]]; then
  log "skip: on $current"
  exit 0
fi

if ! git diff --quiet || ! git diff --cached --quiet; then
  log "skip: dirty tree"
  exit 0
fi

if ! git remote get-url clawseat >/dev/null 2>&1; then
  log "skip: no clawseat remote"
  exit 0
fi

git fetch clawseat main --quiet 2>>"$LOG" || {
  log "fetch failed"
  exit 0
}

local_sha="$(git rev-parse HEAD)"
remote_sha="$(git rev-parse clawseat/main 2>/dev/null || true)"
if [[ -z "$remote_sha" ]]; then
  log "skip: clawseat/main not found"
  exit 0
fi

if [[ "$local_sha" != "$remote_sha" ]]; then
  git reset --hard clawseat/main >>"$LOG" 2>&1
  log "updated $local_sha -> $remote_sha"
else
  log "already at $local_sha"
fi
