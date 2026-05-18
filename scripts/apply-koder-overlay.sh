#!/usr/bin/env bash
# WARNING: This script is destructive.
# - Overwrites workspace-<tenant>/ contents in the OpenClaw home directory.
# - Requires B2.5 (bootstrap_machine_tenants.py) to have populated
#   ~/.clawseat/machine.toml with openclaw.json scan results FIRST.
# - Run order: install.sh -> B2.5 -> apply-koder-overlay.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CLAWSEAT_ROOT="${CLAWSEAT_ROOT:-$REPO_ROOT}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

DRY_RUN=0
QUIET=0
PROJECT="install"
FEISHU_GROUP_ID=""
REAL_HOME="${CLAWSEAT_REAL_HOME:-$HOME}"

TENANT_NAMES=()
TENANT_WORKSPACES=()
CHOSEN=""
WORKSPACE=""

usage() {
  cat <<'EOF'
Usage: scripts/apply-koder-overlay.sh [OPTIONS] [project] [feishu_group_id]

Options:
  --dry-run                 Show what would be done without executing runners
  -q, --quiet               Suppress destructive banner (for CI)
  -h, --help                Show this help and exit
EOF
}

err() {
  local code="$1" message="$2"
  printf 'ERR_%s: %s\n' "$code" "$message" >&2
}

die() {
  local status="$1" code="$2" message="$3"
  err "$code" "$message"
  exit "$status"
}

note() {
  printf '==> %s\n' "$*"
}

print_cmd() {
  printf '[dry-run] '
  printf '%q ' "$@"
  printf '\n'
}

read_project_binding_field() {
  local field="$1"
  local binding_path="$REAL_HOME/.agents/tasks/$PROJECT/PROJECT_BINDING.toml"
  [[ -f "$binding_path" ]] || return 0
  "$PYTHON_BIN" - "$binding_path" "$field" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

path = Path(sys.argv[1])
field = sys.argv[2]
try:
    import tomllib
except Exception:
    import tomli as tomllib

try:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(0)

value = data.get(field, "")
if value:
    print(value)
PY
}

