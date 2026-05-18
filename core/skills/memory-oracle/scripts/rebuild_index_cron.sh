#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_PATH="${HOME}/.agents/memory/_index_rebuild.log"

mkdir -p "$(dirname "$LOG_PATH")"
python3 "$SCRIPT_DIR/scan_index.py" rebuild --all >>"$LOG_PATH" 2>&1
