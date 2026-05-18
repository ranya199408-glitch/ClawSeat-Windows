#!/usr/bin/env bash
# shellcheck shell=bash
# Loaded by scripts/install.sh. Resolve this file with BASH_SOURCE so
# callers may source install.sh from any current working directory.
_CLAWSEAT_INSTALL_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

require_tty_for_provider_prompt() {
  if [[ ! -t 0 || ! -t 1 ]]; then
    die 2 NON_TTY_NO_PROVIDER \
      "non-TTY environment detected (e.g. agent-launcher sandbox); use --provider <flag>. Run: bash scripts/install.sh --help"
  fi
}

export_line() { printf 'export %s=%q\n' "$1" "$2"; }

remember_provider_selection() {
  PROVIDER_MODE="$1"
  PROVIDER_KEY="${2:-}"
  PROVIDER_BASE="${3:-}"
  PROVIDER_MODEL="${4:-}"
}

provider_config_value() {
  local query="$1"
  local tool="$2"
  local provider="${3:-}"
  "$PYTHON_BIN" - "$REPO_ROOT" "$query" "$tool" "$provider" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

repo_root = Path(sys.argv[1])
query = sys.argv[2]
tool = sys.argv[3]
provider = sys.argv[4]
sys.path.insert(0, str(repo_root / "core" / "scripts"))

from agent_admin_config import provider_default_base_url, tool_default_base_url

value = ""
if query == "tool-default-base-url":
    value = tool_default_base_url(tool) or ""
elif query == "provider-default-base-url":
    value = provider_default_base_url(tool, provider) or ""
print(value)
PY
}

install_provider_default_model() {
  local provider="$1"
  "$PYTHON_BIN" - "$REPO_ROOT" "$provider" <<'PY'
from __future__ import annotations
import sys
from pathlib import Path
repo_root = Path(sys.argv[1])
provider = sys.argv[2]
sys.path.insert(0, str(repo_root / "core" / "scripts"))
from agent_admin_config import provider_default_model
print(provider_default_model('claude', provider) or '')
PY
}

CLAUDE_DEFAULTS_LOADED=0
CLAUDE_DEFAULT_BASE_URL=""
CLAUDE_MINIMAX_DEFAULT_BASE_URL=""
CLAUDE_DEEPSEEK_DEFAULT_BASE_URL=""
CLAUDE_ARK_DEFAULT_BASE_URL=""
CLAUDE_XCODE_DEFAULT_BASE_URL=""

load_claude_default_base_urls() {
  [[ "$CLAUDE_DEFAULTS_LOADED" == "1" ]] && return 0
  CLAUDE_DEFAULT_BASE_URL="$(provider_config_value tool-default-base-url claude)"
  CLAUDE_MINIMAX_DEFAULT_BASE_URL="$(provider_config_value provider-default-base-url claude minimax)"
  CLAUDE_DEEPSEEK_DEFAULT_BASE_URL="$(provider_config_value provider-default-base-url claude deepseek)"
  CLAUDE_ARK_DEFAULT_BASE_URL="$(provider_config_value provider-default-base-url claude ark)"
  CLAUDE_XCODE_DEFAULT_BASE_URL="$(provider_config_value provider-default-base-url claude xcode-best)"
  CLAUDE_DEFAULTS_LOADED=1
}

claude_tool_default_base_url() {
  load_claude_default_base_urls
  printf '%s\n' "$CLAUDE_DEFAULT_BASE_URL"
}

provider_default_base_url() {
  load_claude_default_base_urls
  case "$1" in
    minimax) printf '%s\n' "$CLAUDE_MINIMAX_DEFAULT_BASE_URL" ;;
    deepseek) printf '%s\n' "$CLAUDE_DEEPSEEK_DEFAULT_BASE_URL" ;;
    ark) printf '%s\n' "$CLAUDE_ARK_DEFAULT_BASE_URL" ;;
    xcode-best) printf '%s\n' "$CLAUDE_XCODE_DEFAULT_BASE_URL" ;;
    anthropic_console) printf '%s\n' "$CLAUDE_DEFAULT_BASE_URL" ;;
    *) return 1 ;;
  esac
}

provider_base_or_default() {
  local mode="$1" base="${2:-}"
  if [[ -n "$base" ]]; then
    printf '%s\n' "$base"
    return 0
  fi
  provider_default_base_url "$mode"
}

print_provider_url_notice() {
  local mode="$1" base="${2:-}"
  case "$mode" in
    minimax|deepseek|ark|xcode-best)
      [[ -n "$base" ]] && printf 'Provider URL will be auto-configured to %s\n' "$base"
      ;;
  esac
}

normalize_provider_choice() {
  if [[ "$FORCE_PROVIDER" =~ ^[0-9]+$ ]]; then
    FORCE_PROVIDER_CHOICE="$FORCE_PROVIDER"
    FORCE_PROVIDER=""
  fi
  if [[ -n "$FORCE_PROVIDER_CHOICE" && ! "$FORCE_PROVIDER_CHOICE" =~ ^[0-9]+$ ]]; then
    FORCE_PROVIDER_CHOICE=""
  fi
}