run_or_die() {
  local status="$1" code="$2" message="$3"
  shift 3
  if [[ "$DRY_RUN" == "1" ]]; then
    print_cmd "$@"
    return 0
  fi
  "$@" || die "$status" "$code" "$message"
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --dry-run)
        DRY_RUN=1
        shift
        ;;
      --quiet|-q)
        QUIET=1
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      --)
        shift
        break
        ;;
      -*)
        die 2 BAD_FLAG "unknown flag: $1"
        ;;
      *)
        break
        ;;
    esac
  done

  if [[ $# -gt 0 ]]; then
    PROJECT="$1"
    shift
  fi
  if [[ $# -gt 0 ]]; then
    FEISHU_GROUP_ID="$1"
    shift
  fi
  [[ $# -eq 0 ]] || die 2 BAD_USAGE "too many positional arguments"
  [[ "$PROJECT" =~ ^[a-z0-9-]+$ ]] || die 2 BAD_PROJECT "project must match ^[a-z0-9-]+$"
}

resolve_profile_path() {
  "$PYTHON_BIN" - "$REPO_ROOT" "$PROJECT" <<'PY'
import sys
from pathlib import Path

repo = Path(sys.argv[1])
for path in (repo, repo / "core" / "lib"):
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)

from core.resolve import dynamic_profile_path

print(dynamic_profile_path(sys.argv[2]))
PY
}

resolve_openclaw_home() {
  if [[ -n "${OPENCLAW_HOME:-}" ]]; then
    printf '%s\n' "$OPENCLAW_HOME"
    return 0
  fi
  "$PYTHON_BIN" - "$REPO_ROOT" <<'PY'
import sys
from pathlib import Path

repo = Path(sys.argv[1])
for path in (repo, repo / "core" / "lib"):
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)

from real_home import real_user_home

print(real_user_home() / ".openclaw")
PY
}

collect_tenants() {
  local output=""
  output="$("$PYTHON_BIN" - "$REPO_ROOT" <<'PY'
import sys
from pathlib import Path

repo = Path(sys.argv[1])
for path in (repo, repo / "core" / "lib"):
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)

from core.lib.machine_config import list_openclaw_tenants

for tenant in list_openclaw_tenants():
    print(f"{tenant.name}\t{tenant.workspace}")
PY
)" || die 11 LIST_OPENCLAW_AGENTS_FAILED "unable to enumerate OpenClaw tenants"

  TENANT_NAMES=()
  TENANT_WORKSPACES=()
  while IFS=$'\t' read -r name workspace; do
    [[ -n "${name:-}" ]] || continue
    TENANT_NAMES+=("$name")
    TENANT_WORKSPACES+=("$workspace")
  done <<<"$output"

  [[ ${#TENANT_NAMES[@]} -gt 0 ]] || die 2 NO_OPENCLAW_AGENTS "~/.openclaw/ 下未找到可用 OpenClaw agent"
}

choose_tenant() {
  local idx="" zero_idx=""
  echo "可选的 OpenClaw agent (作为 koder 身份)："
  for idx in "${!TENANT_NAMES[@]}"; do
    printf '  [%d] %s\n' "$((idx + 1))" "${TENANT_NAMES[$idx]}"
  done

  if [[ "$DRY_RUN" == "1" ]]; then
    CHOSEN="${TENANT_NAMES[0]}"
    WORKSPACE="${TENANT_WORKSPACES[0]}"
    printf '[dry-run] auto-selecting [1] %s\n' "$CHOSEN"
    return 0
  fi

  read -r -p "Pick number: " idx || die 3 PICK_READ_FAILED "failed to read tenant selection"
  [[ "$idx" =~ ^[0-9]+$ ]] || die 3 BAD_PICK "pick must be a positive integer"
  zero_idx=$((idx - 1))
  if (( zero_idx < 0 || zero_idx >= ${#TENANT_NAMES[@]} )); then
    die 3 BAD_PICK "pick out of range: $idx"
  fi

  CHOSEN="${TENANT_NAMES[$zero_idx]}"
  WORKSPACE="${TENANT_WORKSPACES[$zero_idx]}"
}

confirm_overlay() {
  printf "将把 '%s' 的身份完全覆盖为 koder。此操作会改写 6 个核心文件（IDENTITY/SOUL/TOOLS/MEMORY/AGENTS/CONTRACT）。\n" "$CHOSEN"
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[dry-run] destructive confirmation skipped"
    return 0
  fi
  local confirm=""
  read -r -p "确认? [y/N]: " confirm || die 4 CONFIRM_READ_FAILED "failed to read destructive confirmation"
  if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
    echo "aborted"
    exit 0
  fi
}

run_init_koder() {
  local profile_path="$1"
  local init_script="$CLAWSEAT_ROOT/core/skills/clawseat-install/scripts/init_koder.py"
  local -a cmd=()

  note "Step 4: init_koder"
  if [[ -n "${INIT_KODER_RUNNER:-}" ]]; then
    cmd=("$INIT_KODER_RUNNER")
  else
    cmd=("$PYTHON_BIN" "$init_script")
  fi
  cmd+=(--workspace "$WORKSPACE" --project "$PROJECT" --profile "$profile_path" --on-conflict backup)
  if [[ -n "$FEISHU_GROUP_ID" ]]; then
    cmd+=(--feishu-group-id "$FEISHU_GROUP_ID")
  fi

  run_or_die 4 INIT_KODER_FAILED "init_koder.py failed for tenant '$CHOSEN'" "${cmd[@]}"
}

run_koder_bind() {
  local bind_py=""
  local -a cmd=()

  note "Step 5: project koder-bind"
  if [[ -n "${KODER_BIND_RUNNER:-}" ]]; then
    cmd=("$KODER_BIND_RUNNER" --project "$PROJECT" --tenant "$CHOSEN" --workspace "$WORKSPACE")
    if [[ -n "${FEISHU_GROUP_ID:-}" ]]; then
      cmd+=(--feishu-group-id "$FEISHU_GROUP_ID")
    fi
  else
    bind_py='import sys; from pathlib import Path; repo = Path(sys.argv[1]); sys.path[:0] = [str(repo), str(repo / "core" / "lib")]; from core.scripts.agent_admin_layered import do_koder_bind; do_koder_bind(sys.argv[2], sys.argv[3], group_id=sys.argv[4] if len(sys.argv) > 4 and sys.argv[4] else None)'
    cmd=("$PYTHON_BIN" -c "$bind_py" "$REPO_ROOT" "$PROJECT" "$CHOSEN" "${FEISHU_GROUP_ID:-}")
  fi

  run_or_die 5 KODER_BIND_FAILED "agent-admin koder-bind failed for tenant '$CHOSEN'" "${cmd[@]}"
}

run_feishu_config() {
  local openclaw_home="$1"
  local configure_script="$CLAWSEAT_ROOT/core/skills/clawseat-install/scripts/configure_koder_feishu.py"
  local -a cmd=()

  [[ -n "$FEISHU_GROUP_ID" ]] || return 0

  note "Step 6: configure koder feishu"
  if [[ -n "${CONFIGURE_KODER_FEISHU_RUNNER:-}" ]]; then
    cmd=("$CONFIGURE_KODER_FEISHU_RUNNER")
  else
    cmd=("$PYTHON_BIN" "$configure_script")
  fi
  cmd+=(--agent "$CHOSEN" --group-id "$FEISHU_GROUP_ID" --openclaw-home "$openclaw_home")

  run_or_die 6 CONFIGURE_KODER_FEISHU_FAILED "configure_koder_feishu.py failed for tenant '$CHOSEN'" "${cmd[@]}"
}

print_layer2_hint() {
  local sender_app_id
  sender_app_id="$(read_project_binding_field feishu_sender_app_id)"
  sender_app_id="${sender_app_id:-<FEISHU_SENDER_APP_ID>}"

  cat <<EOF

✓ koder overlay applied (OpenClaw Layer 1 ready).

──────────────────────────────────────────────────
Layer 1 (OpenClaw side) configured automatically.
Layer 2 (Feishu) requires manual operator action:
  1. Go to Feishu developer console (https://open.feishu.cn/app)
  2. Enable 'Receive all group messages' for this bot
  3. Add bot to the target group
Without Layer 2, non-@ messages will not reach koder.
──────────────────────────────────────────────────

⚠ Feishu Layer 2 配置必需（operator 手动操作）：
  1. 打开 https://open.feishu.cn/app
  2. 选 app ${sender_app_id}
  3. 事件订阅 → 消息接收模式 → 选 "接收群聊所有消息"（非仅 @）
  4. 如 app 已 release，点击 "刷新 release"
  5. 完成后回 memory 确认 "ok"，再继续 B5.5 / B6

注：此步 lark-cli / Open API 不可编程，必须 UI 操作。
配置不做 → bot 只响应 @，非 @ 消息到达不了 OpenClaw。
EOF
}

print_banner() {
  [[ "$QUIET" == "1" ]] && return 0
  cat <<'BANNER'
══════════════════════════════════════════════════════
  ⚠ WARNING — apply-koder-overlay.sh is DESTRUCTIVE
══════════════════════════════════════════════════════
  This script will overwrite workspace-<tenant>/ contents.

  PREREQUISITE: B2.5 must have populated ~/.clawseat/machine.toml
  via bootstrap_machine_tenants.py (which scans openclaw.json).

  Required run order:
    1) install.sh        (Phase A)
    2) B2.5 bootstrap    (~/.clawseat/machine.toml populated)
    3) apply-koder-overlay.sh   ← you are here

  Without prerequisites, koder overlay binding will be incomplete.
══════════════════════════════════════════════════════
BANNER
}

main() {
  local profile_path="" openclaw_home=""

  parse_args "$@"
  print_banner

  note "Step 1: list OpenClaw tenants"
  collect_tenants
  choose_tenant
  confirm_overlay

  profile_path="$(resolve_profile_path)" || die 12 PROFILE_RESOLVE_FAILED "unable to resolve profile path for project '$PROJECT'"
  if [[ "$DRY_RUN" != "1" && ! -f "$profile_path" ]]; then
    die 12 PROFILE_NOT_FOUND "profile not found: $profile_path"
  fi

  openclaw_home="$(resolve_openclaw_home)" || die 13 OPENCLAW_HOME_RESOLVE_FAILED "unable to resolve OpenClaw home"

  run_init_koder "$profile_path"
  run_koder_bind
  run_feishu_config "$openclaw_home"
  print_layer2_hint

  printf "OK: '%s' 已改造为 koder，绑定到项目 '%s'\n" "$CHOSEN" "$PROJECT"
}

main "$@"
