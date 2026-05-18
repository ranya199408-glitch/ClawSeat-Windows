#!/usr/bin/env bash
# shellcheck shell=bash
# i18n: Language switching for AI-native install UX.

_CLAWSEAT_I18N_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_LIB_DIR="${INSTALL_LIB_DIR:-$_CLAWSEAT_I18N_LIB_DIR}"
_CLAWSEAT_LANG="${CLAWSEAT_LANG:-zh}"

i18n_set() {
  case "${1:-zh}" in
    en|zh) _CLAWSEAT_LANG="$1" ;;
    /en) _CLAWSEAT_LANG="en" ;;
    /zh) _CLAWSEAT_LANG="zh" ;;
    *) _CLAWSEAT_LANG="zh" ;;
  esac
  export CLAWSEAT_LANG="$_CLAWSEAT_LANG"
}

i18n_get() {
  local key="$1"
  local lang="${_CLAWSEAT_LANG:-${CLAWSEAT_LANG:-zh}}"
  local strings_file="${INSTALL_LIB_DIR}/i18n_strings_${lang}.toml"
  if [[ -f "$strings_file" ]]; then
    python3 - "$strings_file" "$key" <<'PY' 2>/dev/null || printf '%s\n' "$key"
import sys
import tomllib

with open(sys.argv[1], "rb") as fh:
    strings = tomllib.load(fh)
print(strings.get(sys.argv[2], sys.argv[2]))
PY
  else
    printf '%s\n' "$key"
  fi
}