detect_provider() {
  "$PYTHON_BIN" - "$REPO_ROOT" "$MEMORY_ROOT/machine/credentials.json" <<'PY'
import json, sys
from pathlib import Path
repo_root = Path(sys.argv[1])
sys.path.insert(0, str(repo_root / "core" / "scripts"))

from agent_admin_config import provider_default_base_url, provider_url_matches

p = Path(sys.argv[2])
if not p.is_file(): raise SystemExit(1)
d = json.loads(p.read_text(encoding="utf-8"))
def lookup(name):
    obj = d
    for part in name.split("."):
        if not isinstance(obj, dict) or part not in obj: return ""
        obj = obj[part]
    return "true" if obj is True else ("false" if obj is False else ("" if obj is None else str(obj)))

candidates = []
seen = set()
def add(mode, label, key="", base=""):
    sig = (mode, key or "", base or "")
    if sig in seen:
        return
    seen.add(sig)
    candidates.append((mode, label, key, base))

k, b = lookup("keys.MINIMAX_API_KEY.value"), lookup("keys.MINIMAX_BASE_URL.value")
if k:
    default_base = provider_default_base_url("claude", "minimax") or ""
    add("minimax", "claude-code + minimax (MINIMAX_API_KEY env)", k, b or default_base)
k, b = lookup("keys.ANTHROPIC_AUTH_TOKEN.value"), lookup("keys.ANTHROPIC_BASE_URL.value")
if k and provider_url_matches("claude", "minimax", b):
    add("minimax", "claude-code + minimax (ANTHROPIC_AUTH_TOKEN -> minimaxi)", k, b)
elif k and provider_url_matches("claude", "deepseek", b):
    add("deepseek", "claude-code + DeepSeek (ANTHROPIC_AUTH_TOKEN -> deepseek)", k, b)
elif k and provider_url_matches("claude", "xcode-best", b):
    add("xcode-best", "claude-code + xcode-best (ANTHROPIC_AUTH_TOKEN -> xcode.best)", k, b)
elif k and b:
    add("custom_api", f"claude-code + custom API ({b})", k, b)
k, b = lookup("keys.ANTHROPIC_API_KEY.value"), lookup("keys.ANTHROPIC_BASE_URL.value")
if k and b:
    add("custom_api", f"claude-code + custom API ({b})", k, b)
elif k:
    add("anthropic_console", "claude-code + anthropic-console (ANTHROPIC_API_KEY)", k, "")
k = lookup("keys.CLAUDE_CODE_OAUTH_TOKEN.value")
if k:
    add("oauth_token", "claude-code + oauth_token (CLAUDE_CODE_OAUTH_TOKEN)", k, "")
k, b = lookup("keys.DASHSCOPE_API_KEY.value"), lookup("keys.DASHSCOPE_BASE_URL.value")
if k:
    add("custom_api", "claude-code + custom API (DASHSCOPE_API_KEY)", k, b)
k, b = lookup("keys.ARK_API_KEY.value"), lookup("keys.ARK_BASE_URL.value")
if k:
    default_base = provider_default_base_url("claude", "ark") or ""
    add("ark", f"claude-code + ARK 火山方舟 ({b or default_base})", k, b or default_base)
if lookup("oauth.has_any") == "true":
    add("oauth", "claude-code + host oauth (Anthropic Pro / Claude.ai login)", "", "")

for mode, label, key, base in candidates:
    print("\t".join([mode, label, key, base]))
PY
}

