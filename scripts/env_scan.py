#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CORE_SCRIPTS = str(_REPO_ROOT / "core" / "scripts")
if _CORE_SCRIPTS not in sys.path:
    sys.path.insert(0, _CORE_SCRIPTS)
_CORE_LIB = str(_REPO_ROOT / "core" / "lib")
if _CORE_LIB not in sys.path:
    sys.path.insert(0, _CORE_LIB)

from agent_admin_config import is_supported_runtime_combo, provider_url_matches  # noqa: E402
from utils import now_iso  # noqa: E402


def real_home() -> Path:
    override = os.environ.get("CLAWSEAT_SCAN_HOME", "").strip()
    if override:
        return Path(override).expanduser()
    try:
        import pwd

        home = Path(pwd.getpwuid(os.getuid()).pw_dir)
        if home.is_dir():
            return home
    except Exception:
        pass
    return Path(os.environ.get("HOME", str(Path.home()))).expanduser()


def env_file_has_key(path: Path, key: str) -> bool:
    if not path.is_file():
        return False
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        name, sep, _value = line.partition("=")
        if sep and name.strip() == key:
            return True
    return False


def env_file_has_any_key(path: Path, *keys: str) -> bool:
    return any(env_file_has_key(path, key) for key in keys)


def dir_has_evidence(path: Path) -> bool:
    if not path.is_dir():
        return False
    try:
        next(path.iterdir())
    except StopIteration:
        return False
    return True


def add_auth_method(
    auth_methods: list[dict[str, object]],
    seen: set[tuple[str, str, str]],
    *,
    tool: str,
    auth_mode: str,
    provider: str,
    source: str,
) -> None:
    if not is_supported_runtime_combo(tool, auth_mode, provider):
        raise RuntimeError(
            f"env_scan attempted to emit unsupported runtime combo "
            f"{tool}/{auth_mode}/{provider}"
        )
    triple = (tool, auth_mode, provider)
    if triple in seen:
        return
    seen.add(triple)
    auth_methods.append(
        {
            "tool": tool,
            "auth_mode": auth_mode,
            "provider": provider,
            "source": source,
        }
    )


