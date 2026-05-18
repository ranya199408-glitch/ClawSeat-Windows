#!/usr/bin/env bash
set -euo pipefail

brief="${CLAWSEAT_MEMORY_BRIEF:-${CLAWSEAT_ANCESTOR_BRIEF:-}}"
if [[ -z "$brief" || ! -f "$brief" ]]; then
  # brief 缺失或不可读，归到别的启动问题，不在这个检查里阻塞。
  exit 0
fi

session_target="${CLAWSEAT_MEMORY_SESSION:-${CLAWSEAT_ANCESTOR_SESSION:-${TMUX_PANE:-}}}"
if [[ -z "$session_target" ]]; then
  exit 0
fi

if ! command -v tmux >/dev/null 2>&1; then
  exit 0
fi

memory_started_unix="$(
  tmux display-message -p -t "$session_target" '#{session_created}' 2>/dev/null || true
)"
brief_mtime_unix=""
if brief_mtime_unix="$(stat -f %m "$brief" 2>/dev/null)"; then
  :
elif brief_mtime_unix="$(stat -c %Y "$brief" 2>/dev/null)"; then
  :
else
  exit 0
fi

if [[ ! "$memory_started_unix" =~ ^[0-9]+$ || ! "$brief_mtime_unix" =~ ^[0-9]+$ ]]; then
  exit 0
fi

if (( brief_mtime_unix > memory_started_unix )); then
  printf 'BRIEF_DRIFT_DETECTED\n'
  printf '  memory_started_unix=%s\n' "$memory_started_unix"
  printf '  brief_mtime_unix=%s\n' "$brief_mtime_unix"
  printf '  brief_path=%s\n' "$brief"
  exit 1
fi

exit 0