write_provider_env() {
  local mode="$1" key="${2:-}" base="${3:-}"
  local resolved_base=""
  mkdir -p "$(dirname "$PROVIDER_ENV")" || die 22 PROVIDER_ENV_DIR_FAILED "unable to create provider env directory."
  {
    printf '# generated by scripts/install.sh for project=%s\n# provider_mode=%s\n' "$PROJECT" "$mode"
    case "$mode" in
      minimax)
        resolved_base="$(provider_base_or_default minimax "$base")"
        export_line ANTHROPIC_BASE_URL "$resolved_base"
        export_line ANTHROPIC_AUTH_TOKEN "$key"
        export_line ANTHROPIC_MODEL "${PROVIDER_MODEL:-MiniMax-M2.7-highspeed}"
        echo 'export API_TIMEOUT_MS=3000000'
        echo 'export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1'
        echo 'unset CLAUDE_CODE_OAUTH_TOKEN ANTHROPIC_API_KEY'
        ;;
      deepseek)
        resolved_base="$(provider_base_or_default deepseek "$base")"
        export_line ANTHROPIC_BASE_URL "$resolved_base"
        export_line ANTHROPIC_AUTH_TOKEN "$key"
        export_line ANTHROPIC_MODEL "${PROVIDER_MODEL:-deepseek-v4-pro[1M]}"
        echo 'export API_TIMEOUT_MS=3000000'
        echo 'export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1'
        echo 'unset CLAUDE_CODE_OAUTH_TOKEN ANTHROPIC_API_KEY'
        ;;
      ark)
        resolved_base="$(provider_base_or_default ark "$base")"
        export_line ANTHROPIC_BASE_URL "$resolved_base"
        export_line ANTHROPIC_AUTH_TOKEN "$key"
        export_line ANTHROPIC_MODEL "${PROVIDER_MODEL:-ark-code-latest}"
        echo 'export API_TIMEOUT_MS=3000000'
        echo 'export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1'
        echo 'unset CLAUDE_CODE_OAUTH_TOKEN ANTHROPIC_API_KEY'
        ;;
      xcode-best)
        resolved_base="$(provider_base_or_default xcode-best "$base")"
        export_line ANTHROPIC_BASE_URL "$resolved_base"
        export_line ANTHROPIC_AUTH_TOKEN "$key"
        [[ -n "$PROVIDER_MODEL" ]] && export_line ANTHROPIC_MODEL "$PROVIDER_MODEL" || echo 'unset ANTHROPIC_MODEL'
        echo 'unset CLAUDE_CODE_OAUTH_TOKEN ANTHROPIC_API_KEY API_TIMEOUT_MS CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC'
        ;;
      custom_api)
        export_line ANTHROPIC_BASE_URL "$base"
        export_line ANTHROPIC_AUTH_TOKEN "$key"
        [[ -n "$PROVIDER_MODEL" ]] && export_line ANTHROPIC_MODEL "$PROVIDER_MODEL" || echo 'unset ANTHROPIC_MODEL'
        echo 'unset CLAUDE_CODE_OAUTH_TOKEN ANTHROPIC_API_KEY API_TIMEOUT_MS CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC'
        ;;
      anthropic_console)
        export_line ANTHROPIC_API_KEY "$key"
        [[ -n "$PROVIDER_MODEL" ]] && export_line ANTHROPIC_MODEL "$PROVIDER_MODEL" || echo 'unset ANTHROPIC_MODEL'
        echo 'unset CLAUDE_CODE_OAUTH_TOKEN ANTHROPIC_AUTH_TOKEN ANTHROPIC_BASE_URL API_TIMEOUT_MS CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC'
        ;;
      oauth_token) export_line CLAUDE_CODE_OAUTH_TOKEN "$key"; echo 'unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN ANTHROPIC_BASE_URL ANTHROPIC_MODEL API_TIMEOUT_MS CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC' ;;
      oauth) echo 'unset CLAUDE_CODE_OAUTH_TOKEN ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN ANTHROPIC_BASE_URL ANTHROPIC_MODEL API_TIMEOUT_MS CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC' ;;
      *) die 22 PROVIDER_MODE_UNKNOWN "unknown provider mode: $mode" ;;
    esac
  } >"$PROVIDER_ENV" || die 22 PROVIDER_ENV_WRITE_FAILED "unable to write $PROVIDER_ENV"
  chmod 600 "$PROVIDER_ENV" || die 22 PROVIDER_ENV_CHMOD_FAILED "unable to chmod $PROVIDER_ENV"
}

select_provider_candidate() {
  local choice="$1"
  shift
  local -a candidates=("$@")
  local mode label key base

  if [[ ! "$choice" =~ ^[0-9]+$ ]]; then
    die 22 INVALID_PROVIDER_CHOICE "invalid provider choice: $choice"
  fi
  if (( choice < 1 || choice > ${#candidates[@]} )); then
    die 22 PROVIDER_NOT_FOUND "requested provider choice $choice but only ${#candidates[@]} candidate(s) were detected"
  fi

  IFS=$'\t' read -r mode label key base <<<"${candidates[$((choice-1))]}"
  case "$mode" in
    minimax) remember_provider_selection minimax "$key" "$base" "$(install_provider_default_model minimax)" ;;
    deepseek) remember_provider_selection deepseek "$key" "$base" "$(install_provider_default_model deepseek)" ;;
    ark) remember_provider_selection ark "$key" "$base" "$(install_provider_default_model ark)" ;;
    xcode-best) remember_provider_selection xcode-best "$key" "$base" "$FORCE_MODEL" ;;
    *) remember_provider_selection "$mode" "$key" "$base" ;;
  esac

  if [[ "$DRY_RUN" == "1" ]]; then
    printf '[dry-run] choose provider #%s via %s and write %s\n' "$choice" "$label" "$PROVIDER_ENV"
  else
    write_provider_env "$mode" "$key" "$base"
    print_provider_url_notice "$mode" "$(provider_base_or_default "$mode" "$base" || true)"
    printf 'Using selected provider candidate #%s: %s\n' "$choice" "$label"
  fi
}

_api_key_name_for_provider() {
  case "$1" in
    minimax) printf '%s\n' "MINIMAX_API_KEY" ;;
    deepseek) printf '%s\n' "DEEPSEEK_API_KEY" ;;
    ark) printf '%s\n' "ARK_API_KEY" ;;
    xcode-best) printf '%s\n' "XCODE_BEST_API_KEY" ;;
    anthropic|anthropic-console|anthropic_console) printf '%s\n' "ANTHROPIC_API_KEY" ;;
    openai) printf '%s\n' "OPENAI_API_KEY" ;;
    google|gemini) printf '%s\n' "GEMINI_API_KEY" ;;
    *) printf '%s\n' "$(printf '%s_API_KEY' "$1" | tr '[:lower:]-' '[:upper:]_')" ;;
  esac
}

_env_global_has_key() {
  local key="$1" env_file="$HOME/.agents/.env.global"
  [[ -n "${!key:-}" ]] && return 0
  [[ -f "$env_file" ]] || return 1
  grep -Eq "^[[:space:]]*(export[[:space:]]+)?${key}=" "$env_file"
}

