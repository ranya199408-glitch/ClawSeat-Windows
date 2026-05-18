#!/usr/bin/env bash
# Convenience wrapper: launch Claude Code via agent-launcher.sh.
set -euo pipefail
exec "$(dirname "$0")/agent-launcher.sh" --tool claude "$@"
