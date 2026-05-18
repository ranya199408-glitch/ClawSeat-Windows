#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Iterable

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_CORE_SCRIPTS = str(_REPO_ROOT / "core" / "scripts")
if _CORE_SCRIPTS not in sys.path:
    sys.path.insert(0, _CORE_SCRIPTS)
_CORE_LIB = str(_REPO_ROOT / "core" / "lib")
if _CORE_LIB not in sys.path:
    sys.path.insert(0, _CORE_LIB)

from agent_admin_config import tool_default_base_url
from env_utils import parse_env_file
from core.lib.real_home import real_user_home


TOOL_KEYS = {
    "claude": ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY", "API_KEY"],
    "codex": ["OPENAI_API_KEY", "API_KEY", "ANTHROPIC_API_KEY"],
    "gemini": ["GEMINI_API_KEY", "GOOGLE_API_KEY", "API_KEY"],
}

TOOL_URLS = {
    "claude": ["ANTHROPIC_BASE_URL", "OPENAI_BASE_URL", "OPENAI_API_BASE", "BASE_URL", "API_BASE_URL"],
    "codex": ["OPENAI_BASE_URL", "OPENAI_API_BASE", "BASE_URL", "API_BASE_URL"],
    "gemini": ["GOOGLE_GEMINI_BASE_URL", "GEMINI_BASE_URL", "BASE_URL", "API_BASE_URL"],
}

TOOL_MODELS = {
    "claude": ["ANTHROPIC_MODEL", "CLAUDE_MODEL", "MODEL"],
    "codex": ["OPENAI_MODEL", "CODEX_MODEL", "MODEL"],
    "gemini": ["GEMINI_MODEL", "GOOGLE_GEMINI_MODEL", "MODEL"],
}

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["list", "lookup"], default="list")
    parser.add_argument("--tool", required=True, choices=["claude", "codex", "gemini"])
    parser.add_argument("--workdir", default="")
    parser.add_argument("--label", default="")
    return parser.parse_args()


def discover_home() -> Path:
    return Path(os.environ.get("AGENT_LAUNCHER_DISCOVER_HOME", str(real_user_home()))).expanduser()


def candidate_files(tool: str, workdir: str) -> list[Path]:
    home = discover_home()
    files: list[Path] = []

    secrets_root = home / ".agent-runtime" / "secrets"
    for path in sorted((secrets_root / tool).glob("*.env")) if (secrets_root / tool).exists() else []:
        files.append(path)
    for path in sorted((secrets_root / "shared").glob("*.env")) if (secrets_root / "shared").exists() else []:
        files.append(path)

    for profile_name in [".zshrc", ".zprofile", ".bashrc", ".bash_profile", ".profile"]:
        profile_path = home / profile_name
        if profile_path.exists():
            files.append(profile_path)

    if workdir:
        wd = Path(workdir).expanduser()
        for env_name in [
            ".env",
            ".env.local",
            ".env.development",
            ".env.development.local",
            ".env.production",
            ".env.production.local",
            ".envrc",
        ]:
            env_path = wd / env_name
            if env_path.exists():
                files.append(env_path)

    seen: set[Path] = set()
    ordered: list[Path] = []
    for path in files:
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        ordered.append(path)
    return ordered


def source_rank(path: Path, tool: str, workdir: str) -> tuple[int, int, str]:
    home = discover_home()
    resolved = path.resolve()
    workdir_path = Path(workdir).expanduser().resolve() if workdir else None
    tool_secret_root = (home / ".agent-runtime" / "secrets" / tool).resolve()
    shared_secret_root = (home / ".agent-runtime" / "secrets" / "shared").resolve()

    score = 50
    if workdir_path and (resolved == workdir_path or workdir_path in resolved.parents):
        score = 10
    if resolved == tool_secret_root or tool_secret_root in resolved.parents:
        score = 0
    elif resolved == shared_secret_root or shared_secret_root in resolved.parents:
        score = 5
    elif resolved.name in {".env.local", ".env.development.local", ".env.production.local"}:
        score = min(score, 12)
    elif resolved.name in {".env", ".env.development", ".env.production", ".envrc"}:
        score = min(score, 15)
    elif resolved.name in {".zshrc", ".zprofile", ".bashrc", ".bash_profile", ".profile"}:
        score = min(score, 30)

    depth = len(resolved.parts)
    return (score, depth, str(resolved))


def mask_key(value: str) -> str:
    if len(value) <= 8:
        return value[:2] + "…" if len(value) > 2 else "••••"
    return f"{value[:4]}…{value[-4:]}"


def display_source(path: Path) -> str:
    home = discover_home()
    try:
        rel = path.relative_to(home)
        return f"~/{rel}"
    except Exception:
        return str(path)


def build_label(source: str, base_url: str, key: str, model: str) -> str:
    detail = f"{source} — {base_url} — {mask_key(key)}"
    if model:
        detail = f"{detail} · {model}"
    return f"Discovered: {detail}"


def iter_discovered(tool: str, workdir: str) -> Iterable[dict[str, str]]:
    key_names = TOOL_KEYS[tool]
    url_names = TOOL_URLS[tool]
    model_names = TOOL_MODELS[tool]
    default_url = tool_default_base_url(tool) or ""
    emitted: set[tuple[str, str, str, str]] = set()
    collected: list[dict[str, str]] = []

    for path in sorted(candidate_files(tool, workdir), key=lambda p: source_rank(p, tool, workdir)):
        values = parse_env_file(path)
        key = next((values[name] for name in key_names if values.get(name)), "")
        if not key:
            continue
        base_url = next((values[name] for name in url_names if values.get(name)), default_url)
        model = next((values[name] for name in model_names if values.get(name)), "")
        source = display_source(path)
        ident = (source, base_url, key, model)
        if ident in emitted:
            continue
        emitted.add(ident)
        collected.append({
            "source": source,
            "base_url": base_url,
            "key": key,
            "model": model,
            "label": build_label(source, base_url, key, model),
        })

    yield from collected


def main() -> int:
    args = parse_args()
    discovered = list(iter_discovered(args.tool, args.workdir))

    if args.mode == "list":
        for item in discovered:
            print(item["label"])
        return 0

    if not args.label:
        return 1
    for item in discovered:
        if item["label"] == args.label:
            print(item["key"])
            print(item["base_url"])
            print(item["model"])
            print(item["source"])
            return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