_missing_api_keys_for_template() {
  local template_file="$REPO_ROOT/templates/${CLAWSEAT_TEMPLATE_NAME}.toml"
  [[ -f "$template_file" ]] || return 0
  "$PYTHON_BIN" - "$template_file" <<'PY'
from __future__ import annotations

import sys

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore

KEYS = {
    "minimax": "MINIMAX_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "ark": "ARK_API_KEY",
    "xcode-best": "XCODE_BEST_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "anthropic-console": "ANTHROPIC_API_KEY",
    "anthropic_console": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google": "GEMINI_API_KEY",
    "gemini": "GEMINI_API_KEY",
}

with open(sys.argv[1], "rb") as handle:
    data = tomllib.load(handle)

seen: set[tuple[str, str]] = set()
for spec in data.get("engineers", []):
    if str(spec.get("auth_mode", "")).strip() != "api":
        continue
    provider = str(spec.get("provider", "")).strip()
    if not provider:
        continue
    key = KEYS.get(provider, f"{provider.upper().replace('-', '_')}_API_KEY")
    item = (provider, key)
    if item in seen:
        continue
    seen.add(item)
    print(f"{provider}\t{key}")
PY
}

_collect_missing_api_keys() {
  local line provider key
  while IFS=$'\t' read -r provider key; do
    [[ -n "$provider" && -n "$key" ]] || continue
    _env_global_has_key "$key" || printf '%s\t%s\n' "$provider" "$key"
  done < <(_missing_api_keys_for_template)
}

_append_env_global_key() {
  local key="$1" value="$2" env_file="$HOME/.agents/.env.global"
  mkdir -p "$(dirname "$env_file")" || die 22 PROVIDER_ENV_DIR_FAILED "unable to create ~/.agents"
  touch "$env_file" || die 22 PROVIDER_ENV_WRITE_FAILED "unable to write $env_file"
  chmod 600 "$env_file" || true
  if grep -Eq "^[[:space:]]*(export[[:space:]]+)?${key}=" "$env_file"; then
    "$PYTHON_BIN" - "$env_file" "$key" "$value" <<'PY'
from __future__ import annotations

import re
import shlex
import sys
from pathlib import Path

path = Path(sys.argv[1])
key = sys.argv[2]
value = sys.argv[3]
line = f"export {key}={shlex.quote(value)}"
pattern = re.compile(rf"^(\s*export\s+)?{re.escape(key)}=.*$", re.MULTILINE)
text = pattern.sub(line, path.read_text(encoding="utf-8"))
path.write_text(text, encoding="utf-8")
PY
  else
    printf 'export %s=%q\n' "$key" "$value" >>"$env_file" \
      || die 22 PROVIDER_ENV_WRITE_FAILED "unable to write $env_file"
  fi
}

_provision_missing_api_keys() {
  local missing="$1" line provider key value
  while IFS=$'\t' read -r -u 3 provider key; do
    [[ -n "$provider" && -n "$key" ]] || continue
    printf 'Enter %s for template provider %s: ' "$key" "$provider" >&2
    if [[ -t 0 ]]; then
      read -r value < /dev/tty
    else
      read -r value
    fi
    [[ -n "$value" ]] || die 22 PROVIDER_INPUT_MISSING "missing value for $key"
    _append_env_global_key "$key" "$value"
  done 3<<<"$missing"
}

_check_api_keys_for_template() {
  [[ "$DRY_RUN" == "1" ]] && return 0
  local missing="" reply=""
  missing="$(_collect_missing_api_keys)"
  [[ -n "$missing" ]] || return 0

  if [[ "$PROVISION_KEYS" == "1" ]]; then
    _provision_missing_api_keys "$missing"
    return 0
  fi

  if [[ "${CLAWSEAT_NON_INTERACTIVE:-0}" == "1" || ! -t 0 || ! -t 1 ]]; then
    warn "missing API keys for template $CLAWSEAT_TEMPLATE_NAME; install skipped without changes:"
    printf '%s\n' "$missing" | while IFS=$'\t' read -r provider key; do
      [[ -n "$provider" && -n "$key" ]] && warn "  $provider requires $key"
    done
    warn "rerun with --provision-keys or add keys to ~/.agents/.env.global"
    return 1
  fi

  printf 'Template %s needs API keys for worker seats:\n' "$CLAWSEAT_TEMPLATE_NAME" >&2
  printf '%s\n' "$missing" | while IFS=$'\t' read -r provider key; do
    [[ -n "$provider" && -n "$key" ]] && printf '  - %s: %s\n' "$provider" "$key" >&2
  done
  printf 'A) provision missing keys now\nB) continue without provisioning\nC) cancel\nChoose [A]: ' >&2
  read -r reply
  reply="${reply:-A}"
  case "$reply" in
    A|a) _provision_missing_api_keys "$missing" ;;
    B|b) warn "continuing with missing template API keys" ;;
    C|c) die 22 PROVIDER_INPUT_MISSING "operator cancelled missing API key provisioning" ;;
    *) die 22 INVALID_PROVIDER_CHOICE "invalid choice: $reply" ;;
  esac
}

