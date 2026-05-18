#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
_CORE_LIB = _REPO_ROOT / "core" / "lib"
if str(_CORE_LIB) not in sys.path:
    sys.path.insert(0, str(_CORE_LIB))

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore


SEARCH_KEYS = {
    "MINIMAX_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_API_KEY",
    "MINIMAX_BASE_URL",
    "ANTHROPIC_BASE_URL",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read a path and report MiniMax readiness without leaking secrets.")
    parser.add_argument("--path", required=True, help="File or directory to inspect.")
    parser.add_argument("--category", help="Diagnostic category label to echo back.")
    return parser.parse_args()


def _infer_category(path: Path) -> str:
    if path.is_dir():
        return "directory"
    suffix = path.suffix.lower().lstrip(".")
    if suffix:
        return suffix
    return "file"


def _read_text(path: Path) -> tuple[str | None, str | None]:
    try:
        return path.read_text(encoding="utf-8"), None
    except (OSError, UnicodeDecodeError) as exc:
        if isinstance(exc, OSError):
            return None, "unreadable"
        return None, "unreadable"


def _parse_env_text(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, sep, raw_value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        if not key:
            continue
        raw_value = raw_value.strip()
        if not raw_value:
            values[key] = ""
            continue
        try:
            parsed = shlex.split(raw_value, posix=True)
        except ValueError:
            parsed = []
        values[key] = parsed[0] if parsed else raw_value.strip("\"'")
    return values


def _contains_nonempty_scalar(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (bytes, bytearray)):
        return bool(bytes(value).strip())
    if isinstance(value, (int, float, bool)):
        return True
    if isinstance(value, dict):
        return any(_contains_nonempty_scalar(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_contains_nonempty_scalar(item) for item in value)
    return bool(str(value).strip())


def _mapping_has_minimax_signal(value: object) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).upper() in SEARCH_KEYS and _contains_nonempty_scalar(item):
                return True
            if _mapping_has_minimax_signal(item):
                return True
    elif isinstance(value, (list, tuple, set)):
        return any(_mapping_has_minimax_signal(item) for item in value)
    return False


def _probe_structured(path: Path, text: str) -> bool:
    suffix = path.suffix.lower()
    try:
        if suffix == ".json":
            return _mapping_has_minimax_signal(json.loads(text))
        if suffix == ".toml":
            return _mapping_has_minimax_signal(tomllib.loads(text))
    except (json.JSONDecodeError, tomllib.TOMLDecodeError, ValueError, TypeError):
        return False
    return False


def _probe_file(path: Path) -> str:
    text, error = _read_text(path)
    if error == "unreadable" or text is None:
        return "unreadable"
    if not text.strip():
        return "missing"

    if _probe_structured(path, text):
        return "ready"

    env_values = _parse_env_text(text)
    for key in SEARCH_KEYS:
        value = env_values.get(key)
        if value is not None and str(value).strip():
            return "ready"

    return "missing"


def _probe_directory(path: Path) -> str:
    candidates: list[Path] = []
    for child in sorted(path.rglob("*")):
        if not child.is_file():
            continue
        name = child.name.lower()
        suffix = child.suffix.lower()
        if "minimax" in name or name == "credentials.json" or suffix in {".env", ".json", ".toml"}:
            candidates.append(child)
    if not candidates:
        return "missing"

    saw_unreadable = False
    for candidate in candidates:
        state = _probe_file(candidate)
        if state == "ready":
            return "ready"
        if state == "unreadable":
            saw_unreadable = True
    return "unreadable" if saw_unreadable else "missing"


def main() -> int:
    args = parse_args()
    raw_path = Path(args.path).expanduser()
    path = raw_path.resolve(strict=False)
    category = (args.category.strip() if args.category else _infer_category(path)) or _infer_category(path)

    if not path.exists():
        readiness = "missing"
    elif path.is_dir():
        readiness = _probe_directory(path)
    elif path.is_file():
        readiness = _probe_file(path)
    else:
        readiness = "unreadable"

    payload = {
        "path": str(path),
        "category": category,
        "readiness": readiness,
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
