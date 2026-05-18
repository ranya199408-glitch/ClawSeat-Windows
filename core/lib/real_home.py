"""Real user HOME resolver — survives sandbox/isolated HOME overrides.

Many ClawSeat scripts (install symlinks, workspace setup, receipt writes,
lark-cli auth lookup) need to target the operator's actual home directory
(e.g. ``~/.openclaw/``, ``~/.claude/``, ``~/.agents/``). When a caller runs
inside a harness that isolates ``HOME`` — a tmux seat sandbox, a ClawSeat
ancestor CC launcher, a Docker ``--user`` container, a CI runner — plain
``Path.home()`` and ``os.environ['HOME']`` silently return the sandbox
path. Symlinks then land under ``/sandbox/.../<sandbox-home>/`` instead of
``<HOME>/.openclaw/`` and the install appears to "succeed" while
actually being unreachable from the real user session.

This module is the single source of truth for "where is the operator's
real HOME, regardless of which sandbox we're running in".

Resolution priority (most-authoritative first):

1. ``CLAWSEAT_SANDBOX_HOME_STRICT=1`` → force ``Path.home()`` (test override,
   lets T15 regression tests assert sandbox behaviour without patching).
2. ``CLAWSEAT_REAL_HOME`` env → explicit operator override (debugging /
   unusual setups where neither AGENT_HOME nor ``pwd`` yields the right
   answer).
3. ``AGENT_HOME`` env, if it differs from ``Path.home()`` → harness-injected
   real path (``start_seat.py`` sets this before execing the seat).
4. ``pwd.getpwuid(os.getuid()).pw_dir`` → POSIX-authoritative answer,
   immune to any ``HOME`` env override. This is what makes the helper
   environment-independent: a user running ``python3 install_*.py`` from
   any harness, with any ``HOME``, still resolves their actual home.
5. ``Path.home()`` → last-resort fallback (only if the ``pwd`` database
   lookup itself fails, which should not happen on normal macOS/Linux).

Safety: :func:`real_user_home` raises :class:`SandboxHomeError` if every
probe returns a known sandbox pattern. Loud failure is preferred over
silent writes to the wrong location.
"""
from __future__ import annotations

import os
from pathlib import Path

__all__ = ["real_user_home", "is_sandbox_home", "SandboxHomeError"]


# Known sandbox HOME patterns that should NEVER be treated as real user home.
# Kept deliberately narrow: only ClawSeat-internal seat runtime and ancestor
# launcher paths. Adding generic container patterns (e.g. ``/nonexistent``)
# would mask legitimate bugs in the caller's environment setup.
_SANDBOX_PATTERNS: tuple[str, ...] = (
    "/.agents/runtime/identities/",
    "/.agent-runtime/identities/",
)


class SandboxHomeError(RuntimeError):
    """Raised when every real-HOME probe returns a sandbox-looking path."""


def is_sandbox_home(path: Path | str) -> bool:
    """Return True if *path* matches a known ClawSeat sandbox HOME pattern."""
    return any(p in str(path) for p in _SANDBOX_PATTERNS)


def _probe_pwd() -> Path | None:
    try:
        import pwd
        pw = pwd.getpwuid(os.getuid())
        if pw and pw.pw_dir:
            return Path(pw.pw_dir)
    except (ImportError, KeyError):
        pass
    return None


def real_user_home() -> Path:
    """Return the operator's real HOME. See module docstring for priority.

    Raises:
        SandboxHomeError: if all probes return a sandbox-looking path.
    """
    # 1. Strict-sandbox test override
    if os.environ.get("CLAWSEAT_SANDBOX_HOME_STRICT") == "1":
        return Path.home()

    # 2. Explicit operator override
    override = os.environ.get("CLAWSEAT_REAL_HOME")
    if override:
        candidate = Path(override).expanduser()
        if not is_sandbox_home(candidate):
            return candidate
        # override points to sandbox — ignore, fall through

    # 3. Harness-injected AGENT_HOME (must differ from current HOME)
    agent_home = os.environ.get("AGENT_HOME", "")
    if agent_home and agent_home != str(Path.home()):
        candidate = Path(agent_home).expanduser()
        if not is_sandbox_home(candidate):
            return candidate

    # 4. pwd database — OS-authoritative, env-override-immune
    pw_home = _probe_pwd()
    if pw_home is not None and not is_sandbox_home(pw_home):
        return pw_home

    # 5. Last-resort fallback
    fallback = Path.home()
    if is_sandbox_home(fallback):
        raise SandboxHomeError(
            f"Could not resolve real user home: every probe returned sandbox "
            f"path ({fallback}). Set CLAWSEAT_REAL_HOME to your real home "
            f"(e.g. <HOME> or /home/<you>) and re-run. Set "
            f"CLAWSEAT_SANDBOX_HOME_STRICT=1 only if you genuinely want the "
            f"sandbox path (test fixtures)."
        )
    return fallback