select_provider() {
  note "Step 3: primary seat provider"
  unset CLAWSEAT_INSTALL_SKIP_CLAUDE_REQUIRED
  local mode="" label="" key="" base="" reply="" primary_template_tool="" primary_template_auth="" primary_template_provider="" primary_template_model="" effective_memory_tool=""
  local -a candidates=()

  read -r primary_template_tool primary_template_auth primary_template_provider primary_template_model < <(
    template_seat_config "$PRIMARY_SEAT_ID" 2>/dev/null || printf 'claude oauth anthropic \n'
  )
  effective_memory_tool="${MEMORY_TOOL:-$primary_template_tool}"

  if [[ "$PRIMARY_SEAT_ID" == "memory" && "$effective_memory_tool" != "claude" ]]; then
    export CLAWSEAT_INSTALL_SKIP_CLAUDE_REQUIRED=1
    remember_provider_selection oauth
    if [[ "$DRY_RUN" == "1" ]]; then
      printf 'Project: %s\n' "$PROJECT"
      if [[ "$effective_memory_tool" == "codex" ]]; then
        printf '[dry-run] memory-tool=codex auth=chatgpt model=%s; skip Claude provider selection\n' "$MEMORY_MODEL"
      else
        printf '[dry-run] memory-tool=gemini auth=oauth; skip Claude provider selection\n'
      fi
    else
      if [[ "$effective_memory_tool" == "codex" ]]; then
        printf 'Using memory tool: codex (auth=chatgpt, model=%s); skipping Claude provider selection.\n' "$MEMORY_MODEL"
      else
        printf 'Using memory tool: gemini (auth=oauth); skipping Claude provider selection.\n'
      fi
    fi
    return
  fi

  if [[ -n "$FORCE_PROVIDER" && -z "$FORCE_BASE_URL" && -n "$FORCE_API_KEY" ]]; then
    case "$FORCE_PROVIDER" in
      minimax)
        [[ -n "$FORCE_MODEL" ]] || FORCE_MODEL="MiniMax-M2.7-highspeed"
        remember_provider_selection minimax "$FORCE_API_KEY" "$(provider_base_or_default minimax)" "$FORCE_MODEL"
        if [[ "$DRY_RUN" == "1" ]]; then
          printf '[dry-run] force provider=minimax via explicit api-key and write %s\n' "$PROVIDER_ENV"
        else
          write_provider_env minimax "$FORCE_API_KEY" "$(provider_base_or_default minimax)"
          print_provider_url_notice minimax "$(provider_base_or_default minimax)"
          printf 'Using forced provider: minimax (base_url=%s)\n' "$(provider_base_or_default minimax)"
        fi
        return
        ;;
      deepseek)
        [[ -n "$FORCE_MODEL" ]] || FORCE_MODEL="deepseek-v4-pro[1M]"
        remember_provider_selection deepseek "$FORCE_API_KEY" "$(provider_base_or_default deepseek)" "$FORCE_MODEL"
        if [[ "$DRY_RUN" == "1" ]]; then
          printf '[dry-run] force provider=deepseek via explicit api-key and write %s\n' "$PROVIDER_ENV"
        else
          write_provider_env deepseek "$FORCE_API_KEY" "$(provider_base_or_default deepseek)"
          print_provider_url_notice deepseek "$(provider_base_or_default deepseek)"
          printf 'Using forced provider: deepseek (base_url=%s)\n' "$(provider_base_or_default deepseek)"
        fi
        return
        ;;
      ark)
        [[ -n "$FORCE_MODEL" ]] || FORCE_MODEL="ark-code-latest"
        remember_provider_selection ark "$FORCE_API_KEY" "$(provider_base_or_default ark)" "$FORCE_MODEL"
        if [[ "$DRY_RUN" == "1" ]]; then
          printf '[dry-run] force provider=ark via explicit api-key and write %s\n' "$PROVIDER_ENV"
        else
          write_provider_env ark "$FORCE_API_KEY" "$(provider_base_or_default ark)"
          print_provider_url_notice ark "$(provider_base_or_default ark)"
          printf 'Using forced provider: ark (base_url=%s)\n' "$(provider_base_or_default ark)"
        fi
        return
        ;;
      xcode-best)
        remember_provider_selection xcode-best "$FORCE_API_KEY" "$(provider_base_or_default xcode-best)" "$FORCE_MODEL"
        if [[ "$DRY_RUN" == "1" ]]; then
          printf '[dry-run] force provider=xcode-best via explicit api-key and write %s\n' "$PROVIDER_ENV"
        else
          write_provider_env xcode-best "$FORCE_API_KEY" "$(provider_base_or_default xcode-best)"
          print_provider_url_notice xcode-best "$(provider_base_or_default xcode-best)"
          printf 'Using forced provider: xcode-best (base_url=%s)\n' "$(provider_base_or_default xcode-best)"
        fi
        return
        ;;
      anthropic_console)
        remember_provider_selection anthropic_console "$FORCE_API_KEY" "" "$FORCE_MODEL"
        if [[ "$DRY_RUN" == "1" ]]; then
          printf '[dry-run] force provider=anthropic_console via explicit api-key and write %s\n' "$PROVIDER_ENV"
        else
          write_provider_env anthropic_console "$FORCE_API_KEY"
          printf 'Using forced provider: anthropic_console\n'
        fi
        return
        ;;
    esac
  fi

  if [[ -n "$FORCE_BASE_URL" && -n "$FORCE_API_KEY" ]]; then
    remember_provider_selection custom_api "$FORCE_API_KEY" "$FORCE_BASE_URL" "$FORCE_MODEL"
    if [[ "$DRY_RUN" == "1" ]]; then
      printf '[dry-run] force provider=custom_api via explicit flags and write %s\n' "$PROVIDER_ENV"
    else
      write_provider_env custom_api "$FORCE_API_KEY" "$FORCE_BASE_URL"
      printf 'Using: explicit custom API (base_url=%s)\n' "$FORCE_BASE_URL"
    fi
    return
  fi

  while IFS= read -r line; do
    [[ -n "$line" ]] && candidates+=("$line")
  done < <(detect_provider 2>/dev/null || true)

  if [[ -n "$FORCE_PROVIDER_CHOICE" ]]; then
    select_provider_candidate "$FORCE_PROVIDER_CHOICE" "${candidates[@]}"
    return
  fi

  if [[ -n "$FORCE_PROVIDER" ]]; then
    local c forced_found=0
    for c in "${candidates[@]-}"; do
      IFS=$'\t' read -r mode label key base <<<"$c"
      if [[ "$mode" != "$FORCE_PROVIDER" ]]; then
        continue
      fi
      forced_found=1
      case "$mode" in
        minimax) remember_provider_selection "$mode" "$key" "$base" "$(install_provider_default_model "$mode")" ;;
        deepseek) remember_provider_selection "$mode" "$key" "$base" "$(install_provider_default_model "$mode")" ;;
        ark) remember_provider_selection "$mode" "$key" "$base" "$(install_provider_default_model "$mode")" ;;
        xcode-best) remember_provider_selection "$mode" "$key" "$base" "$FORCE_MODEL" ;;
        *) remember_provider_selection "$mode" "$key" "$base" ;;
      esac
      if [[ "$DRY_RUN" == "1" ]]; then
        printf '[dry-run] force provider=%s via %s and write %s\n' "$FORCE_PROVIDER" "$label" "$PROVIDER_ENV"
      else
        write_provider_env "$mode" "$key" "$base"
        print_provider_url_notice "$mode" "$(provider_base_or_default "$mode" "$base" || true)"
        printf 'Using forced provider: %s\n' "$label"
      fi
      return
    done
    if (( forced_found == 1 )); then
      return
    fi
    if [[ "$DRY_RUN" == "1" && ${#candidates[@]} -eq 0 ]]; then
      case "$FORCE_PROVIDER" in
        minimax) remember_provider_selection minimax "dry-run-placeholder-key" "$(provider_base_or_default minimax)" "$(install_provider_default_model minimax)" ;;
        deepseek) remember_provider_selection deepseek "dry-run-placeholder-key" "$(provider_base_or_default deepseek)" "$(install_provider_default_model deepseek)" ;;
        ark) remember_provider_selection ark "dry-run-placeholder-key" "$(provider_base_or_default ark)" "$(install_provider_default_model ark)" ;;
        xcode-best) remember_provider_selection xcode-best "dry-run-placeholder-key" "$(provider_base_or_default xcode-best)" "$FORCE_MODEL" ;;
        custom_api) remember_provider_selection custom_api "dry-run-placeholder-key" "$(claude_tool_default_base_url)" "$FORCE_MODEL" ;;
        anthropic_console) remember_provider_selection anthropic_console "dry-run-placeholder-key" ;;
        oauth_token) remember_provider_selection oauth_token "dry-run-placeholder-token" ;;
        oauth) remember_provider_selection oauth ;;
        *) die 22 PROVIDER_NOT_FOUND "unsupported --provider value: $FORCE_PROVIDER" ;;
      esac
      printf '[dry-run] inspect %s and write %s\n' "$MEMORY_ROOT/machine/credentials.json" "$PROVIDER_ENV"
      return
    fi
    die 22 PROVIDER_NOT_FOUND "--provider $FORCE_PROVIDER not detected on this host"
  fi

  if [[ "$DRY_RUN" == "1" ]]; then
    printf 'Project: %s\n' "$PROJECT"
    if [[ ${#candidates[@]} -eq 0 ]]; then
      remember_provider_selection custom_api "dry-run-placeholder-key" "$(claude_tool_default_base_url)"
    else
      IFS=$'\t' read -r mode label key base <<<"${candidates[0]}"
      case "$mode" in
        minimax) remember_provider_selection "$mode" "$key" "$base" "$(install_provider_default_model minimax)" ;;
        deepseek) remember_provider_selection "$mode" "$key" "$base" "$(install_provider_default_model deepseek)" ;;
        ark) remember_provider_selection "$mode" "$key" "$base" "$(install_provider_default_model ark)" ;;
        xcode-best) remember_provider_selection "$mode" "$key" "$base" "$FORCE_MODEL" ;;
        *) remember_provider_selection "$mode" "$key" "$base" ;;
      esac
    fi
    printf '[dry-run] inspect %s and write %s\n' "$MEMORY_ROOT/machine/credentials.json" "$PROVIDER_ENV"
    return
  fi

  if [[ ${#candidates[@]} -gt 0 ]]; then
    printf 'Project: %s\n' "$PROJECT"
    printf 'Detected %d Claude Code provider candidate(s) on this host:\n' "${#candidates[@]}"
    local i=1 c m l _k _b mdl
    for c in "${candidates[@]}"; do
      IFS=$'\t' read -r m l _k _b <<<"$c"
      mdl="$(install_provider_default_model "$m" 2>/dev/null || true)"
      if [[ $i -eq 1 ]]; then
        if [[ -n "$mdl" ]]; then
          printf '  [%d] %s  (model: %s)  (recommended)\n' "$i" "$l" "$mdl"
        else
          printf '  [%d] %s   (recommended)\n' "$i" "$l"
        fi
      else
        if [[ -n "$mdl" ]]; then
          printf '  [%d] %s  (model: %s)\n' "$i" "$l" "$mdl"
        else
          printf '  [%d] %s\n' "$i" "$l"
        fi
      fi
      i=$((i+1))
    done
    printf '  [c] enter custom base_url + api_key manually\n'
    require_tty_for_provider_prompt
    read -r -p "Choose [1]: " reply
    reply="${reply:-1}"
    if [[ "$reply" =~ ^[0-9]+$ ]] && (( reply >= 1 && reply <= ${#candidates[@]} )); then
      IFS=$'\t' read -r mode label key base <<<"${candidates[$((reply-1))]}"
      case "$mode" in
        minimax) remember_provider_selection "$mode" "$key" "$base" "$(install_provider_default_model minimax)" ;;
        deepseek) remember_provider_selection "$mode" "$key" "$base" "$(install_provider_default_model deepseek)" ;;
        ark) remember_provider_selection "$mode" "$key" "$base" "$(install_provider_default_model ark)" ;;
        xcode-best) remember_provider_selection "$mode" "$key" "$base" "$FORCE_MODEL" ;;
        *) remember_provider_selection "$mode" "$key" "$base" ;;
      esac
      write_provider_env "$mode" "$key" "$base"
      print_provider_url_notice "$mode" "$(provider_base_or_default "$mode" "$base" || true)"
      printf 'Using: %s\n' "$label"
      return
    fi
    if [[ ! "$reply" =~ ^[Cc]$ ]]; then
      die 22 INVALID_PROVIDER_CHOICE "invalid choice: $reply (expected 1-${#candidates[@]} or c)"
    fi
  fi

  require_tty_for_provider_prompt
  if [[ ${#candidates[@]} -eq 0 ]]; then
    printf '未检测到可用的 Claude Code 登录方式。请输入：\n'
  fi
  read -r -p "  base_url (回车=官方 Anthropic): " reply; [[ -n "$reply" ]] && base="$reply"
  read -r -p "  api_key: " reply; [[ -n "$reply" ]] && key="$reply"
  [[ -n "$key" ]] || die 22 PROVIDER_INPUT_MISSING "no provider credential supplied."
  if [[ -n "$base" ]]; then
    remember_provider_selection custom_api "$key" "$base"
    write_provider_env custom_api "$key" "$base"
  else
    remember_provider_selection anthropic_console "$key"
    write_provider_env anthropic_console "$key"
  fi
}

seat_auth_mode_for_provider_mode() {
  case "$PROVIDER_MODE" in
    minimax|deepseek|ark|xcode-best|custom_api|anthropic_console) printf '%s\n' "api" ;;
    oauth_token) printf '%s\n' "oauth_token" ;;
    oauth) printf '%s\n' "oauth" ;;
    *) die 22 PROVIDER_MODE_UNKNOWN "unknown provider mode for seat auth mapping: ${PROVIDER_MODE:-<unset>}" ;;
  esac
}

