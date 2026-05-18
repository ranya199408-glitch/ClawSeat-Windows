#!/usr/bin/env python3
"""
transport_router.py — canonical entry for all seat dispatch/notify/complete traffic.

This is the single source of truth for routing seat operations to either the
dynamic-roster (`core/migration/*_dynamic.py`) or legacy (gstack-harness
`scripts/*.py`) implementation. Routing is decided by whether the resolved
profile has `[dynamic_roster].enabled = true`.

Callers should always invoke this module via subprocess, e.g. from
`core/adapter/clawseat_adapter.py`. Do not import the underlying scripts
directly — that bypasses profile detection and can silently pin a stale
code path.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Sequence

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parent.parent.parent
MIGRATION_ROOT = REPO_ROOT / "core" / "migration"
LEGACY_ROOT = REPO_ROOT / "core" / "skills" / "gstack-harness" / "scripts"
_CORE_LIB = REPO_ROOT / "core" / "lib"
if str(_CORE_LIB) not in sys.path:
    sys.path.insert(0, str(_CORE_LIB))
from utils import load_toml  # noqa: E402

COMMAND_SCRIPTS = {
    "dispatch": {
        "dynamic": MIGRATION_ROOT / "dispatch_task_dynamic.py",
        "legacy": LEGACY_ROOT / "dispatch_task.py",
    },
    "notify": {
        "dynamic": MIGRATION_ROOT / "notify_seat_dynamic.py",
        "legacy": LEGACY_ROOT / "notify_seat.py",
    },
    "complete": {
        "dynamic": MIGRATION_ROOT / "complete_handoff_dynamic.py",
        "legacy": LEGACY_ROOT / "complete_handoff.py",
    },
    "render-console": {
        "dynamic": MIGRATION_ROOT / "render_console_dynamic.py",
        "legacy": LEGACY_ROOT / "render_console.py",
    },
}


def usage() -> str:
    commands = ", ".join(sorted(COMMAND_SCRIPTS))
    return (
        "Usage: transport_router.py <command> [--dynamic-profile PATH] --profile PATH [args...]\n"
        f"Commands: {commands}"
    )


def is_dynamic_profile(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        data = load_toml(path) or {}
    except (OSError, tomllib.TOMLDecodeError):
        return False
    dynamic = data.get("dynamic_roster", {})
    return isinstance(dynamic, dict) and bool(dynamic.get("enabled", False))


def candidate_dynamic_profiles(profile_path: Path) -> list[Path]:
    candidates = [profile_path]
    if profile_path.suffix == ".toml":
        stem = profile_path.stem
        candidates.append(profile_path.with_name(f"{stem}-dynamic.toml"))
        candidates.append(profile_path.with_name(f"{stem}.dynamic.toml"))
    return candidates


def extract_flag_value(args: Sequence[str], flag: str) -> str | None:
    index = 0
    while index < len(args):
        item = args[index]
        if item == flag:
            if index + 1 >= len(args):
                raise SystemExit(f"{flag} requires a value")
            return args[index + 1]
        prefix = f"{flag}="
        if item.startswith(prefix):
            return item[len(prefix):]
        index += 1
    return None


def strip_flag_value(args: Sequence[str], flag: str) -> tuple[list[str], str | None]:
    stripped: list[str] = []
    value: str | None = None
    skip_next = False
    for index, item in enumerate(args):
        if skip_next:
            skip_next = False
            continue
        if item == flag:
            if index + 1 >= len(args):
                raise SystemExit(f"{flag} requires a value")
            value = args[index + 1]
            skip_next = True
            continue
        prefix = f"{flag}="
        if item.startswith(prefix):
            value = item[len(prefix):]
            continue
        stripped.append(item)
    return stripped, value


def replace_flag_value(args: Sequence[str], flag: str, value: str) -> list[str]:
    replaced: list[str] = []
    skip_next = False
    replaced_flag = False
    for index, item in enumerate(args):
        if skip_next:
            skip_next = False
            continue
        if item == flag:
            if index + 1 >= len(args):
                raise SystemExit(f"{flag} requires a value")
            replaced.extend([flag, value])
            replaced_flag = True
            skip_next = True
            continue
        prefix = f"{flag}="
        if item.startswith(prefix):
            replaced.append(f"{flag}={value}")
            replaced_flag = True
            continue
        replaced.append(item)
    if not replaced_flag:
        raise SystemExit(f"missing required {flag}")
    return replaced


def resolve_profile(profile_arg: str, dynamic_override: str | None) -> tuple[Path, bool]:
    candidates: list[Path] = []
    if dynamic_override:
        candidates.append(Path(dynamic_override).expanduser())
    profile_path = Path(profile_arg).expanduser()
    candidates.extend(candidate_dynamic_profiles(profile_path))
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve(strict=False)
        if resolved in seen:
            continue
        seen.add(resolved)
        if is_dynamic_profile(candidate):
            return candidate, True
    return profile_path, False


def main() -> int:
    argv = sys.argv[1:]
    if not argv or argv[0] in {"-h", "--help"}:
        print(usage())
        return 0
    command = argv[0]
    if command not in COMMAND_SCRIPTS:
        raise SystemExit(f"unknown command {command}\n{usage()}")
    forwarded_args, dynamic_override = strip_flag_value(argv[1:], "--dynamic-profile")
    profile_arg = extract_flag_value(forwarded_args, "--profile")
    if not profile_arg:
        raise SystemExit(f"missing required --profile\n{usage()}")
    selected_profile, dynamic_mode = resolve_profile(profile_arg, dynamic_override)
    script = COMMAND_SCRIPTS[command]["dynamic" if dynamic_mode else "legacy"]
    child_args = replace_flag_value(forwarded_args, "--profile", str(selected_profile))
    completed = subprocess.run(
        [sys.executable, str(script), *child_args],
        cwd=str(REPO_ROOT),
        check=False,
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
