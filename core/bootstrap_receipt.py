"""
bootstrap_receipt.py — ClawSeat bootstrap receipt read/write/validation.

Writes BOOTSTRAP_RECEIPT.toml on successful bootstrap, reads it on restart,
and validates whether a cached receipt is still valid.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import tomllib

from core.resolve import try_resolve_clawseat_root as _resolve_clawseat_root
from core.lib.real_home import real_user_home


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def _resolve_agents_root() -> Path:
    agents = os.environ.get("AGENTS_ROOT", "")
    if agents:
        return Path(agents).expanduser()
    home = real_user_home()
    if (home / ".agents").exists():
        return home / ".agents"
    return home / ".agents"


def _receipt_path(project: str) -> Path:
    """Return the path to BOOTSTRAP_RECEIPT.toml for the project."""
    agents_root = _resolve_agents_root()
    heartbeat_owner = "koder"
    try:
        from core.resolve import dynamic_profile_path as _dynamic_profile_path

        profile_path = _dynamic_profile_path(project)
        if profile_path.exists():
            data = tomllib.loads(profile_path.read_text(encoding="utf-8"))
            heartbeat_owner = str(data.get("heartbeat_owner", "")).strip() or "koder"
    except Exception:
        heartbeat_owner = "koder"
    workspace = agents_root / "workspaces" / project / heartbeat_owner
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace / "BOOTSTRAP_RECEIPT.toml"


# ---------------------------------------------------------------------------
# Receipt schema
# ---------------------------------------------------------------------------

RECEIPT_VERSION = 1
RECEIPT_VALID_FOR_SECONDS = 3600 * 24  # 24 hours


def write_receipt(
    project: str,
    preflight_result: "preflight.PreflightResult",
    *,
    python_version: str | None = None,
    tmux_version: str | None = None,
    seats_available: dict[str, bool] | None = None,
    notes: dict[str, object] | None = None,
) -> Path:
    """
    Write a BOOTSTRAP_RECEIPT.toml for the given project.

    Returns the path the receipt was written to.
    """
    clawseat_root = _resolve_clawseat_root()
    clawseat_root_str = str(clawseat_root) if clawseat_root else ""

    # Resolve python version (audit M16: cap runtime so a wedged
    # interpreter cannot stall bootstrap; SubprocessError already covers
    # TimeoutExpired).
    if python_version is None:
        try:
            result = subprocess.run(
                ["python3", "--version"],
                text=True,
                capture_output=True,
                check=True,
                timeout=5,
            )
            python_version = result.stdout.strip()
        except (subprocess.SubprocessError, FileNotFoundError, OSError):
            python_version = "unknown"

    # Resolve tmux version
    if tmux_version is None:
        tmux_path = shutil.which("tmux")
        if tmux_path:
            try:
                result = subprocess.run(
                    ["tmux", "-V"],
                    text=True,
                    capture_output=True,
                    check=True,
                    timeout=5,
                )
                tmux_version = result.stdout.strip()
            except (subprocess.SubprocessError, FileNotFoundError, OSError):
                tmux_version = "unknown"
        else:
            tmux_version = "not installed"

    # Profile path
    from core.resolve import dynamic_profile_path as _dpp
    profile_path = str(_dpp(project))
    if not Path(profile_path).exists():
        profile_path = f"/tmp/{project}-profile.toml"

    preflight_section: dict[str, str] = {}
    for item in preflight_result.items:
        preflight_section[item.name] = item.status.value

    seats_available = seats_available or {"claude": False, "codex": False, "gemini": False}
    notes = notes or {}

    now = datetime.now(timezone.utc)
    iso_timestamp = now.isoformat()

    receipt = {
        "bootstrap": {
            "version": RECEIPT_VERSION,
            "project": project,
            "bootstrapped_at": iso_timestamp,
            "clawseat_root": clawseat_root_str,
            "python_version": python_version,
            "tmux_version": tmux_version,
            "dynamic_profile": profile_path,
            "adapter_type": "tmux-cli",
        },
        "preflight": preflight_section,
        "seats_available": seats_available,
        "notes": notes,
    }

    path = _receipt_path(project)
    content = _render_toml(receipt)
    path.write_text(content, encoding="utf-8")
    return path


def read_receipt(project: str) -> dict[str, object] | None:
    """
    Read the BOOTSTRAP_RECEIPT.toml for the given project.

    Returns the receipt dict or None if it doesn't exist or can't be parsed.
    """
    path = _receipt_path(project)
    if not path.exists():
        return None
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError):
        return None


def is_valid(receipt: dict[str, object]) -> tuple[bool, str]:
    """
    Check whether a receipt is still valid.

    Returns (is_valid, reason).
    """
    # Check version
    bootstrap = receipt.get("bootstrap", {})
    version = bootstrap.get("version", 0)
    if version != RECEIPT_VERSION:
        return False, f"receipt version {version} != expected {RECEIPT_VERSION}"

    # Check clawseat_root hasn't changed
    current_root = _resolve_clawseat_root()
    receipt_root = bootstrap.get("clawseat_root", "")
    if current_root and str(current_root) != receipt_root:
        return False, f"clawseat_root changed: was {receipt_root}, now {current_root}"

    # Check not expired
    try:
        raw_ts = bootstrap.get("bootstrapped_at", "")
        if raw_ts:
            ts = datetime.fromisoformat(raw_ts)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age = datetime.now(timezone.utc) - ts
            if age.total_seconds() > RECEIPT_VALID_FOR_SECONDS:
                return False, f"receipt expired ({age.days}d old)"
    except (ValueError, TypeError, OverflowError):
        return False, "invalid timestamp in receipt"

    # Check tmux server is still running
    import shutil as _sh
    tmux_bin = _sh.which("tmux")
    if tmux_bin:
        import subprocess as _sp
        try:
            _sp.run([tmux_bin, "list-sessions"], capture_output=True, check=True, timeout=5)
        except (_sp.CalledProcessError, _sp.TimeoutExpired, FileNotFoundError):
            return False, "tmux server not running (receipt stale)"

    # Check dynamic profile still exists
    project = bootstrap.get("project", "")
    if project:
        from core.resolve import dynamic_profile_path as _dpp
        profile = _dpp(str(project))
        if not profile.exists():
            return False, f"dynamic profile missing: {profile} (receipt stale)"

    return True, "valid"


def _render_toml(data: dict[str, object], prefix: str = "") -> str:
    """Render a dict to TOML string."""
    lines: list[str] = []
    simple: list[tuple[str, object]] = []
    nested: list[tuple[str, dict[str, object]]] = []

    for key, value in data.items():
        if isinstance(value, dict):
            nested.append((key, value))
        else:
            simple.append((key, value))

    for key, value in simple:
        if isinstance(value, bool):
            lines.append(f"{key} = {'true' if value else 'false'}")
        elif isinstance(value, int):
            lines.append(f"{key} = {value}")
        elif isinstance(value, float):
            lines.append(f"{key} = {repr(value)}")
        elif isinstance(value, str):
            lines.append(f'{key} = "{value}"')
        elif isinstance(value, list):
            items = ", ".join(_toml_list_item(i) for i in value)
            lines.append(f"{key} = [{items}]")
        else:
            lines.append(f'{key} = "{value}"')

    for key, value in nested:
        section = key if not prefix else f"{prefix}.{key}"
        lines.append("")
        lines.append(f"[{section}]")
        lines.append(_render_toml(value, prefix=section))

    return "\n".join(lines)


def _toml_list_item(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    return f'"{value}"'