seat_provider_for_provider_mode() {
  case "$PROVIDER_MODE" in
    minimax) printf '%s\n' "minimax" ;;
    deepseek) printf '%s\n' "deepseek" ;;
    ark) printf '%s\n' "ark" ;;
    xcode-best) printf '%s\n' "xcode-best" ;;
    custom_api|anthropic_console) printf '%s\n' "anthropic-console" ;;
    oauth_token|oauth) printf '%s\n' "anthropic" ;;
    *) die 22 PROVIDER_MODE_UNKNOWN "unknown provider mode for seat provider mapping: ${PROVIDER_MODE:-<unset>}" ;;
  esac
}

seat_provider_for_explicit_provider() {
  case "$1" in
    minimax) printf '%s\n' "minimax" ;;
    deepseek) printf '%s\n' "deepseek" ;;
    ark) printf '%s\n' "ark" ;;
    xcode-best) printf '%s\n' "xcode-best" ;;
    custom_api|anthropic_console) printf '%s\n' "anthropic-console" ;;
    *) die 22 PROVIDER_MODE_UNKNOWN "unknown provider for api-seat override: ${1:-<unset>}" ;;
  esac
}

seat_model_for_provider_mode() {
  case "$PROVIDER_MODE" in
    minimax) printf '%s\n' "${PROVIDER_MODEL:-MiniMax-M2.7-highspeed}" ;;
    deepseek) printf '%s\n' "${PROVIDER_MODEL:-deepseek-v4-pro[1M]}" ;;
    ark) printf '%s\n' "${PROVIDER_MODEL:-ark-code-latest}" ;;
    xcode-best|custom_api|anthropic_console) [[ -n "$PROVIDER_MODEL" ]] && printf '%s\n' "$PROVIDER_MODEL" || true ;;
    *) return 0 ;;
  esac
}

