#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
AGENTCTL="${AGENTCTL_BIN:-$REPO_ROOT/core/shell-scripts/agentctl.sh}"
REAL_HOME="${CLAWSEAT_REAL_HOME:-${HOME:-}}"
AGENTS_ROOT="${AGENTS_ROOT:-${REAL_HOME}/.agents}"

usage() {
  printf 'Usage: %s <project> <seat>\n' "$0" >&2
  exit 2
}

PROJECT_SCOPE="${CLAWSEAT_PROJECT:-}"
SEAT_ID=""
BASE_SESSION=""
if [[ $# -eq 1 ]]; then
  printf 'error: 1-arg form is retired; rerun as: %s <project> <seat>\n' "$0" >&2
  exit 2
elif [[ $# -eq 2 ]]; then
  PROJECT_SCOPE="$1"
  SEAT_ID="$2"
  BASE_SESSION="$PROJECT_SCOPE-$SEAT_ID"
else
  usage
fi

POLL_SECONDS="${WAIT_FOR_SEAT_POLL_SECONDS:-2}"
RECONNECT_PAUSE="${WAIT_FOR_SEAT_RECONNECT_PAUSE:-2}"
PRIMARY_FAILURE_BUDGET="${WAIT_FOR_SEAT_PRIMARY_FAILURE_BUDGET:-10}"
DEGRADED_WARN_EVERY_POLLS="${WAIT_FOR_SEAT_DEGRADED_WARN_EVERY_POLLS:-15}"
PRIMARY_FAILURE_COUNT=0
TARGET_SESSION=""

resolve_via_agentctl() {
  local resolved=""
  [[ -x "$AGENTCTL" ]] || return 1
  resolved="$("$AGENTCTL" session-name "$SEAT_ID" --project "$PROJECT_SCOPE" 2>/dev/null || true)"
  [[ -n "$resolved" ]] || return 1
  printf '%s\n' "$resolved"
}

fallback_session_prefix() {
  printf '%s-%s\n' "$PROJECT_SCOPE" "$SEAT_ID"
}

engineer_profile_path() {
  printf '%s/engineers/%s/engineer.toml\n' "$AGENTS_ROOT" "$SEAT_ID"
}

warn_fallback_attach() {
  local attempt_count="$1"
  local session_name="$2"
  printf "WARN: agentctl resolution failed after %s attempts; falling back to '%s'\n" \
    "$attempt_count" "$session_name" >&2
}

warn_stale_tool_session() {
  local session_name="$1"
  local canonical_tool="$2"
  printf 'WARN: wait-for-seat stale-tool session detected: found %s, canonical tool is %s, skipping\n' \
    "$session_name" "$canonical_tool" >&2
}

warn_canonical_tool_lookup_failed() {
  local reason="$1"
  local engineer_file="$2"
  printf 'WARN: wait-for-seat cannot resolve canonical tool for %s: %s (%s); fix %s so it contains a valid default_tool, then keep waiting\n' \
    "$BASE_SESSION" "$reason" "$engineer_file" "$engineer_file" >&2
}

warn_degraded_wait() {
  local attempt_count="$1"
  printf "WARN: agentctl resolution still degraded for %s after %s attempts; waiting for canonical session or fixed suffix fallback\n" \
    "$BASE_SESSION" "$attempt_count" >&2
}

read_default_tool_from_engineer_profile() {
  local engineer_file="$1"
  command -v python3 >/dev/null 2>&1 || {
    printf 'python3 is unavailable for engineer.toml parsing\n' >&2
    return 14
  }
  python3 - "$engineer_file" <<'PY'
from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

path = Path(sys.argv[1]).expanduser()
tool_pattern = re.compile(r"^[A-Za-z0-9._-]+$")
try:
    with path.open("rb") as fh:
        data = tomllib.load(fh)
except FileNotFoundError:
    print("missing engineer profile", file=sys.stderr)
    raise SystemExit(11)
except PermissionError as exc:
    print(f"unreadable engineer profile: {exc}", file=sys.stderr)
    raise SystemExit(12)
except tomllib.TOMLDecodeError as exc:
    print(f"malformed engineer profile: {exc}", file=sys.stderr)
    raise SystemExit(13)
except OSError as exc:
    print(f"unreadable engineer profile: {exc}", file=sys.stderr)
    raise SystemExit(12)

tool = data.get("default_tool")
if not isinstance(tool, str) or not tool.strip():
    print("malformed engineer profile: missing default_tool", file=sys.stderr)
    raise SystemExit(13)

tool = tool.strip()
if not tool_pattern.fullmatch(tool):
    print(f"malformed engineer profile: invalid default_tool '{tool}'", file=sys.stderr)
    raise SystemExit(13)

print(tool)
PY
}

resolve_via_fixed_suffix_fallback() {
  local prefix="" suffix="" candidate="" canonical_tool="" engineer_file="" lookup_output=""
  prefix="$(fallback_session_prefix || true)"
  [[ -n "$prefix" ]] || return 1
  engineer_file="$(engineer_profile_path)"
  lookup_output="$(read_default_tool_from_engineer_profile "$engineer_file" 2>&1)"
  if [[ $? -ne 0 ]]; then
    warn_canonical_tool_lookup_failed "$lookup_output" "$engineer_file"
    return 1
  fi
  canonical_tool="$lookup_output"
  for suffix in claude codex gemini; do
    [[ "$suffix" == "$canonical_tool" ]] && continue
    candidate="${prefix}-${suffix}"
    if tmux has-session -t "=$candidate" 2>/dev/null; then
      warn_stale_tool_session "$candidate" "$canonical_tool"
    fi
  done
  candidate="${prefix}-${canonical_tool}"
  if tmux has-session -t "=$candidate" 2>/dev/null; then
    warn_fallback_attach "$PRIMARY_FAILURE_COUNT" "$candidate"
    printf '%s\n' "$candidate"
    return 0
  fi
  return 1
}

resolve_session() {
  local base="$1" resolved=""
  TARGET_SESSION=""
  resolved="$(resolve_via_agentctl || true)"
  if [[ -n "$resolved" ]] && tmux has-session -t "=$resolved" 2>/dev/null; then
    PRIMARY_FAILURE_COUNT=0
    TARGET_SESSION="$resolved"
    return 0
  fi
  PRIMARY_FAILURE_COUNT=$((PRIMARY_FAILURE_COUNT + 1))
  if (( PRIMARY_FAILURE_COUNT >= PRIMARY_FAILURE_BUDGET )); then
    if resolved="$(resolve_via_fixed_suffix_fallback)"; then
      TARGET_SESSION="$resolved"
      return 0
    fi
    if (( PRIMARY_FAILURE_COUNT == PRIMARY_FAILURE_BUDGET )) || \
       (( DEGRADED_WARN_EVERY_POLLS > 0 && PRIMARY_FAILURE_COUNT % DEGRADED_WARN_EVERY_POLLS == 0 )); then
      warn_degraded_wait "$PRIMARY_FAILURE_COUNT"
    fi
  fi
  return 1
}

print_waiting() {
  printf 'pane is waiting for %s ...\n' "$BASE_SESSION"
  printf '(seat will appear here once project memory spawns it)\n'
}

print_reconnecting() {
  local session_name="$1"
  printf 'DETACHED from %s - reconnecting in %ss ...\n' "$session_name" "$RECONNECT_PAUSE"
  printf '(tmux session is still alive; press Ctrl+C to stop waiting)\n'
}

print_trust_prompt_detected() {
  local session_name="$1"
  printf 'gemini trust prompt detected at %s - operator attach pane and press 1\n' "$session_name" >&2
}

capture_pane_text() {
  local session_name="$1"
  tmux capture-pane -t "=$session_name" -p -S -80 2>/dev/null || true
}

detect_trust_prompt() {
  case "$1" in
    *"Do you trust the files in this folder"*|*"Trust folder"*)
      return 0
      ;;
  esac
  return 1
}

while true; do
  if resolve_session "$BASE_SESSION"; then
    attach_rc=0
    if env -u TMUX tmux attach -t "=$TARGET_SESSION"; then
      attach_rc=0
    else
      attach_rc=$?
      pane_text="$(capture_pane_text "$TARGET_SESSION")"
      if detect_trust_prompt "$pane_text"; then
        print_trust_prompt_detected "$TARGET_SESSION"
      fi
    fi
    printf 'DETACHED from %s\n' "$TARGET_SESSION"
    sleep "$RECONNECT_PAUSE"
    if env -u TMUX tmux has-session -t "=$TARGET_SESSION" 2>/dev/null; then
      print_reconnecting "$TARGET_SESSION"
      continue
    fi
    exit "$attach_rc"
  else
    print_waiting
    sleep "$POLL_SECONDS"
  fi
done
