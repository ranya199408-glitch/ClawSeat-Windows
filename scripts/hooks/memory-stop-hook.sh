#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_CLAWSEAT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CLAWSEAT_ROOT="${CLAWSEAT_ROOT:-${CLAUDE_PROJECT_DIR:-$DEFAULT_CLAWSEAT_ROOT}}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
if [[ -f "$CLAWSEAT_ROOT/core/launchers/agent-launcher-common.sh" ]]; then
  # shellcheck source=/dev/null
  source "$CLAWSEAT_ROOT/core/launchers/agent-launcher-common.sh"
fi
# v1 LEGACY (M4 remove): retired global memory session "machine-memory-claude".
LEGACY_GLOBAL_MEMORY_SESSION="$(printf '%s-%s-%s' machine memory claude)"
SESSION_NAME="${TMUX_SESSION_NAME:-$LEGACY_GLOBAL_MEMORY_SESSION}"

parse_payload() {
  local payload_json="$1"
  HOOK_PAYLOAD_JSON="$payload_json" "$PYTHON_BIN" - "$CLAWSEAT_ROOT" <<'PY'
import json
import os
import re
import shlex
import sys
from pathlib import Path

clawseat_root = Path(sys.argv[1]).expanduser()
for extra in (clawseat_root, clawseat_root / "core" / "lib"):
    text = str(extra)
    if text not in sys.path:
        sys.path.insert(0, text)

try:
    from core.resolve import dynamic_profile_path
except Exception:  # pragma: no cover - best effort for hook runtime
    dynamic_profile_path = None  # type: ignore[assignment]


def emit(name: str, value: str) -> None:
    print(f"{name}={shlex.quote(value)}")


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


raw = os.environ.get("HOOK_PAYLOAD_JSON", "").strip()
if not raw:
    raise SystemExit(0)
try:
    payload = json.loads(raw)
except json.JSONDecodeError as exc:
    fail(f"error: invalid Stop payload JSON: {exc.msg}")

session_id = str(payload.get("session_id", "") or "").strip()
if not session_id:
    fail("error: Stop payload missing session_id")

transcript_path = str(payload.get("transcript_path", "") or "").strip()
if not transcript_path:
    fail("error: Stop payload missing transcript_path")
transcript_file = Path(transcript_path).expanduser()
if not transcript_file.is_file():
    fail(f"error: transcript_path does not exist: {transcript_file}")

last_assistant_message = str(payload.get("last_assistant_message", "") or "")

try:
    transcript_text = transcript_file.read_text(encoding="utf-8", errors="replace")
except OSError as exc:
    fail(f"error: unable to read transcript_path {transcript_file}: {exc}")

combined = "\n".join(part for part in (transcript_text, last_assistant_message) if part)

deliver_match = re.search(r"\[DELIVER:([^\]]+)\]", combined)
attrs: dict[str, str] = {}
if deliver_match:
    for token in re.split(r"[,\s]+", deliver_match.group(1).strip()):
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        key = key.strip().lower().replace("-", "_")
        value = value.strip()
        if key and value:
            attrs[key] = value

task_id = (
    attrs.get("task_id")
    or attrs.get("task")
    or attrs.get("query_id")
    or ""
)
if not task_id:
    for pattern in (
        r"(?mi)^task_id:\s*([A-Za-z0-9._-]+)\s*$",
        r"(?mi)^task-id:\s*([A-Za-z0-9._-]+)\s*$",
        r"\b(MEMORY-QUERY-\d+-\d+)\b",
    ):
        match = re.search(pattern, combined)
        if match:
            task_id = match.group(1).strip()
            break

project = (
    attrs.get("project")
    or os.environ.get("CLAWSEAT_PROJECT", "")
    or os.environ.get("AGENTS_PROJECT", "")
)
if not project:
    match = re.search(r"(?mi)^project:\s*([A-Za-z0-9._-]+)\s*$", combined)
    if match:
        project = match.group(1).strip()
push_project = project or "unknown"

profile_path = attrs.get("profile", "")
if not profile_path and project:
    if dynamic_profile_path is not None:
        try:
            profile_path = str(dynamic_profile_path(project))
        except Exception:
            profile_path = str(Path.home() / ".agents" / "profiles" / f"{project}-profile-dynamic.toml")
    else:
        profile_path = str(Path.home() / ".agents" / "profiles" / f"{project}-profile-dynamic.toml")

target = (
    attrs.get("seat")
    or attrs.get("target")
    or attrs.get("to")
    or ""
)

push_text = re.sub(r"\[CLEAR-REQUESTED\]", "", last_assistant_message or "")
push_text = re.sub(r"\[DELIVER:[^\]]+\]", "", push_text).strip()
push_text = re.sub(r"(?mi)^\[Memory\]\s*", "", push_text, count=1).strip()

response_answer = last_assistant_message or combined
response_answer = re.sub(r"\[CLEAR-REQUESTED\]", "", response_answer)
response_answer = re.sub(r"\[DELIVER:[^\]]+\]", "", response_answer)
response_answer = response_answer.strip()
if not response_answer:
    response_answer = "Memory completed the requested query."

response = {
    "answer": response_answer,
    "claims": [],
    "sources": [],
    "confidence": "medium",
}

emit("TRANSCRIPT_PATH", transcript_path)
emit("SESSION_ID", session_id)
emit("CLEAR_REQUESTED", "1" if "[CLEAR-REQUESTED]" in combined else "0")
emit("MEMORY_PUSH", "1" if push_text else "0")
emit("MEMORY_PUSH_TEXT", push_text)
emit("MEMORY_PUSH_PROJECT", push_project)

emit("DELIVER_TARGET", target)
emit("DELIVER_TASK_ID", task_id)
emit("DELIVER_PROJECT", project)
emit("DELIVER_PROFILE", profile_path)
emit("DELIVER_VERDICT", attrs.get("verdict", "") or "")
emit("DELIVER_SUMMARY", attrs.get("summary", "") or "")
emit("DELIVER_COMMIT", attrs.get("commit", "") or "")
emit("DELIVER_SWEEP", attrs.get("sweep", "") or "")
emit("DELIVER_TASK", attrs.get("task", "") or "")
emit("DELIVER_TITLE", attrs.get("title", "") or "")
emit("DELIVER_RESPONSE_JSON", json.dumps(response, ensure_ascii=False))
PY
}

