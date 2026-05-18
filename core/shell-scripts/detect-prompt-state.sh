#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <tmux-target> [capture_lines]" >&2
  exit 1
fi

target="$1"
lines="${2:-120}"
content="$(tmux capture-pane -pt "$target" -S -"$lines")"

if grep -qi 'Do you want to continue\? \[Y/n\]:' <<<"$content"; then
  echo "shell_confirmation"
  exit 0
fi

if grep -qi 'Shell awaiting input' <<<"$content"; then
  echo "shell_waiting"
  exit 0
fi

if grep -qi 'Queued' <<<"$content"; then
  echo "focus_mismatch_or_queued"
  exit 0
fi

if grep -qi 'Type your message' <<<"$content"; then
  echo "agent_input"
  exit 0
fi

if grep -qi 'Thinking...' <<<"$content"; then
  echo "agent_running"
  exit 0
fi

echo "unknown"
