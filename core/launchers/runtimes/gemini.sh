#!/usr/bin/env bash
# Sourced by agent-launcher.sh. Keep path resolution BASH_SOURCE-based because
# sourced files observe a different $0 than the top-level launcher.

if [[ -z "${LAUNCHER_DIR:-}" ]]; then
  _launcher_lib_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  case "$_launcher_lib_dir" in
    */helpers|*/runtimes) LAUNCHER_DIR="$(cd "$_launcher_lib_dir/.." && pwd)" ;;
    *) LAUNCHER_DIR="$_launcher_lib_dir" ;;
  esac
  export LAUNCHER_DIR
fi
if [[ -z "${LAUNCHER_REPO_ROOT:-}" ]]; then
  LAUNCHER_REPO_ROOT="$(cd "$LAUNCHER_DIR/../.." && pwd)"
fi
REAL_HOME="${REAL_HOME:-${HOME:-}}"
LAUNCHER_PYTHON_BIN="${LAUNCHER_PYTHON_BIN:-${PYTHON_BIN:-python3}}"

if ! declare -F load_custom_env >/dev/null; then
  # shellcheck source=../helpers/env.sh
  source "$LAUNCHER_DIR/helpers/env.sh"
fi
if ! declare -F resolve_claude_secret_file >/dev/null; then
  # shellcheck source=../helpers/auth.sh
  source "$LAUNCHER_DIR/helpers/auth.sh"
fi
if ! declare -F seed_user_tool_dirs >/dev/null; then
  # shellcheck source=../helpers/sandbox.sh
  source "$LAUNCHER_DIR/helpers/sandbox.sh"
fi

run_gemini_runtime() {
  local auth_mode="$1"
  local workdir="$2"
  local session_name="$3"
  local -a resume_args=()
  local resume_label=""

  if [[ "${CLAWSEAT_NO_AUTO_RESUME:-0}" != "1" ]]; then
    resume_args=(--resume latest)
    resume_label="$(launcher_read_active_session_id "${CLAWSEAT_SEAT:-}" 2>/dev/null || true)"
    [[ -z "$resume_label" ]] && resume_label="latest"
  fi

  if [[ "$auth_mode" == "oauth" ]]; then
    unset GEMINI_API_KEY GOOGLE_API_KEY
    export HOME="$REAL_HOME"
    seed_user_tool_dirs "$HOME" "${CLAWSEAT_PROJECT:-}"
    prepare_gemini_home "$HOME" "$workdir"
    cd "$workdir"
    echo "────────────────────────────────────────"
    echo " Gemini CLI · OAuth"
    echo " Session:    $session_name"
    echo " Directory:  $workdir"
    echo " HOME:       $HOME"
    echo "────────────────────────────────────────"
    [[ -n "$resume_args" ]] && launcher_resume_banner "$resume_label" >&2
    exec gemini -y ${resume_args[@]+"${resume_args[@]}"}
  fi

  local secret_file="" runtime_dir
  if [[ "$auth_mode" != "custom" ]]; then
    secret_file="$REAL_HOME/.agent-runtime/secrets/gemini/primary.env"
    if [[ ! -f "$secret_file" ]]; then
      echo "error: missing Gemini secret file: $secret_file" >&2
      exit 1
    fi
  fi

  runtime_dir="$REAL_HOME/.agent-runtime/identities/gemini/api/${auth_mode}-${session_name}"
  mkdir -p \
    "$runtime_dir/home" \
    "$runtime_dir/xdg/config" \
    "$runtime_dir/xdg/data" \
    "$runtime_dir/xdg/cache" \
    "$runtime_dir/xdg/state"

  export HOME="$runtime_dir/home"
  export XDG_CONFIG_HOME="$runtime_dir/xdg/config"
  export XDG_DATA_HOME="$runtime_dir/xdg/data"
  export XDG_CACHE_HOME="$runtime_dir/xdg/cache"
  export XDG_STATE_HOME="$runtime_dir/xdg/state"
  seed_user_tool_dirs "$HOME" "${CLAWSEAT_PROJECT:-}"
  prepare_gemini_home "$HOME" "$workdir"

  if [[ "$auth_mode" == "custom" ]]; then
    load_custom_env "$CUSTOM_ENV_FILE"
    export GEMINI_API_KEY="${LAUNCHER_CUSTOM_API_KEY:-}"
    export GOOGLE_API_KEY="${LAUNCHER_CUSTOM_API_KEY:-}"
    export GOOGLE_GEMINI_BASE_URL="${LAUNCHER_CUSTOM_BASE_URL:-}"
  else
    set -a
    source "$secret_file"
    set +a
    export GOOGLE_API_KEY="${GOOGLE_API_KEY:-${GEMINI_API_KEY:-}}"
  fi

  cd "$workdir"
  echo "────────────────────────────────────────"
  echo " Gemini CLI · $(uppercase_ascii "$auth_mode") API"
  echo " Session:    $session_name"
  echo " Directory:  $workdir"
  echo " HOME:       $HOME"
  echo " XDG_CONFIG: $XDG_CONFIG_HOME"
  echo "────────────────────────────────────────"
  [[ -n "$resume_args" ]] && launcher_resume_banner "$resume_label" >&2
  if [[ -n "${LAUNCHER_CUSTOM_MODEL:-}" ]]; then
    exec gemini -y -m "${LAUNCHER_CUSTOM_MODEL}" ${resume_args[@]+"${resume_args[@]}"}
  fi
  exec gemini -y ${resume_args[@]+"${resume_args[@]}"}
}