tmux_session_name() {
  tmux display-message -p '#S' 2>/dev/null || echo unknown
}

send_clear() {
  local candidates=()
  local candidate=""
  candidates+=("$SESSION_NAME")
  candidates+=("$LEGACY_GLOBAL_MEMORY_SESSION" "install-memory-claude" "memory-claude")
  for candidate in "${candidates[@]}"; do
    [[ -n "$candidate" ]] || continue
    sleep 0.5
    env -u TMUX tmux send-keys -t "=${candidate#=}" "/clear" Enter 2>/dev/null && return 0 || true
  done
  return 0
}

read_feishu_group_id() {
  local project="$1"
  local binding_path="$HOME/.agents/tasks/${project}/PROJECT_BINDING.toml"
  "$PYTHON_BIN" - "$binding_path" <<'PY' || true
import sys
from pathlib import Path

try:
    import tomllib
except ImportError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

path = Path(sys.argv[1]).expanduser()
if not path.is_file():
    raise SystemExit(0)
try:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(0)

group_id = str(data.get("feishu_group_id") or "").strip()
if not group_id:
    bridge = data.get("bridge")
    if isinstance(bridge, dict):
        group_id = str(bridge.get("group_id") or "").strip()
print(group_id)
PY
}

send_feishu_message() {
  local project="$1" group_id="$2" message="$3"

  [[ -n "$group_id" ]] || { echo "[memory-hook] no group_id; skip feishu" >&2; return 0; }
  command -v lark-cli >/dev/null 2>&1 || { echo "[memory-hook] lark-cli missing; skip feishu" >&2; return 0; }

  if [[ -n "${CALLS_LOG:-}" ]]; then
    printf -- '--as user im +messages-send --chat-id %s --text %s\n' "$group_id" "$message" >> "$CALLS_LOG"
  fi
  LARK_CLI_NO_PROXY=1 lark-cli im +messages-send --as user \
    --chat-id "$group_id" --text "$message" 2>&1 | while IFS= read -r line; do
    echo "[memory-hook] $line" >&2
  done || true
}

