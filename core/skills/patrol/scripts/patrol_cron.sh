#!/usr/bin/env bash
set -euo pipefail

mode="${1:-}"
[[ "$mode" == "daily" || "$mode" == "weekly" ]] || exit 0

project="${CLAWSEAT_PROJECT:-${AGENTS_PROJECT:-install}}"
CLAWSEAT_ROOT="${CLAWSEAT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)}"
session="${project}-patrol"
log_path="${HOME}/.agents/memory/_patrol.log"
mkdir -p "$(dirname "$log_path")"

check_cross_project_disappear() {
  local project="${1:-install}"
  local snapshot_file="${HOME}/.agents/workspaces/${project}/patrol/session-snapshot.txt"
  local current_sessions previous_sessions session
  local -a disappeared=()

  current_sessions="$(tmux list-sessions -F "#S" 2>/dev/null || true)"
  mkdir -p "$(dirname "$snapshot_file")" 2>/dev/null || true

  if [[ ! -f "$snapshot_file" ]]; then
    printf '%s\n' "$current_sessions" >"$snapshot_file" 2>/dev/null || true
    return 0
  fi

  previous_sessions="$(cat "$snapshot_file" 2>/dev/null || true)"
  while IFS= read -r session; do
    [[ -z "$session" ]] && continue
    [[ "$session" == "${project}-"* ]] && continue
    if ! printf '%s\n' "$current_sessions" | grep -qxF "$session"; then
      disappeared+=("$session")
    fi
  done <<<"$previous_sessions"

  if [[ ${#disappeared[@]} -gt 0 ]]; then
    local alert_msg="[ALERT:cross-project-disappear] Sessions disappeared: ${disappeared[*]}"
    osascript \
      -e 'on run argv' \
      -e 'display notification (item 1 of argv) with title "ClawSeat Watchdog"' \
      -e 'end run' \
      "$alert_msg" 2>/dev/null || true
    bash "${CLAWSEAT_ROOT}/core/shell-scripts/send-and-verify.sh" \
      --project "${project}" memory "${alert_msg}" 2>/dev/null || true
  fi

  printf '%s\n' "$current_sessions" >"$snapshot_file" 2>/dev/null || true
}

if ! command -v tmux >/dev/null 2>&1; then
  exit 0
fi
check_cross_project_disappear "$project"
if ! tmux has-session -t "$session" 2>/dev/null; then
  echo "warn: patrol session ${session} not found, skipping cron trigger" >&2
  exit 0
fi

message="patrol scan $mode; KB finding frontmatter required: schema_version: 1; format: markdown_note"
{
  printf '%s project=%s mode=%s session=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$project" "$mode" "$session"
} >>"$log_path" 2>/dev/null || true

tmux send-keys -t "$session" "$message" Enter >/dev/null 2>&1 || true
exit 0
