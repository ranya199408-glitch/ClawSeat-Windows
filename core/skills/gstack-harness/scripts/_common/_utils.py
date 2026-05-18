"""Focused helpers for gstack harness profile/session ordering."""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from _feishu import _real_user_home
from _utils import AGENTS_ROOT, PLACEHOLDER_RE, REPO_ROOT, ensure_parent, load_toml, sanitize_name, utc_now_iso, write_text

__all__ = [
    "expand_profile_value",
    "normalize_role",
    "role_sort_key",
    "_unique_seats",
    "infer_role_from_seat_id",
    "GLOBAL_ENV_PATH",
    "GLOBAL_SECRET_MAP",
    "_TOKEN_MAX_MODELS",
    "_TOKEN_MAX_DEFAULT",
    "_BYTES_PER_TOKEN",
    "_load_global_env",
    "seed_empty_secret_from_peer",
    "_infer_max_tokens",
    "_find_session_jsonls",
    "_compute_pct_from_jsonl",
    "measure_token_usage_pct",
    "write_gstack_heartbeat_receipt",
]


def expand_profile_value(value: str) -> Path:
    """Expand {PLACEHOLDER} and ~ in a profile TOML value.

    Sandbox-safe: `~` is resolved against the operator's real HOME via
    core/lib/real_home.real_user_home(), not os.path.expanduser() which
    walks `$HOME` (the seat / ancestor sandbox HOME). Without this,
    profile values like `workspace_root = "~/.agents/workspaces/install"`
    resolve to `<sandbox>/.agents/workspaces/install` and bootstrap's
    _sync_workspaces_host_to_sandbox reports `host_workspace_not_found`.
    """
    defaults = {
        "CLAWSEAT_ROOT": str(REPO_ROOT),
        "AGENTS_ROOT": str(AGENTS_ROOT),
    }

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        return os.environ.get(key, defaults.get(key, match.group(0)))

    expanded = PLACEHOLDER_RE.sub(replace, value)
    if expanded.startswith("~/") or expanded == "~":
        # Manual ~ substitution anchored on the operator's real HOME.
        # `_real_user_home` was re-exported from _feishu.py earlier in this
        # module; using it keeps every profile-loaded path sandbox-safe.
        expanded = str(_real_user_home()) + expanded[1:]
    # Path.expanduser() still runs to catch any ~user/ forms not handled above.
    return Path(expanded).expanduser()


def normalize_role(role: str) -> str:
    if role in {"planner", "planner-dispatcher"}:
        return "planner"
    if role in {"memory", "memory-oracle"}:
        return "memory"
    if role and role.startswith("cartooner-"):
        return role[len("cartooner-"):]
    return role or "specialist"


def role_sort_key(seat: str, role: str, *, heartbeat_owner: str = "") -> tuple[int, str]:
    normalized = normalize_role(role)
    priority = {
        "frontstage-supervisor": 0,
        "planner": 1,
        "builder": 2,
        "reviewer": 3,
        "patrol": 4,
        "qa": 4,
        "designer": 5,
        "specialist": 50,
    }
    if (heartbeat_owner and seat == heartbeat_owner) or normalized == "frontstage-supervisor":
        return (0, seat)
    return (priority.get(normalized, 50), seat)