seat_model_for_explicit_provider() {
  case "$1" in
    minimax) printf '%s\n' "${PROVIDER_MODEL:-MiniMax-M2.7-highspeed}" ;;
    deepseek) printf '%s\n' "${PROVIDER_MODEL:-deepseek-v4-pro[1M]}" ;;
    ark) printf '%s\n' "${PROVIDER_MODEL:-ark-code-latest}" ;;
    xcode-best|custom_api|anthropic_console) [[ -n "$PROVIDER_MODEL" ]] && printf '%s\n' "$PROVIDER_MODEL" || true ;;
    *) return 0 ;;
  esac
}

provider_base_for_explicit_provider() {
  case "$1" in
    minimax|deepseek|ark|xcode-best) provider_base_or_default "$1" ;;
    custom_api|anthropic_console) [[ -n "$PROVIDER_BASE" ]] && printf '%s\n' "$PROVIDER_BASE" || true ;;
    *) return 0 ;;
  esac
}

launcher_auth_for_provider() {
  case "$PROVIDER_MODE" in
    minimax|deepseek|ark|xcode-best|custom_api|anthropic_console) printf '%s\n' "custom" ;;
    oauth_token) printf '%s\n' "oauth_token" ;;
    oauth) printf '%s\n' "oauth" ;;
    *) die 22 PROVIDER_MODE_UNKNOWN "unknown provider mode for launcher auth mapping: ${PROVIDER_MODE:-<unset>}" ;;
  esac
}

