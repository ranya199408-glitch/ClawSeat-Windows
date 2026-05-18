from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

_CORE_LIB = Path(__file__).resolve().parents[1] / "lib"
if str(_CORE_LIB) not in sys.path:
    sys.path.insert(0, str(_CORE_LIB))
from env_utils import parse_env_file  # noqa: E402

from agent_admin_config import (
    DEFAULT_PATH,
    CodexProviderConfig,
    _resolve_effective_home,
    parse_codex_provider_config,
)
from seat_roles import normalize_seat_role


HOME = _resolve_effective_home()
REPO_ROOT = Path(os.environ.get("CODE_REPO_ROOT", str(HOME / "coding"))).expanduser()
RUNTIME_ROOT = HOME / ".agents" / "runtime" / "identities"
SECRETS_ROOT = HOME / ".agents" / "secrets"


def q(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def ensure_secret_permissions(path: Path) -> None:
    if path.exists():
        path.chmod(0o600)


def detect_macos_system_proxies() -> dict[str, str]:
    try:
        proc = subprocess.run(
            ["scutil", "--proxy"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return {}

    values: dict[str, str] = {}
    for raw_line in proc.stdout.splitlines():
        line = raw_line.strip()
        if " : " not in line:
            continue
        key, value = line.split(" : ", 1)
        values[key.strip()] = value.strip()

    http_proxy = ""
    https_proxy = ""
    all_proxy = ""

    if values.get("HTTPEnable") == "1" and values.get("HTTPProxy") and values.get("HTTPPort"):
        http_proxy = f"http://{values['HTTPProxy']}:{values['HTTPPort']}"
    if values.get("HTTPSEnable") == "1" and values.get("HTTPSProxy") and values.get("HTTPSPort"):
        https_proxy = f"http://{values['HTTPSProxy']}:{values['HTTPSPort']}"
    if values.get("SOCKSEnable") == "1" and values.get("SOCKSProxy") and values.get("SOCKSPort"):
        all_proxy = f"socks5://{values['SOCKSProxy']}:{values['SOCKSPort']}"
    if not any((http_proxy, https_proxy, all_proxy)):
        return {}
    return {
        "http_proxy": http_proxy,
        "https_proxy": https_proxy,
        "HTTP_PROXY": http_proxy,
        "HTTPS_PROXY": https_proxy,
        "ALL_PROXY": all_proxy,
        "NO_PROXY": "localhost,127.0.0.1,::1,.local",
    }


def write_env_file(path: Path, values: dict[str, str], ensure_dir_fn: Any, write_text_fn: Any) -> None:
    ensure_dir_fn(path.parent)
    lines = [f"{key}={shlex.quote(value)}" for key, value in sorted(values.items())]
    write_text_fn(path, "\n".join(lines) + ("\n" if lines else ""), mode=0o600)


def ensure_empty_env_file(path: Path, ensure_dir_fn: Any, write_text_fn: Any) -> None:
    if path.exists():
        return
    write_env_file(path, {}, ensure_dir_fn, write_text_fn)


def _render_codex_config_toml(provider: CodexProviderConfig, trust_paths: list[str]) -> str:
    """Render a validated CodexProviderConfig to TOML.

    Pure function — takes only the typed config + trust paths, returns
    a string. No I/O. This lets tests round-trip the render without a
    filesystem.
    """
    lines = [
        f"model_provider = {q(provider.model_provider)}",
        f"model = {q(provider.model)}",
    ]
    if provider.model_reasoning_effort is not None:
        lines.append(f"model_reasoning_effort = {q(provider.model_reasoning_effort)}")
    if provider.disable_response_storage is not None:
        lines.append(
            f"disable_response_storage = {'true' if provider.disable_response_storage else 'false'}"
        )
    if provider.preferred_auth_method is not None:
        lines.append(f"preferred_auth_method = {q(provider.preferred_auth_method)}")
    if provider.personality is not None:
        lines.append(f"personality = {q(provider.personality)}")
    lines.extend(
        [
            "",
            f"[model_providers.{provider.model_provider}]",
            f"name = {q(provider.name or provider.model_provider)}",
            f"base_url = {q(provider.base_url)}",
            f"wire_api = {q(provider.wire_api)}",
        ]
    )
    if provider.env_key is not None:
        lines.append(f"env_key = {q(provider.env_key)}")
    if provider.requires_openai_auth is not None:
        lines.append(
            f"requires_openai_auth = {'true' if provider.requires_openai_auth else 'false'}"
        )
    if provider.request_max_retries is not None:
        lines.append(f"request_max_retries = {int(provider.request_max_retries)}")
    if provider.stream_max_retries is not None:
        lines.append(f"stream_max_retries = {int(provider.stream_max_retries)}")
    if provider.stream_idle_timeout_ms is not None:
        lines.append(f"stream_idle_timeout_ms = {int(provider.stream_idle_timeout_ms)}")
    lines.append("")
    if provider.profile_name is not None:
        lines.extend(
            [
                f"[profiles.{provider.profile_name}]",
                f"model_provider = {q(provider.model_provider)}",
                f"model = {q(provider.model)}",
                "",
            ]
        )
    for path in trust_paths:
        lines.extend(
            [
                f"[projects.{q(path)}]",
                'trust_level = "trusted"',
                "",
            ]
        )
    return "\n".join(lines)


def write_codex_api_config(
    session: Any,
    codex_home: Path,
    project_repo: Path,
    provider_configs: dict[str, dict[str, Any]],
    write_text_fn: Any,
) -> None:
    raw = provider_configs.get(session.provider)
    if not raw:
        raise ValueError(f"Unsupported Codex API provider: {session.provider}")
    provider = parse_codex_provider_config(raw)

    trust_paths = [str(HOME), str(REPO_ROOT)]
    for path in (project_repo, project_repo / "openclaw"):
        if path.exists():
            trust_paths.append(str(path))

    write_text_fn(codex_home / "config.toml", _render_codex_config_toml(provider, trust_paths))


def common_env() -> dict[str, str]:
    host = os.environ
    term = host.get("TERM", "")
    if not term or term == "dumb":
        term = "xterm-256color"
    env = {
        "PATH": host.get("PATH", DEFAULT_PATH),
        "USER": host.get("USER", os.popen("id -un").read().strip() or ""),
        "SHELL": host.get("SHELL", "/bin/zsh"),
        "TERM": term,
        "LANG": host.get("LANG", "en_US.UTF-8"),
        "LC_ALL": host.get("LC_ALL", "en_US.UTF-8"),
        "TMPDIR": host.get("TMPDIR", "/tmp"),
        "SSH_AUTH_SOCK": host.get("SSH_AUTH_SOCK", ""),
        "http_proxy": host.get("http_proxy", ""),
        "https_proxy": host.get("https_proxy", ""),
        "HTTP_PROXY": host.get("HTTP_PROXY", ""),
        "HTTPS_PROXY": host.get("HTTPS_PROXY", ""),
        "ALL_PROXY": host.get("ALL_PROXY", ""),
        "NO_PROXY": host.get("NO_PROXY", ""),
    }
    if not any(env[key] for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")):
        env.update(detect_macos_system_proxies())
    return env


def identity_name(
    tool: str,
    mode: str,
    provider: str,
    engineer_id: str,
    project_name: str | None = None,
) -> str:
    parts = [tool, mode, provider]
    if project_name:
        parts.append(project_name)
    parts.append(engineer_id)
    return ".".join(parts)


def runtime_dir_for_identity(tool: str, mode: str, identity: str) -> Path:
    return RUNTIME_ROOT / tool / mode / identity


def secret_file_for(tool: str, provider: str, engineer_id: str) -> Path:
    return SECRETS_ROOT / tool / provider / f"{engineer_id}.env"


def session_name_for(project: str, engineer_id: str, tool: str) -> str:
    return f"{project}-{normalize_seat_role(engineer_id)}-{tool}"
