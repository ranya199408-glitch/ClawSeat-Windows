#!/usr/bin/env python3
"""Install the patrol Stop hook into a Claude workspace settings.json."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_HOOK = SCRIPT_DIR / "hooks" / "patrol-stop-hook.sh"


def _load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def install_patrol_hook_at(settings_path: Path, hook_script: Path = DEFAULT_HOOK) -> tuple[dict, bool]:
    settings = _load(settings_path)
    hooks = settings.get("hooks") if isinstance(settings.get("hooks"), dict) else {}
    stop = hooks.get("Stop") if isinstance(hooks.get("Stop"), list) else []
    command = f"bash {hook_script}"
    changed = False
    for entry in stop:
        if not isinstance(entry, dict) or entry.get("matcher", "") != "":
            continue
        defs = entry.get("hooks")
        if not isinstance(defs, list):
            continue
        if any(isinstance(item, dict) and item.get("command") == command for item in defs):
            hooks["Stop"] = stop
            settings["hooks"] = hooks
            return settings, changed
    stop.append({"matcher": "", "hooks": [{"type": "command", "command": command, "timeout": 10}]})
    hooks["Stop"] = stop
    settings["hooks"] = hooks
    return settings, True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--settings-path", default="")
    parser.add_argument("--hook-script", default=str(DEFAULT_HOOK))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    settings_path = Path(args.settings_path).expanduser() if args.settings_path else Path(args.workspace) / ".claude" / "settings.json"
    settings, changed = install_patrol_hook_at(settings_path, Path(args.hook_script).expanduser())
    rendered = json.dumps(settings, indent=2, ensure_ascii=False) + "\n"
    if args.dry_run:
        print(rendered, end="")
        return 0
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(rendered, encoding="utf-8")
    print("updated" if changed else "unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