build_memory_push_message() {
  local push_text="$1" project="$2" session="$3" ts="$4" task_id="$5" verdict="$6"

  FEISHU_PUSH_TEXT="$push_text" \
  FEISHU_PUSH_PROJECT="$project" \
  FEISHU_PUSH_SESSION="$session" \
  FEISHU_PUSH_TS="$ts" \
  FEISHU_PUSH_TASK_ID="$task_id" \
  FEISHU_PUSH_VERDICT="$verdict" \
  "$PYTHON_BIN" - <<'PY'
import os

text = os.environ.get("FEISHU_PUSH_TEXT", "").strip()
project = os.environ.get("FEISHU_PUSH_PROJECT", "unknown").strip() or "unknown"
session = os.environ.get("FEISHU_PUSH_SESSION", "unknown").strip() or "unknown"
hook_ts = os.environ.get("FEISHU_PUSH_TS", "").strip() or "unknown"
task_id = os.environ.get("FEISHU_PUSH_TASK_ID", "").strip()
verdict = os.environ.get("FEISHU_PUSH_VERDICT", "").strip()

if len(text) > 3500:
    text = text[:3450] + "…[truncated, see TUI]"

parts = [f"project={project}", f"session={session}"]
if task_id:
    parts.append(f"task_id={task_id}")
if verdict:
    parts.append(f"verdict={verdict}")

message = f"[Memory] {text}\n\n---\n_via Memory @ {hook_ts} | " + " | ".join(parts) + "_"
print(message)
PY
}

write_active_session_marker() {
  local seat="${CLAWSEAT_SEAT:-}"
  local session_id="${SESSION_ID:-}"
  [[ -n "$seat" ]] || return 0
  [[ -n "$session_id" ]] || return 0
  launcher_write_active_session_id "$seat" "$session_id" || true
}

deliver_response() {
  local target="$1" task_id="$2" profile="$3" response_json="$4"
  local deliver_script="$CLAWSEAT_ROOT/core/skills/memory-oracle/scripts/memory_deliver.py"

  [[ -n "$target" ]] || return 0
  [[ -n "$task_id" ]] || {
    echo "[memory-hook] deliver_skipped: missing task_id for target '$target'" >&2
    return 0
  }
  [[ -n "$profile" ]] || {
    echo "[memory-hook] deliver_skipped: missing profile for target '$target' task '$task_id'" >&2
    return 0
  }

  "$PYTHON_BIN" "$deliver_script" \
    --profile "$profile" \
    --task-id "$task_id" \
    --target "$target" \
    --response-inline "$response_json" \
    --summary "Auto-delivered by memory Stop hook." \
    2>&1 | while IFS= read -r line; do
      echo "[memory-hook] $line" >&2
    done || true
  return 0
}

main() {
  local payload_json="" parsed="" hook_project="" hook_session="" hook_ts=""
  local feishu_group_id="" memory_push_message=""
  payload_json="$(cat || true)"
  [[ -n "$payload_json" ]] || return 0

  if ! parsed="$(parse_payload "$payload_json")"; then
    return 1
  fi
  [[ -n "$parsed" ]] || return 0
  eval "$parsed"
  write_active_session_marker || true

  hook_project="${DELIVER_PROJECT:-${CLAWSEAT_PROJECT:-${AGENTS_PROJECT:-unknown}}}"
  [[ -n "$hook_project" ]] || hook_project="unknown"
  hook_session="$(tmux_session_name)"
  hook_ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  if [[ "${CLEAR_REQUESTED:-0}" == "1" ]]; then
    send_clear || true
  fi

  if [[ "${MEMORY_PUSH:-0}" == "1" && "${CLAWSEAT_FEISHU_ENABLED:-1}" != "0" ]]; then
    local _mp_project="${MEMORY_PUSH_PROJECT:-$hook_project}"
    local _mp_text="${MEMORY_PUSH_TEXT:-}"
    if [[ -n "$_mp_text" ]]; then
      memory_push_message="$(
        build_memory_push_message \
          "$_mp_text" \
          "$_mp_project" \
          "$hook_session" \
          "$hook_ts" \
          "${DELIVER_TASK_ID:-}" \
          "${DELIVER_VERDICT:-}"
      )"
      if [[ -n "$memory_push_message" ]]; then
        feishu_group_id="$(read_feishu_group_id "$_mp_project")"
        send_feishu_message "$_mp_project" "$feishu_group_id" "$memory_push_message" || true
      fi
    fi
  fi

  if [[ -n "${DELIVER_TARGET:-}" ]]; then
    deliver_response \
      "${DELIVER_TARGET:-}" \
      "${DELIVER_TASK_ID:-}" \
      "${DELIVER_PROFILE:-}" \
      "${DELIVER_RESPONSE_JSON:-}" || true
  fi
}

main "$@"