def scan() -> dict:
    home = real_home()
    claude_dir = home / ".claude"
    codex_dir = home / ".codex"
    gemini_dir = home / ".gemini"
    agents_root = home / ".agents"
    agents_secrets_root = agents_root / "secrets"
    legacy_secrets_root = home / ".agent-runtime" / "secrets"
    global_env_file = agents_root / ".env.global"
    anthropic_console_file = agents_secrets_root / "claude" / "anthropic-console.env"
    claude_ark_file = legacy_secrets_root / "claude" / "ark.env"
    claude_minimax_file = legacy_secrets_root / "claude" / "minimax.env"
    claude_xcode_file = legacy_secrets_root / "claude" / "xcode.env"
    codex_xcode_file = legacy_secrets_root / "codex" / "xcode.env"
    gemini_api_file = legacy_secrets_root / "gemini" / "primary.env"
    claude_files = sorted(p.name for p in claude_dir.glob("*")) if claude_dir.is_dir() else []
    env = os.environ
    auth_methods: list[dict[str, object]] = []
    seen_triples: set[tuple[str, str, str]] = set()
    claude_oauth_ready = (
        (claude_dir / ".credentials.json").is_file()
        or any("cred" in name or "token" in name for name in claude_files)
    )
    claude_oauth_token_ready = (
        bool(env.get("CLAUDE_CODE_OAUTH_TOKEN"))
        or env_file_has_key(global_env_file, "CLAUDE_CODE_OAUTH_TOKEN")
    )
    claude_anthropic_console_ready = (
        bool(env.get("ANTHROPIC_API_KEY"))
        or env_file_has_key(anthropic_console_file, "ANTHROPIC_API_KEY")
    )

    base_url = env.get("ANTHROPIC_BASE_URL", "").strip()
    openai_base_url = (
        env.get("OPENAI_BASE_URL", "").strip()
        or env.get("OPENAI_API_BASE", "").strip()
    )
    local_model = any(
        str(env.get(name, "")).startswith(("http://localhost", "http://127.0.0.1"))
        for name in (
            "ANTHROPIC_BASE_URL",
            "OPENAI_BASE_URL",
            "OPENAI_API_BASE",
            "OLLAMA_HOST",
            "GEMINI_BASE_URL",
        )
    )
    claude_ark_file_has_url = env_file_has_key(claude_ark_file, "ANTHROPIC_BASE_URL")
    claude_minimax_file_has_url = env_file_has_key(claude_minimax_file, "ANTHROPIC_BASE_URL")
    claude_xcode_file_has_url = env_file_has_key(claude_xcode_file, "ANTHROPIC_BASE_URL")
    codex_xcode_file_has_url = env_file_has_any_key(
        codex_xcode_file,
        "OPENAI_BASE_URL",
        "OPENAI_API_BASE",
    )
    claude_ark_ready = (
        (
            env_file_has_key(claude_ark_file, "ANTHROPIC_AUTH_TOKEN")
            and claude_ark_file_has_url
        )
        or (
            bool(env.get("ANTHROPIC_AUTH_TOKEN"))
            and provider_url_matches("claude", "ark", base_url)
        )
    )
    claude_minimax_ready = (
        (
            env_file_has_key(claude_minimax_file, "ANTHROPIC_AUTH_TOKEN")
            and claude_minimax_file_has_url
        )
        or (
            bool(env.get("ANTHROPIC_AUTH_TOKEN"))
            and provider_url_matches("claude", "minimax", base_url)
        )
    )
    claude_xcode_ready = (
        (
            env_file_has_key(claude_xcode_file, "ANTHROPIC_AUTH_TOKEN")
            and claude_xcode_file_has_url
        )
        or (
            bool(env.get("ANTHROPIC_AUTH_TOKEN"))
            and provider_url_matches("claude", "xcode-best", base_url)
        )
    )
    codex_oauth_ready = dir_has_evidence(codex_dir)
    codex_xcode_ready = (
        (
            env_file_has_key(codex_xcode_file, "OPENAI_API_KEY")
            and codex_xcode_file_has_url
        )
        or (
            bool(env.get("OPENAI_API_KEY"))
            and provider_url_matches("codex", "xcode-best", openai_base_url)
        )
    )
    gemini_oauth_ready = dir_has_evidence(gemini_dir)
    gemini_api_ready = (
        env_file_has_key(gemini_api_file, "GEMINI_API_KEY")
        or bool(env.get("GEMINI_API_KEY"))
    )

    if claude_oauth_ready:
        add_auth_method(
            auth_methods,
            seen_triples,
            tool="claude",
            auth_mode="oauth",
            provider="anthropic",
            source=str(claude_dir),
        )
    if claude_oauth_token_ready:
        add_auth_method(
            auth_methods,
            seen_triples,
            tool="claude",
            auth_mode="oauth_token",
            provider="anthropic",
            source=(
                "CLAUDE_CODE_OAUTH_TOKEN"
                if env.get("CLAUDE_CODE_OAUTH_TOKEN")
                else str(global_env_file)
            ),
        )
    if claude_anthropic_console_ready:
        add_auth_method(
            auth_methods,
            seen_triples,
            tool="claude",
            auth_mode="api",
            provider="anthropic-console",
            source=(
                "ANTHROPIC_API_KEY"
                if env.get("ANTHROPIC_API_KEY")
                else str(anthropic_console_file)
            ),
        )
    if claude_minimax_ready:
        add_auth_method(
            auth_methods,
            seen_triples,
            tool="claude",
            auth_mode="api",
            provider="minimax",
            source=(
                "ANTHROPIC_AUTH_TOKEN + ANTHROPIC_BASE_URL"
                if env.get("ANTHROPIC_AUTH_TOKEN") and provider_url_matches("claude", "minimax", base_url)
                else str(claude_minimax_file)
            ),
        )
    if claude_ark_ready:
        add_auth_method(
            auth_methods,
            seen_triples,
            tool="claude",
            auth_mode="api",
            provider="ark",
            source=(
                "ANTHROPIC_AUTH_TOKEN + ANTHROPIC_BASE_URL"
                if env.get("ANTHROPIC_AUTH_TOKEN") and provider_url_matches("claude", "ark", base_url)
                else str(claude_ark_file)
            ),
        )
    if claude_xcode_ready:
        add_auth_method(
            auth_methods,
            seen_triples,
            tool="claude",
            auth_mode="api",
            provider="xcode-best",
            source=(
                "ANTHROPIC_AUTH_TOKEN + ANTHROPIC_BASE_URL"
                if env.get("ANTHROPIC_AUTH_TOKEN") and provider_url_matches("claude", "xcode-best", base_url)
                else str(claude_xcode_file)
            ),
        )
    if codex_oauth_ready:
        add_auth_method(
            auth_methods,
            seen_triples,
            tool="codex",
            auth_mode="oauth",
            provider="openai",
            source=str(codex_dir),
        )
    if codex_xcode_ready:
        add_auth_method(
            auth_methods,
            seen_triples,
            tool="codex",
            auth_mode="api",
            provider="xcode-best",
            source=(
                "OPENAI_API_KEY + OPENAI_BASE_URL/OPENAI_API_BASE"
                if env.get("OPENAI_API_KEY") and provider_url_matches("codex", "xcode-best", openai_base_url)
                else str(codex_xcode_file)
            ),
        )
    if gemini_oauth_ready:
        add_auth_method(
            auth_methods,
            seen_triples,
            tool="gemini",
            auth_mode="oauth",
            provider="google",
            source=str(gemini_dir),
        )
    if gemini_api_ready:
        add_auth_method(
            auth_methods,
            seen_triples,
            tool="gemini",
            auth_mode="api",
            provider="google-api-key",
            source=(
                "GEMINI_API_KEY"
                if env.get("GEMINI_API_KEY")
                else str(gemini_api_file)
            ),
        )

    return {
        "scanned_at": now_iso(),
        "home": str(home),
        "claude": {
            "dir": str(claude_dir),
            "files": claude_files,
            "has_credentials_json": (claude_dir / ".credentials.json").is_file(),
        },
        "env": {
            "ANTHROPIC_API_KEY": bool(env.get("ANTHROPIC_API_KEY")),
            "ANTHROPIC_AUTH_TOKEN": bool(env.get("ANTHROPIC_AUTH_TOKEN")),
            "ANTHROPIC_BASE_URL": base_url or None,
            "CLAUDE_CODE_OAUTH_TOKEN": bool(env.get("CLAUDE_CODE_OAUTH_TOKEN")),
            "OPENAI_API_KEY": bool(env.get("OPENAI_API_KEY")),
            "OPENAI_BASE_URL": openai_base_url or None,
            "GEMINI_API_KEY": bool(env.get("GEMINI_API_KEY")),
        },
        "providers": {
            "anthropic-console": claude_anthropic_console_ready,
            "ark": claude_ark_ready,
            "minimax": claude_minimax_ready,
            "xcode-best": claude_xcode_ready or codex_xcode_ready,
            "oauth_token": claude_oauth_token_ready,
            "anthropic_proxy": bool(base_url and not provider_url_matches("claude", "anthropic-console", base_url)),
            "local_model": local_model,
        },
        "runtimes": {name: shutil.which(name) for name in ("claude", "codex", "gemini")},
        "auth_methods": auth_methods,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Scan local auth evidence and runtime binaries.")
    ap.add_argument("--output", type=Path, default=None, help="write JSON to this path instead of stdout")
    args = ap.parse_args()
    data = scan()
    blob = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(blob, encoding="utf-8")
        print(args.output)
        return 0
    print(blob, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