launcher_tool_for_seat() {
  local seat_id="${1:-}"
  if [[ "$seat_id" == "$PRIMARY_SEAT_ID" ]] && memory_primary_skips_claude_provider; then
    primary_effective_tool
    return
  fi
  printf '%s\n' "claude"
}

launcher_auth_for_seat() {
  local seat_id="${1:-}"
  if [[ "$seat_id" == "$PRIMARY_SEAT_ID" ]] && memory_primary_uses_codex; then
    printf '%s\n' "chatgpt"
    return
  fi
  if [[ "$seat_id" == "$PRIMARY_SEAT_ID" ]] && memory_primary_uses_gemini; then
    printf '%s\n' "oauth"
    return
  fi
  launcher_auth_for_provider
}

launcher_custom_env_file_for_session() {
  local session="$1" safe_session api_key="" base_url="" model=""
  case "$PROVIDER_MODE" in
    minimax)
      api_key="$PROVIDER_KEY"
      base_url="$(provider_base_or_default minimax "$PROVIDER_BASE")"
      model="${PROVIDER_MODEL:-MiniMax-M2.7-highspeed}"
      ;;
    deepseek)
      api_key="$PROVIDER_KEY"
      base_url="$(provider_base_or_default deepseek "$PROVIDER_BASE")"
      model="${PROVIDER_MODEL:-deepseek-v4-pro[1M]}"
      ;;
    ark)
      api_key="$PROVIDER_KEY"
      base_url="$(provider_base_or_default ark "$PROVIDER_BASE")"
      model="${PROVIDER_MODEL:-ark-code-latest}"
      ;;
    xcode-best)
      api_key="$PROVIDER_KEY"
      base_url="$(provider_base_or_default xcode-best "$PROVIDER_BASE")"
      model="$PROVIDER_MODEL"
      ;;
    custom_api)
      api_key="$PROVIDER_KEY"
      base_url="$PROVIDER_BASE"
      model="$PROVIDER_MODEL"
      ;;
    anthropic_console)
      api_key="$PROVIDER_KEY"
      base_url="${PROVIDER_BASE:-$(provider_base_or_default anthropic_console)}"
      model="$PROVIDER_MODEL"
      ;;
    *)
      return 0
      ;;
  esac

  safe_session="${session//[^A-Za-z0-9_.-]/_}"
  if [[ "$DRY_RUN" == "1" ]]; then
    printf '/tmp/clawseat-install-%s.env\n' "$safe_session"
    return 0
  fi
  [[ -n "$api_key" ]] || die 22 PROVIDER_INPUT_MISSING "no provider credential available for launcher custom env."

  local env_file=""
  env_file="$(mktemp "/tmp/clawseat-install-${safe_session}.XXXXXX")" \
    || die 22 PROVIDER_ENV_WRITE_FAILED "unable to create launcher custom env file."
  chmod 600 "$env_file" || die 22 PROVIDER_ENV_CHMOD_FAILED "unable to chmod $env_file"
  {
    printf 'export LAUNCHER_CUSTOM_API_KEY=%q\n' "$api_key"
    if [[ -n "$base_url" ]]; then
      printf 'export LAUNCHER_CUSTOM_BASE_URL=%q\n' "$base_url"
    fi
    if [[ -n "$model" ]]; then
      printf 'export LAUNCHER_CUSTOM_MODEL=%q\n' "$model"
    fi
  } >"$env_file" || die 22 PROVIDER_ENV_WRITE_FAILED "unable to write $env_file"
  printf '%s\n' "$env_file"
}
