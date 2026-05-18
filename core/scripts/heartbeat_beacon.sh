#!/usr/bin/env bash
# heartbeat_beacon.sh <project>
# Reads ~/.agents/heartbeat/<project>.toml and sends [HEARTBEAT_TICK] via lark-cli.
# Designed to run from launchd; errors are logged to stderr but do not crash the runner.
set -euo pipefail

project="${1:?usage: heartbeat_beacon.sh <project>}"
config="${HOME}/.agents/heartbeat/${project}.toml"

if [ ! -f "$config" ]; then
    echo "heartbeat_beacon: no config at $config" >&2
    exit 1
fi

# Parse TOML fields via awk (no Python dependency).
group_id=$(awk -F '= *' '/^feishu_group_id/ {gsub(/[" \t\r]/,"",$2); print $2}' "$config")
template=$(awk -F '= *"' '/^message_template/ {sub(/"[[:space:]]*$/,"",$2); print $2}' "$config")
enabled=$(awk -F '= *' '/^enabled/ {gsub(/[" \t\r]/,"",$2); print $2}' "$config")

if [ "${enabled:-true}" = "false" ]; then
    echo "heartbeat_beacon: project '$project' heartbeat is disabled, skipping" >&2
    exit 0
fi

if [ -z "$group_id" ]; then
    echo "heartbeat_beacon: feishu_group_id not set in $config" >&2
    exit 1
fi

# Substitute {project} and {ts} in template.
ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
message="${template//\{project\}/$project}"
message="${message//\{ts\}/$ts}"

# Allow override of lark-cli path for testing.
lark_cli="${LARK_CLI_OVERRIDE:-lark-cli}"

# Send via lark-cli. Log errors but exit non-zero so launchd captures failures.
if ! "$lark_cli" --as user im +messages-send --chat-id "$group_id" --text "$message"; then
    echo "heartbeat_beacon: send failed for $project @ $(date -u +%Y-%m-%dT%H:%M:%SZ)" >&2
    exit 1
fi
