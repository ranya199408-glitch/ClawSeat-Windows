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

if ! declare -F env_file_has_key >/dev/null; then
  # shellcheck source=../helpers/env.sh
  source "$LAUNCHER_DIR/helpers/env.sh"
fi

validate_auth_mode() {
  local tool="$1" auth="$2"
  case "$tool:$auth" in
    claude:oauth|claude:oauth_token|claude:anthropic-console|claude:minimax|claude:deepseek|claude:xcode|claude:custom|\
    codex:chatgpt|codex:xcode|codex:custom|\
    gemini:oauth|gemini:primary|gemini:custom)
      return 0
      ;;
    *)
      echo "error: unsupported auth '$auth' for tool '$tool'" >&2
      exit 2
      ;;
  esac
}

resolve_claude_secret_file() {
  case "$1" in
    oauth_token) printf '%s\n' "$REAL_HOME/.agents/.env.global" ;;
    anthropic-console) printf '%s\n' "$REAL_HOME/.agents/secrets/claude/anthropic-console.env" ;;
    minimax) printf '%s\n' "$REAL_HOME/.agent-runtime/secrets/claude/minimax.env" ;;
    deepseek) printf '%s\n' "$REAL_HOME/.agent-runtime/secrets/claude/deepseek.env" ;;
    xcode) printf '%s\n' "$REAL_HOME/.agent-runtime/secrets/claude/xcode.env" ;;
    *) return 1 ;;
  esac
}

show_claude_auth_setup_hint() {
  local auth_mode="$1"
  case "$auth_mode" in
    oauth_token)
      cat >&2 <<'EOF'
hint: missing Claude OAuth token
  run: claude setup-token
  then write the result into: ~/.agents/.env.global
  example: export CLAUDE_CODE_OAUTH_TOKEN=<CLAUDE_CODE_OAUTH_TOKEN>
EOF
      ;;
    anthropic-console)
      cat >&2 <<'EOF'
hint: missing Anthropic Console API key
  create a Claude Code scoped key in Anthropic Console
  then write it into: ~/.agents/secrets/claude/anthropic-console.env
  example: ANTHROPIC_API_KEY=<ANTHROPIC_API_KEY>
EOF
      ;;
  esac
}

# ── --check-secrets dispatch ───────────────────────────────────────────
# install preflight hook: given --check-secrets <tool> + --auth <mode>,
# resolve the expected secret file and report its state as one JSON line on
# stdout so Python callers can parse without shelling out to jq.
#   exit 0 = secret file present + required key found (or inherently not needed)
#   exit 1 = missing file or missing key (hint in payload)
#   exit 2 = bad (tool, auth) combination or --auth missing
handle_check_secrets() {
  if [[ -z "${CHECK_SECRETS_TOOL:-}" ]]; then
    return 0
  fi
  if [[ -z "$AUTH_MODE" ]]; then
    echo '{"status":"error","reason":"--check-secrets requires --auth <mode>"}' >&2
    exit 2
  fi
  _cs_file=""
  _cs_key=""
  case "$CHECK_SECRETS_TOOL" in
    claude)
      case "$AUTH_MODE" in
        oauth)
          printf '{"status":"ok","note":"legacy keychain oauth; no secret file"}\n'
          exit 0 ;;
        oauth_token)
          _cs_file="$REAL_HOME/.agents/.env.global"
          _cs_key="CLAUDE_CODE_OAUTH_TOKEN" ;;
        anthropic-console)
          _cs_file="$REAL_HOME/.agents/secrets/claude/anthropic-console.env"
          _cs_key="ANTHROPIC_API_KEY" ;;
        minimax)
          _cs_file="$REAL_HOME/.agent-runtime/secrets/claude/minimax.env"
          _cs_key="ANTHROPIC_AUTH_TOKEN" ;;
        deepseek)
          _cs_file="$REAL_HOME/.agent-runtime/secrets/claude/deepseek.env"
          _cs_key="ANTHROPIC_AUTH_TOKEN" ;;
        xcode)
          _cs_file="$REAL_HOME/.agent-runtime/secrets/claude/xcode.env"
          _cs_key="ANTHROPIC_AUTH_TOKEN" ;;
        custom)
          printf '{"status":"ok","note":"custom auth — secret via --custom-env-file"}\n'
          exit 0 ;;
        *) echo "{\"status\":\"error\",\"reason\":\"unknown claude auth '$AUTH_MODE'\"}" >&2 ; exit 2 ;;
      esac ;;
    codex)
      case "$AUTH_MODE" in
        chatgpt)
          printf '{"status":"ok","note":"codex chatgpt login uses ~/.codex (keychain); no file needed"}\n'
          exit 0 ;;
        xcode)
          _cs_file="$REAL_HOME/.agent-runtime/secrets/codex/xcode.env"
          _cs_key="OPENAI_API_KEY" ;;
        custom)
          printf '{"status":"ok","note":"custom auth — secret via --custom-env-file"}\n'
          exit 0 ;;
        *) echo "{\"status\":\"error\",\"reason\":\"unknown codex auth '$AUTH_MODE'\"}" >&2 ; exit 2 ;;
      esac ;;
    gemini)
      case "$AUTH_MODE" in
        oauth)
          printf '{"status":"ok","note":"gemini google oauth uses ~/.gemini (keychain); no file needed"}\n'
          exit 0 ;;
        primary)
          _cs_file="$REAL_HOME/.agent-runtime/secrets/gemini/primary.env"
          _cs_key="GEMINI_API_KEY" ;;
        custom)
          printf '{"status":"ok","note":"custom auth — secret via --custom-env-file"}\n'
          exit 0 ;;
        *) echo "{\"status\":\"error\",\"reason\":\"unknown gemini auth '$AUTH_MODE'\"}" >&2 ; exit 2 ;;
      esac ;;
    *)
      echo "{\"status\":\"error\",\"reason\":\"--check-secrets tool must be claude|codex|gemini, got '$CHECK_SECRETS_TOOL'\"}" >&2
      exit 2 ;;
  esac
  if [[ ! -f "$_cs_file" ]]; then
    if [[ "$CHECK_SECRETS_TOOL" = "claude" ]] && [[ "$AUTH_MODE" = "oauth_token" ]]; then
      _hint="run: claude setup-token    # paste result into $_cs_file"
    else
      _hint="obtain the $_cs_key for $CHECK_SECRETS_TOOL/$AUTH_MODE and write it into $_cs_file"
    fi
    printf '{"status":"missing-file","file":"%s","key":"%s","hint":"%s"}\n' \
      "$_cs_file" "$_cs_key" "$_hint"
    exit 1
  fi
  if ! env_file_has_key "$_cs_file" "$_cs_key"; then
    printf '{"status":"missing-key","file":"%s","key":"%s","hint":"add %s=... to %s"}\n' \
      "$_cs_file" "$_cs_key" "$_cs_key" "$_cs_file"
    exit 1
  fi
  printf '{"status":"ok","file":"%s","key":"%s"}\n' "$_cs_file" "$_cs_key"
  exit 0
}

