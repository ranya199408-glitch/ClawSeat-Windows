"""Shared utilities — file I/O, subprocess, TOML quoting.

Extracted from _common.py. All harness scripts import these via _common.py
re-exports, so backward compatibility is preserved.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable


# ── Real-user-HOME anchor (SSOT: core/lib/real_home.py) ──────────────
#
# Scripts in this directory are imported by ancestor-mode Claude Code
# (which runs under a sandbox HOME at
# ~/.agent-runtime/identities/<tool>/<auth>/<id>/home/) as well as by
# backend tmux seats (which run under ~/.agents/runtime/identities/...).
# In both cases `Path.home()` / `$HOME` return the SANDBOX, not the
# operator's real home. If we anchor AGENT_HOME / AGENTS_ROOT /
# OPENCLAW_HOME against Path.home() we end up writing to/looking under
# the sandbox tree, which explains the live-install symptom
# `workspace_sync: <seat> status=skip reason=host_workspace_not_found
# host=<HOME>/.agent-runtime/.../<sandbox-home>/workspaces/...` —
# bootstrap resolved profile.workspace_root against the sandbox HOME
# and the matching directory simply doesn't exist there.
#
# core/lib/real_home.real_user_home() is the canonical resolver
# (CLAWSEAT_SANDBOX_HOME_STRICT → CLAWSEAT_REAL_HOME → AGENT_HOME env
# → pwd.getpwuid → Path.home() fallback). Anchor every module-level
# HOME constant on that so every callsite that reads these constants
# is automatically sandbox-safe.
_REAL_HOME_LIB = Path(__file__).resolve().parents[3] / "lib"
if str(_REAL_HOME_LIB) not in sys.path:
    sys.path.insert(0, str(_REAL_HOME_LIB))
from real_home import real_user_home as _real_user_home_ssot  # noqa: E402

if (
    "tomllib" in sys.modules
    and sys.modules["tomllib"] is None
    and "tomli" in sys.modules
    and sys.modules["tomli"] is None
):  # pragma: no cover - exercised by isolated import regression test
    raise ModuleNotFoundError(
        "clawseat requires Python 3.11+ OR tomli installed for Python <3.11. "
        "Install with: pip install tomli"
    )

from utils import load_toml as _core_load_toml, q, q_array  # noqa: E402


def _anchored_home() -> Path:
    """Return the operator's real HOME for AGENT_HOME/OPENCLAW_HOME defaults."""
    return _real_user_home_ssot()


# ── Path constants ───────────────────────────────────────────────────

REPO_ROOT = Path(
    os.environ.get("CLAWSEAT_ROOT", str(Path(__file__).resolve().parents[4]))
)
AGENT_HOME = Path(os.environ.get("AGENT_HOME", str(_anchored_home()))).expanduser()
AGENTS_ROOT = AGENT_HOME / ".agents"
SCRIPTS_ROOT = REPO_ROOT / "core" / "shell-scripts"
OPENCLAW_HOME = Path(
    os.environ.get("OPENCLAW_HOME", str(_anchored_home() / ".openclaw"))
).expanduser()
OPENCLAW_CONFIG_PATH = Path(
    os.environ.get("OPENCLAW_CONFIG_PATH", str(OPENCLAW_HOME / "openclaw.json"))
).expanduser()
OPENCLAW_AGENTS_ROOT = OPENCLAW_HOME / "agents"
OPENCLAW_FEISHU_SEND_SH = Path(
    os.environ.get(
        "CLAWSEAT_FEISHU_SEND_SH",
        os.environ.get(
            "OPENCLAW_FEISHU_SEND_SH",
            str(OPENCLAW_HOME / "skills" / "claude-desktop" / "script" / "feishu-send.sh"),
        ),
    )
).expanduser()

# ── Regex constants ──────────────────────────────────────────────────

TASK_ROW_RE = re.compile(r"^\|\s*([A-Za-z0-9_-]+)\s*\|")
CONSUMED_RE = re.compile(
    r"^Consumed:\s*(?P<task_id>\S+)\s+from\s+(?P<source>\S+)\s+at\s+(?P<ts>.+)$"
)
PLACEHOLDER_RE = re.compile(r"\{([A-Z0-9_]+)\}")


# ── Time ─────────────────────────────────────────────────────────────

def utc_now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ── File I/O ─────────────────────────────────────────────────────────

def sanitize_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip())


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    ensure_parent(path)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _load_optional_toml(path: Path) -> dict[str, Any] | None:
    return _core_load_toml(path, missing_ok=True)


load_toml = _load_optional_toml


def write_json(path: Path, payload: dict[str, Any]) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


# ── Subprocess ───────────────────────────────────────────────────────

def run_command(args: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return run_command_with_env(args, cwd=cwd, env={"HOME": str(AGENT_HOME)})


def run_command_with_env(
    args: list[str],
    *,
    cwd: Path | str | None = None,
    env: dict[str, str | None] | None = None,
) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        for key, value in env.items():
            if value is None:
                merged_env.pop(key, None)
            else:
                merged_env[key] = value
    return subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
        env=merged_env,
        check=False,
    )


def require_success(result: subprocess.CompletedProcess[str], what: str) -> None:
    """Raise RuntimeError on any non-zero exit."""
    if result.returncode == 0:
        return
    stderr = result.stderr.strip()
    stdout = result.stdout.strip()
    detail = stderr or stdout or f"exit {result.returncode}"
    raise RuntimeError(f"{what} failed: {detail}")


def require_success_allow_skip(result: subprocess.CompletedProcess[str], what: str) -> None:
    """Like require_success but tolerates exit code 2 (transport skipped)."""
    if result.returncode == 0:
        return
    if result.returncode == 2:
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        detail = stderr or stdout or "skipped"
        print(f"warn: {what} skipped: {detail}", file=sys.stderr)
        return
    stderr = result.stderr.strip()
    stdout = result.stdout.strip()
    detail = stderr or stdout or f"exit {result.returncode}"
    raise RuntimeError(f"{what} failed: {detail}")


# ── Misc helpers ─────────────────────────────────────────────────────

def summarize_status_lines(lines: Iterable[str]) -> list[str]:
    return [line.strip() for line in lines if line.strip()]


def executable_command(path: Path, *extra_args: str) -> list[str]:
    if path.suffix == ".py":
        return [sys.executable, str(path), *extra_args]
    return [str(path), *extra_args]