def _unique_seats(values: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        seat = str(value).strip()
        if not seat or seat in seen:
            continue
        seen.add(seat)
        ordered.append(seat)
    return ordered


def infer_role_from_seat_id(seat: str, fallback: str = "", *, heartbeat_owner: str = "") -> str:
    if fallback:
        return fallback
    if heartbeat_owner and seat == heartbeat_owner:
        return "frontstage-supervisor"
    if seat == "planner":
        return "planner"
    if re.match(r"^[a-z0-9-]+-\d+$", seat):
        return seat.rsplit("-", 1)[0]
    return "specialist"

# ── Secret seeding ───────────────────────────────────────────────────

GLOBAL_ENV_PATH = AGENTS_ROOT / ".env.global"

GLOBAL_SECRET_MAP: dict[tuple[str, str], dict[str, str]] = {
    ("claude", "minimax"): {
        "ANTHROPIC_AUTH_TOKEN": "MINIMAX_API_KEY",
        "ANTHROPIC_BASE_URL": "MINIMAX_BASE_URL",
    },
    ("claude", "xcode-best"): {
        "ANTHROPIC_API_KEY": "XCODE_BEST_API_KEY",
        "ANTHROPIC_BASE_URL": "XCODE_BEST_CLAUDE_BASE_URL",
    },
    ("codex", "xcode-best"): {
        "OPENAI_API_KEY": "XCODE_BEST_API_KEY",
    },
}


def _load_global_env() -> dict[str, str]:
    if not GLOBAL_ENV_PATH.exists():
        return {}
    result: dict[str, str] = {}
    for line in GLOBAL_ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip()
    return result


def seed_empty_secret_from_peer(profile: HarnessProfile, seat: str) -> Path | None:
    agents_root = profile.workspace_root.parent.parent
    session_path = agents_root / "sessions" / profile.project_name / seat / "session.toml"
    if not session_path.exists():
        return None
    session_data = load_toml(session_path)
    secret_file_raw = str(session_data.get("secret_file", "")).strip()
    if not secret_file_raw:
        return None
    secret_file = Path(secret_file_raw).expanduser()
    ensure_parent(secret_file)
    if secret_file.exists() and secret_file.stat().st_size > 0:
        return None
    provider_dir = secret_file.parent
    if provider_dir.exists():
        for peer in sorted(provider_dir.glob("*.env")):
            if peer == secret_file or peer.stat().st_size == 0:
                continue
            # Validate peer secret has at least one KEY=VALUE line with non-empty value
            peer_content = peer.read_text(encoding="utf-8").strip()
            has_valid_key = False
            for line in peer_content.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    _k, _, _v = line.partition("=")
                    if _k.strip() and _v.strip().strip('"').strip("'"):
                        has_valid_key = True
                        break
            if not has_valid_key:
                print(f"secret_seed_skipped: {peer} has no valid KEY=VALUE entries", file=__import__('sys').stderr)
                continue
            shutil.copy2(peer, secret_file)
            secret_file.chmod(0o600)
            return peer
    tool = str(session_data.get("tool", "")).strip()
    provider = str(session_data.get("provider", "")).strip()
    mapping = GLOBAL_SECRET_MAP.get((tool, provider))
    if mapping:
        global_env = _load_global_env()
        lines = []
        for seat_var, global_var in mapping.items():
            value = global_env.get(global_var, "")
            if value:
                lines.append(f'{seat_var}="{value}"')
        if lines:
            ensure_parent(secret_file)
            write_text(secret_file, "\n".join(lines) + "\n")
            secret_file.chmod(0o600)
            return GLOBAL_ENV_PATH
    return None

_TOKEN_MAX_MODELS: dict[str, int] = {
    "opus-4-7": 200_000,
    "claude-opus-4-7": 200_000,
    "sonnet-4-6": 200_000,
    "claude-sonnet-4-6": 200_000,
    "haiku-4-5": 200_000,
    "claude-haiku-4-5": 200_000,
    "claude-opus-4-7-1m": 1_000_000,
}
_TOKEN_MAX_DEFAULT = 200_000
_BYTES_PER_TOKEN = 8


def _infer_max_tokens(model: str) -> int:
    """Hardcoded context-window size per model. ~30% error bar heuristic."""
    m = model.lower().strip()
    # Generic 1M detection (check before exact-key loop so "1m" in model name wins)
    if "1m" in m and "opus" in m:
        return 1_000_000
    # Longest key first to ensure more-specific variants win
    for key, tokens in sorted(_TOKEN_MAX_MODELS.items(), key=lambda kv: -len(kv[0])):
        if key in m:
            return tokens
    return _TOKEN_MAX_DEFAULT


def _find_session_jsonls(runtime_dir: str | None, workspace: "Path") -> list["Path"]:
    candidates: list[Path] = []
    for base in [
        Path(runtime_dir) / "home" / ".claude" / "projects" if runtime_dir else None,
        workspace / ".claude" / "projects",
    ]:
        if base is None or not base.exists():
            continue
        candidates.extend(base.glob("*/*.jsonl"))
    return candidates


def _compute_pct_from_jsonl(jsonl_path: "Path", model: str = "") -> tuple[float, str]:
    size_bytes = jsonl_path.stat().st_size
    max_tokens = _infer_max_tokens(model)
    approx_tokens = size_bytes / _BYTES_PER_TOKEN
    pct = min(1.0, approx_tokens / max_tokens)
    return pct, "session_jsonl_size"


def measure_token_usage_pct(
    profile: "HarnessProfile",
    seat: str,
    *,
    _session_jsonl_override: "Path | None" = None,
    _model_override: str = "",
) -> tuple[float | None, str]:
    import os as _os

    # Source 1: env var (forward-compat: CC may expose this natively one day)
    env_pct = _os.environ.get("CC_CONTEXT_USAGE_PCT", "").strip()
    if env_pct:
        try:
            return (min(1.0, max(0.0, float(env_pct))), "cc_env")
        except ValueError:  # silent-ok: malformed env var → fall through to next source
            pass

    # Source 2: session.jsonl size
    try:
        if _session_jsonl_override is not None:
            jsonl = _session_jsonl_override
            model = _model_override
        else:
            # Locate runtime_dir via session.toml
            agents_root = Path(_os.environ.get("AGENTS_ROOT", str(_real_user_home() / ".agents")))
            sessions_root = agents_root / "sessions"
            session_toml_path = sessions_root / profile.project_name / seat / "session.toml"
            runtime_dir = None
            model = _model_override
            if session_toml_path.exists():
                session_data = load_toml(session_toml_path)
                if session_data:
                    runtime_dir = str(session_data.get("runtime_dir", "")).strip() or None
                    if not model:
                        model = str(session_data.get("model", "")).strip()

            workspace = profile.workspace_for(seat)
            candidates = _find_session_jsonls(runtime_dir, workspace)
            if not candidates:
                return (None, "unknown")
            # Use the largest file (most active session)
            jsonl = max(candidates, key=lambda p: p.stat().st_size)

        pct, source = _compute_pct_from_jsonl(jsonl, model)
        return (pct, source)
    except Exception:
        return (None, "unknown")


def write_gstack_heartbeat_receipt(
    profile: "HarnessProfile",
    seat: str,
    *,
    status: str = "verified",
    install_fingerprint: str = "",
    manifest_fingerprint: str = "",
    verification_method: str = "gstack-harness",
    evidence: str = "",
    verified_at: str | None = None,
    _session_jsonl_override: "Path | None" = None,
    _model_override: str = "",
) -> None:
    try:
        pct, source = measure_token_usage_pct(
            profile, seat,
            _session_jsonl_override=_session_jsonl_override,
            _model_override=_model_override,
        )
    except Exception:
        pct, source = None, "unknown"
    now = utc_now_iso()
    receipt_path = profile.heartbeat_receipt_for(seat)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "version = 2",
        f'seat_id = "{seat}"',
        f'project = "{profile.project_name}"',
        f'status = "{status}"',
        f'verified_at = "{verified_at or now}"',
    ]
    if install_fingerprint:
        lines.append(f'install_fingerprint = "{install_fingerprint}"')
    if manifest_fingerprint:
        lines.append(f'manifest_fingerprint = "{manifest_fingerprint}"')
    if verification_method:
        lines.append(f'verification_method = "{verification_method}"')
    if evidence:
        lines.append(f'evidence = "{evidence}"')
    # Token fields — pct absent when unknown (readers default to None = no alert)
    if pct is not None:
        lines.append(f"token_usage_pct = {pct:.6f}")
    lines.append(f'token_usage_source = "{source}"')
    lines.append(f'token_usage_measured_at = "{now}"')
    lines.append("")
    receipt_path.write_text("\n".join(lines), encoding="utf-8")
