#!/usr/bin/env python3
"""Install the planner Stop hook into a Claude workspace settings.json."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CLAWSEAT_ROOT = SCRIPT_DIR.parents[3]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, help="Planner Claude workspace root.")
    parser.add_argument(
        "--clawseat-root",
        default=str(DEFAULT_CLAWSEAT_ROOT),
        help="Absolute path to the ClawSeat checkout used to resolve the default hook script.",
    )
    parser.add_argument("--hook-script", default="", help="Absolute path to planner-stop-hook.sh.")
    parser.add_argument("--dry-run", action="store_true", help="Print the target config without writing.")
    return parser.parse_args()


def _load_settings(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _wanted_command(hook_script: Path) -> str:
    return f"bash {hook_script}"


def install_planner_hook(workspace: Path, hook_script: Path) -> tuple[Path, dict, bool]:
    settings_path = workspace / ".claude" / "settings.json"
    settings = _load_settings(settings_path)
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}

    stop_entries = hooks.get("Stop")
    if not isinstance(stop_entries, list):
        stop_entries = []

    command = _wanted_command(hook_script)
    changed = False
    found = False
    for entry in stop_entries:
        if not isinstance(entry, dict):
            continue
        matcher = entry.get("matcher", "")
        hook_defs = entry.get("hooks")
        if matcher != "" or not isinstance(hook_defs, list):
            continue
        for hook_def in hook_defs:
            if not isinstance(hook_def, dict):
                continue
            if hook_def.get("type") == "command" and hook_def.get("command") == command:
                found = True
                if hook_def.get("timeout") != 10:
                    hook_def["timeout"] = 10
                    changed = True
                break
        if found:
            break

    if not found:
        stop_entries.append(
            {
                "matcher": "",
                "hooks": [
                    {
                        "type": "command",
                        "command": command,
                        "timeout": 10,
                    }
                ],
            }
        )
        changed = True

    hooks["Stop"] = stop_entries
    settings["hooks"] = hooks
    return settings_path, settings, changed


def main() -> int:
    args = parse_args()
    workspace = Path(args.workspace).expanduser().resolve()
    clawseat_root = Path(args.clawseat_root).expanduser().resolve()
    hook_script = (
        Path(args.hook_script).expanduser().resolve()
        if args.hook_script
        else clawseat_root / "scripts" / "hooks" / "planner-stop-hook.sh"
    )
    if not hook_script.exists():
        print(f"error: hook script not found: {hook_script}")
        return 2

    settings_path, settings, changed = install_planner_hook(workspace, hook_script)
    rendered = json.dumps(settings, indent=2, ensure_ascii=False) + "\n"
    if args.dry_run:
        print(f"target: {settings_path}")
        print(rendered, end="")
        return 0

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(rendered, encoding="utf-8")
    print(f"{'updated' if changed else 'unchanged'}: {settings_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
